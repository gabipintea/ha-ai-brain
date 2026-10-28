"""Export / import round trip and re-adoption of the brain's own automations."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ha_ai_brain.api.app import build_orchestrator
from ha_ai_brain.config import AutonomyLevel, BrainSettings, OperatingMode
from ha_ai_brain.domain.models import FeedbackEpisode, FeedbackPolarity, IgnoredTarget, UserContextNote
from ha_ai_brain.domain.portability import exportable_prefs, is_secret_pref, parse_bundle
from ha_ai_brain.domain.watches import WatchRule


def make(tmp: str, name: str):
    return build_orchestrator(
        BrainSettings(use_simulator=True, operating_mode=OperatingMode.PERIODIC_BATCH, default_autonomy=AutonomyLevel.COPILOT, db_path=str(Path(tmp) / name))
    )


class PureTests(unittest.TestCase):
    def test_secrets_never_exported(self) -> None:
        self.assertTrue(is_secret_pref("llm_api_key"))
        self.assertEqual(exportable_prefs({"llm_api_key": "x", "quiet_hours_start": "22:00", "paused": "True"}), {"quiet_hours_start": "22:00"})

    def test_rejects_foreign_or_newer_files(self) -> None:
        with self.assertRaises(ValueError):
            parse_bundle({"hello": 1})
        with self.assertRaises(ValueError):
            parse_bundle({"format": "ha_ai_brain_export", "version": 99, "sections": {}})

    def test_bad_entries_are_skipped_and_counted(self) -> None:
        b = parse_bundle({"format": "ha_ai_brain_export", "version": 1, "sections": {
            "ignored_targets": [{"pattern": "sensor.x"}, {"nope": 1}],
            "preferences": {"llm_api_key": "leak", "quiet_hours_start": "22:00"},
        }})
        self.assertEqual(b.counts(), {"ignored_targets": 1, "preferences": 1})
        self.assertEqual(b.skipped["ignored_targets"], 1)
        self.assertEqual(b.sections["preferences"], [("quiet_hours_start", "22:00")])


class RoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_export_then_import_into_fresh_install(self) -> None:
        a = make(self._tmp.name, "a.db")
        await a.memory.save_ignored_target(IgnoredTarget(pattern="sensor.noisy_*", reason="r"))
        await a.memory.save_user_context_note(UserContextNote(content="Humidifier is broken"))
        await a.memory.save_ui_preference("quiet_hours_start", "22:00")
        await a.memory.save_ui_preference("llm_api_key", "SECRET")
        await a.memory.save_feedback(FeedbackEpisode(
            agent_id="x", cause_category="c", action_signature="sig1", target_entity_ids=["light.a"],
            service_called="automation.upsert_native_automation", polarity=FeedbackPolarity.REJECTED_EXPLICIT,
        ))
        await a.learning.record_exception_feedback("kind:light.a", rejected=True)
        await a.watches.save(WatchRule(name="W", entity_ids=["sensor.x"], condition={"kind": "numeric", "above": 5}, description="d"))
        bundle = await a.export_bundle()
        text = json.dumps(bundle)
        self.assertNotIn("SECRET", text)

        b = make(self._tmp.name, "b.db")
        preview = await b.import_bundle(json.loads(text), apply=False)
        self.assertFalse(preview["applied"])
        self.assertEqual(await b.memory.get_ignored_targets(), [])
        done = await b.import_bundle(json.loads(text), apply=True)
        self.assertTrue(done["applied"])
        self.assertEqual([t.pattern for t in await b.memory.get_ignored_targets()], ["sensor.noisy_*"])
        self.assertEqual(len(await b.memory.get_user_context_notes()), 1)
        self.assertIn("sig1", await b.memory.get_rejected_signatures())
        self.assertEqual(len(await b.watches.list()), 1)
        self.assertEqual(b.learning.muted_exceptions(), ["kind:light.a"])
        self.assertEqual((await b.memory.get_ui_preferences()).get("quiet_hours_start"), "22:00")
        await b.import_bundle(json.loads(text), apply=True)  # importing twice must not duplicate
        self.assertEqual(len(await b.memory.get_ignored_targets()), 1)
        self.assertEqual(len(await b.watches.list()), 1)

    async def test_adopt_only_prefixed_untracked_automations(self) -> None:
        o = make(self._tmp.name, "c.db")
        from ha_ai_brain.domain.models import NativeAutomationProposal

        light = next(e for e in await o.smart_home.get_all_states() if e.startswith("light."))
        for aid in ("ai_brain_aaaa1111", "my_own_automation"):
            await o.smart_home.upsert_automation(NativeAutomationProposal(
                automation_id=aid, alias="A " + aid, description="d", trigger=[{"platform": "time", "at": "07:00:00"}],
                action=[{"service": "light.turn_on", "target": {"entity_id": light}}],
            ))
        o._cached_states = await o.smart_home.get_all_states()
        found = await o.adoptable_automations()
        self.assertEqual([f["automation_id"] for f in found], ["ai_brain_aaaa1111"])
        res = await o.adopt_automations(["ai_brain_aaaa1111", "my_own_automation"])
        self.assertEqual(res["adopted"], ["ai_brain_aaaa1111"])
        self.assertEqual(await o.adoptable_automations(), [])
        self.assertEqual(len(await o.memory.get_accepted_automations()), 1)

    async def test_disable_enable_delete_only_for_tracked(self) -> None:
        from ha_ai_brain.domain.models import NativeAutomationProposal

        o = make(self._tmp.name, "d.db")
        light = next(e for e in await o.smart_home.get_all_states() if e.startswith("light."))
        proposals = {}
        for aid in ("ai_brain_bbbb2222", "my_own_automation"):
            proposals[aid] = NativeAutomationProposal(
                automation_id=aid, alias="A " + aid, description="d", trigger=[{"platform": "time", "at": "07:00:00"}],
                action=[{"service": "light.turn_on", "target": {"entity_id": light}}],
            )
            await o.smart_home.upsert_automation(proposals[aid])
        o._cached_states = await o.smart_home.get_all_states()
        await o.adopt_automations(["ai_brain_bbbb2222"])

        with self.assertRaises(KeyError):  # not tracked: must never be touched
            await o.set_automation_enabled("my_own_automation", False)
        with self.assertRaises(KeyError):
            await o.delete_tracked_automation("my_own_automation")

        await o.set_automation_enabled("ai_brain_bbbb2222", False)
        self.assertEqual((await o.smart_home.get_all_states())["automation.ai_brain_bbbb2222"].state, "off")
        await o.set_automation_enabled("ai_brain_bbbb2222", True)
        self.assertEqual((await o.smart_home.get_all_states())["automation.ai_brain_bbbb2222"].state, "on")

        await o.delete_tracked_automation("ai_brain_bbbb2222")
        states = await o.smart_home.get_all_states()
        self.assertNotIn("automation.ai_brain_bbbb2222", states)
        self.assertIn("automation.my_own_automation", states)
        self.assertEqual(await o.memory.get_accepted_automations(), [])


if __name__ == "__main__":
    unittest.main()
