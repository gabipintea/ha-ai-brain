"""Central Brain Orchestrator coordinating Triage, LangGraph Agents, Arbiter, Guardrails, and Memory."""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import time
from typing import Any
import uuid

from ha_ai_brain.application.agent_registry import AgentRegistry
from ha_ai_brain.application.graphs.specialized_agent import AgentGraphState, SpecializedAgentGraph
from ha_ai_brain.application.graphs.subagents import ComputationSubAgent, ResearchSubAgent
from ha_ai_brain.application.learning import LearningEngine
from ha_ai_brain.application.research_agenda import KnowledgeStore, ResearchAgenda
from ha_ai_brain.application.watch_service import WatchService
from ha_ai_brain.config import AutonomyLevel, BrainSettings, FallbackPolicy, OperatingMode
from ha_ai_brain.domain.agent_scope import agent_can_act, agent_has_scope
from ha_ai_brain.domain.arbiter import ConflictArbiter
from ha_ai_brain.domain.automation_rules import AutomationRule, RuleAction, _collect_actions, find_equivalent_rule, parse_automation_config
from ha_ai_brain.domain.expectations import ExceptionFinding, is_safety_entity
from ha_ai_brain.domain.min_change import MinChangeRule, find_rule, is_below_min_change
from ha_ai_brain.domain.lifecycle import AutomationReview, review_deployed_automation
from ha_ai_brain.domain.outcomes import evaluate_outcome
from ha_ai_brain.domain.patterns import automation_from_pattern
from ha_ai_brain.domain.timeutil import is_quiet_hours, parse_hhmm, parse_iso
from ha_ai_brain.domain.undo import build_undo_calls, capture_snapshot
from ha_ai_brain.domain.watches import WatchRule, WatchTracker, backtest_watch, evaluate_watch, validate_watch
from ha_ai_brain.domain.context import person_entities
from ha_ai_brain.domain.guardrails import GuardrailDecisionType, GuardrailEngine
from ha_ai_brain.domain.models import (
    ActionIntent,
    ActionPriority,
    ActionRiskLevel,
    AdvisoryInsight,
    AgentRunLog,
    AgentSpec,
    ApprovalRule,
    DerivedSignal,
    FeedbackEpisode,
    FeedbackPolarity,
    PendingApproval,
    SemanticEventFrame,
    StateChangedEvent,
    UserContextNote,
)
from ha_ai_brain.domain.service_resolver import normalize_automation_proposal
from ha_ai_brain.domain.triage import EdgeSignalTriage, matches_device_class_or_heuristics
from ha_ai_brain.ports.billing import LicensePort
from ha_ai_brain.ports.llm import LLMProviderPort
from ha_ai_brain.ports.mcp import McpClientPort
from ha_ai_brain.ports.memory import MemoryStorePort
from ha_ai_brain.ports.notification import NotificationPort
from ha_ai_brain.ports.research import ResearchPort
from ha_ai_brain.ports.sandbox import ComputationSandboxPort
from ha_ai_brain.ports.smart_home import SmartHomePort
from ha_ai_brain.ports.telemetry import TelemetryStorePort

MIN_CHANGE_KEY = "min_change_rules"
logger = logging.getLogger(__name__)

# True while handling a critical unusual situation: its approval requests must reach you even during quiet hours.
_URGENT_DISPATCH: ContextVar[bool] = ContextVar("urgent_dispatch", default=False)

