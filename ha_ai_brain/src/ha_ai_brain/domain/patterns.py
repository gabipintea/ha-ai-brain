"""Deterministic (zero-token) mining of recurring household behaviour from recorded state transitions."""

from __future__ import annotations

import hashlib
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

from ha_ai_brain.domain.models import NativeAutomationProposal, Transition
from ha_ai_brain.domain.sequence_filters import (
    RULE_FAN_OUT,
    RULE_MIRROR,
    RULE_SAME_TIME,
    RULE_SHARED_CAUSE,
    SequenceReport,
    SuppressedHabit,
    build_cause_pool,
    find_burst_transitions,
    find_common_cause,
    is_fan_out,
    reason_fan_out,
    reason_same_time,
    reason_shared_cause,
    time_anchor,
)
from ha_ai_brain.domain.service_semantics import ACTUATOR_DOMAINS, SCRIPT_RUN_STATE, service_for_state
from ha_ai_brain.domain.timeutil import (
    circular_distance,
    circular_mean,
    day_class,
    format_minute,
    minute_of_day,
    to_local,
)

NON_STATES = frozenset({"unavailable", "unknown", "", "none"})
# Transitions caused by the brain itself or by an existing automation are not "human habits".
AUTOMATED_ORIGINS = frozenset({"ai_brain", "ha_automation"})
# In-between states of one physical movement: never a habit trigger ("blind opening" -> "blind open" is one action).
TRANSITIONAL_STATES = frozenset({"opening", "closing", "locking", "unlocking", "arming", "disarming", "pending"})
TRIGGER_DOMAINS = frozenset({"binary_sensor", "person", "lock", "cover", "light", "switch", "input_boolean"})
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]
WEEKEND = ["sat", "sun"]


@dataclass
class MinedPattern:
    pattern_id: str
    kind: str  # "time_habit" | "sequence"
    entity_id: str
    to_state: str
    day_class: str  # "all" | "weekday" | "weekend"
    support_days: int
    observed_days: int
    confidence: float
    description: str
    minute_of_day: float | None = None
    spread_minutes: float | None = None
    trigger_entity: str | None = None
    trigger_state: str | None = None
    median_lag_seconds: float | None = None
    lift: float | None = None
    covered_by: str | None = None  # alias of an existing automation that already implements it

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("confidence", "minute_of_day", "spread_minutes", "median_lag_seconds", "lift"):
            if data.get(key) is not None:
                data[key] = round(float(data[key]), 2)
        return data


def observed_days(data_start: datetime, data_end: datetime, tz: tzinfo) -> dict[str, int]:
    """Number of (mostly) complete local days with recorded data, split by weekday / weekend."""
    start = to_local(data_start, tz)
    end = to_local(data_end, tz)
    first = start.date() + timedelta(days=1) if (end.date() - start.date()).days >= 3 else start.date()
    counts = {"weekday": 0, "weekend": 0}
    d = first
    while d <= end.date():
        counts["weekend" if d.weekday() >= 5 else "weekday"] += 1
        d += timedelta(days=1)
    counts["all"] = counts["weekday"] + counts["weekend"]
    return counts


def _is_habit_transition(t: Transition) -> bool:
    return (
        t.domain in ACTUATOR_DOMAINS
        and t.origin not in AUTOMATED_ORIGINS
        and t.new_state not in NON_STATES
        and t.old_state not in NON_STATES
        and t.old_state != t.new_state
        and service_for_state(t.domain, t.new_state) is not None
    )


def _is_script_run(t: Transition) -> bool:
    """A script the household started by hand (runs started by automations or the brain are not habits)."""
    return t.domain == "script" and t.new_state == SCRIPT_RUN_STATE and t.origin not in AUTOMATED_ORIGINS


