"""Sub-Agent Delegation Workflows: Research Sub-Agent and Computation Sub-Agent."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from ha_ai_brain.domain.models import DerivedSignal, EntityState, ResearchFinding
from ha_ai_brain.domain.promptfmt import dumps
from ha_ai_brain.ports.llm import REASONING_LOW, LLMProviderPort
from ha_ai_brain.ports.memory import MemoryStorePort
from ha_ai_brain.ports.research import ResearchPort
from ha_ai_brain.ports.sandbox import ComputationSandboxPort

logger = logging.getLogger(__name__)

# Upper bound for entities serialized into a single LLM prompt (protects token budget on large installations).
MAX_PROMPT_ENTITIES = 250
CODE_CACHE_DAYS = 7

COMPACT_ATTR_KEYS = (
    "friendly_name",
    "temperature",
    "current_temperature",
    "target_temp_high",
    "target_temp_low",
    "humidity",
    "target_humidity",
    "current_position",
    "percentage",
    "hvac_action",
    "preset_mode",
)


def compact_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    return {k: attrs[k] for k in COMPACT_ATTR_KEYS if k in attrs}


def research_digest(findings: list[ResearchFinding]) -> list[dict[str, Any]]:
    """Findings without their (unverifiable) source lists - the model needs the substance, not the bibliography."""
    return [
        {
            "topic": f.topic,
            "principle": f.principle_summary,
            "thresholds": f.recommended_thresholds_or_physics,
            "implications": f.actionable_implications,
        }
        for f in findings
    ]


def _build_derived_signals(signals_raw: Any, code: str, default_method: str) -> list[DerivedSignal]:
    """Convert raw sandbox output items into validated DerivedSignal objects, skipping malformed entries."""
    derived: list[DerivedSignal] = []
    if not isinstance(signals_raw, list):
        return derived
    for item in signals_raw:
        if not isinstance(item, dict) or "signal_name" not in item:
            continue
        sources = item.get("source_entities", [])
        if isinstance(sources, str):
            sources = [sources]
        try:
            derived.append(
                DerivedSignal(
                    signal_name=str(item["signal_name"]),
                    value=item.get("value", 0.0),
                    unit=str(item.get("unit", "")),
                    formula_or_method=str(item.get("formula_or_method", default_method)),
                    source_entities=[str(e) for e in sources] if isinstance(sources, list) else [],
                    interpretation=str(item.get("interpretation", "")),
                    python_code_executed=code,
                )
            )
        except Exception as exc:
            logger.debug("Ignoring malformed derived signal %r: %s", item.get("signal_name"), exc)
    return derived


class ResearchSubAgent:
    """
    Autonomous Sub-Agent responsible for inspecting available Home Assistant entity keys,
    values, units, and device classes from an expert perspective to discover what physical,
    environmental, or behavioral principles and derived signals are relevant.
    """

    def __init__(self, llm: LLMProviderPort, research_port: ResearchPort) -> None:
        self.llm = llm
        self.research_port = research_port

    async def investigate(
        self,
        agent_specialty: str,
        site_context: str,
        observed_states: dict[str, EntityState],
        mode: str,
        reference_knowledge: list[dict[str, Any]] | None = None,
    ) -> list[ResearchFinding]:
        """
        Inspect the raw Home Assistant entity schema and values and let the expert LLM
        discover what scientific/domain principles and derived metrics apply in a single call.
        """
        # The expert principles that apply depend on the *kinds* of devices, not on today's values: send counts per kind.
        kinds = Counter(
            (st.domain, st.device_class or "", st.unit_of_measurement or "")
            for eid, st in observed_states.items()
            if st.domain != "automation" and "_real_feel_" not in eid
        )
        entity_types = [
            {"domain": d, "class": c, "unit": u, "count": n}
            for (d, c, u), n in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))[:60]
        ]

        findings = await self.research_port.research_topic(
            query=f"Expert domain analysis and derived signal discovery for {agent_specialty} (mode={mode})",
            site_context=site_context,
            telemetry_context={
                "reference_knowledge": reference_knowledge or [],
                "agent_specialty": agent_specialty,
                "mode": mode,
                "entity_types": entity_types,
            },
        )
        return findings


class ComputationSubAgent:
    """
    Autonomous Sub-Agent that translates the LLM's own domain hypotheses and raw Home Assistant
    entity states / history into executable Python code inside the ComputationSandboxPort,
    returning factual DerivedSignals.

    The generated code is cached (in memory and, when a memory store is given, persistently) per agent/area and
    reused for up to a week in BOTH real-time and batch mode - it runs locally for free. It is regenerated when the set
    of numeric entities or the user's notes change, when it fails, or when it expires.
    """

    def __init__(self, llm: LLMProviderPort, sandbox: ComputationSandboxPort, memory: MemoryStorePort | None = None) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self.memory = memory
        # cache_key -> (signature, code, saved_at)
        self._cached_code: dict[str, tuple[str, str, datetime]] = {}

    @staticmethod
    def _signature(numeric_states: dict[str, float], notes: list[dict[str, Any]]) -> str:
        material = [sorted(numeric_states), sorted((str(n.get("scope")), str(n.get("content"))) for n in notes)]
        return hashlib.sha1(json.dumps(material).encode()).hexdigest()[:16]

    async def _load_code(self, cache_key: str, signature: str) -> str | None:
        entry = self._cached_code.get(cache_key)
        if entry is None and self.memory is not None:
            try:
                raw = await self.memory.get_kv(f"compcode:{cache_key}")
                if raw:
                    data = json.loads(raw)
                    entry = (data["sig"], data["code"], datetime.fromisoformat(data["saved_at"]))
                    self._cached_code[cache_key] = entry
            except Exception as exc:
                logger.debug("computation cache read failed: %s", exc)
        if entry and entry[0] == signature and datetime.now(timezone.utc) - entry[2] < timedelta(days=CODE_CACHE_DAYS):
            return entry[1]
        return None

    async def _store_code(self, cache_key: str, signature: str, code: str) -> None:
        now = datetime.now(timezone.utc)
        self._cached_code[cache_key] = (signature, code, now)
        if self.memory is not None:
            try:
                await self.memory.set_kv(f"compcode:{cache_key}", json.dumps({"sig": signature, "code": code, "saved_at": now.isoformat()}))
            except Exception as exc:
                logger.debug("computation cache write failed: %s", exc)

    async def compute_derived_signals(
        self,
        observed_states: dict[str, EntityState],
        history_series: dict[str, list[dict[str, Any]]],
        research_findings: list[ResearchFinding],
        mode: str,
        user_context_notes: list[dict[str, Any]] | None = None,
        cache_key: str = "default",
        history_summaries: dict[str, dict[str, Any]] | None = None,
    ) -> list[DerivedSignal]:
        """
        Let the LLM decide what derived signals (if any) are useful to compute from the available entity keys, states,
        and historical trajectories, write Python 3 code using `math` and `statistics`, and execute it inside the
        isolated subprocess sandbox. Valid cached code is executed again without any LLM call.
        """
        numeric_states: dict[str, float] = {}
        raw_states: dict[str, Any] = {}
        for eid, st in observed_states.items():
            if st.domain == "automation" or "_real_feel_" in eid:
                continue
            raw_states[eid] = {
                "state": st.state,
                "numeric": st.numeric_value,
                "unit": st.unit_of_measurement,
                "device_class": st.device_class,
                "domain": st.domain,
                "area_id": st.area_id,
                "attributes": compact_attrs(st.attributes),
            }
            if st.numeric_value is not None:
                numeric_states[eid] = st.numeric_value

        sandbox_inputs = {
            "numeric_states": numeric_states,
            "states": raw_states,
            "history": history_series,
            "mode": mode,
        }
        notes = user_context_notes or []
        signature = self._signature(numeric_states, notes)

        cached_code = await self._load_code(cache_key, signature)
        if cached_code:
            exec_output = await self.sandbox.execute_python(code=cached_code, input_variables=sandbox_inputs, timeout_seconds=5.0)
            if exec_output.get("error"):
                logger.info("Cached computation for %s failed (%s); regenerating.", cache_key, str(exec_output["error"])[:160])
                self._cached_code.pop(cache_key, None)
            else:
                return _build_derived_signals(exec_output.get("signals", []), cached_code, "cached_sandbox_execution")

        code_plan = await self.llm.generate_json(
            system_prompt=(
                "You are the Computation Sub-Agent. Inspect the available Home Assistant entities "
                "(`inputs['numeric_states']`, `inputs['states']`, `inputs['history']`) and the expert "
                "`research_findings`.\n"
                "Decide what derived signals, physical metrics, correlations, or rates-of-change "
                "(if any) are useful to compute for these specific entities.\n"
                "Write pure Python 3 code (without `import` statements—`math` and `statistics` are already "
                "pre-loaded in globals, and dunder `__` attributes are forbidden) that reads `inputs` and "
                "populates `results['signals']` as a list of dicts, where each dict has:\n"
                "- `signal_name`: string\n"
                "- `value`: float, string, or dict\n"
                "- `unit`: string\n"
                "- `formula_or_method`: string\n"
                "- `source_entities`: list of entity_id strings\n"
                "- `interpretation`: string\n"
                "`history_summary` gives per-entity statistics (min/max/mean/std/slope per hour, or state shares) for the whole "
                "lookback window; the complete time series is in `inputs['history']` (list of {state, last_changed}).\n"
                "The code is cached and re-run on future values, so it must work from `inputs` generically (look entities up by "
                "device class / unit / area where possible) and must not hard-code today's readings.\n"
                "If no derived calculation is needed, set `python_code` to an empty string. "
                "Return JSON with key `python_code`."
            ),
            user_prompt=dumps(
                {
                    "research_findings": research_digest(research_findings),
                    "user_context_notes": notes,
                    "mode": mode,
                    # Locally computed statistics over the WHOLE lookback window for every entity (the raw series
                    # is available to the code itself via inputs['history']).
                    "history_summary": dict(list((history_summaries or {}).items())[:80]),
                    "available_numeric_states": numeric_states,
                }
            ),
            use_fast_tier=True,
            context_hint={
                "task": "generate_computation_code",
                "reasoning": REASONING_LOW,
                "numeric_states": numeric_states,
                "states": raw_states,
                "history": history_series,
                "research_findings": [f.model_dump() for f in research_findings],
                "mode": mode,
            },
        )

        python_code = str(code_plan.get("python_code", "")).strip()
        if not python_code:
            return []

        exec_output = await self.sandbox.execute_python(
            code=python_code,
            input_variables=sandbox_inputs,
            timeout_seconds=5.0,
        )
        if exec_output.get("error"):
            # Never cache code that failed: it would be re-run (and fail) every time.
            logger.warning("Generated computation failed in sandbox: %s", str(exec_output["error"])[:200])
            return []

        await self._store_code(cache_key, signature, python_code)
        return _build_derived_signals(exec_output.get("signals", []), python_code, "")
