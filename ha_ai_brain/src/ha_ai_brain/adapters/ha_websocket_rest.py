"""Production Home Assistant Adapter using WebSocket API (live event stream & registries) & REST API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import datetime, timedelta, timezone
import asyncio
import json
import logging
from typing import Any

from ha_ai_brain.domain.models import EntityState, EventOrigin, NativeAutomationProposal, StateChangedEvent
from ha_ai_brain.ports.smart_home import SmartHomePort

logger = logging.getLogger(__name__)


class HomeAssistantAdapter(SmartHomePort):
    """
    Connects to a live Home Assistant instance (either locally inside an HA Add-on via
    `http://supervisor/core` + `SUPERVISOR_TOKEN`, or remotely via Long-Lived Access Token).

    Resolves Home Assistant Area Registry, Device Registry, and Entity Registry over WebSocket
    so every EntityState is enriched with its real `area_id`, and tracks `automation_triggered`
    events so native HA automation actions are properly attributed.
    """

    def __init__(self, base_url: str, ws_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        if ws_url:
            self.ws_url = ws_url
        else:
            ws_scheme = "wss://" if self.base_url.startswith("https://") else "ws://"
            host_part = self.base_url.split("://", 1)[-1]
            self.ws_url = f"{ws_scheme}{host_part}/api/websocket"
        self.token = token

        # Cached entity_id -> area_id map resolved from HA registries
        self._entity_area_map: dict[str, str] = {}
        self._area_names: dict[str, str] = {}
        self._registry_last_fetched: datetime | None = None
        self._available_notify_services: list[str] = []
        # context_id -> automation_entity_id from `automation_triggered` events
        self._automation_context_map: dict[str, str] = {}
        self._notification_action_handler: Callable[[str, str], Coroutine[Any, Any, None]] | None = None

    def set_notification_action_handler(
        self,
        handler: Callable[[str, str], Coroutine[Any, Any, None]],
    ) -> None:
        """Register callback for `mobile_app_notification_action` events from HA Companion App."""
        self._notification_action_handler = handler

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def refresh_area_registry_map(self, force: bool = False) -> dict[str, str]:
        """
        Query Home Assistant's Area, Device, and Entity registries over WebSocket
        to build an accurate `entity_id -> area_id` mapping.
        """
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._registry_last_fetched is not None
            and (now - self._registry_last_fetched) < timedelta(minutes=15)
            and self._entity_area_map
        ):
            return self._entity_area_map

        try:
            import websockets

            async with websockets.connect(self.ws_url, max_size=16 * 1024 * 1024) as ws:
                await ws.recv()  # auth_required
                await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                auth_res = json.loads(await ws.recv())
                if auth_res.get("type") != "auth_ok":
                    raise RuntimeError(f"HA WebSocket auth failed: {auth_res}")

                # 1. Fetch Area Registry
                await ws.send(json.dumps({"id": 101, "type": "config/area_registry/list"}))
                areas_msg = json.loads(await ws.recv())
                areas_list = areas_msg.get("result") or []

                # 2. Fetch Device Registry
                await ws.send(json.dumps({"id": 102, "type": "config/device_registry/list"}))
                devices_msg = json.loads(await ws.recv())
                devices_list = devices_msg.get("result") or []

                # 3. Fetch Entity Registry
                await ws.send(json.dumps({"id": 103, "type": "config/entity_registry/list"}))
                entities_msg = json.loads(await ws.recv())
                entities_list = entities_msg.get("result") or []

            area_names: dict[str, str] = {}
            for a in areas_list:
                aid = a.get("area_id")
                if aid:
                    area_names[aid] = a.get("name", aid)

            device_area_map: dict[str, str] = {}
            for d in devices_list:
                did = d.get("id")
                aid = d.get("area_id")
                if did and aid:
                    device_area_map[did] = aid

            entity_area_map: dict[str, str] = {}
            for e in entities_list:
                eid = e.get("entity_id")
                if not eid:
                    continue
                aid = e.get("area_id") or device_area_map.get(e.get("device_id") or "")
                if aid:
                    entity_area_map[eid] = aid

            self._area_names = area_names
            self._entity_area_map = entity_area_map
            self._registry_last_fetched = now
            logger.info(
                "Resolved HA Registries: %d areas, %d devices, %d entities mapped to areas",
                len(area_names),
                len(device_area_map),
                len(entity_area_map),
            )
        except Exception as exc:
            logger.warning("Could not fetch HA WebSocket registries (falling back to entity_id inference): %s", exc)

        return self._entity_area_map

    def _resolve_area_id(self, entity_id: str, attributes: dict[str, Any]) -> str | None:
        """Resolve an entity's area_id from registry cache, attributes, or entity naming convention."""
        if "area_id" in attributes and attributes["area_id"]:
            return str(attributes["area_id"])
        if entity_id in self._entity_area_map:
            return self._entity_area_map[entity_id]

        # Fallback heuristic if user hasn't assigned HA areas to all entities yet:
        # e.g., `sensor.master_bedroom_temperature` -> `master_bedroom`
        object_id = entity_id.split(".", 1)[-1]
        if any(k in object_id for k in ("outdoor", "outside", "exterior", "weather")):
            return "outdoor"
        for suffix in (
            "_temperature",
            "_temp",
            "_humidity",
            "_hum",
            "_illuminance",
            "_lux",
            "_ufh",
            "_thermostat",
            "_radiator",
            "_heater",
            "_ac",
            "_dehumidifier",
            "_humidifier",
            "_window",
            "_blinds",
            "_blind",
            "_shutter",
            "_curtain",
            "_ventilator",
            "_fan",
            "_light",
            "_motion",
            "_occupancy",
            "_presence",
            "_door",
            "_contact",
            "_lock",
            "_power",
            "_energy",
            "_plug",
            "_switch",
        ):
            if object_id.endswith(suffix) and len(object_id) > len(suffix):
                return object_id[: -len(suffix)]
        return None

    async def get_all_states(self) -> dict[str, EntityState]:
        import httpx

        await self.refresh_area_registry_map()

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{self.base_url}/api/states", headers=self._headers())
            resp.raise_for_status()
            raw_list = resp.json()

        states: dict[str, EntityState] = {}
        for item in raw_list:
            ctx = item.get("context", {}) or {}
            attrs = item.get("attributes", {}) or {}
            eid = item["entity_id"]
            area_id = self._resolve_area_id(eid, attrs)
            st = EntityState(
                entity_id=eid,
                state=str(item.get("state", "unknown")),
                attributes=attrs,
                area_id=area_id,
                context_id=ctx.get("id"),
                context_user_id=ctx.get("user_id"),
            )
            states[st.entity_id] = st
        return states

    async def get_history(
        self,
        entity_ids: list[str],
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        # Filter out domains that don't carry state time-series and cap to avoid huge query strings
        filtered_ids = [
            eid
            for eid in entity_ids
            if not eid.startswith(("automation.", "notify.", "sun."))
            and not any(noise in eid for noise in ("_signal_level", "_bssid", "_ssid", "_app_version", "_version_"))
        ][:60]
        if not filtered_ids:
            return {}
        import httpx

        ts = start_time.isoformat()
        history: dict[str, list[dict[str, Any]]] = {}
        chunk_size = 25

        async with httpx.AsyncClient(timeout=20.0) as client:
            for i in range(0, len(filtered_ids), chunk_size):
                chunk = filtered_ids[i : i + chunk_size]
                params: dict[str, str] = {
                    "filter_entity_id": ",".join(chunk),
                    "minimal_response": "true",
                }
                if end_time:
                    params["end_time"] = end_time.isoformat()

                resp = await client.get(
                    f"{self.base_url}/api/history/period/{ts}",
                    headers=self._headers(),
                    params=params,
                )
                if resp.status_code != 200:
                    logger.warning("HA history query returned %d for chunk of %d entities", resp.status_code, len(chunk))
                    continue
                data = resp.json()
                for series in data:
                    if series and isinstance(series, list):
                        eid = series[0].get("entity_id")
                        if eid:
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
        import httpx

        payload = dict(service_data)
        if target_entity_ids and domain != "notify":
            payload["entity_id"] = target_entity_ids

        # Normalize common LLM parameter quirks to prevent HA 400 Bad Request rejections
        if domain == "cover":
            if service in ("close_cover", "open_cover", "stop_cover"):
                pos = payload.pop("position", None)
                if pos is not None:
                    try:
                        pos_int = int(pos)
                        if 0 < pos_int < 100:
                            service = "set_cover_position"
                            payload["position"] = pos_int
                    except (ValueError, TypeError):
                        pass

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code >= 400:
                logger.error(
                    "[HA SERVICE CALL ERROR %d] %s.%s targets=%s body=%s sent_payload=%s",
                    resp.status_code, domain, service, target_entity_ids, resp.text, payload,
                )
            resp.raise_for_status()
            return {"status": "ok", "domain": domain, "service": service, "response": resp.json()}

    async def upsert_automation(self, proposal: NativeAutomationProposal) -> dict[str, Any]:
        import httpx

        payload = {
            "id": proposal.automation_id,
            "alias": f"[AI Brain] {proposal.alias}",
            "description": proposal.description,
            "mode": proposal.mode,
            "trigger": proposal.trigger,
            "condition": proposal.condition,
            "action": proposal.action,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/config/automation/config/{proposal.automation_id}",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return {"status": "automation_created", "automation_id": proposal.automation_id, "alias": payload["alias"]}

    async def get_system_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{self.base_url}/api/error/all", headers=self._headers())
            resp.raise_for_status()
            lines = resp.text.splitlines()[-limit:]
            return [{"line": line} for line in lines]

    async def get_available_notify_services(self) -> list[str]:
        if self._available_notify_services:
            return self._available_notify_services
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/api/services", headers=self._headers())
                if resp.status_code == 200:
                    data = resp.json()
                    for domain_entry in data:
                        if isinstance(domain_entry, dict) and domain_entry.get("domain") == "notify":
                            services_dict = domain_entry.get("services") or {}
                            found = [
                                f"notify.{svc}"
                                for svc in sorted(services_dict.keys())
                                if svc != "send_message"
                            ]
                            if found:
                                self._available_notify_services = found
                                return found
        except Exception as exc:
            logger.warning("Could not fetch HA notify services: %s", exc)
        return ["notify.notify"]

    async def subscribe_state_changes(self) -> AsyncIterator[StateChangedEvent]:
        import websockets

        await self.refresh_area_registry_map()

        async with websockets.connect(self.ws_url, max_size=16 * 1024 * 1024) as ws:
            # 1. Receive auth_required
            await ws.recv()
            # 2. Authenticate
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth_res = json.loads(await ws.recv())
            if auth_res.get("type") != "auth_ok":
                raise RuntimeError(f"HA WebSocket authentication failed: {auth_res}")

            # 3. Subscribe to all events in a single call so we never miss actions or drop frames
            await ws.send(json.dumps({"id": 1, "type": "subscribe_events"}))
            sub_res = json.loads(await ws.recv())
            if not sub_res.get("success"):
                raise RuntimeError(f"HA WebSocket subscribe_events failed: {sub_res}")

            event_queue: asyncio.Queue[StateChangedEvent | None | Exception] = asyncio.Queue(maxsize=1000)

            async def _ws_reader_loop() -> None:
                try:
                    async for raw_msg in ws:
                        msg = json.loads(raw_msg)
                        if msg.get("type") != "event":
                            continue
                        event_obj = msg.get("event", {})
                        event_type = event_obj.get("event_type", "")
                        data = event_obj.get("data", {})
                        ctx = event_obj.get("context", {}) or {}

                        # 1. Process Mobile Notification actions IMMEDIATELY without waiting for LLMs or queues
                        if (
                            event_type in ("mobile_app_notification_action", "ios.notification_action_fired")
                            or "notification" in event_type
                        ):
                            logger.info("[MOBILE NOTIFICATION EVENT RECEIVED] event=%s data=%s", event_type, data)
                            action_str = str(
                                data.get("action")
                                or data.get("actionName")
                                or (data.get("action_data", {}) if isinstance(data.get("action_data"), dict) else {}).get("action")
                                or ""
                            )
                            decision_map = {
                                "BRAIN_APPROVE_ONCE": "approved_once",
                                "BRAIN_APPROVE_REPEATABLE": "approved_repeatable",
                                "BRAIN_DISMISS": "dismissed",
                                "BRAIN_REJECT": "rejected",
                            }
                            matched = False
                            for prefix, decision in decision_map.items():
                                if prefix in action_str:
                                    approval_id = action_str.split(prefix + ":", 1)[-1].strip()
                                    matched = True
                                    logger.info(
                                        "[MOBILE NOTIFICATION ACTION DISPATCHED] approval_id=%s decision=%s (from action_str=%s)",
                                        approval_id, decision, action_str,
                                    )
                                    if self._notification_action_handler:
                                        asyncio.create_task(self._notification_action_handler(approval_id, decision))
                                    break
                            if matched:
                                continue

                        # 2. Track native HA automation trigger contexts for causal attribution
                        if event_type == "automation_triggered":
                            trig_ctx_id = ctx.get("id")
                            auto_eid = str(data.get("entity_id", "automation.unknown"))
                            if trig_ctx_id:
                                self._automation_context_map[trig_ctx_id] = auto_eid
                                if len(self._automation_context_map) > 2000:
                                    oldest = next(iter(self._automation_context_map))
                                    del self._automation_context_map[oldest]
                            continue

                        # 3. Only state_changed events are buffered for downstream agent processing
                        if event_type != "state_changed":
                            continue

                        new_raw = data.get("new_state")
                        if not new_raw:
                            continue
                        old_raw = data.get("old_state")

                        eid = new_raw["entity_id"]
                        new_attrs = new_raw.get("attributes", {}) or {}
                        area_id = self._resolve_area_id(eid, new_attrs)

                        ctx_id = ctx.get("id")
                        parent_id = ctx.get("parent_id")
                        auto_eid_matched = (
                            (self._automation_context_map.get(ctx_id) if ctx_id else None)
                            or (self._automation_context_map.get(parent_id) if parent_id else None)
                        )
                        if auto_eid_matched and ctx_id:
                            self._automation_context_map[ctx_id] = auto_eid_matched

                        new_state = EntityState(
                            entity_id=eid,
                            state=str(new_raw.get("state", "unknown")),
                            attributes=new_attrs,
                            area_id=area_id,
                            context_id=ctx_id,
                            context_user_id=ctx.get("user_id"),
                        )
                        old_state = (
                            EntityState(
                                entity_id=old_raw["entity_id"],
                                state=str(old_raw.get("state", "unknown")),
                                attributes=old_raw.get("attributes", {}) or {},
                                area_id=area_id,
                            )
                            if old_raw
                            else None
                        )
                        sc_event = StateChangedEvent(
                            entity_id=new_state.entity_id,
                            old_state=old_state,
                            new_state=new_state,
                            context_id=ctx_id,
                            context_parent_id=parent_id,
                            context_user_id=ctx.get("user_id"),
                            origin=EventOrigin.HA_AUTOMATION if auto_eid_matched else EventOrigin.HUMAN_OR_PHYSICAL,
                            triggered_by_automation_id=auto_eid_matched,
                        )

                        if event_queue.full():
                            try:
                                event_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        await event_queue.put(sc_event)
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    await event_queue.put(exc)
                finally:
                    await event_queue.put(None)

            reader_task = asyncio.create_task(_ws_reader_loop())
            try:
                while True:
                    item = await event_queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item
                    yield item
            finally:
                reader_task.cancel()
                try:
                    await reader_task
                except (asyncio.CancelledError, Exception):
                    pass
