"""Generic anomaly detection, learning from dismissals, and natural-language watches."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from ha_ai_brain.adapters.memory_sqlite import SQLiteMemoryAdapter
from ha_ai_brain.api.app import build_orchestrator, create_app
from ha_ai_brain.application.watch_service import WatchService
from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.anomaly import (
    build_discrete_profiles,
    find_dwell_anomalies,
    find_flapping,
    find_numeric_anomalies,
    find_silent_entities,
    find_stuck_unavailable,
    prioritise,
)
from ha_ai_brain.domain.baselines import NumericBaseline
from ha_ai_brain.domain.expectations import ExceptionFinding, classify_severity
from ha_ai_brain.domain.models import EntityState, Transition
from ha_ai_brain.domain.watches import (
    WatchCondition,
    WatchRule,
    WatchTracker,
    backtest_watch,
    build_entity_catalog,
    evaluate_watch,
    validate_watch,
)
from ha_ai_brain.ports.llm import LLMProviderPort

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # a Wednesday


def state(eid: str, value: str, changed_ago: timedelta = timedelta(0), **kw: Any) -> EntityState:
    return EntityState(entity_id=eid, state=value, last_changed=NOW - changed_ago, last_updated=kw.pop("updated", NOW - changed_ago), **kw)


def on_off_history(eid: str, cycles: int = 20, on_minutes: int = 40) -> list[Transition]:
    out: list[Transition] = []
    for i in range(cycles):
        start = NOW - timedelta(days=cycles - i, hours=2)
        out.append(Transition(eid, start, "off", "on", "human_or_physical"))
        out.append(Transition(eid, start + timedelta(minutes=on_minutes + (i % 5) * 3), "on", "off", "human_or_physical"))
    return out


class TestGenericDetectors(unittest.TestCase):
    def test_dwell_anomaly_works_for_any_entity_type(self) -> None:
        for eid in ("light.a", "fan.b", "vacuum.c", "input_boolean.d"):
            profiles = build_discrete_profiles(on_off_history(eid), NOW - timedelta(days=21), NOW)
            self.assertEqual(profiles[eid].rest_state, "off")
            long_on = {eid: state(eid, "on", timedelta(hours=5))}
            found = find_dwell_anomalies(long_on, profiles, NOW, UTC)
            self.assertEqual([f.kind for f in found], ["dwell_anomaly"], eid)
            normal = {eid: state(eid, "on", timedelta(minutes=45))}
            self.assertEqual(find_dwell_anomalies(normal, profiles, NOW, UTC), [])
            resting = {eid: state(eid, "off", timedelta(days=3))}
            self.assertEqual(find_dwell_anomalies(resting, profiles, NOW, UTC), [])

    def test_silent_entity_and_flapping(self) -> None:
        trans = []
        for d in range(1, 9):
            for h in (7, 10, 13, 16, 19, 22):
                trans.append(Transition("binary_sensor.s", NOW - timedelta(days=d) .__add__(timedelta(hours=h - 12)), "off", "on", "sensor_telemetry"))
                trans.append(Transition("binary_sensor.s", NOW - timedelta(days=d) .__add__(timedelta(hours=h - 12, minutes=5)), "on", "off", "sensor_telemetry"))
        profiles = build_discrete_profiles(trans, NOW - timedelta(days=9), NOW)
        quiet = {"binary_sensor.s": state("binary_sensor.s", "off", timedelta(hours=40))}
        self.assertEqual([f.kind for f in find_silent_entities(quiet, profiles, NOW, UTC)], ["silent_entity"])
        fine = {"binary_sensor.s": state("binary_sensor.s", "off", timedelta(hours=1))}
        self.assertEqual(find_silent_entities(fine, profiles, NOW, UTC), [])
        flap = find_flapping({"binary_sensor.s": 30}, fine, profiles, NOW, UTC)
        self.assertEqual([f.kind for f in flap], ["flapping"])
        self.assertEqual(find_flapping({"binary_sensor.s": 2}, fine, profiles, NOW, UTC), [])

    def _numeric_rows(self, mean: float = 22.0, hours: int = 40 * 24, n: int = 6) -> list[tuple[str, int, float]]:
        # ascending in time, like the telemetry store returns them
        return [((NOW - timedelta(hours=h)).replace(minute=0).isoformat(), n, mean + (0.2 if h % 2 else -0.2)) for h in range(hours - 1, 0, -1)]

    def test_numeric_excursion_requires_sustained_departure(self) -> None:
        rows = self._numeric_rows()
        # the previous full hour is also far out of range
        rows[-1] = (rows[-1][0], 6, 34.0)
        base = {"sensor.t": NumericBaseline(rows, UTC)}
        hot = {"sensor.t": state("sensor.t", "35.0", unit_of_measurement="°C", attributes={"friendly_name": "T"})}
        found = find_numeric_anomalies(hot, {"sensor.t": rows}, base, NOW, UTC)
        self.assertEqual([f.kind for f in found], ["numeric_excursion"])

        calm_rows = self._numeric_rows()
        calm_base = {"sensor.t": NumericBaseline(calm_rows, UTC)}
        spike_only = {"sensor.t": state("sensor.t", "35.0")}
        self.assertEqual(find_numeric_anomalies(spike_only, {"sensor.t": calm_rows}, calm_base, NOW, UTC), [])  # one reading is not enough
        normal = {"sensor.t": state("sensor.t", "22.3")}
        self.assertEqual(find_numeric_anomalies(normal, {"sensor.t": calm_rows}, calm_base, NOW, UTC), [])

    def test_cumulative_counters_are_ignored_and_stale_sensors_found(self) -> None:
        rows = self._numeric_rows()
        rows[-1] = (rows[-1][0], 6, 99.0)
        base = {"sensor.e": NumericBaseline(rows, UTC)}
        counter = {"sensor.e": state("sensor.e", "99.0", attributes={"state_class": "total_increasing"})}
        self.assertEqual(find_numeric_anomalies(counter, {"sensor.e": rows}, base, NOW, UTC), [])
        stale = {"sensor.e": state("sensor.e", "22.0", timedelta(hours=7), updated=NOW - timedelta(hours=7))}
        found = find_numeric_anomalies(stale, {"sensor.e": rows}, base, NOW, UTC)
        self.assertEqual([f.kind for f in found], ["stale_sensor"])

    def test_mass_unavailable_collapses_into_one_finding(self) -> None:
        many = {f"light.l{i}": state(f"light.l{i}", "unavailable", timedelta(hours=3)) for i in range(7)}
        found = find_stuck_unavailable(many, NOW, UTC)
        self.assertEqual(len(found), 1)
        self.assertIn("7 entities", found[0].summary)
        one = {"light.x": state("light.x", "unavailable", timedelta(hours=3))}
        self.assertEqual(len(find_stuck_unavailable(one, NOW, UTC)), 1)
        self.assertEqual(find_stuck_unavailable({"light.x": state("light.x", "unavailable", timedelta(minutes=5))}, NOW, UTC), [])

    def test_severity_is_contextual_and_prioritisation_is_bounded(self) -> None:
        lock = state("lock.x", "unlocked")
        light = state("light.x", "on")
        self.assertEqual(classify_severity(lock, {"presence": {"anyone_home": False}}), "critical")
        self.assertEqual(classify_severity(lock, {"presence": {"anyone_home": True}, "part_of_day": "afternoon"}), "warning")
        self.assertEqual(classify_severity(lock, {"part_of_day": "night"}), "critical")
        self.assertEqual(classify_severity(light, {"presence": {"anyone_home": False}}), "info")

        def f(kind: str, eid: str, sev: str) -> ExceptionFinding:
            return ExceptionFinding(kind, eid, sev, "s", "a", "b", 0.9)

        findings = [f("silent_entity", "a", "info"), f("routine_deviation", "a", "info"), f("dwell_anomaly", "b", "critical")]
        ranked = prioritise(findings, {"presence": {"anyone_home": True}}, limit=5)
        self.assertEqual([(x.entity_id, x.kind) for x in ranked], [("b", "dwell_anomaly"), ("a", "routine_deviation")])
        away = prioritise(findings, {"presence": {"anyone_home": False}}, limit=5)
        self.assertEqual([x.entity_id for x in away], ["b"])  # calm info-level noise is dropped while the home is empty
        self.assertEqual(len(prioritise([f("flapping", f"e{i}", "info") for i in range(10)], None, limit=3)), 3)


class StubLLM(LLMProviderPort):
    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.answer = answer or {}
        self.calls: list[dict[str, Any]] = []

    async def generate_json(self, system_prompt: str, user_prompt: str, use_fast_tier: bool = False, context_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append({"system": system_prompt, "user": user_prompt})
        return self.answer


def rule(**overrides: Any) -> WatchRule:
    base: dict[str, Any] = dict(name="r", entity_ids=["sensor.t"], condition=WatchCondition(kind="numeric", above=10.0, for_minutes=30))
    base.update(overrides)
    return WatchRule(**base)


class TestWatchRules(unittest.TestCase):
    def test_model_rejects_inconsistent_rules(self) -> None:
        bad: list[dict[str, Any]] = [
            dict(condition=WatchCondition(kind="numeric")),
            dict(condition=WatchCondition(kind="state")),
            dict(condition=WatchCondition(kind="silence", for_minutes=1)),
            dict(window_start="22:00"),
            dict(window_start="25:00", window_end="07:00"),
            dict(weekdays=["funday"]),
            dict(severity="apocalyptic"),
            dict(entity_ids=[]),
        ]
        for overrides in bad:
            with self.assertRaises((ValidationError, ValueError), msg=str(overrides)):
                rule(**overrides)
        with self.assertRaises(ValidationError):
            WatchCondition(kind="telepathy")

    def test_numeric_watch_needs_the_condition_to_hold_for_the_duration(self) -> None:
        r = rule()
        tracker = WatchTracker()
        hot = {"sensor.t": state("sensor.t", "12.5")}
        self.assertEqual(evaluate_watch(r, hot, NOW, UTC, tracker, None), [])
        self.assertEqual(evaluate_watch(r, hot, NOW + timedelta(minutes=20), UTC, tracker, None), [])
        fired = evaluate_watch(r, hot, NOW + timedelta(minutes=31), UTC, tracker, None)
        self.assertEqual(len(fired), 1)
        self.assertIn("above 10", fired[0].detail)
        cool = {"sensor.t": state("sensor.t", "9.0")}
        evaluate_watch(r, cool, NOW + timedelta(minutes=40), UTC, tracker, None)
        self.assertEqual(evaluate_watch(r, hot, NOW + timedelta(minutes=45), UTC, tracker, None), [])  # the clock restarted

    def test_state_watch_uses_real_state_age_and_supports_negation(self) -> None:
        r = rule(entity_ids=["lock.x"], condition=WatchCondition(kind="state", state="unlocked", for_minutes=10))
        self.assertEqual(evaluate_watch(r, {"lock.x": state("lock.x", "unlocked", timedelta(minutes=5))}, NOW, UTC, WatchTracker(), None), [])
        self.assertEqual(len(evaluate_watch(r, {"lock.x": state("lock.x", "unlocked", timedelta(minutes=15))}, NOW, UTC, WatchTracker(), None)), 1)
        neg = rule(entity_ids=["lock.x"], condition=WatchCondition(kind="state", state="locked", negate=True))
        self.assertEqual(len(evaluate_watch(neg, {"lock.x": state("lock.x", "jammed")}, NOW, UTC, WatchTracker(), None)), 1)
        self.assertEqual(evaluate_watch(neg, {"lock.x": state("lock.x", "locked")}, NOW, UTC, WatchTracker(), None), [])
        self.assertEqual(evaluate_watch(neg, {"lock.x": state("lock.x", "unavailable")}, NOW, UTC, WatchTracker(), None), [])

    def test_silence_watch_and_gates(self) -> None:
        sil = rule(entity_ids=["sensor.s"], condition=WatchCondition(kind="silence", for_minutes=60))
        self.assertEqual(len(evaluate_watch(sil, {"sensor.s": state("sensor.s", "1", timedelta(hours=2))}, NOW, UTC, WatchTracker(), None)), 1)
        self.assertEqual(evaluate_watch(sil, {"sensor.s": state("sensor.s", "1", timedelta(minutes=10))}, NOW, UTC, WatchTracker(), None), [])

        hot = {"sensor.t": state("sensor.t", "50")}
        base = dict(condition=WatchCondition(kind="numeric", above=10.0))
        self.assertEqual(evaluate_watch(rule(presence="away", **base), hot, NOW, UTC, WatchTracker(), True), [])
        self.assertEqual(len(evaluate_watch(rule(presence="away", **base), hot, NOW, UTC, WatchTracker(), False)), 1)
        self.assertEqual(evaluate_watch(rule(presence="home", **base), hot, NOW, UTC, WatchTracker(), None), [])
        self.assertEqual(evaluate_watch(rule(window_start="22:00", window_end="06:00", **base), hot, NOW, UTC, WatchTracker(), None), [])
        self.assertEqual(len(evaluate_watch(rule(window_start="11:00", window_end="13:00", **base), hot, NOW, UTC, WatchTracker(), None)), 1)
        self.assertEqual(evaluate_watch(rule(weekdays=["sat", "sun"], **base), hot, NOW, UTC, WatchTracker(), None), [])  # NOW is a Wednesday
        self.assertEqual(evaluate_watch(rule(enabled=False, **base), hot, NOW, UTC, WatchTracker(), None), [])

    def test_validation_against_real_entities(self) -> None:
        states = {"sensor.t": state("sensor.t", "12"), "light.l": state("light.l", "on"), "select.m": state("select.m", "a", attributes={"options": ["a", "b"]})}
        errors, _ = validate_watch(rule(entity_ids=["sensor.nope"]), states)
        self.assertIn("Unknown entity: sensor.nope", errors)
        errors, _ = validate_watch(rule(entity_ids=["light.l"]), states)
        self.assertTrue(any("no numeric value" in e for e in errors))
        errors, warnings = validate_watch(rule(entity_ids=["select.m"], condition=WatchCondition(kind="state", state="zzz")), states)
        self.assertEqual(errors, [])
        self.assertTrue(warnings)

    def test_backtest_counts_episodes_and_flags_noisy_rules(self) -> None:
        trans = on_off_history("light.a", cycles=10, on_minutes=40)
        r = rule(entity_ids=["light.a"], condition=WatchCondition(kind="state", state="on", for_minutes=30))
        res = backtest_watch(r, trans, {}, NOW - timedelta(days=12), NOW, UTC)
        self.assertEqual(res["episodes"], 10)
        longer = rule(entity_ids=["light.a"], condition=WatchCondition(kind="state", state="on", for_minutes=300))
        self.assertEqual(backtest_watch(longer, trans, {}, NOW - timedelta(days=12), NOW, UTC)["episodes"], 0)
        busy = [t for i in range(36) for t in (
            Transition("light.a", NOW - timedelta(hours=72 - 2 * i), "off", "on", "human_or_physical"),
            Transition("light.a", NOW - timedelta(hours=72 - 2 * i - 1), "on", "off", "human_or_physical"),
        )]
        noisy = rule(entity_ids=["light.a"], condition=WatchCondition(kind="state", state="on"))
        self.assertIn("very often", backtest_watch(noisy, busy, {}, NOW - timedelta(days=3), NOW, UTC)["note"])
        attr = rule(condition=WatchCondition(kind="numeric", above=1.0, attribute="x"))
        self.assertIsNone(backtest_watch(attr, [], {}, NOW - timedelta(days=5), NOW, UTC)["episodes"])

    def test_catalog_prefers_entities_mentioned_in_the_request(self) -> None:
        states = {f"sensor.thing{i}": state(f"sensor.thing{i}", "1") for i in range(50)}
        states["sensor.cellar_humidity"] = state("sensor.cellar_humidity", "60", attributes={"friendly_name": "Cellar Humidity"})
        catalog = build_entity_catalog("alert me when the cellar humidity is high", states, limit=10)
        self.assertEqual(catalog[0]["id"], "sensor.cellar_humidity")
        self.assertEqual(len(catalog), 10)


class TestWatchServiceAndApi(unittest.IsolatedAsyncioTestCase):
    GOOD = {
        "watch": {
            "name": "Hot sensor",
            "entity_ids": ["sensor.living_room_temperature"],
            "condition": {"kind": "numeric", "above": 40, "for_minutes": 10},
            "severity": "critical",
            "message": "Too hot",
        },
        "explanation": "Alerts when the living room exceeds 40 for ten minutes.",
    }

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_compile_validates_and_storage_survives_restart(self) -> None:
        mem = SQLiteMemoryAdapter(str(Path(self._tmp.name) / "m.db"))
        states = {"sensor.living_room_temperature": state("sensor.living_room_temperature", "21")}
        svc = WatchService(mem, StubLLM(self.GOOD))
        res = await svc.compile("tell me when it gets hot", states)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["draft"]["description"], "tell me when it gets hot")
        saved = await svc.save(WatchRule.model_validate(res["draft"]))

        again = WatchService(mem, StubLLM())
        self.assertEqual([r.watch_id for r in await again.list()], [saved.watch_id])
        self.assertTrue(await again.delete(saved.watch_id))
        self.assertEqual(await again.list(), [])

        unknown = WatchService(mem, StubLLM({"watch": {**self.GOOD["watch"], "entity_ids": ["sensor.invented"]}}))
        self.assertIn("Unknown entity: sensor.invented", (await unknown.compile("x y z w v", states))["errors"])
        self.assertTrue((await WatchService(mem, StubLLM({})).compile("something long enough", states))["errors"])
        self.assertTrue((await WatchService(mem, StubLLM({"error": "cannot"})).compile("something long enough", states))["errors"])
        bad = WatchService(mem, StubLLM({"watch": {"name": "n", "entity_ids": ["sensor.living_room_temperature"], "condition": {"kind": "numeric"}}}))
        self.assertTrue((await bad.compile("something long enough", states))["errors"])
        mem._conn.close()

    async def test_orchestrator_fires_once_per_cooldown_and_api_round_trip(self) -> None:
        app = create_app(BrainSettings(use_simulator=True, db_path=str(Path(self._tmp.name) / "t.db"), custom_agents_dir=self._tmp.name, timezone="UTC"))
        orch = app.state.orchestrator
        stub = StubLLM(self.GOOD)
        orch.llm = stub
        orch.watches.llm = stub
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            compiled = (await client.post("/api/watches/compile", json={"text": "alert when the living room is hot"})).json()
            self.assertEqual(compiled["errors"], [])
            self.assertIn("backtest", compiled)
            saved = await client.post("/api/watches", json=compiled["draft"])
            self.assertEqual(saved.status_code, 200)
            watch_id = saved.json()["watch"]["watch_id"]
            bad = {**compiled["draft"], "entity_ids": ["sensor.invented"], "watch_id": "other"}
            self.assertEqual((await client.post("/api/watches", json=bad)).status_code, 400)

            states = await orch.smart_home.get_all_states()
            orch._cached_states = states
            self.assertEqual(await orch.evaluate_watches(), 0)  # 22.1 is below the limit
            orch.smart_home._states["sensor.living_room_temperature"] = states["sensor.living_room_temperature"].model_copy(update={"state": "45"})
            orch._cached_states = await orch.smart_home.get_all_states()
            await orch.evaluate_watches()  # starts the 10 minute clock
            orch._watch_tracker.since[(watch_id, "sensor.living_room_temperature")] = datetime.now(UTC) - timedelta(minutes=11)
            self.assertEqual(await orch.evaluate_watches(), 1)
            self.assertEqual(await orch.evaluate_watches(), 0)  # cooldown
            insights = [i for i in await orch.memory.get_advisory_insights(status="active") if i.category == "watch"]
            self.assertEqual(len(insights), 1)

            listed = (await client.get("/api/watches")).json()["watches"]
            self.assertEqual((listed[0]["fire_count"], listed[0]["enabled"]), (1, True))
            self.assertFalse((await client.post(f"/api/watches/{watch_id}/toggle")).json()["watch"]["enabled"])
            self.assertEqual((await client.delete(f"/api/watches/{watch_id}")).status_code, 200)
            self.assertEqual((await client.delete(f"/api/watches/{watch_id}")).status_code, 404)
        orch.memory._conn.close()
        orch.telemetry.close()


class TestExceptionFeedbackLearning(unittest.IsolatedAsyncioTestCase):
    async def test_dismissals_extend_the_quiet_period_and_rejection_mutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db"), custom_agents_dir=tmp, timezone="UTC"))
            eng = orch.learning
            f = ExceptionFinding("dwell_anomaly", "light.kitchen_ceiling", "info", "s", "off", "on", 0.9)
            base = eng._cooldown(f)
            await eng.record_exception_feedback(f.feedback_key, rejected=False)
            await eng.record_exception_feedback(f.feedback_key, rejected=False)
            self.assertEqual(eng._cooldown(f), base * 4)
            await eng.record_exception_feedback(f.feedback_key, rejected=True)
            self.assertEqual(eng.muted_exceptions(), [f.feedback_key])

            fresh = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db"), custom_agents_dir=tmp, timezone="UTC"))
            await fresh.learning.load_exception_feedback()
            self.assertEqual(fresh.learning.muted_exceptions(), [f.feedback_key])
            await fresh.learning.unmute_exception(f.feedback_key)
            self.assertEqual(fresh.learning.muted_exceptions(), [])
            for o in (orch, fresh):
                o.memory._conn.close()
                o.telemetry.close()


if __name__ == "__main__":
    unittest.main()
