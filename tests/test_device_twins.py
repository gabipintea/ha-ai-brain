"""One physical device exposed twice (two integrations): recognised by serial number, history merged, nothing counted twice."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ha_ai_brain.adapters.ha_websocket_rest import HomeAssistantAdapter
from ha_ai_brain.api.app import build_orchestrator
from ha_ai_brain.application.learning import LearningEngine
from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.automation_rules import parse_automation_config, pattern_covered_by
from ha_ai_brain.domain.expectations import ExceptionFinding
from ha_ai_brain.domain.models import EntityState, Transition
from ha_ai_brain.domain.patterns import mine_all_report
from ha_ai_brain.domain.twins import EntityFacts, build_twin_map, canonicalize_transitions

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
SERIAL = "AB12CD34EF56"


def facts(eid: str, dev: str, *, serial: str = SERIAL, maker: str = "Acme", platform: str = "matter", area: str | None = None) -> EntityFacts:
    return EntityFacts(eid, dev, maker, "Roller blind", serial, platform, area)


def state(eid: str, features: int = 0, st: str = "open") -> EntityState:
    return EntityState(entity_id=eid, state=st, attributes={"friendly_name": eid.split(".")[1], "supported_features": features})


PAIR = [facts("cover.blind_a", "d1", area="kitchen"), facts("cover.blind_a_hk", "d2", platform="homekit")]
STATES = {"cover.blind_a": state("cover.blind_a", 15), "cover.blind_a_hk": state("cover.blind_a_hk", 11)}


class GroupingTests(unittest.TestCase):
    def test_same_serial_on_two_devices_is_a_twin_pair_with_the_richer_entity_kept(self) -> None:
        twins = build_twin_map(PAIR, STATES)
        self.assertEqual(len(twins.groups), 1)
        g = twins.groups[0]
        self.assertEqual((g.canonical, g.members), ("cover.blind_a", ["cover.blind_a", "cover.blind_a_hk"]))
        self.assertEqual(twins.canonical("cover.blind_a_hk"), "cover.blind_a")
        self.assertTrue(twins.are_twins("cover.blind_a", "cover.blind_a_hk"))
        self.assertEqual(g.serial_hint, "EF56")
        self.assertIn("more controls", g.why_canonical)

    def test_an_unreachable_entity_is_not_chosen(self) -> None:
        states = {**STATES, "cover.blind_a": state("cover.blind_a", 15, "unavailable")}
        self.assertEqual(build_twin_map(PAIR, states).groups[0].canonical, "cover.blind_a_hk")

    def test_things_that_are_not_twins(self) -> None:
        one_device = [facts("cover.blind_a", "d1"), facts("cover.blind_b", "d1")]  # two entities of one device
        self.assertFalse(build_twin_map(one_device))
        sensor = [facts("cover.blind_a", "d1"), facts("sensor.blind_a_battery", "d2")]  # different kind
        self.assertFalse(build_twin_map(sensor))
        other_maker = [facts("cover.blind_a", "d1"), facts("cover.blind_b", "d2", maker="Other")]
        self.assertFalse(build_twin_map(other_maker))
        for bad in ("", "1", "000000", "12"):  # missing or placeholder serials
            self.assertFalse(build_twin_map([facts("cover.blind_a", "d1", serial=bad), facts("cover.blind_b", "d2", serial=bad)]))

    def test_light_and_switch_of_one_device_exposed_twice_are_twins(self) -> None:
        pair = [facts("light.lamp", "d1"), facts("switch.lamp_hk", "d2", platform="homekit")]
        self.assertEqual(len(build_twin_map(pair).groups), 1)

    def test_entities_missing_from_home_assistant_are_ignored(self) -> None:
        self.assertFalse(build_twin_map(PAIR, {"cover.blind_a": STATES["cover.blind_a"]}))

    def test_a_split_by_the_homeowner_wins(self) -> None:
        gid = build_twin_map(PAIR, STATES).groups[0].group_id
        self.assertFalse(build_twin_map(PAIR, STATES, {gid}))


def echo_history(days: int = 10) -> list[Transition]:
    """The same blind reported by both integrations a second apart; user mostly operates it via the second one."""
    t: list[Transition] = []
    for d in range(1, days + 1):
        base = NOW - timedelta(days=d) + timedelta(hours=-3, minutes=d % 4)
        t += [Transition("cover.blind_a_hk", base, "closed", "open", "human_or_physical"), Transition("cover.blind_a", base + timedelta(seconds=1), "closed", "open", "human_or_physical"),
              Transition("cover.blind_a", base + timedelta(hours=9), "open", "closed", "human_or_physical"), Transition("cover.blind_a_hk", base + timedelta(hours=9, seconds=2), "open", "closed", "human_or_physical")]
    return t


class MergeTests(unittest.TestCase):
    def test_history_is_merged_onto_one_entity_and_echoes_dropped(self) -> None:
        twins = build_twin_map(PAIR, STATES)
        merged = canonicalize_transitions(echo_history(), twins)
        self.assertEqual({t.entity_id for t in merged}, {"cover.blind_a"})
        self.assertEqual(len(merged), 20)  # 40 raw reports = 20 movements
        g = twins.groups[0]
        self.assertEqual((g.twin_changes, g.moved_together), (20, 20))

    def test_a_change_seen_by_one_side_only_is_kept(self) -> None:
        twins = build_twin_map(PAIR, STATES)
        only = [Transition("cover.blind_a_hk", NOW, "closed", "open")]
        merged = canonicalize_transitions(only, twins)
        self.assertEqual([(t.entity_id, t.new_state) for t in merged], [("cover.blind_a", "open")])
        self.assertEqual((twins.groups[0].twin_changes, twins.groups[0].moved_together), (1, 0))

    def test_unrelated_entities_pass_through_untouched(self) -> None:
        twins = build_twin_map(PAIR, STATES)
        t = [Transition("light.porch", NOW, "off", "on")]
        self.assertEqual(canonicalize_transitions(t, twins), t)

    def test_without_twins_nothing_changes(self) -> None:
        t = echo_history(2)
        self.assertIs(canonicalize_transitions(t, build_twin_map([])), t)


class MiningTests(unittest.TestCase):
    def test_twin_history_gives_one_time_habit_and_no_sequence_between_twins(self) -> None:
        raw = echo_history()
        start, end = NOW - timedelta(days=11), NOW
        # without the merge: two different entities, differently named => a habit each and a bogus "follows" relation
        before, _ = mine_all_report(raw, start, end, UTC)
        self.assertGreaterEqual(len({p.entity_id for p in before}), 2)
        merged = canonicalize_transitions(raw, build_twin_map(PAIR, STATES))
        after, _ = mine_all_report(merged, start, end, UTC)
        self.assertEqual({p.entity_id for p in after}, {"cover.blind_a"})
        self.assertFalse([p for p in after if p.kind == "sequence"])

    def test_an_automation_on_the_other_twin_covers_the_habit(self) -> None:
        twins = build_twin_map(PAIR, STATES)
        merged = canonicalize_transitions(echo_history(), twins)
        habit = next(p for p in mine_all_report(merged, NOW - timedelta(days=11), NOW, UTC)[0] if p.to_state == "open")
        rule = parse_automation_config({"id": "1", "alias": "Open blind", "trigger": [{"platform": "time", "at": f"{int(habit.minute_of_day // 60):02d}:{int(habit.minute_of_day % 60):02d}:00"}],
                                        "action": [{"service": "cover.open_cover", "target": {"entity_id": "cover.blind_a_hk"}}]})
        self.assertIsNone(pattern_covered_by([rule], habit))
        self.assertEqual(pattern_covered_by([rule], habit, twins=twins), "Open blind")


class FakeHome:
    def __init__(self, f: list[EntityFacts]) -> None:
        self.f = f

    async def get_entity_device_facts(self) -> list[EntityFacts]:
        return self.f


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_split_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db")))
            eng: LearningEngine = orch.learning
            eng.smart_home = FakeHome(PAIR)  # type: ignore[assignment]
            twins = await eng.refresh_twins(STATES, force=True)
            self.assertEqual(len(twins.groups), 1)
            gid = twins.groups[0].group_id
            self.assertIn("reason", eng.twin_groups()[0])
            await eng.set_twin_split(gid, True)
            self.assertFalse(await eng.refresh_twins(STATES, force=True))
            self.assertEqual(await eng.twin_splits(), [gid])
            await eng.set_twin_split(gid, False)
            self.assertTrue(await eng.refresh_twins(STATES, force=True))

    async def test_registry_failure_means_no_twins_not_a_crash(self) -> None:
        class Broken:
            async def get_entity_device_facts(self) -> list[EntityFacts]:
                raise RuntimeError("no socket")

        with tempfile.TemporaryDirectory() as tmp:
            orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db")))
            orch.learning.smart_home = Broken()  # type: ignore[assignment]
            self.assertFalse(await orch.learning.refresh_twins(STATES, force=True))

    async def test_one_alert_per_twin_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db")))
            eng = orch.learning
            eng.smart_home = FakeHome(PAIR)  # type: ignore[assignment]
            await eng.refresh_twins(STATES, force=True)
            mk = lambda eid: ExceptionFinding("silent_entity", eid, "warning", "quiet", "active", "quiet")
            out = eng._one_finding_per_twin_group([mk("cover.blind_a_hk"), mk("cover.blind_a"), mk("light.other")])
            self.assertEqual([f.entity_id for f in out], ["cover.blind_a", "light.other"])
            only_other = eng._one_finding_per_twin_group([mk("cover.blind_a_hk")])
            self.assertEqual([f.entity_id for f in only_other], ["cover.blind_a_hk"])  # a problem on one side alone is still reported

    async def test_learned_snapshot_lists_the_twin_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db")))
            orch.learning.smart_home = FakeHome(PAIR)  # type: ignore[assignment]
            orch._cached_states = dict(STATES)
            snap = await orch.get_learned_snapshot()
            self.assertEqual([g["canonical"] for g in snap["device_twins"]], ["cover.blind_a"])
            self.assertEqual(snap["device_twin_splits"], [])


class AdapterTests(unittest.TestCase):
    def test_entity_facts_come_from_the_device_and_entity_registry(self) -> None:
        devices = [
            {"id": "d1", "manufacturer": "Acme", "model": "Roller blind", "serial_number": SERIAL, "area_id": "kitchen"},
            {"id": "d2", "manufacturer": "Acme", "model": "Roller blind", "serial_number": SERIAL},
            {"id": "svc", "entry_type": "service", "manufacturer": "Acme", "serial_number": SERIAL},
        ]
        entities = [
            {"entity_id": "cover.blind_a", "device_id": "d1", "platform": "matter"},
            {"entity_id": "cover.blind_a_hk", "device_id": "d2", "platform": "homekit", "hidden_by": "user"},
            {"entity_id": "sensor.cloud", "device_id": "svc", "platform": "x"},
            {"entity_id": "light.no_device", "device_id": None, "platform": "y"},
        ]
        got = {f.entity_id: f for f in HomeAssistantAdapter._build_entity_facts(devices, entities)}
        self.assertEqual(set(got), {"cover.blind_a", "cover.blind_a_hk"})
        self.assertEqual((got["cover.blind_a"].serial, got["cover.blind_a"].area_id), (SERIAL, "kitchen"))
        self.assertTrue(got["cover.blind_a_hk"].hidden)
        self.assertEqual(len(build_twin_map(list(got.values())).groups), 1)


if __name__ == "__main__":
    unittest.main()
