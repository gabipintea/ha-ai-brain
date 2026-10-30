"""Structural understanding of the automations already configured in Home Assistant."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any

from ha_ai_brain.domain.patterns import MinedPattern, same_device
from ha_ai_brain.domain.service_semantics import ACTUATOR_DOMAINS, state_after_service
from ha_ai_brain.domain.timeutil import WEEKDAY_NAMES, circular_distance, minute_of_day, parse_hhmm, to_local

_SIMPLE_CONDITIONS = frozenset({"time"})
# Trigger kinds that fire on a threshold or a template, not on a recurring routine: an automation driven only by these
# (for example an overheat cut-off) does not make a "usually off around 07:30" habit automated.
_NON_ROUTINE_TRIGGERS = frozenset({"numeric_state", "template"})
_CLIMATE_ACTIVE_STATES = frozenset({"heat", "cool", "auto", "heat_cool", "dry", "fan_only"})


def clean_alias(alias: str) -> str:
    """Collapse a repeated '[AI Brain]' prefix (older proposals could carry it twice)."""
    name = alias.strip()
    prefix = "[AI Brain]"
    while name.lower().startswith(prefix.lower() + " [ai brain]"):
        name = prefix + name[len(prefix) * 2 + 1 :]
    return name


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _entity_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return []


@dataclass
class RuleAction:
    entity_id: str
    domain: str
    service: str
    data: dict[str, Any] = field(default_factory=dict)
    device_id: str = ""
    area_id: str = ""

    @property
    def result_state(self) -> str | None:
        return state_after_service(self.domain, self.service, self.data)


@dataclass
class AutomationRule:
    automation_id: str
    alias: str
    enabled: bool = True
    time_triggers: list[int] = field(default_factory=list)  # minutes of day (local)
    state_triggers: list[tuple[str, str | None]] = field(default_factory=list)
    other_triggers: list[str] = field(default_factory=list)
    weekdays: set[int] | None = None  # 0=Mon; None = every day
    simple_conditions: bool = True  # only time/weekday conditions -> fully predictable
    actions: list[RuleAction] = field(default_factory=list)
    complex_actions: bool = False  # choose / if / repeat blocks
    entity_state_id: str = ""  # the automation.* entity (filled in from the state registry)

    def targets(self) -> list[str]:
        return sorted({a.entity_id for a in self.actions if a.entity_id})

    def summary(self) -> dict[str, Any]:
        triggers: list[str] = [f"time {m // 60:02d}:{m % 60:02d}" for m in self.time_triggers]
        triggers += [f"state {e}->{t or '*'}" for e, t in self.state_triggers]
        triggers += self.other_triggers
        return {
            "alias": self.alias,
            "enabled": self.enabled,
            "triggers": triggers,
            "weekdays": [WEEKDAY_NAMES[i] for i in sorted(self.weekdays)] if self.weekdays is not None else "all",
            "actions": [f"{a.domain}.{a.service} -> {a.entity_id}" for a in self.actions if a.entity_id][:8],
        }


def _device_action_call(item: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    """Translate a Home Assistant UI device action (`domain` + `type`) into `(domain, service, data)`."""
    domain = str(item.get("domain") or "").strip()
    kind = str(item.get("type") or "").strip()
    if not domain or not kind:
        return None
    if kind == "set_hvac_mode" and domain == "climate":
        data = {"hvac_mode": item["hvac_mode"]} if item.get("hvac_mode") is not None else {}
        return domain, "set_hvac_mode", data
    if kind in ("turn_on", "turn_off", "toggle"):
        return domain, kind, {}
    if kind in ("open", "close") and domain in ("cover", "valve"):
        return domain, f"{kind}_{domain}", {}
    if kind == "set_position" and domain == "cover":
        data = {"position": item["position"]} if item.get("position") is not None else {}
        return domain, "set_cover_position", data
    if kind in ("lock", "unlock") and domain == "lock":
        return domain, kind, {}
    return None


def _collect_actions(items: list[Any], rule: AutomationRule, depth: int = 0) -> None:
    for item in items:
        if not isinstance(item, dict):
            continue
        svc = item.get("service") or item.get("action")
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        call: tuple[str, str, dict[str, Any]] | None = None
        if isinstance(svc, str) and "." in svc:
            domain, _, service = svc.partition(".")
            clean_data = {k: v for k, v in data.items() if k != "entity_id"}
            for key in ("hvac_mode", "position"):
                if key not in clean_data and item.get(key) is not None:
                    clean_data[key] = item[key]
            call = (domain, service, clean_data)
        else:
            call = _device_action_call(item)

        if call is not None:
            domain, service, clean_data = call
            ids = _entity_ids(target.get("entity_id")) or _entity_ids(item.get("entity_id")) or _entity_ids(data.get("entity_id"))
            dev_ids = _entity_ids(target.get("device_id")) or _entity_ids(item.get("device_id"))
            area_ids = _entity_ids(target.get("area_id")) or _entity_ids(item.get("area_id"))
            if domain == "script" and service not in ("turn_on", "turn_off", "toggle", "reload"):
                ids = [f"script.{service}"]  # `script.movie_mode` called directly runs that script
                service = "turn_on"
            for eid in ids:
                eff_domain = eid.split(".", 1)[0] if domain == "homeassistant" and "." in eid else domain
                rule.actions.append(RuleAction(eid, eff_domain, service, clean_data))
            if not ids:
                for did in dev_ids:
                    rule.actions.append(RuleAction("", domain, service, clean_data, device_id=did))
                for aid in area_ids:
                    rule.actions.append(RuleAction("", domain, service, clean_data, area_id=aid))
            continue

        rule.complex_actions = True
        if depth > 4:
            continue
        for key in ("sequence", "then", "else", "default"):
            if isinstance(item.get(key), list):
                _collect_actions(item[key], rule, depth + 1)
        for branch in _listify(item.get("choose")):
            if isinstance(branch, dict) and isinstance(branch.get("sequence"), list):
                _collect_actions(branch["sequence"], rule, depth + 1)
        for branch in _listify(item.get("parallel")):
            if isinstance(branch, dict) and isinstance(branch.get("sequence"), list):
                _collect_actions(branch["sequence"], rule, depth + 1)
            elif isinstance(branch, dict):
                _collect_actions([branch], rule, depth + 1)
            elif isinstance(branch, list):
                _collect_actions(branch, rule, depth + 1)
        if isinstance(item.get("repeat"), dict) and isinstance(item["repeat"].get("sequence"), list):
            _collect_actions(item["repeat"]["sequence"], rule, depth + 1)


def parse_automation_config(cfg: dict[str, Any]) -> AutomationRule:
    """Parse a Home Assistant automation config (old `trigger/condition/action` or new plural keys)."""
    rule = AutomationRule(
        automation_id=str(cfg.get("id") or ""),
        alias=clean_alias(str(cfg.get("alias") or cfg.get("id") or "automation")),
    )
    for trig in _listify(cfg.get("trigger") if "trigger" in cfg else cfg.get("triggers")):
        if not isinstance(trig, dict):
            continue
        kind = str(trig.get("platform") or trig.get("trigger") or "")
        if kind == "time":
            at = trig.get("at")
            minute = parse_hhmm(at) if isinstance(at, str) else None
            if minute is not None:
                rule.time_triggers.append(minute)
            else:
                rule.other_triggers.append("time(dynamic)")
        elif kind == "state":
            for eid in _entity_ids(trig.get("entity_id")):
                to = trig.get("to")
                rule.state_triggers.append((eid, None if to is None else str(to)))
        elif kind == "device" and trig.get("entity_id"):
            for eid in _entity_ids(trig.get("entity_id")):
                to = trig.get("to") if trig.get("to") is not None else trig.get("type")
                rule.state_triggers.append((eid, None if to is None else str(to)))
        else:
            rule.other_triggers.append(kind or "unknown")

    for cond in _listify(cfg.get("condition") if "condition" in cfg else cfg.get("conditions")):
        if not isinstance(cond, dict):
            rule.simple_conditions = False
            continue
        kind = str(cond.get("condition") or "")
        if kind == "time" and set(cond) <= {"condition", "weekday", "alias", "enabled"}:
            wd = {WEEKDAY_NAMES.index(str(w).lower()[:3]) for w in _listify(cond.get("weekday")) if str(w).lower()[:3] in WEEKDAY_NAMES}
            if wd:
                rule.weekdays = wd if rule.weekdays is None else rule.weekdays & wd
        elif kind not in _SIMPLE_CONDITIONS:
            rule.simple_conditions = False
        else:
            rule.simple_conditions = False  # before/after windows etc. are not modelled

    _collect_actions(_listify(cfg.get("action") if "action" in cfg else cfg.get("actions")), rule)
    return rule


def resolve_rule_targets(
    rules: list[AutomationRule],
    states: dict[str, Any] | None = None,
    facts: list[Any] | None = None,
) -> None:
    """Expand device_id, area_id and entity-registry UUID targets in `rules` into concrete entity_ids."""
    reg_map = {f.registry_id: f.entity_id for f in (facts or ()) if getattr(f, "registry_id", "") and getattr(f, "entity_id", "")}
    by_device: dict[str, list[str]] = {}
    for f in facts or ():
        if getattr(f, "device_id", "") and getattr(f, "entity_id", "") and not getattr(f, "disabled", False):
            by_device.setdefault(f.device_id, []).append(f.entity_id)
    by_area: dict[str, list[str]] = {}
    for eid, st in (states or {}).items():
        aid = getattr(st, "area_id", None)
        if aid:
            by_area.setdefault(str(aid), []).append(eid)

    def _domain_matches(action_domain: str, entity_id: str) -> bool:
        ent_dom = entity_id.split(".", 1)[0]
        if action_domain == "homeassistant":
            return ent_dom in ACTUATOR_DOMAINS
        return ent_dom == action_domain

    for rule in rules:
        resolved: list[RuleAction] = []
        for act in rule.actions:
            eid = reg_map.get(act.entity_id, act.entity_id) if act.entity_id and "." not in act.entity_id else act.entity_id
            if eid and "." in eid:
                eff_dom = eid.split(".", 1)[0] if act.domain == "homeassistant" else act.domain
                resolved.append(RuleAction(eid, eff_dom, act.service, act.data))
                continue
            candidates: list[str] = []
            if act.device_id:
                candidates.extend(e for e in by_device.get(act.device_id, ()) if _domain_matches(act.domain, e))
            if act.area_id:
                candidates.extend(e for e in by_area.get(act.area_id, ()) if _domain_matches(act.domain, e))
            if candidates:
                for target_eid in dict.fromkeys(candidates):
                    eff_dom = target_eid.split(".", 1)[0] if act.domain == "homeassistant" else act.domain
                    resolved.append(RuleAction(target_eid, eff_dom, act.service, act.data))
            elif act.entity_id:
                resolved.append(act)
        rule.actions = resolved
        rule.state_triggers = [
            (reg_map.get(e, e) if "." not in e else e, to)
            for e, to in rule.state_triggers
        ]


def action_produces_state(act: RuleAction, state: str) -> bool:
    """True when `act` can place its target entity into `state`."""
    if act.result_state == state:
        return True
    if act.domain == "climate":
        if act.service == "turn_on" and state in _CLIMATE_ACTIVE_STATES:
            return True
        if act.service in ("set_hvac_mode", "set_temperature"):
            raw_mode = str(act.data.get("hvac_mode") or "")
            if "{" in raw_mode and re.search(rf"\b{re.escape(state)}\b", raw_mode):
                return True
    return False


def rule_produces_state(rule: AutomationRule, entity_id: str, state: str, twins: Any = None) -> bool:
    """True when an enabled `rule` has an action that puts `entity_id` (or its twin) into `state`."""
    if not rule.enabled:
        return False
    return any(
        (same_device(a.entity_id, entity_id) or (twins is not None and twins.are_twins(a.entity_id, entity_id)))
        and action_produces_state(a, state)
        for a in rule.actions
    )


def is_state_automated(
    entity_id: str,
    state: str,
    rules: list[AutomationRule] | None,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
    tz: tzinfo | None = None,
    twins: Any = None,
) -> bool:
    """True when an enabled automation in `rules` explains `entity_id` currently being in `state`."""
    if not rules:
        return False
    for rule in rules:
        if not rule_produces_state(rule, entity_id, state, twins=twins):
            continue
        if rule.weekdays is not None and tz is not None and (since is not None or now is not None):
            days = {to_local(t, tz).weekday() for t in (since, now) if t is not None}
            if not (days & rule.weekdays):
                continue
        pure_time = (
            bool(rule.time_triggers)
            and not rule.state_triggers
            and not rule.other_triggers
            and rule.simple_conditions
            and not rule.complex_actions
        )
        if pure_time and since is not None and tz is not None:
            since_min = minute_of_day(to_local(since, tz))
            if any(circular_distance(m, since_min) <= 45 for m in rule.time_triggers):
                return True
            if now is not None and any(circular_distance(m, minute_of_day(to_local(now, tz))) <= 90 for m in rule.time_triggers):
                return True
            continue
        return True
    return False


def _weekday_overlap(rule: AutomationRule, day_class: str) -> bool:
    if rule.weekdays is None or day_class == "all":
        return True
    days = set(range(0, 5)) if day_class == "weekday" else {5, 6}
    return bool(rule.weekdays & days)


def pattern_covered_by(rules: list[AutomationRule], pattern: MinedPattern, tolerance: int = 45, twins: Any = None) -> str | None:
    """Alias of an enabled automation that already produces the behaviour in `pattern`, else None."""
    for rule in rules:
        if not rule.enabled:
            continue
        for act in rule.actions:
            if not (same_device(act.entity_id, pattern.entity_id) or (twins and twins.are_twins(act.entity_id, pattern.entity_id))) or not action_produces_state(act, pattern.to_state):
                continue
            if pattern.kind == "time_habit" and pattern.minute_of_day is not None:
                if any(circular_distance(m, pattern.minute_of_day) <= tolerance for m in rule.time_triggers) and _weekday_overlap(
                    rule, pattern.day_class
                ):
                    return rule.alias
                # Event-driven rules (motion, sun, presence ...) may well produce the same routine.
                routine_triggers = rule.state_triggers or [t for t in rule.other_triggers if t not in _NON_ROUTINE_TRIGGERS]
                if not rule.time_triggers and routine_triggers:
                    return rule.alias
            elif pattern.kind == "sequence":
                if any(e == pattern.trigger_entity or (twins and twins.are_twins(e, pattern.trigger_entity or "")) for e, _ in rule.state_triggers):
                    return rule.alias
    return None


@dataclass(frozen=True)
class RuleExpectation:
    automation_id: str
    alias: str
    entity_id: str
    expected_state: str
    minute: int
    weekdays: frozenset[int] | None


def rule_expectations(rules: list[AutomationRule]) -> list[RuleExpectation]:
    """What each fully-predictable time-triggered automation promises to have done by a given time."""
    out: list[RuleExpectation] = []
    for rule in rules:
        if not rule.enabled or not rule.simple_conditions or rule.complex_actions or rule.state_triggers or rule.other_triggers:
            continue
        for minute in rule.time_triggers:
            for act in rule.actions:
                state = act.result_state
                if state:
                    out.append(
                        RuleExpectation(
                            rule.automation_id,
                            rule.alias,
                            act.entity_id,
                            state,
                            minute,
                            frozenset(rule.weekdays) if rule.weekdays is not None else None,
                        )
                    )
    return out


def find_equivalent_rule(rules: list[AutomationRule], proposal: dict[str, Any], tolerance: int = 45) -> str | None:
    """Alias of an existing enabled automation that already does what `proposal` (a config dict) would do."""
    cand = parse_automation_config(proposal)
    cand_effects = {(a.entity_id, a.result_state) for a in cand.actions if a.result_state}
    if not cand_effects:
        return None
    for rule in rules:
        if not rule.enabled:
            continue
        if not cand_effects & {(a.entity_id, a.result_state) for a in rule.actions if a.result_state}:
            continue
        if cand.time_triggers and any(circular_distance(m, n) <= tolerance for m in cand.time_triggers for n in rule.time_triggers):
            return rule.alias
        if cand.state_triggers and {e for e, _ in cand.state_triggers} & {e for e, _ in rule.state_triggers}:
            return rule.alias
    return None
