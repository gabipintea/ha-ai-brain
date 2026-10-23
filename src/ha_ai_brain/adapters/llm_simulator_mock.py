"""Offline Mock LLM Adapter used strictly for the Digital Twin Simulator when no API key is set."""

from __future__ import annotations

from typing import Any

from ha_ai_brain.adapters.quota_monitor import BaseQuotaMonitorAdapter
from ha_ai_brain.ports.billing import LicensePort
from ha_ai_brain.ports.llm import LLMProviderPort, LLMQuotaAndUsageSnapshot


MOCK_SANDBOX_SCRIPT = '''
numeric = inputs.get("numeric_states", {})
states = inputs.get("states", {})
history = inputs.get("history", {})
mode = inputs.get("mode", "realtime_stream")
signals = []

t_out = None
t_out_eid = None
for eid, info in states.items():
    area = str(info.get("area_id") or "")
    dc = info.get("device_class")
    val = info.get("numeric")
    if val is not None and dc == "temperature" and (
        area in ("outdoor", "outside", "exterior")
        or any(k in eid for k in ("outdoor", "outside", "exterior", "external"))
    ):
        t_out = float(val)
        t_out_eid = eid
        break

areas = {}
for eid, info in states.items():
    area = info.get("area_id") or "default"
    if area in ("outdoor", "outside", "exterior") or eid == t_out_eid:
        continue
    dc = info.get("device_class")
    val = info.get("numeric")
    if val is not None and dc in ("temperature", "humidity", "illuminance"):
        areas.setdefault(area, {})[dc] = (eid, float(val))

for area, metrics in areas.items():
    if "temperature" in metrics and "humidity" in metrics:
        t_eid, t_in = metrics["temperature"]
        rh_eid, rh_in = metrics["humidity"]
        rh_clamped = max(1.0, min(100.0, rh_in))
        a = 17.625
        b = 243.04
        gamma = (a * t_in) / (b + t_in) + math.log(rh_clamped / 100.0)
        dew_point = round((b * gamma) / (a - gamma), 2)
        signals.append({
            "signal_name": f"{area}_dew_point_temperature",
            "value": dew_point,
            "unit": "°C",
            "formula_or_method": "Magnus-Tetens psychrometric equation",
            "source_entities": [t_eid, rh_eid],
            "interpretation": f"Indoor vapor condenses on surfaces in {area} at or below {dew_point}°C."
        })
        if t_out is not None and t_out_eid is not None:
            t_glass = round(t_in - 0.32 * (t_in - float(t_out)), 2)
            margin = round(t_glass - dew_point, 2)
            risk = "CRITICAL_CONDENSATION_RISK" if margin <= 0.5 else ("HIGH_CONDENSATION_RISK" if margin <= 1.8 else "SAFE")
            signals.append({
                "signal_name": f"{area}_window_condensation_margin",
                "value": margin,
                "unit": "°C",
                "formula_or_method": "T_glass - T_dp",
                "source_entities": [t_eid, rh_eid, t_out_eid],
                "interpretation": f"{risk}: Glass {t_glass}°C vs Dew Point {dew_point}°C (margin {margin:+.2f}°C)."
            })

    if "illuminance" in metrics and "temperature" in metrics:
        lux_eid, lux_val = metrics["illuminance"]
        t_eid, t_in = metrics["temperature"]
        solar_kw_m2 = round(lux_val / 120000.0, 3)
        status = "HIGH_SOLAR_HEAT_GAIN" if lux_val >= 25000 else "LOW_SOLAR_GAIN"
        signals.append({
            "signal_name": f"{area}_solar_heat_gain_index",
            "value": solar_kw_m2,
            "unit": "kW/m² eq",
            "formula_or_method": "E_lux / 120,000",
            "source_entities": [lux_eid, t_eid],
            "interpretation": f"{status}: Facade illuminance is {lux_val:.0f} lx."
        })

for eid, series in history.items():
    st_info = states.get(eid, {})
    if st_info.get("device_class") == "temperature" and eid != t_out_eid and len(series) >= 3:
        vals = []
        for pt in series:
            try:
                vals.append(float(pt.get("state")))
            except Exception:
                pass
        if len(vals) >= 3:
            slope_per_hour = round((vals[-1] - vals[0]) / max(1, len(vals) - 1), 2)
            if slope_per_hour <= -0.5 or mode == "periodic_batch":
                health = "POOR_INSULATION_RAPID_HEAT_LOSS" if slope_per_hour <= -0.6 else "NORMAL_THERMAL_RETENTION"
                src = [eid] + ([t_out_eid] if t_out_eid else [])
                signals.append({
                    "signal_name": f"{eid.replace('sensor.', '')}_thermal_decay_rate",
                    "value": slope_per_hour,
                    "unit": "°C/hr",
                    "formula_or_method": "Linear finite difference dT/dt",
                    "source_entities": src,
                    "interpretation": f"{health}: Slope is {slope_per_hour:+.2f}°C/hr."
                })

results["signals"] = signals
'''


