"""Sub-Agent Delegation Workflows: Research Sub-Agent and Computation Sub-Agent."""

from __future__ import annotations

import json
from typing import Any

from ha_ai_brain.domain.models import DerivedSignal, EntityState, ResearchFinding
from ha_ai_brain.ports.llm import LLMProviderPort
from ha_ai_brain.ports.research import ResearchPort
from ha_ai_brain.ports.sandbox import ComputationSandboxPort

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
    ) -> list[ResearchFinding]:
        """
        Inspect the raw Home Assistant entity schema and values and let the expert LLM
        discover what scientific/domain principles and derived metrics apply in a single call.
        """
        entity_summary = {
            eid: {
                "state": st.state,
                "unit": st.unit_of_measurement,
                "device_class": st.device_class,
                "domain": st.domain,
                "area_id": st.area_id,
                "attrs": compact_attrs(st.attributes),
            }
            for eid, st in observed_states.items()
            if st.domain != "automation" and "_real_feel_" not in eid
        }

        findings = await self.research_port.research_topic(
            query=f"Expert domain analysis and derived signal discovery for {agent_specialty} (mode={mode})",
            site_context=site_context,
            telemetry_context={
                "agent_specialty": agent_specialty,
                "mode": mode,
                "entities": entity_summary,
            },
        )
        return findings


class ComputationSubAgent:
    """
    Autonomous Sub-Agent that translates the LLM's own domain hypotheses and raw Home Assistant
    entity states / history into executable Python code inside the ComputationSandboxPort,
    returning factual DerivedSignals.
    """

    def __init__(self, llm: LLMProviderPort, sandbox: ComputationSandboxPort) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self._cached_code: dict[str, str] = {}

    async def compute_derived_signals(
        self,
        observed_states: dict[str, EntityState],
        history_series: dict[str, list[dict[str, Any]]],
        research_findings: list[ResearchFinding],
        mode: str,
        user_context_notes: list[dict[str, Any]] | None = None,
        cache_key: str = "default",
    ) -> list[DerivedSignal]:
        """
        Let the LLM decide what derived signals (if any) are useful to compute from the
        available entity keys, states, and historical trajectories, write Python 3 code
        using `math` and `statistics`, and execute it inside the isolated subprocess sandbox.
        In realtime_stream mode, reuses cached Python code to execute without LLM calls.
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

        # In realtime_stream mode: reuse cached Python calculation script if available (0 LLM tokens!)
        if mode == "realtime_stream" and cache_key in self._cached_code:
            cached_code = self._cached_code[cache_key]
            if cached_code:
                try:
                    exec_output = await self.sandbox.execute_python(
                        code=cached_code,
                        input_variables=sandbox_inputs,
                        timeout_seconds=5.0,
                    )
                    signals_raw = exec_output.get("signals", [])
                    if isinstance(signals_raw, list) and signals_raw:
                        derived_signals: list[DerivedSignal] = []
                        for item in signals_raw:
                            if isinstance(item, dict) and "signal_name" in item:
                                derived_signals.append(
                                    DerivedSignal(
                                        signal_name=str(item["signal_name"]),
                                        value=item.get("value", 0.0),
                                        unit=str(item.get("unit", "")),
                                        formula_or_method=str(item.get("formula_or_method", "cached_sandbox_execution")),
                                        source_entities=list(item.get("source_entities", [])),
                                        interpretation=str(item.get("interpretation", "")),
                                        python_code_executed=cached_code,
                                    )
                                )
                        if derived_signals:
                            return derived_signals
                except Exception:
                    pass

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
                "If no derived calculation is needed, set `python_code` to an empty string. "
                "Return JSON with key `python_code`."
            ),
            user_prompt=json.dumps(
                {
                    "research_findings": [f.model_dump() for f in research_findings],
                    "user_context_notes": user_context_notes or [],
                    "available_numeric_states": numeric_states,
                    "history_sample": {
                        eid: series[-4:]
                        for eid, series in list(history_series.items())[:15]
                        if "_real_feel_" not in eid
                    },
                    "mode": mode,
                }
            ),
            use_fast_tier=True,
            context_hint={
                "task": "generate_computation_code",
                "numeric_states": numeric_states,
                "states": raw_states,
                "history": history_series,
                "research_findings": [f.model_dump() for f in research_findings],
                "mode": mode,
            },
        )

        python_code = str(code_plan.get("python_code", "")).strip()
        if python_code:
            self._cached_code[cache_key] = python_code
        if not python_code:
            return []

        exec_output = await self.sandbox.execute_python(
            code=python_code,
            input_variables=sandbox_inputs,
            timeout_seconds=5.0,
        )

        signals_raw = exec_output.get("signals", [])
        derived_signals: list[DerivedSignal] = []
        if isinstance(signals_raw, list):
            for item in signals_raw:
                if isinstance(item, dict) and "signal_name" in item:
                    derived_signals.append(
                        DerivedSignal(
                            signal_name=str(item["signal_name"]),
                            value=item.get("value", 0.0),
                            unit=str(item.get("unit", "")),
                            formula_or_method=str(item.get("formula_or_method", "")),
                            source_entities=list(item.get("source_entities", [])),
                            interpretation=str(item.get("interpretation", "")),
                            python_code_executed=python_code,
                        )
                    )
        return derived_signals