def _best_cluster(items: list[tuple[Any, int]], tolerance: int) -> tuple[float, list[tuple[Any, int]]]:
    """
    Densest group of (date, minute) items that fit in a +-tolerance window on the 24 h clock, at most one item per date.
    Sliding window over the sorted (and wrapped) minutes: O(n log n) instead of comparing every pair.
    """
    n = len(items)
    if n == 0:
        return 0.0, []
    width = 2 * tolerance
    pts = sorted((m, d) for d, m in items)
    ext = pts + [(m + 1440, d) for m, d in pts]  # wrap past midnight

    counts: dict[Any, int] = {}
    distinct = 0
    best = (0, 0, 0, 0)  # (distinct dates, -span, start, end)
    j = 0
    for i in range(n):
        j = max(j, i)
        while j < len(ext) and j - i < n and ext[j][0] - ext[i][0] <= width:
            d = ext[j][1]
            counts[d] = counts.get(d, 0) + 1
            if counts[d] == 1:
                distinct += 1
            j += 1
        span = ext[j - 1][0] - ext[i][0] if j > i else 0
        if (distinct, -span) > (best[0], best[1]):
            best = (distinct, -span, i, j)
        d = ext[i][1]
        counts[d] -= 1
        if counts[d] == 0:
            distinct -= 1
            del counts[d]

    _, _, start, end = best
    window_minutes = [m % 1440 for m, _ in ext[start:end]]
    centre = circular_mean(window_minutes)
    refined: dict[Any, int] = {}
    for d, m in items:
        dist = circular_distance(m, centre)
        if dist <= tolerance and (d not in refined or dist < circular_distance(refined[d], centre)):
            refined[d] = m
    members = [(d, m) for d, m in refined.items()]
    return (circular_mean([m for _, m in members]) if members else centre), members


def _class_support(rows: list[tuple[Any, int, str]], centre: float, tolerance: int, cls: str) -> int:
    return len({d for d, m, c in rows if c == cls and circular_distance(m, centre) <= tolerance})


def _pid(*parts: Any) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def mine_time_habits(
    transitions: list[Transition],
    data_start: datetime,
    data_end: datetime,
    tz: tzinfo,
    *,
    tolerance: int = 20,
    min_support: int = 3,
    min_confidence: float = 0.6,
    max_clusters_per_key: int = 2,
) -> list[MinedPattern]:
    obs = observed_days(data_start, data_end, tz)
    if obs["all"] < 3:
        return []

    groups: dict[tuple[str, str], list[tuple[Any, int, str]]] = defaultdict(list)
    for t in transitions:
        if not (_is_habit_transition(t) or _is_script_run(t)):
            continue
        local = to_local(t.ts, tz)
        groups[(t.entity_id, t.new_state)].append((local.date(), minute_of_day(local), day_class(local)))

    patterns: list[MinedPattern] = []
    for (entity_id, state), rows in groups.items():
        for cls in ("all", "weekday", "weekend"):
            denominators = obs[cls]
            needed = min_support if cls != "weekend" else 2
            if denominators < (3 if cls != "weekend" else 2):
                continue
            remaining = [(d, m) for d, m, c in rows if cls == "all" or c == cls]
            found_for_cls: list[MinedPattern] = []
            for _ in range(max_clusters_per_key):
                if len(remaining) < needed:
                    break
                centre, members = _best_cluster(remaining, tolerance)
                if len({d for d, _ in members}) < needed:
                    break
                support = len({d for d, _ in members})
                conf = support / denominators
                member_set = set(members)
                remaining = [r for r in remaining if r not in member_set]
                threshold = min_confidence if cls == "all" else min_confidence + 0.1
                if conf < threshold:
                    continue
                spread = max(circular_distance(m, centre) for _, m in members)
                eff_cls, eff_support, eff_denominators = cls, support, denominators
                if cls == "all":
                    # A habit that happens (almost) only on weekdays or only on weekends must not become a daily rule.
                    sw = _class_support(rows, centre, tolerance, "weekday") / max(1, obs["weekday"])
                    se = _class_support(rows, centre, tolerance, "weekend") / max(1, obs["weekend"])
                    if sw >= 0.85 and se < 0.35 and obs["weekday"] >= 3:
                        eff_cls = "weekday"
                        eff_support = _class_support(rows, centre, tolerance, "weekday")
                        eff_denominators = obs["weekday"]
                    elif se >= 0.85 and sw < 0.35 and obs["weekend"] >= 2:
                        eff_cls = "weekend"
                        eff_support = _class_support(rows, centre, tolerance, "weekend")
                        eff_denominators = obs["weekend"]
                    conf = eff_support / eff_denominators
                support, denominators = eff_support, eff_denominators
                cls_text = {"all": "every day", "weekday": "on weekdays", "weekend": "on weekends"}[eff_cls]
                found_for_cls.append(
                    MinedPattern(
                        pattern_id=_pid("th", entity_id, state, eff_cls, round(centre / 30)),
                        kind="time_habit",
                        entity_id=entity_id,
                        to_state=state,
                        day_class=eff_cls,
                        support_days=support,
                        observed_days=denominators,
                        confidence=min(1.0, conf),
                        minute_of_day=centre,
                        spread_minutes=spread,
                        description=(
                            f"{entity_id} {'is run' if state == SCRIPT_RUN_STATE else f'is set to {state!r}'} around {format_minute(centre)} {cls_text} "
                            f"({support} of {denominators} days, ±{int(spread)} min)"
                        ),
                    )
                )
            patterns.extend(found_for_cls)
        # When an every-day pattern exists, the class-specific duplicates add no information.
        all_centres = [p.minute_of_day for p in patterns if p.entity_id == entity_id and p.to_state == state and p.day_class == "all"]
        if all_centres:
            patterns = [
                p
                for p in patterns
                if not (
                    p.entity_id == entity_id
                    and p.to_state == state
                    and p.day_class != "all"
                    and any(circular_distance(p.minute_of_day or 0, c or 0) <= tolerance for c in all_centres)
                )
            ]
    unique: dict[str, MinedPattern] = {}
    for p in patterns:
        if p.pattern_id not in unique or p.confidence > unique[p.pattern_id].confidence:
            unique[p.pattern_id] = p
    patterns = sorted(unique.values(), key=lambda p: (p.confidence, p.support_days), reverse=True)
    return patterns


