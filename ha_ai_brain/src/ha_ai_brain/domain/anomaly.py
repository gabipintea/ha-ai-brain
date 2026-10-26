"""
Generic, signal-based anomaly detection learned per entity from the household's own history.

Nothing here knows about specific devices: every detector works from statistics (how long an entity usually
stays in a state, how often it changes, what range a sensor normally has at this hour) and from Home Assistant's
own semantic classes. Safety relevance only affects *severity*, never whether something is examined.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any

from ha_ai_brain.domain.baselines import NumericBaseline
from ha_ai_brain.domain.expectations import (
    NON_STATES,
    ExceptionFinding,
    classify_severity,
    is_safety_entity,
)
from ha_ai_brain.domain.models import EntityState, Transition
from ha_ai_brain.domain.timeutil import parse_iso, to_local

MIN_DWELL_SAMPLES = 6
MIN_ACTIVE_DAYS = 5
CUMULATIVE_STATE_CLASSES = frozenset({"total", "total_increasing"})
SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    k = (len(ordered) - 1) * pct
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def fmt_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60.0))
    if minutes < 90:
        return f"{minutes} min"
    hours = minutes / 60.0
    return f"{hours:.1f} h" if hours < 48 else f"{hours / 24.0:.1f} days"


@dataclass
class DiscreteProfile:
    """What 'normal' looks like for one switchable / binary entity."""

    entity_id: str
    n_transitions: int
    days_active: float
    rest_state: str | None  # the state it spends most of its time in
    dwell: dict[str, tuple[int, float, float]] = field(default_factory=dict)  # state -> (n, p50 s, p90 s)
    per_day: float = 0.0
    gap_p95: float | None = None  # seconds between consecutive changes
    hourly_mean: float = 0.0
    hourly_std: float = 0.0


def build_discrete_profiles(transitions: list[Transition], window_start: datetime, now: datetime) -> dict[str, DiscreteProfile]:
    by_entity: dict[str, list[Transition]] = defaultdict(list)
    for t in transitions:
        by_entity[t.entity_id].append(t)
    total_hours = max(1.0, (now - window_start).total_seconds() / 3600.0)
    profiles: dict[str, DiscreteProfile] = {}
    for eid, rows in by_entity.items():
        rows.sort(key=lambda t: t.ts)
        if len(rows) < 3:
            continue
        dwell_lists: dict[str, list[float]] = defaultdict(list)
        share: dict[str, float] = defaultdict(float)
        first = rows[0]
        if first.old_state and first.old_state not in NON_STATES:
            share[first.old_state] += max(0.0, (first.ts - window_start).total_seconds())
        for cur, nxt in zip(rows, rows[1:]):
            seconds = (nxt.ts - cur.ts).total_seconds()
            if cur.new_state not in NON_STATES and seconds >= 0:
                dwell_lists[cur.new_state].append(seconds)
                share[cur.new_state] += seconds
        last = rows[-1]
        if last.new_state not in NON_STATES:
            share[last.new_state] += max(0.0, (now - last.ts).total_seconds())
        gaps = [(b.ts - a.ts).total_seconds() for a, b in zip(rows, rows[1:])]
        buckets: dict[int, int] = defaultdict(int)
        for t in rows:
            buckets[int(t.ts.timestamp() // 3600)] += 1
        n = len(rows)
        mean = n / total_hours
        sumsq = sum(c * c for c in buckets.values())
        std = math.sqrt(max(0.0, sumsq / total_hours - mean * mean))
        days = max(1.0, (rows[-1].ts - rows[0].ts).total_seconds() / 86400.0)
        profiles[eid] = DiscreteProfile(
            entity_id=eid,
            n_transitions=n,
            days_active=days,
            rest_state=max(share, key=share.get) if share else None,
            dwell={s: (len(v), _percentile(v, 0.5), _percentile(v, 0.9)) for s, v in dwell_lists.items() if v},
            per_day=n / days,
            gap_p95=_percentile(gaps, 0.95) if gaps else None,
            hourly_mean=mean,
            hourly_std=std,
        )
    return profiles


def _finding(
    kind: str,
    st: EntityState,
    household: dict[str, Any] | None,
    local_now: datetime,
    summary: str,
    expected: str,
    confidence: float,
    since: datetime | None,
    severity: str | None = None,
) -> ExceptionFinding:
    return ExceptionFinding(
        kind=kind,
        entity_id=st.entity_id,
        severity=severity or classify_severity(st, household, local_now),
        summary=summary,
        expected_state=expected,
        current_state=st.state,
        confidence=confidence,
        since=since,
    )


def _label(st: EntityState) -> str:
    return str(st.attributes.get("friendly_name") or st.entity_id)


def find_dwell_anomalies(
    states: dict[str, EntityState],
    profiles: dict[str, DiscreteProfile],
    now: datetime,
    tz: tzinfo,
    household: dict[str, Any] | None = None,
) -> list[ExceptionFinding]:
    """An entity has stayed in a non-resting state far longer than it ever (or almost ever) did before."""
    out: list[ExceptionFinding] = []
    local_now = to_local(now, tz)
    for eid, prof in profiles.items():
        st = states.get(eid)
        if st is None or st.state in NON_STATES or prof.rest_state is None or st.state == prof.rest_state:
            continue
        stats = prof.dwell.get(st.state)
        if not stats or stats[0] < MIN_DWELL_SAMPLES:
            continue
        n, p50, p90 = stats
        elapsed = (now - st.last_changed).total_seconds()
        if elapsed > max(2 * p90, p90 + 900, 1200):
            out.append(
                _finding(
                    "dwell_anomaly", st, household, local_now,
                    f"Exception: {_label(st)} has been '{st.state}' for {fmt_duration(elapsed)}; it normally stays that way "
                    f"for about {fmt_duration(p50)} and almost never more than {fmt_duration(p90)} ({n} past occurrences).",
                    prof.rest_state, min(1.0, n / 20.0), st.last_changed,
                )
            )
    return out


def find_silent_entities(
    states: dict[str, EntityState],
    profiles: dict[str, DiscreteProfile],
    now: datetime,
    tz: tzinfo,
    household: dict[str, Any] | None = None,
) -> list[ExceptionFinding]:
    """An entity that reliably changes several times a day has stopped changing (dead sensor, lost link, stuck device)."""
    out: list[ExceptionFinding] = []
    local_now = to_local(now, tz)
    for eid, prof in profiles.items():
        st = states.get(eid)
        if st is None or st.state in NON_STATES or prof.days_active < MIN_ACTIVE_DAYS or prof.per_day < 2 or not prof.gap_p95:
            continue
        silence = (now - st.last_changed).total_seconds()
        if silence > max(3 * prof.gap_p95, 6 * 3600):
            out.append(
                _finding(
                    "silent_entity", st, household, local_now,
                    f"Exception: {_label(st)} has not changed for {fmt_duration(silence)}, but it normally changes about "
                    f"{prof.per_day:.1f} times a day (longest usual pause {fmt_duration(prof.gap_p95)}).",
                    "changing regularly", min(1.0, prof.days_active / 14.0), st.last_changed,
                    severity="warning" if is_safety_entity(st) else "info",
                )
            )
    return out


def find_flapping(
    recent_counts: dict[str, int],
    states: dict[str, EntityState],
    profiles: dict[str, DiscreteProfile],
    now: datetime,
    tz: tzinfo,
    household: dict[str, Any] | None = None,
) -> list[ExceptionFinding]:
    """Far more state changes in the last hour than this entity ever produces (chattering contact, cycling device)."""
    out: list[ExceptionFinding] = []
    local_now = to_local(now, tz)
    for eid, count in recent_counts.items():
        prof, st = profiles.get(eid), states.get(eid)
        if prof is None or st is None:
            continue
        if count >= max(8, prof.hourly_mean + 4 * prof.hourly_std):
            out.append(
                _finding(
                    "flapping", st, household, local_now,
                    f"Exception: {_label(st)} changed state {count} times in the last hour (usually about {prof.hourly_mean:.1f}).",
                    "stable", min(1.0, count / 20.0), None, severity="info",
                )
            )
    return out


def find_stuck_unavailable(
    states: dict[str, EntityState],
    now: datetime,
    tz: tzinfo,
    *,
    min_minutes: int = 60,
    group_threshold: int = 5,
) -> list[ExceptionFinding]:
    """Entities unavailable for a long time; many at once collapse into a single finding (integration / network outage)."""
    stuck = [
        s for s in states.values()
        if s.state in ("unavailable", "unknown") and s.domain not in ("automation", "scene", "script", "update")
        and (now - s.last_changed) >= timedelta(minutes=min_minutes)
    ]
    if not stuck:
        return []
    if len(stuck) >= group_threshold:
        first = min(stuck, key=lambda s: s.last_changed)
        return [
            ExceptionFinding(
                kind="stuck_unavailable", entity_id=first.entity_id, severity="warning",
                summary=f"Exception: {len(stuck)} entities have been unavailable for over {min_minutes} min (for example {_label(first)}) - "
                        "this usually points to one integration, hub or network problem.",
                expected_state="available", current_state=first.state, since=first.last_changed,
            )
        ]
    return [
        ExceptionFinding(
            kind="stuck_unavailable", entity_id=s.entity_id, severity="warning" if is_safety_entity(s) else "info",
            summary=f"Exception: {_label(s)} has been {s.state} for {fmt_duration((now - s.last_changed).total_seconds())}.",
            expected_state="available", current_state=s.state, since=s.last_changed,
        )
        for s in stuck
    ]


def find_numeric_anomalies(
    states: dict[str, EntityState],
    hourly_rows: dict[str, list[tuple[str, int, float]]],
    baselines: dict[str, NumericBaseline],
    now: datetime,
    tz: tzinfo,
    household: dict[str, Any] | None = None,
) -> list[ExceptionFinding]:
    """Sensors far outside their usual range for this hour (sustained over two readings) and sensors that went quiet."""
    out: list[ExceptionFinding] = []
    local_now = to_local(now, tz)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    for eid, st in states.items():
        if st.domain != "sensor" or st.attributes.get("state_class") in CUMULATIVE_STATE_CLASSES:
            continue
        if st.device_class in ("timestamp", "date", "enum"):
            continue
        rows = hourly_rows.get(eid)
        if not rows or len(rows) < 12:
            continue

        # Stale: a sensor that reports at least every ~30 min has been silent for hours
        per_hour = sorted(n for _, n, _ in rows)
        typical_n = per_hour[len(per_hour) // 2]
        silence = (now - st.last_updated).total_seconds()
        if st.state not in NON_STATES and typical_n >= 2 and silence > 3 * 3600:
            out.append(
                _finding(
                    "stale_sensor", st, household, local_now,
                    f"Exception: {_label(st)} has not reported for {fmt_duration(silence)}, but it normally reports "
                    f"about {typical_n} times an hour.",
                    "reporting regularly", 0.8, st.last_updated, severity="warning" if is_safety_entity(st) else "info",
                )
            )
            continue

        value = st.numeric_value
        base = baselines.get(eid)
        if value is None or base is None:
            continue
        z_now = base.zscore(value, now)
        previous = [(parse_iso(h), mean) for h, _, mean in rows]
        previous = [(t, m) for t, m in previous if t is not None and t < current_hour]
        if z_now is None or not previous:
            continue
        z_prev = base.zscore(previous[-1][1], previous[-1][0])
        if z_prev is None or abs(z_now) < 3.5 or abs(z_prev) < 3.0 or (z_now > 0) != (z_prev > 0):
            continue
        stat = base.stats.get((_day_class(local_now), local_now.hour))
        usual = stat[1] if stat else value
        unit = st.unit_of_measurement or ""
        out.append(
            _finding(
                "numeric_excursion", st, household, local_now,
                f"Exception: {_label(st)} reads {value:g}{unit}, far from its usual {usual:.1f}{unit} for this time of day, "
                f"and the previous hour was also out of range.",
                f"about {usual:.1f}{unit}", min(1.0, abs(z_now) / 8.0), None,
            )
        )
    return out


def _day_class(local: datetime) -> str:
    return "weekend" if local.weekday() >= 5 else "weekday"


SUPPRESS_WHEN_AWAY = frozenset({"silent_entity", "routine_deviation", "dwell_anomaly"})


def prioritise(
    findings: list[ExceptionFinding],
    household: dict[str, Any] | None,
    *,
    limit: int,
) -> list[ExceptionFinding]:
    """One finding per entity (most specific wins), calm entities left alone while the home is empty, worst first."""
    anyone_home = ((household or {}).get("presence") or {}).get("anyone_home")
    specificity = {
        "security_while_away": 0, "automation_missed": 1, "routine_deviation": 2, "numeric_excursion": 2,
        "dwell_anomaly": 3, "flapping": 4, "stale_sensor": 4, "silent_entity": 5, "stuck_unavailable": 6,
    }
    best: dict[str, ExceptionFinding] = {}
    for f in findings:
        if anyone_home is False and f.kind in SUPPRESS_WHEN_AWAY and f.severity == "info":
            continue
        cur = best.get(f.entity_id)
        if cur is None or specificity.get(f.kind, 9) < specificity.get(cur.kind, 9):
            best[f.entity_id] = f
    ranked = sorted(best.values(), key=lambda f: (SEVERITY_RANK.get(f.severity, 3), -f.confidence))
    return ranked[:limit]
