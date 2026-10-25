"""Backward-compatibility shim for climate_agent (re-exported from specialized_agent)."""

from __future__ import annotations

from ha_ai_brain.application.graphs.specialized_agent import (
    AgentGraphState,
    ClimateAgentGraph,
    ClimateGraphState,
    SpecializedAgentGraph,
)

__all__ = [
    "AgentGraphState",
    "ClimateAgentGraph",
    "ClimateGraphState",
    "SpecializedAgentGraph",
]