def mine_sequences(
    transitions: list[Transition],
    data_start: datetime,
    data_end: datetime,
    **kwargs: Any,
) -> list[MinedPattern]:
    """'When A happens, the household does B within a few minutes' relations, filtered by statistical lift and shared-cause checks."""
    return mine_sequences_report(transitions, data_start, data_end, **kwargs)[0]


def mine_sequences_report(
    transitions: list[Transition],
    data_start: datetime,
    data_end: datetime,
    *,
    tz: tzinfo = timezone.utc,
    max_lag_seconds: int = 600,
    min_hits: int = 4,
    min_confidence: float = 0.7,
    min_lift: float = 3.0,
    max_keys: int = 150,
    max_per_effect: int = 2,
    cause_events: list[Transition] | None = None,
) -> tuple[list[MinedPattern], SequenceReport]:
    """
    Same as `mine_sequences`, plus a report of every relation that looked like a habit but was dropped, and why:
    scripted bursts and automated triggers are ignored up front (#4); surviving pairs are rejected when they share a hidden cause
    (#1), both sit at a fixed time of day (#2), or one trigger fans out to many devices (#3).
    """
    report = SequenceReport()
    span = max(3600.0, (data_end - data_start).total_seconds())

    bursts = find_burst_transitions(transitions, _is_habit_transition)
    report.ignored_burst_transitions = len(bursts)
    # Automation / script runs are not device changes, but they are the most likely hidden cause behind a pair.
    cause_pool = build_cause_pool(transitions + (cause_events or []), min_hits)

    trig_times: dict[tuple[str, str], list[float]] = defaultdict(list)
    effect_times: dict[tuple[str, str], list[float]] = defaultdict(list)
    for i, t in enumerate(transitions):
        if t.new_state in NON_STATES or t.old_state == t.new_state or i in bursts:
            continue
        ts = t.ts.timestamp()
        if t.domain in TRIGGER_DOMAINS and t.new_state not in TRANSITIONAL_STATES:
            if t.origin in AUTOMATED_ORIGINS:
                report.ignored_automated_triggers += 1  # something an automation did is not a human action to react to
            else:
                trig_times[(t.entity_id, t.new_state)].append(ts)
        if _is_habit_transition(t):
            effect_times[(t.entity_id, t.new_state)].append(ts)

    def top(d: dict[tuple[str, str], list[float]], minimum: int) -> dict[tuple[str, str], list[float]]:
        keep = sorted((k for k, v in d.items() if len(v) >= minimum), key=lambda k: len(d[k]), reverse=True)[:max_keys]
        return {k: sorted(d[k]) for k in keep}

    triggers = top(trig_times, min_hits + 1)
    effects = top(effect_times, min_hits)

    def drop(rule: str, p: MinedPattern, reason: str, details: dict[str, Any] | None = None) -> None:
        report.suppressed.append(
            SuppressedHabit(
                rule=rule,
                trigger_entity=p.trigger_entity or "",
                trigger_state=p.trigger_state or "",
                entity_id=p.entity_id,
                to_state=p.to_state,
                hits=p.support_days,
                confidence=p.confidence,
                reason=reason,
                details=details or {},
            )
        )

    candidates: dict[tuple[str, str], list[MinedPattern]] = defaultdict(list)
    for (a_ent, a_state), a_times in triggers.items():
        anchor_a = time_anchor(a_times, tz)
        for (b_ent, b_state), b_times in effects.items():
            if a_ent == b_ent:
                continue
            lags: list[float] = []
            hit_pairs: list[tuple[float, float]] = []
            for ta in a_times:
                idx = bisect_right(b_times, ta)
                if idx < len(b_times) and b_times[idx] - ta <= max_lag_seconds:
                    lags.append(b_times[idx] - ta)
                    hit_pairs.append((ta, b_times[idx]))
            hits = len(lags)
            if hits < min_hits:
                continue
            conf = hits / len(a_times)
            expected = len(a_times) * len(b_times) * max_lag_seconds / span
            lift = hits / max(expected, 0.05)
            if conf < min_confidence or lift < min_lift:
                continue
            median_lag = statistics.median(lags)
            pattern = MinedPattern(
                pattern_id=_pid("sq", a_ent, a_state, b_ent, b_state),
                kind="sequence",
                entity_id=b_ent,
                to_state=b_state,
                day_class="all",
                support_days=hits,
                observed_days=len(a_times),
                confidence=min(1.0, conf),
                trigger_entity=a_ent,
                trigger_state=a_state,
                median_lag_seconds=median_lag,
                lift=lift,
                description=(
                    f"{b_ent} goes '{b_state}' within ~{max(1, int(round(median_lag / 60)))} min after "
                    f"{a_ent} becomes '{a_state}' ({hits} of {len(a_times)} times, lift x{lift:.1f})"
                ),
            )
            cause = find_common_cause(a_ent, b_ent, a_times, hit_pairs, cause_pool, min_hits=min_hits, min_confidence=min_confidence)
            if cause is not None:
                key, explained, total = cause
                drop(RULE_SHARED_CAUSE, pattern, reason_shared_cause(key, explained, total, a_ent, b_ent),
                     {"cause_entity": key[0], "cause_state": key[1], "explained_hits": explained, "total_hits": total})
                continue
            anchor_b = time_anchor([tb for _, tb in hit_pairs], tz)
            if anchor_a is not None and anchor_b is not None:
                drop(RULE_SAME_TIME, pattern, reason_same_time(a_ent, anchor_a, b_ent, anchor_b),
                     {"trigger_clock": anchor_a[0], "effect_clock": anchor_b[0]})
                continue
            candidates[(b_ent, b_state)].append(pattern)

    # One trigger followed by many different devices is a scene / shared trigger, not a chain.
    by_trigger: dict[tuple[str, str], list[MinedPattern]] = defaultdict(list)
    for plist in candidates.values():
        for p in plist:
            by_trigger[(p.trigger_entity or "", p.trigger_state or "")].append(p)
    fan_groups: list[tuple[set[tuple[str, str]], str, str]] = []
    for (a_ent, a_state), plist in by_trigger.items():
        keys = [(p.entity_id, p.to_state) for p in plist]
        if is_fan_out(keys, effects, max_lag_seconds, min_confidence):
            reason = reason_fan_out(a_ent, a_state, len(plist))
            for p in plist:
                drop(RULE_FAN_OUT, p, reason, {"effects": len(plist)})
            for key in {(p.entity_id, p.to_state) for p in plist}:
                candidates[key] = [p for p in candidates[key] if (p.trigger_entity, p.trigger_state) != (a_ent, a_state)]
            fan_groups.append(({(a_ent, a_state), *keys}, a_ent, a_state))
    # Devices that all follow the same trigger also "follow each other"; those links are the same shared trigger, not chains.
    for key, plist in list(candidates.items()):
        kept = []
        for p in plist:
            group = next((g for g in fan_groups if (p.trigger_entity, p.trigger_state) in g[0] and key in g[0]), None)
            if group is None:
                kept.append(p)
            else:
                drop(RULE_FAN_OUT, p, f"{p.trigger_entity} and {p.entity_id} both belong to the group of devices that follow "
                                      f"{group[1]} becoming '{group[2]}'; that is one shared trigger, not a chain.", {"group_trigger": group[1]})
        candidates[key] = kept

    # Two entities that always follow each other (the same blind exposed by two integrations, a group, one remote command) are
    # not a habit: automating A->B and B->A would even loop. Drop both directions.
    pairs = {(p.trigger_entity, p.entity_id) for plist in candidates.values() for p in plist}
    for key, plist in list(candidates.items()):
        kept = []
        for p in plist:
            if (p.entity_id, p.trigger_entity) in pairs:
                drop(RULE_MIRROR, p, f"{p.trigger_entity} and {p.entity_id} always follow each other (one device exposed twice, a group or "
                                     f"one command), so it is one movement, not a habit.")
            else:
                kept.append(p)
        candidates[key] = kept

    out: list[MinedPattern] = []
    for plist in candidates.values():
        plist.sort(key=lambda p: (p.confidence * min(p.lift or 1.0, 20.0), p.support_days), reverse=True)
        out.extend(plist[:max_per_effect])
    out.sort(key=lambda p: (p.confidence, p.support_days), reverse=True)
    return out, report


