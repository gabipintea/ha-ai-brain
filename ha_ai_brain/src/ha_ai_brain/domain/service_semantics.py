"""Mapping between Home Assistant service calls and the entity state they produce (and back)."""

from __future__ import annotations

from typing import Any

# Domains whose state a household can flip by hand and an automation can reproduce.
ACTUATOR_DOMAINS = frozenset(
    {"light", "switch", "cover", "climate", "fan", "humidifier", "lock", "input_boolean", "water_heater", "valve"}
)

# A script has no lasting state: a hand-started run is recorded as this momentary "state" so it can be mined like any habit.
SCRIPT_RUN_STATE = "run"
TEMP_STATE_PREFIX = "temp:"
PRESET_STATE_PREFIX = "preset:"

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


def format_temp_token(value: Any) -> str | None:
    """Canonical transition token (`temp:21`, `temp:20.5`) for a target temperature attribute, or None if invalid."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = round(float(value), 1)
    except (TypeError, ValueError):
        return None
    if not (4.0 <= num <= 95.0):
        return None
    return f"{TEMP_STATE_PREFIX}{num:g}"


def format_preset_token(value: Any) -> str | None:
    """Canonical transition token (`preset:eco`, `preset:comfort`) for a preset/mode attribute, or None if invalid."""
    preset = str(value or "").strip()
    if not preset or preset.lower() in ("unknown", "unavailable", "null") or "{" in preset:
        return None
    return f"{PRESET_STATE_PREFIX}{preset}"


def state_channel(state: str | None) -> str:
    """State sub-channel: `'temp'` for target temperature, `'preset'` for preset mode, or `''` for primary entity state."""
    s = state or ""
    if s.startswith(TEMP_STATE_PREFIX):
        return "temp"
    if s.startswith(PRESET_STATE_PREFIX):
        return "preset"
    return ""


def is_attribute_state(state: str | None) -> bool:
    """True when `state` represents an attribute transition (`temp:...` or `preset:...`) rather than `.state`."""
    return bool(state_channel(state))


def describe_state(state: str) -> str:
    """Human-readable representation of a state or attribute token for habit descriptions."""
    if state.startswith(TEMP_STATE_PREFIX):
        return f"{state[len(TEMP_STATE_PREFIX):]}°"
    if state.startswith(PRESET_STATE_PREFIX):
        return f"preset '{state[len(PRESET_STATE_PREFIX):]}'"
    return f"{state!r}"


def state_after_service(domain: str, service: str, data: dict[str, Any] | None = None) -> str | None:
    """The state an entity ends in after `domain.service`, if that is well defined."""
    if domain in ("climate", "water_heater") and service == "set_temperature":
        tok = format_temp_token((data or {}).get("temperature"))
        if tok is not None:
            return tok
        mode = (data or {}).get("hvac_mode")
        return str(mode) if mode and "{" not in str(mode) else None
    if domain == "climate":
        if service == "set_hvac_mode":
            mode = (data or {}).get("hvac_mode")
            return str(mode) if mode and "{" not in str(mode) else None
        if service == "set_preset_mode":
            tok = format_preset_token((data or {}).get("preset_mode"))
            return tok if tok and tok.lower() != "preset:none" else tok
        if service == "turn_off":
            return "off"
    if domain == "fan" and service == "set_preset_mode":
        return format_preset_token((data or {}).get("preset_mode"))
    if domain == "humidifier" and service == "set_mode":
        return format_preset_token((data or {}).get("mode"))
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
    if state.startswith(TEMP_STATE_PREFIX) and domain in ("climate", "water_heater"):
        try:
            val = round(float(state[len(TEMP_STATE_PREFIX):]), 1)
        except ValueError:
            return None
        if not (4.0 <= val <= 95.0):
            return None
        return "set_temperature", {"temperature": int(val) if val.is_integer() else val}
    if state.startswith(PRESET_STATE_PREFIX):
        preset = state[len(PRESET_STATE_PREFIX):].strip()
        if not preset or preset.lower() in ("none", "null", "unknown", "unavailable"):
            return None
        if domain in ("climate", "fan"):
            return "set_preset_mode", {"preset_mode": preset}
        if domain == "humidifier":
            return "set_mode", {"mode": preset}
        return None
    if domain == "climate" and state in ("heat", "cool", "off", "auto", "heat_cool", "dry", "fan_only"):
        return "set_hvac_mode", {"hvac_mode": state}
    svc = _STATE_SERVICE.get(domain, {}).get(state)
    return (svc, {}) if svc else None
