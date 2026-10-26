"""LangGraph StateGraph implementation for Autonomous Specialized Domain Agents (Climate, Lighting, Security, Energy, Covers, Diagnostics, and Custom Agents)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from ha_ai_brain.application.graphs.state_graph_engine import END, START, StateGraph
from ha_ai_brain.application.graphs.subagents import (
    MAX_PROMPT_ENTITIES,
    ComputationSubAgent,
    ResearchSubAgent,
    compact_attrs,
    research_digest,
)
from ha_ai_brain.domain.models import (
    ActionIntent,
    ActionPriority,
    ActionRiskLevel,
    AdvisoryInsight,
    AgentSpec,
    DerivedSignal,
    EntityState,
    ExpectedOutcome,
    FeedbackEpisode,
    NativeAutomationProposal,
    PendingApproval,
    ResearchFinding,
    UserContextNote,
)
from ha_ai_brain.domain.automation_rules import find_equivalent_rule
from ha_ai_brain.application.research_agenda import approved_knowledge_for
from ha_ai_brain.domain.knowledge import KNOWLEDGE_VERSION, select_knowledge
from ha_ai_brain.domain.promptfmt import dumps
from ha_ai_brain.domain.series import summarize_history
from ha_ai_brain.domain.service_resolver import normalize_automation_proposal, resolve_notification_service
from ha_ai_brain.ports.llm import REASONING_DEFAULT, REASONING_LOW, LLMProviderPort
from ha_ai_brain.ports.memory import MemoryStorePort
from ha_ai_brain.ports.smart_home import SmartHomePort
from ha_ai_brain.ports.telemetry import TelemetryStorePort

logger = logging.getLogger(__name__)

RESEARCH_CACHE_DAYS = 14

# LLM-proposed actions may never claim the top priority tiers: those are reserved for human overrides and life safety.
MAX_LLM_ACTION_PRIORITY = ActionPriority.EQUIPMENT_AND_STRUCTURAL_PROTECTION


class AgentGraphState(TypedDict, total=False):
    """Typed state flowing through the specialized domain agent LangGraph StateGraph."""

    agent_spec: AgentSpec
    site_context: str
    mode: str  # "realtime_stream" or "periodic_batch"
    lookback_hours: int
    area_id: str | None
    trigger_summary: str
    corroborated_states: dict[str, EntityState]
    history_series: dict[str, list[dict[str, Any]]]
    past_feedback: list[FeedbackEpisode]
    user_context_notes: list[UserContextNote]
    research_findings: list[ResearchFinding]
    derived_signals: list[DerivedSignal]
    proposed_intents: list[ActionIntent]
    advisory_insights: list[AdvisoryInsight]
    rejected_insights: list[AdvisoryInsight]
    rejected_actions: list[FeedbackEpisode]
    accepted_automations: list[FeedbackEpisode]
    pending_approvals: list[PendingApproval]
    available_services: dict[str, list[str]]
    available_notify_services: list[str]
    configured_notify_service: str
    # --- learned context supplied by the orchestrator / gathered locally (no LLM tokens) ---
    household_context: dict[str, Any]
    mined_patterns: list[dict[str, Any]]
    automation_rules: list[Any]
    history_summaries: dict[str, dict[str, Any]]
    recent_activity: list[dict[str, Any]]
    reference_knowledge: list[dict[str, Any]]
    patterns_handled_by_system: bool


# Backward compatibility alias
ClimateGraphState = AgentGraphState


class SpecializedAgentGraph:
    """
    Generalized LangGraph workflow orchestrating any specialized domain agent
    (Climate, Lighting, Security, Energy, Covers, Diagnostics, or Custom Agents):
      START
        -> corroborate_context
        -> delegate_research_subagent
        -> delegate_computation_subagent
        -> (conditional by mode)
           ├─ realtime_stream -> synthesize_realtime_reactions -> END
           └─ periodic_batch  -> synthesize_batch_automations_and_insights -> END
    """

    def __init__(
        self,
        smart_home: SmartHomePort,
        llm: LLMProviderPort,
        memory: MemoryStorePort,
        research_subagent: ResearchSubAgent,
        computation_subagent: ComputationSubAgent,
        telemetry: TelemetryStorePort | None = None,
        knowledge_dir: str = "",
    ) -> None:
        self.telemetry = telemetry
        self.knowledge_dir = knowledge_dir
        self.smart_home = smart_home
        self.llm = llm
        self.memory = memory
        self.research_subagent = research_subagent
        self.computation_subagent = computation_subagent
        self._cached_findings: dict[str, tuple[datetime, list[ResearchFinding]]] = {}
        self._compiled_graph = self._build_graph()

    def invalidate_context_caches(self) -> None:
        """Clear cached sub-agent research findings and computation code when context or rules change."""
        self._cached_findings.clear()
        if hasattr(self.computation_subagent, "_cached_code"):
            self.computation_subagent._cached_code.clear()

    def _build_graph(self) -> Any:
        builder = StateGraph(AgentGraphState)

        builder.add_node("corroborate_context", self._corroborate_context_node)
        builder.add_node("delegate_research_subagent", self._delegate_research_node)
        builder.add_node("delegate_computation_subagent", self._delegate_computation_node)
        builder.add_node("synthesize_realtime_reactions", self._synthesize_realtime_reactions_node)
        builder.add_node("synthesize_batch_automations_and_insights", self._synthesize_batch_node)

        builder.add_edge(START, "corroborate_context")
        builder.add_edge("corroborate_context", "delegate_research_subagent")
        builder.add_edge("delegate_research_subagent", "delegate_computation_subagent")
        builder.add_conditional_edges(
            "delegate_computation_subagent",
            self._route_by_mode,
            {
                "realtime_stream": "synthesize_realtime_reactions",
                "periodic_batch": "synthesize_batch_automations_and_insights",
            },
        )
        builder.add_edge("synthesize_realtime_reactions", END)
        builder.add_edge("synthesize_batch_automations_and_insights", END)

        return builder.compile()

    async def ainvoke(self, initial_state: AgentGraphState) -> AgentGraphState:
        """Execute the compiled LangGraph workflow."""
        result = await self._compiled_graph.ainvoke(initial_state)
        return result  # type: ignore[return-value]

    def _route_by_mode(self, state: AgentGraphState) -> str:
        mode = state.get("mode", "realtime_stream")
        return "periodic_batch" if mode == "periodic_batch" else "realtime_stream"

    async def _corroborate_context_node(self, state: AgentGraphState) -> dict[str, Any]:
        """Gather historical state trajectories and episodic feedback memory."""
        agent_spec = state["agent_spec"]
        area_id = state.get("area_id")
        corroborated = state.get("corroborated_states", {})
        if not corroborated:
            corroborated = await self.smart_home.get_all_states()

        now = datetime.now(timezone.utc)
        lookback_hours = state.get("lookback_hours") or (24 if state.get("mode") == "periodic_batch" else 4)
        history_series = await self.smart_home.get_history(
            entity_ids=list(corroborated.keys()),
            start_time=now - timedelta(hours=lookback_hours),
            end_time=now,
        )

        past_feedback = await self.memory.get_relevant_feedback(
            agent_id=agent_spec.agent_id,
            area_id=area_id,
            limit=15,
        )
        user_notes = await self.memory.get_user_context_notes(active_only=True)
        rejected_insights = await self.memory.get_rejected_insights()
        rejected_actions = await self.memory.get_rejected_suggestions()
        accepted_automations = await self.memory.get_accepted_automations()
        pending_approvals = await self.memory.get_pending_approvals()
        ignored_targets = await self.memory.get_ignored_targets()
        if ignored_targets:
            corroborated = {
                eid: st
                for eid, st in corroborated.items()
                if not any(t.matches(eid) for t in ignored_targets)
            }
            history_series = {
                eid: series
                for eid, series in history_series.items()
                if not any(t.matches(eid) for t in ignored_targets)
            }

        recent_activity: list[dict[str, Any]] = []
        if self.telemetry is not None and state.get("mode", "realtime_stream") == "realtime_stream":
            try:
                recent = await self.telemetry.get_transitions(
                    since=now - timedelta(hours=3),
                    entity_ids=[e for e, st in corroborated.items() if st.domain not in ("sensor", "weather", "sun", "automation")][:60] or None,
                )
                recent_activity = [
                    {"entity_id": t.entity_id, "from": t.old_state, "to": t.new_state, "at": t.ts.isoformat(timespec="minutes"), "by": t.origin}
                    for t in recent[-25:]
                ]
            except Exception as exc:
                logger.debug("recent activity unavailable: %s", exc)

        return {
            "corroborated_states": corroborated,
            "history_series": history_series,
            "history_summaries": summarize_history(history_series),
            "recent_activity": recent_activity,
            "reference_knowledge": (
                await approved_knowledge_for(self.memory, agent_spec.agent_id)
                + select_knowledge(agent_spec, corroborated, user_dir=self.knowledge_dir)
            )[:10],
            "past_feedback": past_feedback,
            "user_context_notes": user_notes,
            "rejected_insights": rejected_insights,
            "rejected_actions": rejected_actions,
            "accepted_automations": accepted_automations,
            "pending_approvals": pending_approvals,
        }

    @staticmethod
    def _research_digest(findings: list[ResearchFinding]) -> list[dict[str, Any]]:
        return research_digest(findings)

    @staticmethod
    def _compose_effective_site_context(state: AgentGraphState) -> str:
        base_ctx = state.get("site_context", "")
        notes = state.get("user_context_notes", [])
        if not notes:
            return base_ctx
        bullet_lines = "\n".join(
            f"- [{n.scope}] {n.content}" + (f" (entities: {', '.join(n.related_entities)})" if n.related_entities else "")
            for n in notes
        )
        return (
            f"{base_ctx}\n\n"
            "CRITICAL USER-PROVIDED CONTEXT & HARDWARE/BEHAVIORAL CONSTRAINTS (MUST OBEY):\n"
            f"{bullet_lines}"
        )

    async def _delegate_research_node(self, state: AgentGraphState) -> dict[str, Any]:
        """Delegate scientific & domain discovery to the Research Sub-Agent (with a persistent, signature-keyed cache)."""
        agent_spec = state["agent_spec"]
        mode = state.get("mode", "realtime_stream")
        cache_key = f"{agent_spec.agent_id}:{state.get('area_id') or 'global'}"
        now = datetime.now(timezone.utc)

        # In realtime_stream mode: reuse cached research findings if fresher than 6 hours (saves ~2,400 tokens!)
        if mode == "realtime_stream" and cache_key in self._cached_findings:
            cached_t, cached_findings = self._cached_findings[cache_key]
            if (now - cached_t).total_seconds() < 21600.0 and cached_findings:
                return {"research_findings": cached_findings}

        # Persistent cache keyed by the *kinds* of devices the agent looks at (not their ids or values): adding one more
        # sensor of an existing kind never triggers new research. Edits to the site context / notes do.
        observed = state.get("corroborated_states", {})
        type_signature = sorted(
            {(s_.domain, s_.device_class or "", s_.unit_of_measurement or "") for s_ in observed.values() if s_.domain != "automation"}
        )
        signature = hashlib.sha1(
            json.dumps(
                [KNOWLEDGE_VERSION, agent_spec.agent_id, agent_spec.specialty, agent_spec.custom_domain_rules_prompt,
                 type_signature, self._compose_effective_site_context(state)],
                default=str,
            ).encode()
        ).hexdigest()[:16]
        kv_key = f"rcache:{agent_spec.agent_id}:{signature}"
        ttl_seconds = RESEARCH_CACHE_DAYS * 86400
        try:
            cached_raw = await self.memory.get_kv(kv_key)
            if cached_raw:
                payload = json.loads(cached_raw)
                saved_at = datetime.fromisoformat(payload["saved_at"])
                if (now - saved_at).total_seconds() < ttl_seconds:
                    findings = [ResearchFinding.model_validate(f) for f in payload["findings"]]
                    if findings:
                        self._cached_findings[cache_key] = (saved_at, findings)
                        return {"research_findings": findings}
        except Exception as exc:
            logger.debug("research cache read failed: %s", exc)

        findings = await self.research_subagent.investigate(
            agent_specialty=f"{agent_spec.name}: {agent_spec.specialty}. {agent_spec.custom_domain_rules_prompt}",
            site_context=self._compose_effective_site_context(state),
            observed_states=observed,
            mode=mode,
            reference_knowledge=state.get("reference_knowledge", []),
        )
        if findings:
            self._cached_findings[cache_key] = (now, findings)
            try:
                await self.memory.set_kv(
                    kv_key,
                    json.dumps({"saved_at": now.isoformat(), "findings": [f.model_dump() for f in findings]}),
                )
            except Exception as exc:
                logger.debug("research cache write failed: %s", exc)
        return {"research_findings": findings}

    async def _delegate_computation_node(self, state: AgentGraphState) -> dict[str, Any]:
        """Delegate numerical physics & time-series signal extraction to the Computation Sub-Agent."""
        agent_spec = state["agent_spec"]
        cache_key = f"{agent_spec.agent_id}:{state.get('area_id') or 'global'}"
        signals = await self.computation_subagent.compute_derived_signals(
            observed_states=state.get("corroborated_states", {}),
            history_series=state.get("history_series", {}),
            research_findings=state.get("research_findings", []),
            mode=state.get("mode", "realtime_stream"),
            user_context_notes=[
                {"scope": n.scope, "content": n.content, "related_entities": n.related_entities}
                for n in state.get("user_context_notes", [])
            ],
            cache_key=cache_key,
            history_summaries=state.get("history_summaries", {}),
        )
        return {"derived_signals": signals}

    async def _synthesize_realtime_reactions_node(self, state: AgentGraphState) -> dict[str, Any]:
        """
        Synthesize real-time autonomous reactions based on corroborated telemetry,
        sub-agent research findings, derived signals, and human feedback history.
        """
        agent_spec = state["agent_spec"]
        corroborated = state.get("corroborated_states", {})
        derived_signals = state.get("derived_signals", [])
        research_findings = state.get("research_findings", [])
        past_feedback = state.get("past_feedback", [])
        trigger_area = state.get("area_id")
        trigger_summary = state.get("trigger_summary", "")

        # Identify controllable actuators in the corroborated context
        actuators = {
            eid: {
                "domain": st.domain,
                "state": st.state,
                "area_id": st.area_id,
                "attributes": compact_attrs(st.attributes),
            }
            for eid, st in corroborated.items()
            if st.domain in agent_spec.controllable_domains and st.domain != "automation"
        }

        # Area-scoped telemetry: in real-time mode, only send sensors in the triggered area
        # plus outdoor/weather/sun and the trigger entity itself (saves ~3,000 tokens)
        relevant_sensors = {}
        for eid, s in corroborated.items():
            if s.domain == "automation" or "_real_feel_" in eid:
                continue
            is_trigger = eid in trigger_summary
            is_same_area = trigger_area and s.area_id == trigger_area
            is_outdoor_or_global = (
                s.domain in ("weather", "sun")
                or s.area_id in ("outdoor", "outside", "exterior", "rooftop")
                or any(k in eid for k in ("outdoor", "outside", "weather"))
            )
            if is_trigger or is_same_area or is_outdoor_or_global or not trigger_area:
                relevant_sensors[eid] = {
                    "state": s.state,
                    "unit": s.unit_of_measurement,
                    "area": s.area_id,
                    "attributes": compact_attrs(s.attributes),
                }

        available_services = state.get("available_services", {})
        available_notify = state.get("available_notify_services", [])
        configured_notify = state.get("configured_notify_service", "notify.notify")
        present_domains = {st.domain for st in corroborated.values()}
        relevant_services = {
            dom: svcs
            for dom, svcs in available_services.items()
            if (dom in agent_spec.controllable_domains and dom in present_domains) or dom in ("notify", "homeassistant")
        }

        llm_response = await self.llm.generate_json(
            system_prompt=(
                f"You are the {agent_spec.name} ({agent_spec.specialty}). "
                f"Goals: {'; '.join(agent_spec.goals)}. "
                f"{agent_spec.custom_domain_rules_prompt}\n"
                "Analyze the current sensor states, the Research Sub-Agent's scientific findings, "
                "and the Computation Sub-Agent's derived numerical signals from an expert domain perspective. "
                "STRICTLY OBEY the 'CRITICAL USER-PROVIDED CONTEXT' section of `site_context` (e.g. broken device sub-features, physical constraints, or user preferences) "
                "and never propose actions or notifications that violate it. "
                "Also respect past human feedback (never repeat actions marked rejected_explicit or overridden_implicit). "
                "Propose concrete Home Assistant service reactions using available actuators (e.g. `lock.lock`, "
                "`cover.close_cover`, `climate.set_temperature`, `light.turn_on`).\n"
                "CRITICAL: Whenever a controllable actuator exists for the action you want to take, ALWAYS propose "
                "the actual device service call (e.g. `domain: 'lock', service: 'lock', target_entity_ids: ['lock.front_door']`), "
                "NOT a `notify.notify` message asking the user 'Please confirm if you would like to...'. "
                "The deterministic Guardrail Engine automatically intercepts device service calls in Co-Pilot mode "
                "and sends an actionable notification with interactive 'Approve Once', 'Always Allow', and 'Reject' buttons! "
                "Only use `notify.notify` for pure physical advisories where NO smart actuator exists (e.g., manually closing an un-motorized window).\n"
                "If `trigger_summary` starts with 'Exception:', it reports a deviation from a learned household routine or from an existing "
                "automation. Judge from `household` (who is home, time of day) and `recent_activity` whether it is genuinely abnormal; if it is, "
                "propose the single most appropriate corrective device action, otherwise return an empty `actions` list. Do not duplicate what "
                "an existing automation already does and never act on routine, expected behaviour.\n"
                "Return JSON with key `actions` (list of objects with `domain`, `service`, `target_entity_ids`, "
                "`service_data`, `cause_category`, `rationale`, `derived_signals_used`, `priority`, `risk_level`, "
                "and optional `expected_outcome`)."
            ),
            # Stable parts first and volatile parts last: providers that cache prompt prefixes can then reuse the stable head.
            user_prompt=dumps(
                {
                    "site_context": self._compose_effective_site_context(state),
                    "reference_knowledge": state.get("reference_knowledge", [])[:5],
                    "research_findings": self._research_digest(research_findings),
                    "available_ha_services": relevant_services,
                    "available_notification_services": available_notify,
                    "preferred_notification_service": configured_notify,
                    "past_feedback": [
                        {
                            "signature": fb.action_signature,
                            "polarity": fb.polarity.value,
                            "service": fb.service_called,
                            "note": fb.human_note,
                        }
                        for fb in past_feedback[:5]
                    ],
                    "household": state.get("household_context", {}),
                    "area_id": trigger_area,
                    "trigger_summary": trigger_summary,
                    "recent_activity": state.get("recent_activity", []),
                    "sensor_states": relevant_sensors,
                    "available_actuators": actuators,
                    "derived_signals": [d.model_dump(exclude={"python_code_executed"}) for d in derived_signals],
                }
            ),
            use_fast_tier=True,
            context_hint={
                "task": "synthesize_realtime_reactions",
                "reasoning": REASONING_LOW,
                "agent_id": agent_spec.agent_id,
                "area_id": trigger_area,
                "corroborated": {eid: s.model_dump(mode="json") for eid, s in corroborated.items()},
                "actuators": actuators,
                "derived_signals": [d.model_dump() for d in derived_signals],
                "research_findings": [f.model_dump() for f in research_findings],
                "past_feedback": [fb.model_dump(mode="json") for fb in past_feedback],
            },
        )

        intents = self._parse_action_intents(
            raw_actions=llm_response.get("actions", []),
            agent_id=agent_spec.agent_id,
            default_area_id=state.get("area_id"),
            available_notify_services=available_notify,
            preferred_notify_service=configured_notify,
        )
        return {"proposed_intents": intents, "advisory_insights": []}

    async def _synthesize_batch_node(self, state: AgentGraphState) -> dict[str, Any]:
        """
        Periodic / On-Demand Batch Analysis Node (Low-Token Mode):
        Analyzes multi-hour/multi-day telemetry & derived signals to produce:
        1. Structural/Hardware/Parameter AdvisoryInsights
        2. Non-duplicate Native Home Assistant Automations (crystallizing discovered patterns)
        """
        agent_spec = state["agent_spec"]
        corroborated = state.get("corroborated_states", {})
        derived_signals = state.get("derived_signals", [])
        research_findings = state.get("research_findings", [])
        rejected_insights = state.get("rejected_insights", [])
        rejected_actions = state.get("rejected_actions", [])
        rejected_automations = [
            ep for ep in rejected_actions
            if ep.service_called == "automation.upsert_native_automation"
        ]
        accepted_automations = state.get("accepted_automations", [])
        pending_approvals = state.get("pending_approvals", [])
        pending_automations = [
            p for p in pending_approvals
            if p.intent.domain == "automation" or p.intent.native_automation is not None
        ]

        rules_by_id = {r.automation_id: r for r in state.get("automation_rules", []) if r.automation_id}
        existing_automations = {
            eid: {
                "state": st.state,
                "friendly_name": st.attributes.get("friendly_name", eid),
                "last_triggered": st.attributes.get("last_triggered"),
                **({"definition": rules_by_id[st.attributes["id"]].summary()} if st.attributes.get("id") in rules_by_id else {}),
            }
            for eid, st in corroborated.items()
            if st.domain == "automation"
        }
        mined_patterns = state.get("mined_patterns", [])
        pattern_policy = (
            "Routine time-based or sequence habits are handled by the system itself - do not turn them into automations; "
            "focus on insights, tuning and non-trivial cross-entity logic."
            if state.get("patterns_handled_by_system", True)
            else "You MAY turn the strongest patterns into native automations (set `pattern_id`), preferring simple, predictable triggers."
        )

        available_services = state.get("available_services", {})
        available_notify = state.get("available_notify_services", [])
        configured_notify = state.get("configured_notify_service", "notify.notify")
        present_domains = {st.domain for st in corroborated.values()}
        relevant_services = {
            dom: svcs
            for dom, svcs in available_services.items()
            if (dom in agent_spec.controllable_domains and dom in present_domains) or dom in ("notify", "homeassistant")
        }
        histories = state.get("history_summaries", {})
        deployed_or_pending = [
            {
                "alias": (ep.service_data or {}).get("alias") or ep.cause_category,
                "targets": ep.target_entity_ids,
                "status": "deployed",
            }
            for ep in accepted_automations
        ] + [
            {
                "alias": (p.intent.native_automation.alias if p.intent.native_automation else (p.intent.service_data or {}).get("alias") or p.intent.cause_category),
                "targets": p.intent.target_entity_ids,
                "status": "pending_approval",
            }
            for p in pending_automations
        ]

        llm_response = await self.llm.generate_json(
            system_prompt=(
                f"You are the {agent_spec.name} ({agent_spec.specialty}) running in Periodic Deep Batch Analysis Mode. "
                "You are analyzing the historical entity trajectories over the past `lookback_hours` hours. "
                "Examine the entity trajectories (`entities[*].stats`), the Research Sub-Agent's findings, the Computation "
                "Sub-Agent's derived signals, and the `existing_automations` already configured in Home Assistant.\n"
                "CRITICAL RULES FOR WHAT THE HOMEOWNER ALREADY DECIDED:\n"
                "- `rejected_insights` and `rejected_automations` were explicitly REJECTED: never suggest those topics, similar logic, or automations controlling those devices again.\n"
                "- `deployed_or_pending_automations` are already deployed or awaiting a decision: never propose a duplicate, nor one that controls the same devices for similar conditions or accomplishes the same goal.\n"
                "CRITICAL RULES FOR EXISTING AUTOMATIONS & USER CONTEXT NOTES:\n"
                "- Strictly obey the 'CRITICAL USER-PROVIDED CONTEXT' section of `site_context` (e.g., mechanically broken features, devices used only in specific modes, or user directives). Never suggest actions or insights that contradict it.\n"
                "- Do NOT mistake repetitive device state changes driven by `existing_automations` for un-automated manual human habits.\n"
                "- Do NOT propose a `native_automation` that duplicates an automation already listed in `existing_automations` or `deployed_or_pending_automations`.\n"
                "- If an existing automation can be improved based on physical telemetry, emit an `advisory_insight` explaining how.\n"
                "- `existing_automations[*].definition` shows the real triggers/actions of each automation; never propose something an existing automation already does.\n"
                "CRITICAL RULES FOR LEARNED PATTERNS & EVIDENCE:\n"
                "- `mined_patterns` are statistically verified recurring behaviours from the household's own history (with support and confidence) that are NOT yet automated. "
                f"{pattern_policy}\n"
                "- Ground every recommendation in `entities[*].stats`, `derived_signals`, `household` and `reference_knowledge` (cite the reference id in `finding_details`). "
                "Do not invent sources, standards or URLs; do not claim patterns that are not in the data. "
                "Call a `reference_knowledge` entry a 'built-in reference' (or 'approved knowledge' only when its origin says approved); "
                "never write that something is 'based on research' or 'research shows' unless an entry's origin says approved web research.\n"
                "- Use `household.weather.forecast_next_hours`, `household.energy_prices` and `household.solar_forecast` when proposing load-shifting or pre-conditioning.\n"
                "CRITICAL RULES FOR NATIVE AUTOMATIONS (Triggers, Conditions & Actions):\n"
                "- ONLY use entity IDs that exist in the provided `entities` dictionary. Never hallucinate or assume non-existent entities.\n"
                "- ONLY use valid Home Assistant services that exist in the provided `available_ha_services`.\n"
                f"- When an automation action sends a notification (e.g. alerting the homeowner), you MUST use a valid service from `available_notification_services` (preferred: '{configured_notify}').\n"
                f"- NEVER invent non-existent notification services or guess device names (e.g. never invent unverified device names). If notifying the homeowner, use '{configured_notify}'.\n"
                "- Actions must use standard Home Assistant action schema: `{'service': 'domain.service', 'target': {'entity_id': '...'}, 'data': {...}}`.\n"
                "Return JSON with:\n"
                "1) `advisory_insights`: list of objects (`category`, `title` (concise 4-8 words), `finding_details` (deep technical analysis with sensor readings and psychrometric context), `evidence_metrics`, "
                "`recommended_human_action` (direct actionable step for homeowner), `estimated_impact`).\n"
                "2) `native_automations`: list of new, non-duplicate Home Assistant automation objects (`alias`, `description`, "
                "`trigger`, `condition`, `action`, `cause_category`, `discovered_pattern_rationale`, optional `pattern_id` when implementing a listed pattern).\n"
                "3) `actions`: optional list of immediate parameter adjustments."
            ),
            # Stable / slowly changing parts first, volatile parts last (prefix caching); each entity carries its own stats.
            user_prompt=dumps(
                {
                    "site_context": self._compose_effective_site_context(state),
                    "reference_knowledge": state.get("reference_knowledge", []),
                    "research_findings": self._research_digest(research_findings),
                    "available_ha_services": relevant_services,
                    "available_notification_services": available_notify,
                    "preferred_notification_service": configured_notify,
                    "rejected_insights": [
                        {"category": r.category, "title": r.title, "reason": r.rejection_reason}
                        for r in rejected_insights
                    ],
                    "rejected_automations": [
                        {
                            "alias": (ep.service_data or {}).get("alias") or ep.cause_category,
                            "targets": ep.target_entity_ids,
                            "note": ep.human_note if not ep.human_note.startswith("Rejected by user") else "",
                        }
                        for ep in rejected_automations
                    ],
                    "deployed_or_pending_automations": deployed_or_pending,
                    "existing_automations": existing_automations,
                    "lookback_hours": state.get("lookback_hours", 24),
                    "household": state.get("household_context", {}),
                    "mined_patterns": mined_patterns[:12],
                    "derived_signals": [d.model_dump(exclude={"python_code_executed"}) for d in derived_signals],
                    "entities": {
                        eid: {
                            "state": s.state,
                            "unit": s.unit_of_measurement,
                            "area": s.area_id,
                            "domain": s.domain,
                            "attrs": compact_attrs(s.attributes),
                            "stats": histories.get(eid),
                        }
                        for eid, s in list(
                            (e, st) for e, st in corroborated.items() if st.domain != "automation" and "_real_feel_" not in e
                        )[:MAX_PROMPT_ENTITIES]
                    },
                }
            ),
            use_fast_tier=False,
            context_hint={
                "task": "synthesize_batch_analysis",
                "reasoning": REASONING_DEFAULT,
                "agent_id": agent_spec.agent_id,
                "corroborated": {eid: s.model_dump(mode="json") for eid, s in corroborated.items()},
                "existing_automations": existing_automations,
                "deployed_or_pending_automations": [
                    {
                        "alias": (ep.service_data or {}).get("alias") or ep.cause_category,
                        "targets": ep.target_entity_ids,
                        "status": "deployed",
                    }
                    for ep in accepted_automations
                ] + [
                    {
                        "alias": (p.intent.native_automation.alias if p.intent.native_automation else (p.intent.service_data or {}).get("alias") or p.intent.cause_category),
                        "targets": p.intent.target_entity_ids,
                        "status": "pending_approval",
                    }
                    for p in pending_automations
                ],
                "derived_signals": [d.model_dump(exclude={"python_code_executed"}) for d in derived_signals],
                "research_findings": [f.model_dump() for f in research_findings],
                "rejected_insights": [r.model_dump(mode="json") for r in rejected_insights],
                "rejected_automations": [ep.model_dump(mode="json") for ep in rejected_automations],
            },
        )

        def _is_rejected_insight(cand_title: str, cand_category: str) -> bool:
            ct = cand_title.lower().strip()
            cc = cand_category.lower().strip()
            for r in rejected_insights:
                rt = r.title.lower().strip()
                rc = r.category.lower().strip()
                if rt == ct:
                    return True
                if len(rt) >= 8 and (rt in ct or ct in rt):
                    return True
                if rc == cc:
                    r_words = set(re.findall(r"\w{4,}", rt))
                    c_words = set(re.findall(r"\w{4,}", ct))
                    if r_words and len(r_words & c_words) >= max(2, len(r_words) // 2):
                        return True
            return False

        insights: list[AdvisoryInsight] = []
        raw_insights = llm_response.get("advisory_insights", [])
        if isinstance(raw_insights, dict):
            raw_insights = [raw_insights]
        for item in raw_insights if isinstance(raw_insights, list) else []:
            if isinstance(item, dict) and "title" in item:
                cand_title = str(item["title"])
                cand_cat = str(item.get("category", "thermal_efficiency"))
                if _is_rejected_insight(cand_title, cand_cat):
                    continue
                raw_em = item.get("evidence_metrics", {})
                if isinstance(raw_em, dict):
                    em_dict = raw_em
                elif isinstance(raw_em, list):
                    em_dict = {f"metric_{i+1}": v for i, v in enumerate(raw_em)}
                else:
                    em_dict = {"summary": str(raw_em)}
                insights.append(
                    AdvisoryInsight(
                        agent_id=agent_spec.agent_id,
                        category=cand_cat,
                        title=cand_title,
                        finding_details=str(item.get("finding_details", "")),
                        evidence_metrics=em_dict,
                        recommended_human_action=str(item.get("recommended_human_action", "")),
                        estimated_impact=str(item.get("estimated_impact", "")),
                    )
                )

        def _is_rejected_automation(cand_alias: str, cand_desc: str) -> bool:
            ca = cand_alias.lower().strip()
            ca_slug = re.sub(r"[^a-z0-9]+", "_", ca).strip("_")
            for r in rejected_automations:
                ra = str((r.service_data or {}).get("alias") or r.cause_category or "").lower().strip()
                ra_slug = re.sub(r"[^a-z0-9]+", "_", ra).strip("_")
                if ra_slug and (ra_slug == ca_slug or ra_slug in ca_slug or ca_slug in ra_slug):
                    return True
                r_words = set(re.findall(r"\w{4,}", ra))
                c_words = set(re.findall(r"\w{4,}", ca))
                if r_words and len(r_words & c_words) >= max(2, len(r_words) // 2):
                    return True
            return False

        def _normalize_words(text: str) -> set[str]:
            stopwords = {"the", "a", "an", "and", "or", "to", "for", "in", "on", "of", "with", "at", "by", "from", "ai", "brain", "native", "automation"}
            words = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
            return words - stopwords

        def _is_duplicate_automation(cand_alias: str, cand_targets: list[str]) -> bool:
            c_words = _normalize_words(cand_alias)
            c_targets_set = set(cand_targets)

            # 1. Existing automations in Home Assistant
            for eid, auto_info in existing_automations.items():
                fname = auto_info.get("friendly_name", "")
                ex_words = _normalize_words(fname)
                if ex_words and len(ex_words & c_words) >= max(2, min(len(ex_words), len(c_words)) // 2 + 1):
                    return True

            # 2. Deployed / accepted automations
            for ep in accepted_automations:
                data = ep.service_data or {}
                a_alias = data.get("alias") or ep.cause_category
                a_words = _normalize_words(a_alias)
                if a_words and len(a_words & c_words) >= max(2, min(len(a_words), len(c_words)) // 2 + 1):
                    return True
                ep_targets = set(ep.target_entity_ids or [])
                if c_targets_set and ep_targets.intersection(c_targets_set):
                    if a_words and len(a_words & c_words) >= 1:
                        return True

            # 3. Pending automations awaiting approval
            for p in pending_automations:
                nat = p.intent.native_automation
                p_alias = (nat.alias if nat else None) or (p.intent.service_data or {}).get("alias") or p.intent.cause_category
                p_words = _normalize_words(p_alias)
                if p_words and len(p_words & c_words) >= max(2, min(len(p_words), len(c_words)) // 2 + 1):
                    return True
                p_targets = set(p.intent.target_entity_ids or [])
                if c_targets_set and p_targets.intersection(c_targets_set):
                    if p_words and len(p_words & c_words) >= 1:
                        return True

            return False

        intents: list[ActionIntent] = []
        raw_autos = llm_response.get("native_automations", [])
        if isinstance(raw_autos, dict):
            raw_autos = [raw_autos]
        for auto in raw_autos if isinstance(raw_autos, list) else []:
            if isinstance(auto, dict) and "alias" in auto:
                cand_alias = str(auto["alias"])
                cand_desc = str(auto.get("description", ""))
                if _is_rejected_automation(cand_alias, cand_desc):
                    continue
                raw_trig = auto.get("trigger", [])
                raw_cond = auto.get("condition", [])
                raw_act = auto.get("action", [])
                proposal = NativeAutomationProposal(
                    alias=str(auto["alias"]),
                    description=str(auto.get("description", "")),
                    trigger=raw_trig if isinstance(raw_trig, list) else [raw_trig] if isinstance(raw_trig, dict) else [],
                    condition=raw_cond if isinstance(raw_cond, list) else [raw_cond] if isinstance(raw_cond, dict) else [],
                    action=raw_act if isinstance(raw_act, list) else [raw_act] if isinstance(raw_act, dict) else [],
                    discovered_pattern_rationale=str(auto.get("discovered_pattern_rationale", "")),
                )
                proposal = normalize_automation_proposal(
                    proposal=proposal,
                    available_services=available_services,
                    available_notify_services=available_notify,
                    preferred_notify_service=configured_notify,
                    known_entity_ids=set(corroborated.keys()),
                )
                cand_targets = proposal.extract_target_entities()
                if _is_duplicate_automation(cand_alias, cand_targets):
                    continue
                equivalent = find_equivalent_rule(
                    state.get("automation_rules", []),
                    {"alias": proposal.alias, "trigger": proposal.trigger, "condition": proposal.condition, "action": proposal.action},
                )
                if equivalent:
                    logger.info("Dropping proposal '%s': existing automation '%s' already does this.", cand_alias, equivalent)
                    continue
                if auto.get("pattern_id"):
                    proposal.source_pattern_id = str(auto["pattern_id"])
                all_targets = [f"automation.{proposal.automation_id}"] + cand_targets
                intents.append(
                    ActionIntent(
                        agent_id=agent_spec.agent_id,
                        area_id=state.get("area_id"),
                        domain="automation",
                        service="upsert_native_automation",
                        target_entity_ids=all_targets,
                        service_data=proposal.model_dump(),
                        cause_category=str(auto.get("cause_category", "crystallized_native_automation")),
                        rationale=proposal.discovered_pattern_rationale or proposal.description,
                        derived_signals_used=[d.signal_name for d in derived_signals],
                        priority=ActionPriority.HABIT_PREDICTION,
                        risk_level=ActionRiskLevel.MEDIUM,
                        native_automation=proposal,
                    )
                )

        # Also include any immediate parameter tuning actions proposed during batch analysis
        intents.extend(
            self._parse_action_intents(
                raw_actions=llm_response.get("actions", []),
                agent_id=agent_spec.agent_id,
                default_area_id=state.get("area_id"),
                available_notify_services=available_notify,
                preferred_notify_service=configured_notify,
            )
        )

        return {"proposed_intents": intents, "advisory_insights": insights}

    def _parse_action_intents(
        self,
        raw_actions: list[Any],
        agent_id: str,
        default_area_id: str | None,
        available_notify_services: list[str] | None = None,
        preferred_notify_service: str = "notify.notify",
    ) -> list[ActionIntent]:
        intents: list[ActionIntent] = []
        for item in raw_actions:
            if not isinstance(item, dict) or "domain" not in item or "service" not in item:
                continue

            priority_str = str(item.get("priority", "COMFORT_ENHANCEMENT")).upper()
            priority = ActionPriority.__members__.get(priority_str, ActionPriority.COMFORT_ENHANCEMENT)
            if priority > MAX_LLM_ACTION_PRIORITY:
                priority = MAX_LLM_ACTION_PRIORITY

            risk_str = str(item.get("risk_level", "low")).lower()
            try:
                risk = ActionRiskLevel(risk_str)
            except ValueError:
                risk = ActionRiskLevel.LOW

            raw_targets = item.get("target_entity_ids", [])
            if isinstance(raw_targets, str):
                raw_targets = [raw_targets]
            raw_sd = item.get("service_data", {})
            sd_dict = raw_sd if isinstance(raw_sd, dict) else {"value": raw_sd}
            raw_ds = item.get("derived_signals_used", [])
            if isinstance(raw_ds, str):
                raw_ds = [raw_ds]

            domain_val = str(item["domain"]).strip().lower()
            service_val = str(item["service"]).strip().lower()

            # Resolve notification services dynamically
            if domain_val == "notify" and available_notify_services:
                resolved = resolve_notification_service(
                    target_service=f"notify.{service_val}",
                    available_notify_services=available_notify_services,
                    preferred_service=preferred_notify_service,
                )
                domain_val, _, service_val = resolved.partition(".")

            intent = ActionIntent(
                agent_id=agent_id,
                area_id=item.get("area_id", default_area_id),
                domain=domain_val,
                service=service_val,
                target_entity_ids=[str(t) for t in raw_targets] if isinstance(raw_targets, list) else [],
                service_data=sd_dict,
                cause_category=str(item.get("cause_category", "autonomous_reaction")),
                rationale=str(item.get("rationale", "")),
                derived_signals_used=[str(d) for d in raw_ds] if isinstance(raw_ds, list) else [],
                priority=priority,
                risk_level=risk,
            )

            exp_raw = item.get("expected_outcome")
            if isinstance(exp_raw, dict) and "monitored_entity_id" in exp_raw:
                try:
                    intent.expected_outcome = ExpectedOutcome(
                        action_id=intent.intent_id,
                        agent_id=agent_id,
                        monitored_entity_id=str(exp_raw["monitored_entity_id"]),
                        baseline_value=exp_raw.get("baseline_value", ""),
                        expected_direction_or_target=str(exp_raw.get("expected_direction_or_target", "")),
                        check_after_minutes=max(1, int(exp_raw.get("check_after_minutes", 30))),
                    )
                except (TypeError, ValueError) as exc:
                    # A malformed optional field must not discard the whole proposed action.
                    logger.debug("Ignoring malformed expected_outcome %r: %s", exp_raw, exc)

            intents.append(intent)
        return intents


# Backward compatibility alias
ClimateAgentGraph = SpecializedAgentGraph
