"""Household / environment context assembled locally from Home Assistant state (no LLM, no extra API calls)."""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

from ha_ai_brain.domain.models import EntityState
from ha_ai_brain.domain.timeutil import WEEKDAY_NAMES, day_class, to_local

PRICE_KEYWORDS = ("price", "tariff", "nordpool", "tibber", "electricity_cost", "energy_price")
SOLAR_FORECAST_KEYWORDS = ("solar", "pv", "photovoltaic", "energy_production", "power_production")


def part_of_day(hour: int) -> str:
    if hour < 6:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    if hour < 23:
        return "evening"
    return "night"


def person_entities(states: dict[str, EntityState]) -> list[str]:
    return sorted(eid for eid, st in states.items() if st.domain == "person")


def build_household_context(
    states: dict[str, EntityState],
    now: datetime,
    tz: tzinfo,
    forecast: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    local = to_local(now, tz)
    persons = [s for s in states.values() if s.domain == "person"]
    ctx: dict[str, Any] = {
        "local_time": local.strftime("%Y-%m-%d %H:%M"),
        "weekday": WEEKDAY_NAMES[local.weekday()],
        "day_class": day_class(local),
        "part_of_day": part_of_day(local.hour),
        "presence": {
            "people_tracked": len(persons),
            "anyone_home": (any(p.state == "home" for p in persons) if persons else None),
            "states": {p.entity_id: p.state for p in persons[:8]},
        },
    }

    sun = states.get("sun.sun")
    if sun is not None:
        ctx["sun"] = {
            "state": sun.state,
            "elevation": sun.attributes.get("elevation"),
            "azimuth": sun.attributes.get("azimuth"),
            "next_rising": sun.attributes.get("next_rising"),
            "next_setting": sun.attributes.get("next_setting"),
        }

    weather = next((s for s in states.values() if s.domain == "weather"), None)
    if weather is not None:
        ctx["weather"] = {
            "entity_id": weather.entity_id,
            "condition": weather.state,
            "temperature": weather.attributes.get("temperature"),
            "humidity": weather.attributes.get("humidity"),
            "wind_speed": weather.attributes.get("wind_speed"),
            "cloud_coverage": weather.attributes.get("cloud_coverage"),
        }
        if forecast:
            ctx["weather"]["forecast_next_hours"] = forecast[:12]

    def pick(keywords: tuple[str, ...], require_numeric: bool = True) -> list[dict[str, Any]]:
        found = []
        for eid, st in states.items():
            if st.domain != "sensor":
                continue
            low = eid.lower()
            if not any(k in low for k in keywords):
                continue
            if require_numeric and st.numeric_value is None:
                continue
            found.append({"entity_id": eid, "state": st.state, "unit": st.unit_of_measurement})
        return found[:6]

    prices = pick(PRICE_KEYWORDS)
    prices += [
        {"entity_id": eid, "state": st.state, "unit": st.unit_of_measurement}
        for eid, st in states.items()
        if st.domain == "sensor" and st.device_class == "monetary" and st.numeric_value is not None
    ][:3]
    if prices:
        ctx["energy_prices"] = prices[:6]
    solar = [e for e in pick(SOLAR_FORECAST_KEYWORDS) if "forecast" in e["entity_id"].lower() or "estimate" in e["entity_id"].lower()]
    if solar:
        ctx["solar_forecast"] = solar
    return ctx
