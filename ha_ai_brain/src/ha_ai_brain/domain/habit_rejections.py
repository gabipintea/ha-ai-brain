"""Habits the homeowner rejected ("not a real habit"): remembered so the same habit is never shown, proposed or sent to an agent again.

A mined habit is recomputed from history every time, and a time habit's id depends on a 30-minute bucket of its average time, so
the id alone can drift. A rejection therefore also matches the same habit by what it means: the same device going to the same
state at about the same time on overlapping days, or the same "B follows A" pair.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from pydantic import BaseModel, Field

from ha_ai_brain.domain.patterns import MinedPattern, same_device
from ha_ai_brain.domain.timeutil import circular_distance

# A rejected time habit also hides the same habit whose average time drifted by up to this much.
MATCH_WINDOW_MINUTES = 30
MAX_REJECTED_HABITS = 500


class RejectedHabit(BaseModel):
    rejection_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-]+$")  # the habit's id when it was rejected
    kind: str = Field(pattern=r"^(time_habit|sequence)$")
    entity_id: str = Field(min_length=3, max_length=255)
    to_state: str = Field(max_length=100)
    day_class: str = Field(default="all", pattern=r"^(all|weekday|weekend)$")
    minute_of_day: float | None = Field(default=None, ge=0, lt=1440)
    trigger_entity: str | None = Field(default=None, max_length=255)
    trigger_state: str | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=1000)
    rejected_at: datetime | None = None
    deleted_at: datetime | None = None
    status: str = Field(default="rejected", pattern=r"^(rejected|deleted)$")

    @classmethod
    def from_pattern(cls, pattern: MinedPattern, now: datetime) -> RejectedHabit:
        return cls(
            rejection_id=pattern.pattern_id,
            kind=pattern.kind,
            entity_id=pattern.entity_id,
            to_state=pattern.to_state,
            day_class=pattern.day_class,
            minute_of_day=pattern.minute_of_day,
            trigger_entity=pattern.trigger_entity,
            trigger_state=pattern.trigger_state,
            description=pattern.description[:1000],
            rejected_at=now,
        )


def _same_entity(a: str, b: str, names: dict[str, str] | None, canonical: Callable[[str], str] | None) -> bool:
    if canonical is not None:
        a, b = canonical(a), canonical(b)
    if same_device(a, b):
        return True
    na, nb = (names or {}).get(a, "").strip().lower(), (names or {}).get(b, "").strip().lower()
    return bool(na) and na == nb and a.split(".", 1)[0] == b.split(".", 1)[0]


def _days_overlap(a: str, b: str) -> bool:
    return a == b or "all" in (a, b)


def rejection_matches(
    rejected: RejectedHabit,
    pattern: MinedPattern,
    names: dict[str, str] | None = None,
    canonical: Callable[[str], str] | None = None,
    window: int = MATCH_WINDOW_MINUTES,
) -> bool:
    """True when `pattern` is the habit the homeowner rejected (same id, or the same meaning after small drifts)."""
    if rejected.rejection_id == pattern.pattern_id:
        return True
    if rejected.kind != pattern.kind or rejected.to_state != pattern.to_state:
        return False
    if not _same_entity(rejected.entity_id, pattern.entity_id, names, canonical):
        return False
    if pattern.kind == "sequence":
        return (
            bool(rejected.trigger_entity and pattern.trigger_entity)
            and rejected.trigger_state == pattern.trigger_state
            and _same_entity(rejected.trigger_entity or "", pattern.trigger_entity or "", names, canonical)
        )
    if rejected.minute_of_day is None or pattern.minute_of_day is None:
        return False
    return _days_overlap(rejected.day_class, pattern.day_class) and circular_distance(rejected.minute_of_day, pattern.minute_of_day) <= window


def split_rejected(
    patterns: list[MinedPattern],
    rejected: list[RejectedHabit],
    names: dict[str, str] | None = None,
    canonical: Callable[[str], str] | None = None,
    now: datetime | None = None,
) -> tuple[list[MinedPattern], set[str]]:
    """Patterns the homeowner did not reject or delete, and the ids of the active rejections that still match history."""
    if not rejected:
        return list(patterns), set()
    kept: list[MinedPattern] = []
    seen: set[str] = set()
    # Filter out expired deletions (older than 30 days)
    valid_records = [
        r for r in rejected
        if r.status != "deleted" or not now or not r.deleted_at or (now - r.deleted_at).total_seconds() < 30 * 86400
    ]
    for p in patterns:
        matching = [r for r in valid_records if rejection_matches(r, p, names, canonical)]
        if matching:
            seen.update(r.rejection_id for r in matching if r.status == "rejected")
        else:
            kept.append(p)
    return kept, seen


def rejected_habit_card(rejected: RejectedHabit, still_detected: bool) -> dict[str, Any]:
    return {**rejected.model_dump(mode="json"), "still_detected": still_detected}
