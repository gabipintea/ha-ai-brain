"""Regression tests for configuration parsing, guardrails, approvals, sandboxing and API hardening."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from ha_ai_brain.adapters.mcp_router import ExtensibleMcpClientAdapter
from ha_ai_brain.adapters.memory_sqlite import SQLiteMemoryAdapter
from ha_ai_brain.adapters.quota_monitor import create_quota_monitor_for_model
from ha_ai_brain.adapters.sandbox_python import PythonSandboxAdapter
from ha_ai_brain.api.app import create_app
from ha_ai_brain.application.graphs.specialized_agent import SpecializedAgentGraph
from ha_ai_brain.config import AutonomyLevel, BrainSettings, FallbackPolicy, OperatingMode, mask_secret
from ha_ai_brain.domain.guardrails import GuardrailDecisionType, GuardrailEngine
from ha_ai_brain.domain.models import ActionIntent, ActionPriority, AgentSpec, EntityState, PendingApproval


def _intent(domain: str, service: str, targets: list[str], **kwargs) -> ActionIntent:
    return ActionIntent(
        agent_id="agent_a",
        domain=domain,
        service=service,
        target_entity_ids=targets,
        cause_category="test",
        rationale="test",
        **kwargs,
    )


def _evaluate(intent: ActionIntent, autonomy=AutonomyLevel.AUTONOMOUS, rejected: set[str] | None = None):
    return GuardrailEngine().evaluate(
        intent=intent,
        autonomy_level=autonomy,
        notifications_enabled=True,
        endorsed_rules={},
        rejected_signatures=rejected,
    )


class TestSettingsFromEnv(unittest.TestCase):
    def test_boolean_and_numeric_env_values_are_parsed_defensively(self) -> None:
        env = {
            "BRAIN_NOTIFICATIONS_ENABLED": "false",
            "BRAIN_USE_SIMULATOR": "1",
            "BRAIN_BATCH_INTERVAL_MINUTES": "not-a-number",
            "BRAIN_BATCH_LOOKBACK_HOURS": "100000",
            "BRAIN_OPERATING_MODE": "bogus",
            "BRAIN_SITE_CONTEXT": "",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = BrainSettings.from_env()
        self.assertFalse(cfg.notifications_enabled)
        self.assertTrue(cfg.use_simulator)
        self.assertEqual(cfg.batch_interval_minutes, 360)
        self.assertEqual(cfg.batch_lookback_hours, 720)
        self.assertEqual(cfg.operating_mode, OperatingMode.HYBRID)
        self.assertIn("Smart property", cfg.site_context)

    def test_public_dict_never_contains_secrets(self) -> None:
        cfg = BrainSettings(llm_api_key="sk-abcdefghijklmnopqrstuvwxyz", ha_token="tok", license_key="PRO-MONTHLY-x")
        public = cfg.public_dict()
        for secret_field in ("llm_api_key", "ha_token", "license_key"):
            self.assertNotIn(secret_field, public)
        self.assertNotIn("abcdefghijklmnopqrstuv", str(public))
        self.assertTrue(public["has_api_key"])
        self.assertEqual(mask_secret("short-key"), "••••••••")


class TestGuardrails(unittest.TestCase):
    def test_arbitrary_code_domains_are_hard_blocked(self) -> None:
        for domain in ("shell_command", "hassio", "python_script"):
            res = _evaluate(_intent(domain, "run", []))
            self.assertEqual(res.decision, GuardrailDecisionType.HARD_BLOCKED, domain)

    def test_rejection_matches_exact_entities_not_substrings(self) -> None:
        rejected = {"sig:agent_a:light.turn_off:light.kitchen"}
        blocked = _evaluate(_intent("light", "turn_off", ["light.kitchen"]), rejected=rejected)
        other = _evaluate(_intent("light", "turn_off", ["light.kitchen_ceiling"]), rejected=rejected)
        self.assertEqual(blocked.decision, GuardrailDecisionType.HARD_BLOCKED)
        self.assertNotEqual(other.decision, GuardrailDecisionType.HARD_BLOCKED)

    def test_closing_a_garage_door_is_not_critical_but_opening_is(self) -> None:
        close = _evaluate(_intent("cover", "close_cover", ["cover.garage_door"]))
        opening = _evaluate(_intent("cover", "open_cover", ["cover.garage_door"]))
        self.assertNotEqual(close.effective_risk.value, "critical")
        self.assertEqual(opening.decision, GuardrailDecisionType.REQUIRE_USER_APPROVAL)


class TestModels(unittest.TestCase):
    def test_non_finite_states_are_not_numeric(self) -> None:
        for raw in ("nan", "inf", "-inf", "unavailable"):
            self.assertIsNone(EntityState(entity_id="sensor.x", state=raw).numeric_value, raw)
        self.assertEqual(EntityState(entity_id="sensor.x", state="21.5").numeric_value, 21.5)

    def test_agent_id_cannot_escape_the_agents_directory(self) -> None:
        base = dict(name="n", specialty="s", description="d")
        for bad in ("../evil", "a/b", "", ".hidden", "x" * 65):
            with self.assertRaises(ValueError):
                AgentSpec(agent_id=bad, **base)
        self.assertEqual(AgentSpec(agent_id="good-agent_1", **base).agent_id, "good-agent_1")


class TestLlmProposalHandling(unittest.TestCase):
    def test_priority_is_capped_and_malformed_outcome_does_not_drop_the_action(self) -> None:
        graph = SpecializedAgentGraph.__new__(SpecializedAgentGraph)
        intents = graph._parse_action_intents(
            raw_actions=[
                {
                    "domain": "light",
                    "service": "turn_off",
                    "target_entity_ids": "light.a",
                    "priority": "LIFE_AND_SECURITY_SAFETY",
                    "expected_outcome": {"monitored_entity_id": "sensor.a", "check_after_minutes": "soon"},
                }
            ],
            agent_id="agent_a",
            default_area_id=None,
        )
        self.assertEqual(len(intents), 1)
        self.assertLessEqual(intents[0].priority, ActionPriority.EQUIPMENT_AND_STRUCTURAL_PROTECTION)
        self.assertIsNone(intents[0].expected_outcome)
        self.assertEqual(intents[0].target_entity_ids, ["light.a"])


class TestQuotaFallbackCompatibility(unittest.TestCase):
    def test_gemini_default_fallbacks_are_not_used_for_other_providers(self) -> None:
        gemini_defaults = ["gemini/gemini-3.8-flash", "gemini/gemini-3.5-flash"]
        monitor = create_quota_monitor_for_model("openai/gpt-4o", api_key="k", fallback_models=gemini_defaults)
        fallbacks = monitor._snapshot.fallback_models
        self.assertTrue(fallbacks)
        self.assertFalse(any("gemini" in m for m in fallbacks))

    def test_openrouter_defaults_keep_vendor_segment(self) -> None:
        monitor = create_quota_monitor_for_model("openrouter/anthropic/claude-3.5-sonnet", api_key="k")
        self.assertIn("google/gemini-2.5-flash", monitor._snapshot.fallback_models)

    def test_auth_errors_do_not_start_a_cooldown(self) -> None:
        monitor = create_quota_monitor_for_model("openai/gpt-4o", api_key="k")
        snap = monitor.record_quota_or_rate_limit_error("openai/gpt-4o", 401, "bad key", {})
        self.assertFalse(snap.quota_exhausted)
        self.assertEqual(snap.cooldown_seconds_remaining, 0)


class TestApprovalsAndMemory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.memory = SQLiteMemoryAdapter(db_path=str(Path(self._tmp.name) / "t.db"))

    async def asyncTearDown(self) -> None:
        self.memory._conn.close()
        self._tmp.cleanup()

    async def test_approval_can_only_be_resolved_once(self) -> None:
        pending = PendingApproval(intent=_intent("light", "turn_off", ["light.a"]), signature="sig:x")
        await self.memory.save_pending_approval(pending)
        first = await self.memory.resolve_pending_approval(pending.approval_id, "approved_once")
        second = await self.memory.resolve_pending_approval(pending.approval_id, "approved_once")
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    async def test_stale_pending_approvals_expire(self) -> None:
        pending = PendingApproval(intent=_intent("light", "turn_off", ["light.a"]), signature="sig:x")
        await self.memory.save_pending_approval(pending)
        self.assertEqual(await self.memory.expire_stale_pending_approvals(max_age_hours=24), [])
        expired = await self.memory.expire_stale_pending_approvals(max_age_hours=-1)
        self.assertEqual(expired, [pending.approval_id])
        self.assertEqual(await self.memory.get_pending_approvals(), [])


class TestSandboxAndMcp(unittest.IsolatedAsyncioTestCase):
    async def test_sandbox_does_not_expose_parent_environment(self) -> None:
        sandbox = PythonSandboxAdapter()
        with patch.dict(os.environ, {"BRAIN_LLM_API_KEY": "super-secret"}):
            result = await sandbox.execute_python("results['signals'] = [{'signal_name': 'ok', 'value': 1}]", {})
        self.assertEqual(result["signals"][0]["signal_name"], "ok")
        self.assertNotIn("super-secret", str(result))

    async def test_sandbox_rejects_imports_and_times_out(self) -> None:
        sandbox = PythonSandboxAdapter()
        blocked = await sandbox.execute_python("import os\nresults['signals'] = []", {})
        self.assertIn("forbidden", blocked["error"].lower())
        slow = await sandbox.execute_python("while True:\n    pass", {}, timeout_seconds=0.5)
        self.assertIn("timed out", slow["error"])

    async def test_mcp_never_fabricates_tool_results(self) -> None:
        mcp = ExtensibleMcpClientAdapter()
        res = await mcp.call_tool("router_network_mcp", "find_device_by_hostname_or_mac", {"hostname": "x"})
        self.assertEqual(res["status"], "unavailable")

        async def handler(args: dict) -> dict:
            return {"status": "found", "hostname": args["hostname"]}

        mcp.register_tool_handler("router_network_mcp", "find_device_by_hostname_or_mac", handler)
        res = await mcp.call_tool("router_network_mcp", "find_device_by_hostname_or_mac", {"hostname": "x"})
        self.assertEqual(res, {"status": "found", "hostname": "x"})


class TestIngressGuard(unittest.IsolatedAsyncioTestCase):
    async def test_non_ingress_clients_are_rejected_inside_the_addon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db"), custom_agents_dir=tmp)
            with patch.dict(os.environ, {"SUPERVISOR_TOKEN": "x"}):
                app = create_app(settings)
            for host, expected in (("172.30.32.2", 200), ("10.9.9.9", 403)):
                transport = httpx.ASGITransport(app=app, client=(host, 1234))
                async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                    self.assertEqual((await client.get("/api/status")).status_code, expected, host)
                    # The watchdog endpoint is always reachable and exposes no data.
                    health = await client.get("/api/health")
                    self.assertEqual(health.json(), {"status": "ok"})
            app.state.orchestrator.memory._conn.close()


if __name__ == "__main__":
    unittest.main()
