"""Guardrails look inside the automations an agent proposes (they keep running without the brain)."""

from __future__ import annotations

import unittest

from ha_ai_brain.config import AutonomyLevel
from ha_ai_brain.domain.guardrails import GuardrailDecisionType, GuardrailEngine, iter_action_calls
from ha_ai_brain.domain.models import ActionIntent, ActionRiskLevel, NativeAutomationProposal


def intent(actions: list) -> ActionIntent:
    proposal = NativeAutomationProposal(alias="Test", description="d", trigger=[{"platform": "time", "at": "07:00:00"}], action=actions)
    return ActionIntent(
        agent_id="security_safety_agent", domain="automation", service="upsert_native_automation",
        target_entity_ids=[f"automation.{proposal.automation_id}"], service_data=proposal.model_dump(),
        cause_category="c", rationale="r", native_automation=proposal,
    )


def call(svc: str, entity: str | None = None) -> dict:
    return {"service": svc, **({"target": {"entity_id": entity}} if entity else {})}


class AutomationGuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.g = GuardrailEngine()

    def decide(self, actions: list, level: AutonomyLevel = AutonomyLevel.AUTONOMOUS):
        return self.g.evaluate(intent(actions), level, True, {})

    def test_plain_automation_stays_medium_and_autonomous_runs(self) -> None:
        d = self.decide([call("light.turn_on", "light.hall"), call("notify.notify")])
        self.assertEqual(d.effective_risk, ActionRiskLevel.MEDIUM)
        self.assertEqual(d.decision, GuardrailDecisionType.EXECUTE_IMMEDIATELY)

    def test_unlocking_inside_an_automation_always_needs_approval(self) -> None:
        for actions in (
            [call("lock.unlock", "lock.front")],
            [call("lock.open", "lock.front")],
            [call("alarm_control_panel.alarm_disarm", "alarm_control_panel.home")],
            [call("homeassistant.turn_off", "lock.front")],  # generic service aimed at a lock
            [call("cover.open_cover", "cover.garage_door")],
            [{"choose": [{"conditions": [], "sequence": [{"if": [], "then": [call("lock.unlock", "lock.back")]}]}]}],  # buried deep
            [{"parallel": [call("light.turn_on", "light.a"), call("lock.unlock", "lock.back")]}],
        ):
            d = self.decide(actions)
            self.assertEqual(d.effective_risk, ActionRiskLevel.CRITICAL, actions)
            self.assertEqual(d.decision, GuardrailDecisionType.REQUIRE_USER_APPROVAL, actions)

    def test_locking_and_closing_are_not_escalated(self) -> None:
        d = self.decide([call("lock.lock", "lock.front"), call("cover.close_cover", "cover.garage_door"), call("alarm_control_panel.alarm_arm_away", "alarm_control_panel.home")])
        self.assertEqual(d.effective_risk, ActionRiskLevel.MEDIUM)

    def test_high_risk_and_templated_services_are_never_automatic(self) -> None:
        for actions in ([call("valve.close_valve", "valve.main")], [call("homeassistant.restart")], [call("{{ states('input_text.x') }}")]):
            d = self.decide(actions)
            self.assertEqual(d.effective_risk, ActionRiskLevel.HIGH, actions)
            self.assertEqual(d.decision, GuardrailDecisionType.REQUIRE_USER_APPROVAL, actions)

    def test_code_running_services_inside_an_automation_are_blocked(self) -> None:
        for svc in ("shell_command.reboot", "python_script.x", "hassio.addon_stop"):
            d = self.decide([call("light.turn_on", "light.a"), {"sequence": [call(svc)]}])
            self.assertEqual(d.decision, GuardrailDecisionType.HARD_BLOCKED, svc)

    def test_reason_names_what_the_automation_would_do(self) -> None:
        d = self.decide([call("lock.unlock", "lock.front")])
        self.assertIn("lock.unlock", d.reason)

    def test_walker_finds_nested_calls(self) -> None:
        found = [s for s, _ in iter_action_calls([{"repeat": {"sequence": [call("a.b")]}}, {"action": "c.d"}])]
        self.assertEqual(sorted(found), ["a.b", "c.d"])



class OpeningDetectionTests(unittest.TestCase):
    def engine(self, states: dict | None = None, extra: tuple = ()) -> GuardrailEngine:
        g = GuardrailEngine()
        states = states or {}
        g.entity_lookup = lambda eid: states.get(eid, ("", ""))
        g.extra_critical = extra
        return g

    def test_device_class_and_whole_words(self) -> None:
        g = self.engine({"cover.sectional": ("garage", "Sectional"), "cover.side": ("", "Side Gate"), "cover.hall": ("door", "Hall door")})
        self.assertTrue(g.is_critical_opening("cover.sectional", "open_cover"))   # by device class, no keyword in the name
        self.assertTrue(g.is_critical_opening("cover.side", "open_cover"))        # by friendly name
        self.assertTrue(g.is_critical_opening("cover.garage_door", "open_cover"))  # by id word
        self.assertTrue(g.is_critical_opening("switch.garage_opener", "turn_on"))  # switch-like openers
        self.assertTrue(g.is_critical_opening("button.gate_open", "press"))
        self.assertFalse(g.is_critical_opening("cover.hall", "open_cover"))        # an indoor door cover
        self.assertFalse(g.is_critical_opening("cover.investigate_room", "open_cover"))  # "gate" inside another word
        self.assertFalse(g.is_critical_opening("cover.garage_door", "close_cover"))
        self.assertFalse(g.is_critical_opening("switch.garage_light", "turn_off"))

    def test_user_entries_exact_pattern_and_word(self) -> None:
        g = self.engine(extra=("cover.driveway", "*carport*", "barn"))
        self.assertTrue(g.is_critical_opening("cover.driveway", "open_cover"))
        self.assertTrue(g.is_critical_opening("cover.my_carport_door", "open_cover"))
        self.assertTrue(g.is_critical_opening("cover.old_barn", "open_cover"))
        self.assertTrue(g.is_critical_opening("switch.barn_lights", "turn_on"))   # the user asked for the word, anywhere
        self.assertFalse(g.is_critical_opening("cover.driveway", "close_cover"))
        self.assertFalse(g.is_critical_opening("cover.driveway_2", "open_cover"))  # exact entry does not match prefixes

    def test_direct_action_and_automation_are_both_critical(self) -> None:
        g = self.engine({"cover.sectional": ("garage", "")})
        direct = ActionIntent(agent_id="a", domain="cover", service="open_cover", target_entity_ids=["cover.sectional"], cause_category="c", rationale="r")
        self.assertEqual(g.evaluate(direct, AutonomyLevel.AUTONOMOUS, True, {}).effective_risk, ActionRiskLevel.CRITICAL)
        nested = intent([{"if": [], "then": [call("cover.open_cover", "cover.sectional")]}])
        self.assertEqual(g.evaluate(nested, AutonomyLevel.AUTONOMOUS, True, {}).effective_risk, ActionRiskLevel.CRITICAL)
        closing = ActionIntent(agent_id="a", domain="cover", service="close_cover", target_entity_ids=["cover.sectional"], cause_category="c", rationale="r")
        self.assertNotEqual(g.evaluate(closing, AutonomyLevel.AUTONOMOUS, True, {}).effective_risk, ActionRiskLevel.CRITICAL)


if __name__ == "__main__":
    unittest.main()
