"""Registry of Built-in Specialized Agents and Declarative User-Defined Custom Agents."""

from __future__ import annotations

from pathlib import Path
import yaml

from ha_ai_brain.domain.models import AgentSpec


def get_builtin_agents() -> list[AgentSpec]:
    """
    Return the built-in suite of specialized Home Assistant AI Agents.
    Note: Agents are defined by their expert domain persona and high-level objectives,
    NOT hardcoded metrics or rules. Each agent inspects the actual entity keys, values,
    attributes, and history to discover what derived signals and reactions make sense.
    """
    return [
        AgentSpec(
            agent_id="climate_thermal_agent",
            name="Climate & Indoor Environment Agent",
            specialty="Senior Building Physics, HVAC, Thermodynamics & Indoor Environmental Quality Engineer",
            description=(
                "Analyzes all indoor and outdoor environmental sensors, heating/cooling/ventilation systems, "
                "and shading/window actuators from an expert building-science perspective. Discovers relevant "
                "physical relationships and derived metrics dynamically from the available Home Assistant entities."
            ),
            monitored_domains=["sensor", "climate", "weather", "cover", "fan", "humidifier"],
            monitored_device_classes=["temperature", "humidity", "illuminance", "carbon_dioxide", "volatile_organic_compounds", "pressure"],
            controllable_domains=["climate", "fan", "humidifier", "cover", "notify", "automation"],
            goals=[
                "Analyze available environmental sensor keys, values, units, and historical trajectories from a building-physics and thermodynamics perspective",
                "Identify any physical risks, comfort inefficiencies, thermal lag effects, or structural anomalies implied by the data",
                "Determine what derived physical or statistical signals (if any) should be computed from the available sensors to support decisions",
                "Control available climate, ventilation, humidity, and cover actuators (or notify occupants when manual action is needed) and synthesize non-duplicate native HA automations",
            ],
            enabled=True,
            is_custom=False,
        ),
        AgentSpec(
            agent_id="lighting_pattern_agent",
            name="Lighting & Habit Automation Agent",
            specialty="Human Behavioral Pattern Scientist & Smart Lighting Ergonomics Expert",
            description=(
                "Observes manual human device interactions, presence/occupancy sensors, and ambient light "
                "to discover un-automated human routines and synthesize predictive reactions or native automations."
            ),
            monitored_domains=["light", "binary_sensor", "sensor", "sun", "person"],
            monitored_device_classes=["illuminance", "motion", "occupancy", "presence"],
            controllable_domains=["light", "scene", "automation", "notify"],
            goals=[
                "Distinguish genuine manual human habits from actions already triggered by existing Home Assistant automations",
                "Predictively actuate lighting or propose native HA automations for recurring manual routines",
            ],
            enabled=True,
            is_custom=False,
        ),
        AgentSpec(
            agent_id="security_safety_agent",
            name="Security & Safety Agent",
            specialty="Physical Security, Perimeter Integrity & Environmental Hazard Specialist",
            description=(
                "Monitors locks, openings, hazard sensors, and occupancy states with strict deterministic "
                "guardrails on sensitive actuators."
            ),
            monitored_domains=["lock", "alarm_control_panel", "binary_sensor", "cover", "person"],
            monitored_device_classes=["door", "window", "lock", "moisture", "smoke", "gas"],
            controllable_domains=["lock", "alarm_control_panel", "cover", "valve", "notify"],
            goals=[
                "Correlate occupancy with perimeter state and environmental hazard sensors to protect the property",
                "Propose the actual actuator service call (e.g. lock.lock, cover.close_cover, valve.close_valve) when an action can be taken by an actuator; the Guardrail Engine will automatically attach the interactive Approve/Reject buttons to the user notification",
            ],
            enabled=True,
            is_custom=False,
        ),
        AgentSpec(
            agent_id="energy_efficiency_agent",
            name="Energy, Power & Solar Optimization Agent",
            specialty="Residential Energy Storage, Solar Photovoltaics & Load Shifting Engineer",
            description=(
                "Analyzes whole-home power draw, solar generation, grid export/import, battery state of charge, "
                "and heavy appliance cycles to minimize electricity bills and maximize solar self-consumption."
            ),
            monitored_domains=["sensor", "switch", "climate", "binary_sensor"],
            monitored_device_classes=["power", "energy", "battery", "current", "voltage"],
            controllable_domains=["switch", "climate", "automation", "notify"],
            goals=[
                "Analyze historical power consumption and solar production profiles to identify baseload waste and phantom loads",
                "Recommend or synthesize native automations to schedule flexible loads (EV charging, heat pumps, water heaters, dehumidifiers) during peak solar or cheap tariffs",
                "Emit advisory insights for unusually high standby power consumption or energy anomalies",
            ],
            enabled=True,
            is_custom=False,
        ),
        AgentSpec(
            agent_id="cover_shading_agent",
            name="Cover & Solar Shading Agent",
            specialty="Passive Solar Architecture & Automated Envelope Shading Specialist",
            description=(
                "Manages motorized blinds, roller shutters, curtains, and awnings to balance natural day-lighting, "
                "passive solar winter heating, summer overheating protection, and night-time privacy."
            ),
            monitored_domains=["cover", "sensor", "sun", "weather", "binary_sensor"],
            monitored_device_classes=["blind", "curtain", "shade", "shutter", "window", "illuminance", "temperature"],
            controllable_domains=["cover", "automation", "notify"],
            goals=[
                "Coordinate cover positions with solar elevation, azimuth, and outdoor illuminance to optimize indoor comfort and glare",
                "Automate night-time closing to reduce thermal envelope radiation losses in winter",
                "Detect un-automated manual adjustments to motorized shading and propose native automations",
            ],
            enabled=True,
            is_custom=False,
        ),
        AgentSpec(
            agent_id="repair_diagnostics_agent",
            name="Repair & Diagnostics Agent",
            specialty="Smart Home Systems Reliability & Network Diagnostics Engineer",
            description=(
                "Monitors unavailable entities and HA error logs; uses MCP tools to diagnose connectivity, "
                "DHCP/IP changes, and integration health."
            ),
            monitored_domains=["device_tracker", "sensor", "switch", "climate", "light"],
            monitored_device_classes=[],
            controllable_domains=["homeassistant", "notify"],
            goals=[
                "Detect unavailable entities, inspect HA system logs, and diagnose root causes",
                "Use available MCP tools and HA services to self-heal integrations or report actionable diagnostics",
            ],
            enabled=True,
            is_custom=False,
        ),
    ]


