"""Deterministic Guardrails, Safety Bounds, and Repeatable Approval Policy Engine."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel

from ha_ai_brain.config import AutonomyLevel
from ha_ai_brain.domain.models import ActionIntent, ActionRiskLevel, ApprovalRule


class GuardrailDecisionType(str, Enum):
    """Outcome of guardrail policy evaluation."""

    EXECUTE_IMMEDIATELY = "execute_immediately"
    REQUIRE_USER_APPROVAL = "require_user_approval"
    SHADOW_LOG_ONLY = "shadow_log_only"
    HARD_BLOCKED = "hard_blocked"


class GuardrailEvaluation(BaseModel):
    """Result returned by the GuardrailEngine for a single ActionIntent."""

    decision: GuardrailDecisionType
    effective_risk: ActionRiskLevel
    signature: str
    reason: str
    matched_rule: ApprovalRule | None = None


class GuardrailEngine:
    """
    Deterministic policy engine protecting the smart home:
    1. Hard physical & security boundaries (e.g. min/max HVAC temp, lock/alarm protection).
    2. Risk-tier escalation for sensitive domains (locks, alarms, exterior covers, water valves).
    3. Repeatable Approval Signature lookup so endorsed actions never prompt again.
    """

    MIN_SAFE_TEMP_C = 12.0
    MAX_SAFE_TEMP_C = 28.0

    CRITICAL_SERVICES = {
        ("lock", "unlock"),
        ("lock", "open"),
        ("alarm_control_panel", "alarm_disarm"),
    }

    # Domains an LLM-authored action may never call: they run arbitrary code/commands or manage the host.
    FORBIDDEN_DOMAINS = frozenset(
        {"shell_command", "python_script", "pyscript", "command_line", "rest_command", "hassio", "script", "recorder"}
    )

    _RISK_ORDER = (ActionRiskLevel.LOW, ActionRiskLevel.MEDIUM, ActionRiskLevel.HIGH, ActionRiskLevel.CRITICAL)

    HIGH_RISK_SERVICES = {
        ("valve", "close_valve"),
        ("homeassistant", "restart"),
        ("homeassistant", "reload_config_entry"),
    }

    def evaluate(
        self,
        intent: ActionIntent,
        autonomy_level: AutonomyLevel,
        notifications_enabled: bool,
        endorsed_rules: dict[str, ApprovalRule],
        rejected_signatures: set[str] | None = None,
    ) -> GuardrailEvaluation:
        """Evaluate an ActionIntent against deterministic safety rules and user approval memory."""
        signature = intent.repeatable_signature()

        # 0. Domains that execute arbitrary code/commands are never allowed from an LLM proposal
        if intent.domain in self.FORBIDDEN_DOMAINS:
            return GuardrailEvaluation(
                decision=GuardrailDecisionType.HARD_BLOCKED,
                effective_risk=ActionRiskLevel.CRITICAL,
                signature=signature,
                reason=f"Hard Safety Guardrail: domain '{intent.domain}' can run arbitrary code or manage the host and is never allowed.",
            )

        # 1. Check if the user previously explicitly banned/rejected this repeatable signature
        matched_rejection = signature in rejected_signatures if rejected_signatures else False
        if rejected_signatures and not matched_rejection:
            matched_rejection = self._matches_rejected_signature(intent, rejected_signatures)

        if matched_rejection:
            return GuardrailEvaluation(
                decision=GuardrailDecisionType.HARD_BLOCKED,
                effective_risk=intent.risk_level,
                signature=signature,
                reason=f"Action signature '{signature}' was previously rejected by the user.",
            )

        # 2. Hard Physical Safety Bounds Check (e.g. Thermostat temperature range)
        if intent.domain == "climate" and intent.service == "set_temperature":
            temp = intent.service_data.get("temperature")
            if temp is not None:
                try:
                    temp_f = float(temp)
                    if not (self.MIN_SAFE_TEMP_C <= temp_f <= self.MAX_SAFE_TEMP_C):
                        return GuardrailEvaluation(
                            decision=GuardrailDecisionType.HARD_BLOCKED,
                            effective_risk=ActionRiskLevel.CRITICAL,
                            signature=signature,
                            reason=(
                                f"Hard Safety Guardrail: Requested temperature {temp_f}°C is outside "
                                f"safe physical bounds [{self.MIN_SAFE_TEMP_C}°C, {self.MAX_SAFE_TEMP_C}°C]."
                            ),
                        )
                except (TypeError, ValueError):
                    pass

        # 3. Deterministic Risk Escalation based on domain/service
        effective_risk = self._determine_effective_risk(intent)

        # 4. Shadow Mode never executes actions
        if autonomy_level == AutonomyLevel.SHADOW:
            return GuardrailEvaluation(
                decision=GuardrailDecisionType.SHADOW_LOG_ONLY,
                effective_risk=effective_risk,
                signature=signature,
                reason="System is in SHADOW mode: action and reasoning logged without execution.",
            )

        # 5. Pure informational notifications sent to the user are always safe to execute
        if intent.domain == "notify":
            return GuardrailEvaluation(
                decision=GuardrailDecisionType.EXECUTE_IMMEDIATELY,
                effective_risk=ActionRiskLevel.LOW,
                signature=signature,
                reason="Informational notification to user is safe to execute immediately.",
            )

        # 6. Critical security actions (unlocking doors, disarming alarms) ALWAYS require approval
        if effective_risk == ActionRiskLevel.CRITICAL:
            return GuardrailEvaluation(
                decision=GuardrailDecisionType.REQUIRE_USER_APPROVAL,
                effective_risk=effective_risk,
                signature=signature,
                reason=f"Critical security guardrail: '{intent.domain}.{intent.service}' always requires explicit human confirmation.",
            )

        # 7. Check if this repeatable action signature has already been endorsed by the user
        existing_rule = endorsed_rules.get(signature)
        if not existing_rule and endorsed_rules:
            # Fallback 1: match by canonical (agent_id, domain_service, target_entity_ids)
            intent_targets = sorted(intent.target_entity_ids)
            svc_tag = f"{intent.domain}.{intent.service}"
            for rule in endorsed_rules.values():
                if (
                    rule.auto_approve
                    and rule.agent_id == intent.agent_id
                    and rule.domain_service == svc_tag
                    and sorted(rule.target_entity_ids) == intent_targets
                ):
                    existing_rule = rule
                    break

            # Fallback 2: Generalized entity-level endorsement across multi-target rules
            # If every target in intent_targets is already covered by user-endorsed rules for this agent & service,
            # auto-approve the action without re-prompting.
            if not existing_rule and intent_targets:
                endorsed_entities_for_svc: set[str] = set()
                candidate_rule: ApprovalRule | None = None
                for rule in endorsed_rules.values():
                    if rule.auto_approve and rule.agent_id == intent.agent_id and rule.domain_service == svc_tag:
                        endorsed_entities_for_svc.update(rule.target_entity_ids)
                        if candidate_rule is None:
                            candidate_rule = rule
                if candidate_rule and all(t in endorsed_entities_for_svc for t in intent_targets):
                    existing_rule = candidate_rule

        if existing_rule and existing_rule.auto_approve:
            return GuardrailEvaluation(
                decision=GuardrailDecisionType.EXECUTE_IMMEDIATELY,
                effective_risk=effective_risk,
                signature=signature,
                reason=f"Auto-approved via user-endorsed repeatable rule (used {existing_rule.execution_count} times).",
                matched_rule=existing_rule,
            )

        # 8. Evaluate based on Autonomy Level & Notification Preferences
        if autonomy_level == AutonomyLevel.AUTONOMOUS:
            if effective_risk in (ActionRiskLevel.LOW, ActionRiskLevel.MEDIUM):
                return GuardrailEvaluation(
                    decision=GuardrailDecisionType.EXECUTE_IMMEDIATELY,
                    effective_risk=effective_risk,
                    signature=signature,
                    reason=f"AUTONOMOUS mode: '{effective_risk.value}' risk action executed automatically.",
                )

        # If notifications are disabled by user preference, allow LOW/MEDIUM actions automatically
        if not notifications_enabled and effective_risk in (ActionRiskLevel.LOW, ActionRiskLevel.MEDIUM):
            return GuardrailEvaluation(
                decision=GuardrailDecisionType.EXECUTE_IMMEDIATELY,
                effective_risk=effective_risk,
                signature=signature,
                reason="Notifications disabled by user: executing non-high-risk action automatically.",
            )

        return GuardrailEvaluation(
            decision=GuardrailDecisionType.REQUIRE_USER_APPROVAL,
            effective_risk=effective_risk,
            signature=signature,
            reason=(
                f"Requires confirmation ({autonomy_level.value} mode, risk={effective_risk.value}). "
                "Approve as repeatable to never be asked again for this pattern."
            ),
        )

    @staticmethod
    def _matches_rejected_signature(intent: ActionIntent, rejected_signatures: set[str]) -> bool:
        """
        Match an intent against previously rejected signatures of the same agent and service.
        Signature layout: `sig:<agent_id>:<domain.service>:<targets or automation slug[:targets]>`.
        Targets are compared as exact entity ids (never as substrings), so rejecting `light.kitchen`
        does not also block `light.kitchen_ceiling`.
        """
        svc_tag = f"{intent.domain}.{intent.service}"
        intent_targets = set(intent.target_entity_ids)
        slug = ""
        if intent.domain == "automation":
            alias = (intent.native_automation.alias if intent.native_automation else "") or str(intent.service_data.get("alias", ""))
            slug = re.sub(r"[^a-z0-9]+", "_", alias.lower()).strip("_")

        for rej_sig in rejected_signatures:
            parts = rej_sig.split(":", 3)
            if len(parts) < 4 or parts[0] != "sig" or parts[1] != intent.agent_id or parts[2] != svc_tag:
                continue
            rejected_tokens = {tok for tok in re.split(r"[,:]", parts[3]) if tok}
            if not intent_targets:
                return True
            if intent_targets & rejected_tokens:
                return True
            if slug and slug in rejected_tokens:
                return True
        return False

    @classmethod
    def _max_risk(cls, *levels: ActionRiskLevel) -> ActionRiskLevel:
        return max(levels, key=cls._RISK_ORDER.index)

    def _determine_effective_risk(self, intent: ActionIntent) -> ActionRiskLevel:
        """Compute deterministic floor risk for sensitive services."""
        pair = (intent.domain, intent.service)
        if pair in self.CRITICAL_SERVICES:
            return ActionRiskLevel.CRITICAL
        if pair in self.HIGH_RISK_SERVICES:
            return ActionRiskLevel.HIGH

        if intent.domain == "cover":
            opening = intent.service != "close_cover"
            for entity_id in intent.target_entity_ids:
                # Opening a garage door or gate exposes the property; closing one is never escalated.
                if opening and ("garage" in entity_id or "gate" in entity_id):
                    return ActionRiskLevel.CRITICAL
                if any(k in entity_id for k in ("blind", "shade", "curtain", "shutter")):
                    return intent.risk_level
            pos = intent.service_data.get("position", 100 if intent.service == "open_cover" else 0)
            try:
                if float(pos) > 30:
                    return self._max_risk(intent.risk_level, ActionRiskLevel.HIGH)
            except (TypeError, ValueError):
                pass
            return self._max_risk(intent.risk_level, ActionRiskLevel.MEDIUM)

        if intent.domain == "automation":
            return self._max_risk(intent.risk_level, ActionRiskLevel.MEDIUM)

        return intent.risk_level
