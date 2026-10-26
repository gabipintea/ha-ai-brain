"""Local (zero-token) summarisation of Home Assistant history series for LLM prompts."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from ha_ai_brain.domain.timeutil import parse_iso


def _float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def summarize_series(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Compress a history series into a handful of statistics:
    numeric series -> count/first/last/min/max/mean/std/slope per hour;
    discrete series -> number of changes and the share of observed points in each state.
    """
    if not points:
        return None
    states = [str(p.get("state", "")) for p in points]
    values = [_float(s) for s in states]
    numeric = [v for v in values if v is not None]

    if len(numeric) >= max(2, int(len(points) * 0.8)):
        mean = sum(numeric) / len(numeric)
        std = math.sqrt(sum((v - mean) ** 2 for v in numeric) / len(numeric))
        slope = None
        stamped = [(parse_iso(p.get("last_changed") or p.get("last_updated")), _float(p.get("state"))) for p in points]
        stamped = [(t, v) for t, v in stamped if t is not None and v is not None]
        if len(stamped) >= 2:
            hours = (stamped[-1][0] - stamped[0][0]).total_seconds() / 3600.0
            if hours > 0:
                slope = round((stamped[-1][1] - stamped[0][1]) / hours, 3)
        return {
            "kind": "numeric",
            "n": len(numeric),
            "first": round(numeric[0], 3),
            "last": round(numeric[-1], 3),
            "min": round(min(numeric), 3),
            "max": round(max(numeric), 3),
            "mean": round(mean, 3),
            "std": round(std, 3),
            "slope_per_hour": slope,
        }

    counts = Counter(states)
    changes = sum(1 for a, b in zip(states, states[1:]) if a != b)
    total = len(states)
    return {
        "kind": "discrete",
        "n": total,
        "changes": changes,
        "last": states[-1],
        "share": {k: round(v / total, 2) for k, v in counts.most_common(4)},
    }


def summarize_history(history: dict[str, list[dict[str, Any]]], limit: int = 120) -> dict[str, dict[str, Any]]:
    """Summaries for the most dynamic entities first (largest relative variation / most state changes)."""
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for eid, points in history.items():
        if "_real_feel_" in eid:
            continue
        summary = summarize_series(points)
        if not summary:
            continue
        if summary["kind"] == "numeric":
            span = summary["max"] - summary["min"]
            score = span / (abs(summary["mean"]) + 1.0)
        else:
            score = float(summary["changes"])
        scored.append((score, eid, summary))
    scored.sort(key=lambda t: t[0], reverse=True)
    return {eid: summary for _, eid, summary in scored[:limit]}
