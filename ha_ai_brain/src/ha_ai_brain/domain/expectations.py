"""Exception detection: what is unusual *right now* compared with learned routines and configured automations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Any

from ha_ai_brain.domain.automation_rules import AutomationRule, RuleExpectation, is_state_automated
from ha_ai_brain.domain.backtest import Timeline
from ha_ai_brain.domain.models import EntityState
from ha_ai_brain.domain.patterns import AUTOMATED_ORIGINS
from ha_ai_brain.domain.timeutil import day_class, format_minute, local_at, minute_of_day, to_local

NON_STATES = frozenset({"unavailable", "unknown", ""})

# Home Assistant's own semantic classes (not user specific): what makes an entity safety/security relevant.
SAFETY_DOMAINS = frozenset({"lock", "alarm_control_panel", "valve", "siren"})
SAFETY_DEVICE_CLASSES = frozenset(
    {"smoke", "gas", "carbon_monoxide", "moisture", "safety", "tamper", "problem", "lock",
     "door", "window", "garage_door", "garage", "gate", "opening"}
)
# Perimeter-type entities: "open" / "unlocked" is a risk when nobody is home.
PERIMETER_COVER_CLASSES = frozenset({"door", "garage", "gate", "window"})
PERIMETER_OPENING_CLASSES = frozenset({"door", "window", "garage_door", "opening"})
# Fallback for installs that never set device classes on covers.
PERIMETER_NAME_HINTS = ("garage", "gate", "door")

DEFAULT_GRACE_MINUTES = 30
MIN_GRACE_MINUTES = 15
MAX_GRACE_MINUTES = 180
MAX_AUTOMATED_HOLD = timedelta(hours=12)


@dataclass
class ExceptionFinding:
    kind: str  # routine_deviation | dwell_anomaly | silent_entity | flapping | numeric_excursion | stale_sensor | ...
    entity_id: str
    severity: str  # critical | warning | info
    summary: str
    expected_state: str
    current_state: str
    confidence: float = 1.0
    since: datetime | None = None

    @property
    def dedupe_key(self) -> str:
        return f"{self.kind}:{self.entity_id}:{self.current_state}"

    @property
    def feedback_key(self) -> str:
        """Key used to learn from the user's dismissals: independent of the current state value."""
        return f"{self.kind}:{self.entity_id}"


def is_safety_entity(state: EntityState) -> bool:
    if state.domain in SAFETY_DOMAINS:
        return True
    if state.domain == "binary_sensor":
        return (state.device_class or "") in SAFETY_DEVICE_CLASSES
    if state.domain == "cover":
        return is_perimeter_cover(state)
    return False


def is_perimeter_cover(state: EntityState) -> bool:
    if state.domain != "cover":
        return False
    if state.device_class:
        return state.device_class in PERIMETER_COVER_CLASSES
    return any(h in state.entity_id for h in PERIMETER_NAME_HINTS)


def classify_severity(state: EntityState, household: dict[str, Any] | None, now_local: datetime | None = None) -> str:
    """Generic severity: safety-relevant entities escalate when nobody is home or at night; everything else is informational."""
    if not is_safety_entity(state):
        return "info"
    presence = ((household or {}).get("presence") or {}).get("anyone_home")
    part = (household or {}).get("part_of_day")
    if part is None and now_local is not None:
        part = "night" if (now_local.hour >= 23 or now_local.hour < 6) else "day"
    return "critical" if (presence is False or part == "night") else "warning"


def _label(state: EntityState) -> str:
    return str(state.attributes.get("friendly_name") or state.entity_id)


def expected_state_now(
    tl: Timeline,
    entity_id: str,
    now: datetime,
    tz: tzinfo,
    data_start: datetime,
) -> tuple[str, float, int] | None:
    """
    Learned routine for `entity_id` in the current local hour: (state, confidence, days observed).
    A past day only counts when the state was stable through the whole hour (4 samples agree).
    """
    local_now = to_local(now, tz)
    cls = day_class(local_now)
    first_complete = to_local(data_start, tz).date() + timedelta(days=1)
    votes: Counter[str] = Counter()
    day = local_now.date() - timedelta(days=1)
    scanned = 0
    while day >= first_complete and scanned < 60:
        scanned += 1
        if day_class(day) == cls:
            samples = [tl.state_at(entity_id, local_at(day, local_now.hour * 60 + q, tz)) for q in (0, 15, 30, 45)]
            if samples[0] is not None and all(s == samples[0] for s in samples):
                votes[samples[0]] += 1
        day -= timedelta(days=1)
    total = sum(votes.values())
    if total == 0:
        return None
    state, count = votes.most_common(1)[0]
    return state, count / total, total


def derived_grace_minutes(profile: Any, state_value: str) -> int:
    """How long a deviating state must persist before it is worth reporting, learned from how long it usually lasts."""
    dwell = getattr(profile, "dwell", {}).get(state_value) if profile is not None else None
    if dwell and dwell[0] >= 3:
        return int(min(MAX_GRACE_MINUTES, max(MIN_GRACE_MINUTES, 1.5 * dwell[1] / 60.0)))
    return DEFAULT_GRACE_MINUTES


