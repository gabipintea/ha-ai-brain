"""Capture pre-action state so an autonomous action can be reverted with one tap."""

from __future__ import annotations

from typing import Any

from ha_ai_brain.domain.models import EntityState

REVERSIBLE_DOMAINS = frozenset({"light", "switch", "fan", "humidifier", "input_boolean", "cover", "climate"})
_ATTRS = ("current_position", "temperature", "brightness", "percentage", "target_humidity")


def capture_snapshot(states: dict[str, EntityState], entity_ids: list[str]) -> dict[str, dict[str, Any]]:
    snap: dict[str, dict[str, Any]] = {}
    for eid in entity_ids:
        st = states.get(eid)
        if st is None or st.domain not in REVERSIBLE_DOMAINS:
            continue
        snap[eid] = {"state": st.state, "attributes": {k: st.attributes[k] for k in _ATTRS if k in st.attributes}}
    return snap


def build_undo_calls(snapshot: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Service calls restoring the captured state. Locks / alarms are deliberately never reverted automatically."""
    calls: list[dict[str, Any]] = []
    for eid, prev in snapshot.items():
        domain = eid.split(".", 1)[0]
        state = prev.get("state")
        attrs = prev.get("attributes", {})
        if state in (None, "unavailable", "unknown"):
            continue
        if domain in ("light", "switch", "fan", "humidifier", "input_boolean"):
            if state == "on":
                data: dict[str, Any] = {}
                if domain == "light" and attrs.get("brightness") is not None:
                    data["brightness"] = attrs["brightness"]
                if domain == "fan" and attrs.get("percentage") is not None:
                    data["percentage"] = attrs["percentage"]
                calls.append({"domain": domain, "service": "turn_on", "entity_ids": [eid], "service_data": data})
            elif state == "off":
                calls.append({"domain": domain, "service": "turn_off", "entity_ids": [eid], "service_data": {}})
        elif domain == "cover":
            pos = attrs.get("current_position")
            if pos is not None:
                calls.append({"domain": domain, "service": "set_cover_position", "entity_ids": [eid], "service_data": {"position": pos}})
            elif state in ("open", "closed"):
                svc = "open_cover" if state == "open" else "close_cover"
                calls.append({"domain": domain, "service": svc, "entity_ids": [eid], "service_data": {}})
        elif domain == "climate":
            if state in ("heat", "cool", "off", "auto", "heat_cool"):
                calls.append({"domain": domain, "service": "set_hvac_mode", "entity_ids": [eid], "service_data": {"hvac_mode": state}})
            if attrs.get("temperature") is not None:
                calls.append({"domain": domain, "service": "set_temperature", "entity_ids": [eid], "service_data": {"temperature": attrs["temperature"]}})
    return calls
