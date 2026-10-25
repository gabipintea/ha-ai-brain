"""Domain Entities and Value Objects for the HA AI Brain."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ActionPriority(int, Enum):
    """Priority hierarchy used by the Conflict Arbiter when multiple agents target the same entity."""

    ENERGY_OPTIMIZATION = 10
    COMFORT_ENHANCEMENT = 30
    HABIT_PREDICTION = 40
    EQUIPMENT_AND_STRUCTURAL_PROTECTION = 70  # e.g., Condensation / moisture damage / frost protection
    EXPLICIT_HUMAN_OVERRIDE = 90
    LIFE_AND_SECURITY_SAFETY = 100


class ActionRiskLevel(str, Enum):
    """Safety sensitivity tier evaluated by the Guardrail Engine."""

    LOW = "low"            # e.g., Adjusting fan speed, turning on dehumidifier, sending info notification
    MEDIUM = "medium"      # e.g., Adjusting UFH thermostat setpoint, opening motorized window slightly, creating HA automation
    HIGH = "high"          # e.g., Opening exterior garage/door, shutting main water valve, reloading HA integration
    CRITICAL = "critical"  # e.g., Unlocking front door, disarming security alarm (always requires human approval)


class FeedbackPolarity(str, Enum):
    """Whether an agent action was endorsed, rejected, or manually overridden by a human."""

    ENDORSED_ONCE = "endorsed_once"
    ENDORSED_REPEATABLE = "endorsed_repeatable"
    REJECTED_EXPLICIT = "rejected_explicit"
    OVERRIDDEN_IMPLICIT = "overridden_implicit"  # Human manually reverted device state shortly after AI action
    OUTCOME_VERIFIED_SUCCESS = "outcome_verified_success"
    OUTCOME_VERIFIED_FAILURE = "outcome_verified_failure"


class EventOrigin(str, Enum):
    """Causal origin of a Home Assistant state transition."""

    SENSOR_TELEMETRY = "sensor_telemetry"      # Passive environmental/meter sensor reading
    HUMAN_OR_PHYSICAL = "human_or_physical"    # Human UI interaction or physical wall switch
    HA_AUTOMATION = "ha_automation"            # Triggered by a native Home Assistant automation
    AI_BRAIN = "ai_brain"                      # Triggered by an HA AI Brain service call


class EntityState(BaseModel):
    """Normalized Home Assistant entity state snapshot."""

    entity_id: str
    state: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    area_id: str | None = None
    domain: str = ""
    device_class: str | None = None
    unit_of_measurement: str | None = None
    last_changed: datetime = Field(default_factory=utc_now)
    last_updated: datetime = Field(default_factory=utc_now)
    context_id: str | None = None
    context_user_id: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.domain and "." in self.entity_id:
            self.domain = self.entity_id.split(".", 1)[0]
        if not self.device_class and "device_class" in self.attributes:
            self.device_class = str(self.attributes["device_class"])
        if not self.unit_of_measurement and "unit_of_measurement" in self.attributes:
            self.unit_of_measurement = str(self.attributes["unit_of_measurement"])
        if not self.area_id and "area_id" in self.attributes:
            self.area_id = str(self.attributes["area_id"])

    @property
    def numeric_value(self) -> float | None:
        try:
            return float(self.state)
        except (ValueError, TypeError):
            return None


class StateChangedEvent(BaseModel):
    """Real-time state transition emitted by Home Assistant."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    entity_id: str
    old_state: EntityState | None = None
    new_state: EntityState
    timestamp: datetime = Field(default_factory=utc_now)
    context_id: str | None = None
    context_parent_id: str | None = None
    context_user_id: str | None = None
    origin: EventOrigin = EventOrigin.HUMAN_OR_PHYSICAL
    triggered_by_automation_id: str | None = None


class SemanticEventFrame(BaseModel):
    """Debounced, corroborated bundle of significant state transitions routed to a specialized agent."""

    frame_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_agent_id: str
    area_id: str | None = None
    trigger_events: list[StateChangedEvent] = Field(default_factory=list)
    corroborated_states: dict[str, EntityState] = Field(default_factory=dict)
    significance_reason: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class DerivedSignal(BaseModel):
    """Factual signal computed by the Computation Sub-Agent (e.g., dew point, heat loss rate dT/dt)."""

    signal_name: str
    value: float | str | dict[str, Any]
    unit: str = ""
    formula_or_method: str = ""
    source_entities: list[str] = Field(default_factory=list)
    interpretation: str = ""
    python_code_executed: str = ""


