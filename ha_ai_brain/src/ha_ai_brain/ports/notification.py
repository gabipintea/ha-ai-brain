"""Port Interface for Actionable Push Notifications and Human-in-the-Loop Approvals."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ha_ai_brain.domain.models import AdvisoryInsight, PendingApproval


class NotificationPort(ABC):
    """Dispatches actionable confirmation prompts and informational alerts to the human."""

    @abstractmethod
    async def send_approval_request(self, pending: PendingApproval) -> None:
        """
        Send an actionable push notification (e.g. via HA Companion App) with actions:
        - APPROVE_ONCE_{approval_id}
        - APPROVE_REPEATABLE_{approval_id}
        - REJECT_{approval_id}
        """

    @abstractmethod
    async def send_advisory_alert(self, insight: AdvisoryInsight) -> None:
        """Notify the human of an important physical/insulation/automation insight."""

    async def dismiss_approval_notification(self, approval_id: str) -> None:
        """Dismiss/clear the actionable push notification from user devices."""
        pass