def mine_all(
    transitions: list[Transition],
    data_start: datetime,
    data_end: datetime,
    tz: tzinfo,
) -> list[MinedPattern]:
    return mine_all_report(transitions, data_start, data_end, tz)[0]


def mine_all_report(
    transitions: list[Transition],
    data_start: datetime,
    data_end: datetime,
    tz: tzinfo,
    cause_events: list[Transition] | None = None,
) -> tuple[list[MinedPattern], SequenceReport]:
    if not transitions:
        return [], SequenceReport()
    sequences, report = mine_sequences_report(transitions, data_start, data_end, tz=tz, cause_events=cause_events)
    return mine_time_habits(transitions, data_start, data_end, tz) + sequences, report


def _nice_name(entity_id: str, names: dict[str, str] | None) -> str:
    if names and names.get(entity_id):
        return names[entity_id]
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


_SWITCHABLE_SIBLINGS = frozenset({"light", "switch"})


def same_device(a: str, b: str) -> bool:
    """True for the same entity, or a light/switch pair sharing one object id (one physical device exposed twice)."""
    if a == b:
        return True
    da, _, oa = a.partition(".")
    db, _, ob = b.partition(".")
    return oa == ob and da in _SWITCHABLE_SIBLINGS and db in _SWITCHABLE_SIBLINGS


