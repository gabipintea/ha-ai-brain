"""LLM-Driven Domain & Scientific Research Adapter (Zero Hardcoded Signals or Rules)."""

from __future__ import annotations

import json
from typing import Any

from ha_ai_brain.domain.models import ResearchFinding
from ha_ai_brain.ports.llm import LLMProviderPort
from ha_ai_brain.ports.research import ResearchPort


class ScientificResearchAdapter(ResearchPort):
    """
    Delegates scientific, physical, thermodynamic, and domain discovery directly to the LLM
    acting as a domain subject-matter expert over the observed Home Assistant entity schema.
    No metrics or formulas are hardcoded in code.
    """

    def __init__(self, llm: LLMProviderPort | None = None) -> None:
        self.llm = llm

    def bind_llm(self, llm: LLMProviderPort) -> None:
        self.llm = llm

    async def research_topic(
        self,
        query: str,
        site_context: str = "",
        telemetry_context: dict[str, Any] | None = None,
    ) -> list[ResearchFinding]:
        if self.llm is None:
            return []

        resp = await self.llm.generate_json(
            system_prompt=(
                "You are an autonomous Scientific & Domain Research Sub-Agent for a Smart Home AI Brain.\n"
                "Examine the provided Home Assistant sensor entity keys, current values, units, device classes, "
                "areas, and historical summary from an expert domain perspective.\n"
                "Without relying on pre-programmed rules, determine:\n"
                "1) What physical, environmental, thermodynamic, or behavioral phenomena and interactions "
                "could be analyzed across these specific entities.\n"
                "2) What derived signals, equations, or statistical metrics (if any) would be valuable to compute "
                "from these raw entity values and history to assess risks, comfort, efficiency, or automation opportunities.\n"
                "Return JSON with key `findings`, where each item is an object with:\n"
                "- `topic`: string\n"
                "- `principle_summary`: string (including any physical or statistical formulas to compute)\n"
                "- `recommended_thresholds_or_physics`: string\n"
                "- `actionable_implications`: list of strings\n"
                "- `sources`: list of strings"
            ),
            user_prompt=json.dumps(
                {
                    "research_objective": query,
                    "site_context": site_context,
                    "observed_telemetry": telemetry_context or {},
                }
            ),
            use_fast_tier=False,
            context_hint={
                "task": "expert_scientific_research",
                "query": query,
                "site_context": site_context,
                "telemetry_context": telemetry_context or {},
            },
        )

        findings: list[ResearchFinding] = []
        raw_findings = resp.get("findings") or resp.get("result") or []
        if isinstance(raw_findings, dict):
            raw_findings = [raw_findings]
        for item in raw_findings if isinstance(raw_findings, list) else []:
            if isinstance(item, dict) and ("topic" in item or "title" in item):
                raw_impl = item.get("actionable_implications", [])
                raw_src = item.get("sources", [])
                findings.append(
                    ResearchFinding(
                        topic=str(item.get("topic") or item.get("title") or "Domain Finding"),
                        principle_summary=str(item.get("principle_summary") or item.get("summary") or ""),
                        recommended_thresholds_or_physics=str(item.get("recommended_thresholds_or_physics") or item.get("thresholds") or ""),
                        actionable_implications=[str(x) for x in raw_impl] if isinstance(raw_impl, list) else [str(raw_impl)],
                        sources=[str(x) for x in raw_src] if isinstance(raw_src, list) else [str(raw_src)],
                    )
                )
        return findings
