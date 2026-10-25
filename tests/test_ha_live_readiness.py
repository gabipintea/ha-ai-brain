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
            logs = []
            for _ in range(20):
                await asyncio.sleep(0.1)
                logs = await orchestrator.memory.get_recent_run_logs(limit=5)
                if logs:
                    break

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
        self.assertEqual(ha._resolve_area_id("binary_sensor.front_door_contact", {}), "front_door")
        self.assertEqual(ha._resolve_area_id("lock.main_entrance_lock", {}), "main_entrance")
        self.assertEqual(ha._resolve_area_id("sensor.kitchen_fridge_power", {}), "kitchen_fridge")

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

        # Subprocess timeout is killed cleanly without hanging
        timeout_res = await sandbox.execute_python(
            code="x = 0\nwhile True:\n    x += 1\n",
            input_variables={},
            timeout_seconds=0.3,
        )
        self.assertIn("timed out", timeout_res.get("error", ""))

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
        from ha_ai_brain.application.graphs.specialized_agent import ClimateAgentGraph, SpecializedAgentGraph
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

        # Verify cache invalidation triggers immediately without requiring reloads or restarts
        from datetime import datetime, timezone
        from ha_ai_brain.domain.models import ResearchFinding
        orchestrator.agent_graph._cached_findings["test_agent:global"] = (
            datetime.now(timezone.utc),
            [
                ResearchFinding(
                    topic="thermal",
                    principle_summary="old cached finding",
                    recommended_thresholds_or_physics="physics info",
                )
            ]
        )
        self.assertEqual(len(orchestrator.agent_graph._cached_findings), 1)
        orchestrator.invalidate_context_caches()
        self.assertEqual(len(orchestrator.agent_graph._cached_findings), 0)

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

    async def test_10_multi_provider_inflight_fallback_and_recovery(self) -> None:
        """
        Verify that OpenAI, Anthropic, and OpenRouter adapters support unified in-flight fallback:
        1. Quota monitor initializes with provider-specific default fallback chains.
        2. Fast-tier and primary-tier requests both anchor candidate 0 correctly.
        3. When a candidate encounters HTTP 429, LiteLLMAdapter fails over in-flight to the next candidate model.
        4. Cooldown expiration restores candidate 1 automatically.
        5. HTTP 401/403 (invalid key) terminates candidate loop immediately without retrying.
        """
        from datetime import datetime, timedelta, timezone
        from unittest.mock import MagicMock, patch
        from ha_ai_brain.adapters.quota_monitor import OpenAIAnthropicHeadersQuotaMonitorAdapter
        from ha_ai_brain.adapters.llm_litellm import LiteLLMAdapter

        # 1. Test OpenAI candidate rotation & default fallbacks
        oai_mon = OpenAIAnthropicHeadersQuotaMonitorAdapter(provider="openai", default_model="openai/gpt-4o")
        self.assertEqual(oai_mon._snapshot.fallback_models, ["gpt-4o-mini", "gpt-3.5-turbo"])
        # Deep audit requesting primary gpt-4o:
        candidates_deep = oai_mon.select_execution_candidates("openai/gpt-4o")
        self.assertEqual(candidates_deep, ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"])
        # Fast reflex tier requesting gpt-4o-mini:
        candidates_fast = oai_mon.select_execution_candidates("openai/gpt-4o-mini")
        self.assertEqual(candidates_fast, ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"])

        # When gpt-4o-mini hits 429:
        oai_mon.record_quota_or_rate_limit_error(
            model="gpt-4o-mini",
            status_code=429,
            error_body="Rate limit reached for model gpt-4o-mini. Please retry in 15s.",
            headers={"Retry-After": "15"},
        )
        self.assertTrue(oai_mon.is_model_in_cooldown("gpt-4o-mini")[0])
        self.assertFalse(oai_mon.is_model_in_cooldown("gpt-4o")[0])
        # gpt-4o-mini is now in cooldown, candidates fail over to remaining models:
        self.assertEqual(oai_mon.select_execution_candidates("openai/gpt-4o-mini"), ["gpt-4o", "gpt-3.5-turbo"])

        # When gpt-4o-mini cooldown expires:
        oai_mon._model_cooldowns["gpt-4o-mini"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertEqual(oai_mon.select_execution_candidates("openai/gpt-4o-mini"), ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"])

        # 2. Test Anthropic default fallbacks
        anthropic_mon = OpenAIAnthropicHeadersQuotaMonitorAdapter(
            provider="anthropic",
            default_model="anthropic/claude-3-5-sonnet-20241022",
        )
        self.assertIn("claude-3-5-haiku-20241022", anthropic_mon._snapshot.fallback_models)
        self.assertIn("claude-3-haiku-20240307", anthropic_mon._snapshot.fallback_models)

        # 3. Test LiteLLMAdapter in-flight multi-candidate failover
        llm = LiteLLMAdapter(
            model="openai/gpt-4o",
            fast_model="openai/gpt-4o-mini",
            api_key="sk-test-key",
            fallback_policy="auto",
        )

        mock_err_429 = Exception("Rate limit exceeded")
        mock_err_429.status_code = 429
        mock_err_429.llm_provider_response_headers = {"retry-after": "25"}

        mock_success_resp = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = '{"suggested_actions": ["climate.set_temperature"], "target_celsius": 21.5}'
        mock_success_resp.choices = [mock_choice]
        mock_success_resp.usage.prompt_tokens = 250
        mock_success_resp.usage.completion_tokens = 50
        mock_success_resp._response_headers = {"x-ratelimit-remaining-requests": "450"}

        called_models = []

        async def fake_acompletion(**kwargs):
            m = kwargs.get("model")
            called_models.append(m)
            if m == "openai/gpt-4o-mini":
                raise mock_err_429
            return mock_success_resp

        with patch("litellm.acompletion", side_effect=fake_acompletion):
            res = await llm.generate_json(
                system_prompt="Test sys",
                user_prompt="Test user",
                use_fast_tier=True,
                context_hint={"task": "reflex_test"},
            )

        self.assertEqual(res.get("suggested_actions"), ["climate.set_temperature"])
        self.assertEqual(res.get("target_celsius"), 21.5)
        # Verify it attempted candidate 1 first, failed on 429, then succeeded on candidate 2:
        self.assertEqual(called_models, ["openai/gpt-4o-mini", "openai/gpt-4o"])

        # Check quota status recorded both the rate limit on candidate 1 and success on candidate 2:
        snap = await llm.get_quota_status()
        self.assertEqual(snap.requests_rate_limited_session, 1)
        self.assertEqual(snap.requests_succeeded_session, 1)
        self.assertTrue(llm.quota_monitor.is_model_in_cooldown("gpt-4o-mini")[0])

        # 4. Verify HTTP 401 terminates early without rotating candidates
        called_models_401 = []
        mock_err_401 = Exception("Invalid API key")
        mock_err_401.status_code = 401

        async def fake_acompletion_401(**kwargs):
            called_models_401.append(kwargs.get("model"))
            raise mock_err_401

        with patch("litellm.acompletion", side_effect=fake_acompletion_401):
            res_401 = await llm.generate_json(
                system_prompt="Test sys",
                user_prompt="Test user",
                use_fast_tier=False,
                context_hint={"task": "auth_test"},
            )

        self.assertEqual(res_401, {})
        # Should stop after first candidate because 401 is invalid auth:
        self.assertEqual(len(called_models_401), 1)

    def test_11_triage_generic_numeric_sensors_debounce_and_antiflap_no_unbound_error(self) -> None:
        """
        Verify that generic numeric sensors (e.g. PM2.5, upload speed) that are neither
        illuminance nor power do not raise UnboundLocalError for 'last_t' when transitioning states.
        """
        from datetime import datetime, timezone
        from ha_ai_brain.domain.models import StateChangedEvent, EntityState
        from ha_ai_brain.domain.triage import EdgeSignalTriage

        triage = EdgeSignalTriage()
        now = datetime.now(timezone.utc)

        # Initial reading
        ev1 = StateChangedEvent(
            entity_id="sensor.master_bedroom_master_purifier_pm2_5",
            old_state=EntityState(entity_id="sensor.master_bedroom_master_purifier_pm2_5", state="12", attributes={"device_class": "pm25"}),
            new_state=EntityState(entity_id="sensor.master_bedroom_master_purifier_pm2_5", state="18", attributes={"device_class": "pm25"}),
            timestamp=now,
        )
        frames1, _ = triage.evaluate_event(ev1, agents=[], all_states={})
        self.assertIsNotNone(frames1)

        # Second reading on same sensor: triggers prev_num is not None branch
        ev2 = StateChangedEvent(
            entity_id="sensor.master_bedroom_master_purifier_pm2_5",
            old_state=EntityState(entity_id="sensor.master_bedroom_master_purifier_pm2_5", state="18", attributes={"device_class": "pm25"}),
            new_state=EntityState(entity_id="sensor.master_bedroom_master_purifier_pm2_5", state="25", attributes={"device_class": "pm25"}),
            timestamp=now,
        )
        frames2, _ = triage.evaluate_event(ev2, agents=[], all_states={})
        self.assertIsNotNone(frames2)

        # Speed / bandwidth sensor
        ev3 = StateChangedEvent(
            entity_id="sensor.x55_upload_speed",
            old_state=EntityState(entity_id="sensor.x55_upload_speed", state="100.5", attributes={"unit_of_measurement": "kB/s"}),
            new_state=EntityState(entity_id="sensor.x55_upload_speed", state="105.2", attributes={"unit_of_measurement": "kB/s"}),
            timestamp=now,
        )
        frames3, _ = triage.evaluate_event(ev3, agents=[], all_states={})
        self.assertIsNotNone(frames3)

    async def test_12_notify_service_smart_resolution_and_fallback(self) -> None:
        """
        Verify that HomeAssistantNotificationAdapter automatically resolves notify services:
        - 'notify.phone' -> 'notify.mobile_app_phone'
        - Fallbacks to 'notify.notify' on unrecognized targets
        - Catches service errors without raising uncaught exceptions in periodic batch
        """
        from ha_ai_brain.adapters.notification_ha import HomeAssistantNotificationAdapter
        from ha_ai_brain.domain.models import AdvisoryInsight

        sim = SmartHomeSimulatorAdapter()
        # Mock available services
        sim._available_notify_services = [
            "notify.mobile_app_phone",
            "notify.mobile_app_tablet",
            "notify.notify",
        ]

        # 1. User specified notify.phone (missing mobile_app_)
        notif = HomeAssistantNotificationAdapter(smart_home=sim, notify_service="notify.phone")
        domain, service = await notif._resolve_service_name()
        self.assertEqual(domain, "notify")
        self.assertEqual(service, "mobile_app_phone")

        # 2. User specified non-existent device -> falls back to notify.notify
        notif_unknown = HomeAssistantNotificationAdapter(smart_home=sim, notify_service="notify.unknown_tablet")
        d2, s2 = await notif_unknown._resolve_service_name()
        self.assertEqual(d2, "notify")
        self.assertEqual(s2, "notify")

        # 3. Test send_advisory_alert works seamlessly with compact mobile layout & deep-link
        insight = AdvisoryInsight(
            agent_id="climate_thermal_agent",
            category="thermal_insulation",
            title="High Humidity Alert",
            finding_details="Humidity is 74%",
            recommended_human_action="Turn off humidifier",
        )
        await notif.send_advisory_alert(insight)
        self.assertEqual(len(notif.sent_notifications), 1)
        self.assertEqual(sim.service_call_log[-1]["service"], "mobile_app_phone")
        p1 = notif.sent_notifications[-1]["payload"]
        self.assertEqual(p1["title"], "🧠 AI Brain · High Humidity Alert")
        self.assertTrue(p1["message"].startswith("👉 Turn off humidifier"))
        self.assertEqual(p1["data"]["url"], f"/ha_ai_brain#insight-{insight.insight_id}")
        self.assertEqual(p1["data"]["clickAction"], f"/ha_ai_brain#insight-{insight.insight_id}")
        self.assertEqual(p1["data"]["subtitle"], "Thermal Insulation")

        # 4. Test very long title and message are compacted cleanly for mobile lockscreen cards
        long_insight = AdvisoryInsight(
            agent_id="climate_thermal_agent",
            category="excessive_relative_humidity",
            title="Excessive Relative Humidity and Active Humidifier Conflict in Master Suite",
            finding_details=(
                "Sensor telemetry indicates ambient humidity in the Master Suite is between 68% and 74%. "
                "Despite exceeding safe indoor humidity thresholds, the humidifier is actively running at 60% setpoint."
            ),
            recommended_human_action="Set the master purifier humidifier target to 50% or switch it to off when seasonal ambient humidity exceeds 60% RH.",
        )
        await notif.send_advisory_alert(long_insight)
        p2 = notif.sent_notifications[-1]["payload"]
        self.assertLessEqual(len(p2["title"]), 46)
        self.assertTrue(p2["title"].endswith("…"))
        self.assertTrue(p2["message"].startswith("👉 Set the master purifier"))
        self.assertLessEqual(len(p2["message"]), 180)
        self.assertEqual(p2["data"]["url"], f"/ha_ai_brain#insight-{long_insight.insight_id}")
        # 5. Test send_approval_request formatting is compact and actionable with deep-link
        from ha_ai_brain.domain.models import ActionIntent, NativeAutomationProposal, PendingApproval
        app_intent = ActionIntent(
            agent_id="climate_thermal_agent",
            cause_category="thermal_loss_pre_trim",
            domain="climate",
            service="set_temperature",
            target_entity_ids=["climate.master_bedroom_ufh"],
            service_data={"temperature": 21.5},
            rationale="Outdoor temperature plummeted by 4.2°C over the past 2 hours, increasing floor slab thermal dissipation rate significantly.",
        )
        pending = PendingApproval(
            intent=app_intent,
            signature="climate.set_temperature:climate.master_bedroom_ufh",
        )
        await notif.send_approval_request(pending)
        app_payload = notif.sent_notifications[-1]["payload"]
        self.assertEqual(app_payload["title"], "🧠 AI Brain · Approval Needed")
        self.assertTrue(app_payload["message"].startswith("climate.set_temperature → climate.master_bedroom_ufh"))
        self.assertLessEqual(len(app_payload["message"]), 180)
        self.assertEqual(app_payload["data"]["subtitle"], "climate.set_temperature")
        self.assertEqual(app_payload["data"]["url"], f"/ha_ai_brain#approval-{pending.approval_id}")
        self.assertEqual(app_payload["data"]["clickAction"], f"/ha_ai_brain#approval-{pending.approval_id}")
        self.assertEqual(len(app_payload["data"]["actions"]), 4)

        # 6. Test send_approval_request for native automation proposal has human-readable title and deep link
        auto_prop = NativeAutomationProposal(
            alias="Dehumidify on High Humidity",
            description="Turns on exhaust fan when relative humidity exceeds 65%",
            trigger=[{"platform": "numeric_state", "entity_id": "sensor.bedroom_humidity", "above": 65}],
            action=[{"service": "fan.turn_on", "target": {"entity_id": "fan.bedroom_purifier"}}],
        )
        auto_intent = ActionIntent(
            agent_id="climate_thermal_agent",
            domain="automation",
            service="upsert_native_automation",
            target_entity_ids=[f"automation.{auto_prop.automation_id}"],
            service_data=auto_prop.model_dump(),
            cause_category="prevent_condensation",
            rationale="Humidity exceeds 65% for extended periods.",
            native_automation=auto_prop,
        )
        pending_auto = PendingApproval(
            intent=auto_intent,
            signature=f"sig:climate_thermal_agent:automation.upsert_native_automation:automation.{auto_prop.automation_id}",
        )
        await notif.send_approval_request(pending_auto)
        auto_payload = notif.sent_notifications[-1]["payload"]
        self.assertTrue(auto_payload["title"].startswith("🧠 AI Brain · New Automation:"))
        self.assertTrue(auto_payload["message"].startswith("⚡ Create Automation: Dehumidify on High Humidity"))
        self.assertEqual(auto_payload["data"]["url"], f"/ha_ai_brain#approval-{pending_auto.approval_id}")
        self.assertEqual(auto_payload["data"]["clickAction"], f"/ha_ai_brain#approval-{pending_auto.approval_id}")

    def test_13_codebase_zero_personal_entity_leakage(self) -> None:
        """
        Verify that no user-specific device names, personal emails, or proprietary brand strings
        are hardcoded in ha_ai_brain source code.
        """
        import os
        from pathlib import Path

        forbidden_tokens = [
            "gabis_mac",
            "andrada_s_iphone",
            "gabriels_iphone",
            "lenovo_",
            "_energy_returned",
            "_perception",
            "master_ac_",
            "daikin",
        ]
        src_dir = Path(__file__).resolve().parent.parent / "ha_ai_brain" / "src" / "ha_ai_brain"
        self.assertTrue(src_dir.exists())

        for root, _, files in os.walk(src_dir):
            for file in files:
                if file.endswith(".py"):
                    full_p = Path(root) / file
                    content = full_p.read_text(encoding="utf-8")
                    for token in forbidden_tokens:
                        self.assertNotIn(
                            token,
                            content,
                            f"Forbidden personal token '{token}' found in {full_p.name}",
                        )

    def test_14_sqlite_migration_from_v019_without_status_column(self) -> None:
        """
        Verify that booting SQLiteMemoryAdapter on an existing SQLite database from v0.1.9
        (where advisory_insights lacks the 'status' column) seamlessly migrates without OperationalError.
        """
        import sqlite3
        from pathlib import Path
        import tempfile
        from ha_ai_brain.adapters.memory_sqlite import SQLiteMemoryAdapter

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_p = str(Path(tmp_dir) / "legacy_v019.db")
            # Create old schema table without status column
            conn = sqlite3.connect(db_p)
            conn.execute(
                """
                CREATE TABLE advisory_insights (
                    insight_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.commit()
            conn.close()

            # Now instantiate SQLiteMemoryAdapter - must migrate cleanly without OperationalError
            adapter = SQLiteMemoryAdapter(db_path=db_p)
            cur = adapter._conn.cursor()
            cols = {col[1] for col in cur.execute("PRAGMA table_info(advisory_insights)").fetchall()}
            self.assertIn("status", cols)


if __name__ == "__main__":
    unittest.main()
