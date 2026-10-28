"""Health review of automations the brain deployed: do they fire, and do people fight them?"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ha_ai_brain.domain.automation_rules import RuleAction
from ha_ai_brain.domain.backtest import Timeline
from ha_ai_brain.domain.models import EntityState
from ha_ai_brain.domain.patterns import AUTOMATED_ORIGINS

OVERRIDE_WINDOW = timedelta(minutes=15)


@dataclass
class AutomationReview:
    automation_id: str
    alias: str
    verdict: str  # healthy | never_fired | overridden | disabled | missing | too_new
    fires: int
    overrides: int
    days_deployed: float
    details: str
    entity_id: str = ""

    @property
    def needs_attention(self) -> bool:
        return self.verdict in ("never_fired", "overridden", "disabled", "missing")


def count_overrides(fires: list[datetime], actions: list[RuleAction], tl: Timeline) -> int:
    overrides = 0
    for fire in fires:
        for act in actions:
            desired = act.result_state
            if not desired:
                continue
            reverted = [
                t
                for t in tl.between(act.entity_id, fire + timedelta(seconds=5), fire + OVERRIDE_WINDOW)
                if t.new_state != desired and t.origin not in AUTOMATED_ORIGINS
            ]
            if reverted:
                overrides += 1
                break
    return overrides


def review_deployed_automation(
    *,
    automation_id: str,
    alias: str,
    deployed_at: datetime,
    now: datetime,
    state: EntityState | None,
    fires: list[datetime],
    actions: list[RuleAction],
    tl: Timeline,
    expected_fires_per_week: float | None = None,
) -> AutomationReview:
    days = max(0.0, (now - deployed_at).total_seconds() / 86400.0)
    fires_since = [f for f in fires if f >= deployed_at]
    overrides = count_overrides(fires_since, actions, tl)
    base = dict(automation_id=automation_id, alias=alias, fires=len(fires_since), overrides=overrides, days_deployed=round(days, 1))
    entity_id = state.entity_id if state else ""

    if days < 1:
        return AutomationReview(verdict="too_new", details="Deployed less than a day ago.", entity_id=entity_id, **base)
    if days < 3 and not fires_since and state is not None and state.state != "off":
        return AutomationReview(
            verdict="too_new",
            details=f"Deployed {days:.0f} day(s) ago and has not run yet - too early to judge.",
            entity_id=entity_id,
            **base,
        )
    if state is None:
        return AutomationReview(
            verdict="missing",
            details="Not found in Home Assistant any more (deleted or never created). Treat the proposal as no longer deployed.",
            **base,
        )
    if state.state == "off":
        return AutomationReview(verdict="disabled", details="The automation is switched off in Home Assistant.", entity_id=entity_id, **base)
    expected = 1.0 if expected_fires_per_week is None else expected_fires_per_week
    if days >= 7 and not fires_since and expected >= 1.0:
        return AutomationReview(
            verdict="never_fired",
            details=f"No runs in {days:.0f} days although history suggested about {expected:.0f} per week - its trigger may not match.",
            entity_id=entity_id,
            **base,
        )
    if len(fires_since) >= 4 and overrides / len(fires_since) >= 0.5:
        return AutomationReview(
            verdict="overridden",
            details=f"You reverted {overrides} of its {len(fires_since)} runs within 15 minutes - it does not match your habits.",
            entity_id=entity_id,
            **base,
        )
    return AutomationReview(
        verdict="healthy",
        details=f"{len(fires_since)} {'run' if len(fires_since) == 1 else 'runs'} in {days:.0f} {'day' if round(days) == 1 else 'days'}, {overrides} overridden.",
        entity_id=entity_id,
        **base,
    )
