"""Replay a proposed automation against recorded history to see what it *would* have done."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, tzinfo
from typing import Any

from ha_ai_brain.domain.automation_rules import AutomationRule, RuleAction, _collect_actions, _entity_ids, _listify
from ha_ai_brain.domain.models import BacktestResult, NativeAutomationProposal, Transition
from ha_ai_brain.domain.patterns import AUTOMATED_ORIGINS
from ha_ai_brain.domain.timeutil import WEEKDAY_NAMES, iter_days, local_at, minute_of_day, parse_hhmm, to_local

MIN_DAYS = 3.0
OPPOSITE_WINDOW = timedelta(minutes=30)


def _duration_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return float(value.get("hours", 0)) * 3600 + float(value.get("minutes", 0)) * 60 + float(value.get("seconds", 0))
    if isinstance(value, str):
        parts = value.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return 0.0
        while len(nums) < 3:
            nums.insert(0, 0.0)
        return nums[-3] * 3600 + nums[-2] * 60 + nums[-1]
    return 0.0


class _Timeline:
    """Per-entity sorted transitions with point-in-time state lookups."""

    def __init__(self, transitions: list[Transition]) -> None:
        self.by_entity: dict[str, list[Transition]] = defaultdict(list)
        for t in sorted(transitions, key=lambda t: t.ts):
            self.by_entity[t.entity_id].append(t)
        self._times = {eid: [t.ts for t in ts] for eid, ts in self.by_entity.items()}

    def has(self, entity_id: str) -> bool:
        return entity_id in self.by_entity

    def state_at(self, entity_id: str, ts: datetime) -> str | None:
        rows = self.by_entity.get(entity_id)
        if not rows:
            return None
        idx = bisect_right(self._times[entity_id], ts)
        if idx == 0:
            return rows[0].old_state or None
        return rows[idx - 1].new_state

    def between(self, entity_id: str, start: datetime, end: datetime) -> list[Transition]:
        rows = self.by_entity.get(entity_id, [])
        times = self._times.get(entity_id, [])
        lo = bisect_right(times, start - timedelta(microseconds=1))
        hi = bisect_right(times, end)
        return rows[lo:hi]


def _eval_condition(cond: Any, ts: datetime, tl: _Timeline, tz: tzinfo, notes: set[str]) -> bool:
    """Evaluate a condition at `ts`; conditions that cannot be modelled are assumed true and flagged approximate."""
    if not isinstance(cond, dict):
        notes.add("approximate: unrecognised condition ignored")
        return True
    kind = str(cond.get("condition") or "")
    local = to_local(ts, tz)
    if kind == "time":
        if cond.get("weekday") is not None:
            names = {str(w).lower()[:3] for w in _listify(cond["weekday"])}
            if WEEKDAY_NAMES[local.weekday()] not in names:
                return False
        cur = minute_of_day(local)
        after = parse_hhmm(cond.get("after")) if isinstance(cond.get("after"), str) else None
        before = parse_hhmm(cond.get("before")) if isinstance(cond.get("before"), str) else None
        if after is not None and before is not None:
            return (after <= cur < before) if after < before else (cur >= after or cur < before)
        if after is not None and cur < after:
            return False
        if before is not None and cur >= before:
            return False
        return True
    if kind == "state":
        wanted = {str(s) for s in _listify(cond.get("state"))}
        for eid in _entity_ids(cond.get("entity_id")):
            cur = tl.state_at(eid, ts)
            if cur is None:
                notes.add(f"approximate: no history for {eid}, state condition assumed true")
                continue
            if cur not in wanted:
                return False
        return True
    if kind in ("and", "or", "not") and isinstance(cond.get("conditions"), list):
        results = [_eval_condition(c, ts, tl, tz, notes) for c in cond["conditions"]]
        if kind == "and":
            return all(results)
        if kind == "or":
            return any(results)
        return not any(results)
    notes.add(f"approximate: '{kind or 'template'}' condition not replayed")
    return True


def _fires_for_trigger(trig: dict[str, Any], tl: _Timeline, start: datetime, end: datetime, tz: tzinfo, notes: set[str]) -> list[datetime] | None:
    kind = str(trig.get("platform") or trig.get("trigger") or "")
    if kind == "time" and isinstance(trig.get("at"), str):
        minute = parse_hhmm(trig["at"])
        if minute is None:
            return None
        fires = []
        for d in iter_days(start, end, tz):
            ts = local_at(d, minute, tz).astimezone(start.tzinfo)
            if start <= ts <= end:
                fires.append(ts)
        return fires
    if kind == "state":
        ids = _entity_ids(trig.get("entity_id"))
        if not ids or not any(tl.has(i) for i in ids):
            notes.add("no recorded history for the trigger entity")
            return None
        to_states = {str(s) for s in _listify(trig.get("to"))} if trig.get("to") is not None else None
        from_states = {str(s) for s in _listify(trig.get("from"))} if trig.get("from") is not None else None
        hold = _duration_seconds(trig.get("for")) if trig.get("for") else 0.0
        fires = []
        for eid in ids:
            rows = tl.by_entity.get(eid, [])
            for i, t in enumerate(rows):
                if to_states is not None and t.new_state not in to_states:
                    continue
                if to_states is None and t.new_state in ("unavailable", "unknown"):
                    continue
                if from_states is not None and t.old_state not in from_states:
                    continue
                fire_ts = t.ts + timedelta(seconds=hold)
                if hold and i + 1 < len(rows) and rows[i + 1].ts < fire_ts:
                    continue  # state did not hold long enough
                if start <= fire_ts <= end:
                    fires.append(fire_ts)
        return sorted(fires)
    notes.add(f"approximate: '{kind or 'unknown'}' trigger cannot be replayed from recorded transitions")
    return None


def backtest_automation(
    proposal: NativeAutomationProposal,
    transitions: list[Transition],
    data_start: datetime,
    data_end: datetime,
    tz: tzinfo,
    *,
    window_minutes: int = 20,
) -> BacktestResult:
    days = (data_end - data_start).total_seconds() / 86400.0
    if days < MIN_DAYS:
        return BacktestResult(
            verdict="unverifiable",
            days_observed=round(days, 1),
            summary=f"Only {days:.1f} days of history recorded so far - not enough to replay (need {MIN_DAYS:.0f}+).",
        )

    tl = _Timeline(transitions)
    notes: set[str] = set()
    window = timedelta(minutes=window_minutes)
    end = data_end - window

    fires: list[datetime] = []
    replayed_any = False
    for trig in proposal.trigger:
        if not isinstance(trig, dict):
            continue
        result = _fires_for_trigger(trig, tl, data_start, end, tz, notes)
        if result is not None:
            replayed_any = True
            fires.extend(result)
    if not replayed_any:
        return BacktestResult(
            verdict="unverifiable",
            days_observed=round(days, 1),
            approximate=True,
            notes=sorted(notes),
            summary="This trigger type cannot be replayed from recorded history; judged on the AI's reasoning only.",
        )

    fires = sorted(set(fires))
    fires = [f for f in fires if all(_eval_condition(c, f, tl, tz, notes) for c in proposal.condition)]

    rule = AutomationRule(automation_id="", alias=proposal.alias)
    _collect_actions(proposal.action, rule)
    targets: list[RuleAction] = [a for a in rule.actions if a.result_state]

    aligned = redundant = contradicted = 0
    observed_manual = covered_manual = 0
    if targets:
        for fire in fires:
            fire_aligned = fire_contra = False
            all_redundant = True
            for act in targets:
                desired = act.result_state or ""
                # strictly before the fire instant: a manual action at the same second still counts as aligned, not redundant
                if tl.state_at(act.entity_id, fire - timedelta(seconds=1)) == desired:
                    continue
                all_redundant = False
                near = [t for t in tl.between(act.entity_id, fire - window, fire + window) if t.new_state == desired and t.origin not in AUTOMATED_ORIGINS]
                if near:
                    fire_aligned = True
                after = [t for t in tl.between(act.entity_id, fire, fire + OPPOSITE_WINDOW) if t.new_state != desired and t.origin not in AUTOMATED_ORIGINS]
                if after and not near:
                    fire_contra = True
            if all_redundant:
                redundant += 1
            elif fire_aligned:
                aligned += 1
            elif fire_contra:
                contradicted += 1

        fire_times = fires
        for act in targets:
            desired = act.result_state or ""
            for t in tl.by_entity.get(act.entity_id, []):
                if t.new_state != desired or t.origin in AUTOMATED_ORIGINS or not (data_start <= t.ts <= end):
                    continue
                observed_manual += 1
                if any(abs((t.ts - f).total_seconds()) <= window.total_seconds() for f in fire_times):
                    covered_manual += 1
    else:
        notes.add("actions have no well-defined resulting state; alignment not measured")

    effective = max(0, len(fires) - redundant)
    quality = (aligned / effective) if (targets and effective) else None
    approximate = any(n.startswith("approximate") for n in notes)

    if not targets or quality is None or len(fires) < 3:
        verdict = "unverifiable"
    elif quality >= 0.5:
        verdict = "supported"
    elif quality >= 0.25:
        verdict = "partial"
    else:
        verdict = "weak"
    if approximate and verdict == "supported":
        verdict = "partial"

    parts = [f"Replayed {days:.0f} days of your history: it would have fired {len(fires)} time(s)"]
    if targets and fires:
        parts.append(f"{aligned} matched what you did by hand (±{window_minutes} min)")
        if redundant:
            parts.append(f"{redundant} found the device already in the desired state")
        if contradicted:
            parts.append(f"{contradicted} were followed by you doing the opposite")
    if observed_manual:
        parts.append(f"covers {covered_manual} of {observed_manual} manual occurrences")
    return BacktestResult(
        verdict=verdict,
        days_observed=round(days, 1),
        fires=len(fires),
        aligned=aligned,
        redundant=redundant,
        contradicted=contradicted,
        observed_manual=observed_manual,
        covered_manual=covered_manual,
        quality=None if quality is None else round(quality, 2),
        approximate=approximate,
        summary="; ".join(parts) + ".",
        notes=sorted(notes),
    )


Timeline = _Timeline  # public alias for other domain modules
