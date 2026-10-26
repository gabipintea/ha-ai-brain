"""User-defined minimum change per sensor: smaller moves never count as a significant live event."""

from __future__ import annotations

import fnmatch
import uuid

from pydantic import BaseModel, Field


class MinChangeRule(BaseModel):
    """
    Opt-in rule for one entity or a wildcard group (for example `sensor.mains_voltage` or `sensor.*_voltage`).
    There is deliberately no default and no automatic rule: only what the user sets here is applied.
    """

    rule_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    pattern: str
    min_change: float = Field(gt=0)
    reason: str = ""

    def matches(self, entity_id: str) -> bool:
        pat, eid = self.pattern.strip().lower(), entity_id.strip().lower()
        if not pat:
            return False
        if "*" in pat or "?" in pat:
            return fnmatch.fnmatch(eid, pat)
        return eid == pat


def find_rule(rules: list[MinChangeRule], entity_id: str) -> MinChangeRule | None:
    """The matching rule with the largest threshold wins (most conservative)."""
    hits = [r for r in rules if r.matches(entity_id)]
    return max(hits, key=lambda r: r.min_change) if hits else None


def is_below_min_change(rule: MinChangeRule, reference: float, value: float) -> bool:
    return abs(value - reference) < rule.min_change
