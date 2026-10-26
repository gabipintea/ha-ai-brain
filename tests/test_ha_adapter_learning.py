"""Home Assistant adapter additions (history, automation configs, forecast, timezone) and history backfill."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ha_ai_brain.adapters.ha_websocket_rest import HomeAssistantAdapter
from ha_ai_brain.adapters.telemetry_sqlite import SQLiteTelemetryStore
from ha_ai_brain.application.learning import LearningEngine, aggregate_hourly, history_to_records
from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.models import EntityState
from ha_ai_brain.ports.smart_home import SmartHomePort

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def adapter_with(handler: Any, **kwargs: Any) -> HomeAssistantAdapter:
    ad = HomeAssistantAdapter("http://ha.test:8123", "ws://ha.test:8123/api/websocket", "tok", **kwargs)
    ad._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=ad._headers(), timeout=5.0)
    return ad


class TestHomeAssistantAdapterAdditions(unittest.IsolatedAsyncioTestCase):
    async def test_history_is_not_capped_at_60_entities_and_is_chunked(self) -> None:
        seen_chunks: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            ids = request.url.params["filter_entity_id"].split(",")
            seen_chunks.append(len(ids))
            self.assertEqual(request.url.params["minimal_response"], "true")
            return httpx.Response(200, json=[[{"entity_id": e, "state": "on", "last_changed": NOW.isoformat()}] for e in ids])

        ad = adapter_with(handler, history_max_entities=300)
        ids = [f"light.l{i}" for i in range(130)] + ["automation.skipped", "sun.sun"]
        history = await ad.get_history(ids, NOW - timedelta(hours=24), NOW)
        self.assertEqual(len(history), 130)
        self.assertEqual(sum(seen_chunks), 130)
        self.assertGreater(len(seen_chunks), 2)

        capped = adapter_with(handler, history_max_entities=40)
        self.assertEqual(len(await capped.get_history(ids, NOW - timedelta(hours=24), NOW)), 40)

    async def test_automation_configs_skip_unavailable_definitions(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/states":
                return httpx.Response(
                    200,
                    json=[
                        {"entity_id": "automation.a", "state": "on", "attributes": {"id": "111"}},
                        {"entity_id": "automation.yaml_one", "state": "on", "attributes": {}},
                        {"entity_id": "automation.b", "state": "off", "attributes": {"id": "222"}},
                        {"entity_id": "light.x", "state": "on", "attributes": {}},
                    ],
                )
            if path.endswith("/111"):
                return httpx.Response(200, json={"alias": "A", "trigger": [], "action": []})
            return httpx.Response(404)

        configs = await adapter_with(handler).get_automation_configs()
        self.assertEqual([c["id"] for c in configs], ["111"])

    async def test_forecast_timezone_and_real_timestamps(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/services/weather/get_forecasts":
                return httpx.Response(
                    200,
                    json={"service_response": {"weather.home": {"forecast": [{"datetime": "2026-10-14T13:00:00Z", "temperature": 12.5, "secret": "x"}]}}},
                )
            if request.url.path == "/api/config":
                return httpx.Response(200, json={"time_zone": "Europe/Berlin"})
            if request.url.path == "/api/states":
                return httpx.Response(
                    200,
                    json=[{"entity_id": "lock.door", "state": "unlocked", "attributes": {}, "last_changed": "2026-10-14T01:00:00+00:00"}],
                )
            return httpx.Response(404)

        ad = adapter_with(handler)
        self.assertEqual(await ad.get_weather_forecast("weather.home"), [{"datetime": "2026-10-14T13:00:00Z", "temperature": 12.5}])
        self.assertEqual(await ad.get_timezone(), "Europe/Berlin")
        ad._registry_last_fetched = datetime.now(UTC)  # skip the websocket registry fetch
        states = await ad.get_all_states()
        self.assertEqual(states["lock.door"].last_changed, datetime(2026, 10, 14, 1, 0, tzinfo=UTC))

    def test_notification_button_decoding(self) -> None:
        decode = HomeAssistantAdapter._decode_notification_action
        self.assertEqual(decode({"action": "BRAIN_UNDO:abc123"}), ("abc123", "undo"))
        self.assertEqual(decode({"action": "BRAIN_APPROVE_REPEATABLE:1-2"}), ("1-2", "approved_repeatable"))
        self.assertIsNone(decode({"action": "SOMETHING_ELSE:1"}))
        self.assertIsNone(decode({"action": "BRAIN_REJECT:"}))


class _HistoryStub(SmartHomePort):
    """Minimal smart-home stub serving fixed history."""

    def __init__(self, history: dict[str, list[dict[str, Any]]]) -> None:
        self.history = history
        self.calls: list[list[str]] = []

    async def get_all_states(self) -> dict[str, EntityState]:
        return {}

    async def get_history(self, entity_ids: list[str], start_time: datetime, end_time: datetime | None = None) -> dict[str, list[dict[str, Any]]]:
        self.calls.append(list(entity_ids))
        return {e: s for e, s in self.history.items() if e in entity_ids}

    async def call_service(self, *a: Any, **k: Any) -> dict[str, Any]:
        return {}

    async def upsert_automation(self, *a: Any, **k: Any) -> dict[str, Any]:
        return {}

    async def get_system_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        return []

    def subscribe_state_changes(self) -> Any:  # pragma: no cover
        raise NotImplementedError


class TestBackfill(unittest.IsolatedAsyncioTestCase):
    def _history(self) -> dict[str, list[dict[str, Any]]]:
        def pt(state: str, hours_ago: float) -> dict[str, Any]:
            return {"state": state, "last_changed": (NOW - timedelta(hours=hours_ago)).isoformat()}

        return {
            "light.hall": [{"entity_id": "light.hall", **pt("off", 30)}, pt("on", 20), pt("unavailable", 19), pt("off", 18), pt("on", 5)],
            "sensor.temp": [{"entity_id": "sensor.temp", **pt("20.0", 5.5)}, pt("22.0", 5.2), pt("21.0", 3.0), pt("bad", 2.0)],
        }

    def test_conversion_skips_unavailable_and_non_numeric_points(self) -> None:
        transitions, samples = history_to_records(self._history(), NOW - timedelta(hours=40))
        self.assertEqual([(t.old_state, t.new_state) for t in transitions], [("off", "on"), ("off", "on")])
        self.assertEqual(len(samples), 3)
        rows = aggregate_hourly(samples)
        self.assertEqual(sum(n for _, _, n, _ in rows), 3)

    async def test_backfill_imports_once_and_marks_observation_start(self) -> None:
        hall = EntityState(entity_id="light.hall", state="on")
        temp = EntityState(entity_id="sensor.temp", state="21.0", device_class="temperature")
        states = {s.entity_id: s for s in (hall, temp)}
        stub = _HistoryStub(self._history())
        store = SQLiteTelemetryStore(":memory:")
        engine = LearningEngine(BrainSettings(store_backfill_hours=48, timezone="UTC"), stub, store)

        self.assertEqual(await engine.backfill(states, now=NOW), 2)
        self.assertEqual(await engine.backfill(states, now=NOW), 0)  # idempotent
        self.assertEqual(stub.calls[0], ["light.hall"])  # switchables and sensors are fetched separately
        self.assertEqual(stub.calls[1], ["sensor.temp"])
        window = await store.observation_window(NOW)
        assert window is not None
        self.assertEqual(window[0], NOW - timedelta(hours=48))
        hours = await store.get_numeric_hours("sensor.temp")
        self.assertEqual(sum(n for _, n, _ in hours), 3)
        store.close()


if __name__ == "__main__":
    unittest.main()