# Unanswered approval requests expire after this long (an hours-old proposal no longer reflects the home state).
PENDING_APPROVAL_TTL_HOURS = 24


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
        telemetry: TelemetryStorePort | None = None,
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

        self.registry = registry or AgentRegistry(
            custom_agents_dir=settings.custom_agents_dir,
            bundled_agents_dir=settings.bundled_agents_dir,
        )
        self.triage = EdgeSignalTriage(manual_override_cooldown_seconds=settings.manual_override_cooldown_seconds)
        self.arbiter = ConflictArbiter(triage=self.triage)
        self.guardrails = GuardrailEngine()

        self.research_subagent = ResearchSubAgent(llm=llm, research_port=research)
        self.computation_subagent = ComputationSubAgent(llm=llm, sandbox=sandbox, memory=memory)
        if telemetry is None:
            from ha_ai_brain.adapters.telemetry_sqlite import SQLiteTelemetryStore

            telemetry = SQLiteTelemetryStore(":memory:")
        self.telemetry = telemetry
        self.learning = LearningEngine(settings, smart_home, telemetry, memory)
        self.watches = WatchService(memory, llm)
        self.research = ResearchAgenda(settings, llm, memory, smart_home, self.registry, self._budget_ok)
        self._watch_tracker = WatchTracker()
        self.agent_graph = SpecializedAgentGraph(
            smart_home=smart_home,
            llm=llm,
            memory=memory,
            research_subagent=self.research_subagent,
            computation_subagent=self.computation_subagent,
            telemetry=telemetry,
            knowledge_dir=settings.knowledge_dir,
        )

        # Wire mobile push notification action callback if supported by the smart_home adapter
        if hasattr(self.smart_home, "set_notification_action_handler"):
            self.smart_home.set_notification_action_handler(self._on_mobile_notification_action)

        self._background_tasks: list[asyncio.Task[Any]] = []
        self._action_tasks: set[asyncio.Task[Any]] = set()
        self._running = False
        self._cached_states: dict[str, Any] = {}
        self._next_batch_run_at: datetime | None = None
        self._last_batch_run_at: datetime | None = None
        self._action_times: deque[tuple[datetime, tuple[str, ...]]] = deque()
        self._token_day = ""
        self._tokens_today = 0
        self._last_total_tokens = 0
        self._deferred_approval_pushes: set[str] = set()
        self._deferred_insights: list[AdvisoryInsight] = []
        self._housekeeping_ticks = 0
        self._bootstrapped = False
        self._coalesce_last: dict[str, float] = {}
        self._coalesce_pending: dict[str, SemanticEventFrame] = {}
        self._coalesce_tasks: dict[str, asyncio.Task[Any]] = {}
        self._wake_times: dict[str, deque[float]] = {}
        self._ignored_cache: list[Any] = []
        self._ignored_cache_at = float("-inf")
        self._min_change_cache: list[MinChangeRule] = []
        self._min_change_cache_at = float("-inf")
        self._min_change_ref: dict[str, float] = {}
        if hasattr(self.memory, "get_ui_preferences_sync"):
            self._apply_ui_preferences_dict(self.memory.get_ui_preferences_sync())

    async def get_next_batch_run_at(self) -> datetime | None:
        """Return the calculated date & time of the next scheduled periodic batch analysis."""
        if self.settings.operating_mode == OperatingMode.REALTIME_STREAM:
            return None
        if self._next_batch_run_at:
            return self._next_batch_run_at
        last_run = await self.get_last_batch_run_at()
        interval = timedelta(minutes=self.settings.batch_interval_minutes)
        now = datetime.now(timezone.utc)
        if last_run:
            next_t = last_run + interval
            if next_t > now:
                return next_t
        return now + interval

    async def get_last_batch_run_at(self) -> datetime | None:
        """Return the timestamp when the most recent periodic batch run occurred."""
        if self._last_batch_run_at:
            return self._last_batch_run_at
        if hasattr(self.memory, "get_last_batch_run_time"):
            self._last_batch_run_at = await self.memory.get_last_batch_run_time()
        return self._last_batch_run_at

    async def _ignored_targets(self) -> list[Any]:
        """The ignore list changes rarely but is consulted on every single event: cache it for a minute."""
        if time.monotonic() - self._ignored_cache_at > 60.0:
            self._ignored_cache = await self.memory.get_ignored_targets()
            self._ignored_cache_at = time.monotonic()
        return self._ignored_cache

    async def get_min_change_rules(self) -> list[MinChangeRule]:
        if time.monotonic() - self._min_change_cache_at > 60.0:
            try:
                raw = json.loads(await self.memory.get_kv(MIN_CHANGE_KEY) or "[]")
                self._min_change_cache = [MinChangeRule.model_validate(r) for r in raw]
            except Exception as exc:
                logger.warning("Could not read minimum-change rules: %s", exc)
                self._min_change_cache = []
            self._min_change_cache_at = time.monotonic()
        return self._min_change_cache

    async def save_min_change_rules(self, rules: list[MinChangeRule]) -> None:
        await self.memory.set_kv(MIN_CHANGE_KEY, json.dumps([r.model_dump() for r in rules]))
        self._min_change_cache = rules
        self._min_change_cache_at = time.monotonic()
        self._min_change_ref.clear()

    def _below_user_min_change(self, rules: list[MinChangeRule], event: StateChangedEvent) -> bool:
        """True when the user set a minimum change for this entity and the value has not moved that far from the last accepted one."""
        rule = find_rule(rules, event.entity_id)
        value = event.new_state.numeric_value
        if rule is None or value is None:
            return False
        ref = self._min_change_ref.get(event.entity_id)
        if ref is None:
            ref = event.old_state.numeric_value if event.old_state is not None else None
        if ref is None or not is_below_min_change(rule, ref, value):
            self._min_change_ref[event.entity_id] = value
            return False
        self._min_change_ref[event.entity_id] = ref
        return True

    def invalidate_context_caches(self) -> None:
        """Notify agent graph to clear cached research findings and computations upon context or rule updates."""
        self._ignored_cache_at = float("-inf")
        self._min_change_cache_at = float("-inf")
        if hasattr(self.agent_graph, "invalidate_context_caches"):
            self.agent_graph.invalidate_context_caches()

    async def start_background_workers(self) -> None:
        """Start the live HA WebSocket stream listener and the Periodic Batch scheduler."""
        if self._running:
            return
        await self._restore_persisted_ui_preferences()
        self._running = True
        self._background_tasks = [
            asyncio.create_task(self._event_stream_worker_loop(), name="ha_ws_event_stream_worker"),
            asyncio.create_task(self._periodic_batch_scheduler_loop(), name="ha_periodic_batch_scheduler"),
            asyncio.create_task(self._bootstrap_then_housekeeping(), name="ha_learning_housekeeping"),
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
        try:
            await self.learning.flush()
        except Exception as exc:
            logger.debug("final telemetry flush failed: %s", exc)
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        for task in list(self._action_tasks):
            task.cancel()
        if self._action_tasks:
            await asyncio.gather(*list(self._action_tasks), return_exceptions=True)

    def spawn_background_task(self, coro: Any, name: str) -> asyncio.Task[Any]:
        """Run a fire-and-forget coroutine while keeping a strong reference (un-referenced tasks can be garbage collected)."""
        task = asyncio.create_task(coro, name=name)
        self._action_tasks.add(task)
        task.add_done_callback(self._action_tasks.discard)
        return task

    def _apply_ui_preferences_dict(self, prefs: dict[str, str]) -> None:
        """Apply persisted UI preferences to live settings and adapters."""
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
        self._apply_extended_preferences(prefs)
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

    _BOOL_PREFS = (
        "paused", "realtime_gating", "exception_detection", "privacy_scrub",
        "notify_autonomous_actions", "deterministic_automations", "research_enabled", "research_web_search",
    )
    _INT_PREFS = (
        "daily_token_budget", "max_actions_per_hour", "max_actions_per_entity_per_hour",
        "research_interval_days", "research_topics_per_agent",
        "realtime_coalesce_seconds", "max_agent_wakeups_per_hour",
    )

    def _apply_extended_preferences(self, prefs: dict[str, str]) -> None:
        for key in self._BOOL_PREFS:
            if key in prefs:
                setattr(self.settings, key, prefs[key].lower() == "true")
        for key in self._INT_PREFS:
            if key in prefs:
                try:
                    setattr(self.settings, key, max(0, int(prefs[key])))
                except ValueError:
                    pass
        for key in ("quiet_hours_start", "quiet_hours_end"):
            if key in prefs:
                setattr(self.settings, key, prefs[key])
        if "domain_autonomy" in prefs:
            try:
                raw = json.loads(prefs["domain_autonomy"])
                self.settings.domain_autonomy = {str(d): AutonomyLevel(v) for d, v in raw.items()}
            except (ValueError, TypeError, AttributeError):
                pass
        if hasattr(self.llm, "privacy_scrub"):
            self.llm.privacy_scrub = self.settings.privacy_scrub

    async def update_runtime_settings(self, changes: dict[str, Any]) -> None:
        """Validate, apply and persist the learning / safety settings editable from the dashboard."""
        for key in self._BOOL_PREFS:
            if changes.get(key) is not None:
                setattr(self.settings, key, bool(changes[key]))
                await self.memory.save_ui_preference(key, str(bool(changes[key])))
        for key in self._INT_PREFS:
            if changes.get(key) is not None:
                value = max(0, int(changes[key]))
                setattr(self.settings, key, value)
                await self.memory.save_ui_preference(key, str(value))
        for key in ("quiet_hours_start", "quiet_hours_end"):
            if changes.get(key) is not None:
                value = str(changes[key]).strip()
                if value and parse_hhmm(value) is None:
                    raise ValueError(f"{key} must be HH:MM")
                setattr(self.settings, key, value)
                await self.memory.save_ui_preference(key, value)
        if changes.get("domain_autonomy") is not None:
            mapping = {str(d).strip().lower(): AutonomyLevel(v) for d, v in dict(changes["domain_autonomy"]).items() if str(d).strip()}
            self.settings.domain_autonomy = mapping
            await self.memory.save_ui_preference("domain_autonomy", json.dumps({d: lvl.value for d, lvl in mapping.items()}))
        if hasattr(self.llm, "privacy_scrub"):
            self.llm.privacy_scrub = self.settings.privacy_scrub

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
                if self._running:
                    # Stream ended without an error (server closed the socket): back off instead of spinning.
                    logger.warning("HA event stream closed; reconnecting in %.1fs...", backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, 60.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("HA WebSocket stream disconnected (%s); reconnecting in %.1fs...", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    async def _initial_batch_delay_seconds(self) -> float:
        """Delay before the first batch after startup: honor the previous run so frequent restarts never re-spend LLM tokens."""
        interval = max(60.0, self.settings.batch_interval_minutes * 60.0)
        if not (self.settings.llm_api_key and not self.settings.use_simulator):
            return interval
        last_run = await self.get_last_batch_run_at()
        if last_run is None:
            return 3.0
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        since_last = (datetime.now(timezone.utc) - last_run).total_seconds()
        return max(3.0, interval - since_last)

    async def _expire_stale_approvals(self) -> None:
        """Expire approvals nobody answered within a day so they stop suppressing fresh proposals and clear their push cards."""
        try:
            expired_ids = await self.memory.expire_stale_pending_approvals(max_age_hours=PENDING_APPROVAL_TTL_HOURS)
        except Exception as exc:
            logger.warning("Could not expire stale pending approvals: %s", exc)
            return
        for approval_id in expired_ids:
            if hasattr(self.notification, "dismiss_approval_notification"):
                try:
                    await self.notification.dismiss_approval_notification(approval_id)
                except Exception:
                    pass
        if expired_ids:
            logger.info("Expired %d stale pending approvals (older than %dh).", len(expired_ids), PENDING_APPROVAL_TTL_HOURS)

    async def _periodic_batch_scheduler_loop(self) -> None:
        """Run periodic batch analysis `batch_interval_minutes` after the previous run (restart-aware)."""
        first_run = True
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                if first_run:
                    first_run = False
                    delay = await self._initial_batch_delay_seconds()
                else:
                    delay = max(60.0, self.settings.batch_interval_minutes * 60.0)
                self._next_batch_run_at = now + timedelta(seconds=delay)
                # Sleep towards the *current* target: a manual run moves it, and the loop must follow instead of firing on the old time.
                while self._running:
                    remaining = (self._next_batch_run_at - datetime.now(timezone.utc)).total_seconds()
                    if remaining <= 0:
                        break
                    await asyncio.sleep(min(remaining, 30.0))
                if not self._running:
                    break
                await self._expire_stale_approvals()
                if self.settings.operating_mode in (OperatingMode.PERIODIC_BATCH, OperatingMode.HYBRID):
                    quota = await self.llm.get_quota_status()
                    if quota.quota_exhausted and quota.cooldown_seconds_remaining > 0:
                        logger.warning(
                            "Skipping scheduled batch analysis: AI model quota cooldown active (%ds remaining).",
                            quota.cooldown_seconds_remaining,
                        )
                        continue
                    self._last_batch_run_at = datetime.now(timezone.utc)
                    try:
                        await self.run_pattern_cycle()
                    except Exception as habit_exc:
                        logger.error("Error during learned-habit scan: %s", habit_exc)
                    active_agents = self.registry.get_active_agents()
                    logger.info("Executing Periodic Batch Analysis across %d active specialized agents...", len(active_agents))
                    for agent in active_agents:
                        if not self._running:
                            break
                        try:
                            logger.info("Running Batch Analysis for agent: %s (%s)...", agent.name, agent.agent_id)
                            await self.run_periodic_batch_analysis(
                                agent_id=agent.agent_id,
                                lookback_hours=self.settings.batch_lookback_hours,
                                force=False,
                            )
                        except Exception as agent_exc:
                            logger.error("Error in periodic batch analysis for agent %s: %s", agent.agent_id, agent_exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in periodic batch scheduler: %s", exc)
                await asyncio.sleep(30.0)

    async def _on_mobile_notification_action(self, approval_id: str, decision: str) -> None:
        """Callback triggered when a user taps Approve Once / Always Allow / Reject on their phone."""
        try:
            if decision == "undo":
                await self.handle_undo(approval_id)
                return
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

        ignored_targets = await self._ignored_targets()
        if ignored_targets and any(t.matches(event.entity_id) for t in ignored_targets):
            return []

        # 4. Deadband / Significance Filtering
        frames, implicit_feedback = self.triage.evaluate_event(
            event=event,
            all_states=all_states,
            agents=self.registry.list_agents(),
            ignored_targets=ignored_targets,
        )

        if frames:
            min_rules = await self.get_min_change_rules()
            if min_rules and self._below_user_min_change(min_rules, event):
                frames = []

        old_val = event.old_state.state if event.old_state else "?"
        if frames:
            logger.debug(
                "[LIVE EVENT -> SIGNIFICANT] %s (area=%s, origin=%s): '%s' -> '%s' | Routed to: %s",
                event.entity_id,
                event.new_state.area_id or "unassigned",
                event.origin.value,
                old_val,
                event.new_state.state,
                [f.target_agent_id for f in frames],
            )
        else:
            logger.debug(
                "[LIVE EVENT -> FILTERED] %s (area=%s, origin=%s): '%s' -> '%s'",
                event.entity_id,
                event.new_state.area_id or "unassigned",
                event.origin.value,
                old_val,
                event.new_state.state,
            )

        if implicit_feedback is not None:
            await self.memory.save_feedback(implicit_feedback)

        # Learning is local and cheap: every relevant transition is recorded, whatever the operating mode.
        await self.learning.record_event(event)

        if self.settings.operating_mode == OperatingMode.PERIODIC_BATCH or self.settings.paused:
            # Pure Periodic Batch mode and the kill switch: live events are learned from but never sent to LLM agents
            return []

        run_logs: list[AgentRunLog] = []
        now = datetime.now(timezone.utc)
        for frame in frames:
            wake, why = await self.learning.should_wake_agent(frame, now)
            if not wake:
                self.learning.stats["llm_calls_avoided"] += 1
                self.learning.stats[f"avoided:{frame.target_agent_id}"] += 1
                logger.debug("[GATED -> NO LLM CALL] %s", why)
                continue
            log = await self._run_or_coalesce(frame)
            if log is not None:
                run_logs.append(log)
        return run_logs

    # --------------------------------------------------------------------------------------------- real-time discipline
    def _frame_is_urgent(self, frame: SemanticEventFrame) -> bool:
        """Safety-relevant events are never delayed, coalesced or capped."""
        if _URGENT_DISPATCH.get():
            return True
        return bool(frame.trigger_events) and is_safety_entity(frame.trigger_events[0].new_state)

    async def _run_or_coalesce(self, frame: SemanticEventFrame) -> AgentRunLog | None:
        """
        Burst control: the first event for an (agent, area) runs immediately; further events inside the window are merged
        into ONE trailing run that sees the latest state. Without this, a single physical change that produces several
        events would be sent to the AI several times.
        """
        window = self.settings.realtime_coalesce_seconds
        if window <= 0 or self._frame_is_urgent(frame):
            return await self._run_agent_for_frame(frame)
        key = f"{frame.target_agent_id}:{frame.area_id or 'global'}"
        now = time.monotonic()
        last = self._coalesce_last.get(key)
        if last is None or now - last >= window:
            self._coalesce_last[key] = now
            return await self._run_agent_for_frame(frame)
        self._coalesce_pending[key] = frame  # keep only the latest
        self.learning.stats["events_coalesced"] += 1
        if key not in self._coalesce_tasks:
            self._coalesce_tasks[key] = self.spawn_background_task(self._trailing_run(key, window - (now - last)), f"ha_coalesce_{key}")
        return None

    async def _trailing_run(self, key: str, delay: float) -> None:
        try:
            await asyncio.sleep(max(0.0, delay))
        finally:
            frame = self._coalesce_pending.pop(key, None)
            self._coalesce_tasks.pop(key, None)
        if frame is not None:
            self._coalesce_last[key] = time.monotonic()
            try:
                await self._run_agent_for_frame(frame)
            except Exception as exc:
                logger.error("Trailing agent run for %s failed: %s", key, exc)

    def _wake_allowed(self, agent_id: str, frame: SemanticEventFrame) -> bool:
        """Per-agent hourly cap on real-time AI wake-ups (safety events and critical exceptions are exempt)."""
        cap = self.settings.max_agent_wakeups_per_hour
        if cap <= 0 or self._frame_is_urgent(frame):
            return True
        times = self._wake_times.setdefault(agent_id, deque())
        now = time.monotonic()
        while times and now - times[0] > 3600:
            times.popleft()
        if len(times) >= cap:
            return False
        times.append(now)
        return True

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

        if self.settings.paused:
            return None
        if not agent_can_act(agent_spec, frame.corroborated_states):
            # Nothing in this context that the agent can operate: an AI call could only produce a message.
            self.learning.stats["wakeups_skipped_no_actuator"] += 1
            logger.debug("Not waking %s: no device it can operate in the context of '%s'.", agent_spec.agent_id, frame.significance_reason[:80])
            return None
        if not self._wake_allowed(agent_spec.agent_id, frame):
            self.learning.stats["wakeups_capped"] += 1
            logger.info("Agent %s reached its hourly cap of %d real-time wake-ups; skipping.", agent_spec.agent_id, self.settings.max_agent_wakeups_per_hour)
            return None
        if await self._budget_exhausted():
            logger.warning("Daily LLM token budget reached; skipping agent %s.", agent_spec.agent_id)
            self.learning.stats["budget_skipped"] += 1
            return None

        available_services = await self.smart_home.get_available_services()
        available_notify = await self.smart_home.get_available_notify_services()

        initial_state: AgentGraphState = {
            "agent_spec": agent_spec,
            "household_context": await self.learning.household(self._cached_states or {}, datetime.now(timezone.utc)),
            "automation_rules": self.learning.rules,
            "site_context": self.settings.site_context,
            "mode": "realtime_stream",
            "area_id": frame.area_id,
            "trigger_summary": frame.significance_reason,
            "corroborated_states": frame.corroborated_states,
            "available_services": available_services,
            "available_notify_services": available_notify,
            "configured_notify_service": self.settings.notification_service,
        }

        final_state = await self.agent_graph.ainvoke(initial_state)
        intents = final_state.get("proposed_intents", [])
        insights = final_state.get("advisory_insights", [])
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        for intent in intents:
            intent.run_id = run_id
        for insight in insights:
            insight.run_id = run_id

        exec_results = await self._evaluate_and_dispatch_intents(intents, run_id=run_id)

        run_log = AgentRunLog(
            run_id=run_id,
            agent_id=agent_spec.agent_id,
            mode="realtime_stream",
            trigger_summary=frame.significance_reason,
            research_findings=final_state.get("research_findings", []),
            derived_signals=final_state.get("derived_signals", []),
            proposed_intents=intents,
            advisory_insights=insights,
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

    async def _batch_fingerprint(self, agent_spec: AgentSpec, filtered_states: dict[str, Any], patterns: list[Any]) -> str:
        """
        Hash of the things that change *what could be recommended*: which entities and automations exist, your notes,
        ignore list and site context, and which habits are still un-automated. Momentary states are deliberately excluded
        (a light being on tonight does not warrant a new analysis); activity is judged separately by counting events.
        """
        notes = await self.memory.get_user_context_notes(active_only=True)
        ignored = await self.memory.get_ignored_targets()
        material = [
            agent_spec.agent_id,
            sorted(filtered_states),
            sorted((r.alias, r.enabled) for r in self.learning.rules),
            sorted(n.note_id for n in notes),
            sorted(t.pattern for t in ignored),
            sorted(p.pattern_id for p in patterns if not p.covered_by),
            self.settings.site_context,
        ]
        return hashlib.sha1(json.dumps(material, default=str).encode()).hexdigest()

    async def run_periodic_batch_analysis(
        self,
        agent_id: str = "climate_thermal_agent",
        area_id: str | None = None,
        lookback_hours: int | None = None,
        force: bool = True,
    ) -> AgentRunLog:
        """
        Execute Mode B: Periodic / On-Demand Batch Analysis across historical entity states.

        Step 1: Discover all available entities in Home Assistant via smart_home.get_all_states().
        Step 2: Filter entities matching the target agent's monitored and controllable domains.
        Step 3: Summarise historical trajectories over [now - lookback_hours, now] locally and gather learned context
                (mined habits, household presence, weather / tariff data, curated reference guidance).
        Step 4: Execute Research Sub-Agent, Computation Sub-Agent, and LLM synthesis to produce
                advisory insights and native Home Assistant automations, then backtest every proposed
                automation against the recorded history before it reaches the homeowner.

        `force=False` (scheduler) skips agents whose inputs have not meaningfully changed since their last run.
        """
        agent_spec = self.registry.get_agent(agent_id)
        if not agent_spec:
            raise ValueError(f"Unknown agent_id: {agent_id}")
        if not force and await self._budget_exhausted():
            logger.warning("Daily LLM token budget reached; skipping scheduled batch for %s.", agent_spec.name)
            self.learning.stats["budget_skipped"] += 1
            return AgentRunLog(agent_id=agent_id, mode="periodic_batch", trigger_summary="Skipped: daily token budget reached")

        effective_lookback = lookback_hours or getattr(self.settings, "batch_lookback_hours", 24)
        all_states = await self.smart_home.get_all_states()
        self._cached_states = all_states  # keeps redundancy / target validation current between event bursts
        ignored_targets = await self.memory.get_ignored_targets()
        filtered_states: dict[str, Any] = {}
        for eid, st in all_states.items():
            if ignored_targets and any(t.matches(eid) for t in ignored_targets):
                continue
            if area_id and st.area_id != area_id and st.domain not in ("weather", "automation", "sun") and "outdoor" not in eid:
                continue
            if st.domain == "automation":
                filtered_states[eid] = st
            elif st.domain in agent_spec.monitored_domains or st.domain in agent_spec.controllable_domains:
                if st.domain == "sensor" and agent_spec.monitored_device_classes:
                    if matches_device_class_or_heuristics(st, agent_spec.monitored_device_classes):
                        filtered_states[eid] = st
                else:
                    filtered_states[eid] = st

        in_scope, why_not = agent_has_scope(agent_spec, all_states)
        if not in_scope:
            self.learning.stats["batch_skipped_no_scope"] += 1
            logger.info("Batch for %s skipped: %s.", agent_spec.name, why_not)
            return AgentRunLog(agent_id=agent_spec.agent_id, mode="periodic_batch", trigger_summary=f"Skipped: {why_not} (no tokens used)")

        now = datetime.now(timezone.utc)
        await self.learning.refresh_rules(all_states)
        patterns = await self.learning.get_patterns(now, all_states)

        fp_key = f"batchfp:{agent_spec.agent_id}:{area_id or 'all'}"
        fingerprint = await self._batch_fingerprint(agent_spec, filtered_states, patterns)
        scope_ids = [e for e, st in filtered_states.items() if st.domain != "automation"]
        idle_runs = 0
        try:
            prev = json.loads(await self.memory.get_kv(fp_key) or "{}")
            idle_runs = int(prev.get("idle", 0))
            prev_ts = parse_iso(prev.get("ts"))
            if not force and prev.get("fp") == fingerprint and prev_ts is not None:
                # Same entities / automations / notes. Skip while little happened in this agent's scope; after runs that
                # found nothing new, allow ever longer quiet periods (up to 48 h) and need more activity to wake up again.
                max_age = timedelta(hours=24 * (2 if idle_runs >= 2 else 1))
                await self.learning.flush()
                events = await self.telemetry.count_since(prev_ts, scope_ids)
                if now - prev_ts < max_age and events < min(25 * (1 + idle_runs), 200):
                    self.learning.stats["batch_skipped_unchanged"] += 1
                    logger.info("Batch for %s skipped: nothing relevant changed since %s (%d events in scope).", agent_spec.name, prev_ts.isoformat(), events)
                    return AgentRunLog(
                        agent_id=agent_spec.agent_id,
                        mode="periodic_batch",
                        trigger_summary="Skipped: nothing relevant changed since the last analysis (no tokens used)",
                    )
        except Exception as exc:
            logger.debug("batch fingerprint check failed: %s", exc)

        start_time = now - timedelta(hours=effective_lookback)
        logger.info(
            "Starting Batch Analysis for agent '%s' across %d domain entities over past %d hours (window: %s to %s)...",
            agent_spec.name,
            len(filtered_states),
            effective_lookback,
            start_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

        available_services = await self.smart_home.get_available_services()
        available_notify = await self.smart_home.get_available_notify_services()
        relevant_domains = set(agent_spec.controllable_domains) | set(agent_spec.monitored_domains)
        pattern_dicts = [
            p.to_dict()
            for p in patterns
            if not p.covered_by and p.entity_id.split(".", 1)[0] in relevant_domains and p.entity_id in all_states
        ][:12]

        initial_state: AgentGraphState = {
            "agent_spec": agent_spec,
            "site_context": self.settings.site_context,
            "mode": "periodic_batch",
            "lookback_hours": effective_lookback,
            "area_id": area_id,
            "trigger_summary": f"Periodic/Manual Batch Analysis for {agent_spec.name} ({effective_lookback}h lookback)",
            "corroborated_states": filtered_states,
            "available_services": available_services,
            "available_notify_services": available_notify,
            "configured_notify_service": self.settings.notification_service,
            "household_context": await self.learning.household(all_states, now),
            "mined_patterns": pattern_dicts,
            "automation_rules": self.learning.rules,
            "patterns_handled_by_system": self.settings.deterministic_automations,
        }

        final_state = await self.agent_graph.ainvoke(initial_state)
        intents = final_state.get("proposed_intents", [])
        insights = final_state.get("advisory_insights", [])
        run_id = f"run_{uuid.uuid4().hex[:8]}"

        for insight in insights:
            insight.run_id = run_id
            await self.memory.save_advisory_insight(insight)
            await self._notify_insight(insight)

        for intent in intents:
            intent.run_id = run_id

        await self._attach_backtests(intents, now)
        exec_results = await self._evaluate_and_dispatch_intents(intents, run_id=run_id)

        run_log = AgentRunLog(
            run_id=run_id,
            agent_id=agent_spec.agent_id,
            mode="periodic_batch",
            trigger_summary=f"Batch Historical Analysis ({len(filtered_states)} relevant entities analyzed over {effective_lookback}h)",
            research_findings=final_state.get("research_findings", []),
            derived_signals=final_state.get("derived_signals", []),
            proposed_intents=intents,
            advisory_insights=insights,
            execution_results=exec_results,
        )
        self._log_agent_run_summary(run_log)
        await self.memory.save_run_log(run_log)
        useful = bool(insights) or any(r.get("status") in ("awaiting_user_approval", "executed") for r in exec_results)
        try:
            await self.memory.set_kv(
                fp_key,
                json.dumps({"fp": fingerprint, "ts": datetime.now(timezone.utc).isoformat(), "idle": 0 if useful else idle_runs + 1}),
            )
        except Exception as exc:
            logger.debug("could not persist batch fingerprint: %s", exc)
        self._last_batch_run_at = datetime.now(timezone.utc)
        if self.settings.operating_mode != OperatingMode.REALTIME_STREAM:
            self._next_batch_run_at = self._last_batch_run_at + timedelta(minutes=self.settings.batch_interval_minutes)
        return run_log

    async def run_all_periodic_batch_analyses(
        self,
        lookback_hours: int | None = None,
        area_id: str | None = None,
    ) -> list[AgentRunLog]:
        """Run the learned-habit scan and then batch analysis sequentially across all active registered agents."""
        logs: list[AgentRunLog] = []
        try:
            habit_log = await self.run_pattern_cycle()
            if habit_log is not None:
                logs.append(habit_log)
        except Exception as exc:
            logger.error("Error during learned-habit scan: %s", exc)
        for agent in self.registry.get_active_agents():
            try:
                log = await self.run_periodic_batch_analysis(
                    agent_id=agent.agent_id,
                    area_id=area_id,
                    lookback_hours=lookback_hours,
                )
                logs.append(log)
            except Exception as exc:
                logger.error("Error during batch analysis for agent '%s': %s", agent.agent_id, exc)
        return logs

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
            # `light.turn_on` with brightness/colour etc. changes an already-on light, so only bare calls can be no-ops.
            has_parameters = any(k != "entity_id" for k in intent.service_data)
            if intent.service in ("turn_off", "turn_on") and not (intent.service == "turn_on" and has_parameters):
                target_state = "off" if intent.service == "turn_off" else "on"
                if all(
                    self._cached_states.get(eid) and self._cached_states[eid].state == target_state
                    for eid in intent.target_entity_ids
                ):
                    return True, f"All target entities are already {target_state}."

        return False, ""

    @staticmethod
    def _automations_equivalent(a: Any, b: Any) -> bool:
        def dump(p: Any) -> dict[str, Any]:
            return {"alias": p.alias, "trigger": p.trigger, "condition": p.condition, "action": p.action}

        return find_equivalent_rule([parse_automation_config(dump(a))], dump(b)) is not None

    def _unknown_target_entities(self, intent: ActionIntent) -> list[str]:
        """Return targets missing from the known entity cache (skipped when the cache is empty or for non-entity domains)."""
        if not self._cached_states or intent.domain in ("automation", "notify") or not intent.target_entity_ids:
            return []
        return [eid for eid in intent.target_entity_ids if eid not in self._cached_states]

    async def _evaluate_and_dispatch_intents(
        self, intents: list[ActionIntent], run_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Pass proposed ActionIntents through the Conflict Arbiter and Guardrail Engine."""
        results: list[dict[str, Any]] = []
        endorsed_rules = await self.memory.get_endorsed_rules()
        rejected_signatures = await self.memory.get_rejected_signatures()
        active_pending = await self.memory.get_pending_approvals()

        for intent in intents:
            # -1. Agents may only act through the domains they are declared to control
            agent_spec = self.registry.get_agent(intent.agent_id)
            if agent_spec is not None and intent.domain not in agent_spec.controllable_domains:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": intent.repeatable_signature(),
                        "status": "blocked_domain_not_permitted",
                        "reason": f"Agent '{intent.agent_id}' is not permitted to call the '{intent.domain}' domain.",
                    }
                )
                continue

            # -0.5. Never act on entities that do not exist (hallucinated ids); automations/notifications target no real entity
            unknown_targets = self._unknown_target_entities(intent)
            if unknown_targets:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": intent.repeatable_signature(),
                        "status": "invalid_target",
                        "reason": f"Unknown Home Assistant entities: {unknown_targets}.",
                    }
                )
                continue

            # -0.4. Automations whose replay against the household's own history shows they do not match its behaviour
            if intent.backtest is not None and intent.backtest.verdict == "weak" and intent.native_automation is not None:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": intent.repeatable_signature(),
                        "status": "dropped_weak_backtest",
                        "reason": intent.backtest.summary,
                    }
                )
                continue

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
                if intent.native_automation is not None and p.intent.native_automation is not None:
                    # Two different automations may legitimately control the same device (e.g. "on at 18:00", "off at 23:00").
                    if p.signature == intent.repeatable_signature() or self._automations_equivalent(
                        p.intent.native_automation, intent.native_automation
                    ):
                        results.append(
                            {
                                "intent_id": intent.intent_id,
                                "signature": intent.repeatable_signature(),
                                "status": "suppressed_duplicate_pending",
                                "reason": f"An equivalent automation is already pending user approval (ID: {p.approval_id[:8]}).",
                            }
                        )
                        conflict_found = True
                        break
                    continue
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

            # 3. Deterministic Guardrail & Repeatable Approval Check (per-domain autonomy; kill switch = shadow)
            autonomy = (
                AutonomyLevel.SHADOW
                if self.settings.paused
                else self.settings.domain_autonomy.get(intent.domain, self.settings.default_autonomy)
            )
            eval_res = self.guardrails.evaluate(
                intent=intent,
                autonomy_level=autonomy,
                notifications_enabled=self.settings.notifications_enabled,
                endorsed_rules=endorsed_rules,
                rejected_signatures=rejected_signatures,
            )
            decision = eval_res.decision
            reason = eval_res.reason

            # 3b. Safety rails: never let a runaway loop actuate the house - excess actions go to the human instead
            if decision == GuardrailDecisionType.EXECUTE_IMMEDIATELY and intent.domain != "notify":
                limited = self._rate_limited(intent)
                if limited:
                    decision = GuardrailDecisionType.REQUIRE_USER_APPROVAL
                    reason = f"{reason} Held for approval: {limited}"
                    self.learning.stats["rate_limited"] += 1

            if decision == GuardrailDecisionType.HARD_BLOCKED:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": eval_res.signature,
                        "status": "hard_blocked",
                        "reason": reason,
                    }
                )
            elif decision == GuardrailDecisionType.SHADOW_LOG_ONLY:
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": eval_res.signature,
                        "status": "shadow_logged",
                        "reason": reason,
                    }
                )
            elif decision == GuardrailDecisionType.REQUIRE_USER_APPROVAL:
                effective_run_id = run_id or intent.run_id
                pending = PendingApproval(
                    intent=intent,
                    signature=eval_res.signature,
                    run_id=effective_run_id,
                )
                intent.approval_id = pending.approval_id
                await self.memory.save_pending_approval(pending)
                # Later intents in this same batch must see it, or identical/opposing proposals would pile up.
                active_pending.append(pending)
                if self.settings.notifications_enabled:
                    if (
                        self._in_quiet_hours()
                        and not _URGENT_DISPATCH.get()
                        and eval_res.effective_risk not in (ActionRiskLevel.HIGH, ActionRiskLevel.CRITICAL)
                    ):
                        self._deferred_approval_pushes.add(pending.approval_id)
                    else:
                        await self.notification.send_approval_request(pending)
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "approval_id": pending.approval_id,
                        "run_id": effective_run_id,
                        "signature": eval_res.signature,
                        "status": "awaiting_user_approval",
                        "reason": reason,
                    }
                )
            elif decision == GuardrailDecisionType.EXECUTE_IMMEDIATELY:
                snapshot = (
                    capture_snapshot(self._cached_states, intent.target_entity_ids)
                    if self.settings.notify_autonomous_actions and intent.domain not in ("notify", "automation")
                    else {}
                )
                exec_out = await self._execute_intent(intent)
                self._record_action(intent)
                if eval_res.matched_rule is not None:
                    await self.memory.increment_rule_usage(eval_res.signature)
                elif self.settings.notify_autonomous_actions and intent.domain not in ("notify", "automation") and exec_out.get("status") != "error":
                    # Always tell the human; the Undo button only exists for actions that can be safely reverted.
                    await self._announce_autonomous_action(intent, snapshot, eval_res.signature)
                results.append(
                    {
                        "intent_id": intent.intent_id,
                        "signature": eval_res.signature,
                        "status": "executed",
                        "reason": reason,
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
                available_services = await self.smart_home.get_available_services()
                available_notify = await self.smart_home.get_available_notify_services()
                intent.native_automation = normalize_automation_proposal(
                    proposal=intent.native_automation,
                    available_services=available_services,
                    available_notify_services=available_notify,
                    preferred_notify_service=self.settings.notification_service,
                    known_entity_ids=set(self._cached_states.keys()),
                )
                res = await self.smart_home.upsert_automation(intent.native_automation)
                await self.learning.refresh_rules(self._cached_states, force=True)
            elif intent.domain == "notify":
                # Strictly use the single notification service chosen by the user in Settings / UI
                if hasattr(self.notification, "_resolve_service_name"):
                    domain, notify_service = await self.notification._resolve_service_name()
                else:
                    domain, _, configured_notify_svc = self.settings.notification_service.partition(".")
                    notify_service = configured_notify_svc or "notify"
                    domain = domain or "notify"
                payload = dict(intent.service_data)
                if "title" not in payload:
                    payload["title"] = "🧠 AI Brain Notice"
                if "message" not in payload:
                    payload["message"] = intent.rationale
                panel_path = "/ha_ai_brain"
                if hasattr(self.smart_home, "get_addon_panel_path"):
                    try:
                        panel_path = await self.smart_home.get_addon_panel_path()
                    except Exception:
                        panel_path = "/ha_ai_brain"
                data = dict(payload.get("data") or {})
                data.setdefault("url", panel_path)
                data.setdefault("clickAction", panel_path)
                payload["data"] = data
                try:
                    res = await self.smart_home.call_service(
                        domain=domain,
                        service=notify_service,
                        target_entity_ids=[],
                        service_data=payload,
                        context_id=context_id,
                    )
                except Exception as exc:
                    logger.warning("Service call %s.%s failed: %s; falling back to notify.notify", domain, notify_service, exc)
                    res = await self.smart_home.call_service(
                        domain="notify",
                        service="notify",
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
            self.invalidate_context_caches()
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
        self.invalidate_context_caches()

        return {
            "approval_id": approval_id,
            "status": decision,
            "signature": signature,
            "repeatable_rule_saved": decision == "approved_repeatable",
            "service_output": exec_res,
        }

    async def get_pending_approvals(self) -> list[PendingApproval]:
        """Fetch active pending approvals and ensure native automation actions are normalized against discovered services."""
        pending = await self.memory.get_pending_approvals()
        if not pending:
            return []
        try:
            available_services = await self.smart_home.get_available_services()
            available_notify = await self.smart_home.get_available_notify_services()
            pref_notify = self.settings.notification_service
            for p in pending:
                if p.intent and p.intent.domain == "automation" and p.intent.native_automation:
                    p.intent.native_automation = normalize_automation_proposal(
                        proposal=p.intent.native_automation,
                        available_services=available_services,
                        available_notify_services=available_notify,
                        preferred_notify_service=pref_notify,
                        known_entity_ids=set(self._cached_states.keys()),
                    )
                    p.intent.service_data = p.intent.native_automation.model_dump()
        except Exception as exc:
            logger.warning("Could not normalize pending approval automation actions: %s", exc)
        return pending

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

    # ==================================================================================================
    # Safety rails: quiet hours, rate limits, token budget, undo
    # ==================================================================================================
    def _in_quiet_hours(self, now: datetime | None = None) -> bool:
        local = self.learning.local_now(now or datetime.now(timezone.utc))
        return is_quiet_hours(local, self.settings.quiet_hours_start, self.settings.quiet_hours_end)

    async def _notify_insight(self, insight: AdvisoryInsight, *, urgent: bool = False, even_in_shadow: bool = False) -> None:
        """Push an insight honoring notification preferences, shadow mode and quiet hours."""
        if not self.settings.notifications_enabled:
            return
        if self.settings.default_autonomy == AutonomyLevel.SHADOW and not even_in_shadow:
            return
        if not urgent and self._in_quiet_hours():
            self._deferred_insights = (self._deferred_insights + [insight])[-20:]
            return
        try:
            if urgent:
                await self.notification.send_advisory_alert(insight, urgent=True)
            else:
                await self.notification.send_advisory_alert(insight)
        except Exception as exc:
            logger.warning("Could not dispatch advisory notification: %s", exc)

    async def _flush_deferred(self) -> None:
        """Deliver pushes that were held back during quiet hours."""
        if self._in_quiet_hours() or not (self._deferred_approval_pushes or self._deferred_insights):
            return
        if self._deferred_approval_pushes:
            ids, self._deferred_approval_pushes = self._deferred_approval_pushes, set()
            for pending in await self.memory.get_pending_approvals():
                if pending.approval_id in ids and self.settings.notifications_enabled:
                    await self.notification.send_approval_request(pending)
        insights, self._deferred_insights = self._deferred_insights, []
        for insight in insights:
            await self._notify_insight(insight)

    async def _tokens_used_today(self) -> int:
        day = datetime.now(timezone.utc).date().isoformat()
        try:
            quota = await self.llm.get_quota_status()
        except Exception:
            return self._tokens_today
        total = quota.prompt_tokens_session + quota.completion_tokens_session
        if day != self._token_day:
            self._token_day = day
            try:
                self._tokens_today = int(await self.memory.get_kv(f"tokens:{day}") or 0)
            except ValueError:
                self._tokens_today = 0
            self._last_total_tokens = total
        delta = total - self._last_total_tokens if total >= self._last_total_tokens else total
        self._last_total_tokens = total
        if delta > 0:
            self._tokens_today += delta
            await self.memory.set_kv(f"tokens:{day}", str(self._tokens_today))
        return self._tokens_today

    async def _budget_exhausted(self) -> bool:
        budget = self.settings.daily_token_budget
        return budget > 0 and await self._tokens_used_today() >= budget

    def _rate_limited(self, intent: ActionIntent) -> str:
        """Non-empty explanation when executing `intent` now would exceed the hourly action caps."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        while self._action_times and self._action_times[0][0] < cutoff:
            self._action_times.popleft()
        if len(self._action_times) >= self.settings.max_actions_per_hour:
            return f"hourly cap of {self.settings.max_actions_per_hour} autonomous actions reached"
        for eid in intent.target_entity_ids:
            if sum(1 for _, ents in self._action_times if eid in ents) >= self.settings.max_actions_per_entity_per_hour:
                return f"{eid} already changed {self.settings.max_actions_per_entity_per_hour} times in the last hour"
        return ""

    def _record_action(self, intent: ActionIntent) -> None:
        if intent.domain != "notify":
            self._action_times.append((datetime.now(timezone.utc), tuple(intent.target_entity_ids)))

    async def _announce_autonomous_action(self, intent: ActionIntent, snapshot: dict[str, Any], signature: str) -> None:
        """Remember how to revert an action the brain took on its own and tell the human, with an Undo button."""
        calls = build_undo_calls(snapshot)
        undo_id = uuid.uuid4().hex[:12] if calls else None
        if undo_id:
            record = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "summary": f"{intent.domain}.{intent.service} on {', '.join(intent.target_entity_ids)}",
                "agent_id": intent.agent_id,
                "area_id": intent.area_id,
                "cause_category": intent.cause_category,
                "signature": signature,
                "service_called": f"{intent.domain}.{intent.service}",
                "target_entity_ids": intent.target_entity_ids,
                "calls": calls,
            }
            await self.memory.set_kv(f"undo:{undo_id}", json.dumps(record))
        if self.settings.notifications_enabled and not self._in_quiet_hours():
            try:
                await self.notification.send_action_taken(intent, undo_id)
            except Exception as exc:
                logger.debug("could not send action notice: %s", exc)

    async def list_undo_records(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for key, raw in (await self.memory.list_kv("undo:")).items():
            try:
                rec = json.loads(raw)
                created = parse_iso(rec["created_at"])
            except (ValueError, KeyError):
                continue
            if created is None or created < cutoff:
                await self.memory.delete_kv(key)
                continue
            out.append({"undo_id": key.split(":", 1)[1], "created_at": rec["created_at"], "summary": rec.get("summary", "")})
        return sorted(out, key=lambda r: r["created_at"], reverse=True)[:10]

    async def handle_undo(self, undo_id: str) -> dict[str, Any]:
        """Revert an autonomous action and teach the brain that the human disagreed."""
        raw = await self.memory.get_kv(f"undo:{undo_id}")
        if not raw:
            raise KeyError(f"Undo record '{undo_id}' not found or expired")
        rec = json.loads(raw)
        created = parse_iso(rec.get("created_at"))
        if created is None or datetime.now(timezone.utc) - created > timedelta(hours=24):
            await self.memory.delete_kv(f"undo:{undo_id}")
            raise ValueError("This action is too old to undo automatically")
        await self.memory.delete_kv(f"undo:{undo_id}")  # exactly once
        reverted: list[str] = []
        for call in rec["calls"]:
            context_id = f"ai_brain_{uuid.uuid4().hex[:12]}"
            self.triage.register_ai_action(
                context_id=context_id,
                entity_ids=call["entity_ids"],
                agent_id=rec.get("agent_id", "undo"),
                cause_category="undo",
                action_signature=rec.get("signature", "undo"),
                service_called=f"{call['domain']}.{call['service']}",
                service_data=call["service_data"],
            )
            try:
                await self.smart_home.call_service(
                    domain=call["domain"],
                    service=call["service"],
                    target_entity_ids=call["entity_ids"],
                    service_data=call["service_data"],
                    context_id=context_id,
                )
                reverted.extend(call["entity_ids"])
            except Exception as exc:
                logger.warning("Undo call %s.%s failed: %s", call["domain"], call["service"], exc)
        for eid in rec.get("target_entity_ids", []):
            self.triage.mark_manual_override(eid)
        await self.memory.save_feedback(
            FeedbackEpisode(
                agent_id=rec.get("agent_id", "undo"),
                area_id=rec.get("area_id"),
                cause_category=rec.get("cause_category", "undo"),
                action_signature=rec.get("signature", "undo"),
                target_entity_ids=rec.get("target_entity_ids", []),
                service_called=rec.get("service_called", ""),
                polarity=FeedbackPolarity.OVERRIDDEN_IMPLICIT,
                human_note="The homeowner undid this autonomous action; do not repeat it in similar situations.",
            )
        )
        self.invalidate_context_caches()
        self.learning.stats["undone"] += 1
        return {"undo_id": undo_id, "status": "undone", "reverted": sorted(set(reverted))}

    # ==================================================================================================
    # Backtesting and learned-habit automations (no LLM involved)
    # ==================================================================================================
    async def _attach_backtests(self, intents: list[ActionIntent], now: datetime) -> None:
        for intent in intents:
            if intent.native_automation is not None and intent.backtest is None:
                try:
                    intent.backtest = await self.learning.backtest(intent.native_automation, now)
                except Exception as exc:
                    logger.warning("Backtest failed for '%s': %s", intent.native_automation.alias, exc)

    def _agent_for_automation(self, domain: str) -> str:
        for agent in self.registry.get_active_agents():
            if "automation" in agent.controllable_domains and domain in agent.controllable_domains:
                return agent.agent_id
        for agent in self.registry.get_active_agents():
            if "automation" in agent.controllable_domains:
                return agent.agent_id
        return "pattern_miner"

    async def run_pattern_cycle(self) -> AgentRunLog | None:
        """Turn strong, un-automated recurring habits into automation proposals using statistics only (zero tokens)."""
        now = datetime.now(timezone.utc)
        if not await self.learning.baseline_ready(now):
            return None
        states = await self.smart_home.get_all_states()
        self._cached_states = states
        ignored = await self.memory.get_ignored_targets()
        await self.learning.refresh_rules(states)
        patterns = [
            p
            for p in await self.learning.get_patterns(now, states, force=True)
            if not (ignored and any(t.matches(p.entity_id) for t in ignored))
        ]
        if not patterns or not self.settings.deterministic_automations or self.settings.max_new_automations_per_cycle <= 0:
            return None

        names = {eid: str(st.attributes.get("friendly_name") or "") for eid, st in states.items()}
        persons = person_entities(states)
        rejected = await self.memory.get_rejected_signatures()
        intents: list[ActionIntent] = []
        for p in patterns:
            if len(intents) >= self.settings.max_new_automations_per_cycle:
                break
            strong = p.confidence >= 0.75 and (p.support_days >= 4 if p.kind == "time_habit" else p.support_days >= 5)
            if p.covered_by or not strong:
                continue
            proposal = automation_from_pattern(p, names, persons)
            if proposal is None or self.learning.equivalent_rule(proposal):
                continue
            domain = p.entity_id.split(".", 1)[0]
            intent = ActionIntent(
                agent_id=self._agent_for_automation(domain),
                domain="automation",
                service="upsert_native_automation",
                target_entity_ids=[f"automation.{proposal.automation_id}"] + proposal.extract_target_entities(),
                service_data=proposal.model_dump(),
                cause_category="learned_habit",
                rationale=proposal.discovered_pattern_rationale,
                priority=ActionPriority.HABIT_PREDICTION,
                risk_level=ActionRiskLevel.MEDIUM,
                native_automation=proposal,
            )
            if intent.repeatable_signature() in rejected:
                continue
            intents.append(intent)
        if not intents:
            return None

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        for intent in intents:
            intent.run_id = run_id
        await self._attach_backtests(intents, now)
        exec_results = await self._evaluate_and_dispatch_intents(intents, run_id=run_id)
        proposed = sum(1 for r in exec_results if r.get("status") in ("awaiting_user_approval", "executed"))
        self.learning.stats["habit_automations_proposed"] += proposed
        run_log = AgentRunLog(
            run_id=run_id,
            agent_id="pattern_miner",
            mode="periodic_batch",
            trigger_summary=f"Learned-habit scan (statistics only, no AI tokens): {len(patterns)} patterns, {proposed} new automation proposals",
            derived_signals=[
                DerivedSignal(
                    signal_name=f"habit:{p.pattern_id}",
                    value=round(p.confidence, 2),
                    unit="confidence",
                    formula_or_method=f"{p.kind}: support {p.support_days}/{p.observed_days}",
                    source_entities=[e for e in (p.entity_id, p.trigger_entity) if e],
                    interpretation=p.description + (f" - already automated by '{p.covered_by}'" if p.covered_by else ""),
                )
                for p in patterns[:10]
            ],
            proposed_intents=intents,
            execution_results=exec_results,
        )
        self._log_agent_run_summary(run_log)
        await self.memory.save_run_log(run_log)
        self._last_batch_run_at = datetime.now(timezone.utc)
        return run_log

    # ==================================================================================================
    # Exceptions (deviations from routines / automations)
    # ==================================================================================================
    def _agent_for_entity(self, entity_id: str, state: Any) -> AgentSpec | None:
        active = self.registry.get_active_agents()
        domain = entity_id.split(".", 1)[0]
        security = domain in ("lock", "alarm_control_panel") or any(w in entity_id for w in ("garage", "gate", "door")) or (
            getattr(state, "device_class", "") in ("door", "window", "garage_door", "opening")
        )
        if security:
            for a in active:
                if a.agent_id == "security_safety_agent":
                    return a
        for a in active:
            if a.agent_id != "repair_diagnostics_agent" and domain in a.controllable_domains:
                return a
        for a in active:
            if a.agent_id != "repair_diagnostics_agent" and domain in a.monitored_domains:
                return a
        return None

    async def check_exceptions(self) -> list[ExceptionFinding]:
        """Look for unusual situations (open house while away, routine broken, automation did not run)."""
        if not self.settings.exception_detection:
            return []
        now = datetime.now(timezone.utc)
        states = await self.smart_home.get_all_states()
        self._cached_states = states
        ignored = await self.memory.get_ignored_targets()
        visible = {e: s for e, s in states.items() if not (ignored and any(t.matches(e) for t in ignored))}
        await self.learning.refresh_rules(states)
        household = await self.learning.household(visible, now)
        findings = await self.learning.detect_exceptions(visible, now, household)
        for finding in findings:
            try:
                await self._handle_exception(finding, visible, ignored, now)
            except Exception as exc:
                logger.error("Could not handle exception for %s: %s", finding.entity_id, exc)
        return findings

    async def _handle_exception(self, finding: ExceptionFinding, states: dict[str, Any], ignored: list[Any], now: datetime) -> None:
        self.learning.mark_reported(finding, now)
        st = states[finding.entity_id]
        label = str(st.attributes.get("friendly_name") or finding.entity_id)
        title = f"Unusual: {label} is {finding.current_state}"[:120]
        active = await self.memory.get_advisory_insights(limit=100, status="active")
        if any(i.title == title for i in active):
            return  # still unacknowledged: do not nag
        agent = self._agent_for_entity(finding.entity_id, st)
        actions = {
            "security_while_away": f"Check and secure {label} now - nobody appears to be home.",
            "automation_missed": "Open Home Assistant > Settings > Automations and check the automation's trace to see why it did not run.",
            "routine_deviation": f"Check whether {label} is meant to stay {finding.current_state}; if so you can ignore this.",
        }
        insight = AdvisoryInsight(
            agent_id=agent.agent_id if agent else "exception_monitor",
            category="exception",
            title=title,
            finding_details=finding.summary,
            evidence_metrics={
                "kind": finding.kind,
                "entity_id": finding.entity_id,
                "expected_state": finding.expected_state,
                "current_state": finding.current_state,
                "confidence": round(finding.confidence, 2),
                "severity": finding.severity,
            },
            recommended_human_action=actions.get(finding.kind, "Review the situation."),
            estimated_impact="Safety / security" if finding.severity == "critical" else "Comfort / energy",
        )
        await self.memory.save_advisory_insight(insight)
        self.learning.stats["exceptions_detected"] += 1
        await self._notify_insight(insight, urgent=finding.severity == "critical", even_in_shadow=True)

        if agent is None or self.settings.paused or self.settings.operating_mode == OperatingMode.PERIODIC_BATCH:
            return
        frame = SemanticEventFrame(
            target_agent_id=agent.agent_id,
            area_id=st.area_id,
            corroborated_states=self.triage.build_context(st, states, agent, ignored),
            significance_reason=finding.summary,
        )
        token = _URGENT_DISPATCH.set(finding.severity == "critical")
        try:
            await self._run_agent_for_frame(frame)
        finally:
            _URGENT_DISPATCH.reset(token)

    # ==================================================================================================
    # Closed loops: outcome verification, automation lifecycle, trust, digest
    # ==================================================================================================
    async def verify_due_outcomes(self) -> int:
        now = datetime.now(timezone.utc)
        due = await self.memory.get_due_expected_outcomes(now)
        if not due:
            return 0
        states = self._cached_states or await self.smart_home.get_all_states()
        checked = 0
        for outcome in due:
            st = states.get(outcome.monitored_entity_id)
            status, note = evaluate_outcome(outcome.expected_direction_or_target, outcome.baseline_value, st.numeric_value if st else None)
            if status == "unknown":
                await self.memory.set_expected_outcome_status(outcome.outcome_id, "unverifiable")
                continue
            success = status == "success"
            await self.memory.save_feedback(
                FeedbackEpisode(
                    agent_id=outcome.agent_id,
                    cause_category="outcome_verification",
                    action_signature=f"outcome:{outcome.action_id}",
                    target_entity_ids=[outcome.monitored_entity_id],
                    service_called="outcome_check",
                    polarity=FeedbackPolarity.OUTCOME_VERIFIED_SUCCESS if success else FeedbackPolarity.OUTCOME_VERIFIED_FAILURE,
                    human_note=f"Expected '{outcome.expected_direction_or_target}': {note}.",
                )
            )
            await self.memory.set_expected_outcome_status(outcome.outcome_id, "verified_success" if success else "verified_failure")
            self.learning.stats["outcomes_success" if success else "outcomes_failure"] += 1
            checked += 1
        return checked

    async def review_deployed_automations(self) -> list[AutomationReview]:
        """Do the automations the brain created actually run, and does the household fight them?"""
        accepted = await self.memory.get_accepted_automations()
        if not accepted:
            return []
        now = datetime.now(timezone.utc)
        states = await self.smart_home.get_all_states()
        by_id = {str(s.attributes.get("id")): s for s in states.values() if s.domain == "automation" and s.attributes.get("id")}
        reviews: list[AutomationReview] = []
        for ep in accepted:
            data = ep.service_data or {}
            automation_id = str(data.get("automation_id") or "")
            if not automation_id:
                continue
            state = by_id.get(automation_id)
            fires: list[datetime] = []
            if state is not None:
                last = parse_iso(state.attributes.get("last_triggered"))
                if last is not None:
                    from ha_ai_brain.domain.models import Transition
                    from ha_ai_brain.ports.telemetry import AUTOMATION_FIRE_STATE

                    await self.telemetry.record_transitions([Transition(state.entity_id, last, "", AUTOMATION_FIRE_STATE, "ha_automation")])
                fires = await self.telemetry.get_fires(state.entity_id, since=ep.created_at)
            rule = AutomationRule(automation_id=automation_id, alias=str(data.get("alias") or automation_id))
            _collect_actions(data.get("action") or [], rule)
            targets = sorted({a.entity_id for a in rule.actions})
            tl = await self.learning.timeline_for(targets, now, days=30) if targets else await self.learning.timeline_for([], now, days=0)
            reviews.append(
                review_deployed_automation(
                    automation_id=automation_id,
                    alias=rule.alias,
                    deployed_at=ep.created_at,
                    now=now,
                    state=state,
                    fires=fires,
                    actions=rule.actions,
                    tl=tl,
                )
            )
        for review in reviews:
            if review.needs_attention:
                await self._report_automation_review(review, now)
        await self.memory.set_kv("lifecycle:last", json.dumps([r.__dict__ for r in reviews]))
        return reviews

    async def _report_automation_review(self, review: AutomationReview, now: datetime) -> None:
        key = f"lifecycle:notified:{review.automation_id}"
        last = parse_iso(await self.memory.get_kv(key))
        if last is not None and now - last < timedelta(days=7):
            return
        await self.memory.set_kv(key, now.isoformat())
        insight = AdvisoryInsight(
            agent_id="automation_lifecycle",
            category="automation_review",
            title=f"Automation needs attention: {review.alias}"[:120],
            finding_details=review.details,
            evidence_metrics={"verdict": review.verdict, "runs": review.fires, "overridden": review.overrides, "days_deployed": review.days_deployed},
            recommended_human_action={
                "overridden": "Edit or disable this automation - it keeps being reverted by hand.",
                "never_fired": "Open the automation's trace in Home Assistant; its trigger probably does not match reality.",
                "disabled": "It is switched off. Re-enable it or delete it so the brain can propose a better one.",
                "missing": "It no longer exists in Home Assistant; the brain may propose it again.",
            }.get(review.verdict, "Review this automation."),
            estimated_impact="Keeps learned automations trustworthy",
        )
        await self.memory.save_advisory_insight(insight)
        await self._notify_insight(insight)
        if review.verdict == "overridden" and review.entity_id:
            intent = ActionIntent(
                agent_id="automation_lifecycle",
                domain="automation",
                service="turn_off",
                target_entity_ids=[review.entity_id],
                cause_category="automation_overridden",
                rationale=f"'{review.alias}': {review.details} Turning it off stops the tug-of-war until you revise it.",
                priority=ActionPriority.COMFORT_ENHANCEMENT,
                risk_level=ActionRiskLevel.HIGH,  # always needs a human decision, even in autonomous mode
            )
            await self._evaluate_and_dispatch_intents([intent])

    async def propose_trust_promotions(self) -> int:
        """Suggest relaxing approvals for action types the household has repeatedly approved without objection."""
        now = datetime.now(timezone.utc)
        counts = await self.memory.get_feedback_counts(now - timedelta(days=30))
        rules = await self.memory.get_endorsed_rules()
        approved: Counter[tuple[str, str]] = Counter()
        objections: Counter[tuple[str, str]] = Counter()
        for row in counts:
            key = (row["agent_id"], row["service_called"])
            if row["polarity"] == FeedbackPolarity.ENDORSED_ONCE.value:
                approved[key] += row["count"]
            elif row["polarity"] in (
                FeedbackPolarity.REJECTED_EXPLICIT.value,
                FeedbackPolarity.OVERRIDDEN_IMPLICIT.value,
                FeedbackPolarity.OUTCOME_VERIFIED_FAILURE.value,
            ):
                objections[key] += row["count"]
        created = 0
        for (agent_id, service), n in approved.items():
            domain = service.split(".", 1)[0]
            if n < 5 or objections[(agent_id, service)] or domain in ("lock", "alarm_control_panel", "valve", "automation", "outcome_check", "notify"):
                continue
            if any(r.agent_id == agent_id and r.domain_service == service for r in rules.values()):
                continue
            if self.settings.domain_autonomy.get(domain) == AutonomyLevel.AUTONOMOUS:
                continue
            key = f"trust:notified:{agent_id}:{service}"
            last = parse_iso(await self.memory.get_kv(key))
            if last is not None and now - last < timedelta(days=30):
                continue
            await self.memory.set_kv(key, now.isoformat())
            insight = AdvisoryInsight(
                agent_id=agent_id,
                category="trust_promotion",
                title=f"Let the brain handle '{service}' by itself?"[:120],
                finding_details=f"You approved '{service}' {n} times in the last 30 days and never rejected or reverted it.",
                evidence_metrics={"approvals": n, "service": service},
                recommended_human_action=(
                    f"Use 'Always allow' on the next approval, or set the '{domain}' domain to Autonomous in Settings > Safety. "
                    "Every autonomous action comes with an Undo button."
                ),
                estimated_impact="Fewer interruptions",
            )
            await self.memory.save_advisory_insight(insight)
            await self._notify_insight(insight)
            created += 1
        return created

    async def _persist_stats(self) -> None:
        """Persist per-day counters so the 'what I learned' view survives restarts."""
        day = datetime.now(timezone.utc).date().isoformat()
        flushed: Counter[str] = getattr(self, "_stats_flushed", Counter())
        delta = {k: v - flushed.get(k, 0) for k, v in self.learning.stats.items() if v - flushed.get(k, 0) > 0}
        if not delta:
            return
        try:
            stored = json.loads(await self.memory.get_kv(f"stats:{day}") or "{}")
        except ValueError:
            stored = {}
        for k, v in delta.items():
            stored[k] = int(stored.get(k, 0)) + v
        await self.memory.set_kv(f"stats:{day}", json.dumps(stored))
        self._stats_flushed = Counter(self.learning.stats)

    async def _stats_last_days(self, days: int = 7) -> dict[str, int]:
        await self._persist_stats()
        total: Counter[str] = Counter()
        today = datetime.now(timezone.utc).date()
        for i in range(days):
            raw = await self.memory.get_kv(f"stats:{(today - timedelta(days=i)).isoformat()}")
            if raw:
                try:
                    total.update({k: int(v) for k, v in json.loads(raw).items()})
                except ValueError:
                    pass
        return dict(total)

    async def maybe_send_weekly_digest(self) -> bool:
        now = datetime.now(timezone.utc)
        last = parse_iso(await self.memory.get_kv("digest:last"))
        if last is None:
            await self.memory.set_kv("digest:last", now.isoformat())
            return False
        if now - last < timedelta(days=7):
            return False
        stats = await self._stats_last_days(7)
        tokens = 0
        for i in range(7):
            tokens += int(await self.memory.get_kv(f"tokens:{(now.date() - timedelta(days=i)).isoformat()}") or 0)
        deployed = len(await self.memory.get_accepted_automations())
        lines = [
            f"LLM calls avoided by local learning: {stats.get('llm_calls_avoided', 0)}",
            f"Batch analyses skipped because nothing changed: {stats.get('batch_skipped_unchanged', 0)}",
            f"Automations proposed from your own habits (no AI tokens): {stats.get('habit_automations_proposed', 0)}",
            f"Unusual situations detected: {stats.get('exceptions_detected', 0)}",
            f"Actions you undid: {stats.get('undone', 0)}",
            f"AI tokens used this week: {tokens:,}",
            f"Automations deployed so far: {deployed}",
            f"Research findings waiting for your review: {len(await KnowledgeStore(self.memory).items(status='proposed'))}",
        ]
        insight = AdvisoryInsight(
            agent_id="automation_lifecycle",
            category="weekly_digest",
            title="Your weekly AI Brain digest",
            finding_details="\n".join(lines),
            evidence_metrics={k: v for k, v in stats.items() if not k.startswith("avoided:")},
            recommended_human_action="Open the Learned tab to review habits, routines and deployed automations.",
            estimated_impact="Transparency",
        )
        await self.memory.save_advisory_insight(insight)
        await self.memory.set_kv("digest:last", now.isoformat())
        await self._notify_insight(insight)
        return True

    async def daily_housekeeping(self) -> None:
        now = datetime.now(timezone.utc)
        await self.telemetry.prune(self.settings.store_retention_days, now)
        removed = await self.memory.prune_old(now)
        if any(removed.values()):
            logger.info("Retention cleanup removed: %s", {k: v for k, v in removed.items() if v})
        await self.telemetry.maintain()
        await self.memory.maintain()
        await self.review_deployed_automations()
        await self.propose_trust_promotions()
        await self.maybe_send_weekly_digest()

    # ==================================================================================================
    # Background housekeeping
    # ==================================================================================================
    async def _bootstrap_learning(self) -> None:
        await self.learning.init_timezone()
        states = await self.smart_home.get_all_states()
        if not self._cached_states:
            self._cached_states = states
        await self.learning.refresh_rules(states, force=True)
        await self.learning.load_exception_feedback()
        await self.learning.backfill(states)
        self._bootstrapped = True

    async def _safe(self, label: str, fn: Any) -> None:
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Housekeeping job '%s' failed: %s", label, exc)

    async def housekeeping_tick(self) -> None:
        """One minute of background upkeep: outcomes, deferred pushes, exception checks, daily jobs."""
        self._housekeeping_ticks += 1
        n = self._housekeeping_ticks
        if not self._bootstrapped:
            await self._safe("bootstrap", self._bootstrap_learning)
        await self._safe("outcomes", self.verify_due_outcomes)
        await self._safe("deferred", self._flush_deferred)
        await self._safe("watches", self.evaluate_watches)
        if n % 60 == 1 and self._bootstrapped:
            await self._safe("research_schedule", self._maybe_start_research)
        if n % 5 == 0:
            await self._safe("exceptions", self.check_exceptions)
        if n % 30 == 0:
            await self._safe("stats", self._persist_stats)
        if self._bootstrapped:
            day = datetime.now(timezone.utc).date().isoformat()
            if await self.memory.get_kv("daily:last") != day:
                await self.memory.set_kv("daily:last", day)
                await self._safe("daily", self.daily_housekeeping)

    async def _bootstrap_then_housekeeping(self) -> None:
        await self._safe("bootstrap", self._bootstrap_learning)
        while self._running:
            await asyncio.sleep(60)
            if self._running:
                await self.housekeeping_tick()

    # ==================================================================================================
    # Read model for the dashboard
    # ==================================================================================================
    async def get_learned_snapshot(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        win = await self.learning.window(now)
        days = (win[1] - win[0]).total_seconds() / 86400.0 if win else 0.0
        patterns = await self.learning.get_patterns(now, self._cached_states or None)
        try:
            lifecycle = json.loads(await self.memory.get_kv("lifecycle:last") or "[]")
        except ValueError:
            lifecycle = []
        stats = await self._stats_last_days(7)
        return {
            "days_of_data": round(days, 1),
            "baseline_ready": days >= self.settings.baseline_min_days,
            "baseline_min_days": self.settings.baseline_min_days,
            "store": await self.telemetry.stats(),
            "timezone": self.learning._tz_name or "UTC",
            "patterns": [p.to_dict() for p in patterns[:40]],
            "existing_automations": len(self.learning.rules),
            "automation_reviews": lifecycle,
            "stats_7d": {k: v for k, v in stats.items() if not k.startswith("avoided:")},
            "tokens_today": await self._tokens_used_today(),
            "daily_token_budget": self.settings.daily_token_budget,
            "gating_active": self.settings.realtime_gating and days >= self.settings.baseline_min_days,
            "undo_records": await self.list_undo_records(),
            "muted_exceptions": self.learning.muted_exceptions(),
        }

    # ==================================================================================================
    # Watches: user-described conditions, compiled once and evaluated locally
    # ==================================================================================================
    async def backtest_watch_rule(self, rule: WatchRule) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        win = await self.learning.window(now)
        if not win:
            return {"episodes": None, "note": "No history recorded yet."}
        start = max(win[0], now - timedelta(days=30))
        transitions = await self.telemetry.get_transitions(since=start, entity_ids=rule.entity_ids)
        rows = await self.telemetry.get_all_numeric_hours(since=start)
        return backtest_watch(rule, transitions, {e: rows.get(e, []) for e in rule.entity_ids}, start, win[1], self.learning.tz)

    async def compile_watch(self, text: str) -> dict[str, Any]:
        states = self._cached_states or await self.smart_home.get_all_states()
        result = await self.watches.compile(text, states)
        if result.get("draft") and not result["errors"]:
            result["backtest"] = await self.backtest_watch_rule(WatchRule.model_validate(result["draft"]))
        return result

    async def save_watch(self, rule: WatchRule) -> WatchRule:
        states = self._cached_states or await self.smart_home.get_all_states()
        errors, _ = validate_watch(rule, states)
        if errors:
            raise ValueError("; ".join(errors))
        return await self.watches.save(rule)

    async def evaluate_watches(self) -> int:
        """Evaluate every enabled watch against live state (no AI, no I/O beyond the cached states)."""
        rules = [r for r in await self.watches.list() if r.enabled]
        if not rules:
            return 0
        states = self._cached_states or await self.smart_home.get_all_states()
        now = datetime.now(timezone.utc)
        persons = [s for s in states.values() if s.domain == "person"]
        anyone_home: bool | None = any(p.state == "home" for p in persons) if persons else None
        fired = 0
        for rule in rules:
            firings = evaluate_watch(rule, states, now, self.learning.tz, self._watch_tracker, anyone_home)
            if not firings:
                continue
            if rule.last_fired and now - rule.last_fired < timedelta(minutes=rule.cooldown_minutes):
                continue
            title = f"Watch: {rule.name}"[:120]
            detail = rule.message or "; ".join(f.detail for f in firings[:5])
            if rule.message:
                detail += " (" + "; ".join(f.detail for f in firings[:5]) + ")"
            rule.last_fired, rule.fire_count = now, rule.fire_count + 1
            await self.watches.save(rule)
            active = await self.memory.get_advisory_insights(limit=100, status="active")
            if any(i.title == title for i in active):
                continue
            insight = AdvisoryInsight(
                agent_id="watch_monitor",
                category="watch",
                title=title,
                finding_details=detail,
                evidence_metrics={"kind": "watch", "watch_id": rule.watch_id, "entities": [f.entity_id for f in firings], "severity": rule.severity},
                recommended_human_action=rule.description or "Check the situation.",
                estimated_impact="Your own watch",
            )
            await self.memory.save_advisory_insight(insight)
            self.learning.stats["watches_fired"] += 1
            await self._notify_insight(insight, urgent=rule.severity == "critical", even_in_shadow=True)
            fired += 1
        return fired

    # ==================================================================================================
    # Research agenda
    # ==================================================================================================
    async def _budget_ok(self) -> bool:
        return not await self._budget_exhausted()

    async def _maybe_start_research(self) -> None:
        now = datetime.now(timezone.utc)
        if not self.settings.research_enabled or not self.llm.is_available:
            return
        if await self.research.last_run() is None:
            # Never spend tokens on research at first start: the first run happens a day later (or when you press the button).
            first = now - timedelta(days=max(1, self.settings.research_interval_days)) + timedelta(days=1)
            await self.memory.set_kv("research:last_run", first.isoformat())
            return
        if await self.research.due(now):
            self.spawn_background_task(self._run_research(), "ha_research_run")

    async def _run_research(self, agent_ids: list[str] | None = None) -> dict[str, Any]:
        try:
            summary = await self.research.run(agent_ids)
        except Exception as exc:
            logger.error("Research run failed: %s", exc)
            return {"status": "error", "message": str(exc)}
        self.learning.stats["research_findings"] += int(summary.get("findings", 0))
        logger.info("Research run finished: %s", summary)
        return summary

    async def start_research_now(self) -> dict[str, Any]:
        if self.research.running:
            return {"status": "already_running"}
        if not self.llm.is_available:
            return {"status": "unavailable", "message": "Research needs an AI provider. Configure one in Settings."}
        self.spawn_background_task(self._run_research(), "ha_research_run")
        return {"status": "started"}
