"""Port Interface for interacting with Home Assistant (or a Digital Twin Simulator)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from ha_ai_brain.domain.models import EntityState, NativeAutomationProposal, StateChangedEvent


class SmartHomePort(ABC):
    """Outbound and Inbound port abstracting Home Assistant WebSocket & REST APIs."""

    @abstractmethod
    async def get_all_states(self) -> dict[str, EntityState]:
        """Fetch current states of all entities in the smart home."""

    @abstractmethod
    async def get_history(
        self,
        entity_ids: list[str],
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch historical state time-series for specified entities."""

    @abstractmethod
    async def call_service(
        self,
        domain: str,
        service: str,
        target_entity_ids: list[str],
        service_data: dict[str, Any],
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a Home Assistant service call on target entities."""

    @abstractmethod
    async def upsert_automation(self, proposal: NativeAutomationProposal) -> dict[str, Any]:
        """Create or update a native Home Assistant automation via the HA Config API."""

    @abstractmethod
    async def get_system_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read Home Assistant error/warning logs (used by the Repair & Diagnostics Agent)."""

    @abstractmethod
    def subscribe_state_changes(self) -> AsyncIterator[StateChangedEvent]:
        """Yield live state_changed events streamed from Home Assistant."""

    async def get_available_notify_services(self) -> list[str]:
        """Return all available `notify.*` service targets discovered in Home Assistant."""
        return ["notify.notify"]
