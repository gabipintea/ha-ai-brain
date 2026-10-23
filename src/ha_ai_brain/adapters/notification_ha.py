"""Home Assistant Actionable Notification Adapter (Companion App Push + In-Memory History)."""

from __future__ import annotations

from typing import Any

from ha_ai_brain.domain.models import AdvisoryInsight, PendingApproval
from ha_ai_brain.ports.notification import NotificationPort
from ha_ai_brain.ports.smart_home import SmartHomePort


class HomeAssistantNotificationAdapter(NotificationPort):
    """
    Sends actionable notifications via Home Assistant's `notify` domain with action buttons:
    - Approve Once
    - Approve & Always Allow (Repeatable)
    - Reject
    """

    def __init__(self, smart_home: SmartHomePort, notify_service: str = "notify.notify") -> None:
        self.smart_home = smart_home
        self.notify_service = notify_service
        self.sent_notifications: list[dict[str, Any]] = []

    async def send_approval_request(self, pending: PendingApproval) -> None:
        domain, _, service = self.notify_service.partition(".")
        service = service or "notify"
        intent = pending.intent
        aid = pending.approval_id

        payload = {
            "title": f"AI Brain Approval ({intent.agent_id})",
            "message": (
                f"Action: {intent.domain}.{intent.service} on {', '.join(intent.target_entity_ids)}\n"
                f"Why: {intent.rationale}"
            ),
            "data": {
                "tag": f"ha_ai_brain_{aid}",
                "actions": [
                    {
                        "action": f"BRAIN_APPROVE_ONCE:{aid}",
                        "title": "Approve Once",
                    },
                    {
                        "action": f"BRAIN_APPROVE_REPEATABLE:{aid}",
                        "title": "Always Allow This",
                    },
                    {
                        "action": f"BRAIN_REJECT:{aid}",
                        "title": "Reject",
                    },
                ],
            },
        }
        self.sent_notifications.append({"type": "approval_request", "approval_id": aid, "payload": payload})
        await self.smart_home.call_service(
            domain=domain or "notify",
            service=service,
            target_entity_ids=[],
            service_data=payload,
        )

    async def send_advisory_alert(self, insight: AdvisoryInsight) -> None:
        domain, _, service = self.notify_service.partition(".")
        service = service or "notify"
        payload = {
            "title": f"AI Brain Insight: {insight.title}",
            "message": f"{insight.finding_details}\nRecommendation: {insight.recommended_human_action}",
        }
        self.sent_notifications.append({"type": "advisory_insight", "insight_id": insight.insight_id, "payload": payload})
        await self.smart_home.call_service(
            domain=domain or "notify",
            service=service,
            target_entity_ids=[],
            service_data=payload,
        )
