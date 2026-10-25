"""Tests for Dynamic Home Assistant Service Discovery, Action Normalization, and Automation Repair."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from ha_ai_brain.adapters.ha_simulator import SmartHomeSimulatorAdapter
from ha_ai_brain.api.app import build_orchestrator
from ha_ai_brain.config import AutonomyLevel, BrainSettings, OperatingMode
from ha_ai_brain.domain.models import ActionIntent, NativeAutomationProposal, PendingApproval
from ha_ai_brain.domain.service_resolver import (
    normalize_automation_proposal,
    normalize_single_action,
    resolve_notification_service,
)


class TestServiceResolverAndAutomations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.db_file = str(Path(self._tmp_dir.name) / "service_test.db")

    async def asyncTearDown(self) -> None:
        self._tmp_dir.cleanup()

    def test_1_resolve_notification_service_variations(self) -> None:
        """Verify dynamic matching of notification service targets against discovered services."""
        available = [
            "notify.notify",
            "notify.persistent_notification",
            "notify.mobile_app_user_phone",
            "notify.mobile_app_living_room_tablet",
        ]

        # Exact match
        self.assertEqual(
            resolve_notification_service("notify.mobile_app_user_phone", available),
            "notify.mobile_app_user_phone",
        )

        # Missing mobile_app_ prefix
        self.assertEqual(
            resolve_notification_service("notify.user_phone", available),
            "notify.mobile_app_user_phone",
        )
        self.assertEqual(
            resolve_notification_service("user_phone", available),
            "notify.mobile_app_user_phone",
        )

        # Substring device match
        self.assertEqual(
            resolve_notification_service("notify.tablet", available),
            "notify.mobile_app_living_room_tablet",
        )

        # Completely unknown device falls back to preferred or notify.notify
        self.assertEqual(
            resolve_notification_service(
                "notify.non_existent_watch",
                available,
                preferred_service="notify.mobile_app_user_phone",
            ),
            "notify.mobile_app_user_phone",
        )

        self.assertEqual(
            resolve_notification_service("notify.non_existent_watch", available),
            "notify.notify",
        )

    def test_2_normalize_single_action_and_aliases(self) -> None:
        """Verify action normalization across notification services, domain aliases, and nested structures."""
        services = {
            "notify": ["notify", "mobile_app_user_phone"],
            "switch": ["turn_on", "turn_off", "toggle"],
            "cover": ["open_cover", "close_cover", "set_cover_position"],
        }
        notify_services = ["notify.notify", "notify.mobile_app_user_phone"]

        # Action using 'service' key with alias
        act1 = {"service": "switch.on", "target": {"entity_id": "switch.uv_lamp"}}
        norm1 = normalize_single_action(act1, services, notify_services)
        self.assertEqual(norm1["service"], "switch.turn_on")

        # Action using 'action' key (HA 2024+ syntax) with notification target lacking prefix
        act2 = {"action": "notify.user_phone", "data": {"message": "Alert"}}
        norm2 = normalize_single_action(act2, services, notify_services)
        self.assertEqual(norm2["action"], "notify.mobile_app_user_phone")

        # Nested action in 'choose' sequence
        act3 = {
            "choose": [
                {
                    "conditions": [{"condition": "template", "value_template": "{{ true }}"}],
                    "sequence": [
                        {"service": "cover.close", "target": {"entity_id": "cover.shutter"}},
                        {"service": "notify.user_phone", "data": {"message": "Closed"}},
                    ],
                }
            ]
        }
        norm3 = normalize_single_action(act3, services, notify_services)
        seq = norm3["choose"][0]["sequence"]
        self.assertEqual(seq[0]["service"], "cover.close_cover")
        self.assertEqual(seq[1]["service"], "notify.mobile_app_user_phone")

    def test_3_normalize_automation_proposal_deep(self) -> None:
        """Verify NativeAutomationProposal normalization preserves fields while fixing service names."""
        services = {
            "notify": ["notify", "mobile_app_phone"],
            "switch": ["turn_on", "turn_off"],
        }
        notify_services = ["notify.notify", "notify.mobile_app_phone"]

        prop = NativeAutomationProposal(
            alias="Battery Dropped Alert",
            description="Alerts when sensor drops",
            trigger=[{"platform": "state", "entity_id": "sensor.battery", "to": "unavailable"}],
            action=[
                {"service": "switch.off", "target": {"entity_id": "switch.charger"}},
                {"service": "notify.phone", "data": {"title": "Warning", "message": "Recharge pack"}},
            ],
        )

        norm_prop = normalize_automation_proposal(
            prop,
            available_services=services,
            available_notify_services=notify_services,
            preferred_notify_service="notify.mobile_app_phone",
        )

        self.assertEqual(norm_prop.action[0]["service"], "switch.turn_off")
        self.assertEqual(norm_prop.action[1]["service"], "notify.mobile_app_phone")

    async def test_4_orchestrator_loads_and_repairs_pending_approval_services(self) -> None:
        """
        Verify that existing pending approvals with un-prefixed or aliased services
        are dynamically repaired when queried via get_pending_approvals() and executed cleanly.
        """
        settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.PERIODIC_BATCH,
            default_autonomy=AutonomyLevel.COPILOT,
            db_path=self.db_file,
            notification_service="notify.mobile_app_phone",
        )
        orchestrator = build_orchestrator(settings)
        sim: SmartHomeSimulatorAdapter = orchestrator.smart_home

        # Simulate a proposal created by an older version that stored un-prefixed notify.phone
        unprefixed_prop = NativeAutomationProposal(
            alias="Maintenance Alert",
            description="Alerts user of battery failure",
            trigger=[{"platform": "state", "entity_id": "sensor.blind_wide_battery", "to": "unavailable"}],
            action=[{"service": "notify.phone", "data": {"message": "Battery unavailable"}}],
        )
        intent = ActionIntent(
            agent_id="climate_thermal_agent",
            domain="automation",
            service="upsert_native_automation",
            target_entity_ids=[f"automation.{unprefixed_prop.automation_id}"],
            service_data=unprefixed_prop.model_dump(),
            cause_category="prevent_failure",
            rationale="Battery sensor unavailable",
            native_automation=unprefixed_prop,
        )
        pending = PendingApproval(
            intent=intent,
            signature=f"sig:climate_thermal_agent:automation.upsert_native_automation:{unprefixed_prop.automation_id}",
        )
        await orchestrator.memory.save_pending_approval(pending)

        # 1. Fetch pending approvals through orchestrator: should normalize in-memory for UI
        loaded = await orchestrator.get_pending_approvals()
        self.assertEqual(len(loaded), 1)
        self.assertIsNotNone(loaded[0].intent.native_automation)
        self.assertEqual(
            loaded[0].intent.native_automation.action[0]["service"],
            "notify.mobile_app_phone",
        )

        # 2. Approve the proposal: orchestrator._execute_intent should upsert with normalized service into HA
        res = await orchestrator.handle_approval_decision(
            approval_id=pending.approval_id,
            decision="approved_once",
        )
        self.assertEqual(res["status"], "approved_once")

        created = sim.created_automations
        self.assertIn(unprefixed_prop.automation_id, created)
        ha_upserted = created[unprefixed_prop.automation_id]
        self.assertEqual(ha_upserted.action[0]["service"], "notify.mobile_app_phone")

    async def test_5_accepted_and_pending_automations_prevent_duplicates(self) -> None:
        """
        Verify that once an automation is approved and deployed:
        1. It is saved in memory as an accepted automation with extracted target entities.
        2. HA state simulator registers automation entity.
        3. Subsequent batch analyses do not propose duplicate automations for the same devices.
        4. In-flight pending proposals for the same devices are suppressed.
        """
        settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.PERIODIC_BATCH,
            default_autonomy=AutonomyLevel.COPILOT,
            db_path=self.db_file,
            notification_service="notify.mobile_app_phone",
        )
        orchestrator = build_orchestrator(settings)
        sim: SmartHomeSimulatorAdapter = orchestrator.smart_home

        # 1. First batch run proposes automations
        log1 = await orchestrator.run_periodic_batch_analysis(agent_id="climate_thermal_agent")
        pending1 = await orchestrator.get_pending_approvals()
        self.assertGreaterEqual(len(pending1), 1)

        auto_pending = [p for p in pending1 if p.intent.domain == "automation"]
        self.assertGreaterEqual(len(auto_pending), 1)
        first_auto = auto_pending[0]

        # Verify physical target entities were extracted
        self.assertGreaterEqual(len(first_auto.intent.target_entity_ids), 2)

        # 2. Approve the first automation
        res_app = await orchestrator.handle_approval_decision(
            approval_id=first_auto.approval_id,
            decision="approved_once",
        )
        self.assertEqual(res_app["status"], "approved_once")

        # Verify accepted automations stored in SQLite memory
        accepted = await orchestrator.memory.get_accepted_automations()
        self.assertEqual(len(accepted), 1)

        # Verify HA state simulator has the automation registered as an entity
        states = await sim.get_all_states()
        self.assertIn(f"automation.{first_auto.intent.native_automation.automation_id}", states)

        # 3. Second batch run: should NOT generate a duplicate automation for the same devices
        log2 = await orchestrator.run_periodic_batch_analysis(agent_id="climate_thermal_agent")
        pending2 = await orchestrator.get_pending_approvals()

        # Any new proposals in pending2 must not duplicate the accepted automation
        for p in pending2:
            if p.intent.domain == "automation":
                self.assertNotEqual(
                    p.intent.native_automation.alias,
                    first_auto.intent.native_automation.alias,
                )
