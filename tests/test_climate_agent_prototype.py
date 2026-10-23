"""End-to-End Verification Suite for the Hexagonal HA AI Brain & Climate Agent Prototype."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ha_ai_brain.adapters.ha_simulator import SmartHomeSimulatorAdapter
from ha_ai_brain.api.app import build_orchestrator
from ha_ai_brain.config import AutonomyLevel, BrainSettings, OperatingMode
from ha_ai_brain.domain.guardrails import GuardrailDecisionType
from ha_ai_brain.domain.models import ActionIntent, ActionRiskLevel, FeedbackPolarity


class TestClimateAgentPrototype(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_file = str(Path(self._tmp_dir.name) / "test_brain.db")
        self.settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.HYBRID,
            default_autonomy=AutonomyLevel.COPILOT,
            notifications_enabled=True,
            db_path=db_file,
            custom_agents_dir="agents",
        )
        self.orchestrator = build_orchestrator(self.settings)
        assert isinstance(self.orchestrator.smart_home, SmartHomeSimulatorAdapter)
        self.simulator: SmartHomeSimulatorAdapter = self.orchestrator.smart_home

    async def asyncTearDown(self) -> None:
        self._tmp_dir.cleanup()

    async def test_1_condensation_subagent_computation_and_repeatable_approval(self) -> None:
        """
        Verify that:
        1. A humidity spike in Master Bedroom triggers the Climate Agent.
        2. The Research Sub-Agent discovers psychrometric condensation physics.
        3. The Computation Sub-Agent executes Python code in the sandbox to calculate Dew Point & Window Glass Margin.
        4. In Co-Pilot mode, the reaction asks for approval first; once approved as repeatable,
           a second identical event executes automatically without asking again!
        """
        event = self.simulator.emit_simulated_state_change("sensor.master_bedroom_humidity", "68.5")
        logs = await self.orchestrator.process_state_changed_event(event)
        self.assertGreaterEqual(len(logs), 1)
        log = logs[0]

        # Verify Research Sub-Agent & Computation Sub-Agent derived signals
        self.assertGreaterEqual(len(log.research_findings), 1)
        signal_map = {s.signal_name: s for s in log.derived_signals}
        self.assertIn("master_bedroom_dew_point_temperature", signal_map)
        self.assertIn("master_bedroom_window_condensation_margin", signal_map)

        dew_point = float(signal_map["master_bedroom_dew_point_temperature"].value)
        self.assertAlmostEqual(dew_point, 14.94, delta=0.2)

        # In COPILOT mode with notifications enabled, actions require confirmation first
        pending = await self.orchestrator.memory.get_pending_approvals()
        self.assertGreaterEqual(len(pending), 1)

        # Approve all pending actions as REPEATABLE ("Always Allow This")
        for p in pending:
            res = await self.orchestrator.handle_approval_decision(
                approval_id=p.approval_id,
                decision="approved_repeatable",
                human_note="Endorsed condensation mitigation as repeatable.",
            )
            self.assertTrue(res["repeatable_rule_saved"])

        # Verify repeatable rules are stored in SQLite memory
        rules = await self.orchestrator.memory.get_endorsed_rules()
        self.assertGreaterEqual(len(rules), 1)

        # Now trigger another significant humidity spike in the same room
        event2 = self.simulator.emit_simulated_state_change("sensor.master_bedroom_humidity", "72.0")
        logs2 = await self.orchestrator.process_state_changed_event(event2)
        self.assertGreaterEqual(len(logs2), 1)

        # Every endorsed repeatable action must now execute immediately without asking confirmation!
        statuses = [r["status"] for r in logs2[0].execution_results]
        self.assertTrue(all(s == "executed" for s in statuses), f"Expected all executed, got {statuses}")

    async def test_2_solar_illuminance_and_ufh_thermal_inertia(self) -> None:
        """
        Verify that high outdoor south illuminance wakes the Climate Agent in Autonomous mode
        to proactively trim the Living Room UFH thermostat setpoint and adjust south blinds.
        """
        self.orchestrator.settings.default_autonomy = AutonomyLevel.AUTONOMOUS
        event = self.simulator.emit_simulated_state_change("sensor.outdoor_south_illuminance", "48500")
        logs = await self.orchestrator.process_state_changed_event(event)
        self.assertGreaterEqual(len(logs), 1)

        log = logs[0]
        signal_names = {s.signal_name for s in log.derived_signals}
        self.assertIn("living_room_solar_heat_gain_index", signal_names)

        # Verify UFH thermostat and blinds were proactively adjusted in the simulator
        states = await self.simulator.get_all_states()
        self.assertEqual(states["climate.living_room_ufh"].attributes["temperature"], 20.5)
        self.assertEqual(states["cover.living_room_south_blinds"].attributes["current_position"], 45)

    async def test_3_implicit_human_override_and_conflict_arbiter_backoff(self) -> None:
        """
        Verify that if a human manually changes an entity shortly after the AI controlled it,
        the AI records an OVERRIDDEN_IMPLICIT feedback episode and locks out further AI changes
        during the manual override cooldown.
        """
        self.orchestrator.settings.default_autonomy = AutonomyLevel.AUTONOMOUS
        # 1. AI adjusts living room UFH via solar gain reaction
        event = self.simulator.emit_simulated_state_change("sensor.outdoor_south_illuminance", "49000")
        await self.orchestrator.process_state_changed_event(event)

        # Simulate 10 seconds passing so it falls into the human override detection window (>2s)
        ai_rec = self.orchestrator.triage._recent_ai_actions["climate.living_room_ufh"]
        from datetime import timedelta
        ai_rec["timestamp"] = ai_rec["timestamp"] - timedelta(seconds=15)

        # 2. Human manually sets UFH back to 23.0°C
        human_event = self.simulator.emit_simulated_state_change(
            "climate.living_room_ufh",
            "heat",
            attributes_patch={"temperature": 23.0},
            context_user_id="human_user_01",
        )
        # Change state string slightly to represent manual override transition
        human_event.old_state.state = "auto"  # type: ignore[union-attr]

        await self.orchestrator.process_state_changed_event(human_event)

        # Verify implicit negative feedback was recorded
        feedback = await self.orchestrator.memory.get_relevant_feedback("climate_thermal_agent")
        override_Polarities = [f.polarity for f in feedback]
        self.assertIn(FeedbackPolarity.OVERRIDDEN_IMPLICIT, override_Polarities)

        # Verify Conflict Arbiter now blocks the AI from touching `climate.living_room_ufh`
        test_intent = ActionIntent(
            agent_id="climate_thermal_agent",
            domain="climate",
            service="set_temperature",
            target_entity_ids=["climate.living_room_ufh"],
            service_data={"temperature": 20.0},
            cause_category="solar_gain_ufh_inertia_compensation",
            rationale="Attempt to re-apply AI setpoint",
        )
        allowed, reason = self.orchestrator.arbiter.evaluate_intent(test_intent)
        self.assertFalse(allowed)
        self.assertIn("Human Override Cooldown", reason)

    async def test_4_periodic_batch_mode_insulation_diagnosis_and_native_automations(self) -> None:
        """
        Verify Mode B (Periodic Batch Analysis):
        1. Diagnoses high winter thermal decay rate (-0.7°C/hr) in North Office and emits an AdvisoryInsight.
        2. Synthesizes Native Home Assistant Automations to run patterns with 0 ongoing tokens.
        """
        self.orchestrator.settings.default_autonomy = AutonomyLevel.AUTONOMOUS
        log = await self.orchestrator.run_periodic_batch_analysis(agent_id="climate_thermal_agent")

        self.assertEqual(log.mode, "periodic_batch")
        self.assertGreaterEqual(len(log.advisory_insights), 1)
        insight_titles = [i.title for i in log.advisory_insights]
        self.assertTrue(any("North Office" in t for t in insight_titles))

        # Verify native Home Assistant automations were synthesized and upserted
        self.assertGreaterEqual(len(self.simulator.created_automations), 2)

    async def test_5_hard_safety_guardrails_and_custom_agents(self) -> None:
        """
        Verify hard temperature bounds (blocking 35°C) and critical lock guardrails,
        plus custom YAML agent loading (Solar Agent & Craft Beer Brewery Agent).
        """
        unsafe_temp_intent = ActionIntent(
            agent_id="climate_thermal_agent",
            domain="climate",
            service="set_temperature",
            target_entity_ids=["climate.master_bedroom_ufh"],
            service_data={"temperature": 35.0},
            cause_category="unsafe_test",
            rationale="Unsafe overheating test",
        )
        eval_temp = self.orchestrator.guardrails.evaluate(
            intent=unsafe_temp_intent,
            autonomy_level=AutonomyLevel.AUTONOMOUS,
            notifications_enabled=False,
            endorsed_rules={},
        )
        self.assertEqual(eval_temp.decision, GuardrailDecisionType.HARD_BLOCKED)

        unlock_intent = ActionIntent(
            agent_id="security_safety_agent",
            domain="lock",
            service="unlock",
            target_entity_ids=["lock.front_door"],
            service_data={},
            cause_category="unlock_test",
            rationale="Test unlocking door",
            risk_level=ActionRiskLevel.LOW,
        )
        eval_lock = self.orchestrator.guardrails.evaluate(
            intent=unlock_intent,
            autonomy_level=AutonomyLevel.AUTONOMOUS,
            notifications_enabled=False,
            endorsed_rules={},
        )
        self.assertEqual(eval_lock.effective_risk, ActionRiskLevel.CRITICAL)
        self.assertEqual(eval_lock.decision, GuardrailDecisionType.REQUIRE_USER_APPROVAL)

        # Verify custom YAML agents (Solar & Brewery) loaded from `agents/`
        agent_ids = {a.agent_id for a in self.orchestrator.registry.list_agents()}
        self.assertIn("solar_energy_agent", agent_ids)
        self.assertIn("beer_brewery_agent", agent_ids)


if __name__ == "__main__":
    unittest.main()