class AgentRegistry:
    """Manages active built-in agents and user-defined custom agents (YAML / API)."""

    def __init__(self, custom_agents_dir: str = "agents") -> None:
        self.custom_agents_dir = Path(custom_agents_dir)
        self._agents: dict[str, AgentSpec] = {a.agent_id: a for a in get_builtin_agents()}
        self.load_custom_agents_from_disk()

    def load_custom_agents_from_disk(self) -> None:
        """Load declarative custom agent YAML files from `custom_agents_dir`."""
        if not self.custom_agents_dir.exists():
            return
        for yaml_path in sorted(self.custom_agents_dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and "agent_id" in raw:
                    raw["is_custom"] = True
                    spec = AgentSpec.model_validate(raw)
                    self._agents[spec.agent_id] = spec
            except Exception:
                continue

    def register_custom_agent(self, spec: AgentSpec, persist_to_disk: bool = True) -> AgentSpec:
        """Register a new user-defined specialized agent dynamically."""
        spec.is_custom = True
        self._agents[spec.agent_id] = spec
        if persist_to_disk:
            self.custom_agents_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.custom_agents_dir / f"{spec.agent_id}.yaml"
            out_path.write_text(yaml.safe_dump(spec.model_dump(), sort_keys=False), encoding="utf-8")
        return spec

    def get_agent(self, agent_id: str) -> AgentSpec | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def get_active_agents(self) -> list[AgentSpec]:
        """Return all enabled registered agents."""
        return [a for a in self._agents.values() if a.enabled]
