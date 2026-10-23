"""Verification tests for Live Home Assistant Readiness (Stream Worker, Scheduler, Area Resolution, Subprocess Sandbox)."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from ha_ai_brain.adapters.ha_simulator import SmartHomeSimulatorAdapter
from ha_ai_brain.adapters.ha_websocket_rest import HomeAssistantAdapter
from ha_ai_brain.adapters.llm_litellm import LiteLLMAdapter
from ha_ai_brain.adapters.sandbox_python import PythonSandboxAdapter
from ha_ai_brain.api.app import build_orchestrator
from ha_ai_brain.config import AutonomyLevel, BrainSettings, OperatingMode
from ha_ai_brain.domain.models import EventOrigin, FeedbackPolarity


class TestLiveHomeAssistantReadiness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_file = str(Path(self._tmp_dir.name) / "live_test.db")

    async def asyncTearDown(self) -> None:
        self._tmp_dir.cleanup()

    async def test_1_live_stream_background_worker_processes_events_automatically(self) -> None:
        """Verify that `start_background_workers()` consumes `subscribe_state_changes()` automatically."""
        settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.REALTIME_STREAM,
            default_autonomy=AutonomyLevel.SHADOW,
            db_path=self.db_file,
        )
        orchestrator = build_orchestrator(settings)
        assert isinstance(orchestrator.smart_home, SmartHomeSimulatorAdapter)
        sim: SmartHomeSimulatorAdapter = orchestrator.smart_home

        await orchestrator.start_background_workers()
        try:
            # Emit an event into the simulator's async queue; background worker should pick it up
            sim.emit_simulated_state_change("sensor.master_bedroom_humidity", "70.0")
            await asyncio.sleep(0.35)

            logs = await orchestrator.memory.get_recent_run_logs(limit=5)
            self.assertGreaterEqual(len(logs), 1)
            self.assertEqual(logs[0].execution_results[0]["status"], "shadow_logged")
        finally:
            await orchestrator.stop_background_workers()

    async def test_2_mobile_notification_action_callback_resolves_approval(self) -> None:
        """Verify that tapping Approve & Always Allow on HA Companion App resolves pending approval."""
        settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.HYBRID,
            default_autonomy=AutonomyLevel.COPILOT,
            notifications_enabled=True,
            db_path=self.db_file,
        )
        orchestrator = build_orchestrator(settings)
        assert isinstance(orchestrator.smart_home, SmartHomeSimulatorAdapter)
        sim: SmartHomeSimulatorAdapter = orchestrator.smart_home

        event = sim.emit_simulated_state_change("sensor.master_bedroom_humidity", "69.0")
        await orchestrator.process_state_changed_event(event)

        pending = await orchestrator.memory.get_pending_approvals()
        self.assertGreaterEqual(len(pending), 1)
        target_approval_id = pending[0].approval_id

        # Simulate HA Companion App mobile_app_notification_action callback
        await orchestrator._on_mobile_notification_action(target_approval_id, "approved_repeatable")

        rules = await orchestrator.memory.get_endorsed_rules()
        self.assertIn(pending[0].signature, rules)

    async def test_3_area_registry_and_fallback_resolution(self) -> None:
        """Verify HomeAssistantAdapter resolves area_id from registry map and fallback entity naming."""
        ha = HomeAssistantAdapter(
            base_url="http://homeassistant.local:8123",
            ws_url="ws://homeassistant.local:8123/api/websocket",
            token="dummy_token",
        )
        ha._entity_area_map = {
            "sensor.aqara_01_temp": "kids_bedroom",
            "climate.danfoss_01": "kids_bedroom",
        }

        # 1. Registry-mapped entity
        self.assertEqual(ha._resolve_area_id("sensor.aqara_01_temp", {}), "kids_bedroom")
        # 2. Fallback naming inference when entity is not assigned to an HA area yet
        self.assertEqual(ha._resolve_area_id("sensor.guest_bathroom_humidity", {}), "guest_bathroom")
        self.assertEqual(ha._resolve_area_id("sensor.outdoor_balcony_temperature", {}), "outdoor")

    async def test_4_subprocess_sandbox_blocks_imports_and_dunders(self) -> None:
        """Verify that PythonSandboxAdapter runs in an isolated subprocess and blocks unsafe AST nodes."""
        sandbox = PythonSandboxAdapter()

        # Safe math works
        ok_res = await sandbox.execute_python(
            code="results['signals'] = [{'signal_name': 'test', 'value': round(math.sqrt(16), 1)}]",
            input_variables={},
        )
        self.assertEqual(ok_res["signals"][0]["value"], 4.0)

        # Import statement is blocked by AST validator
        bad_import = await sandbox.execute_python(
            code="import os\nresults['signals'] = []",
            input_variables={},
        )
        self.assertIn("Import statements are forbidden", bad_import.get("error", ""))

        # Dunder attribute access is blocked by AST validator
        bad_dunder = await sandbox.execute_python(
            code="x = ().__class__.__bases__\nresults['signals'] = []",
            input_variables={},
        )
        self.assertIn("dunder", bad_dunder.get("error", ""))

    async def test_5_native_ha_automation_actions_are_not_mistaken_for_human_habits_or_overrides(self) -> None:
        """
        Verify that state changes triggered by a native Home Assistant automation (`context_parent_id`)
        are classified as `EventOrigin.HA_AUTOMATION`, do not trigger re-automation in real-time,
        and are not misclassified as implicit human overrides.
        """
        settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.REALTIME_STREAM,
            default_autonomy=AutonomyLevel.AUTONOMOUS,
            db_path=self.db_file,
        )
        orchestrator = build_orchestrator(settings)
        assert isinstance(orchestrator.smart_home, SmartHomeSimulatorAdapter)
        sim: SmartHomeSimulatorAdapter = orchestrator.smart_home

        # 1. AI controls living room UFH
        ev1 = sim.emit_simulated_state_change("sensor.outdoor_south_illuminance", "48500")
        await orchestrator.process_state_changed_event(ev1)

        # Backdate AI action by 20s so it's inside the override window
        from datetime import timedelta

        orchestrator.triage._recent_ai_actions["climate.living_room_ufh"]["timestamp"] -= timedelta(seconds=20)

        # 2. A native HA automation ("automation.evening_comfort_schedule") triggers with context_id "ctx_native_auto_1"
        orchestrator.triage.register_ha_automation_trigger("ctx_native_auto_1", "automation.evening_comfort_schedule")

        # 3. That native HA automation changes `climate.living_room_ufh` (linked via context_parent_id)
        auto_event = sim.emit_simulated_state_change(
            "climate.living_room_ufh",
            "heat",
            attributes_patch={"temperature": 22.0},
        )
        auto_event.old_state.state = "auto"  # type: ignore[union-attr]
        auto_event.context_parent_id = "ctx_native_auto_1"
        auto_event.context_id = "ctx_child_service_call_1"

        logs = await orchestrator.process_state_changed_event(auto_event)

        # Must be classified as HA_AUTOMATION, ignored for real-time agent wakeup, and NOT logged as human override
        self.assertEqual(auto_event.origin, EventOrigin.HA_AUTOMATION)
        self.assertEqual(auto_event.triggered_by_automation_id, "automation.evening_comfort_schedule")
        self.assertEqual(len(logs), 0)

        feedback = await orchestrator.memory.get_relevant_feedback("climate_thermal_agent")
        self.assertNotIn(FeedbackPolarity.OVERRIDDEN_IMPLICIT, [f.polarity for f in feedback])

    async def test_6_live_mode_uses_unscripted_litellm_adapter(self) -> None:
        """Verify that when `use_simulator=False`, `build_orchestrator` wires pure `LiteLLMAdapter`."""
        live_settings = BrainSettings(
            ha_url="http://192.168.1.50:8123",
            ha_token="real_token",
            use_simulator=False,
            db_path=self.db_file,
        )
        orchestrator = build_orchestrator(live_settings)
        self.assertIsInstance(orchestrator.llm, LiteLLMAdapter)

    async def test_7_provider_quota_monitor_parses_gemini_and_openai_limits_and_cooldown(self) -> None:
        """Verify provider-specific `LLMQuotaMonitorPort` implementations for Gemini and OpenAI/Anthropic."""
        from ha_ai_brain.adapters.quota_monitor import (
            GeminiQuotaMonitorAdapter,
            OpenAIAnthropicHeadersQuotaMonitorAdapter,
        )

        # 1. Google Gemini RPC 429 error parsing (RetryInfo + QuotaFailure) + Fallback Policy
        gemini_mon = GeminiQuotaMonitorAdapter(
            default_model="gemini/gemini-3-flash-preview",
            fallback_models=["gemini/gemini-3.6-flash", "gemini/gemini-3.1-flash-lite"],
            fallback_policy="confirm",
        )
        gemini_mon.record_success(model="gemini-3-flash-preview", prompt_tokens=10000, completion_tokens=2000)

        sample_gemini_429 = """{
          "error": {
            "code": 429,
            "message": "You exceeded your current quota, please check your plan and billing details.\\n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20\\nPlease retry in 42.5s.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
              {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [
                  {
                    "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                    "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                    "quotaValue": "20"
                  }
                ]
              },
              {
                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                "retryDelay": "42s"
              }
            ]
          }
        }"""
        snap = gemini_mon.record_quota_or_rate_limit_error(
            model="gemini-3-flash-preview",
            status_code=429,
            error_body=sample_gemini_429,
        )
        self.assertTrue(snap.quota_exhausted)
        self.assertTrue(snap.awaiting_fallback_confirmation)
        self.assertEqual(snap.available_fallback_models, ["gemini-3.6-flash", "gemini-3.1-flash-lite"])
        self.assertEqual(gemini_mon.select_execution_candidates("gemini-3-flash-preview"), [])
        self.assertEqual(snap.quota_metric, "GenerateRequestsPerDayPerProjectPerModel-FreeTier")
        self.assertEqual(str(snap.quota_limit), "20")
        self.assertGreaterEqual(snap.cooldown_seconds_remaining, 38)
        self.assertGreater(snap.estimated_spend_usd_session, 0.0)

        # User confirms switching to fallback model `gemini-3.6-flash`
        gemini_mon.approve_fallback_model("gemini-3.6-flash")
        self.assertEqual(
            gemini_mon.select_execution_candidates("gemini-3-flash-preview"),
            ["gemini-3.6-flash", "gemini-3.1-flash-lite"],
        )
        snap_after_confirm = await gemini_mon.get_quota_and_usage_snapshot()
        self.assertTrue(snap_after_confirm.using_fallback_model)
        self.assertEqual(snap_after_confirm.active_model, "gemini-3.6-flash")

        # When primary model cooldown expires, it automatically switches back to primary `gemini-3-flash-preview`!
        from datetime import datetime, timedelta, timezone

        gemini_mon._model_cooldowns["gemini-3-flash-preview"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        snap_recovered = await gemini_mon.get_quota_and_usage_snapshot()
        self.assertFalse(snap_recovered.using_fallback_model)
        self.assertEqual(snap_recovered.active_model, "gemini-3-flash-preview")
        self.assertEqual(gemini_mon.select_execution_candidates("gemini-3-flash-preview"), ["gemini-3-flash-preview"])

        # 2. OpenAI / Anthropic HTTP rate-limit header parsing
        oai_mon = OpenAIAnthropicHeadersQuotaMonitorAdapter(provider="openai", default_model="gpt-4o-mini")
        oai_mon.record_success(
            model="gpt-4o-mini",
            prompt_tokens=5000,
            completion_tokens=1000,
            headers={
                "x-ratelimit-limit-requests": "500",
                "x-ratelimit-remaining-requests": "499",
            },
        )
        oai_snap = await oai_mon.get_quota_and_usage_snapshot()
        self.assertFalse(oai_snap.quota_exhausted)
        self.assertEqual(oai_snap.quota_limit, "500")
        self.assertEqual(oai_snap.quota_remaining, "499")

    async def test_8_user_context_notes_persisted_and_injected_into_agents(self) -> None:
        """
        Verify that user-provided context notes (e.g. broken humidifier on Philips Air Purifier)
        are persisted in SQLite and injected into the LangGraph state and effective site context.
        """
        from ha_ai_brain.application.graphs.climate_agent import ClimateAgentGraph
        from ha_ai_brain.domain.models import UserContextNote

        settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.HYBRID,
            default_autonomy=AutonomyLevel.SHADOW,
            db_path=self.db_file,
        )
        orchestrator = build_orchestrator(settings)

        note = UserContextNote(
            content="The humidifier on my Philips Air Purifier is mechanically broken and doesn't work. I use the Philips just to purify air.",
            scope="global",
            related_entities=["humidifier.philips_air_purifier", "fan.philips_air_purifier"],
        )
        await orchestrator.memory.save_user_context_note(note)

        saved_notes = await orchestrator.memory.get_user_context_notes()
        self.assertEqual(len(saved_notes), 1)
        self.assertIn("mechanically broken", saved_notes[0].content)

        composed = ClimateAgentGraph._compose_effective_site_context(
            {
                "site_context": "2-storey house in Tunari",
                "user_context_notes": saved_notes,
            }
        )
        self.assertIn("CRITICAL USER-PROVIDED CONTEXT", composed)
        self.assertIn("mechanically broken", composed)
        self.assertIn("humidifier.philips_air_purifier", composed)

        deleted = await orchestrator.memory.delete_user_context_note(note.note_id)
        self.assertTrue(deleted)
        self.assertEqual(len(await orchestrator.memory.get_user_context_notes()), 0)

    async def test_9_ignore_list_filters_triage_and_batch_states_and_persists_notify_choice(self) -> None:
        """
        Verify that user-managed IgnoredTarget entries completely suppress events in Triage
        and strip matching entities from corroborated context and batch analysis without consuming LLM tokens,
        and that notification_service selection is persisted and enforced.
        """
        from ha_ai_brain.domain.models import IgnoredTarget

        settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.HYBRID,
            default_autonomy=AutonomyLevel.COPILOT,
            notification_service="notify.mobile_app_phone",
            db_path=self.db_file,
        )
        orchestrator = build_orchestrator(settings)
        assert isinstance(orchestrator.smart_home, SmartHomeSimulatorAdapter)
        sim: SmartHomeSimulatorAdapter = orchestrator.smart_home

        # 1. Add ignore pattern for master_bedroom_humidity
        ig = IgnoredTarget(pattern="sensor.master_bedroom_*", reason="Ignore master bedroom sensors")
        await orchestrator.memory.save_ignored_target(ig)
        self.assertEqual(len(await orchestrator.memory.get_ignored_targets()), 1)

        # Emitting an event on an ignored entity must produce 0 agent runs
        ev = sim.emit_simulated_state_change("sensor.master_bedroom_humidity", "75.0")
        logs = await orchestrator.process_state_changed_event(ev)
        self.assertEqual(len(logs), 0)

        # 2. Remove from ignore list -> event now triggers agent run and uses only the chosen notify service
        await orchestrator.memory.delete_ignored_target(ig.ignore_id)
        ev2 = sim.emit_simulated_state_change("sensor.master_bedroom_humidity", "79.0")
        logs2 = await orchestrator.process_state_changed_event(ev2)
        self.assertGreaterEqual(len(logs2), 1)
        notify_calls = [c for c in sim.service_call_log if c["domain"] == "notify"]
        self.assertTrue(all(c["service"] == "mobile_app_phone" for c in notify_calls))


if __name__ == "__main__":
    unittest.main()