class ResearchFinding(BaseModel):
    """Scientific, physical, or domain fact retrieved by the Research Sub-Agent."""

    topic: str
    principle_summary: str
    recommended_thresholds_or_physics: str
    actionable_implications: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ExpectedOutcome(BaseModel):
    """Closed-loop check scheduled after an agent executes an action to verify physical effectiveness."""

    outcome_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_id: str
    agent_id: str
    monitored_entity_id: str
    baseline_value: float | str
    expected_direction_or_target: str  # e.g., "decrease_by_at_least_3_percent" or "reach_21.5C"
    check_after_minutes: int = 30
    status: str = "pending"


class NativeAutomationProposal(BaseModel):
    """A native Home Assistant automation synthesized by an agent to crystallize a pattern with 0 ongoing tokens."""

    automation_id: str = Field(default_factory=lambda: f"ai_brain_{uuid.uuid4().hex[:8]}")
    alias: str
    description: str
    mode: str = "single"
    trigger: list[dict[str, Any]]
    condition: list[dict[str, Any]] = Field(default_factory=list)
    action: list[dict[str, Any]]
    discovered_pattern_rationale: str = ""

    def extract_target_entities(self) -> list[str]:
        """Extract all physical entity IDs targeted by this automation's actions."""
        targets: list[str] = []
        for act in self.action:
            if not isinstance(act, dict):
                continue
            tgt = act.get("target")
            if isinstance(tgt, dict):
                eids = tgt.get("entity_id", [])
                if isinstance(eids, str) and eids:
                    targets.append(eids)
                elif isinstance(eids, list):
                    targets.extend(str(e) for e in eids if e)
            direct_eid = act.get("entity_id")
            if isinstance(direct_eid, str) and direct_eid:
                targets.append(direct_eid)
            elif isinstance(direct_eid, list):
                targets.extend(str(e) for e in direct_eid if e)
            data = act.get("data")
            if isinstance(data, dict):
                data_eid = data.get("entity_id")
                if isinstance(data_eid, str) and data_eid:
                    targets.append(data_eid)
                elif isinstance(data_eid, list):
                    targets.extend(str(e) for e in data_eid if e)
        seen: set[str] = set()
        res: list[str] = []
        for t in targets:
            if t not in seen:
                seen.add(t)
                res.append(t)
        return res


class AdvisoryInsight(BaseModel):
    """Architectural, hardware, insulation, or parameter recommendation discovered during analysis."""

    insight_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    category: str  # e.g., "thermal_insulation", "ufh_curve_tuning", "device_addition", "energy_efficiency"
    title: str
    finding_details: str
    evidence_metrics: dict[str, Any] = Field(default_factory=dict)
    recommended_human_action: str
    estimated_impact: str = ""
    status: str = "active"  # "active", "read", "dismissed", "rejected"
    rejection_reason: str = ""
    run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class ActionIntent(BaseModel):
    """A reaction or automation proposed by an autonomous agent before Arbiter & Guardrail evaluation."""

    intent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    area_id: str | None = None
    domain: str                              # e.g., "fan", "climate", "cover", "light", "notify", "automation"
    service: str                             # e.g., "set_percentage", "set_temperature", "set_cover_position"
    target_entity_ids: list[str]
    service_data: dict[str, Any] = Field(default_factory=dict)
    cause_category: str                      # e.g., "window_condensation_prevention", "solar_gain_pre_cooling"
    rationale: str                           # Explainable reasoning chain
    derived_signals_used: list[str] = Field(default_factory=list)
    priority: ActionPriority = ActionPriority.COMFORT_ENHANCEMENT
    risk_level: ActionRiskLevel = ActionRiskLevel.LOW
    expected_outcome: ExpectedOutcome | None = None
    native_automation: NativeAutomationProposal | None = None
    run_id: str | None = None
    approval_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    def repeatable_signature(self) -> str:
        """
        Compute a canonical, repeatable signature for this class of action.
        Canonical signature is derived strictly from (agent_id, domain.service, target_entity_ids).
        For native automations, derives the signature from the canonical automation alias
        and controlled entities rather than an ephemeral random hex ID (e.g. ai_brain_...).
        By excluding free-form LLM rationale and variable cause_category descriptions,
        rules and rejections endorsed by the user will reliably match future proposals.
        """
        if self.domain == "automation" and (self.native_automation is not None or "alias" in self.service_data):
            alias = ""
            if self.native_automation:
                alias = self.native_automation.alias
            elif "alias" in self.service_data:
                alias = str(self.service_data["alias"])
            import re
            slug = re.sub(r"[^a-z0-9]+", "_", alias.lower()).strip("_") if alias else "native_automation"
            controlled: list[str] = []
            auto_actions = []
            if self.native_automation and self.native_automation.action:
                auto_actions = self.native_automation.action
            elif isinstance(self.service_data.get("action"), list):
                auto_actions = self.service_data["action"]
            for act in auto_actions:
                if isinstance(act, dict):
                    t = act.get("target", {})
                    if isinstance(t, dict) and "entity_id" in t:
                        e = t["entity_id"]
                        if isinstance(e, list):
                            controlled.extend(str(x) for x in e)
                        elif e:
                            controlled.append(str(e))
                    elif "entity_id" in act:
                        e = act["entity_id"]
                        if isinstance(e, list):
                            controlled.extend(str(x) for x in e)
                        elif e:
                            controlled.append(str(e))
            targets = ",".join(sorted(set(controlled))) if controlled else slug
            return f"sig:{self.agent_id}:automation.upsert_native_automation:{slug}:{targets}"

        targets = ",".join(sorted(self.target_entity_ids)) or "all"
        return f"sig:{self.agent_id}:{self.domain}.{self.service}:{targets}"


