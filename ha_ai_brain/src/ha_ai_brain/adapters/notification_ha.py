"""Home Assistant Actionable Notification Adapter (Companion App Push + In-Memory History)."""

from __future__ import annotations

import logging
import re
from typing import Any

from ha_ai_brain.domain.models import ActionIntent, AdvisoryInsight, PendingApproval
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

    @staticmethod
    def _compact_title(raw_title: str, prefix: str = "🧠 AI Brain", max_chars: int = 44) -> str:
        """
        Format a concise title for mobile push notification cards/lockscreens.
        Strips common redundant prefixes (e.g. 'AI Brain Insight:', 'AI Brain:')
        and truncates cleanly at word boundaries with an ellipsis if needed.
        """
        t = (raw_title or "").strip()
        for drop in (
            "AI Brain Insight:",
            "AI Brain Approval:",
            "AI Brain:",
            "Insight:",
            "Advisory:",
            "Warning:",
            "Alert:",
        ):
            if t.lower().startswith(drop.lower()):
                t = t[len(drop):].strip()

        if not t:
            return f"{prefix} Notice"
        full = f"{prefix} · {t}"
        if len(full) <= max_chars:
            return full
        truncated = full[:max_chars].rsplit(" ", 1)[0].rstrip(" ,.-;:")
        return f"{truncated}…"

    @staticmethod
    def _compact_insight_message(insight: AdvisoryInsight, max_chars: int = 180) -> str:
        """
        Format a concise, actionable message for mobile notification cards.
        Leads with the recommended action so it is immediately legible on phone lockscreens,
        followed by key telemetry context. The full analysis remains preserved in the Web UI.
        """
        rec = (insight.recommended_human_action or "").strip()
        for drop in ("Recommendation:", "Action:", "Recommended:"):
            if rec.lower().startswith(drop.lower()):
                rec = rec[len(drop):].strip()

        details = (insight.finding_details or "").strip().replace("\n", " ")
        # Extract first sentence for context
        sentences = re.split(r"(?<=[.!?])\s+", details)
        first_sentence = sentences[0].strip() if sentences else ""

        if rec and first_sentence:
            if len(rec) >= 110:
                msg = f"👉 {rec}"
            else:
                msg = f"👉 {rec}\n{first_sentence}"
        elif rec:
            msg = f"👉 {rec}"
        else:
            msg = first_sentence or details

        if len(msg) > max_chars:
            msg = msg[:max_chars].rsplit(" ", 1)[0].rstrip(" ,.-;:") + "…"
        return msg

    @staticmethod
    def _compact_approval_message(intent: ActionIntent, max_chars: int = 180) -> str:
        """
        Format a compact approval message for mobile cards:
        Action target on line 1, first sentence of rationale on line 2.
        Full rationale and raw service parameters remain visible in Web UI.
        """
        targets = ", ".join(intent.target_entity_ids) if intent.target_entity_ids else "system"
        header = f"{intent.domain}.{intent.service} → {targets}"

        why = (intent.rationale or "").strip().replace("\n", " ")
        sentences = re.split(r"(?<=[.!?])\s+", why)
        short_why = sentences[0].strip() if sentences else why

        msg = f"{header}\n{short_why}"
        if len(msg) > max_chars:
            msg = msg[:max_chars].rsplit(" ", 1)[0].rstrip(" ,.-;:") + "…"
        return msg

    async def send_approval_request(self, pending: PendingApproval) -> None:
        domain, service = await self._resolve_service_name()
        intent = pending.intent
        aid = pending.approval_id

        title = "🧠 AI Brain · Approval Needed"
        message = self._compact_approval_message(intent)
        subtitle = f"{intent.domain}.{intent.service}"

        payload = {
            "title": title,
            "message": message,
            "data": {
                "tag": f"ha_ai_brain_{aid}",
                "group": "ha_ai_brain_approvals",
                "subtitle": subtitle,
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
        title = self._compact_title(insight.title, prefix="🧠 AI Brain")
        message = self._compact_insight_message(insight)
        category_title = (insight.category or "Advisory").replace("_", " ").title()

        payload = {
            "title": title,
            "message": message,
            "data": {
                "tag": f"ha_ai_brain_insight_{insight.insight_id}",
                "group": "ha_ai_brain_insights",
                "subtitle": category_title,
                "url": "/ha_ai_brain",
                "clickAction": "/ha_ai_brain",
            },
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
