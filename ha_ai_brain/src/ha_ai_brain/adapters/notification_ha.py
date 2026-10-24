"""Home Assistant Actionable Notification Adapter (Companion App Push + In-Memory History)."""

from __future__ import annotations

import logging
from typing import Any

from ha_ai_brain.domain.models import AdvisoryInsight, PendingApproval
from ha_ai_brain.ports.notification import NotificationPort
from ha_ai_brain.ports.smart_home import SmartHomePort

logger = logging.getLogger(__name__)


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

    async def _resolve_service_name(self) -> tuple[str, str]:
        """
        Intelligently resolve the configured notification service name against available services in HA.
        Handles cases like:
        - User configured 'notify.gabriels_iphone' -> resolves to 'notify.mobile_app_gabriels_iphone'
        - User configured 'mobile_app_gabriels_iphone' -> resolves to domain='notify', service='mobile_app_gabriels_iphone'
        - User configured invalid/missing service -> falls back to 'notify.notify'
        """
        raw = (self.notify_service or "notify.notify").strip()
        domain, _, service = raw.partition(".")
        if not service:
            service = domain
            domain = "notify"
        domain = domain or "notify"

        if hasattr(self.smart_home, "get_available_notify_services"):
            available = await self.smart_home.get_available_notify_services()
            full = f"{domain}.{service}"
            if full in available:
                return domain, service

            # Try prefixing with mobile_app_
            mobile_candidate = f"notify.mobile_app_{service}"
            if mobile_candidate in available:
                return "notify", f"mobile_app_{service}"

            # Try matching substring (e.g. 'gabriels_iphone' in 'notify.mobile_app_gabriels_iphone')
            for avail in available:
                if service in avail or avail.endswith(f"_{service}"):
                    d, _, s = avail.partition(".")
                    return d or "notify", s

            # Fallback to notify.notify if available, else first available
            if "notify.notify" in available:
                return "notify", "notify"
            if available:
                d, _, s = available[0].partition(".")
                return d or "notify", s

        return domain, service

    async def send_approval_request(self, pending: PendingApproval) -> None:
        domain, service = await self._resolve_service_name()
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
                "group": "ha_ai_brain_approvals",
                "url": "/ha_ai_brain",
                "clickAction": "/ha_ai_brain",
                "actions": [
                    {
                        "action": f"BRAIN_APPROVE_ONCE:{aid}",
                        "title": "Approve Once",
                    },
                    {
                        "action": f"BRAIN_APPROVE_REPEATABLE:{aid}",
                        "title": "Always Allow",
                    },
                    {
                        "action": f"BRAIN_DISMISS:{aid}",
                        "title": "Dismiss",
                    },
                    {
                        "action": f"BRAIN_REJECT:{aid}",
                        "title": "Reject",
                    },
                ],
            },
        }
        self.sent_notifications.append({"type": "approval_request", "approval_id": aid, "payload": payload})
        try:
            await self.smart_home.call_service(
                domain=domain,
                service=service,
                target_entity_ids=[],
                service_data=payload,
            )
        except Exception as exc:
            logger.warning("Failed sending approval notification to %s.%s: %s; trying notify.notify fallback", domain, service, exc)
            if service != "notify":
                try:
                    await self.smart_home.call_service(
                        domain="notify",
                        service="notify",
                        target_entity_ids=[],
                        service_data=payload,
                    )
                except Exception as fb_exc:
                    logger.error("Failed sending approval notification on fallback notify.notify: %s", fb_exc)

    async def dismiss_approval_notification(self, approval_id: str) -> None:
        domain, service = await self._resolve_service_name()
        payload = {
            "message": "clear_notification",
            "data": {
                "tag": f"ha_ai_brain_{approval_id}",
            },
        }
        try:
            await self.smart_home.call_service(
                domain=domain,
                service=service,
                target_entity_ids=[],
                service_data=payload,
            )
        except Exception:
            pass

    async def send_advisory_alert(self, insight: AdvisoryInsight) -> None:
        domain, service = await self._resolve_service_name()
        payload = {
            "title": f"AI Brain Insight: {insight.title}",
            "message": f"{insight.finding_details}\nRecommendation: {insight.recommended_human_action}",
        }
        self.sent_notifications.append({"type": "advisory_insight", "insight_id": insight.insight_id, "payload": payload})
        try:
            await self.smart_home.call_service(
                domain=domain,
                service=service,
                target_entity_ids=[],
                service_data=payload,
            )
        except Exception as exc:
            logger.warning("Failed sending advisory alert to %s.%s: %s; trying notify.notify fallback", domain, service, exc)
            if service != "notify":
                try:
                    await self.smart_home.call_service(
                        domain="notify",
                        service="notify",
                        target_entity_ids=[],
                        service_data=payload,
                    )
                except Exception as fb_exc:
                    logger.error("Failed sending advisory alert on fallback notify.notify: %s", fb_exc)