class ApprovalRule(BaseModel):
    """Stored permission rule for repeatable actions endorsed by the user."""

    signature: str
    agent_id: str
    domain_service: str
    target_entity_ids: list[str]
    cause_category: str
    description: str
    auto_approve: bool = True
    approved_by: str = "user"
    created_at: datetime = Field(default_factory=utc_now)
    execution_count: int = 0


class PendingApproval(BaseModel):
    """An action awaiting human confirmation via HA actionable notification or dashboard."""

    approval_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent: ActionIntent
    signature: str
    status: str = "pending"  # pending, approved_once, approved_repeatable, rejected, expired
    run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None


class FeedbackEpisode(BaseModel):
    """Episodic memory entry recording human feedback or outcome verification for reinforcement."""

    episode_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    area_id: str | None = None
    cause_category: str
    action_signature: str
    target_entity_ids: list[str]
    service_called: str
    service_data: dict[str, Any] = Field(default_factory=dict)
    polarity: FeedbackPolarity
    human_note: str = ""
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class UserContextNote(BaseModel):
    """
    Free-form natural-language context, hardware limitation, or behavioral directive
    provided by the user at any time (e.g., 'The humidifier on the Philips Air Purifier is
    mechanically broken; I only use it to purify air').
    """

    note_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    scope: str = "global"  # e.g., "global", an entity_id, an area_id, or an agent_id
    related_entities: list[str] = Field(default_factory=list)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class IgnoredTarget(BaseModel):
    """
    User-managed Ignore List entry (exact entity_id, device prefix, or wildcard pattern like
    `sensor.myengie_*` or `humidifier.bedroom_none`). Ignored entities are stripped from both
    real-time triage and agent state snapshots so they never trigger runs or consume LLM context.
    """

    ignore_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pattern: str
    reason: str = ""
    created_at: datetime = Field(default_factory=utc_now)

    def matches(self, entity_id: str) -> bool:
        import fnmatch

        pat = self.pattern.strip().lower()
        eid = entity_id.strip().lower()
        if not pat:
            return False
        if "*" in pat or "?" in pat:
            return fnmatch.fnmatch(eid, pat)
        if "." in pat:
            return eid == pat or eid.startswith(pat + "_")
        return pat in eid


class AgentSpec(BaseModel):
    """Declarative specification for built-in or user-defined custom agents (e.g., Brewery, Solar)."""

    agent_id: str
    name: str
    specialty: str
    description: str
    monitored_domains: list[str] = Field(default_factory=list)
    monitored_device_classes: list[str] = Field(default_factory=list)
    controllable_domains: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    custom_domain_rules_prompt: str = ""
    enabled: bool = True
    is_custom: bool = False


class AgentRunLog(BaseModel):
    """Complete explainability audit log of an agent invocation."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    mode: str  # "realtime_stream" or "periodic_batch"
    trigger_summary: str
    research_findings: list[ResearchFinding] = Field(default_factory=list)
    derived_signals: list[DerivedSignal] = Field(default_factory=list)
    proposed_intents: list[ActionIntent] = Field(default_factory=list)
    advisory_insights: list[AdvisoryInsight] = Field(default_factory=list)
    execution_results: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
