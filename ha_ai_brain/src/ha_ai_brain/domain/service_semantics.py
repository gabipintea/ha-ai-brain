"""Mapping between Home Assistant service calls and the entity state they produce (and back)."""

from __future__ import annotations

from typing import Any

# Domains whose state a household can flip by hand and an automation can reproduce.
ACTUATOR_DOMAINS = frozenset(
    {"light", "switch", "cover", "climate", "fan", "humidifier", "lock", "input_boolean", "water_heater", "valve"}
)

# A script has no lasting state: a hand-started run is recorded as this momentary "state" so it can be mined like any habit.
SCRIPT_RUN_STATE = "run"

_ON_OFF = {"turn_on": "on", "turn_off": "off"}
_RESULT_STATE: dict[str, dict[str, str]] = {
    "light": _ON_OFF,
    "switch": _ON_OFF,
    "fan": _ON_OFF,
    "humidifier": _ON_OFF,
    "input_boolean": _ON_OFF,
    "cover": {"open_cover": "open", "close_cover": "closed"},
    "lock": {"lock": "locked", "unlock": "unlocked"},
    "valve": {"open_valve": "open", "close_valve": "closed"},
    "script": {"turn_on": SCRIPT_RUN_STATE},
}

_STATE_SERVICE: dict[str, dict[str, str]] = {
    dom: {state: svc for svc, state in mapping.items()} for dom, mapping in _RESULT_STATE.items()
}

# Never propose automations that remove protection.
NEVER_AUTOMATE = frozenset({("lock", "unlocked"), ("alarm_control_panel", "disarmed"), ("valve", "closed")})


def state_after_service(domain: str, service: str, data: dict[str, Any] | None = None) -> str | None:
    """The state an entity ends in after `domain.service`, if that is well defined."""
    if domain == "climate":
        if service in ("set_hvac_mode", "set_temperature"):
            mode = (data or {}).get("hvac_mode")
            return str(mode) if mode and "{" not in str(mode) else None
        if service == "turn_off":
            return "off"
    if domain == "cover" and service == "set_cover_position":
        try:
            return "open" if float((data or {}).get("position", 0)) > 0 else "closed"
        except (TypeError, ValueError):
            return None
    mapped = _RESULT_STATE.get(domain, {}).get(service)
    if mapped is not None:
        return mapped
    if service == "turn_off":
        return "off"
    if service == "turn_on" and domain not in ("climate", "water_heater", "media_player"):
        return "on"
    return None


def service_for_state(domain: str, state: str) -> tuple[str, dict[str, Any]] | None:
    """The service call that brings an entity of `domain` into `state`, or None if there is no safe equivalent."""
    if (domain, state) in NEVER_AUTOMATE:
        return None
    if domain == "climate" and state in ("heat", "cool", "off", "auto", "heat_cool", "dry", "fan_only"):
        return "set_hvac_mode", {"hvac_mode": state}
    svc = _STATE_SERVICE.get(domain, {}).get(state)
    return (svc, {}) if svc else None
