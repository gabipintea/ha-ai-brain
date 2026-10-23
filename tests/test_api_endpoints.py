"""Integration tests for FastAPI Control Plane & Home Assistant Ingress API."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import httpx

from ha_ai_brain.api.app import create_app
from ha_ai_brain.config import AutonomyLevel, BrainSettings, OperatingMode


class TestControlPlaneAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()
        db_file = str(Path(self._tmp_dir.name) / "api_test.db")
        settings = BrainSettings(
            use_simulator=True,
            operating_mode=OperatingMode.HYBRID,
            default_autonomy=AutonomyLevel.COPILOT,
            notifications_enabled=True,
            db_path=db_file,
        )
        self.app = create_app(settings=settings)

    async def asyncTearDown(self) -> None:
        self._tmp_dir.cleanup()

    async def test_api_status_simulate_approve_and_batch(self) -> None:
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Dashboard HTML loads
            res_html = await client.get("/")
            self.assertEqual(res_html.status_code, 200)
            self.assertIn("HA AI Brain", res_html.text)

            # 2. Simulate Condensation Risk event
            res_sim = await client.post("/api/events/simulate", json={"scenario": "condensation_risk"})
            self.assertEqual(res_sim.status_code, 200)
            sim_data = res_sim.json()
            self.assertEqual(len(sim_data["run_logs"]), 1)

            # 3. Check status for pending approvals
            res_status = await client.get("/api/status")
            self.assertEqual(res_status.status_code, 200)
            status_data = res_status.json()
            self.assertGreaterEqual(len(status_data["pending_approvals"]), 1)

            # 4. Approve first pending action as repeatable
            first_approval_id = status_data["pending_approvals"][0]["approval_id"]
            res_decide = await client.post(
                f"/api/approvals/{first_approval_id}/decide",
                json={"decision": "approved_repeatable", "human_note": "Approved via API test"},
            )
            self.assertEqual(res_decide.status_code, 200)
            self.assertTrue(res_decide.json()["repeatable_rule_saved"])

            # 5. Trigger Periodic Batch Analysis
            res_batch = await client.post("/api/batch/analyze", json={"agent_id": "climate_thermal_agent"})
            self.assertEqual(res_batch.status_code, 200)
            batch_log = res_batch.json()["run_log"]
            self.assertEqual(batch_log["mode"], "periodic_batch")
            self.assertGreaterEqual(len(batch_log["advisory_insights"]), 1)

            # 6. Verify paginated /api/logs endpoint
            res_logs = await client.get("/api/logs?limit=5&offset=0")
            self.assertEqual(res_logs.status_code, 200)
            logs_data = res_logs.json()
            self.assertGreaterEqual(logs_data["total"], 2)
            self.assertEqual(len(logs_data["logs"]), 2)
            self.assertFalse(logs_data["has_more"])


if __name__ == "__main__":
    unittest.main()
