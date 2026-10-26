"""0.2.2 fixes: duplicate habit proposals, coverage matching, alias prefix, research repair, automation health, scheduler."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ha_ai_brain.domain.automation_rules import clean_alias, parse_automation_config, pattern_covered_by
from ha_ai_brain.domain.backtest import Timeline
from ha_ai_brain.domain.lifecycle import review_deployed_automation
from ha_ai_brain.domain.models import EntityState, NativeAutomationProposal
from ha_ai_brain.domain.patterns import MinedPattern, is_duplicate_habit, same_device
from ha_ai_brain.domain.research import KnowledgeItem, repair_item

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def habit(entity_id: str, minute: float = 457.0, state: str = "off", day_class: str = "all") -> MinedPattern:
    return MinedPattern(
        pattern_id=f"p_{entity_id}", kind="time_habit", entity_id=entity_id, to_state=state, day_class=day_class,
        support_days=8, observed_days=10, confidence=0.8, description="x", minute_of_day=minute, spread_minutes=4.0,
    )


def rule(trigger: dict, entity: str = "light.porch_lights", service: str = "light.turn_off"):
    return parse_automation_config({"id": "a1", "alias": "Cutoff", "trigger": [trigger], "action": [{"service": service, "target": {"entity_id": entity}}]})


class DuplicateHabitTests(unittest.TestCase):
    def test_light_switch_twins_are_one_device(self) -> None:
        self.assertTrue(same_device("light.porch_lights", "switch.porch_lights"))
        self.assertFalse(same_device("light.porch_lights", "light.garden"))
        self.assertFalse(same_device("cover.porch_lights", "light.porch_lights"))
        self.assertTrue(is_duplicate_habit(habit("light.porch_lights"), habit("switch.porch_lights", 460.0)))

    def test_same_friendly_name_same_time_is_duplicate(self) -> None:
        names = {"cover.blind_small": "Blind Small", "cover.vendor_block_out_blind_2": "Blind Small", "cover.other": "Other"}
        a, b = habit("cover.blind_small", 556.0, "open"), habit("cover.vendor_block_out_blind_2", 558.0, "open")
        self.assertTrue(is_duplicate_habit(a, b, names))
        self.assertFalse(is_duplicate_habit(a, habit("cover.other", 556.0, "open"), names))
        self.assertFalse(is_duplicate_habit(a, habit("cover.vendor_block_out_blind_2", 700.0, "open"), names))
        self.assertFalse(is_duplicate_habit(a, habit("cover.vendor_block_out_blind_2", 556.0, "closed"), names))


class CoverageTests(unittest.TestCase):
    def test_threshold_triggered_rule_does_not_cover_a_time_habit(self) -> None:
        r = rule({"platform": "numeric_state", "entity_id": "sensor.porch_temp", "above": 60})
        self.assertIsNone(pattern_covered_by([r], habit("light.porch_lights")))

    def test_event_rule_still_covers_and_twin_counts(self) -> None:
        r = rule({"platform": "state", "entity_id": "binary_sensor.motion", "to": "off"})
        self.assertEqual(pattern_covered_by([r], habit("light.porch_lights")), "Cutoff")
        self.assertEqual(pattern_covered_by([r], habit("switch.porch_lights")), "Cutoff")


class AliasTests(unittest.TestCase):
    def test_single_prefix(self) -> None:
        def make(alias: str) -> NativeAutomationProposal:
            return NativeAutomationProposal(alias=alias, description="d", trigger=[{}], action=[{}])

        self.assertEqual(make("Porch").branded_alias, "[AI Brain] Porch")
        self.assertEqual(make("[AI Brain] Porch").branded_alias, "[AI Brain] Porch")
        self.assertEqual(make("[ai brain] [AI Brain] Porch").branded_alias, "[AI Brain] Porch")

    def test_clean_alias_collapses_old_double_prefix(self) -> None:
        self.assertEqual(clean_alias("[AI Brain] [AI Brain] Porch"), "[AI Brain] Porch")
        self.assertEqual(clean_alias("[AI Brain] Porch"), "[AI Brain] Porch")
        self.assertEqual(clean_alias("Porch"), "Porch")


class ResearchRepairTests(unittest.TestCase):
    def test_list_repr_and_high_confidence_are_repaired(self) -> None:
        item = KnowledgeItem(
            agent_id="a", title="t", summary="s", confidence="high",
            how_to_apply="['Verify the sensor.', 'Add a condition, don\\'t skip it.']", caveats="Plain text.",
        )
        fixed = repair_item(item)
        self.assertEqual(fixed.how_to_apply, "1) Verify the sensor. 2) Add a condition, don't skip it.")
        self.assertEqual(fixed.caveats, "Plain text.")
        self.assertEqual(fixed.confidence, "medium")

    def test_web_sourced_high_confidence_is_kept(self) -> None:
        item = KnowledgeItem(agent_id="a", title="t", summary="s", confidence="high", basis="web_sources")
        self.assertEqual(repair_item(item).confidence, "high")

    def test_text_that_is_not_a_list_is_untouched(self) -> None:
        item = KnowledgeItem(agent_id="a", title="t", summary="s", how_to_apply="[note] keep as is")
        self.assertEqual(repair_item(item).how_to_apply, "[note] keep as is")


class AutomationHealthTests(unittest.TestCase):
    def test_young_automation_without_runs_is_too_new(self) -> None:
        on = EntityState(entity_id="automation.x", state="on")
        kwargs = dict(automation_id="x", alias="X", now=NOW, state=on, actions=[], tl=Timeline([]))
        young = review_deployed_automation(deployed_at=NOW - timedelta(days=1, hours=2), fires=[], **kwargs)
        self.assertEqual(young.verdict, "too_new")
        ran = review_deployed_automation(deployed_at=NOW - timedelta(days=2), fires=[NOW - timedelta(hours=3)], **kwargs)
        self.assertEqual(ran.verdict, "healthy")
        older = review_deployed_automation(deployed_at=NOW - timedelta(days=4), fires=[], **kwargs)
        self.assertEqual(older.verdict, "healthy")


if __name__ == "__main__":
    unittest.main()
