"""Curated, versioned expert reference guidance injected into prompts (instead of the LLM recalling it from memory)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ha_ai_brain.domain.models import AgentSpec, EntityState

logger = logging.getLogger(__name__)

KNOWLEDGE_VERSION = "2026.10"


@dataclass(frozen=True)
class KnowledgeEntry:
    id: str
    title: str
    tags: frozenset[str]
    guidance: str
    source: str


def _e(id_: str, title: str, tags: str, guidance: str, source: str) -> KnowledgeEntry:
    return KnowledgeEntry(id_, title, frozenset(tags.split()), guidance, source)


BUILTIN_KNOWLEDGE: tuple[KnowledgeEntry, ...] = (
    _e(
        "humidity-comfort", "Indoor relative humidity comfort band",
        "humidity climate hvac humidifier ventilation comfort",
        "Keep indoor relative humidity roughly between 40 % and 60 %. Sustained values above 60-65 % favour mould and dust mites; "
        "below ~30 % dries airways and raises static electricity.",
        "ASHRAE 55 thermal comfort guidance; WHO housing & health guidelines (general guidance)",
    ),
    _e(
        "dew-point-condensation", "Condensation on glazing and cold surfaces",
        "humidity temperature condensation window cover climate",
        "A surface collects condensation when its temperature is at or below the room's dew point. Dew point (Magnus-Tetens, a=17.625, "
        "b=243.04): gamma = a*T/(b+T) + ln(RH/100); Td = b*gamma/(a-gamma). In winter window glass can be several degrees colder than "
        "room air; a margin below ~2 degC between glass and dew point is a condensation risk.",
        "Psychrometrics (Magnus-Tetens approximation)",
    ),
    _e(
        "mould-surface-rh", "Mould growth criterion",
        "humidity mould condensation insulation temperature",
        "Mould growth becomes likely when the relative humidity at a surface stays above about 80 % for days. Cold external-wall "
        "corners reach this first, so look at the coldest rooms and at sustained rather than momentary humidity.",
        "ISO 13788 surface humidity criterion (building physics rule of thumb)",
    ),
    _e(
        "co2-ventilation", "CO2 as a ventilation indicator",
        "carbon_dioxide co2 ventilation fan air_quality",
        "Outdoor CO2 is about 420 ppm. Indoor levels persistently above ~1000 ppm indicate insufficient ventilation for the occupancy; "
        "above ~1500 ppm ventilate. Bedrooms overnight are the usual worst case.",
        "ASHRAE 62.1 / EN 16798-1 (indicative thresholds)",
    ),
    _e(
        "heating-setback", "Heating setback savings",
        "climate heating hvac energy temperature schedule setpoint",
        "Lowering the heating setpoint by roughly 4-5 degC for about 8 hours a day (for example overnight or while away) can save up "
        "to around 10 % of annual heating energy. Each 1 degC lower setpoint typically saves roughly 5-10 %.",
        "US DOE energy saver guidance (general guidance)",
    ),
    _e(
        "sleep-temperature", "Bedroom temperature for sleep",
        "temperature bedroom climate sleep comfort",
        "Bedrooms are commonly recommended at about 16-19 degC for sleep; warmer rooms increase restlessness.",
        "Sleep-medicine consumer guidance (general guidance)",
    ),
    _e(
        "floor-heating-inertia", "Thermal inertia of underfloor heating",
        "climate ufh underfloor floor heating temperature inertia schedule",
        "A concrete heated slab reacts with a lag of hours. Plan pre-heating or setback 2-4 hours ahead, avoid frequent small setpoint "
        "changes, and treat solar gain as a reason to trim the setpoint before the room overshoots.",
        "Building physics rule of thumb",
    ),
    _e(
        "legionella", "Hot-water storage temperature",
        "water_heater boiler hot_water temperature energy legionella",
        "Store domestic hot water at 60 degC or higher and keep distribution at 50 degC or higher; avoid long stagnation between "
        "25 and 45 degC. Do not recommend lowering storage temperature below this for energy savings.",
        "WHO Legionella prevention guidance; HSE L8",
    ),
    _e(
        "frost-protection", "Freeze protection",
        "temperature climate frost heating outdoor pipes",
        "Keep unheated or vacant spaces at 5 degC or above to avoid pipe freezing; a 5-8 degC frost-protection setpoint is typical when away.",
        "General heating practice",
    ),
    _e(
        "solar-load-shifting", "Solar self-consumption and load shifting",
        "power energy solar pv battery switch water_heater ev tariff price",
        "Shift flexible loads (hot-water heater, EV charging, thermal-mass pre-heating) into hours of PV surplus; charge storage ahead of "
        "forecast surplus; avoid exporting to the grid while thermal or battery storage has capacity. Use price sensors for off-peak shifting.",
        "Energy-management practice",
    ),
    _e(
        "standby-loads", "Standby consumption",
        "power energy switch standby plug",
        "Standby loads are commonly cited as 5-10 % of household electricity. Flag devices whose power never drops to near zero at night.",
        "IEA standby power studies (commonly cited range)",
    ),
    _e(
        "window-open-heating", "Heating while a window is open",
        "window door binary_sensor climate heating energy opening",
        "Heating or cooling a room whose window has been open for more than a few minutes wastes energy. Pause the climate entity "
        "and resume after the window closes.",
        "General energy-saving practice",
    ),
    _e(
        "external-shading", "Shading and solar gain",
        "cover blind shade shutter awning illuminance solar temperature sun",
        "External shading blocks solar gain far more effectively than internal blinds. Close south/west shading before the sun hits the "
        "glazing in summer; open it for passive solar gain in winter; close at night in winter to cut radiative losses.",
        "Building physics (passive solar design)",
    ),
    _e(
        "circadian-lighting", "Evening and morning lighting",
        "light lighting illuminance circadian sleep evening",
        "Dim, warm light (about 2700 K or lower) in the evening supports sleep; bright cooler light in the morning supports alertness. "
        "Avoid bright cool light at night for bathroom trips.",
        "Chronobiology consumer guidance (general guidance)",
    ),
    _e(
        "security-away", "Perimeter security while away",
        "lock door garage gate alarm security presence person",
        "Unlocked doors, open garage doors and disarmed alarms while nobody is home are the highest-impact security failures. Treat them "
        "as critical, notify immediately, and never unlock or disarm automatically.",
        "Home-security practice",
    ),
    _e(
        "water-leak", "Water leak response",
        "moisture leak water valve flood binary_sensor",
        "A water-leak sensor in the 'on' state is urgent: notify immediately and, where a motorised main valve exists, propose closing it "
        "(approval required).",
        "Home-safety practice",
    ),
    _e(
        "smoke-co", "Smoke and CO alarms",
        "smoke gas carbon_monoxide safety alarm",
        "Never silence or ignore smoke/CO alarms automatically. Notify every occupant, turn on lights for escape routes, and switch off "
        "ventilation fans that could spread smoke.",
        "Fire-safety practice",
    ),
    _e(
        "device-reliability", "Device availability and battery",
        "unavailable battery sensor zigbee wifi diagnostics repair network",
        "Batteries below ~15 % need replacing soon; devices that flap between available and unavailable usually indicate weak mesh or "
        "Wi-Fi signal or a changed IP address. Group failures by integration or area before blaming a single device.",
        "Smart-home operations practice",
    ),
)


def _load_user_entries(directory: str) -> list[KnowledgeEntry]:
    entries: list[KnowledgeEntry] = []
    path = Path(directory) if directory else None
    if not path or not path.is_dir():
        return entries
    for f in sorted(path.glob("*.y*ml")):
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8"))
            for item in raw if isinstance(raw, list) else []:
                if isinstance(item, dict) and item.get("id") and item.get("guidance"):
                    entries.append(
                        KnowledgeEntry(
                            id=str(item["id"]),
                            title=str(item.get("title", item["id"])),
                            tags=frozenset(str(t).lower() for t in (item.get("tags") or [])),
                            guidance=str(item["guidance"]),
                            source=str(item.get("source", "user-provided")),
                        )
                    )
        except Exception as exc:
            logger.warning("Skipping invalid knowledge file %s: %s", f, exc)
    return entries


def all_entries(user_dir: str = "") -> list[KnowledgeEntry]:
    merged = {e.id: e for e in BUILTIN_KNOWLEDGE}
    for e in _load_user_entries(user_dir):
        merged[e.id] = e
    return list(merged.values())


def select_knowledge(
    agent: AgentSpec,
    states: dict[str, EntityState],
    limit: int = 8,
    user_dir: str = "",
) -> list[dict[str, Any]]:
    """Entries most relevant to the agent's specialty and the kinds of entities that actually exist."""
    words = set(re.findall(r"[a-z0-9_]{3,}", f"{agent.name} {agent.specialty} {' '.join(agent.goals)}".lower()))
    present: set[str] = set(agent.monitored_domains) | set(agent.controllable_domains) | set(agent.monitored_device_classes)
    for st in states.values():
        present.add(st.domain)
        if st.device_class:
            present.add(st.device_class)
        # Entity-name keywords (e.g. "ufh", "boiler", "garage") also drive relevance.
        for token in re.findall(r"[a-z]{3,}", st.entity_id.lower().split(".", 1)[-1]):
            present.add(token)

    scored: list[tuple[int, KnowledgeEntry]] = []
    for entry in all_entries(user_dir):
        score = 2 * len(entry.tags & present) + len(entry.tags & words)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda t: (-t[0], t[1].id))
    return [
        {"id": e.id, "title": e.title, "guidance": e.guidance, "source": e.source, "origin": "built-in seed (general guidance, unverified)"}
        for _, e in scored[:limit]
    ]
