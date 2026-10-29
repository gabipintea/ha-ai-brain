"""Scripts the household starts by hand are habits too (proposed as `script.turn_on`), but only locally mined ones, only with approval."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ha_ai_brain.api.app import build_orchestrator
from ha_ai_brain.application.learning import LearningEngine
from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.automation_rules import parse_automation_config
from ha_ai_brain.domain.backtest import backtest_automation
from ha_ai_brain.domain.guardrails import GuardrailDecisionType, GuardrailEngine
from ha_ai_brain.domain.models import ActionIntent, EntityState, StateChangedEvent, Transition
from ha_ai_brain.domain.patterns import MinedPattern, automation_from_pattern, mine_time_habits
from ha_ai_brain.domain.service_semantics import SCRIPT_RUN_STATE
from ha_ai_brain.ports.telemetry import AUTOMATION_FIRE_STATE

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def evening(d: int, origin: str = "human_or_physical") -> Transition:
    return Transition("script.movie_mode", NOW - timedelta(days=d) + timedelta(hours=9, minutes=d % 4), "off", SCRIPT_RUN_STATE, origin)


def runs(origin: str = "human_or_physical") -> list[Transition]:
    return [evening(d, origin) for d in range(1, 11)]


def pattern() -> MinedPattern:
    p = mine_time_habits(runs(), NOW - timedelta(days=11), NOW, UTC)[0]
    return p


class MiningTests(unittest.TestCase):
    def test_hand_started_script_is_a_time_habit(self) -> None:
        patterns = mine_time_habits(runs(), NOW - timedelta(days=11), NOW, UTC)
        self.assertEqual([(p.entity_id, p.to_state, p.kind) for p in patterns], [("script.movie_mode", "run", "time_habit")])
        self.assertIn("is run around", patterns[0].description)

    def test_runs_started_by_automations_are_not_habits(self) -> None:
        self.assertEqual(mine_time_habits(runs("ha_automation"), NOW - timedelta(days=11), NOW, UTC), [])

    def test_automation_calls_script_turn_on_with_presence_condition(self) -> None:
        proposal = automation_from_pattern(pattern(), {"script.movie_mode": "Movie Mode"}, ["person.a"])
        assert proposal is not None
        self.assertEqual(proposal.action[0], {"service": "script.turn_on", "target": {"entity_id": "script.movie_mode"}})
        self.assertEqual(proposal.trigger[0]["platform"], "time")
        self.assertEqual(proposal.condition[0]["entity_id"], "person.a")

    def test_existing_automation_calling_the_script_covers_the_habit(self) -> None:
        from ha_ai_brain.domain.automation_rules import pattern_covered_by

        for action in ({"service": "script.turn_on", "target": {"entity_id": "script.movie_mode"}}, {"action": "script.movie_mode"}):
            rule = parse_automation_config({"id": "1", "alias": "Evening", "trigger": [{"platform": "time", "at": "21:00:00"}], "action": [action]})
            self.assertEqual(pattern_covered_by([rule], pattern()), "Evening")

    def test_backtest_never_calls_a_script_run_redundant(self) -> None:
        proposal = automation_from_pattern(pattern())
        assert proposal is not None
        result = backtest_automation(proposal, runs(), NOW - timedelta(days=11), NOW, UTC)
        self.assertEqual(result.redundant, 0)
        self.assertGreater(result.aligned, 0)


class RecordingTests(unittest.IsolatedAsyncioTestCase):
    async def _record(self, origin: str) -> list[tuple[str, str]]:
        engine = LearningEngine.__new__(LearningEngine)
        engine._tr_buffer, engine._num_buffer, engine._last_flush = [], {}, 10**12
        old = EntityState(entity_id="script.movie_mode", state="off", attributes={})
        new = EntityState(entity_id="script.movie_mode", state="on", attributes={"last_triggered": NOW.isoformat()})
        from ha_ai_brain.domain.models import EventOrigin

        ev = StateChangedEvent(entity_id="script.movie_mode", old_state=old, new_state=new, timestamp=NOW, origin=EventOrigin(origin))
        await engine.record_event(ev)
        return [(t.entity_id, t.new_state) for t in engine._tr_buffer]

    async def test_only_hand_started_runs_become_habit_events(self) -> None:
        self.assertIn(("script.movie_mode", SCRIPT_RUN_STATE), await self._record("human_or_physical"))
        self.assertEqual(await self._record("ha_automation"), [("script.movie_mode", AUTOMATION_FIRE_STATE)])


class GuardrailTests(unittest.TestCase):
    def intent(self, script: str = "script.movie_mode") -> ActionIntent:
        p = pattern()
        proposal = automation_from_pattern(p)
        assert proposal is not None
        proposal.action[0]["target"]["entity_id"] = script
        return ActionIntent(agent_id="a", domain="automation", service="upsert_native_automation", target_entity_ids=[script],
                            service_data=proposal.model_dump(), native_automation=proposal,
                            cause_category="learned_habit", rationale="test")

    def test_blocked_by_default_and_high_risk_when_locally_mined(self) -> None:
        from ha_ai_brain.config import AutonomyLevel

        g = GuardrailEngine()
        blocked = g.evaluate(self.intent(), AutonomyLevel.AUTONOMOUS, True, {})
        self.assertEqual(blocked.decision, GuardrailDecisionType.HARD_BLOCKED)
        g.habit_scripts = frozenset({"script.movie_mode"})
        allowed = g.evaluate(self.intent(), AutonomyLevel.AUTONOMOUS, True, {})
        self.assertEqual(allowed.decision, GuardrailDecisionType.REQUIRE_USER_APPROVAL)  # high risk: never automatic
        self.assertEqual(allowed.effective_risk.value, "high")
        other = g.evaluate(self.intent("script.other"), AutonomyLevel.AUTONOMOUS, True, {})
        self.assertEqual(other.decision, GuardrailDecisionType.HARD_BLOCKED)


class EndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_hand_run_script_habit_is_proposed_for_approval_and_flag_is_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db")))
            now = datetime.now(UTC)
            trans = [Transition("script.movie_mode", now - timedelta(days=d, hours=2) , "off", SCRIPT_RUN_STATE, "human_or_physical") for d in range(1, 11)]
            await orch.telemetry.record_transitions(trans)
            states = await orch.smart_home.get_all_states()
            states["script.movie_mode"] = EntityState(entity_id="script.movie_mode", state="off", attributes={"friendly_name": "Movie Mode"})
            orch._cached_states = states
            patterns = await orch.learning.get_patterns(now, states, force=True)
            mine = [p for p in patterns if p.entity_id == "script.movie_mode"]
            self.assertTrue(mine)
            res = await orch.propose_habit(mine[0].pattern_id)
            self.assertEqual(res["status"], "proposed", res)
            self.assertEqual(orch.guardrails.habit_scripts, frozenset())


if __name__ == "__main__":
    unittest.main()
