"""Production Home Assistant Adapter using WebSocket API (live event stream & registries) & REST API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import datetime, timedelta, timezone
import asyncio
import json
import logging
import os
from typing import Any

import httpx

from ha_ai_brain.domain.models import EntityState, EventOrigin, NativeAutomationProposal, StateChangedEvent
from ha_ai_brain.domain.timeutil import parse_iso
from ha_ai_brain.ports.smart_home import SmartHomePort

logger = logging.getLogger(__name__)

WS_CONNECT_TIMEOUT_SECONDS = 20.0
REGISTRY_REFRESH_MINUTES = 15
REGISTRY_RETRY_MINUTES = 5
# Only these event types are subscribed to (instead of every event on the bus) to keep traffic and CPU low.
SUBSCRIBED_EVENT_TYPES = (
    "state_changed",
    "automation_triggered",
    "mobile_app_notification_action",
    "ios.notification_action_fired",
)


class HomeAssistantAdapter(SmartHomePort):
    """
    Connects to a live Home Assistant instance (either locally inside an HA Add-on via
    `http://supervisor/core` + `SUPERVISOR_TOKEN`, or remotely via Long-Lived Access Token).

    Resolves Home Assistant Area Registry, Device Registry, and Entity Registry over WebSocket
    so every EntityState is enriched with its real `area_id`, and tracks `automation_triggered`
    events so native HA automation actions are properly attributed.
    """

    def __init__(self, base_url: str, ws_url: str, token: str, history_max_entities: int = 300) -> None:
        self.history_max_entities = history_max_entities
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
        self._available_services_cache: dict[str, list[str]] = {}
        self._services_last_fetched: datetime | None = None
        # context_id -> automation_entity_id from `automation_triggered` events
        self._automation_context_map: dict[str, str] = {}
        self._notification_action_handler: Callable[[str, str], Coroutine[Any, Any, None]] | None = None
        self._discovered_panel_path: str | None = None
        self._device_inventory: list[dict[str, Any]] = []
        self._client: httpx.AsyncClient | None = None
        self._action_tasks: set[asyncio.Task[Any]] = set()

    def _http(self) -> httpx.AsyncClient:
        """Shared connection-pooled HTTP client (per-request timeouts are passed at call sites)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(headers=self._headers(), timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        """Release pooled HTTP connections on shutdown."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

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
            and (now - self._registry_last_fetched) < timedelta(minutes=REGISTRY_REFRESH_MINUTES)
        ):
            return self._entity_area_map

        try:
            import websockets

            async with websockets.connect(
                self.ws_url, max_size=16 * 1024 * 1024, open_timeout=WS_CONNECT_TIMEOUT_SECONDS
            ) as ws:
                await ws.recv()  # auth_required
                await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                auth_res = json.loads(await ws.recv())
                if auth_res.get("type") != "auth_ok":
                    raise RuntimeError("HA WebSocket auth failed (check the access token)")

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

                # 4. Fetch Panels to discover Add-on's exact frontend URL path
                await ws.send(json.dumps({"id": 104, "type": "get_panels"}))
                panels_msg = json.loads(await ws.recv())
                panels_dict = panels_msg.get("result") or {}
                for k, v in panels_dict.items():
                    addon_ref = (v.get("config") or {}).get("addon", "")
                    title = v.get("title") or ""
                    url_path = v.get("url_path") or k
                    if addon_ref.endswith("ha_ai_brain") or k.endswith("ha_ai_brain") or title == "AI Brain":
                        self._discovered_panel_path = f"/{url_path}"
                        logger.info("Discovered HA Add-on Ingress panel path: %s", self._discovered_panel_path)
                        break

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

            self._device_inventory = self._build_inventory(devices_list, entities_list)
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
            # Retry soon, but not on every call: an unreachable socket would otherwise stall every state fetch.
            self._registry_last_fetched = now - timedelta(minutes=REGISTRY_REFRESH_MINUTES - REGISTRY_RETRY_MINUTES)

        return self._entity_area_map

    @staticmethod
    def _build_inventory(devices: list[dict[str, Any]], entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Group the device registry by (manufacturer, model); only physical-looking devices with identifiable models count."""
        by_device = {d.get("id"): d for d in devices if d.get("id") and d.get("entry_type") != "service" and not d.get("disabled_by")}
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for e in entities:
            dev = by_device.get(e.get("device_id"))
            if dev is None or e.get("disabled_by") or not e.get("entity_id"):
                continue
            manufacturer = str(dev.get("manufacturer") or "").strip()
            model = str(dev.get("model") or "").strip()
            if not manufacturer and not model:
                continue
            g = groups.setdefault(
                (manufacturer, model),
                {"manufacturer": manufacturer, "model": model, "integrations": set(), "domains": set(), "devices": set(), "entity_count": 0},
            )
            g["integrations"].add(str(e.get("platform") or ""))
            g["domains"].add(str(e["entity_id"]).split(".", 1)[0])
            g["devices"].add(dev["id"])
            g["entity_count"] += 1
        return sorted(
            (
                {
                    "manufacturer": g["manufacturer"], "model": g["model"],
                    "integrations": sorted(i for i in g["integrations"] if i),
                    "domains": sorted(g["domains"]), "device_count": len(g["devices"]), "entity_count": g["entity_count"],
                }
                for g in groups.values()
            ),
            key=lambda g: (-g["entity_count"], g["manufacturer"], g["model"]),
        )

    async def get_device_inventory(self) -> list[dict[str, Any]]:
        await self.refresh_area_registry_map()
        return list(self._device_inventory)

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

    @staticmethod
    def _timestamps(raw: dict[str, Any]) -> dict[str, Any]:
        """Real `last_changed` / `last_updated` from HA (needed to know how long a state has persisted)."""
        out: dict[str, Any] = {}
        changed = parse_iso(raw.get("last_changed"))
        updated = parse_iso(raw.get("last_updated"))
        if changed is not None:
            out["last_changed"] = changed
        if updated is not None:
            out["last_updated"] = updated
        return out

    async def get_all_states(self) -> dict[str, EntityState]:
        await self.refresh_area_registry_map()

        resp = await self._http().get(f"{self.base_url}/api/states", timeout=15.0)
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
                **self._timestamps(item),
            )
            states[st.entity_id] = st
        return states

    async def get_history(
        self,
        entity_ids: list[str],
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        # Drop domains without a useful time-series and obvious connectivity noise; cap only the total volume
        filtered_ids = [
            eid
            for eid in entity_ids
            if not eid.startswith(("automation.", "notify.", "sun.", "update.", "persistent_notification."))
            and not any(noise in eid for noise in ("_signal_level", "_bssid", "_ssid", "_app_version", "_version_"))
        ][: self.history_max_entities]
        if not filtered_ids:
            return {}

        ts = start_time.isoformat()
        history: dict[str, list[dict[str, Any]]] = {}
        chunk_size = 25
        client = self._http()
        gate = asyncio.Semaphore(3)

        async def fetch_chunk(chunk: list[str]) -> None:
            params: dict[str, str] = {
                "filter_entity_id": ",".join(chunk),
                "minimal_response": "true",
                "no_attributes": "true",
            }
            if end_time:
                params["end_time"] = end_time.isoformat()
            async with gate:
                try:
                    resp = await client.get(f"{self.base_url}/api/history/period/{ts}", params=params, timeout=30.0)
                except httpx.HTTPError as exc:
                    logger.warning("HA history query failed for chunk of %d entities: %s", len(chunk), exc)
                    return
            if resp.status_code != 200:
                logger.warning("HA history query returned %d for chunk of %d entities", resp.status_code, len(chunk))
                return
            for series in resp.json():
                if series and isinstance(series, list):
                    eid = series[0].get("entity_id")
                    if eid:
                        history[eid] = series

        await asyncio.gather(*(fetch_chunk(filtered_ids[i : i + chunk_size]) for i in range(0, len(filtered_ids), chunk_size)))
        return history

    async def call_service(
        self,
        domain: str,
        service: str,
        target_entity_ids: list[str],
        service_data: dict[str, Any],
        context_id: str | None = None,
    ) -> dict[str, Any]:
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

        resp = await self._http().post(
            f"{self.base_url}/api/services/{domain}/{service}",
            json=payload,
            timeout=15.0,
        )
        if resp.status_code >= 400:
            logger.error(
                "[HA SERVICE CALL ERROR %d] %s.%s targets=%s body=%s",
                resp.status_code, domain, service, target_entity_ids, resp.text[:500],
            )
        resp.raise_for_status()
        try:
            body: Any = resp.json()
        except ValueError:
            body = None
        return {"status": "ok", "domain": domain, "service": service, "response": body}

    async def upsert_automation(self, proposal: NativeAutomationProposal) -> dict[str, Any]:
        payload = {
            "id": proposal.automation_id,
            "alias": proposal.branded_alias,
            "description": proposal.description,
            "mode": proposal.mode,
            "trigger": proposal.trigger,
            "condition": proposal.condition,
            "action": proposal.action,
        }
        client = self._http()
        resp = await client.post(
            f"{self.base_url}/api/config/automation/config/{proposal.automation_id}",
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        # Immediately trigger automation.reload so Home Assistant updates its runtime entity registry
        try:
            reload_resp = await client.post(f"{self.base_url}/api/services/automation/reload", json={}, timeout=15.0)
            if reload_resp.status_code < 400:
                logger.info("Triggered automation.reload successfully after upserting %s", proposal.automation_id)
        except httpx.HTTPError as reload_err:
            logger.warning("Could not trigger automation.reload after upserting %s: %s", proposal.automation_id, reload_err)
        return {"status": "automation_created", "automation_id": proposal.automation_id, "alias": payload["alias"]}

    async def get_automation_configs(self) -> list[dict[str, Any]]:
        """Fetch the config of every UI-managed automation (YAML-defined ones are not exposed by HA's config API)."""
        try:
            resp = await self._http().get(f"{self.base_url}/api/states", timeout=15.0)
            resp.raise_for_status()
            ids = [
                str((item.get("attributes") or {}).get("id"))
                for item in resp.json()
                if str(item.get("entity_id", "")).startswith("automation.") and (item.get("attributes") or {}).get("id")
            ]
        except Exception as exc:
            logger.warning("Could not list automations: %s", exc)
            return []
        gate = asyncio.Semaphore(5)
        configs: list[dict[str, Any]] = []

        async def fetch(automation_id: str) -> None:
            async with gate:
                try:
                    r = await self._http().get(f"{self.base_url}/api/config/automation/config/{automation_id}", timeout=10.0)
                    if r.status_code == 200 and isinstance(r.json(), dict):
                        cfg = r.json()
                        cfg.setdefault("id", automation_id)
                        configs.append(cfg)
                except Exception as exc:
                    logger.debug("Automation config %s unavailable: %s", automation_id, exc)

        await asyncio.gather(*(fetch(i) for i in ids))
        return configs

    async def get_weather_forecast(self, entity_id: str, forecast_type: str = "hourly") -> list[dict[str, Any]]:
        try:
            resp = await self._http().post(
                f"{self.base_url}/api/services/weather/get_forecasts?return_response",
                json={"entity_id": entity_id, "type": forecast_type},
                timeout=15.0,
            )
            if resp.status_code != 200:
                return []
            data = (resp.json().get("service_response") or {}).get(entity_id) or {}
            keep = ("datetime", "condition", "temperature", "precipitation", "precipitation_probability", "wind_speed", "cloud_coverage")
            return [{k: f[k] for k in keep if k in f} for f in (data.get("forecast") or [])[:24] if isinstance(f, dict)]
        except Exception as exc:
            logger.debug("Weather forecast unavailable for %s: %s", entity_id, exc)
            return []

    async def get_timezone(self) -> str:
        try:
            resp = await self._http().get(f"{self.base_url}/api/config", timeout=10.0)
            if resp.status_code == 200:
                return str(resp.json().get("time_zone") or "")
        except Exception as exc:
            logger.debug("Could not read HA timezone: %s", exc)
        return ""

    async def get_system_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        resp = await self._http().get(f"{self.base_url}/api/error/all", timeout=15.0)
        resp.raise_for_status()
        lines = resp.text.splitlines()[-limit:]
        return [{"line": line} for line in lines]

    async def get_available_services(self) -> dict[str, list[str]]:
        """Fetch and return all registered Home Assistant services grouped by domain."""
        now = datetime.now(timezone.utc)
        if (
            self._available_services_cache
            and self._services_last_fetched
            and (now - self._services_last_fetched).total_seconds() < 300
        ):
            return self._available_services_cache

        try:
            resp = await self._http().get(f"{self.base_url}/api/services", timeout=10.0)
            if resp.status_code == 200:
                services_map: dict[str, list[str]] = {}
                for domain_entry in resp.json():
                    if isinstance(domain_entry, dict) and "domain" in domain_entry:
                        dom = str(domain_entry["domain"])
                        svc_dict = domain_entry.get("services") or {}
                        if isinstance(svc_dict, dict):
                            services_map[dom] = sorted(svc_dict.keys())
                if services_map:
                    self._available_services_cache = services_map
                    self._services_last_fetched = now
                    if "notify" in services_map:
                        self._available_notify_services = [
                            f"notify.{svc}"
                            for svc in services_map["notify"]
                            if svc != "send_message"
                        ]
                    return services_map
        except Exception as exc:
            logger.warning("Could not fetch HA services: %s", exc)
        return self._available_services_cache or {}

    async def get_available_notify_services(self) -> list[str]:
        if not self._available_notify_services:
            await self.get_available_services()
        return self._available_notify_services or ["notify.notify"]

    async def get_addon_panel_path(self) -> str:
        """
        Dynamically discover the Home Assistant frontend panel path for this add-on.
        Works across any user installation (custom repos, local add-ons, or official store).
        """
        if self._discovered_panel_path:
            return self._discovered_panel_path

        # 1. Try Supervisor API (available inside HA add-on container)
        supervisor_token = os.getenv("SUPERVISOR_TOKEN") or os.getenv("HASSIO_TOKEN")
        if supervisor_token:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(
                        "http://supervisor/addons/self/info",
                        headers={"Authorization": f"Bearer {supervisor_token}"},
                    )
                    if resp.status_code == 200:
                        slug = resp.json().get("data", {}).get("slug")
                        if slug:
                            self._discovered_panel_path = f"/{slug}"
                            return self._discovered_panel_path
            except Exception as exc:
                logger.debug("Supervisor self/info lookup: %s", exc)

        # 2. Refresh area registry map which queries get_panels over WebSocket
        try:
            await self.refresh_area_registry_map()
            if self._discovered_panel_path:
                return self._discovered_panel_path
        except Exception as exc:
            logger.debug("WebSocket get_panels lookup: %s", exc)

        return "/ha_ai_brain"

    @staticmethod
    def _decode_notification_action(data: dict[str, Any]) -> tuple[str, str] | None:
        """Map a Companion App button press (`BRAIN_<DECISION>:<approval_id>`) to (approval_id, decision)."""
        action_data = data.get("action_data")
        action_str = str(
            data.get("action")
            or data.get("actionName")
            or (action_data.get("action") if isinstance(action_data, dict) else "")
            or ""
        )
        decision_map = {
            "BRAIN_APPROVE_ONCE": "approved_once",
            "BRAIN_APPROVE_REPEATABLE": "approved_repeatable",
            "BRAIN_DISMISS": "dismissed",
            "BRAIN_REJECT": "rejected",
            "BRAIN_UNDO": "undo",
        }
        prefix, _, approval_id = action_str.partition(":")
        decision = decision_map.get(prefix.strip())
        if decision and approval_id.strip():
            return approval_id.strip(), decision
        return None

    def _track_automation_context(self, context_id: str | None, automation_entity_id: str) -> None:
        if not context_id:
            return
        self._automation_context_map[context_id] = automation_entity_id
        if len(self._automation_context_map) > 2000:
            del self._automation_context_map[next(iter(self._automation_context_map))]

    def _parse_state_changed(self, data: dict[str, Any], ctx: dict[str, Any]) -> StateChangedEvent | None:
        new_raw = data.get("new_state")
        if not new_raw:
            return None
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
        if auto_eid_matched:
            self._track_automation_context(ctx_id, auto_eid_matched)

        new_state = EntityState(
            entity_id=eid,
            state=str(new_raw.get("state", "unknown")),
            attributes=new_attrs,
            area_id=area_id,
            context_id=ctx_id,
            context_user_id=ctx.get("user_id"),
            **self._timestamps(new_raw),
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
        return StateChangedEvent(
            entity_id=new_state.entity_id,
            old_state=old_state,
            new_state=new_state,
            context_id=ctx_id,
            context_parent_id=parent_id,
            context_user_id=ctx.get("user_id"),
            origin=EventOrigin.HA_AUTOMATION if auto_eid_matched else EventOrigin.HUMAN_OR_PHYSICAL,
            triggered_by_automation_id=auto_eid_matched,
        )

    async def subscribe_state_changes(self) -> AsyncIterator[StateChangedEvent]:
        import websockets

        await self.refresh_area_registry_map()

        async with websockets.connect(
            self.ws_url, max_size=16 * 1024 * 1024, open_timeout=WS_CONNECT_TIMEOUT_SECONDS
        ) as ws:
            # 1. Receive auth_required, then authenticate
            await ws.recv()
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth_res = json.loads(await ws.recv())
            if auth_res.get("type") != "auth_ok":
                raise RuntimeError("HA WebSocket authentication failed (check the access token)")

            # 2. Subscribe only to the event types we consume; acknowledgements are validated by the reader loop
            for sub_id, event_type in enumerate(SUBSCRIBED_EVENT_TYPES, start=1):
                await ws.send(json.dumps({"id": sub_id, "type": "subscribe_events", "event_type": event_type}))

            event_queue: asyncio.Queue[StateChangedEvent | None | Exception] = asyncio.Queue(maxsize=1000)

            def _dispatch_notification_action(event_type: str, data: dict[str, Any]) -> bool:
                decoded = self._decode_notification_action(data)
                if decoded is None:
                    return False
                approval_id, decision = decoded
                logger.info(
                    "[MOBILE NOTIFICATION ACTION DISPATCHED] event=%s approval_id=%s decision=%s",
                    event_type, approval_id, decision,
                )
                if self._notification_action_handler:
                    task = asyncio.create_task(self._notification_action_handler(approval_id, decision))
                    # Keep a strong reference: un-referenced tasks can be garbage collected mid-flight.
                    self._action_tasks.add(task)
                    task.add_done_callback(self._action_tasks.discard)
                return True

            async def _ws_reader_loop() -> None:
                try:
                    async for raw_msg in ws:
                        try:
                            msg = json.loads(raw_msg)
                            msg_type = msg.get("type")
                            if msg_type == "result":
                                if not msg.get("success", True):
                                    raise RuntimeError(f"HA WebSocket subscribe_events failed: {msg.get('error')}")
                                continue
                            if msg_type != "event":
                                continue
                            event_obj = msg.get("event", {})
                            event_type = event_obj.get("event_type", "")
                            data = event_obj.get("data", {}) or {}
                            ctx = event_obj.get("context", {}) or {}

                            if event_type in ("mobile_app_notification_action", "ios.notification_action_fired"):
                                # Handled immediately, without waiting for LLM agents or the event queue
                                _dispatch_notification_action(event_type, data)
                                continue

                            if event_type == "automation_triggered":
                                self._track_automation_context(
                                    ctx.get("id"), str(data.get("entity_id", "automation.unknown"))
                                )
                                continue

                            if event_type != "state_changed":
                                continue

                            sc_event = self._parse_state_changed(data, ctx)
                        except RuntimeError:
                            raise
                        except Exception as frame_exc:
                            # One malformed frame must not tear down the whole stream
                            logger.warning("Ignoring malformed HA event frame: %s", frame_exc)
                            continue
                        if sc_event is None:
                            continue

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
