"""Does an agent have anything to look at or act on in this home? (Skips pointless AI calls for absent device types.)"""

from __future__ import annotations

from ha_ai_brain.domain.models import AgentSpec, EntityState

# Domains every agent may use without owning any hardware (alerts, automations, generic HA services).
GENERIC_DOMAINS = frozenset({"notify", "automation", "homeassistant", "script", "scene", "persistent_notification"})
PASSIVE_DOMAINS = frozenset({"weather", "sun", "automation"})
UNAVAILABLE = ("unavailable", "unknown")
MIN_MONITORED_FOR_ADVISORY_AGENTS = 3


def actuator_domains(agent: AgentSpec) -> set[str]:
    """Device types the agent can actually operate (everything it controls except notifications / automations)."""
    return set(agent.controllable_domains) - GENERIC_DOMAINS


def agent_has_scope(agent: AgentSpec, states: dict[str, EntityState]) -> tuple[bool, str]:
    """
    Whether a batch analysis for `agent` can produce anything useful:
    * `batch_trigger == "always"`: yes;
    * `"unavailable_only"` (diagnostic agents): only when some entity is unavailable;
    * otherwise: the home must contain at least one device type the agent operates, or - for purely advisory agents that
      operate no hardware - at least a few entities in its monitored domains.
    """
    if agent.batch_trigger == "always":
        return True, ""
    if agent.batch_trigger == "unavailable_only":
        ok = any(st.state in UNAVAILABLE and st.domain not in GENERIC_DOMAINS for st in states.values())
        return ok, "" if ok else "no unavailable entities to diagnose"
    operated = actuator_domains(agent)
    if operated:
        ok = any(st.domain in operated for st in states.values())
        return ok, "" if ok else f"no {'/'.join(sorted(operated))} devices in this home"
    monitored = set(agent.monitored_domains) - PASSIVE_DOMAINS
    count = sum(1 for st in states.values() if st.domain in monitored)
    return count >= MIN_MONITORED_FOR_ADVISORY_AGENTS, "" if count >= MIN_MONITORED_FOR_ADVISORY_AGENTS else "too few relevant entities"


def agent_can_act(agent: AgentSpec, context: dict[str, EntityState]) -> bool:
    """Real-time: an agent is only worth waking when its context contains something it can operate (diagnostics excepted)."""
    operated = actuator_domains(agent)
    if operated:
        return any(st.domain in operated for st in context.values())
    return agent.batch_trigger in ("unavailable_only", "always")
