"""Closed-loop verification: did an executed action have the physical effect the agent predicted?"""

from __future__ import annotations

import re
from typing import Any

_DOWN = ("decrease", "lower", "reduce", "drop", "fall", "below", "under", "less")
_UP = ("increase", "raise", "rise", "above", "over", "greater", "more", "higher")
_NUM = r"(-?\d+(?:\.\d+)?)"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_outcome(expected: str, baseline: Any, current: float | None) -> tuple[str, str]:
    """Return (`success` | `failure` | `unknown`, explanation) for a free-text expectation."""
    if current is None:
        return "unknown", "monitored entity has no numeric value"
    text = re.sub(r"[_\-]+", " ", (expected or "").lower())
    base = _to_float(baseline)

    m = re.search(rf"(?:below|under|less than|<)\s*{_NUM}", text)
    if m:
        limit = float(m.group(1))
        ok = current < limit
        return ("success" if ok else "failure"), f"value {current:g} vs required below {limit:g}"
    m = re.search(rf"(?:above|over|greater than|more than|>)\s*{_NUM}", text)
    if m:
        limit = float(m.group(1))
        ok = current > limit
        return ("success" if ok else "failure"), f"value {current:g} vs required above {limit:g}"
    m = re.search(rf"(?:reach|to|at|target)\s*{_NUM}", text)
    if m:
        target = float(m.group(1))
        tol = max(0.5, abs(target) * 0.03)
        ok = abs(current - target) <= tol
        return ("success" if ok else "failure"), f"value {current:g} vs target {target:g} (+-{tol:g})"

    goes_down = any(w in text for w in _DOWN)
    goes_up = any(w in text for w in _UP)
    if base is None or goes_down == goes_up:
        return "unknown", "expectation could not be evaluated numerically"
    m = re.search(rf"by at least\s*{_NUM}", text)
    needed = float(m.group(1)) if m else 0.0
    delta = current - base
    ok = (-delta >= needed and delta < 0) if goes_down else (delta >= needed and delta > 0)
    return ("success" if ok else "failure"), f"changed by {delta:+g} from baseline {base:g} (needed {'-' if goes_down else '+'}{needed:g})"
