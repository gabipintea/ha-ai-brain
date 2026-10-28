"""0.2.5: plain-language automation drafts, tracking of deployed automations, habit list de-duplication."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ha_ai_brain.api.app import build_orchestrator
from ha_ai_brain.config import AutonomyLevel, BrainSettings, OperatingMode
from ha_ai_brain.domain.automation_draft import proposal_from_yaml, proposal_to_yaml, referenced_entities, validate_draft
from ha_ai_brain.domain.backtest import Timeline
from ha_ai_brain.domain.lifecycle import review_deployed_automation
from ha_ai_brain.domain.models import EntityState, NativeAutomationProposal

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)

YAML = """
alias: Evening light
triggers:
  - platform: time
    at: "20:00:00"
conditions: []
actions:
  - service: light.turn_on
    target:
      entity_id: light.living
"""


class DraftDomainTests(unittest.TestCase):
    def test_yaml_round_trip_and_plural_keys(self) -> None:
        p = proposal_from_yaml(YAML, "my_auto_1")
        self.assertEqual((p.alias, p.automation_id, len(p.trigger), len(p.action)), ("Evening light", "my_auto_1", 1, 1))
        again = proposal_from_yaml(proposal_to_yaml(p), "my_auto_1")
        self.assertEqual(again.action, p.action)

    def test_bad_yaml_is_a_value_error(self) -> None:
        with self.assertRaises(ValueError):
            proposal_from_yaml("alias: [unclosed")
        with self.assertRaises(ValueError):
            proposal_from_yaml("- just\n- a list")

    def test_validation(self) -> None:
        p = proposal_from_yaml(YAML)
        errors, _ = validate_draft(p, {"light.living"}, {"light": ["turn_on"]})
        self.assertEqual(errors, [])
        errors, _ = validate_draft(p, {"light.other"})
        self.assertTrue(any("light.living" in e for e in errors))
        _, warnings = validate_draft(p, {"light.living"}, {"light": ["toggle"]})
        self.assertTrue(any("light.turn_on" in w for w in warnings))
        empty = NativeAutomationProposal(alias="x", description="", trigger=[], action=[])
        self.assertEqual(len(validate_draft(empty, set())[0]), 2)

    def test_referenced_entities(self) -> None:
        self.assertEqual(referenced_entities([{"entity_id": ["a.b", "c.d"]}, {"target": {"entity_id": "e.f"}}]), {"a.b", "c.d", "e.f"})


class HealthWordingTests(unittest.TestCase):
    def test_singular_run_and_day(self) -> None:
        on = EntityState(entity_id="automation.x", state="on")
        r = review_deployed_automation(
            automation_id="x", alias="X", deployed_at=NOW - timedelta(days=2), now=NOW, state=on,
            fires=[NOW - timedelta(hours=3)], actions=[], tl=Timeline([]),
        )
        self.assertIn("1 run in 2 days", r.details)


class HealthOrderTests(unittest.TestCase):
    def test_problems_first_then_alphabetical(self) -> None:
        from ha_ai_brain.domain.lifecycle import review_sort_key

        rows = [
            {"verdict": "healthy", "alias": "Zebra"}, {"verdict": "too_new", "alias": "Mid"},
            {"verdict": "overridden", "alias": "b night"}, {"verdict": "missing", "alias": "Cutoff"},
            {"verdict": "overridden", "alias": "A morning"}, {"verdict": "healthy", "alias": "alpha"},
            {"verdict": "disabled", "alias": "Old"}, {"verdict": "never_fired", "alias": "Idle"},
        ]
        got = [(r["verdict"], r["alias"]) for r in sorted(rows, key=review_sort_key)]
        self.assertEqual([v for v, _ in got], ["missing", "overridden", "overridden", "never_fired", "disabled", "too_new", "healthy", "healthy"])
        self.assertEqual([a for v, a in got if v == "overridden"], ["A morning", "b night"])
        self.assertEqual([a for v, a in got if v == "healthy"], ["alpha", "Zebra"])


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        settings = BrainSettings(
            use_simulator=True, operating_mode=OperatingMode.PERIODIC_BATCH, default_autonomy=AutonomyLevel.COPILOT,
            db_path=str(Path(self._tmp.name) / "t.db"),
        )
        self.o = build_orchestrator(settings)
        states = await self.o.smart_home.get_all_states()
        self.entity = next(eid for eid in states if eid.startswith("light."))

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_draft_create_and_forget(self) -> None:
        entity = self.entity

        async def fake(**_: object) -> dict:
            return {
                "automation": {
                    "alias": "Evening light", "description": "d", "trigger": [{"platform": "time", "at": "20:00:00"}],
                    "action": [{"service": "light.turn_on", "target": {"entity_id": entity}}],
                },
                "explanation": "Turns it on at 8 pm.",
            }

        self.o.llm.generate_json = fake  # type: ignore[method-assign]
        draft = await self.o.draft_automation("Turn the light on at 8 pm every evening")
        self.assertEqual(draft["errors"], [])
        self.assertIn(entity, draft["draft"]["yaml"])

        # the homeowner edits the time before creating it
        edited = draft["draft"]["yaml"].replace("20:00:00", "21:15:00")
        res = await self.o.create_automation_from_yaml(edited, draft["draft"]["automation_id"], "Turn the light on")
        self.assertEqual(res["status"], "created")
        states = await self.o.smart_home.get_all_states()
        self.assertIn(f"automation.{draft['draft']['automation_id']}", states)
        accepted = await self.o.memory.get_accepted_automations()
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].service_data["trigger"][0]["at"], "21:15:00")

        out = await self.o.forget_deployed_automation(draft["draft"]["automation_id"], block=True)
        self.assertTrue(out["blocked"])
        self.assertEqual(await self.o.memory.get_accepted_automations(), [])
        self.assertTrue(await self.o.memory.get_rejected_signatures())
        with self.assertRaises(KeyError):
            await self.o.forget_deployed_automation("nope")

    async def test_draft_warns_about_unlocking_and_refuses_code_services(self) -> None:
        entity = self.entity

        def reply(actions: list) -> object:
            async def fake(**_: object) -> dict:
                return {"automation": {"alias": "X", "description": "d", "trigger": [{"platform": "time", "at": "07:00:00"}], "action": actions}}
            return fake

        self.o.llm.generate_json = reply([{"service": "lock.unlock", "target": {"entity_id": entity}}])  # type: ignore[method-assign]
        res = await self.o.draft_automation("Open the lock at seven every morning")
        self.assertTrue(any("by itself" in w for w in res["warnings"]))
        self.o.llm.generate_json = reply([{"service": "shell_command.reboot"}])  # type: ignore[method-assign]
        res = await self.o.draft_automation("Reboot something every morning")
        self.assertTrue(any("not allowed" in e for e in res["errors"]))
        ok = YAML.replace("light.living", self.entity)
        self.assertEqual((await self.o.create_automation_from_yaml(ok))["status"], "created")  # control: the same YAML is fine
        with self.assertRaises(ValueError):  # the same rule when the homeowner edits the YAML before creating
            await self.o.create_automation_from_yaml(YAML.replace("light.living", self.entity).replace("light.turn_on", "shell_command.reboot"))

    async def test_extra_critical_setting_is_applied_persisted_and_exported(self) -> None:
        await self.o.update_runtime_settings({"critical_openings": " Cover.Driveway ,*carport*;barn,, "})
        self.assertEqual(self.o.guardrails.extra_critical, ("cover.driveway", "*carport*", "barn"))
        self.assertEqual((await self.o.memory.get_ui_preferences())["critical_openings"], "cover.driveway, *carport*, barn")
        again = build_orchestrator(BrainSettings(use_simulator=True, operating_mode=OperatingMode.PERIODIC_BATCH, db_path=str(Path(self._tmp.name) / "t2.db")))  # a fresh orchestrator on another database starts empty...
        self.assertEqual(again.guardrails.extra_critical, ())
        again._apply_ui_preferences_dict(await self.o.memory.get_ui_preferences())  # ...and restores it from the saved preferences
        self.assertEqual(again.guardrails.extra_critical, ("cover.driveway", "*carport*", "barn"))
        self.assertIn("critical_openings", (await self.o.export_bundle())["sections"]["preferences"])

    async def test_unknown_entity_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            await self.o.create_automation_from_yaml(YAML.replace("light.living", "light.does_not_exist"))

    async def test_ai_failure_gives_an_error_not_a_draft(self) -> None:
        async def nothing(**_: object) -> dict:
            return {}

        self.o.llm.generate_json = nothing  # type: ignore[method-assign]
        res = await self.o.draft_automation("Turn the light on at 8 pm")
        self.assertIsNone(res["draft"])
        self.assertTrue(res["errors"])


class AgentPromptPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_forbids_automations_only_for_agents_without_the_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            o = build_orchestrator(BrainSettings(
                use_simulator=True, operating_mode=OperatingMode.PERIODIC_BATCH, default_autonomy=AutonomyLevel.COPILOT,
                db_path=str(Path(tmp) / "p.db"),
            ))
            seen: dict[str, str] = {}
            original = o.llm.generate_json

            async def spy(system_prompt: str, user_prompt: str, **kw):  # type: ignore[no-untyped-def]
                agent = str((kw.get("context_hint") or {}).get("agent_id", ""))
                if "native_automations" in system_prompt:
                    seen[agent] = system_prompt
                return await original(system_prompt=system_prompt, user_prompt=user_prompt, **kw)

            o.llm.generate_json = spy  # type: ignore[method-assign]
            agent = o.registry.get_agent("climate_thermal_agent")
            self.assertIn("automation", agent.controllable_domains)
            await o.run_periodic_batch_analysis(agent_id="climate_thermal_agent", force=True)
            allowed = seen.pop("climate_thermal_agent")
            self.assertIn("CRITICAL RULES FOR NATIVE AUTOMATIONS", allowed)
            self.assertNotIn("NOT PERMITTED", allowed)

            agent.controllable_domains = [d for d in agent.controllable_domains if d != "automation"]
            o.invalidate_context_caches()
            await o.run_periodic_batch_analysis(agent_id="climate_thermal_agent", force=True)
            denied = seen["climate_thermal_agent"]
            self.assertIn("NOT PERMITTED TO CREATE AUTOMATIONS", denied)
            self.assertNotIn("CRITICAL RULES FOR NATIVE AUTOMATIONS", denied)


if __name__ == "__main__":
    unittest.main()