def is_automated_hold(
    eid: str,
    st: EntityState,
    tl: Timeline | None,
    now: datetime,
    rules: list[AutomationRule] | None = None,
    tz: tzinfo | None = None,
    twins: Any = None,
) -> bool:
    """True when a non-safety entity's current state was set by an automation or the brain within the last 12 hours."""
    if is_safety_entity(st) or now - st.last_changed > MAX_AUTOMATED_HOLD:
        return False
    if tl is not None:
        lookup_id = twins.canonical(eid) if twins is not None and hasattr(twins, "canonical") else eid
        last_tr = tl.last_transition_at(lookup_id, now) or (tl.last_transition_at(eid, now) if lookup_id != eid else None)
        if last_tr is not None and last_tr.new_state == st.state and last_tr.origin in AUTOMATED_ORIGINS:
            return True
    return is_state_automated(eid, st.state, rules, since=st.last_changed, now=now, tz=tz, twins=twins)


def find_routine_deviations(
    states: dict[str, EntityState],
    tl: Timeline,
    now: datetime,
    tz: tzinfo,
    data_start: datetime,
    *,
    min_days: int = 3,
    profiles: dict[str, Any] | None = None,
    household: dict[str, Any] | None = None,
    rules: list[AutomationRule] | None = None,
    twins: Any = None,
) -> list[ExceptionFinding]:
    """Any entity with recorded behaviour whose current state contradicts what it reliably is at this hour."""
    findings: list[ExceptionFinding] = []
    local_now = to_local(now, tz)
    for eid, st in states.items():
        if st.state in NON_STATES or not tl.has(eid):
            continue
        grace = derived_grace_minutes((profiles or {}).get(eid), st.state)
        if now - st.last_changed < timedelta(minutes=grace):
            continue
        if is_automated_hold(eid, st, tl, now, rules=rules, tz=tz, twins=twins):
            continue
        learned = expected_state_now(tl, eid, now, tz, data_start)
        if learned is None:
            continue
        expected, conf, days = learned
        min_conf = 0.85 if is_safety_entity(st) else 0.9
        if days < min_days or conf < min_conf or expected == st.state:
            continue
        held = int((now - st.last_changed).total_seconds() // 60)
        findings.append(
            ExceptionFinding(
                kind="routine_deviation",
                entity_id=eid,
                severity=classify_severity(st, household, local_now),
                summary=(
                    f"Exception: {_label(st)} has been '{st.state}' for {held} min, but around "
                    f"{format_minute(minute_of_day(local_now))} it is normally '{expected}' ({conf:.0%} of {days} comparable days)."
                ),
                expected_state=expected,
                current_state=st.state,
                confidence=conf,
                since=st.last_changed,
            )
        )
    return findings


def find_missed_automations(
    expectations: list[RuleExpectation],
    states: dict[str, EntityState],
    now: datetime,
    tz: tzinfo,
    *,
    grace_minutes: int = 10,
    horizon_minutes: int = 90,
) -> list[ExceptionFinding]:
    """A time-triggered automation promised a state that is not there (it failed, was blocked, or was overridden)."""
    findings: list[ExceptionFinding] = []
    local_now = to_local(now, tz)
    for exp in expectations:
        if exp.weekdays is not None and local_now.weekday() not in exp.weekdays:
            continue
        scheduled = local_at(local_now.date(), exp.minute, tz)
        elapsed = (local_now - scheduled).total_seconds() / 60.0
        if not (grace_minutes <= elapsed <= horizon_minutes):
            continue
        st = states.get(exp.entity_id)
        if st is None or st.state in NON_STATES or st.state == exp.expected_state:
            continue
        if to_local(st.last_changed, tz) > scheduled:
            continue  # somebody changed it after the scheduled time: a deliberate override, not a failure
        findings.append(
            ExceptionFinding(
                kind="automation_missed",
                entity_id=exp.entity_id,
                severity="warning" if is_safety_entity(st) else "info",
                summary=(
                    f"Exception: automation '{exp.alias}' should have set {exp.entity_id} to '{exp.expected_state}' at "
                    f"{format_minute(exp.minute)}, but it is still '{st.state}'."
                ),
                expected_state=exp.expected_state,
                current_state=st.state,
                since=scheduled.astimezone(now.tzinfo),
            )
        )
    return findings


def _open_risk(st: EntityState) -> str | None:
    """The risky condition of a perimeter / protection entity ('unlocked', 'disarmed', 'open'), else None."""
    if st.domain == "lock" and st.state == "unlocked":
        return "unlocked"
    if st.domain == "alarm_control_panel" and st.state == "disarmed":
        return "disarmed"
    if st.domain == "cover" and st.state == "open" and is_perimeter_cover(st):
        return "open"
    if st.domain == "binary_sensor" and st.state == "on" and (st.device_class or "") in PERIMETER_OPENING_CLASSES:
        return "open"
    return None


def find_security_while_away(
    states: dict[str, EntityState],
    now: datetime,
    *,
    away_minutes: int = 10,
) -> list[ExceptionFinding]:
    """Deterministic safety net: nobody is home but the perimeter is open / unlocked / disarmed."""
    persons = [s for s in states.values() if s.domain == "person"]
    if not persons or any(p.state == "home" for p in persons):
        return []
    left_at = max(p.last_changed for p in persons)
    if now - left_at < timedelta(minutes=away_minutes):
        return []

    findings: list[ExceptionFinding] = []
    for eid, st in states.items():
        reason = _open_risk(st)
        if not reason:
            continue
        findings.append(
            ExceptionFinding(
                kind="security_while_away",
                entity_id=eid,
                severity="critical" if st.domain in SAFETY_DOMAINS or is_perimeter_cover(st) else "warning",
                summary=f"Exception: {_label(st)} is {reason} while everyone has been away for {int((now - left_at).total_seconds() // 60)} min.",
                expected_state="secured",
                current_state=st.state,
                since=max(left_at, st.last_changed),
            )
        )
    return findings
