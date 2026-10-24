"""FastAPI Server & Dependency Container for HA AI Brain Add-on and Control Plane."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel

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
from ha_ai_brain.api.dashboard_html import DASHBOARD_HTML, render_dashboard_html
from ha_ai_brain.application.orchestrator import BrainOrchestrator
from ha_ai_brain.config import AutonomyLevel, BrainSettings, FallbackPolicy, OperatingMode
from ha_ai_brain.domain.models import AgentSpec, IgnoredTarget, UserContextNote
from ha_ai_brain.ports.llm import LLMProviderPort


class SettingsUpdateRequest(BaseModel):
    operating_mode: OperatingMode | None = None
    default_autonomy: AutonomyLevel | None = None
    llm_fallback_policy: FallbackPolicy | None = None
    notification_service: str | None = None
    notifications_enabled: bool | None = None
    site_context: str | None = None
    llm_model: str | None = None
    llm_fast_model: str | None = None
    llm_api_key: str | None = None


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
    agent_id: str = "climate_thermal_agent"
    area_id: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str  # "approved_once", "approved_repeatable", "rejected"
    human_note: str = ""


class UserContextNoteRequest(BaseModel):
    content: str
    scope: str = "global"
    related_entities: list[str] = []


class IgnoredTargetRequest(BaseModel):
    pattern: str
    reason: str = ""


def build_orchestrator(settings: BrainSettings | None = None) -> BrainOrchestrator:
    """Assemble the Hexagonal Architecture ports and adapters into a BrainOrchestrator."""
    import logging
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    cfg = settings or BrainSettings.from_env()
    if cfg.db_path and "/" in cfg.db_path:
        Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)

    if cfg.use_simulator or not cfg.ha_token:
        smart_home = SmartHomeSimulatorAdapter()
    else:
        smart_home = HomeAssistantAdapter(
            base_url=cfg.ha_url,
            ws_url=cfg.ha_ws_url,
            token=cfg.ha_token,
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
    )


def create_app(settings: BrainSettings | None = None) -> Any:
    """Create the FastAPI application with HA Ingress dashboard, REST API, and background stream/scheduler workers."""
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse

    orchestrator = build_orchestrator(settings=settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await orchestrator.start_background_workers()
        try:
            yield
        finally:
            await orchestrator.stop_background_workers()

    app = FastAPI(
        title="HA AI Brain",
        version="0.1.0",
        description="Autonomous Multi-Agent Cognitive Layer for Home Assistant (Hexagonal Architecture + LangGraph)",
        lifespan=lifespan,
    )
    app.state.orchestrator = orchestrator

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
        pending = await orchestrator.memory.get_pending_approvals()
        rules = await orchestrator.memory.get_endorsed_rules()
        rejected = await orchestrator.memory.get_rejected_suggestions()
        logs = await orchestrator.memory.get_recent_run_logs(limit=10)
        total_logs = await orchestrator.memory.get_run_logs_count()
        insights = await orchestrator.memory.get_advisory_insights(limit=10)
        context_notes = await orchestrator.memory.get_user_context_notes(active_only=True)
        ignored_targets = await orchestrator.memory.get_ignored_targets()
        notify_services = await orchestrator.smart_home.get_available_notify_services()

        settings_dict = orchestrator.settings.model_dump()
        raw_key = settings_dict.pop("llm_api_key", "")
        settings_dict["has_api_key"] = bool(raw_key)
        if raw_key:
            prefix = raw_key[:4]
            suffix = raw_key[-4:] if len(raw_key) >= 8 else ""
            settings_dict["masked_api_key"] = f"{prefix}••••••••{suffix}"
        else:
            settings_dict["masked_api_key"] = ""

        return {
            "settings": settings_dict,
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
            "recent_logs": [l.model_dump(mode="json") for l in logs],
            "total_logs_count": total_logs,
            "advisory_insights": [i.model_dump(mode="json") for i in insights],
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

        resp_settings = orchestrator.settings.model_dump()
        raw_key = resp_settings.pop("llm_api_key", "")
        resp_settings["has_api_key"] = bool(raw_key)
        resp_settings["masked_api_key"] = f"{raw_key[:4]}••••••••{raw_key[-4:]}" if len(raw_key) >= 8 else ("••••" if raw_key else "")
        return {"status": "updated", "settings": resp_settings}

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

        logs = await orchestrator.process_state_changed_event(event)
        return {
            "event": event.model_dump(mode="json"),
            "run_logs": [l.model_dump(mode="json") for l in logs],
        }

    @app.post("/api/batch/analyze")
    async def run_batch(req: BatchAnalyzeRequest) -> dict[str, Any]:
        log = await orchestrator.run_periodic_batch_analysis(agent_id=req.agent_id, area_id=req.area_id)
        return {"run_log": log.model_dump(mode="json")}

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
        notes = await orchestrator.memory.get_user_context_notes(active_only=True)
        return {
            "status": "saved",
            "note": note.model_dump(mode="json"),
            "user_context_notes": [n.model_dump(mode="json") for n in notes],
        }

    @app.delete("/api/context-notes/{note_id}")
    async def delete_context_note(note_id: str) -> dict[str, Any]:
        deleted = await orchestrator.memory.delete_user_context_note(note_id)
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
        targets = await orchestrator.memory.get_ignored_targets()
        return {
            "status": "saved",
            "target": target.model_dump(mode="json"),
            "ignored_targets": [t.model_dump(mode="json") for t in targets],
        }

    @app.delete("/api/ignore-list/{ignore_id}")
    async def delete_ignored_target(ignore_id: str) -> dict[str, Any]:
        deleted = await orchestrator.memory.delete_ignored_target(ignore_id)
        targets = await orchestrator.memory.get_ignored_targets()
        return {
            "status": "deleted" if deleted else "not_found",
            "ignored_targets": [t.model_dump(mode="json") for t in targets],
        }

    return app