class SimulatorMockLLMAdapter(LLMProviderPort):
    """
    Used ONLY when `use_simulator=True` and no LLM API key is configured,
    allowing offline unit tests and simulator demos to run without network access.
    """

    def __init__(self, license_port: LicensePort | None = None) -> None:
        self.license_port = license_port
        self.quota_monitor = BaseQuotaMonitorAdapter(provider="simulator_mock", default_model="simulator-mock")

    async def get_quota_status(self) -> LLMQuotaAndUsageSnapshot:
        return await self.quota_monitor.get_quota_and_usage_snapshot()

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        use_fast_tier: bool = False,
        context_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.quota_monitor.record_success(model="simulator-mock", prompt_tokens=200, completion_tokens=150)
        if self.license_port:
            await self.license_port.record_token_usage(
                agent_id=str((context_hint or {}).get("agent_id", "climate_thermal_agent")),
                prompt_tokens=200,
                completion_tokens=150,
            )

        hint = context_hint or {}
        task = hint.get("task", "")

        if task == "formulate_research_query":
            return {"research_query": "Expert domain hypothesis generation over observed simulator entities"}

        if task == "expert_scientific_research":
            return {
                "findings": [
                    {
                        "topic": "Psychrometric & Thermodynamic Hypothesis (Simulator Mock)",
                        "principle_summary": "Evaluate vapor pressure dew-point margins, solar irradiance heat gain, and envelope cooling rates.",
                        "recommended_thresholds_or_physics": "Compute T_dp, T_glass margin, solar irradiance, and dT/dt.",
                        "actionable_implications": ["Mitigate moisture and thermal overshoot using available room actuators."],
                        "sources": ["ASHRAE Fundamentals"],
                    }
                ]
            }

        if task == "generate_computation_code":
            return {"python_code": MOCK_SANDBOX_SCRIPT}

        if task == "synthesize_realtime_reactions":
            return self._mock_realtime(hint)

        if task == "synthesize_batch_analysis":
            return self._mock_batch(hint)

        return {}

    def _mock_realtime(self, hint: dict[str, Any]) -> dict[str, Any]:
        signals = hint.get("derived_signals", [])
        actuators = hint.get("actuators", {})
        area_id = hint.get("area_id")
        actions: list[dict[str, Any]] = []

        for sig in signals:
            name = str(sig.get("signal_name", ""))
            interp = str(sig.get("interpretation", ""))
            val = sig.get("value")
            sources = list(sig.get("source_entities", []))

            if "window_condensation_margin" in name and ("HIGH_CONDENSATION_RISK" in interp or "CRITICAL_CONDENSATION_RISK" in interp):
                sig_area = name.replace("_window_condensation_margin", "")
                target_area = area_id or sig_area
                rh_entity = sources[1] if len(sources) > 1 else ""
                dehum_ids = [eid for eid, a in actuators.items() if a["domain"] == "humidifier" and a.get("area_id") == target_area]
                fan_ids = [eid for eid, a in actuators.items() if a["domain"] == "fan" and a.get("area_id") == target_area]
                window_ids = [eid for eid, a in actuators.items() if a["domain"] == "cover" and "window" in eid and a.get("area_id") == target_area]

                if dehum_ids:
                    act: dict[str, Any] = {
                        "domain": "humidifier",
                        "service": "turn_on",
                        "target_entity_ids": dehum_ids,
                        "service_data": {"humidity": 48},
                        "cause_category": "window_condensation_prevention",
                        "rationale": f"{interp} Starting dehumidifier.",
                        "derived_signals_used": [name],
                        "priority": "EQUIPMENT_AND_STRUCTURAL_PROTECTION",
                        "risk_level": "low",
                    }
                    if rh_entity:
                        act["expected_outcome"] = {
                            "monitored_entity_id": rh_entity,
                            "baseline_value": val,
                            "expected_direction_or_target": "decrease_humidity_below_55_percent",
                            "check_after_minutes": 30,
                        }
                    actions.append(act)
                if fan_ids:
                    actions.append(
                        {
                            "domain": "fan",
                            "service": "set_percentage",
                            "target_entity_ids": fan_ids,
                            "service_data": {"percentage": 80},
                            "cause_category": "window_condensation_prevention",
                            "rationale": f"{interp} Boosting HRV ventilation.",
                            "derived_signals_used": [name],
                            "priority": "EQUIPMENT_AND_STRUCTURAL_PROTECTION",
                            "risk_level": "low",
                        }
                    )
                if window_ids:
                    actions.append(
                        {
                            "domain": "cover",
                            "service": "set_cover_position",
                            "target_entity_ids": window_ids,
                            "service_data": {"position": 15},
                            "cause_category": "window_condensation_prevention",
                            "rationale": f"{interp} Cracking motorized window.",
                            "derived_signals_used": [name],
                            "priority": "EQUIPMENT_AND_STRUCTURAL_PROTECTION",
                            "risk_level": "medium",
                        }
                    )

            if "solar_heat_gain_index" in name and "HIGH_SOLAR_HEAT_GAIN" in interp:
                sig_area = name.replace("_solar_heat_gain_index", "")
                target_area = area_id or sig_area
                ufh_ids = [eid for eid, a in actuators.items() if a["domain"] == "climate" and a.get("area_id") == target_area]
                blind_ids = [eid for eid, a in actuators.items() if a["domain"] == "cover" and "blind" in eid and a.get("area_id") == target_area]
                if ufh_ids:
                    actions.append(
                        {
                            "domain": "climate",
                            "service": "set_temperature",
                            "target_entity_ids": ufh_ids,
                            "service_data": {"temperature": 20.5},
                            "cause_category": "solar_gain_ufh_inertia_compensation",
                            "rationale": f"{interp} Trimming UFH setpoint.",
                            "derived_signals_used": [name],
                            "priority": "COMFORT_ENHANCEMENT",
                            "risk_level": "medium",
                        }
                    )
                if blind_ids:
                    actions.append(
                        {
                            "domain": "cover",
                            "service": "set_cover_position",
                            "target_entity_ids": blind_ids,
                            "service_data": {"position": 45},
                            "cause_category": "solar_gain_ufh_inertia_compensation",
                            "rationale": f"{interp} Lowering south blinds to 45%.",
                            "derived_signals_used": [name],
                            "priority": "COMFORT_ENHANCEMENT",
                            "risk_level": "low",
                        }
                    )

        return {"actions": actions}

    def _mock_batch(self, hint: dict[str, Any]) -> dict[str, Any]:
        signals = hint.get("derived_signals", [])
        corroborated = hint.get("corroborated", {})
        existing_automations = hint.get("existing_automations", {})
        insights: list[dict[str, Any]] = []
        automations: list[dict[str, Any]] = []

        # Collect target entities already controlled by existing native HA automations
        already_automated_targets: set[str] = set()
        for auto_info in existing_automations.values():
            attrs = auto_info.get("attributes") or {}
            for t in attrs.get("target_entities", []):
                already_automated_targets.add(str(t))

        for sig in signals:
            name = str(sig.get("signal_name", ""))
            interp = str(sig.get("interpretation", ""))
            val = sig.get("value")
            sources = list(sig.get("source_entities", []))

            if "thermal_decay_rate" in name and "POOR_INSULATION_RAPID_HEAT_LOSS" in interp:
                zone = name.replace("_temperature_thermal_decay_rate", "").replace("_", " ").title()
                insights.append(
                    {
                        "category": "thermal_insulation_and_ufh_tuning",
                        "title": f"High Winter Thermal Heat Loss Detected in {zone} ({val}°C/hr)",
                        "finding_details": f"Historical analysis shows {zone} loses heat at {val}°C/hr.",
                        "evidence_metrics": {"thermal_decay_rate_c_per_hr": val, "source_entities": sources},
                        "recommended_human_action": f"Inspect insulation and heating curve in {zone}.",
                        "estimated_impact": "Reduces heating cycling waste.",
                    }
                )

            if "window_condensation_margin" in name and len(sources) >= 3:
                sig_area = name.replace("_window_condensation_margin", "")
                rh_eid = sources[1]
                t_out_eid = sources[2]
                zone_actions = []
                for eid, st in corroborated.items():
                    if st.get("area_id") == sig_area and eid not in already_automated_targets:
                        if st.get("domain") == "humidifier":
                            zone_actions.append({"service": "humidifier.turn_on", "target": {"entity_id": eid}})
                        elif st.get("domain") == "fan":
                            zone_actions.append({"service": "fan.set_percentage", "target": {"entity_id": eid}, "data": {"percentage": 80}})
                if zone_actions:
                    automations.append(
                        {
                            "alias": f"Dew-Point Window Condensation Guard ({sig_area.replace('_', ' ').title()})",
                            "description": f"Synthesized by Climate Agent for {sig_area}.",
                            "cause_category": f"crystallized_condensation_automation_{sig_area}",
                            "discovered_pattern_rationale": "Crystallized psychrometric protection.",
                            "trigger": [{"platform": "numeric_state", "entity_id": rh_eid, "above": 62, "for": "00:05:00"}],
                            "condition": [{"condition": "numeric_state", "entity_id": t_out_eid, "below": 5.0}],
                            "action": zone_actions,
                        }
                    )

            if "solar_heat_gain_index" in name and len(sources) >= 2:
                sig_area = name.replace("_solar_heat_gain_index", "")
                lux_eid = sources[0]
                temp_eid = sources[1]
                ufh_eids = [
                    eid
                    for eid, st in corroborated.items()
                    if st.get("area_id") == sig_area and st.get("domain") == "climate" and eid not in already_automated_targets
                ]
                if ufh_eids:
                    automations.append(
                        {
                            "alias": f"Solar Gain UFH Thermal Inertia Pre-Trim ({sig_area.replace('_', ' ').title()})",
                            "description": f"Lowers {ufh_eids[0]} setpoint on high solar illuminance.",
                            "cause_category": f"crystallized_solar_ufh_automation_{sig_area}",
                            "discovered_pattern_rationale": "Correlated solar irradiance with thermal lag.",
                            "trigger": [{"platform": "numeric_state", "entity_id": lux_eid, "above": 25000, "for": "00:10:00"}],
                            "condition": [{"condition": "numeric_state", "entity_id": temp_eid, "above": 21.5}],
                            "action": [{"service": "climate.set_temperature", "target": {"entity_id": ufh_eids[0]}, "data": {"temperature": 20.5}}],
                        }
                    )

        return {"advisory_insights": insights, "native_automations": automations, "actions": []}
