"""Registry of Built-in Specialized Agents and Declarative User-Defined Custom Agents."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ha_ai_brain.domain.models import AgentSpec

logger = logging.getLogger(__name__)


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
            controllable_domains=["lock", "alarm_control_panel", "cover", "valve", "notify", "automation"],
            goals=[
                "Correlate occupancy with perimeter state and environmental hazard sensors to protect the property",
                "Propose the actual actuator service call (e.g. lock.lock, cover.close_cover, valve.close_valve) when an action can be taken by an actuator; the Guardrail Engine will automatically attach the interactive Approve/Reject buttons to the user notification",
                "Propose native automations only for protective routines (for example a notification when a door stays unlocked while everyone is away, or closing a valve on a leak); automations that unlock, disarm or open anything are never created without your explicit approval",
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
            controllable_domains=["homeassistant", "notify", "automation"],
            goals=[
                "Detect unavailable entities, inspect HA system logs, and diagnose root causes",
                "Use available MCP tools and HA services to self-heal integrations or report actionable diagnostics",
                "Propose a native automation only for a recurring reliability problem (for example a low battery on a device that matters) "
                "that no existing automation, Watch or built-in alert already covers",
            ],
            batch_trigger="unavailable_only",
            enabled=True,
            is_custom=False,
        ),
    ]


BUILTIN_AGENT_IDS: frozenset[str] = frozenset(a.agent_id for a in get_builtin_agents())
BUNDLED_EXAMPLE_IDS: frozenset[str] = frozenset({"solar_energy_agent", "beer_brewery_agent"})


def _shipped_agents_dirs() -> frozenset[Path]:
    parents = Path(__file__).resolve().parents
    out: set[Path] = set()
    for idx in (3, 4):
        if idx < len(parents):
            candidate = parents[idx] / "agents"
            if candidate.is_dir():
                out.add(candidate.resolve())
    return frozenset(out)


class AgentRegistry:
    """Manages active built-in agents and user-defined custom agents (YAML / API)."""

    def __init__(self, custom_agents_dir: str = "agents", bundled_agents_dir: str = "") -> None:
        self.custom_agents_dir = Path(custom_agents_dir)
        self.bundled_agents_dir = Path(bundled_agents_dir) if bundled_agents_dir else None
        self._agents: dict[str, AgentSpec] = {a.agent_id: a for a in get_builtin_agents()}
        self.load_custom_agents_from_disk()

    def _is_shipped_template_file(self, agent_id: str, path: Path) -> bool:
        """Never overwrite or delete the shipped template YAML files inside the repo or container image."""
        if agent_id not in BUNDLED_EXAMPLE_IDS:
            return False
        parent = path.parent.resolve()
        if self.bundled_agents_dir and parent == self.bundled_agents_dir.resolve():
            return True
        return parent in _shipped_agents_dirs()

    def load_custom_agents_from_disk(self) -> None:
        """Load declarative custom agent YAML files (shipped examples first, then the user's persisted agents)."""
        directories: list[Path] = []
        if self.bundled_agents_dir and self.bundled_agents_dir.resolve() != self.custom_agents_dir.resolve():
            directories.append(self.bundled_agents_dir)
        directories.append(self.custom_agents_dir)
        for directory in directories:
            if not directory.is_dir():
                continue
            for yaml_path in sorted(directory.glob("*.yaml")):
                try:
                    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and "agent_id" in raw:
                        raw["is_custom"] = str(raw["agent_id"]) not in BUILTIN_AGENT_IDS
                        spec = AgentSpec.model_validate(raw)
                        self._agents[spec.agent_id] = spec
                except Exception as exc:
                    logger.warning("Skipping invalid agent definition %s: %s", yaml_path, exc)

    def register_custom_agent(self, spec: AgentSpec, persist_to_disk: bool = True) -> AgentSpec:
        """Register a new user-defined specialized agent dynamically."""
        spec.is_custom = spec.agent_id not in BUILTIN_AGENT_IDS
        self._agents[spec.agent_id] = spec
        if persist_to_disk:
            self.custom_agents_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.custom_agents_dir / f"{spec.agent_id}.yaml"
            out_path.write_text(yaml.safe_dump(spec.model_dump(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        return spec

    def set_agent_enabled(self, agent_id: str, enabled: bool, persist_to_disk: bool = True) -> AgentSpec:
        """Enable or disable a built-in or custom agent."""
        spec = self._agents.get(agent_id)
        if spec is None:
            raise KeyError(agent_id)
        spec.enabled = bool(enabled)
        if persist_to_disk:
            out_path = self.custom_agents_dir / f"{spec.agent_id}.yaml"
            if out_path.is_file() and not self._is_shipped_template_file(spec.agent_id, out_path):
                out_path.write_text(yaml.safe_dump(spec.model_dump(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        return spec

    def delete_custom_agent(self, agent_id: str, remove_from_disk: bool = True) -> AgentSpec:
        """Delete a custom agent; built-in agents cannot be deleted."""
        if agent_id in BUILTIN_AGENT_IDS:
            raise ValueError(f"Built-in agent '{agent_id}' cannot be deleted; disable it instead.")
        spec = self._agents.get(agent_id)
        if spec is None:
            raise KeyError(agent_id)
        if not spec.is_custom:
            raise ValueError(f"Built-in agent '{agent_id}' cannot be deleted; disable it instead.")
        del self._agents[agent_id]
        if remove_from_disk:
            out_path = self.custom_agents_dir / f"{agent_id}.yaml"
            if out_path.is_file() and not self._is_shipped_template_file(agent_id, out_path):
                out_path.unlink(missing_ok=True)
        return spec

    def get_agent(self, agent_id: str) -> AgentSpec | None:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def get_active_agents(self) -> list[AgentSpec]:
        """Return all enabled registered agents."""
        return [a for a in self._agents.values() if a.enabled]
