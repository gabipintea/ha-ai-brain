"""Filters that stop 'A is followed by B' habits being mined when A and B merely share a cause (pure logic, no I/O).

Typical false positive: several unrelated automations all trigger on the same event (sunset, someone arriving, a time of day), so
many devices change within a minute of each other every day. Timing alone says "A -> B"; the real reason is a hidden common trigger.
Every dropped pair is reported with a plain-language reason so the dashboard can show it.
"""

from __future__ import annotations

import statistics
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, tzinfo
from typing import Any

from ha_ai_brain.domain.models import Transition
from ha_ai_brain.domain.timeutil import circular_distance, circular_mean, format_minute, minute_of_day, to_local

RULE_SHARED_CAUSE = "shared_cause"
RULE_SAME_TIME = "same_time_of_day"
RULE_FAN_OUT = "fan_out"
RULE_MIRROR = "mirror"
RULE_TWIN = "twin_device"

# Burst detection (scripted scenes): this many different devices switching within a few seconds of each other.
BURST_GAP_SECONDS = 4.0
BURST_MIN_ENTITIES = 4
# Common cause: an event that happened shortly before A (or a moment after, clocks/ordering differ) explains A.
CAUSE_WINDOW_SECONDS = 45.0
CAUSE_LOOKAHEAD_SECONDS = 2.0
CAUSE_MIN_SHARE = 0.5  # the cause must explain at least this share of the hits
MAX_CAUSE_KEYS = 300
# Time anchor.
ANCHOR_TOLERANCE_MINUTES = 20
ANCHOR_SHARE = 0.8
SMOOTH_MEDIAN_DELTA_MINUTES = 6.0
SMOOTH_MIN_PAIRS = 4
# Fan-out: one trigger "followed" by this many different devices is a scene or a shared trigger, not a chain.
FAN_OUT_MIN = 4
FAN_OUT_CLIQUE_MIN = 3  # three effects are enough when they also follow each other
FAN_OUT_CLIQUE_SHARE = 0.5


@dataclass
class SuppressedHabit:
    """A mined 'A -> B' relation that was dropped, and why."""

    rule: str
    trigger_entity: str
    trigger_state: str
    entity_id: str
    to_state: str
    hits: int
    confidence: float
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence"] = round(float(data["confidence"]), 2)
        return data


@dataclass
class SequenceReport:
    suppressed: list[SuppressedHabit] = field(default_factory=list)
    ignored_automated_triggers: int = 0
    ignored_burst_transitions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suppressed": [s.to_dict() for s in self.suppressed],
            "ignored_automated_triggers": self.ignored_automated_triggers,
            "ignored_burst_transitions": self.ignored_burst_transitions,
        }


# ------------------------------------------------------------------ #4 origin: scripted bursts
def find_burst_transitions(transitions: list[Transition], is_candidate: Any) -> set[int]:
    """
    Indexes (into `transitions`) of device changes that belong to a burst: >= BURST_MIN_ENTITIES different devices changing within
    BURST_GAP_SECONDS of each other (chained). A person rarely does that by hand; a script, scene or several automations on one
    trigger do. Only transitions accepted by `is_candidate` take part (so busy motion sensors never count as a burst).
    """
    items = sorted(((t.ts.timestamp(), i) for i, t in enumerate(transitions) if is_candidate(t)))
    flagged: set[int] = set()
    group: list[tuple[float, int]] = []

    def close() -> None:
        if len({transitions[i].entity_id for _, i in group}) >= BURST_MIN_ENTITIES:
            flagged.update(i for _, i in group)

    for item in items:
        if group and item[0] - group[-1][0] > BURST_GAP_SECONDS:
            close()
            group = []
        group.append(item)
    if group:
        close()
    return flagged


# ------------------------------------------------------------------ #1 common cause
def build_cause_pool(transitions: list[Transition], min_count: int) -> dict[tuple[str, str], list[float]]:
    """Every kind of event (any origin, automation runs included) that could be the hidden trigger behind a pair."""
    raw: dict[tuple[str, str], list[float]] = defaultdict(list)
    for t in transitions:
        if t.new_state in ("", "unavailable", "unknown", "none") or t.old_state == t.new_state:
            continue
        raw[(t.entity_id, t.new_state)].append(t.ts.timestamp())
    keep = sorted((k for k, v in raw.items() if len(v) >= min_count), key=lambda k: len(raw[k]), reverse=True)[:MAX_CAUSE_KEYS]
    return {k: sorted(raw[k]) for k in keep}


def _object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[-1]


def _explained(ts: float, cause_times: list[float]) -> bool:
    idx = bisect_right(cause_times, ts + CAUSE_LOOKAHEAD_SECONDS) - 1
    return idx >= 0 and ts - cause_times[idx] <= CAUSE_WINDOW_SECONDS


