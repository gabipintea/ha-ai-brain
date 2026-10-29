"""Port Interface for interacting with Home Assistant (or a Digital Twin Simulator)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from ha_ai_brain.domain.models import EntityState, NativeAutomationProposal, StateChangedEvent
from ha_ai_brain.domain.twins import EntityFacts


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

    async def delete_automation(self, automation_id: str) -> bool:
        """Remove an automation from Home Assistant by its config id. Returns False when unsupported or not found."""
        return False

    @abstractmethod
    async def get_system_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Read Home Assistant error/warning logs (used by the Repair & Diagnostics Agent)."""

    @abstractmethod
    def subscribe_state_changes(self) -> AsyncIterator[StateChangedEvent]:
        """Yield live state_changed events streamed from Home Assistant."""

    async def get_available_services(self) -> dict[str, list[str]]:
        """Return all available registered services in Home Assistant grouped by domain (e.g. {'switch': ['turn_on', 'turn_off', 'toggle'], ...})."""
        return {}

    async def get_available_notify_services(self) -> list[str]:
        """Return all available `notify.*` service targets discovered in Home Assistant."""
        return ["notify.notify"]

    async def get_addon_panel_path(self) -> str:
        """Dynamically discover the Home Assistant frontend panel path for this add-on."""
        return "/ha_ai_brain"

    supports_history_backfill: bool = True

    async def get_automation_configs(self) -> list[dict[str, Any]]:
        """Configuration (triggers / conditions / actions) of the automations defined in Home Assistant, each with its `id`."""
        return []

    async def get_weather_forecast(self, entity_id: str, forecast_type: str = "hourly") -> list[dict[str, Any]]:
        """Short-term forecast entries for a weather entity (empty when unsupported)."""
        return []

    async def get_timezone(self) -> str:
        """IANA timezone configured in Home Assistant (empty when unknown)."""
        return ""

    async def get_entity_device_facts(self) -> list[EntityFacts]:
        """Registry facts per entity (device, manufacturer, model, serial, area) used to recognise one device exposed twice."""
        return []

    async def get_device_inventory(self) -> list[dict[str, Any]]:
        """Distinct physical device models in the home: [{manufacturer, model, integrations, domains, entity_count}]."""
        return []
