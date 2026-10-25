"""Port Interface for Episodic Feedback Memory, Repeatable Approvals, and Audit Trail."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ha_ai_brain.domain.models import (
    AdvisoryInsight,
    AgentRunLog,
    ApprovalRule,
    ExpectedOutcome,
    FeedbackEpisode,
    IgnoredTarget,
    PendingApproval,
    UserContextNote,
)


class MemoryStorePort(ABC):
    """Persists endorsed reactions, feedback episodes, approval rules, and agent thought logs."""

    @abstractmethod
    async def save_feedback(self, episode: FeedbackEpisode) -> None:
        """Record an explicit or implicit human feedback episode."""

    @abstractmethod
    async def get_relevant_feedback(self, agent_id: str, area_id: str | None = None, limit: int = 20) -> list[FeedbackEpisode]:
        """Retrieve historical feedback episodes for an agent/area to guide future reasoning."""

    @abstractmethod
    async def save_approval_rule(self, rule: ApprovalRule) -> None:
        """Persist a repeatable action signature approved by the user."""

    @abstractmethod
    async def increment_rule_usage(self, signature: str) -> None:
        """Increment execution count when an endorsed repeatable rule is auto-triggered."""

    @abstractmethod
    async def get_endorsed_rules(self) -> dict[str, ApprovalRule]:
        """Return all active repeatable approval rules keyed by signature."""

    async def delete_approval_rule(self, signature: str) -> bool:
        """Revoke an endorsed repeatable rule so the action asks for approval again. Returns True if removed."""
        return False

    async def get_rejected_suggestions(self) -> list[FeedbackEpisode]:
        """Return the most recent explicit rejection per blocked signature (newest first)."""
        return []

    async def get_accepted_automations(self) -> list[FeedbackEpisode]:
        """Return historical native automations accepted and deployed by the homeowner."""
        return []

    async def unblock_rejected_signature(self, signature: str) -> bool:
        """Remove explicit rejections for a signature so the suggestion may be proposed again."""
        return False

    @abstractmethod
    async def get_rejected_signatures(self) -> set[str]:
        """Return signatures explicitly rejected by the user."""

    @abstractmethod
    async def save_pending_approval(self, pending: PendingApproval) -> None:
        """Store an action awaiting human approval."""

    @abstractmethod
    async def get_pending_approvals(self) -> list[PendingApproval]:
        """List all unresolved pending approval requests."""

    @abstractmethod
    async def resolve_pending_approval(self, approval_id: str, status: str) -> PendingApproval | None:
        """Mark a pending approval as approved_once, approved_repeatable, rejected, or dismissed."""

    async def dismiss_pending_approval(self, approval_id: str) -> bool:
        """Dismiss a pending proposal without executing or recording a permanent rejection."""
        return False

    async def dismiss_all_pending_approvals(self) -> int:
        """Dismiss all currently pending proposals."""
        return 0

    async def get_approval_statuses(self) -> dict[str, str]:
        """Return a mapping of approval_id -> status across recorded approvals."""
        return {}

    @abstractmethod
    async def save_run_log(self, log: AgentRunLog) -> None:
        """Record a full agent reasoning trace for explainability."""

    @abstractmethod
    async def get_recent_run_logs(self, limit: int = 25, offset: int = 0) -> list[AgentRunLog]:
        """Fetch recent agent invocation logs with optional pagination offset."""

    @abstractmethod
    async def get_run_log(self, run_id: str) -> AgentRunLog | None:
        """Fetch a single agent invocation log by its run_id."""

    @abstractmethod
    async def get_run_logs_count(self) -> int:
        """Return total count of recorded agent run logs."""

    async def get_last_batch_run_time(self) -> datetime | None:
        """Return the timestamp of the most recent periodic batch run."""
        return None

    @abstractmethod
    async def clear_run_logs(self) -> int:
        """Clear all agent run logs to free up database storage."""

    @abstractmethod
    async def save_advisory_insight(self, insight: AdvisoryInsight) -> None:
        """Store a structural/hardware/insulation recommendation."""

    @abstractmethod
    async def get_advisory_insights(self, limit: int = 50, status: str | None = None) -> list[AdvisoryInsight]:
        """List discovered advisory insights, optionally filtered by status."""

    @abstractmethod
    async def get_active_insights_count(self) -> int:
        """Return count of active (un-dismissed, un-rejected) advisory insights."""

    @abstractmethod
    async def resolve_advisory_insight(self, insight_id: str, status: str, rejection_reason: str = "") -> AdvisoryInsight | None:
        """Update an insight's status ('read', 'dismissed', 'rejected') and optional rejection reason."""

    @abstractmethod
    async def delete_advisory_insight(self, insight_id: str) -> bool:
        """Delete an advisory insight by ID."""

    @abstractmethod
    async def dismiss_all_advisory_insights(self) -> int:
        """Dismiss all currently active advisory insights."""

    @abstractmethod
    async def delete_all_advisory_insights(self, status: str | None = None) -> int:
        """Delete all advisory insights, optionally filtered by status."""

    @abstractmethod
    async def get_rejected_insights(self) -> list[AdvisoryInsight]:
        """Retrieve all homeowner-rejected advisory insights."""

    @abstractmethod
    async def unblock_rejected_insight(self, insight_id: str) -> bool:
        """Unblock a rejected insight so agents may propose it again."""

    @abstractmethod
    async def save_expected_outcome(self, outcome: ExpectedOutcome) -> None:
        """Schedule a closed-loop outcome check."""

    async def save_user_context_note(self, note: UserContextNote) -> None:
        """Persist a free-form user context directive or hardware note."""

    async def get_user_context_notes(self, active_only: bool = True) -> list[UserContextNote]:
        """Retrieve user-provided context notes."""
        return []

    async def delete_user_context_note(self, note_id: str) -> bool:
        """Delete a user context note by ID."""
        return False

    async def save_ignored_target(self, target: IgnoredTarget) -> None:
        """Persist an entity/device ignore pattern."""

    async def get_ignored_targets(self) -> list[IgnoredTarget]:
        """Retrieve all user-managed ignored entities/patterns."""
        return []

    async def delete_ignored_target(self, ignore_id: str) -> bool:
        """Remove an entry from the user-managed ignore list."""
        return False

    async def save_ui_preference(self, key: str, value: str) -> None:
        """Persist a runtime UI preference (such as chosen notification_service or default_autonomy)."""

    async def get_ui_preferences(self) -> dict[str, str]:
        """Return all persisted UI preferences."""
        return {}
