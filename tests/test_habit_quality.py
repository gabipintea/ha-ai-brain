"""Habit list quality: transitional states, mirrored pairs, twin entities; proposing a habit on demand; rejected-list filtering."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ha_ai_brain.api.app import build_orchestrator
from ha_ai_brain.application.learning import LearningEngine
from ha_ai_brain.config import AutonomyLevel, BrainSettings, OperatingMode
from ha_ai_brain.domain.models import EntityState, FeedbackEpisode, FeedbackPolarity, Transition
from ha_ai_brain.domain.patterns import MinedPattern, mine_sequences

START = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
END = START + timedelta(days=12)


def day(d: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return START + timedelta(days=d, hours=hour - 8, minutes=minute, seconds=second)


def sequences(transitions: list[Transition]) -> list[tuple[str, str | None]]:
    return [(p.entity_id, p.trigger_entity) for p in mine_sequences(transitions, START, END)]


class SequenceQualityTests(unittest.TestCase):
    def test_transitional_states_are_not_triggers(self) -> None:
        """One blind exposed by two integrations: A 'opening' then B 'open' is a single movement, not a habit."""
        t: list[Transition] = []
        for d in range(10):
            t += [
                Transition("cover.a", day(d, 9, 0, 0), "closed", "opening"), Transition("cover.b", day(d, 9, 0, 20), "closed", "open"),
                Transition("cover.b", day(d, 9, 5, 0), "open", "closed"), Transition("cover.a", day(d, 9, 5, 20), "opening", "open"),
            ]
        self.assertNotIn(("cover.b", "cover.a"), sequences(t))

    def test_mirrored_pairs_are_dropped_but_one_way_relations_stay(self) -> None:
        t: list[Transition] = []
        for d in range(10):
            # A opens, B opens 30 s later, and B opens -> A closes 5 minutes later: A->B and B->A both hold (a mirror)
            t += [Transition("cover.a", day(d, 9), "closed", "open"), Transition("cover.b", day(d, 9, 0, 30), "closed", "open"),
                  Transition("cover.a", day(d, 9, 5), "open", "closed"), Transition("cover.b", day(d, 9, 5, 30), "open", "closed")]
            # a genuine one-way relation: the porch light switch is followed by the hall cover
            t += [Transition("switch.porch", day(d, 18), "off", "on"), Transition("cover.hall", day(d, 18, 1), "open", "closed")]
        found = sequences(t)
        self.assertIn(("cover.hall", "switch.porch"), found)
        self.assertFalse([f for f in found if set(f) == {"cover.a", "cover.b"}])

    def test_same_named_entities_of_one_type_are_twins(self) -> None:
        def state(eid: str, name: str) -> EntityState:
            return EntityState(entity_id=eid, state="open", attributes={"friendly_name": name})

        states = {"cover.x": state("cover.x", "Blind Small"), "cover.y": state("cover.y", "Blind Small"), "cover.z": state("cover.z", "Other")}
        seq = lambda a, b: MinedPattern(pattern_id="p", kind="sequence", entity_id=b, to_state="open", day_class="all", support_days=9,
                                         observed_days=9, confidence=1.0, description="d", trigger_entity=a, trigger_state="open")
        self.assertTrue(LearningEngine._is_twin_sequence(seq("cover.x", "cover.y"), states))
        self.assertFalse(LearningEngine._is_twin_sequence(seq("cover.x", "cover.z"), states))


class OrchestratorHabitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.o = build_orchestrator(BrainSettings(
            use_simulator=True, operating_mode=OperatingMode.PERIODIC_BATCH, default_autonomy=AutonomyLevel.COPILOT,
            db_path=str(Path(self._tmp.name) / "h.db"),
        ))

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_rejected_insight_records_are_not_listed_as_rejected_actions(self) -> None:
        ep = lambda svc, sig: FeedbackEpisode(agent_id="a", cause_category="c", action_signature=sig, target_entity_ids=[],
                                              service_called=svc, polarity=FeedbackPolarity.REJECTED_EXPLICIT)
        await self.o.memory.save_feedback(ep("advisory_insight", "sig:a:advisory_insight:x"))
        await self.o.memory.save_feedback(ep("switch.turn_off", "sig:a:switch.turn_off:switch.x"))
        import httpx
        from ha_ai_brain.api.app import create_app

        app = create_app(settings=self.o.settings)
        await app.state.orchestrator.memory.save_feedback(ep("advisory_insight", "sig:a:advisory_insight:x"))
        await app.state.orchestrator.memory.save_feedback(ep("switch.turn_off", "sig:a:switch.turn_off:switch.x"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            listed = (await client.get("/api/status")).json()["rejected_suggestions"]
        self.assertEqual([e["service_called"] for e in listed], ["switch.turn_off"])

    async def test_propose_habit_sends_it_to_approvals_and_reports_problems(self) -> None:
        with self.assertRaises(KeyError):
            await self.o.propose_habit("nope")
        pattern = MinedPattern(pattern_id="th_demo", kind="time_habit", entity_id="light.living_room", to_state="off", day_class="all",
                               support_days=7, observed_days=10, confidence=0.67, description="light.living_room is set to 'off' around 23:00",
                               minute_of_day=23 * 60.0, spread_minutes=5.0)
        states = await self.o.smart_home.get_all_states()
        light = next(e for e in states if e.startswith("light."))
        pattern.entity_id = light
        self.o.learning._patterns, self.o.learning._patterns_at = [pattern], datetime.now(timezone.utc)

        result = await self.o.propose_habit("th_demo")
        self.assertEqual(result["status"], "proposed", result)
        self.assertTrue([p for p in await self.o.get_pending_approvals() if p.intent.cause_category == "learned_habit"])
        again = await self.o.propose_habit("th_demo")
        self.assertEqual(again["status"], "suppressed_duplicate_pending")

        pattern.covered_by = "Existing"
        self.assertEqual((await self.o.propose_habit("th_demo"))["status"], "already_automated")


if __name__ == "__main__":
    unittest.main()
