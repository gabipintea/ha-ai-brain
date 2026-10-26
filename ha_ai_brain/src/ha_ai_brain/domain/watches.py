"""
User-described watches: a plain-language request is compiled once (by the AI) into a structured rule that is then
evaluated locally and for free, every minute, forever. Rules are validated against real entities and can be
replayed over recorded history before they are saved.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ha_ai_brain.domain.backtest import Timeline
from ha_ai_brain.domain.models import EntityState, Transition
from ha_ai_brain.domain.timeutil import WEEKDAY_NAMES, minute_of_day, parse_hhmm, parse_iso, to_local

KINDS = ("state", "numeric", "silence")
SEVERITIES = ("info", "warning", "critical")
PRESENCE = ("any", "home", "away")
MAX_FOR_MINUTES = 7 * 24 * 60
NON_STATES = frozenset({"unavailable", "unknown"})


class WatchCondition(BaseModel):
    kind: str = "state"
    state: str | None = None  # state/attribute value that triggers the watch (kind=state)
    negate: bool = False  # fire when the value is NOT `state`
    above: float | None = None  # kind=numeric
    below: float | None = None
    attribute: str | None = Field(default=None, max_length=100)  # evaluate an attribute instead of the state
    for_minutes: int = Field(default=0, ge=0, le=MAX_FOR_MINUTES)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"condition kind must be one of {KINDS}")
        return v


class WatchRule(BaseModel):
    watch_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=1000)  # the original request
    entity_ids: list[str] = Field(min_length=1, max_length=50)
    condition: WatchCondition
    presence: str = "any"
    window_start: str = ""
    window_end: str = ""
    weekdays: list[str] = Field(default_factory=list)
    severity: str = "warning"
    message: str = Field(default="", max_length=500)
    cooldown_minutes: int = Field(default=60, ge=1, le=MAX_FOR_MINUTES)
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_fired: datetime | None = None
    fire_count: int = 0

    @field_validator("severity")
    @classmethod
    def _severity(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        return v

    @field_validator("presence")
    @classmethod
    def _presence(cls, v: str) -> str:
        if v not in PRESENCE:
            raise ValueError(f"presence must be one of {PRESENCE}")
        return v

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, v: list[str]) -> list[str]:
        cleaned = [str(d).lower()[:3] for d in v]
        bad = [d for d in cleaned if d not in WEEKDAY_NAMES]
        if bad:
            raise ValueError(f"unknown weekdays: {bad}")
        return cleaned

    @model_validator(mode="after")
    def _consistency(self) -> "WatchRule":
        for label, value in (("window_start", self.window_start), ("window_end", self.window_end)):
            if value and parse_hhmm(value) is None:
                raise ValueError(f"{label} must be HH:MM")
        if bool(self.window_start) != bool(self.window_end):
            raise ValueError("window_start and window_end must be given together")
        c = self.condition
        if c.kind == "numeric" and c.above is None and c.below is None:
            raise ValueError("a numeric watch needs 'above' and/or 'below'")
        if c.kind == "state" and not c.state:
            raise ValueError("a state watch needs a 'state' value")
        if c.kind == "silence" and c.for_minutes < 5:
            raise ValueError("a silence watch needs for_minutes of at least 5")
        return self


def validate_watch(rule: WatchRule, states: dict[str, EntityState]) -> tuple[list[str], list[str]]:
    """(errors, warnings) of a rule against the entities that actually exist."""
    errors: list[str] = []
    warnings: list[str] = []
    for eid in rule.entity_ids:
        st = states.get(eid)
        if st is None:
            errors.append(f"Unknown entity: {eid}")
            continue
        if rule.condition.kind == "numeric":
            raw = st.attributes.get(rule.condition.attribute) if rule.condition.attribute else st.state
            try:
                float(raw)
            except (TypeError, ValueError):
                if st.state not in NON_STATES or rule.condition.attribute:
                    errors.append(f"{eid} has no numeric value to compare ({raw!r})")
        elif rule.condition.kind == "state" and not rule.condition.attribute and rule.condition.state is not None:
            options = st.attributes.get("options")
            if isinstance(options, list) and rule.condition.state not in [str(o) for o in options]:
                warnings.append(f"{eid}: '{rule.condition.state}' is not one of its known options {options[:6]}")
    if rule.condition.for_minutes and rule.cooldown_minutes < rule.condition.for_minutes:
        warnings.append("The cooldown is shorter than the required duration; you may be alerted repeatedly.")
    return errors, warnings


@dataclass
class WatchFiring:
    entity_id: str
    detail: str


class WatchTracker:
    """In-memory 'since when has this condition been true' book-keeping for attribute / numeric conditions."""

    def __init__(self) -> None:
        self.since: dict[tuple[str, str], datetime] = {}

    def clear_rule(self, watch_id: str) -> None:
        for key in [k for k in self.since if k[0] == watch_id]:
            del self.since[key]


def _gates_open(rule: WatchRule, now: datetime, tz: tzinfo, anyone_home: bool | None) -> bool:
    local = to_local(now, tz)
    if rule.weekdays and WEEKDAY_NAMES[local.weekday()] not in rule.weekdays:
        return False
    if rule.window_start and rule.window_end:
        start, end = parse_hhmm(rule.window_start), parse_hhmm(rule.window_end)
        cur = minute_of_day(local)
        if start is not None and end is not None and start != end:
            inside = (start <= cur < end) if start < end else (cur >= start or cur < end)
            if not inside:
                return False
    if rule.presence == "home" and anyone_home is not True:
        return False
    if rule.presence == "away" and anyone_home is not False:
        return False
    return True


def _value(st: EntityState, attribute: str | None) -> Any:
    return st.attributes.get(attribute) if attribute else st.state


def evaluate_watch(
    rule: WatchRule,
    states: dict[str, EntityState],
    now: datetime,
    tz: tzinfo,
    tracker: WatchTracker,
    anyone_home: bool | None,
) -> list[WatchFiring]:
    if not rule.enabled:
        return []
    if not _gates_open(rule, now, tz, anyone_home):
        tracker.clear_rule(rule.watch_id)
        return []
    c = rule.condition
    firings: list[WatchFiring] = []
    for eid in rule.entity_ids:
        st = states.get(eid)
        key = (rule.watch_id, eid)
        if st is None:
            tracker.since.pop(key, None)
            continue
        active, detail, started = False, "", now

        if c.kind == "silence":
            last = st.last_updated if (st.domain == "sensor" or c.attribute) else st.last_changed
            elapsed = (now - last).total_seconds() / 60.0
            active, started = elapsed >= c.for_minutes, last
            detail = f"{eid} has not {'reported' if st.domain == 'sensor' else 'changed'} for {int(elapsed)} min"
        elif c.kind == "numeric":
            try:
                v = float(_value(st, c.attribute))
            except (TypeError, ValueError):
                v = math.nan
            if not math.isnan(v) and math.isfinite(v):
                if c.above is not None and v > c.above:
                    active, detail = True, f"{eid} is {v:g}, above {c.above:g}"
                elif c.below is not None and v < c.below:
                    active, detail = True, f"{eid} is {v:g}, below {c.below:g}"
        else:  # state
            raw = _value(st, c.attribute)
            if raw is not None and (str(raw) not in NON_STATES or str(c.state).lower() in NON_STATES):
                match = str(raw).lower() == str(c.state).lower()
                active = match != c.negate
                detail = f"{eid} is '{raw}'" if not c.negate else f"{eid} is '{raw}' (not '{c.state}')"
                if active and not c.attribute:
                    started = st.last_changed  # true start of this state, survives restarts

        if not active:
            tracker.since.pop(key, None)
            continue
        if c.kind == "numeric" or c.attribute:
            started = tracker.since.setdefault(key, now)
        elapsed_min = (now - started).total_seconds() / 60.0
        if c.kind != "silence" and elapsed_min < c.for_minutes:
            continue
        if c.for_minutes and c.kind != "silence":
            detail += f" for {int(elapsed_min)} min"
        firings.append(WatchFiring(eid, detail))
    return firings


# --------------------------------------------------------------------------------------------- backtest
def backtest_watch(
    rule: WatchRule,
    transitions: list[Transition],
    hourly_rows: dict[str, list[tuple[str, int, float]]],
    start: datetime,
    end: datetime,
    tz: tzinfo,
) -> dict[str, Any]:
    """How often would this watch have fired over the recorded history? (a noisy rule is better caught before saving)"""
    days = max(0.0, (end - start).total_seconds() / 86400.0)
    c = rule.condition
    episodes = 0
    approximate = False
    notes: list[str] = []

    def gate_ok(ts: datetime) -> bool:
        return _gates_open(rule.model_copy(update={"presence": "any"}), ts, tz, None)

    if rule.presence != "any":
        notes.append("presence conditions are not replayed")
        approximate = True

    if c.attribute:
        return {"episodes": None, "days": round(days, 1), "approximate": True, "note": "Rules on attributes cannot be replayed from history."}

    if c.kind == "numeric":
        approximate = True
        notes.append("replayed from hourly averages")
        need_hours = max(1, math.ceil(c.for_minutes / 60.0))
        for eid in rule.entity_ids:
            run = 0
            for hour_ts, _, mean in hourly_rows.get(eid, []):
                t = parse_iso(hour_ts)
                hit = t is not None and start <= t <= end and (
                    (c.above is not None and mean > c.above) or (c.below is not None and mean < c.below)
                )
                run = run + 1 if hit else 0
                if run == need_hours and t is not None and gate_ok(t):
                    episodes += 1
    else:
        tl = Timeline([t for t in transitions if t.entity_id in rule.entity_ids])
        for eid in rule.entity_ids:
            rows = tl.by_entity.get(eid, [])
            for i, t in enumerate(rows):
                nxt = rows[i + 1].ts if i + 1 < len(rows) else end
                if not (start <= t.ts <= end):
                    continue
                if c.kind == "silence":
                    gap = (nxt - t.ts).total_seconds() / 60.0
                    hit = gap >= c.for_minutes
                    when = t.ts + timedelta(minutes=c.for_minutes)
                else:
                    match = t.new_state.lower() == str(c.state).lower()
                    hit = (match != c.negate) and (nxt - t.ts).total_seconds() / 60.0 >= c.for_minutes
                    when = t.ts + timedelta(minutes=c.for_minutes)
                if hit and gate_ok(when):
                    episodes += 1
        if not any(tl.has(e) for e in rule.entity_ids):
            notes.append("no recorded history for these entities yet")
            approximate = True

    per_week = (episodes / days * 7.0) if days >= 1 else None
    note = "; ".join(notes)
    if per_week is not None and per_week > 14:
        note = (note + "; " if note else "") + "this would alert very often - consider a longer duration or tighter condition"
    return {"episodes": episodes, "days": round(days, 1), "per_week": None if per_week is None else round(per_week, 1), "approximate": approximate, "note": note}


# --------------------------------------------------------------------------------------------- catalog
_TOKEN = re.compile(r"[a-z0-9]{3,}")


def build_entity_catalog(text: str, states: dict[str, EntityState], limit: int = 300) -> list[dict[str, Any]]:
    """Entities most relevant to the request (plus a spread of the rest) in compact form for the compiler prompt."""
    words = set(_TOKEN.findall(text.lower()))
    scored: list[tuple[int, str]] = []
    for eid, st in states.items():
        if st.domain in ("automation", "script", "scene", "update", "persistent_notification"):
            continue
        haystack = set(_TOKEN.findall(f"{eid} {st.attributes.get('friendly_name', '')} {st.area_id or ''} {st.device_class or ''}".lower()))
        scored.append((len(words & haystack), eid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    chosen = [eid for score, eid in scored if score > 0][: limit * 2 // 3]
    rest = [eid for score, eid in scored if score == 0]
    chosen += rest[: max(0, limit - len(chosen))]
    out = []
    for eid in chosen:
        st = states[eid]
        out.append(
            {
                "id": eid,
                "name": st.attributes.get("friendly_name"),
                "device_class": st.device_class,
                "unit": st.unit_of_measurement,
                "area": st.area_id,
                "state": st.state,
            }
        )
    return out
