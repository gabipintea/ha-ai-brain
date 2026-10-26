"""FastAPI Server & Dependency Container for HA AI Brain Add-on and Control Plane."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ha_ai_brain.adapters.billing_license import CommercialLicenseAdapter
from ha_ai_brain.adapters.ha_simulator import SmartHomeSimulatorAdapter
from ha_ai_brain.adapters.ha_websocket_rest import HomeAssistantAdapter
from ha_ai_brain.adapters.llm_litellm import LiteLLMAdapter
from ha_ai_brain.adapters.llm_simulator_mock import SimulatorMockLLMAdapter
from ha_ai_brain.adapters.mcp_router import ExtensibleMcpClientAdapter
from ha_ai_brain.adapters.memory_sqlite import SQLiteMemoryAdapter
from ha_ai_brain.adapters.notification_ha import HomeAssistantNotificationAdapter
from ha_ai_brain.adapters.research_scientific import ScientificResearchAdapter
from ha_ai_brain.adapters.sandbox_python import PythonSandboxAdapter
from ha_ai_brain.adapters.telemetry_sqlite import SQLiteTelemetryStore
from ha_ai_brain.api.dashboard_html import DASHBOARD_HTML, render_dashboard_html
from ha_ai_brain.application.orchestrator import BrainOrchestrator
from ha_ai_brain.config import AutonomyLevel, BrainSettings, FallbackPolicy, OperatingMode
from ha_ai_brain.domain.watches import WatchRule
from ha_ai_brain.domain.models import AgentSpec, FeedbackEpisode, FeedbackPolarity, IgnoredTarget, UserContextNote
from ha_ai_brain.ports.llm import LLMProviderPort


class SettingsUpdateRequest(BaseModel):
    operating_mode: OperatingMode | None = None
    default_autonomy: AutonomyLevel | None = None
    llm_fallback_policy: FallbackPolicy | None = None
    notification_service: str | None = None
    notifications_enabled: bool | None = None
    site_context: str | None = Field(default=None, max_length=4000)
    llm_model: str | None = Field(default=None, max_length=200)
    llm_fast_model: str | None = Field(default=None, max_length=200)
    llm_api_key: str | None = Field(default=None, max_length=500)
    # learning / safety
    paused: bool | None = None
    realtime_gating: bool | None = None
    exception_detection: bool | None = None
    deterministic_automations: bool | None = None
    notify_autonomous_actions: bool | None = None
    privacy_scrub: bool | None = None
    daily_token_budget: int | None = Field(default=None, ge=0, le=1_000_000_000)
    max_actions_per_hour: int | None = Field(default=None, ge=1, le=1000)
    max_actions_per_entity_per_hour: int | None = Field(default=None, ge=1, le=100)
    realtime_coalesce_seconds: int | None = Field(default=None, ge=0, le=3600)
    max_agent_wakeups_per_hour: int | None = Field(default=None, ge=0, le=1000)
    quiet_hours_start: str | None = Field(default=None, max_length=5)
    quiet_hours_end: str | None = Field(default=None, max_length=5)
    domain_autonomy: dict[str, AutonomyLevel] | None = None
    research_enabled: bool | None = None
    research_web_search: bool | None = None
    research_interval_days: int | None = Field(default=None, ge=1, le=90)
    research_topics_per_agent: int | None = Field(default=None, ge=1, le=5)

    RUNTIME_FIELDS: ClassVar[tuple[str, ...]] = (
        "paused", "realtime_gating", "exception_detection", "deterministic_automations", "notify_autonomous_actions",
        "privacy_scrub", "daily_token_budget", "max_actions_per_hour", "max_actions_per_entity_per_hour",
        "quiet_hours_start", "quiet_hours_end", "domain_autonomy",
        "research_enabled", "research_web_search", "research_interval_days", "research_topics_per_agent",
        "realtime_coalesce_seconds", "max_agent_wakeups_per_hour",
    )


class FallbackDecisionRequest(BaseModel):
    decision: str  # "approve_fallback", "wait_for_primary", "set_policy"
    fallback_model: str | None = None
    fallback_policy: FallbackPolicy | None = None


class SimulateEventRequest(BaseModel):
    scenario: str | None = None  # "condensation_risk" or "solar_ufh_gain"
    entity_id: str | None = None
    new_value: str | None = None
    context_user_id: str | None = None


class BatchAnalyzeRequest(BaseModel):
    agent_id: str = "all"
    area_id: str | None = None
    lookback_hours: int | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str  # "approved_once", "approved_repeatable", "rejected"
    human_note: str = ""


class UserContextNoteRequest(BaseModel):
    content: str = Field(max_length=2000)
    scope: str = Field(default="global", max_length=200)
    related_entities: list[str] = Field(default_factory=list, max_length=50)


class IgnoredTargetRequest(BaseModel):
    pattern: str = Field(max_length=200)
    reason: str = Field(default="", max_length=500)


class MinChangeRequest(BaseModel):
    pattern: str = Field(max_length=200)
    min_change: float = Field(gt=0, le=1_000_000)
    reason: str = Field(default="", max_length=500)


class WatchCompileRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ResearchDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


class UnmuteRequest(BaseModel):
    key: str = Field(max_length=300)


class InsightRejectionRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


def _package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("ha-ai-brain")
    except Exception:
        return "0.0.0"


def build_orchestrator(settings: BrainSettings | None = None) -> BrainOrchestrator:
    """Assemble the Hexagonal Architecture ports and adapters into a BrainOrchestrator."""
    cfg = settings or BrainSettings.from_env()
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger().setLevel(level)
    if cfg.db_path and "/" in cfg.db_path:
        Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)

    if cfg.use_simulator or not cfg.ha_token:
        smart_home = SmartHomeSimulatorAdapter()
    else:
        smart_home = HomeAssistantAdapter(
            base_url=cfg.ha_url,
            ws_url=cfg.ha_ws_url,
            token=cfg.ha_token,
            history_max_entities=cfg.history_max_entities,
        )

    license_adapter = CommercialLicenseAdapter(initial_license_key=cfg.license_key)

    has_live_llm = bool(cfg.llm_api_key or cfg.managed_proxy_url or cfg.llm_model.startswith("ollama/"))
    if cfg.use_simulator and not has_live_llm:
        llm_adapter: LLMProviderPort = SimulatorMockLLMAdapter(license_port=license_adapter)
    else:
        llm_adapter = LiteLLMAdapter(
            model=cfg.llm_model,
            fast_model=cfg.llm_fast_model,
            api_key=cfg.llm_api_key,
            managed_proxy_url=cfg.managed_proxy_url,
            license_port=license_adapter,
            fallback_models=cfg.llm_fallback_models,
            fallback_policy=cfg.llm_fallback_policy.value,
            privacy_scrub=cfg.privacy_scrub,
        )

    sandbox_adapter = PythonSandboxAdapter()
    research_adapter = ScientificResearchAdapter(llm=llm_adapter)
    memory_adapter = SQLiteMemoryAdapter(db_path=cfg.db_path)
    notification_adapter = HomeAssistantNotificationAdapter(
        smart_home=smart_home,
        notify_service=cfg.notification_service,
    )
    mcp_adapter = ExtensibleMcpClientAdapter()

    return BrainOrchestrator(
        settings=cfg,
        smart_home=smart_home,
        llm=llm_adapter,
        sandbox=sandbox_adapter,
        research=research_adapter,
        memory=memory_adapter,
        notification=notification_adapter,
        mcp_client=mcp_adapter,
        license_port=license_adapter,
        telemetry=SQLiteTelemetryStore(cfg.db_path),
    )


def create_app(settings: BrainSettings | None = None) -> Any:
    """Create the FastAPI application with HA Ingress dashboard, REST API, and background stream/scheduler workers."""
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    orchestrator = build_orchestrator(settings=settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await orchestrator.start_background_workers()
        try:
            yield
        finally:
            await orchestrator.stop_background_workers()
            if hasattr(orchestrator.smart_home, "aclose"):
                await orchestrator.smart_home.aclose()

    app = FastAPI(
        title="HA AI Brain",
        version=_package_version(),
        description="Autonomous Multi-Agent Cognitive Layer for Home Assistant (Hexagonal Architecture + LangGraph)",
        lifespan=lifespan,
    )
    app.state.orchestrator = orchestrator

    # Inside the add-on, the dashboard/API must only be reachable through HA Ingress (Supervisor proxy) so that
    # nobody on the LAN can approve actions or read settings when a host port is mapped by mistake.
    if os.getenv("SUPERVISOR_TOKEN") and os.getenv("BRAIN_ALLOW_ANY_CLIENT", "").lower() not in ("1", "true", "yes"):
        trusted_clients = {
            c.strip() for c in os.getenv("BRAIN_TRUSTED_PROXIES", "172.30.32.2,127.0.0.1,::1").split(",") if c.strip()
        }

        @app.middleware("http")
        async def ingress_only(request: Request, call_next: Any) -> Any:
            client_host = request.client.host if request.client else ""
            if client_host not in trusted_clients and request.url.path != "/api/health":
                return JSONResponse({"detail": "Access is only allowed through Home Assistant Ingress."}, status_code=403)
            return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        notify_services = await orchestrator.smart_home.get_available_notify_services()
        html = render_dashboard_html(
            settings=orchestrator.settings,
            available_notify_services=notify_services,
        )
        return HTMLResponse(
            content=html,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Lightweight liveness probe used by the Home Assistant Supervisor watchdog."""
        return {"status": "ok"}

    async def _learn_from_exception_feedback(insight: Any, *, rejected: bool) -> None:
        """Dismissing an unusual-situation alert quiets that entity for longer; rejecting mutes it."""
        if insight.category != "exception":
            return
        metrics = insight.evidence_metrics or {}
        if metrics.get("kind") and metrics.get("entity_id"):
            await orchestrator.learning.record_exception_feedback(f"{metrics['kind']}:{metrics['entity_id']}", rejected=rejected)

    @app.get("/api/watches")
    async def list_watches() -> dict[str, Any]:
        return {"watches": [w.model_dump(mode="json") for w in await orchestrator.watches.list()]}

    @app.post("/api/watches/compile")
    async def compile_watch(req: WatchCompileRequest) -> dict[str, Any]:
        """One AI call turns a plain-language request into a validated, backtested draft rule (nothing is saved yet)."""
        return await orchestrator.compile_watch(req.text)

    @app.post("/api/watches")
    async def save_watch(rule: WatchRule) -> dict[str, Any]:
        try:
            saved = await orchestrator.save_watch(rule)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "saved", "watch": saved.model_dump(mode="json")}

    @app.post("/api/watches/{watch_id}/toggle")
    async def toggle_watch(watch_id: str) -> dict[str, Any]:
        rule = await orchestrator.watches.get(watch_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Watch not found")
        rule.enabled = not rule.enabled
        await orchestrator.watches.save(rule)
        return {"status": "ok", "watch": rule.model_dump(mode="json")}

    @app.delete("/api/watches/{watch_id}")
    async def delete_watch(watch_id: str) -> dict[str, Any]:
        if not await orchestrator.watches.delete(watch_id):
            raise HTTPException(status_code=404, detail="Watch not found")
        return {"status": "deleted", "watch_id": watch_id}

    @app.get("/api/research")
    async def get_research() -> dict[str, Any]:
        """Research agenda status plus findings waiting for review and the approved knowledge base."""
        status = await orchestrator.research.status()
        proposed = await orchestrator.research.store.items(status="proposed")
        approved = await orchestrator.research.store.items(status="approved")
        rejected = await orchestrator.research.store.items(status="rejected")
        agents = {a.agent_id: a.name for a in orchestrator.registry.list_agents()}
        return {
            **status,
            "agent_names": agents,
            "proposed": [i.model_dump(mode="json") for i in proposed],
            "approved": [i.model_dump(mode="json") for i in approved],
            "rejected_count": len(rejected),
        }

    @app.post("/api/research/run")
    async def run_research() -> dict[str, Any]:
        return await orchestrator.start_research_now()

    @app.post("/api/research/items/{item_id}/decision")
    async def decide_research_item(item_id: str, req: ResearchDecisionRequest) -> dict[str, Any]:
        item = await orchestrator.research.decide(item_id, req.decision)
        if item is None:
            raise HTTPException(status_code=404, detail="Research item not found")
        orchestrator.invalidate_context_caches()
        return {"status": item.status, "item": item.model_dump(mode="json")}

    @app.delete("/api/research/items/{item_id}")
    async def delete_research_item(item_id: str) -> dict[str, Any]:
        if not await orchestrator.research.store.delete_item(item_id):
            raise HTTPException(status_code=404, detail="Research item not found")
        orchestrator.invalidate_context_caches()
        return {"status": "deleted", "item_id": item_id}

    @app.post("/api/exceptions/unmute")
    async def unmute_exception(req: UnmuteRequest) -> dict[str, Any]:
        await orchestrator.learning.unmute_exception(req.key)
        return {"status": "unmuted", "muted": orchestrator.learning.muted_exceptions()}

    @app.get("/api/status")
    async def get_status() -> dict[str, Any]:
        lic = await orchestrator.license_port.verify_license(orchestrator.settings.license_key)
        quota = await orchestrator.llm.get_quota_status()
        if orchestrator._cached_states:
            entity_count = len(orchestrator._cached_states)
        else:
            states = await orchestrator.smart_home.get_all_states()
            orchestrator._cached_states = states
            entity_count = len(states)
        pending = await orchestrator.get_pending_approvals()
        rules = await orchestrator.memory.get_endorsed_rules()
        rejected = await orchestrator.memory.get_rejected_suggestions()
        logs = await orchestrator.memory.get_recent_run_logs(limit=10)
        total_logs = await orchestrator.memory.get_run_logs_count()
        insights = await orchestrator.memory.get_advisory_insights(limit=30, status="active")
        active_insights_count = await orchestrator.memory.get_active_insights_count()
        rejected_insights = await orchestrator.memory.get_rejected_insights()
        context_notes = await orchestrator.memory.get_user_context_notes(active_only=True)
        ignored_targets = await orchestrator.memory.get_ignored_targets()
        notify_services = await orchestrator.smart_home.get_available_notify_services()
        approval_statuses = await orchestrator.memory.get_approval_statuses()
        next_batch = await orchestrator.get_next_batch_run_at()
        last_batch = await orchestrator.get_last_batch_run_at()

        undo_records = await orchestrator.list_undo_records()
        return {
            "undo_records": undo_records,
            "research_pending_review": len(await orchestrator.research.store.items(status="proposed")),
            "settings": orchestrator.settings.public_dict(),
            "available_notify_services": notify_services,
            "license": lic.model_dump(),
            "llm_quota": quota.to_status_dict(),
            "agents": [a.model_dump() for a in orchestrator.registry.list_agents()],
            "entity_count": entity_count,
            "pending_approvals": [p.model_dump(mode="json") for p in pending],
            "endorsed_rules": {k: v.model_dump(mode="json") for k, v in rules.items()},
            "rejected_suggestions": [e.model_dump(mode="json") for e in rejected],
            "user_context_notes": [n.model_dump(mode="json") for n in context_notes],
            "ignored_targets": [t.model_dump(mode="json") for t in ignored_targets],
            "min_change_rules": [r.model_dump() for r in await orchestrator.get_min_change_rules()],
            "recent_logs": [l.model_dump(mode="json") for l in logs],
            "total_logs_count": total_logs,
            "advisory_insights": [i.model_dump(mode="json") for i in insights],
            "active_insights_count": active_insights_count,
            "rejected_insights": [r.model_dump(mode="json") for r in rejected_insights],
            "approval_statuses": approval_statuses,
            "next_batch_run_at": next_batch.isoformat() if next_batch else None,
            "last_batch_run_at": last_batch.isoformat() if last_batch else None,
            "batch_interval_minutes": orchestrator.settings.batch_interval_minutes,
        }

    @app.delete("/api/rejected")
    async def unblock_rejected(signature: str) -> dict[str, Any]:
        """Unblock a previously rejected suggestion so agents may propose it again."""
        removed = await orchestrator.memory.unblock_rejected_signature(signature)
        if not removed:
            raise HTTPException(status_code=404, detail="Rejected suggestion not found")
        return {"status": "unblocked", "signature": signature}

    @app.delete("/api/rules")
    async def revoke_rule(signature: str) -> dict[str, Any]:
        """Revoke an 'always allow' rule; the action will require approval again."""
        removed = await orchestrator.memory.delete_approval_rule(signature)
        if not removed:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"status": "revoked", "signature": signature}

    @app.get("/api/logs")
    async def get_logs(limit: int = 10, offset: int = 0) -> dict[str, Any]:
        logs = await orchestrator.memory.get_recent_run_logs(limit=limit, offset=offset)
        total = await orchestrator.memory.get_run_logs_count()
        return {
            "logs": [l.model_dump(mode="json") for l in logs],
            "total": total,
            "has_more": (offset + len(logs)) < total,
            "offset": offset,
            "limit": limit,
        }

    @app.get("/api/logs/{run_id}")
    async def get_single_log(run_id: str) -> dict[str, Any]:
        """Fetch a specific agent run log by run_id for deep-linking and explainability."""
        log = await orchestrator.memory.get_run_log(run_id)
        if not log:
            raise HTTPException(status_code=404, detail="Run log not found")
        return {"log": log.model_dump(mode="json")}

    @app.delete("/api/logs")
    async def clear_logs() -> dict[str, Any]:
        """Clear all agent run logs to free up storage."""
        count = await orchestrator.memory.clear_run_logs()
        return {"status": "cleared", "deleted_count": count}

    @app.get("/api/insights")
    async def list_insights(status: str | None = None, limit: int = 50) -> dict[str, Any]:
        """List advisory insights optionally filtered by status ('active', 'dismissed', 'rejected')."""
        items = await orchestrator.memory.get_advisory_insights(limit=limit, status=status)
        active_count = await orchestrator.memory.get_active_insights_count()
        return {
            "insights": [i.model_dump(mode="json") for i in items],
            "active_count": active_count,
        }

    @app.post("/api/insights/{insight_id}/dismiss")
    async def dismiss_insight(insight_id: str) -> dict[str, Any]:
        """Mark an advisory insight as read / dismissed."""
        resolved = await orchestrator.memory.resolve_advisory_insight(insight_id=insight_id, status="dismissed")
        if not resolved:
            raise HTTPException(status_code=404, detail="Insight not found")
        await _learn_from_exception_feedback(resolved, rejected=False)
        return {"status": "dismissed", "insight": resolved.model_dump(mode="json")}

    @app.post("/api/insights/dismiss_all")
    async def dismiss_all_insights() -> dict[str, Any]:
        """Dismiss all currently active advisory insights."""
        count = await orchestrator.memory.dismiss_all_advisory_insights()
        return {"status": "dismissed_all", "count": count}

    @app.post("/api/insights/{insight_id}/reject")
    async def reject_insight(insight_id: str, req: InsightRejectionRequest | None = None) -> dict[str, Any]:
        """Reject an advisory insight with an optional reason note so agents never propose it again."""
        reason = (req.reason if req else "").strip()
        resolved = await orchestrator.memory.resolve_advisory_insight(
            insight_id=insight_id,
            status="rejected",
            rejection_reason=reason,
        )
        if not resolved:
            raise HTTPException(status_code=404, detail="Insight not found")
        episode = FeedbackEpisode(
            agent_id=resolved.agent_id,
            cause_category=f"rejected_insight_{resolved.category}",
            action_signature=f"insight:{resolved.category}:{resolved.title}",
            target_entity_ids=[],
            service_called="advisory_insight",
            polarity=FeedbackPolarity.REJECTED_EXPLICIT,
            human_note=reason or f"Homeowner rejected insight '{resolved.title}'",
        )
        await orchestrator.memory.save_feedback(episode)
        await _learn_from_exception_feedback(resolved, rejected=True)
        return {"status": "rejected", "insight": resolved.model_dump(mode="json")}

    @app.delete("/api/insights/{insight_id}")
    async def delete_insight(insight_id: str) -> dict[str, Any]:
        """Delete an advisory insight permanently."""
        deleted = await orchestrator.memory.delete_advisory_insight(insight_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Insight not found")
        return {"status": "deleted", "insight_id": insight_id}

    @app.delete("/api/insights")
    async def clear_all_insights(status: str | None = None) -> dict[str, Any]:
        """Clear all advisory insights permanently, optionally filtered by status."""
        count = await orchestrator.memory.delete_all_advisory_insights(status=status)
        return {"status": "cleared", "deleted_count": count}

    @app.delete("/api/insights/rejected/{insight_id}")
    async def unblock_rejected_insight(insight_id: str) -> dict[str, Any]:
        """Unblock a rejected insight so agents may propose recommendations in this domain again."""
        unblocked = await orchestrator.memory.unblock_rejected_insight(insight_id)
        if not unblocked:
            raise HTTPException(status_code=404, detail="Rejected insight not found")
        return {"status": "unblocked", "insight_id": insight_id}

    @app.post("/api/settings")
    async def update_settings(req: SettingsUpdateRequest) -> dict[str, Any]:
        if req.operating_mode is not None:
            orchestrator.settings.operating_mode = req.operating_mode
            await orchestrator.memory.save_ui_preference("operating_mode", req.operating_mode.value)
        if req.default_autonomy is not None:
            orchestrator.settings.default_autonomy = req.default_autonomy
            await orchestrator.memory.save_ui_preference("default_autonomy", req.default_autonomy.value)
        if req.llm_fallback_policy is not None:
            orchestrator.settings.llm_fallback_policy = req.llm_fallback_policy
            if hasattr(orchestrator.llm, "set_fallback_policy"):
                orchestrator.llm.set_fallback_policy(req.llm_fallback_policy.value)
            await orchestrator.memory.save_ui_preference("llm_fallback_policy", req.llm_fallback_policy.value)
        if req.notification_service is not None and req.notification_service.strip():
            svc = req.notification_service.strip()
            if not svc.startswith("notify."):
                svc = f"notify.{svc}"
            orchestrator.settings.notification_service = svc
            if hasattr(orchestrator.notification, "notify_service"):
                orchestrator.notification.notify_service = svc
            await orchestrator.memory.save_ui_preference("notification_service", svc)
        if req.notifications_enabled is not None:
            orchestrator.settings.notifications_enabled = req.notifications_enabled
            await orchestrator.memory.save_ui_preference("notifications_enabled", str(req.notifications_enabled))
        if req.site_context is not None:
            orchestrator.settings.site_context = req.site_context
            await orchestrator.memory.save_ui_preference("site_context", req.site_context)
        runtime_changes = req.model_dump(include=set(SettingsUpdateRequest.RUNTIME_FIELDS), exclude_none=True)
        if runtime_changes:
            try:
                await orchestrator.update_runtime_settings(runtime_changes)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        llm_updated = False
        if req.llm_model is not None and req.llm_model.strip():
            orchestrator.settings.llm_model = req.llm_model.strip()
            await orchestrator.memory.save_ui_preference("llm_model", orchestrator.settings.llm_model)
            llm_updated = True
        if req.llm_fast_model is not None and req.llm_fast_model.strip():
            orchestrator.settings.llm_fast_model = req.llm_fast_model.strip()
            await orchestrator.memory.save_ui_preference("llm_fast_model", orchestrator.settings.llm_fast_model)
            llm_updated = True
        if req.llm_api_key is not None and req.llm_api_key.strip():
            orchestrator.settings.llm_api_key = req.llm_api_key.strip()
            await orchestrator.memory.save_ui_preference("llm_api_key", orchestrator.settings.llm_api_key)
            llm_updated = True
        if llm_updated and hasattr(orchestrator.llm, "reconfigure"):
            orchestrator.llm.reconfigure(
                model=orchestrator.settings.llm_model,
                fast_model=orchestrator.settings.llm_fast_model,
                api_key=orchestrator.settings.llm_api_key,
                fallback_policy=orchestrator.settings.llm_fallback_policy.value,
            )

        return {"status": "updated", "settings": orchestrator.settings.public_dict()}

    @app.get("/api/learned")
    async def get_learned() -> dict[str, Any]:
        """What the brain has learned locally: habits, routines, deployed-automation health and token savings."""
        return await orchestrator.get_learned_snapshot()

    @app.post("/api/undo/{undo_id}")
    async def undo_action(undo_id: str) -> dict[str, Any]:
        """Revert an action the brain took on its own."""
        try:
            return await orchestrator.handle_undo(undo_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'\"")) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/exceptions/check")
    async def check_exceptions_now() -> dict[str, Any]:
        """Run the exception detectors immediately instead of waiting for the 5-minute schedule."""
        findings = await orchestrator.check_exceptions()
        return {"count": len(findings), "findings": [vars(f) | {"since": f.since.isoformat() if f.since else None} for f in findings]}

    @app.post("/api/llm/fallback")
    async def decide_llm_fallback(req: FallbackDecisionRequest) -> dict[str, Any]:
        if req.fallback_policy is not None:
            orchestrator.settings.llm_fallback_policy = req.fallback_policy
            if hasattr(orchestrator.llm, "set_fallback_policy"):
                orchestrator.llm.set_fallback_policy(req.fallback_policy.value)
        if req.decision == "approve_fallback" and hasattr(orchestrator.llm, "approve_fallback_model"):
            orchestrator.llm.approve_fallback_model(req.fallback_model)
        elif req.decision == "wait_for_primary" and hasattr(orchestrator.llm, "reject_fallback_and_wait_for_primary"):
            orchestrator.llm.reject_fallback_and_wait_for_primary()
        quota = await orchestrator.llm.get_quota_status()
        return {"status": "ok", "llm_quota": quota.to_status_dict()}

    @app.post("/api/events/simulate")
    async def simulate_event(req: SimulateEventRequest) -> dict[str, Any]:
        if not isinstance(orchestrator.smart_home, SmartHomeSimulatorAdapter):
            raise HTTPException(status_code=400, detail="Event simulation requires SmartHomeSimulatorAdapter")

        sim = orchestrator.smart_home
        try:
            if req.scenario == "condensation_risk":
                event = sim.emit_simulated_state_change("sensor.master_bedroom_humidity", "68.5")
            elif req.scenario == "solar_ufh_gain":
                event = sim.emit_simulated_state_change("sensor.outdoor_south_illuminance", "48500")
            elif req.entity_id and req.new_value is not None:
                event = sim.emit_simulated_state_change(
                    req.entity_id,
                    req.new_value,
                    context_user_id=req.context_user_id,
                )
            else:
                raise HTTPException(status_code=400, detail="Provide either scenario or entity_id + new_value")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'\"")) from exc

        logs = await orchestrator.process_state_changed_event(event)
        return {
            "event": event.model_dump(mode="json"),
            "run_logs": [l.model_dump(mode="json") for l in logs],
        }

    @app.post("/api/batch/analyze")
    async def run_batch(req: BatchAnalyzeRequest) -> dict[str, Any]:
        if req.agent_id == "all":
            logs = await orchestrator.run_all_periodic_batch_analyses(
                lookback_hours=req.lookback_hours,
                area_id=req.area_id,
            )
            return {
                "status": "completed",
                "agents_analyzed": len(logs),
                "run_logs": [l.model_dump(mode="json") for l in logs],
                "run_log": logs[0].model_dump(mode="json") if logs else None,
            }
        log = await orchestrator.run_periodic_batch_analysis(
            agent_id=req.agent_id,
            area_id=req.area_id,
            lookback_hours=req.lookback_hours,
        )
        return {"run_log": log.model_dump(mode="json"), "run_logs": [log.model_dump(mode="json")]}

    @app.post("/api/approvals/dismiss-all")
    async def dismiss_all_approvals() -> dict[str, Any]:
        count = await orchestrator.dismiss_all_pending()
        return {"status": "dismissed_all", "count": count}

    @app.post("/api/approvals/{approval_id}/decide")
    async def decide_approval(approval_id: str, req: ApprovalDecisionRequest) -> dict[str, Any]:
        try:
            return await orchestrator.handle_approval_decision(
                approval_id=approval_id,
                decision=req.decision,
                human_note=req.human_note,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agents/custom")
    async def register_custom_agent(spec: AgentSpec) -> dict[str, Any]:
        registered = orchestrator.registry.register_custom_agent(spec)
        orchestrator.invalidate_context_caches()
        return {"status": "registered", "agent": registered.model_dump()}

    @app.post("/api/context-notes")
    async def add_context_note(req: UserContextNoteRequest) -> dict[str, Any]:
        cleaned = req.content.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Context note content cannot be empty")
        note = UserContextNote(
            content=cleaned,
            scope=req.scope.strip() or "global",
            related_entities=[e.strip() for e in req.related_entities if e.strip()],
        )
        await orchestrator.memory.save_user_context_note(note)
        orchestrator.invalidate_context_caches()
        notes = await orchestrator.memory.get_user_context_notes(active_only=True)
        return {
            "status": "saved",
            "note": note.model_dump(mode="json"),
            "user_context_notes": [n.model_dump(mode="json") for n in notes],
        }

    @app.delete("/api/context-notes/{note_id}")
    async def delete_context_note(note_id: str) -> dict[str, Any]:
        deleted = await orchestrator.memory.delete_user_context_note(note_id)
        orchestrator.invalidate_context_caches()
        notes = await orchestrator.memory.get_user_context_notes(active_only=True)
        return {
            "status": "deleted" if deleted else "not_found",
            "user_context_notes": [n.model_dump(mode="json") for n in notes],
        }

    @app.post("/api/ignore-list")
    async def add_ignored_target(req: IgnoredTargetRequest) -> dict[str, Any]:
        cleaned = req.pattern.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Ignore pattern cannot be empty")
        target = IgnoredTarget(pattern=cleaned, reason=req.reason.strip())
        await orchestrator.memory.save_ignored_target(target)
        orchestrator.invalidate_context_caches()
        targets = await orchestrator.memory.get_ignored_targets()
        return {
            "status": "saved",
            "target": target.model_dump(mode="json"),
            "ignored_targets": [t.model_dump(mode="json") for t in targets],
        }

    @app.delete("/api/ignore-list/{ignore_id}")
    async def delete_ignored_target(ignore_id: str) -> dict[str, Any]:
        deleted = await orchestrator.memory.delete_ignored_target(ignore_id)
        orchestrator.invalidate_context_caches()
        targets = await orchestrator.memory.get_ignored_targets()
        return {
            "status": "deleted" if deleted else "not_found",
            "ignored_targets": [t.model_dump(mode="json") for t in targets],
        }

    @app.post("/api/min-change")
    async def add_min_change(req: MinChangeRequest) -> dict[str, Any]:
        from ha_ai_brain.domain.min_change import MinChangeRule

        pattern = req.pattern.strip().lower()
        if not pattern or "." not in pattern.replace("*", "."):
            raise HTTPException(status_code=400, detail="Give an entity id (sensor.name) or a wildcard such as sensor.*_voltage")
        rules = [r for r in await orchestrator.get_min_change_rules() if r.pattern.lower() != pattern]
        rules.append(MinChangeRule(pattern=pattern, min_change=req.min_change, reason=req.reason.strip()))
        await orchestrator.save_min_change_rules(rules)
        return {"status": "saved", "min_change_rules": [r.model_dump() for r in rules]}

    @app.delete("/api/min-change/{rule_id}")
    async def delete_min_change(rule_id: str) -> dict[str, Any]:
        current = await orchestrator.get_min_change_rules()
        rules = [r for r in current if r.rule_id != rule_id]
        await orchestrator.save_min_change_rules(rules)
        return {"status": "deleted" if len(rules) != len(current) else "not_found", "min_change_rules": [r.model_dump() for r in rules]}

    return app
