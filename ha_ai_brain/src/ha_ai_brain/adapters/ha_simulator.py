"""Digital Twin Smart Home Simulator Adapter for Testing, Demos, and Offline Evaluation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from ha_ai_brain.domain.models import EntityState, NativeAutomationProposal, StateChangedEvent
from ha_ai_brain.ports.smart_home import SmartHomePort


class SmartHomeSimulatorAdapter(SmartHomePort):
    """
    In-memory Digital Twin of a Home Assistant instance equipped with temperature, humidity,
    illuminance, UFH thermostats, HRV ventilation, dehumidifiers, and motorized windows/blinds.
    """

    def __init__(self) -> None:
        self._states: dict[str, EntityState] = self._build_initial_states()
        self._event_queue: asyncio.Queue[StateChangedEvent] = asyncio.Queue()
        self._service_call_log: list[dict[str, Any]] = []
        self._created_automations: dict[str, NativeAutomationProposal] = {}

    def _build_initial_states(self) -> dict[str, EntityState]:
        entities = [
            # Master Bedroom
            EntityState(
                entity_id="sensor.master_bedroom_temperature",
                state="21.0",
                area_id="master_bedroom",
                device_class="temperature",
                unit_of_measurement="°C",
                attributes={"friendly_name": "Master Bedroom Temperature", "window_glazing": "double_glazed"},
            ),
            EntityState(
                entity_id="sensor.master_bedroom_humidity",
                state="51.0",
                area_id="master_bedroom",
                device_class="humidity",
                unit_of_measurement="%",
                attributes={"friendly_name": "Master Bedroom Humidity"},
            ),
            EntityState(
                entity_id="climate.master_bedroom_ufh",
                state="heat",
                area_id="master_bedroom",
                attributes={"friendly_name": "Master Bedroom UFH Thermostat", "temperature": 21.0, "current_temperature": 21.0},
            ),
            EntityState(
                entity_id="humidifier.master_bedroom_dehumidifier",
                state="off",
                area_id="master_bedroom",
                attributes={"friendly_name": "Master Bedroom Dehumidifier", "target_humidity": 50},
            ),
            EntityState(
                entity_id="fan.hrv_ventilator",
                state="on",
                area_id="master_bedroom",
                attributes={"friendly_name": "Heat Recovery Ventilator (HRV)", "percentage": 30},
            ),
            EntityState(
                entity_id="cover.master_bedroom_window",
                state="closed",
                area_id="master_bedroom",
                device_class="window",
                attributes={"friendly_name": "Master Bedroom Motorized Window", "current_position": 0},
            ),
            # Living Room (South-Facing with UFH & Solar Illuminance)
            EntityState(
                entity_id="sensor.living_room_temperature",
                state="22.1",
                area_id="living_room",
                device_class="temperature",
                unit_of_measurement="°C",
                attributes={"friendly_name": "Living Room Temperature"},
            ),
            EntityState(
                entity_id="sensor.living_room_humidity",
                state="44.0",
                area_id="living_room",
                device_class="humidity",
                unit_of_measurement="%",
                attributes={"friendly_name": "Living Room Humidity"},
            ),
            EntityState(
                entity_id="sensor.outdoor_south_illuminance",
                state="2400",
                area_id="living_room",
                device_class="illuminance",
                unit_of_measurement="lx",
                attributes={"friendly_name": "Outdoor South Facade Solar Illuminance"},
            ),
            EntityState(
                entity_id="climate.living_room_ufh",
                state="heat",
                area_id="living_room",
                attributes={"friendly_name": "Living Room UFH Thermostat", "temperature": 22.5, "current_temperature": 22.1},
            ),
            EntityState(
                entity_id="cover.living_room_south_blinds",
                state="open",
                area_id="living_room",
                device_class="blind",
                attributes={"friendly_name": "Living Room South Motorized Blinds", "current_position": 100},
            ),
            # North Office (Poor winter insulation test zone)
            EntityState(
                entity_id="sensor.north_office_temperature",
                state="18.4",
                area_id="north_office",
                device_class="temperature",
                unit_of_measurement="°C",
                attributes={"friendly_name": "North Office Temperature"},
            ),
            EntityState(
                entity_id="climate.north_office_ufh",
                state="heat",
                area_id="north_office",
                attributes={"friendly_name": "North Office UFH Thermostat", "temperature": 21.0, "current_temperature": 18.4},
            ),
            # Outdoor & Weather
            EntityState(
                entity_id="sensor.outdoor_temperature",
                state="1.5",
                area_id="outdoor",
                device_class="temperature",
                unit_of_measurement="°C",
                attributes={"friendly_name": "Outdoor Ambient Temperature"},
            ),
            EntityState(
                entity_id="sensor.outdoor_humidity",
                state="82.0",
                area_id="outdoor",
                device_class="humidity",
                unit_of_measurement="%",
                attributes={"friendly_name": "Outdoor Ambient Humidity"},
            ),
            EntityState(
                entity_id="weather.home",
                state="cold_clear",
                area_id="outdoor",
                attributes={"temperature": 1.5, "humidity": 82.0, "wind_speed": 14.0},
            ),
        ]
        return {e.entity_id: e for e in entities}

    async def get_all_states(self) -> dict[str, EntityState]:
        return dict(self._states)

    async def get_history(
        self,
        entity_ids: list[str],
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Generate realistic multi-hour historical trajectories for computation sub-agent analysis."""
        now = end_time or datetime.now(timezone.utc)
        history: dict[str, list[dict[str, Any]]] = {}

        for eid in entity_ids:
            if eid == "sensor.north_office_temperature":
                # Rapid winter heat loss when UFH cycles off (-1.5°C per hour decay slope)
                points = [21.2, 20.5, 19.7, 19.0, 18.4]
            elif eid == "sensor.master_bedroom_humidity":
                points = [50.0, 54.0, 59.5, 64.0, float(self._states[eid].state)]
            elif eid == "sensor.outdoor_temperature":
                points = [4.5, 3.8, 2.9, 2.1, float(self._states[eid].state)]
            elif eid == "climate.living_room_ufh":
                # Shows recurring human habit of boosting setpoint at 07:00 every morning
                points = [20.0, 20.0, 22.5, 22.5, 22.5]
            elif eid in self._states and self._states[eid].numeric_value is not None:
                val = float(self._states[eid].numeric_value or 0.0)
                points = [val - 0.6, val - 0.4, val - 0.2, val - 0.1, val]
            else:
                continue

            series = []
            for idx, val in enumerate(points):
                ts = (now - timedelta(hours=len(points) - 1 - idx)).isoformat()
                series.append({"entity_id": eid, "state": str(val), "last_changed": ts})
            history[eid] = series

        return history

    async def call_service(
        self,
        domain: str,
        service: str,
        target_entity_ids: list[str],
        service_data: dict[str, Any],
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """Simulate executing a Home Assistant service call and update digital twin states."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "domain": domain,
            "service": service,
            "target_entity_ids": target_entity_ids,
            "service_data": service_data,
            "context_id": context_id,
        }
        self._service_call_log.append(record)

        for eid in target_entity_ids:
            if eid not in self._states:
                continue
            current = self._states[eid]
            new_attrs = dict(current.attributes)
            new_state_val = current.state

            if domain == "fan" and service == "set_percentage":
                pct = service_data.get("percentage", 75)
                new_state_val = "on" if pct > 0 else "off"
                new_attrs["percentage"] = pct
            elif domain == "humidifier" and service in ("turn_on", "set_humidity"):
                new_state_val = "on"
                if "humidity" in service_data:
                    new_attrs["target_humidity"] = service_data["humidity"]
            elif domain == "climate" and service == "set_temperature":
                temp = service_data.get("temperature")
                if temp is not None:
                    new_attrs["temperature"] = temp
            elif domain == "cover":
                if service == "set_cover_position":
                    pos = service_data.get("position", 10)
                    new_attrs["current_position"] = pos
                    new_state_val = "open" if pos > 0 else "closed"
                elif service == "open_cover":
                    new_attrs["current_position"] = 100
                    new_state_val = "open"
                elif service == "close_cover":
                    new_attrs["current_position"] = 0
                    new_state_val = "closed"

            updated = current.model_copy(
                update={
                    "state": str(new_state_val),
                    "attributes": new_attrs,
                    "context_id": context_id,
                    "last_changed": datetime.now(timezone.utc),
                }
            )
            self._states[eid] = updated

        return {"status": "simulated_ok", "executed": record}

    async def upsert_automation(self, proposal: NativeAutomationProposal) -> dict[str, Any]:
        self._created_automations[proposal.automation_id] = proposal
        return {
            "status": "automation_upserted",
            "automation_id": proposal.automation_id,
            "alias": f"[AI Brain] {proposal.alias}",
        }

    async def get_system_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "WARNING",
                "source": "components/esphome",
                "message": "Device 'bedroom_air_monitor' (192.168.1.142) connection timed out; DHCP lease may have changed.",
            }
        ][:limit]

    async def get_available_notify_services(self) -> list[str]:
        return [
            "notify.notify",
            "notify.mobile_app_phone",
            "notify.persistent_notification",
        ]

    async def subscribe_state_changes(self) -> AsyncIterator[StateChangedEvent]:
        while True:
            event = await self._event_queue.get()
            yield event

    def emit_simulated_state_change(
        self,
        entity_id: str,
        new_value: str,
        attributes_patch: dict[str, Any] | None = None,
        context_user_id: str | None = None,
    ) -> StateChangedEvent:
        """Update an entity in the simulator and return a StateChangedEvent."""
        old_state = self._states.get(entity_id)
        if old_state is None:
            raise KeyError(f"Unknown simulator entity: {entity_id}")

        merged_attrs = dict(old_state.attributes)
        if attributes_patch:
            merged_attrs.update(attributes_patch)

        new_state = old_state.model_copy(
            update={
                "state": str(new_value),
                "attributes": merged_attrs,
                "context_user_id": context_user_id,
                "last_changed": datetime.now(timezone.utc),
            }
        )
        self._states[entity_id] = new_state
        event = StateChangedEvent(
            entity_id=entity_id,
            old_state=old_state,
            new_state=new_state,
            context_user_id=context_user_id,
        )
        self._event_queue.put_nowait(event)
        return event

    @property
    def service_call_log(self) -> list[dict[str, Any]]:
        return list(self._service_call_log)

    @property
    def created_automations(self) -> dict[str, NativeAutomationProposal]:
        return dict(self._created_automations)
