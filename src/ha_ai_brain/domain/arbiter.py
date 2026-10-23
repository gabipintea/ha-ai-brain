"""Multi-Agent Conflict Arbiter and Entity Lease Manager."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ha_ai_brain.domain.models import ActionIntent, ActionPriority
from ha_ai_brain.domain.triage import EdgeSignalTriage


@dataclass
class EntityLease:
    """Active control lease on a Home Assistant entity."""

    entity_id: str
    holder_agent_id: str
    priority: ActionPriority
    cause_category: str
    expires_at: datetime


class ConflictArbiter:
    """
    Prevents 'Thermostat & Window Wars' between specialized agents and enforces
    human override priority and hardware short-cycle protection.
    """

    def __init__(self, triage: EdgeSignalTriage, default_lease_seconds: int = 300) -> None:
        self.triage = triage
        self.default_lease_seconds = default_lease_seconds
        self._leases: dict[str, EntityLease] = {}

    def evaluate_intent(self, intent: ActionIntent) -> tuple[bool, str]:
        """
        Determine if an ActionIntent is allowed to proceed by checking:
        1. Human Manual Override Lockout
        2. Existing higher-priority Agent Leases
        """
        now = datetime.now(timezone.utc)

        for entity_id in intent.target_entity_ids:
            # 1. Never fight a human who recently manually adjusted this entity
            if self.triage.is_entity_in_manual_override(entity_id):
                return (
                    False,
                    f"Blocked by Human Override Cooldown: '{entity_id}' was recently adjusted manually by a human.",
                )

            # 2. Check active multi-agent leases
            existing = self._leases.get(entity_id)
            if existing and existing.expires_at > now:
                if existing.holder_agent_id != intent.agent_id and existing.priority > intent.priority:
                    return (
                        False,
                        f"Conflict Arbiter: '{entity_id}' is currently leased by '{existing.holder_agent_id}' "
                        f"for '{existing.cause_category}' with higher priority ({existing.priority.name} > {intent.priority.name}).",
                    )

        # Grant/renew leases for all target entities
        lease_duration = self.default_lease_seconds
        if intent.domain == "climate":
            # Longer lease for HVAC/UFH due to thermal inertia & compressor short-cycle protection
            lease_duration = max(lease_duration, 600)

        expires_at = now + timedelta(seconds=lease_duration)
        for entity_id in intent.target_entity_ids:
            self._leases[entity_id] = EntityLease(
                entity_id=entity_id,
                holder_agent_id=intent.agent_id,
                priority=intent.priority,
                cause_category=intent.cause_category,
                expires_at=expires_at,
            )

        return True, "Approved by Conflict Arbiter (lease granted)."