def is_duplicate_habit(a: MinedPattern, b: MinedPattern, names: dict[str, str] | None = None, window: int = 10) -> bool:
    """Two habits that would produce the same automation: one physical device (or two entities sharing a friendly name) set to the
    same state at about the same time on the same days."""
    if a.kind != "time_habit" or b.kind != "time_habit" or a.minute_of_day is None or b.minute_of_day is None:
        return False
    if a.to_state != b.to_state or a.day_class != b.day_class or circular_distance(a.minute_of_day, b.minute_of_day) > window:
        return False
    if same_device(a.entity_id, b.entity_id):
        return True
    na, nb = (names or {}).get(a.entity_id, "").strip().lower(), (names or {}).get(b.entity_id, "").strip().lower()
    return bool(na) and na == nb and a.entity_id.split(".", 1)[0] == b.entity_id.split(".", 1)[0]


def automation_from_pattern(
    pattern: MinedPattern,
    names: dict[str, str] | None = None,
    presence_entities: list[str] | None = None,
) -> NativeAutomationProposal | None:
    """Turn a strong statistical pattern into a native HA automation proposal without any LLM involvement."""
    domain = pattern.entity_id.split(".", 1)[0]
    call = service_for_state(domain, pattern.to_state)
    if call is None:
        return None
    service, data = call
    action: dict[str, Any] = {"service": f"{domain}.{service}", "target": {"entity_id": pattern.entity_id}}
    if data:
        action["data"] = data

    conditions: list[dict[str, Any]] = []
    # Switching things ON while nobody is home is never what a habit means.
    if presence_entities and pattern.to_state in ("on", "heat", "cool", "open", SCRIPT_RUN_STATE) and domain != "cover":
        homes = [{"condition": "state", "entity_id": p, "state": "home"} for p in presence_entities[:6]]
        conditions.append(homes[0] if len(homes) == 1 else {"condition": "or", "conditions": homes})

    name = _nice_name(pattern.entity_id, names)
    if names and sum(1 for n in names.values() if n and n == names.get(pattern.entity_id)) > 1:
        name = f"{name} ({pattern.entity_id.split('.', 1)[1]})"  # several entities share this friendly name
    if pattern.kind == "time_habit" and pattern.minute_of_day is not None:
        # Fire slightly *before* the typical manual action (so the automation gets there first), on a 5-minute grid.
        lead = min(pattern.spread_minutes or 0.0, 5.0)
        rounded = int(((pattern.minute_of_day - lead) // 5) * 5) % 1440
        at = f"{rounded // 60:02d}:{rounded % 60:02d}:00"
        trigger: dict[str, Any] = {"platform": "time", "at": at}
        if pattern.day_class == "weekday":
            conditions.insert(0, {"condition": "time", "weekday": WEEKDAYS})
        elif pattern.day_class == "weekend":
            conditions.insert(0, {"condition": "time", "weekday": WEEKEND})
        scope = {"all": "", "weekday": " (weekdays)", "weekend": " (weekends)"}[pattern.day_class]
        alias = f"{name}: {pattern.to_state} at {at[:5]}{scope}"
    elif pattern.kind == "sequence" and pattern.trigger_entity:
        trigger = {"platform": "state", "entity_id": pattern.trigger_entity, "to": pattern.trigger_state}
        lag = pattern.median_lag_seconds or 0.0
        if lag > 90:
            minutes = max(1, int(lag // 60) - 1)
            trigger["for"] = f"00:{min(minutes, 59):02d}:00"
        alias = f"{name}: {pattern.to_state} after {_nice_name(pattern.trigger_entity, names)} is {pattern.trigger_state}"
    else:
        return None

    return NativeAutomationProposal(
        alias=alias,
        description=f"Learned from your own behaviour: {pattern.description}.",
        trigger=[trigger],
        condition=conditions,
        action=[action],
        discovered_pattern_rationale=(
            f"Statistical pattern (no AI guess): {pattern.description}. "
            f"Confidence {pattern.confidence:.0%}."
        ),
        source_pattern_id=pattern.pattern_id,
    )
