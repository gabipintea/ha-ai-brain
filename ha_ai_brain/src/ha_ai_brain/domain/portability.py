"""Export / import of everything the homeowner decided or wrote (never recorded history, secrets or run logs)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ValidationError

from ha_ai_brain.domain.min_change import MinChangeRule
from ha_ai_brain.domain.models import AdvisoryInsight, ApprovalRule, FeedbackEpisode, FeedbackPolarity, IgnoredTarget, UserContextNote
from ha_ai_brain.domain.research import KnowledgeItem, ResearchTopic
from ha_ai_brain.domain.watches import WatchRule

FORMAT = "ha_ai_brain_export"
VERSION = 1
MAX_BYTES = 5_000_000

_SECRET_HINTS = ("key", "token", "secret", "password", "credential")
# Preferences that only make sense for the machine they were set on.
_SKIP_PREFS = frozenset({"paused"})

# section name -> model used to validate each entry (preferences / muted_alerts are plain mappings)
MODELED: dict[str, type[BaseModel]] = {
    "context_notes": UserContextNote,
    "ignored_targets": IgnoredTarget,
    "min_change_rules": MinChangeRule,
    "watches": WatchRule,
    "rejected_suggestions": FeedbackEpisode,
    "rejected_insights": AdvisoryInsight,
    "approval_rules": ApprovalRule,
    "deployed_automations": FeedbackEpisode,
    "knowledge_items": KnowledgeItem,
    "research_topics": ResearchTopic,
}

LABELS = {
    "preferences": "Dashboard settings",
    "context_notes": "Notes about your home",
    "ignored_targets": "Ignore list entries",
    "min_change_rules": "Minimum-change rules",
    "watches": "Watches",
    "muted_alerts": "Muted / dismissed alerts",
    "rejected_suggestions": "Rejected suggestions",
    "rejected_insights": "Rejected insights",
    "approval_rules": "Always-allow rules",
    "deployed_automations": "Tracked automations",
    "knowledge_items": "Approved / rejected research findings",
    "research_topics": "Research topics",
}


def is_secret_pref(key: str) -> bool:
    low = key.lower()
    return any(h in low for h in _SECRET_HINTS)


def exportable_prefs(prefs: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in prefs.items() if not is_secret_pref(k) and k not in _SKIP_PREFS}


def build_bundle(sections: dict[str, Any], addon_version: str, now: datetime | None = None) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": VERSION,
        "addon_version": addon_version,
        "exported_at": (now or datetime.now(timezone.utc)).isoformat(),
        "sections": sections,
    }


@dataclass
class ParsedBundle:
    sections: dict[str, list[Any]] = field(default_factory=dict)  # validated model instances / plain items
    skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.sections.items() if v}


def parse_bundle(data: Any) -> ParsedBundle:
    """Validate an uploaded file. Raises ValueError when it is not one of our exports; bad entries are skipped and counted."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("This is not a HA AI Brain export file.")
    version = data.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise ValueError("This export was made by a newer version of the add-on. Update the add-on first.")
    raw_sections = data.get("sections")
    if not isinstance(raw_sections, dict):
        raise ValueError("The export file has no sections.")
    out = ParsedBundle()

    def skip(name: str) -> None:
        out.skipped[name] = out.skipped.get(name, 0) + 1

    prefs = raw_sections.get("preferences")
    if isinstance(prefs, dict):
        kept = [(str(k), str(v)) for k, v in prefs.items() if not is_secret_pref(str(k)) and str(k) not in _SKIP_PREFS and len(str(v)) <= 4000]
        out.sections["preferences"] = kept
        if len(kept) != len(prefs):
            out.skipped["preferences"] = len(prefs) - len(kept)

    muted = raw_sections.get("muted_alerts")
    if isinstance(muted, dict):
        items = []
        for key, fb in muted.items():
            if isinstance(fb, dict) and isinstance(key, str) and 0 < len(key) <= 300:
                items.append((key, {"dismissed": max(0, int(fb.get("dismissed", 0) or 0)), "muted": bool(fb.get("muted", False))}))
            else:
                skip("muted_alerts")
        out.sections["muted_alerts"] = items

    for name, model in MODELED.items():
        entries = raw_sections.get(name)
        if not isinstance(entries, list):
            continue
        valid: list[Any] = []
        for entry in entries[:5000]:
            try:
                valid.append(model.model_validate(entry))
            except (ValidationError, ValueError, TypeError):
                skip(name)
        if name == "rejected_suggestions":
            valid = [e for e in valid if e.polarity == FeedbackPolarity.REJECTED_EXPLICIT] or []
        elif name == "deployed_automations":
            kept = [
                e for e in valid
                if e.polarity in (FeedbackPolarity.ENDORSED_ONCE, FeedbackPolarity.ENDORSED_REPEATABLE)
                and e.service_called == "automation.upsert_native_automation"
                and re.fullmatch(r"[A-Za-z0-9_\-]{1,100}", str((e.service_data or {}).get("automation_id") or ""))
            ]
            out.skipped[name] = out.skipped.get(name, 0) + len(valid) - len(kept)
            valid = kept
        elif name == "rejected_insights":
            for ins in valid:
                ins.status = "rejected"
        elif name == "knowledge_items":
            valid = [i for i in valid if i.status in ("approved", "rejected")]
        out.sections[name] = valid

    if not any(out.sections.values()):
        out.warnings.append("The file contains nothing that can be imported.")
    if out.sections.get("approval_rules"):
        out.warnings.append("This file contains always-allow rules: matching actions will run without asking you again.")
    return out
