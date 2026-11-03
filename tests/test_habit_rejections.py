"""Habits the homeowner rejected ("Not a habit"): hidden, never proposed, kept in a list from which they can be restored or deleted."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ha_ai_brain.api.app import build_orchestrator, create_app
from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.habit_rejections import RejectedHabit, rejection_matches, split_rejected
from ha_ai_brain.domain.models import EntityState
from ha_ai_brain.domain.patterns import MinedPattern
from ha_ai_brain.domain.portability import parse_bundle

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def habit(pid: str, eid: str = "light.living_room", state: str = "on", minute: float = 420.0, days: str = "all") -> MinedPattern:
    return MinedPattern(pid, "time_habit", eid, state, days, 8, 10, 0.8, f"{eid} is set to '{state}' around {int(minute)}", minute_of_day=minute, spread_minutes=10)


def sequence(pid: str, trigger: str = "binary_sensor.hall_motion", eid: str = "light.hall", state: str = "on") -> MinedPattern:
    return MinedPattern(pid, "sequence", eid, state, "all", 9, 10, 0.9, f"{eid} follows {trigger}", trigger_entity=trigger, trigger_state="on", median_lag_seconds=5)


def rejected(p: MinedPattern) -> RejectedHabit:
    return RejectedHabit.from_pattern(p, NOW)


class MatchingTests(unittest.TestCase):
    def test_same_id_matches(self) -> None:
        self.assertTrue(rejection_matches(rejected(habit("a1")), habit("a1", minute=900)))

    def test_a_time_habit_that_drifted_a_little_is_still_the_rejected_habit(self) -> None:
        r = rejected(habit("a1", minute=420))
        self.assertTrue(rejection_matches(r, habit("b2", minute=445)))  # new id after the average time moved to another bucket
        self.assertFalse(rejection_matches(r, habit("b2", minute=480)))  # an hour later is a different habit
        self.assertFalse(rejection_matches(r, habit("b2", state="off")))
        self.assertFalse(rejection_matches(r, habit("b2", eid="light.kitchen")))

    def test_day_classes(self) -> None:
        self.assertTrue(rejection_matches(rejected(habit("a1", days="all")), habit("b2", days="weekday")))
        self.assertTrue(rejection_matches(rejected(habit("a1", days="weekday")), habit("b2", days="all")))
        self.assertFalse(rejection_matches(rejected(habit("a1", days="weekday")), habit("b2", days="weekend")))

    def test_same_device_exposed_twice_and_same_name(self) -> None:
        r = rejected(habit("a1", eid="light.desk_lamp"))
        self.assertTrue(rejection_matches(r, habit("b2", eid="switch.desk_lamp")))
        names = {"light.desk_lamp": "Desk lamp", "light.desk_lamp_2": "Desk lamp"}
        self.assertFalse(rejection_matches(r, habit("b2", eid="light.desk_lamp_2")))
        self.assertTrue(rejection_matches(r, habit("b2", eid="light.desk_lamp_2"), names))
        canonical = {"light.desk_lamp_hk": "light.desk_lamp"}
        self.assertTrue(rejection_matches(r, habit("b2", eid="light.desk_lamp_hk"), canonical=lambda e: canonical.get(e, e)))

    def test_sequences(self) -> None:
        r = rejected(sequence("s1"))
        self.assertTrue(rejection_matches(r, sequence("s2")))
        self.assertFalse(rejection_matches(r, sequence("s2", trigger="binary_sensor.kitchen_motion")))
        self.assertFalse(rejection_matches(r, habit("s2", eid="light.hall")))

    def test_split_reports_which_rejections_are_still_found(self) -> None:
        kept, seen = split_rejected([habit("a1"), habit("c3", eid="light.kitchen")], [rejected(habit("a1")), rejected(sequence("s1"))])
        self.assertEqual([p.pattern_id for p in kept], ["c3"])
        self.assertEqual(seen, {"a1"})

    def test_export_entries_are_validated(self) -> None:
        good = rejected(habit("a1")).model_dump(mode="json")
        b = parse_bundle({"format": "ha_ai_brain_export", "version": 1, "sections": {"rejected_habits": [good, {"kind": "nope"}]}})
        self.assertEqual(b.counts(), {"rejected_habits": 1})
        self.assertEqual(b.skipped["rejected_habits"], 1)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    def make(self, name: str = "t.db"):
        orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(self._tmp.name) / name)))
        orch.learning._patterns = [habit("a1"), habit("c3", eid="light.kitchen")]
        orch.learning._patterns_at = datetime.now(UTC) + timedelta(minutes=5)  # serve the patterns above from the cache instead of mining
        return orch

    async def test_reject_restore_and_delete(self) -> None:
        orch = self.make()
        eng = orch.learning
        await eng.reject_habit("a1", NOW)
        self.assertEqual([p.pattern_id for p in await eng.get_patterns(NOW)], ["c3"])
        cards = await eng.rejected_habit_cards()
        self.assertEqual([(c["rejection_id"], c["still_detected"]) for c in cards], [("a1", True)])
        with self.assertRaises(KeyError):
            await orch.propose_habit("a1")  # a rejected habit cannot be proposed

        # 1. Restore puts the habit back into found habits
        self.assertTrue(await eng.restore_rejected_habit("a1"))
        self.assertEqual([p.pattern_id for p in await eng.get_patterns(NOW)], ["a1", "c3"])
        self.assertEqual(await eng.rejected_habit_cards(), [])

        # 2. Reject it again
        await eng.reject_habit("a1", NOW)
        self.assertEqual([p.pattern_id for p in await eng.get_patterns(NOW)], ["c3"])

        # 3. Delete deletes it completely: NOT in rejected_habits AND NOT in found habits
        self.assertTrue(await eng.delete_rejected_habit("a1", NOW))
        self.assertEqual(await eng.rejected_habit_cards(), [])
        self.assertEqual([p.pattern_id for p in await eng.get_patterns(NOW)], ["c3"])

        # Survives a restart / reload from KV store
        eng._rejected_habits = None
        self.assertEqual(await eng.rejected_habit_cards(), [])
        self.assertEqual([p.pattern_id for p in await eng.get_patterns(NOW)], ["c3"])

        with self.assertRaises(KeyError):
            await eng.reject_habit("missing", NOW)

    async def test_a_rejection_no_longer_found_stays_listed(self) -> None:
        eng = self.make().learning
        await eng.reject_habit("a1", NOW)
        eng._patterns = [habit("c3", eid="light.kitchen")]
        await eng.get_patterns(NOW)
        self.assertEqual([c["still_detected"] for c in await eng.rejected_habit_cards()], [False])

    async def test_snapshot_export_and_import(self) -> None:
        a = self.make("a.db")
        a._cached_states = {"light.living_room": EntityState(entity_id="light.living_room", state="off", attributes={})}
        await a.reject_habit("a1")
        snap = await a.get_learned_snapshot()
        self.assertEqual([r["rejection_id"] for r in snap["rejected_habits"]], ["a1"])
        self.assertNotIn("a1", [p["pattern_id"] for p in snap["patterns"]])
        bundle = await a.export_bundle()
        self.assertEqual(len(bundle["sections"]["rejected_habits"]), 1)

        b = self.make("b.db")
        await b.import_bundle(bundle, apply=True)
        self.assertEqual([r.rejection_id for r in await b.learning.list_rejected_habits()], ["a1"])
        self.assertEqual([p.pattern_id for p in await b.learning.get_patterns(NOW)], ["c3"])


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(settings=BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "api.db")))
            orch = app.state.orchestrator
            orch.learning._patterns = [habit("a1"), habit("c3", eid="light.kitchen")]
            orch.learning._patterns_at = datetime.now(UTC) + timedelta(minutes=5)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                self.assertEqual((await client.post("/api/habits/reject", json={"pattern_id": "nope"})).status_code, 404)
                res = await client.post("/api/habits/reject", json={"pattern_id": "a1"})
                self.assertEqual(res.status_code, 200)
                self.assertEqual([r["rejection_id"] for r in res.json()["rejected_habits"]], ["a1"])
                res = await client.post("/api/habits/rejected/a1/restore")
                self.assertEqual((res.status_code, res.json()["status"]), (200, "restored"))
                await client.post("/api/habits/reject", json={"pattern_id": "a1"})
                res = await client.delete("/api/habits/rejected/a1")
                self.assertEqual((res.status_code, res.json()["status"]), (200, "deleted"))
                self.assertEqual((await client.delete("/api/habits/rejected/a1")).status_code, 404)
                # Verify that after delete, a1 does not appear in learned snapshot patterns OR rejected_habits
                learned = (await client.get("/api/learned")).json()
                self.assertEqual([p["pattern_id"] for p in learned["patterns"]], ["c3"])
                self.assertEqual(learned["rejected_habits"], [])


if __name__ == "__main__":
    unittest.main()