def find_common_cause(
    a_ent: str,
    b_ent: str,
    a_times: list[float],
    hit_pairs: list[tuple[float, float]],
    pool: dict[tuple[str, str], list[float]],
    *,
    min_hits: int,
    min_confidence: float,
) -> tuple[tuple[str, str], int, int] | None:
    """
    Look for a third event C that happened right before A on (most of) the occasions where B followed.
    Returns (C, hits explained, hits in total) when the pair does not survive once the C-driven occurrences are removed.
    """
    best: tuple[tuple[str, str], int] | None = None
    for key, c_times in pool.items():
        c_ent = key[0]
        if c_ent in (a_ent, b_ent) or _object_id(c_ent) in (_object_id(a_ent), _object_id(b_ent)):
            continue
        explained = sum(1 for ta, _ in hit_pairs if _explained(ta, c_times))
        if explained >= max(min_hits, CAUSE_MIN_SHARE * len(hit_pairs)) and (best is None or explained > best[1]):
            best = (key, explained)
    if best is None:
        return None
    c_times = pool[best[0]]
    resid_hits = sum(1 for ta, _ in hit_pairs if not _explained(ta, c_times))
    resid_a = sum(1 for ta in a_times if not _explained(ta, c_times))
    if resid_hits >= min_hits and resid_hits / max(1, resid_a) >= min_confidence:
        return None  # B still follows A without C: a real relation (C may just be part of the chain)
    return best[0], best[1], len(hit_pairs)


# ------------------------------------------------------------------ #2 time anchor
def _densest_share(minutes: list[float], tolerance: int) -> tuple[float, float]:
    """Share of the points inside the densest +-tolerance window on the 24 h clock, and that window's centre."""
    best_n, best_centre = 0, 0.0
    for m in minutes:
        members = [x for x in minutes if circular_distance(x, m) <= tolerance]
        if len(members) > best_n:
            best_n, best_centre = len(members), circular_mean([int(round(x)) for x in members])
    return best_n / max(1, len(minutes)), best_centre


def time_anchor(times: list[float], tz: tzinfo) -> tuple[str, float] | None:
    """
    ('fixed' | 'drifting', typical minute of day) when the event always happens at about the same clock time (or drifts smoothly
    day by day, like sunset), else None. One occurrence per local day is used (the first).
    """
    per_day: dict[Any, float] = {}
    for ts in sorted(times):
        local = to_local(datetime.fromtimestamp(ts, tz=tz), tz)
        per_day.setdefault(local.date(), float(minute_of_day(local)))
    if len(per_day) < 4:
        return None
    minutes = list(per_day.values())
    share, centre = _densest_share(minutes, ANCHOR_TOLERANCE_MINUTES)
    if share >= ANCHOR_SHARE:
        return "fixed", centre
    days = sorted(per_day)
    deltas = [circular_distance(per_day[d2], per_day[d1]) for d1, d2 in zip(days, days[1:]) if (d2 - d1).days == 1]
    if len(deltas) >= SMOOTH_MIN_PAIRS and statistics.median(deltas) <= SMOOTH_MEDIAN_DELTA_MINUTES:
        return "drifting", circular_mean([int(round(m)) for m in minutes])
    return None


# ------------------------------------------------------------------ #3 fan-out
def follows(a_times: list[float], b_times: list[float], max_lag: float) -> float:
    """Share of A occurrences that B follows within max_lag seconds."""
    if not a_times:
        return 0.0
    hits = 0
    for ta in a_times:
        idx = bisect_left(b_times, ta + 0.0001)
        if idx < len(b_times) and b_times[idx] - ta <= max_lag:
            hits += 1
    return hits / len(a_times)


def is_fan_out(
    effect_keys: list[tuple[str, str]],
    effect_times: dict[tuple[str, str], list[float]],
    max_lag: float,
    min_confidence: float,
) -> bool:
    n = len(effect_keys)
    if n >= FAN_OUT_MIN:
        return True
    if n < FAN_OUT_CLIQUE_MIN:
        return False
    pairs = linked = 0
    for i in range(n):
        for j in range(i + 1, n):
            ki, kj = effect_keys[i], effect_keys[j]
            pairs += 1
            if max(follows(effect_times[ki], effect_times[kj], max_lag), follows(effect_times[kj], effect_times[ki], max_lag)) >= min_confidence:
                linked += 1
    return pairs > 0 and linked / pairs >= FAN_OUT_CLIQUE_SHARE


# ------------------------------------------------------------------ reasons (plain language, shown in the dashboard)
def reason_shared_cause(cause: tuple[str, str], explained: int, total: int, a_ent: str, b_ent: str) -> str:
    what = "an automation ran" if cause[0].startswith("automation.") else f"{cause[0]} became '{cause[1]}'"
    return (
        f"Both {a_ent} and {b_ent} changed right after the same event ({what}) in {explained} of {total} cases, "
        f"so one is not following the other: they share a trigger."
    )


def reason_same_time(a_ent: str, a_anchor: tuple[str, float], b_ent: str, b_anchor: tuple[str, float]) -> str:
    def part(ent: str, anchor: tuple[str, float]) -> str:
        how = "at about" if anchor[0] == "fixed" else "at a smoothly shifting time, around"
        return f"{ent} {how} {format_minute(anchor[1])}"

    return (
        f"Both happen on the clock every day ({part(a_ent, a_anchor)}; {part(b_ent, b_anchor)}), so they are two separate "
        f"time habits, not one following the other."
    )


def reason_fan_out(trigger_ent: str, trigger_state: str, count: int) -> str:
    return (
        f"{trigger_ent} becoming '{trigger_state}' is followed by {count} different devices; that looks like a scene or one shared "
        f"trigger, not a chain of habits."
    )
