"""Plain-language automation drafts: the compiler prompt, YAML round-trip and validation (no I/O)."""

from __future__ import annotations

import re
from typing import Any

import yaml
from pydantic import ValidationError

from ha_ai_brain.domain.models import NativeAutomationProposal

COMPILER_SYSTEM_PROMPT = (
    "You write ONE native Home Assistant automation from a homeowner's plain-language request.\n"
    "Use ONLY entity ids that appear in `entities`; never invent entities. Use real Home Assistant services "
    "(e.g. light.turn_on, cover.open_cover, climate.set_temperature, notify.notify).\n"
    "Return JSON: {\"automation\": {\"alias\": short title, \"description\": one sentence, \"mode\": \"single\"|\"restart\"|\"queued\"|\"parallel\", "
    "\"trigger\": [Home Assistant trigger objects, e.g. {\"platform\": \"time\", \"at\": \"07:30:00\"} or "
    "{\"platform\": \"state\", \"entity_id\": \"...\", \"to\": \"on\", \"for\": \"00:05:00\"}], "
    "\"condition\": [Home Assistant condition objects, [] if none], "
    "\"action\": [Home Assistant action objects, e.g. {\"service\": \"light.turn_off\", \"target\": {\"entity_id\": \"light.x\"}}]}, "
    "\"explanation\": one or two sentences stating how you interpreted the request and any assumption you made}.\n"
    "Prefer plain, readable automations. If the request cannot be expressed or is too ambiguous to be safe, "
    "return {\"error\": \"why\"}. Write `alias`, `description` and `explanation` in the language of the request."
)

_ENTITY_KEYS = ("entity_id",)
_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def referenced_entities(node: Any) -> set[str]:
    """Every entity id mentioned anywhere in triggers, conditions or actions."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _ENTITY_KEYS:
                values = value if isinstance(value, list) else [value]
                found.update(v for v in values if isinstance(v, str) and _ENTITY_RE.match(v))
            else:
                found |= referenced_entities(value)
    elif isinstance(node, list):
        for item in node:
            found |= referenced_entities(item)
    return found


def _service_names(node: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        for key in ("service", "action"):
            value = node.get(key)
            if isinstance(value, str) and "." in value and "{{" not in value:
                names.add(value)
        for value in node.values():
            names |= _service_names(value)
    elif isinstance(node, list):
        for item in node:
            names |= _service_names(item)
    return names


def validate_draft(
    proposal: NativeAutomationProposal,
    known_entity_ids: set[str],
    available_services: dict[str, list[str]] | None = None,
) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors block creation; warnings are shown but allowed."""
    errors: list[str] = []
    warnings: list[str] = []
    if not proposal.alias.strip():
        errors.append("The automation needs a name (alias).")
    if not proposal.trigger:
        errors.append("The automation needs at least one trigger.")
    if not proposal.action:
        errors.append("The automation needs at least one action.")
    if proposal.mode not in ("single", "restart", "queued", "parallel"):
        errors.append(f"Unknown mode '{proposal.mode}' (use single, restart, queued or parallel).")
    if known_entity_ids:
        missing = sorted(e for e in referenced_entities([proposal.trigger, proposal.condition, proposal.action]) if e not in known_entity_ids)
        if missing:
            errors.append("These entities do not exist in Home Assistant: " + ", ".join(missing))
    if available_services:
        for svc in sorted(_service_names(proposal.action)):
            domain, _, name = svc.partition(".")
            if domain in available_services and name not in available_services[domain]:
                warnings.append(f"Home Assistant does not list the service '{svc}'.")
    return errors, warnings


def proposal_to_yaml(proposal: NativeAutomationProposal) -> str:
    """The editable part of a proposal as Home Assistant-style YAML."""
    doc: dict[str, Any] = {"alias": proposal.alias, "description": proposal.description, "mode": proposal.mode}
    doc["trigger"] = proposal.trigger
    doc["condition"] = proposal.condition
    doc["action"] = proposal.action
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def proposal_from_yaml(text: str, automation_id: str | None = None) -> NativeAutomationProposal:
    """Parse user-edited YAML. Accepts HA's plural keys (triggers/conditions/actions) too. Raises ValueError."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"This is not valid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("Expected a YAML mapping with alias, trigger, condition and action.")

    def pick(*keys: str) -> Any:
        for key in keys:
            if key in doc:
                return doc[key]
        return None

    def as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    data: dict[str, Any] = {
        "alias": str(doc.get("alias") or "").strip(),
        "description": str(doc.get("description") or ""),
        "mode": str(doc.get("mode") or "single"),
        "trigger": as_list(pick("trigger", "triggers")),
        "condition": as_list(pick("condition", "conditions")),
        "action": as_list(pick("action", "actions")),
    }
    if automation_id:
        data["automation_id"] = automation_id
    try:
        return NativeAutomationProposal.model_validate(data)
    except ValidationError as exc:
        raise ValueError("; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:4])) from exc


def proposal_from_ai(payload: dict[str, Any]) -> NativeAutomationProposal:
    """Build a proposal from the compiler's JSON. Raises ValueError."""
    data = {
        "alias": str(payload.get("alias") or "").strip(),
        "description": str(payload.get("description") or ""),
        "mode": str(payload.get("mode") or "single"),
        "trigger": payload.get("trigger") if isinstance(payload.get("trigger"), list) else [],
        "condition": payload.get("condition") if isinstance(payload.get("condition"), list) else [],
        "action": payload.get("action") if isinstance(payload.get("action"), list) else [],
    }
    try:
        return NativeAutomationProposal.model_validate(data)
    except ValidationError as exc:
        raise ValueError("; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:4])) from exc
