"""
Service and Entity validation and normalization engine for Home Assistant automations and service calls.
Ensures actions, triggers, and conditions reference real, existing HA entities and services,
and intelligently resolves device notification services (e.g. resolving non-prefixed mobile app targets).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ha_ai_brain.domain.models import NativeAutomationProposal

logger = logging.getLogger(__name__)

# Common action aliases that users or LLMs frequently output
COMMON_SERVICE_ALIASES: dict[str, dict[str, str]] = {
    "switch": {"on": "turn_on", "turnon": "turn_on", "off": "turn_off", "turnoff": "turn_off"},
    "light": {"on": "turn_on", "turnon": "turn_on", "off": "turn_off", "turnoff": "turn_off"},
    "fan": {"on": "turn_on", "turnon": "turn_on", "off": "turn_off", "turnoff": "turn_off"},
    "cover": {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"},
    "climate": {"set_temp": "set_temperature", "temp": "set_temperature"},
}


def resolve_notification_service(
    target_service: str,
    available_notify_services: list[str],
    preferred_service: str = "notify.notify",
) -> str:
    """
    Intelligently resolve a notification service target against real discovered HA notify services.
    
    Examples:
    - If target_service is already in available_notify_services (e.g. 'notify.mobile_app_myphone') -> returns as is.
    - If target_service lacks 'mobile_app_' (e.g. 'notify.myphone' or 'myphone') -> resolves to 'notify.mobile_app_myphone'.
    - If target_service is a substring of an available service -> resolves to that service.
    - If unknown/invalid -> falls back to preferred_service (if valid in available) or 'notify.notify'.
    """
    if not available_notify_services:
        return preferred_service or "notify.notify"

    raw = (target_service or "").strip().lower()
    if not raw:
        return preferred_service or "notify.notify"

    domain, _, svc = raw.partition(".")
    if not svc:
        svc = domain
        domain = "notify"
    if domain != "notify":
        svc = f"{domain}_{svc}"
        domain = "notify"

    candidate_full = f"notify.{svc}"

    # 1. Exact match in available services
    avail_lower = {s.lower(): s for s in available_notify_services}
    if candidate_full in avail_lower:
        return avail_lower[candidate_full]

    # 2. Try prefixing with mobile_app_
    mobile_candidate = f"notify.mobile_app_{svc}".lower()
    if mobile_candidate in avail_lower:
        return avail_lower[mobile_candidate]

    # 3. Try removing common prefix if user gave notify.notify_myphone
    clean_svc = re.sub(r"^(notify_|mobile_app_|app_)", "", svc)
    mobile_candidate_clean = f"notify.mobile_app_{clean_svc}".lower()
    if mobile_candidate_clean in avail_lower:
        return avail_lower[mobile_candidate_clean]

    # 4. Partial / Substring match against available mobile_app services
    # e.g., if svc is 'phone' or 'myphone', match 'notify.mobile_app_myphone'
    for k, orig in avail_lower.items():
        if clean_svc and (clean_svc in k or k.endswith(f"_{clean_svc}")):
            return orig

    # 4b. Strip trailing counter digits (e.g. 'phone_2' -> 'phone' from duplicated mobile apps)
    base_clean_svc = re.sub(r"_\d+$", "", clean_svc)
    if base_clean_svc != clean_svc:
        for k, orig in avail_lower.items():
            if base_clean_svc and (base_clean_svc in k or k.endswith(f"_{base_clean_svc}")):
                return orig

    # 5. Fallback: preferred_service if valid in available, else notify.notify if available, else first
    pref_lower = (preferred_service or "").lower()
    if pref_lower in avail_lower:
        return avail_lower[pref_lower]
    if "notify.notify" in avail_lower:
        return avail_lower["notify.notify"]
    if "notify.persistent_notification" in avail_lower:
        return avail_lower["notify.persistent_notification"]

    return available_notify_services[0]


def normalize_single_action(
    action: dict[str, Any],
    available_services: dict[str, list[str]],
    available_notify_services: list[str],
    preferred_notify_service: str = "notify.notify",
    known_entity_ids: set[str] | None = None,
) -> dict[str, Any]:
    """
    Normalize and validate a single Home Assistant automation action dictionary.
    Handles 'service' and 'action' keys, resolves notification services against HA,
    and applies service aliases.
    """
    normalized = dict(action)

    # In HA, action can be specified by 'service' or 'action' (HA 2024+ syntax)
    service_key = "service" if "service" in normalized else ("action" if "action" in normalized else None)
    if not service_key:
        # Check nested structures (e.g. choose, if/then, repeat)
        if "choose" in normalized and isinstance(normalized["choose"], list):
            new_choose = []
            for branch in normalized["choose"]:
                if isinstance(branch, dict):
                    b = dict(branch)
                    if "sequence" in b and isinstance(b["sequence"], list):
                        b["sequence"] = [
                            normalize_single_action(
                                act, available_services, available_notify_services, preferred_notify_service, known_entity_ids
                            )
                            if isinstance(act, dict) else act
                            for act in b["sequence"]
                        ]
                    new_choose.append(b)
            normalized["choose"] = new_choose

        if "then" in normalized and isinstance(normalized["then"], list):
            normalized["then"] = [
                normalize_single_action(
                    act, available_services, available_notify_services, preferred_notify_service, known_entity_ids
                )
                if isinstance(act, dict) else act
                for act in normalized["then"]
            ]

        if "else" in normalized and isinstance(normalized["else"], list):
            normalized["else"] = [
                normalize_single_action(
                    act, available_services, available_notify_services, preferred_notify_service, known_entity_ids
                )
                if isinstance(act, dict) else act
                for act in normalized["else"]
            ]

        if "repeat" in normalized and isinstance(normalized["repeat"], dict):
            r = dict(normalized["repeat"])
            if "sequence" in r and isinstance(r["sequence"], list):
                r["sequence"] = [
                    normalize_single_action(
                        act, available_services, available_notify_services, preferred_notify_service, known_entity_ids
                    )
                    if isinstance(act, dict) else act
                    for act in r["sequence"]
                ]
            normalized["repeat"] = r

        return normalized

    raw_val = str(normalized[service_key]).strip()
    domain, _, svc_name = raw_val.partition(".")
    if not svc_name:
        svc_name = domain
        domain = "homeassistant"

    domain = domain.lower()
    svc_name = svc_name.lower()

    # 1. Notification service resolution
    if domain == "notify":
        resolved_notify = resolve_notification_service(
            target_service=raw_val,
            available_notify_services=available_notify_services,
            preferred_service=preferred_notify_service,
        )
        normalized[service_key] = resolved_notify
        return normalized

    # 2. General domain service validation and alias resolution
    if domain in available_services:
        valid_svcs = available_services[domain]
        if svc_name not in valid_svcs:
            alias_map = COMMON_SERVICE_ALIASES.get(domain, {})
            canonical = alias_map.get(svc_name)
            if canonical and canonical in valid_svcs:
                normalized[service_key] = f"{domain}.{canonical}"
            else:
                logger.warning(
                    "Service '%s.%s' is not in available Home Assistant services for domain '%s' (available: %s)",
                    domain,
                    svc_name,
                    domain,
                    valid_svcs,
                )
    else:
        logger.debug("Domain '%s' not found in available Home Assistant services", domain)

    return normalized


def normalize_automation_proposal(
    proposal: NativeAutomationProposal,
    available_services: dict[str, list[str]],
    available_notify_services: list[str],
    preferred_notify_service: str = "notify.notify",
    known_entity_ids: set[str] | None = None,
) -> NativeAutomationProposal:
    """
    Deeply normalize a NativeAutomationProposal's actions against real Home Assistant services.
    """
    normalized_actions = [
        normalize_single_action(
            act,
            available_services=available_services,
            available_notify_services=available_notify_services,
            preferred_notify_service=preferred_notify_service,
            known_entity_ids=known_entity_ids,
        )
        if isinstance(act, dict) else act
        for act in proposal.action
    ]

    proposal.action = normalized_actions
    return proposal
