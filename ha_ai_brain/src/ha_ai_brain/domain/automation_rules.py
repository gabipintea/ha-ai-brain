"""Structural understanding of the automations already configured in Home Assistant."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import Any

from ha_ai_brain.domain.patterns import MinedPattern, same_device
from ha_ai_brain.domain.service_semantics import ACTUATOR_DOMAINS, is_attribute_state, state_after_service
from ha_ai_brain.domain.timeutil import WEEKDAY_NAMES, circular_distance, minute_of_day, parse_hhmm, to_local

_SIMPLE_CONDITIONS = frozenset({"time"})
# Trigger kinds that fire on a threshold or a template, not on a recurring routine: an automation driven only by these
# (for example an overheat cut-off) does not make a "usually off around 07:30" habit automated.
_NON_ROUTINE_TRIGGERS = frozenset({"numeric_state", "template"})
_CLIMATE_ACTIVE_STATES = frozenset({"heat", "cool", "auto", "heat_cool", "dry", "fan_only"})

_SOLAR_ENTITY_HINTS = (
    "illuminance",
    "lux",
    "daylight",
    "sunlight",
    "irradiance",
    "brightness",
    "light_level",
    "light_sensor",
    "ambient_light",
    "solar_elevation",
    "sun_elevation",
)
_HAZARD_ENTITY_HINTS = (
    "moisture",
    "leak",
    "rain",
    "precipitation",
    "flood",
    "water_leak",
    "smoke",
    "gas",
    "carbon_monoxide",
    "tamper",
    "problem",
    "overheat",
    "frost",
    "freeze",
    "wind",
    "storm",
    "hail",
    "lightning",
    "fire",
    "alarm",
    "battery",
    "degraded",
    "watchdog",
    "emergency",
    "ingress",
    "combustible",
)
_HAZARD_DEVICE_CLASSES = frozenset(
    {
        "moisture",
        "smoke",
        "gas",
        "carbon_monoxide",
        "safety",
        "tamper",
        "problem",
        "cold",
        "heat",
        "precipitation",
        "precipitation_intensity",
        "wind_speed",
        "battery",
    }
)
_HAZARD_TRIGGER_STATES = frozenset(
    {
        "rainy",
        "pouring",
        "lightning",
        "lightning-rainy",
        "hail",
        "snowy",
        "snowy-rainy",
        "windy",
        "windy-variant",
        "exceptional",
        "wet",
        "moist",
        "leak",
        "problem",
        "tamper",
        "smoke",
        "gas",
        "unavailable",
        "unknown",
    }
)

# Blueprint path and entity-id markers for physical wall panels, touchscreens, buttons, switches and remote controllers.
_PANEL_HINTS = ("nspanel", "openhasp", "wallpanel", "nextion")
_CONTROLLER_BLUEPRINT_HINTS = (
    *_PANEL_HINTS,
    "hasp",
    "remote",
    "button",
    "controller",
    "dimmer",
    "knob",
    "dial",
    "keyfob",
    "scene_switch",
    "wall_switch",
    "wireless_switch",
    "smart_switch",
    "tap_dial",
    "styrbar",
    "rodret",
    "tradfri",
    "symfonisk",
    "hue_dimmer",
)
_AUTONOMOUS_BLUEPRINT_EXCLUSIONS = (
    "motion",
    "occupancy",
    "presence",
    "schedule",
    "wake_up",
    "alarm",
    "notification",
    "notify",
    "backup",
    "sensor-light",
    "sensor_light",
)
_CONTROLLER_EVENT_TYPES = frozenset(
    {
        "zha_event",
        "deconz_event",
        "hue_event",
        "lutron_event",
        "lutron_caseta_button_event",
        "shelly.click",
        "bthome_ble_event",
        "matter_event",
    }
)
_CONTROLLER_DEVICE_DOMAINS = frozenset(
    {"zha", "deconz", "mqtt", "hue", "shelly", "lutron_caseta", "bthome", "matter", "esphome"}
)
_CONTROLLER_ACTION_TOKENS = (
    "button",
    "press",
    "release",
    "single",
    "double",
    "triple",
    "quadruple",
    "hold",
    "click",
    "rotate",
    "dial",
)
_SENSOR_TRIGGER_EXCLUSIONS = ("motion", "occupancy", "opened", "closed", "temperature", "humidity", "illuminance", "moist", "leak")


def is_controller_automation_id(entity_id_or_alias: str) -> bool:
    """True when an automation entity_id or alias unambiguously names a physical wall panel (e.g. NSPanel, openHASP)."""
    low = (entity_id_or_alias or "").lower()
    return any(h in low for h in _PANEL_HINTS)


def is_controller_blueprint(path: str) -> bool:
    """True when a Home Assistant `use_blueprint.path` belongs to a wall-panel or physical remote/button controller blueprint."""
    low = (path or "").lower().strip()
    if not low:
        return False
    if any(p in low for p in _PANEL_HINTS):
        return True
    if any(ex in low for ex in _AUTONOMOUS_BLUEPRINT_EXCLUSIONS):
        return False
    return any(h in low for h in _CONTROLLER_BLUEPRINT_HINTS)


def _is_controller_trigger(trig: dict[str, Any]) -> bool:
    """True when a single automation trigger fires only in response to a physical button press, remote event or panel tap."""
    kind = str(trig.get("platform") or trig.get("trigger") or "").lower().strip()
    if kind == "event":
        ev_type = str(trig.get("event_type") or "").lower().strip()
        if ev_type in _CONTROLLER_EVENT_TYPES:
            return True
        if ev_type.startswith("esphome.") and any(k in ev_type for k in (*_PANEL_HINTS, "button", "click", "touch", "page", "command")):
            return True
        return False
    if kind == "state":
        ids = _entity_ids(trig.get("entity_id"))
        return bool(ids) and all(eid.split(".", 1)[0] in ("button", "input_button", "event") for eid in ids)
    if kind == "device":
        dom = str(trig.get("domain") or "").lower().strip()
        sig = f"{trig.get('type') or ''} {trig.get('subtype') or ''}".lower()
        if dom in _CONTROLLER_DEVICE_DOMAINS and not any(ex in sig for ex in _SENSOR_TRIGGER_EXCLUSIONS):
            return any(tok in sig for tok in _CONTROLLER_ACTION_TOKENS)
    return False


def dump_controller_overrides(overrides: dict[str, bool]) -> str:
    return json.dumps({k: bool(v) for k, v in sorted(overrides.items()) if k})


def load_controller_overrides(raw: str | None) -> dict[str, bool]:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): bool(v) for k, v in data.items() if isinstance(k, str) and k.startswith("automation.")}


def clean_alias(alias: str) -> str:
    """Collapse a repeated '[AI Brain]' prefix (older proposals could carry it twice)."""
    name = alias.strip()
    prefix = "[AI Brain]"
    while name.lower().startswith(prefix.lower() + " [ai brain]"):
        name = prefix + name[len(prefix) * 2 + 1 :]
    return name


def strip_brain_prefix(alias: str) -> str:
    """Remove leading '[AI Brain]' prefixes for display and canonical alias comparison."""
    return re.sub(r"^(\s*\[ai brain\]\s*)+", "", alias or "", flags=re.IGNORECASE).strip()


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
    numeric_triggers: list[tuple[str, str | None]] = field(default_factory=list)  # (entity_id, "below" | "above" | "range" | None)
    sun_triggers: list[str] = field(default_factory=list)  # "sunset" | "sunrise" | "solar"
    other_triggers: list[str] = field(default_factory=list)
    weekdays: set[int] | None = None  # 0=Mon; None = every day
    simple_conditions: bool = True  # only time/weekday conditions -> fully predictable
    actions: list[RuleAction] = field(default_factory=list)
    complex_actions: bool = False  # choose / if / repeat blocks
    entity_state_id: str = ""  # the automation.* entity (filled in from the state registry)
    blueprint_path: str = ""  # use_blueprint.path when created from a Home Assistant blueprint
    auto_controller: bool = False  # detected as a wall-panel / remote / button controller bridge
    is_controller: bool = False  # effective controller flag (auto_controller + homeowner overrides)
    controller_reason: str = ""  # plain-language explanation shown in the dashboard
    solar_trigger_entities: set[str] = field(default_factory=set)
    hazard_trigger_entities: set[str] = field(default_factory=set)

    def targets(self) -> list[str]:
        return sorted({a.entity_id for a in self.actions if a.entity_id})

    def summary(self) -> dict[str, Any]:
        triggers: list[str] = [f"time {m // 60:02d}:{m % 60:02d}" for m in self.time_triggers]
        triggers += [f"state {e}->{t or '*'}" for e, t in self.state_triggers]
        triggers += [f"numeric_state {e}({d or '*'})" for e, d in self.numeric_triggers]
        triggers += [t for t in self.other_triggers if not (t == "numeric_state" and self.numeric_triggers)]
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
    if kind == "set_preset_mode" and domain in ("climate", "fan"):
        data = {"preset_mode": item["preset_mode"]} if item.get("preset_mode") is not None else {}
        return domain, "set_preset_mode", data
    if kind == "set_mode" and domain == "humidifier":
        data = {"mode": item["mode"]} if item.get("mode") is not None else {}
        return domain, "set_mode", data
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
            for key in ("hvac_mode", "position", "temperature", "preset_mode", "mode"):
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
    bp = cfg.get("use_blueprint")
    bp_path = str(bp.get("path") or "").strip() if isinstance(bp, dict) else ""
    rule = AutomationRule(
        automation_id=str(cfg.get("id") or ""),
        alias=clean_alias(str(cfg.get("alias") or cfg.get("id") or "automation")),
        blueprint_path=bp_path,
    )
    raw_triggers = [t for t in _listify(cfg.get("trigger") if "trigger" in cfg else cfg.get("triggers")) if isinstance(t, dict)]
    for trig in raw_triggers:
        kind = str(trig.get("platform") or trig.get("trigger") or "")
        if kind == "time":
            at = trig.get("at")
            minute = parse_hhmm(at) if isinstance(at, str) else None
            if minute is not None:
                rule.time_triggers.append(minute)
            else:
                rule.other_triggers.append("time(dynamic)")
        elif kind == "state":
            raw_to = trig.get("to")
            if isinstance(raw_to, list):
                to_str = ",".join(str(x) for x in raw_to if x is not None) or None
            else:
                to_str = None if raw_to is None else str(raw_to)
            for eid in _entity_ids(trig.get("entity_id")):
                rule.state_triggers.append((eid, to_str))
        elif kind == "device" and trig.get("entity_id"):
            has_below = trig.get("below") is not None
            has_above = trig.get("above") is not None
            direction = "range" if (has_below and has_above) else ("below" if has_below else ("above" if has_above else None))
            for eid in _entity_ids(trig.get("entity_id")):
                to = trig.get("to") if trig.get("to") is not None else trig.get("type")
                rule.state_triggers.append((eid, None if to is None else str(to)))
                if direction is not None:
                    rule.numeric_triggers.append((eid, direction))
        elif kind == "numeric_state":
            has_below = trig.get("below") is not None
            has_above = trig.get("above") is not None
            direction = "range" if (has_below and has_above) else ("below" if has_below else ("above" if has_above else None))
            for eid in _entity_ids(trig.get("entity_id")):
                rule.numeric_triggers.append((eid, direction))
            rule.other_triggers.append("numeric_state")
        elif kind == "sun":
            ev = str(trig.get("event") or "").lower().strip()
            rule.sun_triggers.append(ev if ev in ("sunset", "sunrise") else "solar")
            rule.other_triggers.append("sun")
        elif kind == "template":
            tpl = str(trig.get("value_template") or "").lower()
            if "sun.sun" in tpl or "illuminance" in tpl or "_lux" in tpl:
                if "below" in tpl or "<" in tpl or "sunset" in tpl:
                    rule.sun_triggers.append("sunset")
                elif "above" in tpl or ">" in tpl or "sunrise" in tpl:
                    rule.sun_triggers.append("sunrise")
                else:
                    rule.sun_triggers.append("solar")
            rule.other_triggers.append("template")
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

    if is_controller_blueprint(bp_path):
        rule.auto_controller = True
        rule.controller_reason = f"Controller / panel blueprint ({bp_path})"
    elif is_controller_automation_id(f"{rule.automation_id} {rule.alias}"):
        rule.auto_controller = True
        rule.controller_reason = "Wall panel or physical controller automation"
    elif raw_triggers and not rule.time_triggers and all(_is_controller_trigger(t) for t in raw_triggers):
        rule.auto_controller = True
        rule.controller_reason = "Triggered only by physical button, remote or panel events"
    rule.is_controller = rule.auto_controller
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
        rule.numeric_triggers = [
            (reg_map.get(e, e) if "." not in e else e, direction)
            for e, direction in rule.numeric_triggers
        ]
        if states:
            for eid in {e for e, _ in rule.state_triggers} | {e for e, _ in rule.numeric_triggers}:
                st = states.get(eid)
                if st is None:
                    continue
                dclass = (getattr(st, "device_class", None) or "").lower()
                unit = (getattr(st, "unit_of_measurement", None) or "").lower()
                if dclass in ("illuminance", "irradiance") or unit in ("lx", "lux", "w/m²", "w/m2"):
                    rule.solar_trigger_entities.add(eid)
                elif dclass in _HAZARD_DEVICE_CLASSES:
                    rule.hazard_trigger_entities.add(eid)


def action_produces_state(act: RuleAction, state: str) -> bool:
    """True when `act` can place its target entity into `state`."""
    if act.result_state == state:
        return True
    if act.domain == "climate":
        if act.service == "turn_on" and state in _CLIMATE_ACTIVE_STATES:
            return True
        if act.service in ("set_hvac_mode", "set_temperature"):
            raw_mode = str(act.data.get("hvac_mode") or "")
            if raw_mode == state or ("{" in raw_mode and re.search(rf"\b{re.escape(state)}\b", raw_mode)):
                return True
    return False


def rule_produces_state(rule: AutomationRule, entity_id: str, state: str, twins: Any = None) -> bool:
    """True when an enabled `rule` has an action that puts `entity_id` (or its twin) into `state`."""
    if not rule.enabled or rule.is_controller:
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


def _is_solar_entity(entity_id: str, rule: AutomationRule | None = None) -> bool:
    low = (entity_id or "").lower().strip()
    if not low:
        return False
    if rule is not None and entity_id in rule.solar_trigger_entities:
        return True
    if low == "sun.sun" or low.startswith("sun."):
        return True
    return any(h in low for h in _SOLAR_ENTITY_HINTS)


def _is_hazard_trigger(entity_id: str, to_state: str | None = None, rule: AutomationRule | None = None) -> bool:
    low = (entity_id or "").lower().strip()
    if not low:
        return False
    if _is_solar_entity(entity_id, rule):
        return False
    if low.startswith("weather.") or (rule is not None and entity_id in rule.hazard_trigger_entities):
        return True
    if any(h in low for h in _HAZARD_ENTITY_HINTS):
        return True
    if to_state:
        tokens = {t.strip().lower() for t in to_state.split(",") if t.strip()}
        if tokens and tokens <= _HAZARD_TRIGGER_STATES:
            return True
    return False


def _is_hazard_alias(alias: str) -> bool:
    low = strip_brain_prefix(alias).lower()
    if low.startswith("safety:"):
        return True
    words = set(re.findall(r"[a-z0-9_]+", low))
    return bool(
        words
        & {
            "precipitation",
            "rain",
            "leak",
            "moisture",
            "smoke",
            "gas",
            "fire",
            "flood",
            "storm",
            "frost",
            "freeze",
            "overheat",
            "emergency",
            "watchdog",
            "ingress",
            "combustible",
        }
    )


def _rule_solar_phases(rule: AutomationRule) -> set[str]:
    """Solar / daylight phases ('dusk', 'dawn', 'solar') that trigger `rule`."""
    phases: set[str] = set()
    for ev in rule.sun_triggers:
        if ev == "sunset":
            phases.add("dusk")
        elif ev == "sunrise":
            phases.add("dawn")
        else:
            phases.add("solar")
    for eid, to in rule.state_triggers:
        if _is_solar_entity(eid, rule):
            low_to = (to or "").lower().strip()
            if low_to in ("below_horizon", "off", "dark", "night"):
                phases.add("dusk")
            elif low_to in ("above_horizon", "on", "light", "day"):
                phases.add("dawn")
            else:
                phases.add("solar")
    for eid, direction in rule.numeric_triggers:
        if _is_solar_entity(eid, rule):
            if direction == "below":
                phases.add("dusk")
            elif direction == "above":
                phases.add("dawn")
            else:
                phases.add("solar")
    return phases


def _solar_phase_matches_minute(phases: set[str], minute: float) -> bool:
    """True when `minute` (0..1440 local time) is compatible with at least one solar phase in `phases`."""
    if not phases:
        return False
    if "solar" in phases:
        return True
    m = minute % 1440
    if "dusk" in phases and not (4 * 60 <= m < 12 * 60):
        return True
    if "dawn" in phases and not (14 * 60 <= m < 23 * 60):
        return True
    return False


def pattern_covered_by(rules: list[AutomationRule], pattern: MinedPattern, tolerance: int = 45, twins: Any = None) -> str | None:
    """Alias of an enabled automation that already produces the behaviour in `pattern`, else None."""
    best_score = 0
    best_alias: str | None = None
    for rule in rules:
        if not rule.enabled or rule.is_controller:
            continue
        produces = any(
            (same_device(act.entity_id, pattern.entity_id) or (twins and twins.are_twins(act.entity_id, pattern.entity_id)))
            and action_produces_state(act, pattern.to_state)
            for act in rule.actions
        )
        if not produces:
            continue
        if pattern.kind == "time_habit" and pattern.minute_of_day is not None:
            if not _weekday_overlap(rule, pattern.day_class):
                continue
            if any(circular_distance(m, pattern.minute_of_day) <= tolerance for m in rule.time_triggers):
                return rule.alias
            phases = _rule_solar_phases(rule)
            if phases and _solar_phase_matches_minute(phases, pattern.minute_of_day):
                if best_score < 2:
                    best_score, best_alias = 2, rule.alias
                continue
            # Event-driven rules (motion, presence ...) may well produce the same routine, unlike hazard/weather/threshold cut-offs.
            if not rule.time_triggers and not phases and not _is_hazard_alias(rule.alias):
                routine_state = [
                    (e, to)
                    for e, to in rule.state_triggers
                    if not _is_hazard_trigger(e, to, rule) and not _is_solar_entity(e, rule)
                ]
                routine_other = [t for t in rule.other_triggers if t not in _NON_ROUTINE_TRIGGERS and t != "sun"]
                if routine_state or routine_other:
                    if best_score < 1:
                        best_score, best_alias = 1, rule.alias
        elif pattern.kind == "sequence":
            trig_entities = [e for e, _ in rule.state_triggers] + [e for e, _ in rule.numeric_triggers]
            if any(e == pattern.trigger_entity or (twins and twins.are_twins(e, pattern.trigger_entity or "")) for e in trig_entities):
                return rule.alias
    return best_alias


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
        if not rule.enabled or rule.is_controller or not rule.simple_conditions or rule.complex_actions or rule.state_triggers or rule.other_triggers:
            continue
        for minute in rule.time_triggers:
            for act in rule.actions:
                state = act.result_state
                if state and not is_attribute_state(state):
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


def find_equivalent_rule(rules: list[AutomationRule], proposal: dict[str, Any], tolerance: int = 45, twins: Any = None) -> str | None:
    """Alias of an existing enabled automation that already does what `proposal` (a config dict) would do."""
    cand = parse_automation_config(proposal)
    cand_actions = [a for a in cand.actions if a.result_state]
    if not cand_actions:
        return None
    cand_phases = _rule_solar_phases(cand)
    for rule in rules:
        if not rule.enabled or rule.is_controller:
            continue
        shares_effect = any(
            (same_device(ca.entity_id, ra.entity_id) or (twins and twins.are_twins(ca.entity_id, ra.entity_id)))
            and action_produces_state(ra, ca.result_state or "")
            for ca in cand_actions
            for ra in rule.actions
        )
        if not shares_effect:
            continue
        if cand.time_triggers and any(circular_distance(m, n) <= tolerance for m in cand.time_triggers for n in rule.time_triggers):
            return rule.alias
        if cand.state_triggers and {e for e, _ in cand.state_triggers} & {e for e, _ in rule.state_triggers}:
            return rule.alias
        if cand.numeric_triggers and any(
            ce == re and (cd == rd or cd is None or rd is None)
            for ce, cd in cand.numeric_triggers
            for re, rd in rule.numeric_triggers
        ):
            return rule.alias
        rule_phases = _rule_solar_phases(rule)
        if cand_phases and rule_phases and (cand_phases & rule_phases or "solar" in cand_phases or "solar" in rule_phases):
            return rule.alias
        if cand.time_triggers and rule_phases and any(_solar_phase_matches_minute(rule_phases, m) for m in cand.time_triggers):
            return rule.alias
        if rule.time_triggers and cand_phases and any(_solar_phase_matches_minute(cand_phases, m) for m in rule.time_triggers):
            return rule.alias
    return None
