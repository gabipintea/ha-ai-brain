"""Port Interface for Actionable Push Notifications and Human-in-the-Loop Approvals."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ha_ai_brain.domain.models import ActionIntent, AdvisoryInsight, PendingApproval


class NotificationPort(ABC):
    """Dispatches actionable confirmation prompts and informational alerts to the human."""

    @abstractmethod
    async def send_approval_request(self, pending: PendingApproval, urgent: bool = False) -> None:
        """
        Send an actionable push notification (e.g. via HA Companion App) with actions:
        - APPROVE_ONCE_{approval_id}
        - APPROVE_REPEATABLE_{approval_id}
        - REJECT_{approval_id}
        """

    @abstractmethod
    async def send_advisory_alert(self, insight: AdvisoryInsight, urgent: bool = False) -> None:
        """Notify the human of an important physical/insulation/automation insight (`urgent` = time-sensitive push)."""

    async def send_batch_summary(
        self, approvals: list[PendingApproval], insights: list[AdvisoryInsight]
    ) -> None:
        """Send a single consolidated push notification when a batch scan produces multiple items."""
        for pending in approvals:
            await self.send_approval_request(pending)
        for insight in insights:
            await self.send_advisory_alert(insight)

    async def send_action_taken(self, intent: ActionIntent, undo_id: str | None) -> None:
        """Tell the human the brain acted on its own, with an Undo button when the action is reversible."""

    async def dismiss_approval_notification(self, approval_id: str) -> None:
        """Dismiss/clear the actionable push notification from user devices."""
        pass
