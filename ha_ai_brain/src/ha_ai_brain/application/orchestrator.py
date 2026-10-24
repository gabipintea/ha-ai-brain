"""Central Brain Orchestrator coordinating Triage, LangGraph Agents, Arbiter, Guardrails, and Memory."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
import uuid

from ha_ai_brain.application.agent_registry import AgentRegistry
from ha_ai_brain.application.graphs.climate_agent import ClimateAgentGraph, ClimateGraphState
from ha_ai_brain.application.graphs.subagents import ComputationSubAgent, ResearchSubAgent
from ha_ai_brain.config import BrainSettings, OperatingMode
from ha_ai_brain.domain.arbiter import ConflictArbiter
from ha_ai_brain.domain.guardrails import GuardrailDecisionType, GuardrailEngine
from ha_ai_brain.domain.models import (
    ActionIntent,
    AgentRunLog,
    ApprovalRule,
    FeedbackEpisode,
    FeedbackPolarity,
    PendingApproval,
    SemanticEventFrame,
    StateChangedEvent,
    UserContextNote,
)
from ha_ai_brain.domain.triage import EdgeSignalTriage
from ha_ai_brain.ports.billing import LicensePort
from ha_ai_brain.ports.llm import LLMProviderPort
from ha_ai_brain.ports.mcp import McpClientPort
from ha_ai_brain.ports.memory import MemoryStorePort
from ha_ai_brain.ports.notification import NotificationPort
from ha_ai_brain.ports.research import ResearchPort
from ha_ai_brain.ports.sandbox import ComputationSandboxPort
from ha_ai_brain.ports.smart_home import SmartHomePort

logger = logging.getLogger(__name__)


class BrainOrchestrator:
    """
    Application service wiring together the Hexagonal Domain Core and Outbound/Inbound Ports.
    Supports both Real-Time Event Stream processing and Periodic/On-Demand Batch Analysis.
    """

    def __init__(
        self,
        settings: BrainSettings,
        smart_home: SmartHomePort,
        llm: LLMProviderPort,
        sandbox: ComputationSandboxPort,
        research: ResearchPort,
        memory: MemoryStorePort,
        notification: NotificationPort,
        mcp_client: McpClientPort,
        license_port: LicensePort,
        registry: AgentRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.smart_home = smart_home
        self.llm = llm
        self.sandbox = sandbox
        self.research = research
        self.memory = memory
        self.notification = notification
        self.mcp_client = mcp_client
        self.license_port = license_port

        self.registry = registry or AgentRegistry(custom_agents_dir=settings.custom_agents_dir)
        self.triage = EdgeSignalTriage(manual_override_cooldown_seconds=settings.manual_override_cooldown_seconds)
        self.arbiter = ConflictArbiter(triage=self.triage)
        self.guardrails = GuardrailEngine()

        self.research_subagent = ResearchSubAgent(llm=llm, research_port=research)
        self.computation_subagent = ComputationSubAgent(llm=llm, sandbox=sandbox)
        self.agent_graph = ClimateAgentGraph(
            smart_home=smart_home,
            llm=llm,
            memory=memory,
            research_subagent=self.research_subagent,
            computation_subagent=self.computation_subagent,
        )

        # Wire mobile push notification action callback if supported by the smart_home adapter
        if hasattr(self.smart_home, "set_notification_action_handler"):
            self.smart_home.set_notification_action_handler(self._on_mobile_notification_action)

        self._background_tasks: list[asyncio.Task[Any]] = []
        self._running = False
        self._cached_states: dict[str, Any] = {}
        if hasattr(self.memory, "get_ui_preferences_sync"):
            self._apply_ui_preferences_dict(self.memory.get_ui_preferences_sync())

    async def start_background_workers(self) -> None:
        """Start the live HA WebSocket stream listener and the Periodic Batch scheduler."""
        if self._running:
            return
        await self._restore_persisted_ui_preferences()
        self._running = True
        self._background_tasks = [
            asyncio.create_task(self._event_stream_worker_loop(), name="ha_ws_event_stream_worker"),
            asyncio.create_task(self._periodic_batch_scheduler_loop(), name="ha_periodic_batch_scheduler"),
        ]
        logger.info(
            "Started HA AI Brain background workers (mode=%s, autonomy=%s, batch_interval=%dm)",
            self.settings.operating_mode.value,
            self.settings.default_autonomy.value,
            self.settings.batch_interval_minutes,
        )

    async def stop_background_workers(self) -> None:
        """Gracefully stop background stream and scheduler tasks."""
        self._running = False
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

    def _apply_ui_preferences_dict(self, prefs: dict[str, str]) -> None:
        """Apply persisted UI preferences to live settings and adapters."""
        from ha_ai_brain.config import AutonomyLevel, FallbackPolicy, OperatingMode

        if "operating_mode" in prefs:
            try:
                self.settings.operating_mode = OperatingMode(prefs["operating_mode"])
            except ValueError:
                pass
        if "default_autonomy" in prefs:
            try:
                self.settings.default_autonomy = AutonomyLevel(prefs["default_autonomy"])
            except ValueError:
                pass
        if "llm_fallback_policy" in prefs:
            try:
                self.settings.llm_fallback_policy = FallbackPolicy(prefs["llm_fallback_policy"])
                if hasattr(self.llm, "set_fallback_policy"):
                    self.llm.set_fallback_policy(self.settings.llm_fallback_policy.value)
            except ValueError:
                pass
        if "notification_service" in prefs and prefs["notification_service"]:
            self.settings.notification_service = prefs["notification_service"]
            if hasattr(self.notification, "notify_service"):
                self.notification.notify_service = prefs["notification_service"]
        if "notifications_enabled" in prefs:
            self.settings.notifications_enabled = prefs["notifications_enabled"].lower() == "true"
        if "site_context" in prefs and prefs["site_context"]:
            self.settings.site_context = prefs["site_context"]
        llm_changed = False
        new_model = self.settings.llm_model
        new_fast = self.settings.llm_fast_model
        new_key = self.settings.llm_api_key
        if "llm_model" in prefs and prefs["llm_model"]:
            new_model = prefs["llm_model"]
            self.settings.llm_model = new_model
            llm_changed = True
        if "llm_fast_model" in prefs and prefs["llm_fast_model"]:
            new_fast = prefs["llm_fast_model"]
            self.settings.llm_fast_model = new_fast
            llm_changed = True
        if "llm_api_key" in prefs and prefs["llm_api_key"]:
            new_key = prefs["llm_api_key"]
            self.settings.llm_api_key = new_key
            llm_changed = True
        if llm_changed and hasattr(self.llm, "reconfigure"):
            self.llm.reconfigure(model=new_model, fast_model=new_fast, api_key=new_key)

    async def _restore_persisted_ui_preferences(self) -> None:
        """Load user preferences saved from the Web UI so restarts never reset user choices."""
        prefs = await self.memory.get_ui_preferences()
        self._apply_ui_preferences_dict(prefs)

    async def _event_stream_worker_loop(self) -> None:
        """Continuously subscribe to Home Assistant WebSocket state_changed events with auto-reconnect."""
        backoff = 2.0
        while self._running:
            try:
                async for event in self.smart_home.subscribe_state_changes():
                    if not self._running:
                        break
                    backoff = 2.0
                    try:
                        await self.process_state_changed_event(event)
                    except Exception as exc:
                        logger.error("Error processing state_changed event for %s: %s", event.entity_id, exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("HA WebSocket stream disconnected (%s); reconnecting in %.1fs...", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    async def _periodic_batch_scheduler_loop(self) -> None:
        """Run periodic batch analysis on startup (if API key configured) and then every `batch_interval_minutes`."""
        first_run = True
        while self._running:
            try:
                if first_run and self.settings.llm_api_key and not self.settings.use_simulator:
                    first_run = False
                    await asyncio.sleep(3.0)
                else:
                    first_run = False
                    interval_seconds = max(60, self.settings.batch_interval_minutes * 60)
                    await asyncio.sleep(interval_seconds)
                if not self._running:
                    break
                if self.settings.operating_mode in (OperatingMode.PERIODIC_BATCH, OperatingMode.HYBRID):
                    logger.info("Running Periodic Batch Analysis with %s...", self.settings.llm_model)
                    await self.run_periodic_batch_analysis(agent_id="climate_thermal_agent")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in periodic batch scheduler: %s", exc)

    async def _on_mobile_notification_action(self, approval_id: str, decision: str) -> None:
        """Callback triggered when a user taps Approve Once / Always Allow / Reject on their phone."""
        try:
            await self.handle_approval_decision(
                approval_id=approval_id,
                decision=decision,
                human_note="Resolved via Home Assistant Companion App notification button.",
            )
        except Exception as exc:
            logger.warning("Failed handling mobile notification action (%s, %s): %s", approval_id, decision, exc)

    async def process_state_changed_event(self, event: StateChangedEvent) -> list[AgentRunLog]:
        """
        Handle a single live `state_changed` event from Home Assistant:
        1. Triage (causal loop filter, implicit human override detection, deadband filter, context corroboration).
        2. If significant and operating mode allows real-time reaction, invoke matching LangGraph agents.
        """
        if not self._cached_states or hasattr(self.smart_home, "_service_call_log"):
            self._cached_states = await self.smart_home.get_all_states()
        self._cached_states[event.entity_id] = event.new_state
        all_states = self._cached_states

        ignored_targets = await self.memory.get_ignored_targets()
        if ignored_targets and any(t.matches(event.entity_id) for t in ignored_targets):
            return []

        # 4. Deadband / Significance Filtering
        frames, implicit_feedback = self.triage.evaluate_event(
            event=event,
            all_states=all_states,
            agents=self.registry.list_agents(),
            ignored_targets=ignored_targets,
        )

        old_val = event.old_state.state if event.old_state else "?"
        if frames:
            logger.info(
                "[LIVE EVENT -> SIGNIFICANT] %s (area=%s, origin=%s): '%s' -> '%s' | Routed to: %s",
                event.entity_id,
                event.new_state.area_id or "unassigned",
                event.origin.value,
                old_val,
                event.new_state.state,
                [f.target_agent_id for f in frames],
            )
        else:
            logger.info(
                "[LIVE EVENT -> FILTERED] %s (area=%s, origin=%s): '%s' -> '%s'",
                event.entity_id,
                event.new_state.area_id or "unassigned",
                event.origin.value,
                old_val,
                event.new_state.state,
            )

        if implicit_feedback is not None:
            await self.memory.save_feedback(implicit_feedback)

        if self.settings.operating_mode == OperatingMode.PERIODIC_BATCH:
            # In pure Periodic Batch mode, live events are not sent to LLM agents
            return []

        run_logs: list[AgentRunLog] = []
        for frame in frames:
            log = await self._run_agent_for_frame(frame)
            if log is not None:
                run_logs.append(log)
        return run_logs

    async def _run_agent_for_frame(self, frame: SemanticEventFrame) -> AgentRunLog | None:
        agent_spec = self.registry.get_agent(frame.target_agent_id)
        if not agent_spec or not agent_spec.enabled:
            return None

        quota_status = await self.llm.get_quota_status()
        if quota_status.quota_exhausted and quota_status.cooldown_seconds_remaining > 0:
            logger.warning(
                "Skipping agent %s for '%s' — AI model quota cooldown active (%ds remaining).",
                agent_spec.agent_id,
                frame.significance_reason,
                quota_status.cooldown_seconds_remaining,
            )
            return None

        initial_state: ClimateGraphState = {
            "agent_spec": agent_spec,
            "site_context": self.settings.site_context,
            "mode": "realtime_stream",
            "area_id": frame.area_id,
            "trigger_summary": frame.significance_reason,
            "corroborated_states": frame.corroborated_states,
        }

        final_state = await self.agent_graph.ainvoke(initial_state)
        intents = final_state.get("proposed_intents", [])
        exec_results = await self._evaluate_and_dispatch_intents(intents)

        run_log = AgentRunLog(
            agent_id=agent_spec.agent_id,
            mode="realtime_stream",
            trigger_summary=frame.significance_reason,
            research_findings=final_state.get("research_findings", []),
            derived_signals=final_state.get("derived_signals", []),
            proposed_intents=intents,
            advisory_insights=final_state.get("advisory_insights", []),
            execution_results=exec_results,
        )
        self._log_agent_run_summary(run_log)
        await self.memory.save_run_log(run_log)
        return run_log

    def _log_agent_run_summary(self, run_log: AgentRunLog) -> None:
        logger.info(
            "=== AGENT RUN COMPLETE [%s | mode=%s] === Trigger: %s",
            run_log.agent_id,
            run_log.mode,
            run_log.trigger_summary,
        )
        for rf in run_log.research_findings:
            logger.info("  [Research Sub-Agent] Topic: %s | %s", rf.topic, rf.principle_summary[:180])
        for ds in run_log.derived_signals:
            logger.info(
                "  [Computation Sub-Agent] Signal: %s = %s %s | %s",
                ds.signal_name,
                ds.value,
                ds.unit,
                ds.interpretation,
            )
        for ins in run_log.advisory_insights:
            logger.info("  [Advisory Insight] %s -> %s", ins.title, ins.recommended_human_action)
        for intent, res in zip(run_log.proposed_intents, run_log.execution_results):
            logger.info(
                "  [Proposed Action] %s.%s on %s (status=%s) | Why: %s",
                intent.domain,
                intent.service,
                intent.target_entity_ids,
                res.get("status"),
                intent.rationale[:180],
            )

    async def run_periodic_batch_analysis(
        self,
        agent_id: str = "climate_thermal_agent",
        area_id: str | None = None,
    ) -> AgentRunLog:
        """
        Execute Mode B: Periodic / On-Demand Batch Analysis across historical entity states.
        Identifies structural issues and synthesizes native Home Assistant automations.
        """
        agent_spec = self.registry.get_agent(agent_id)
        if not agent_spec:
            raise ValueError(f"Unknown agent_id: {agent_id}")

        all_states = await self.smart_home.get_all_states()
        ignored_targets = await self.memory.get_ignored_targets()
        filtered_states = {}
        for eid, st in all_states.items():
            if ignored_targets and any(t.matches(eid) for t in ignored_targets):
                continue
            if area_id and st.area_id != area_id and st.domain not in ("weather", "automation") and "outdoor" not in eid:
                continue
            if st.domain == "automation":
                filtered_states[eid] = st
            elif st.domain in agent_spec.monitored_domains or st.domain in agent_spec.controllable_domains:
                if any(skip in eid for skip in ("gabis_mac", "andrada_s_iphone", "gabriels_iphone", "lenovo_", "_energy_returned", "_perception")):
                    continue
                if st.domain == "sensor" and agent_spec.monitored_device_classes:
                    if st.device_class in agent_spec.monitored_device_classes or any(
                        k in eid for k in ("temperature", "humidity", "illuminance", "dew_point", "_uh_", "master_ac_", "daikin")
                    ):
                        filtered_states[eid] = st
                else:
                    filtered_states[eid] = st

        initial_state: ClimateGraphState = {
            "agent_spec": agent_spec,
            "site_context": self.settings.site_context,
            "mode": "periodic_batch",
            "area_id": area_id,
            "trigger_summary": f"Periodic/Manual Batch Analysis for {agent_spec.name}",
            "corroborated_states": filtered_states,
        }

        final_state = await self.agent_graph.ainvoke(initial_state)
        intents = final_state.get("proposed_intents", [])
        insights = final_state.get("advisory_insights", [])

        for insight in insights:
            await self.memory.save_advisory_insight(insight)
            if self.settings.notifications_enabled and self.settings.default_autonomy != "shadow":
                await self.notification.send_advisory_alert(insight)

        exec_results = await self._evaluate_and_dispatch_intents(intents)

        run_log = AgentRunLog(
            agent_id=agent_spec.agent_id,
            mode="periodic_batch",
            trigger_summary=f"Batch Historical Analysis ({len(filtered_states)} relevant entities analyzed)",
            research_findings=final_state.get("research_findings", []),
            derived_signals=final_state.get("derived_signals", []),
            proposed_intents=intents,
            advisory_insights=insights,
            execution_results=exec_results,
        )
        self._log_agent_run_summary(run_log)
        await self.memory.save_run_log(run_log)
        return run_log

    def _is_intent_redundant(self, intent: ActionIntent) -> tuple[bool, str]:
        """Check if target entities are already in the desired state (prevent redundant proposals)."""
        if not self._cached_states or not intent.target_entity_ids:
            return False, ""

        if intent.domain == "cover":
            if intent.service == "close_cover":
                if all(
                    self._cached_states.get(eid) and self._cached_states[eid].state == "closed"
                    for eid in intent.target_entity_ids
                ):
                    return True, "All target covers are already closed."
            elif intent.service == "open_cover":
                if all(
                    self._cached_states.get(eid) and self._cached_states[eid].state == "open"
                    for eid in intent.target_entity_ids
                ):
                    return True, "All target covers are already open."

        if intent.domain in ("switch", "light"):
            if intent.service in ("turn_off", "turn_on"):
                target_state = "off" if intent.service == "turn_off" else "on"
                if all(
                    self._cached_states.get(eid) and self._cached_states[eid].state == target_state
                    for eid in intent.target_entity_ids
                ):
                    return True, f"All target entities are already {target_state}."

        return False, ""

    async def _evaluate_and_dispatch_intents(self, intents: list[ActionIntent]) -> list[dict[str, Any]]:
        """Pass proposed ActionIntents through the Conflict Arbiter and Guardrail Engine."""
        results: list[dict[str, Any]] = []
        endorsed_rules = await self.memory.get_endorsed_rules()
        rejected_signatures = await self.memory.get_rejected_signatures()
        active_pending = await self.memory.get_pending_approvals()

        for intent in intents:
            # 0. Check for No-Op Redundancy against current entity state
            is_redundant, redundant_reason = self._is_intent_redundant(intent)
            if is_redundant:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": intent.repeatable_signature(),
                        "status": "suppressed_redundant",
                        "reason": redundant_reason,
                    }
                )
                continue

            # 1. Conflict Arbiter Check
            arbiter_ok, arbiter_reason = self.arbiter.evaluate_intent(intent)
            if not arbiter_ok:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": intent.repeatable_signature(),
                        "status": "blocked_by_arbiter",
                        "reason": arbiter_reason,
                    }
                )
                continue

            # 2. Check Active Pending Approvals for In-Flight Duplicates & Contradictions
            conflict_found = False
            for p in active_pending:
                overlapping = set(p.intent.target_entity_ids).intersection(intent.target_entity_ids)
                if not overlapping:
                    continue
                # Identical domain and service already awaiting user decision
                if p.intent.domain == intent.domain and p.intent.service == intent.service:
                    results.append(
                        {
                            "intent_id": intent.intent_id,
                            "signature": intent.repeatable_signature(),
                            "status": "suppressed_duplicate_pending",
                            "reason": f"An identical action on {sorted(overlapping)} is already pending user approval (ID: {p.approval_id[:8]}).",
                        }
                    )
                    conflict_found = True
                    break
                # Contradictory opposing action already awaiting user decision (e.g. open vs close)
                if p.intent.domain == intent.domain and (
                    (p.intent.service == "close_cover" and intent.service in ("open_cover", "set_cover_position"))
                    or (p.intent.service in ("open_cover", "set_cover_position") and intent.service == "close_cover")
                    or (p.intent.service == "turn_on" and intent.service == "turn_off")
                    or (p.intent.service == "turn_off" and intent.service == "turn_on")
                ):
                    results.append(
                        {
                            "intent_id": intent.intent_id,
                            "signature": intent.repeatable_signature(),
                            "status": "blocked_by_conflict",
                            "reason": f"Opposing action on {sorted(overlapping)} is already pending approval (ID: {p.approval_id[:8]}, {p.intent.service} vs {intent.service}).",
                        }
                    )
                    conflict_found = True
                    break

            if conflict_found:
                continue

            # 3. Deterministic Guardrail & Repeatable Approval Check
            eval_res = self.guardrails.evaluate(
                intent=intent,
                autonomy_level=self.settings.default_autonomy,
                notifications_enabled=self.settings.notifications_enabled,
                endorsed_rules=endorsed_rules,
                rejected_signatures=rejected_signatures,
            )

            if eval_res.decision == GuardrailDecisionType.HARD_BLOCKED:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": eval_res.signature,
                        "status": "hard_blocked",
                        "reason": eval_res.reason,
                    }
                )
            elif eval_res.decision == GuardrailDecisionType.SHADOW_LOG_ONLY:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": eval_res.signature,
                        "status": "shadow_logged",
                        "reason": eval_res.reason,
                    }
                )
            elif eval_res.decision == GuardrailDecisionType.REQUIRE_USER_APPROVAL:
                pending = PendingApproval(intent=intent, signature=eval_res.signature)
                await self.memory.save_pending_approval(pending)
                if self.settings.notifications_enabled:
                    await self.notification.send_approval_request(pending)
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "approval_id": pending.approval_id,
                        "signature": eval_res.signature,
                        "status": "awaiting_user_approval",
                        "reason": eval_res.reason,
                    }
                )
            elif eval_res.decision == GuardrailDecisionType.EXECUTE_IMMEDIATELY:
                exec_out = await self._execute_intent(intent)
                if eval_res.matched_rule is not None:
                    await self.memory.increment_rule_usage(eval_res.signature)
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": eval_res.signature,
                        "status": "executed",
                        "reason": eval_res.reason,
                        "service_output": exec_out,
                    }
                )

        return results

    async def _execute_intent(self, intent: ActionIntent) -> dict[str, Any]:
        """Execute an approved ActionIntent against Home Assistant and schedule outcome verification."""
        context_id = f"ai_brain_{uuid.uuid4().hex[:12]}"
        self.triage.register_ai_action(
            context_id=context_id,
            entity_ids=intent.target_entity_ids,
            agent_id=intent.agent_id,
            cause_category=intent.cause_category,
            action_signature=intent.repeatable_signature(),
            service_called=f"{intent.domain}.{intent.service}",
            service_data=intent.service_data,
        )

        try:
            if intent.domain == "automation" and intent.native_automation is not None:
                res = await self.smart_home.upsert_automation(intent.native_automation)
            elif intent.domain == "notify":
                # Strictly use the single notification service chosen by the user in Settings / UI
                _, _, configured_notify_svc = self.settings.notification_service.partition(".")
                notify_service = configured_notify_svc or "notify"
                payload = dict(intent.service_data)
                if "message" not in payload:
                    payload["message"] = intent.rationale
                if "title" not in payload:
                    payload["title"] = f"HA AI Brain ({intent.agent_id})"
                res = await self.smart_home.call_service(
                    domain="notify",
                    service=notify_service,
                    target_entity_ids=[],
                    service_data=payload,
                    context_id=context_id,
                )
            else:
                res = await self.smart_home.call_service(
                    domain=intent.domain,
                    service=intent.service,
                    target_entity_ids=intent.target_entity_ids,
                    service_data=intent.service_data,
                    context_id=context_id,
                )
        except Exception as exc:
            logger.error(
                "Execution error calling %s.%s on %s: %s",
                intent.domain, intent.service, intent.target_entity_ids, exc,
            )
            res = {"status": "error", "error": str(exc), "domain": intent.domain, "service": intent.service}

        if intent.expected_outcome is not None:
            await self.memory.save_expected_outcome(intent.expected_outcome)

        return res

    async def handle_approval_decision(
        self,
        approval_id: str,
        decision: str,
        human_note: str = "",
    ) -> dict[str, Any]:
        """
        Process user feedback from an actionable notification or UI button:
        - `approved_once`: Executes action once; records ENDORSED_ONCE feedback.
        - `approved_repeatable`: Executes action AND stores ApprovalRule so future matching
          actions execute automatically without asking for confirmation again!
        - `rejected`: Cancels action and records REJECTED_EXPLICIT feedback.
        """
        if decision not in ("approved_once", "approved_repeatable", "rejected", "dismissed"):
            raise ValueError(f"Invalid approval decision: {decision}")

        pending = await self.memory.resolve_pending_approval(approval_id=approval_id, status=decision)
        if pending is None:
            raise KeyError(f"PendingApproval '{approval_id}' not found")

        # Automatically clear/dismiss the push notification on the user's mobile devices
        if hasattr(self.notification, "dismiss_approval_notification"):
            try:
                await self.notification.dismiss_approval_notification(approval_id)
            except Exception:
                pass

        intent = pending.intent
        signature = pending.signature

        if decision == "dismissed":
            logger.info(
                "[APPROVAL DECISION -> DISMISSED] Dismissed %s (%s.%s) without execution or permanent block.",
                approval_id,
                intent.domain,
                intent.service,
            )
            return {"approval_id": approval_id, "status": "dismissed", "signature": signature}

        if decision == "rejected":
            episode = FeedbackEpisode(
                agent_id=intent.agent_id,
                area_id=intent.area_id,
                cause_category=intent.cause_category,
                action_signature=signature,
                target_entity_ids=intent.target_entity_ids,
                service_called=f"{intent.domain}.{intent.service}",
                service_data=intent.service_data,
                polarity=FeedbackPolarity.REJECTED_EXPLICIT,
                human_note=human_note or "Rejected by user via confirmation prompt.",
            )
            await self.memory.save_feedback(episode)
            if human_note.strip():
                await self.memory.save_user_context_note(
                    UserContextNote(
                        content=human_note.strip(),
                        scope=intent.agent_id,
                        related_entities=list(intent.target_entity_ids),
                    )
                )
            return {"approval_id": approval_id, "status": "rejected", "signature": signature}

        # Execute the approved action
        logger.info(
            "[APPROVAL DECISION -> %s] Executing %s.%s on %s (approval_id=%s, note=%r)",
            decision.upper(),
            intent.domain,
            intent.service,
            intent.target_entity_ids,
            approval_id,
            human_note,
        )
        exec_res = await self._execute_intent(intent)

        if decision == "approved_repeatable":
            rule = ApprovalRule(
                signature=signature,
                agent_id=intent.agent_id,
                domain_service=f"{intent.domain}.{intent.service}",
                target_entity_ids=intent.target_entity_ids,
                cause_category=intent.cause_category,
                description=intent.rationale,
                auto_approve=True,
                execution_count=1,
            )
            await self.memory.save_approval_rule(rule)
            polarity = FeedbackPolarity.ENDORSED_REPEATABLE
        else:
            polarity = FeedbackPolarity.ENDORSED_ONCE

        episode = FeedbackEpisode(
            agent_id=intent.agent_id,
            area_id=intent.area_id,
            cause_category=intent.cause_category,
            action_signature=signature,
            target_entity_ids=intent.target_entity_ids,
            service_called=f"{intent.domain}.{intent.service}",
            service_data=intent.service_data,
            polarity=polarity,
            human_note=human_note or f"User decision: {decision}",
        )
        await self.memory.save_feedback(episode)

        return {
            "approval_id": approval_id,
            "status": decision,
            "signature": signature,
            "repeatable_rule_saved": decision == "approved_repeatable",
            "service_output": exec_res,
        }

    async def dismiss_all_pending(self) -> int:
        pending = await self.memory.get_pending_approvals()
        for p in pending:
            if hasattr(self.notification, "dismiss_approval_notification"):
                try:
                    await self.notification.dismiss_approval_notification(p.approval_id)
                except Exception:
                    pass
        count = await self.memory.dismiss_all_pending_approvals()
        logger.info("[APPROVAL DECISION -> DISMISSED ALL] Dismissed %d pending approvals.", count)
        return count
