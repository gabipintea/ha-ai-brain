"""Compact serialisation of prompt payloads: the same information in fewer tokens, whatever the AI provider."""

from __future__ import annotations

import json
from typing import Any


def prune(obj: Any) -> Any:
    """Recursively drop empty values (None, '', [], {}) and round floats; zero and False are meaningful and kept."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            pv = prune(v)
            if pv is None or pv == "" or pv == [] or pv == {}:
                continue
            out[k] = pv
        return out
    if isinstance(obj, (list, tuple)):
        return [pv for pv in (prune(v) for v in obj) if not (pv is None or pv == "" or pv == [] or pv == {})]
    if isinstance(obj, float):
        return round(obj, 3)
    return obj


def dumps(obj: Any) -> str:
    """Compact JSON for prompts (no spaces, no empty fields, rounded numbers)."""
    return json.dumps(prune(obj), separators=(",", ":"), ensure_ascii=False, default=str)
