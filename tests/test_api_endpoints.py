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
            # 1. Dashboard HTML loads & JavaScript syntax is valid
            res_html = await client.get("/")
            self.assertEqual(res_html.status_code, 200)
            self.assertIn("HA AI Brain", res_html.text)

            import re, shutil, subprocess
            script_match = re.search(r"<script>(.*?)</script>", res_html.text, re.DOTALL)
            self.assertIsNotNone(script_match)
            if shutil.which("node"):
                node_check = subprocess.run(
                    ["node", "--check"],
                    input=script_match.group(1).encode("utf-8"),
                    capture_output=True,
                )
                self.assertEqual(node_check.returncode, 0, f"JS Syntax Error: {node_check.stderr.decode('utf-8', errors='replace')}")

            # 2. Simulate Condensation Risk event
            res_sim = await client.post("/api/events/simulate", json={"scenario": "condensation_risk"})
            self.assertEqual(res_sim.status_code, 200)
            sim_data = res_sim.json()
            self.assertEqual(len(sim_data["run_logs"]), 1)

            # 3. Check status for pending approvals & scheduled batch time
            res_status = await client.get("/api/status")
            self.assertEqual(res_status.status_code, 200)
            status_data = res_status.json()
            self.assertIn("next_batch_run_at", status_data)
            self.assertIsNotNone(status_data["next_batch_run_at"])
            self.assertGreaterEqual(len(status_data["pending_approvals"]), 1)

            # 4. Approve first pending action as repeatable
            first_approval_id = status_data["pending_approvals"][0]["approval_id"]
            res_decide = await client.post(
                f"/api/approvals/{first_approval_id}/decide",
                json={"decision": "approved_repeatable", "human_note": "Approved via API test"},
            )
            self.assertEqual(res_decide.status_code, 200)
            self.assertTrue(res_decide.json()["repeatable_rule_saved"])

            # Verify approval status is tracked and returned in /api/status
            status_after_decide = (await client.get("/api/status")).json()
            self.assertIn("approval_statuses", status_after_decide)
            self.assertEqual(status_after_decide["approval_statuses"].get(first_approval_id), "approved_repeatable")

            # 4b. Revoke the endorsed rule; it must disappear and a second revoke must 404
            rules = (await client.get("/api/status")).json()["endorsed_rules"]
            self.assertGreaterEqual(len(rules), 1)
            sig = next(iter(rules))
            res_revoke = await client.delete("/api/rules", params={"signature": sig})
            self.assertEqual(res_revoke.status_code, 200)
            self.assertNotIn(sig, (await client.get("/api/status")).json()["endorsed_rules"])
            res_again = await client.delete("/api/rules", params={"signature": sig})
            self.assertEqual(res_again.status_code, 404)

            # 4c. Reject a new suggestion, list it, then unblock it
            await client.post("/api/events/simulate", json={"scenario": "solar_ufh_gain"})
            pend = (await client.get("/api/status")).json()["pending_approvals"]
            self.assertGreaterEqual(len(pend), 1, "solar scenario should leave a pending approval to reject")
            if pend:
                await client.post(
                    f"/api/approvals/{pend[0]['approval_id']}/decide",
                    json={"decision": "rejected", "human_note": ""},
                )
                rej = (await client.get("/api/status")).json()["rejected_suggestions"]
                self.assertGreaterEqual(len(rej), 1)
                rsig = rej[0]["action_signature"]
                self.assertEqual((await client.delete("/api/rejected", params={"signature": rsig})).status_code, 200)
                after = (await client.get("/api/status")).json()["rejected_suggestions"]
                self.assertNotIn(rsig, [e["action_signature"] for e in after])
                self.assertEqual((await client.delete("/api/rejected", params={"signature": rsig})).status_code, 404)

            # 5. Trigger Periodic Batch Analysis (single agent and all agents with lookback)
            res_batch = await client.post("/api/batch/analyze", json={"agent_id": "climate_thermal_agent", "lookback_hours": 24})
            self.assertEqual(res_batch.status_code, 200)
            batch_log = res_batch.json()["run_log"]
            self.assertEqual(batch_log["mode"], "periodic_batch")
            self.assertGreaterEqual(len(batch_log["advisory_insights"]), 1)

            # 5b. Trigger batch across all registered agents
            res_batch_all = await client.post("/api/batch/analyze", json={"agent_id": "all", "lookback_hours": 48})
            self.assertEqual(res_batch_all.status_code, 200)
            all_batch_data = res_batch_all.json()
            self.assertEqual(all_batch_data["status"], "completed")
            self.assertGreaterEqual(all_batch_data["agents_analyzed"], 4)
            self.assertEqual(len(all_batch_data["run_logs"]), all_batch_data["agents_analyzed"])

            # 6. Verify paginated /api/logs endpoint
            res_logs = await client.get("/api/logs?limit=5&offset=0")
            self.assertEqual(res_logs.status_code, 200)
            logs_data = res_logs.json()
            self.assertGreaterEqual(logs_data["total"], 2)
            self.assertEqual(len(logs_data["logs"]), min(5, logs_data["total"]))
            self.assertEqual(logs_data["has_more"], logs_data["total"] > 5)

            # 7. Test AI Provider & Model live reconfiguration
            res_set = await client.post("/api/settings", json={
                "llm_model": "openai/gpt-4o",
                "llm_fast_model": "openai/gpt-4o-mini",
                "llm_api_key": "sk-1234567890abcdef1234",
                "site_context": "Test property with underfloor heating.",
            })
            self.assertEqual(res_set.status_code, 200)
            st_data = (await client.get("/api/status")).json()
            self.assertEqual(st_data["settings"]["llm_model"], "openai/gpt-4o")
            self.assertEqual(st_data["settings"]["site_context"], "Test property with underfloor heating.")
            self.assertTrue(st_data["settings"]["has_api_key"])
            self.assertTrue(st_data["settings"]["masked_api_key"].startswith("sk-1"))
            self.assertTrue(st_data["settings"]["masked_api_key"].endswith("1234"))
            self.assertNotIn("sk-1234567890abcdef1234", str(st_data))

            # 8. Test Dismissing Proposals without Rejection
            await client.post("/api/events/simulate", json={"scenario": "condensation_risk"})
            p_list = (await client.get("/api/status")).json()["pending_approvals"]
            self.assertGreaterEqual(len(p_list), 1)
            target_aid = p_list[0]["approval_id"]
            # Dismiss it
            res_dis = await client.post(f"/api/approvals/{target_aid}/decide", json={"decision": "dismissed"})
            self.assertEqual(res_dis.status_code, 200)
            self.assertEqual(res_dis.json()["status"], "dismissed")
            # Verify not pending and not in rejected list
            cur_status = (await client.get("/api/status")).json()
            self.assertNotIn(target_aid, [p["approval_id"] for p in cur_status["pending_approvals"]])
            self.assertNotIn(p_list[0]["signature"], [r["action_signature"] for r in cur_status["rejected_suggestions"]])

            # Test dismiss-all endpoint
            await client.post("/api/events/simulate", json={"scenario": "condensation_risk"})
            res_dis_all = await client.post("/api/approvals/dismiss-all")
            self.assertEqual(res_dis_all.status_code, 200)
            cur_pend = (await client.get("/api/status")).json()["pending_approvals"]
            self.assertEqual(len(cur_pend), 0)

            # 9. Test Insight Lifecycle: List, Dismiss, Reject with Note, Suppression, and Deletion
            res_ins = await client.get("/api/insights")
            self.assertEqual(res_ins.status_code, 200)
            ins_data = res_ins.json()
            self.assertGreaterEqual(len(ins_data["insights"]), 1)
            target_ins = ins_data["insights"][0]
            target_ins_id = target_ins["insight_id"]
            target_title = target_ins["title"]

            # 9a. Reject an insight with a custom human reason note
            res_rej_ins = await client.post(
                f"/api/insights/{target_ins_id}/reject",
                json={"reason": "I do not want advice about this area"},
            )
            self.assertEqual(res_rej_ins.status_code, 200)
            self.assertEqual(res_rej_ins.json()["insight"]["status"], "rejected")

            # Verify it shows up in rejected_insights and is excluded from active advisory_insights
            status_after_rej = (await client.get("/api/status")).json()
            self.assertNotIn(target_ins_id, [i["insight_id"] for i in status_after_rej["advisory_insights"]])
            rej_list = status_after_rej["rejected_insights"]
            self.assertEqual(len(rej_list), 1)
            self.assertEqual(rej_list[0]["rejection_reason"], "I do not want advice about this area")

            # 9b. Verify subsequent batch analysis suppresses the rejected insight
            res_batch_suppress = await client.post("/api/batch/analyze", json={"agent_id": "climate_thermal_agent", "lookback_hours": 24})
            self.assertEqual(res_batch_suppress.status_code, 200)
            batch_log_suppressed = res_batch_suppress.json()["run_log"]
            suppressed_titles = [i["title"] for i in batch_log_suppressed.get("advisory_insights", [])]
            self.assertNotIn(target_title, suppressed_titles)

            # 9c. Unblock the rejected insight
            res_unblock_ins = await client.delete(f"/api/insights/rejected/{target_ins_id}")
            self.assertEqual(res_unblock_ins.status_code, 200)
            status_after_unblock = (await client.get("/api/status")).json()
            self.assertEqual(len(status_after_unblock["rejected_insights"]), 0)

            # 9d. Dismiss all insights
            res_dis_ins_all = await client.post("/api/insights/dismiss_all")
            self.assertEqual(res_dis_ins_all.status_code, 200)
            status_after_dis = (await client.get("/api/status")).json()
            self.assertEqual(len(status_after_dis["advisory_insights"]), 0)

            # 9e. Clear all logs to free storage
            res_clear_logs = await client.delete("/api/logs")
            self.assertEqual(res_clear_logs.status_code, 200)
            status_after_clear = (await client.get("/api/status")).json()
            self.assertEqual(status_after_clear["total_logs_count"], 0)

            # 10. Test Bidirectional Deep-Linking between Run Logs & Approvals, Single Log Fetching
            res_sim_link = await client.post("/api/events/simulate", json={"entity_id": "sensor.master_bedroom_humidity", "new_value": "71.5"})
            self.assertEqual(res_sim_link.status_code, 200)
            sim_logs = res_sim_link.json()["run_logs"]
            self.assertEqual(len(sim_logs), 1)
            target_run_id = sim_logs[0]["run_id"]

            # Verify pending approval carries run_id
            st_link = (await client.get("/api/status")).json()
            self.assertGreaterEqual(len(st_link["pending_approvals"]), 1)
            matched_p = [p for p in st_link["pending_approvals"] if p.get("run_id") == target_run_id]
            self.assertGreaterEqual(len(matched_p), 1)
            link_aid = matched_p[0]["approval_id"]

            # Verify single log fetch by run_id
            res_single_log = await client.get(f"/api/logs/{target_run_id}")
            self.assertEqual(res_single_log.status_code, 200)
            fetched_log = res_single_log.json()["log"]
            self.assertEqual(fetched_log["run_id"], target_run_id)
            # Verify intent inside run_log carries the approval_id for direct linking
            intents_with_app = [i for i in fetched_log["proposed_intents"] if i.get("approval_id") == link_aid]
            self.assertEqual(len(intents_with_app), 1)

            # Verify 404 on nonexistent log
            res_404_log = await client.get("/api/logs/nonexistent_run_9999")
            self.assertEqual(res_404_log.status_code, 404)

            # Verify batch analysis links insights to run_id
            res_batch_link = await client.post("/api/batch/analyze", json={"agent_id": "climate_thermal_agent", "lookback_hours": 12})
            self.assertEqual(res_batch_link.status_code, 200)
            b_log = res_batch_link.json()["run_log"]
            b_run_id = b_log["run_id"]
            res_ins_after = (await client.get("/api/insights")).json()
            b_insights = [i for i in res_ins_after["insights"] if i.get("run_id") == b_run_id]
            self.assertGreaterEqual(len(b_insights), 1)

            # Verify dashboard HTML includes highlight-pulse and deep-linking methods
            dash_html = (await client.get("/")).text
            self.assertIn("highlight-pulse", dash_html)
            self.assertIn("jumpToElement", dash_html)
            self.assertIn("handleHashNav", dash_html)
            self.assertIn("Create Native Automation:", dash_html)

            # Verify scrollable list containers and count badges on Memory & Rules
            self.assertIn('id="rulesList" class="scroll"', dash_html)
            self.assertIn('id="rejectedList" class="scroll"', dash_html)
            self.assertIn('id="rejectedInsightsList" class="scroll"', dash_html)
            self.assertIn('id="contextNotesList" class="scroll"', dash_html)
            self.assertIn('id="ignoredTargetsList" class="scroll"', dash_html)
            self.assertIn('id="rulesCountBadge"', dash_html)
            self.assertIn('id="rejectedCountBadge"', dash_html)
            self.assertIn('id="rejectedInsightsCountBadge"', dash_html)
            self.assertIn('id="contextNotesCountBadge"', dash_html)
            self.assertIn('id="ignoredCountBadge"', dash_html)

            # Verify ignored list is located in pane-memory and not in pane-settings
            pane_memory = dash_html.split('id="pane-memory"')[1].split('id="pane-settings"')[0]
            self.assertIn('id="ignoredTargetsList"', pane_memory)
            pane_settings = dash_html.split('id="pane-settings"')[1].split('</div>\n\n  <script>')[0] if '</div>\n\n  <script>' in dash_html else dash_html.split('id="pane-settings"')[1]
            self.assertNotIn('id="ignoredTargetsList"', pane_settings)


if __name__ == "__main__":
    unittest.main()
