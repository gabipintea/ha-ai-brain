"""Port Interface for the Research Sub-Agent (Scientific, Building Physics, and Web Research)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ha_ai_brain.domain.models import ResearchFinding


class ResearchPort(ABC):
    """Retrieves factual building-science, physical, comfort, or domain knowledge."""

    @abstractmethod
    async def research_topic(
        self,
        query: str,
        site_context: str = "",
        telemetry_context: dict[str, Any] | None = None,
    ) -> list[ResearchFinding]:
        """Discover relevant scientific principles & formulas for the observed entity states."""
