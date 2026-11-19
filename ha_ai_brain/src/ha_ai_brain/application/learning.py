"""Local learning engine: records telemetry, mines habits, learns baselines and detects exceptions (zero LLM tokens)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.automation_rules import (
    AutomationRule,
    _listify,
    clean_alias,
    dump_controller_overrides,
    find_equivalent_rule,
    is_controller_automation_id,
    load_controller_overrides,
    parse_automation_config,
    pattern_covered_by,
    resolve_rule_targets,
    rule_expectations,
    rule_produces_state,
    strip_brain_prefix,
)
from ha_ai_brain.domain.backtest import Timeline, backtest_automation
from ha_ai_brain.domain.baselines import NumericBaseline
from ha_ai_brain.domain.context import build_household_context
from ha_ai_brain.domain.anomaly import (
    DiscreteProfile,
    build_discrete_profiles,
    collapse_device_findings,
    find_dwell_anomalies,
    find_flapping,
    find_numeric_anomalies,
    find_silent_entities,
    find_stuck_unavailable,
    prioritise,
)
from ha_ai_brain.domain.expectations import (
    ExceptionFinding,
    expected_state_now,
    find_missed_automations,
    find_routine_deviations,
    find_security_while_away,
    is_safety_entity,
)
from ha_ai_brain.domain.models import (
    BacktestResult,
    EntityState,
    NativeAutomationProposal,
    SemanticEventFrame,
    StateChangedEvent,
    Transition,
)
from ha_ai_brain.domain.habit_rejections import MAX_REJECTED_HABITS, RejectedHabit, rejected_habit_card, split_rejected
from ha_ai_brain.domain.patterns import (
    AUTOMATED_ORIGINS,
    TRANSITIONAL_MAX_TRAVEL_SECONDS,
    TRANSITIONAL_STATES,
    MinedPattern,
    mine_all_report,
)
from ha_ai_brain.domain.sequence_filters import RULE_TWIN, SuppressedHabit
from ha_ai_brain.domain.service_semantics import (
    ACTUATOR_DOMAINS,
    SCRIPT_RUN_STATE,
    format_preset_token,
    format_temp_token,
    is_attribute_state,
    state_channel,
)
from ha_ai_brain.domain.timeutil import ensure_utc, parse_iso, resolve_tz, to_local
from ha_ai_brain.ports.memory import MemoryStorePort
from ha_ai_brain.ports.smart_home import SmartHomePort
from ha_ai_brain.domain.twins import TwinMap, build_twin_map, canonicalize_transitions, dump_splits, load_splits, reason_for_card
from ha_ai_brain.ports.telemetry import AUTOMATION_FIRE_STATE, TelemetryStorePort

logger = logging.getLogger(__name__)

RECORDED_DISCRETE_DOMAINS = ACTUATOR_DOMAINS | {"binary_sensor", "person", "alarm_control_panel"}
SECURITY_DEVICE_CLASSES = frozenset({"smoke", "gas", "moisture", "carbon_monoxide", "safety", "tamper", "problem"})
NON_STATES = frozenset({"unavailable", "unknown", ""})
PATTERN_CACHE_MINUTES = 30
MINING_WINDOW_DAYS = 30
SUPPRESSED_LIST_MAX = 60  # how many dropped 'habits' are kept for the dashboard
EXCEPTION_COOLDOWN_HOURS = 6


NUMERIC_BACKFILL_HOURS = 96
NUMERIC_BACKFILL_MAX_ENTITIES = 100
HIGH_VALUE_SENSOR_CLASSES = ("temperature", "humidity", "power", "illuminance", "carbon_dioxide", "energy")


def select_history_entities(states: dict[str, EntityState], limit: int) -> list[str]:
    """Switchable / presence / door entities (their transitions drive habit learning), most valuable first."""
    return sorted(eid for eid, st in states.items() if st.domain in RECORDED_DISCRETE_DOMAINS)[:limit]


def select_numeric_entities(states: dict[str, EntityState], limit: int = NUMERIC_BACKFILL_MAX_ENTITIES) -> list[str]:
    """Numeric sensors worth a baseline: environment, power and illuminance sensors first."""
    scored = sorted(
        (0 if st.device_class in HIGH_VALUE_SENSOR_CLASSES else 1, eid)
        for eid, st in states.items()
        if st.domain == "sensor" and st.numeric_value is not None
    )
    return [eid for _, eid in scored[:limit]]


def aggregate_hourly(samples: list[tuple[str, datetime, float]]) -> list[tuple[str, datetime, int, float]]:
    """Collapse raw numeric samples into (entity, hour, count, sum) rows."""
    buckets: dict[tuple[str, datetime], list[float]] = {}
    for eid, ts, value in samples:
        hour = ensure_utc(ts).replace(minute=0, second=0, microsecond=0)
        agg = buckets.setdefault((eid, hour), [0, 0.0])
        agg[0] += 1
        agg[1] += value
    return [(eid, hour, int(n), total) for (eid, hour), (n, total) in buckets.items()]


def history_to_records(
    history: dict[str, list[dict[str, Any]]],
    since: datetime,
) -> tuple[list[Transition], list[tuple[str, datetime, float]]]:
    """Convert Home Assistant history series into transitions (discrete domains) and numeric samples (sensors)."""
    transitions: list[Transition] = []
    numeric: list[tuple[str, datetime, float]] = []
    for eid, series in history.items():
        domain = eid.split(".", 1)[0]
        prev: str | None = None
        for point in series:
            state = str(point.get("state", ""))
            ts = parse_iso(point.get("last_changed") or point.get("last_updated"))
            if domain == "sensor":
                try:
                    value = float(state)
                except ValueError:
                    continue
                if ts is not None and ts >= since and value == value and abs(value) != float("inf"):
                    numeric.append((eid, ts, value))
                continue
            if domain in RECORDED_DISCRETE_DOMAINS:
                if prev is not None and state != prev and ts is not None and ts >= since:
                    if state not in NON_STATES and prev not in NON_STATES:
                        transitions.append(Transition(eid, ts, prev, state, "unknown"))
                prev = state
    return transitions, numeric


@dataclass
class LearnedSnapshot:
    """Everything the exception detectors need, rebuilt at most every few minutes from the telemetry store."""

    built_at: datetime
    timeline: Timeline
    profiles: dict[str, DiscreteProfile]
    numeric_rows: dict[str, list[tuple[str, int, float]]]
    baselines: dict[str, NumericBaseline]


SNAPSHOT_MINUTES = 30
FLUSH_INTERVAL_SECONDS = 30.0
FLUSH_MAX_BUFFERED = 1000
ATTR_SETTLE_SECONDS = 15.0  # coalesce rapid + / - thermostat taps into a single target transition
FEEDBACK_PREFIX = "excfb:"
REJECTED_HABIT_PREFIX = "habit_rejected:"
CONTROLLER_OVERRIDES_KEY = "controller_automations"


class LearningEngine:
    def __init__(
        self,
        settings: BrainSettings,
        smart_home: SmartHomePort,
        telemetry: TelemetryStorePort,
        memory: MemoryStorePort | None = None,
    ) -> None:
        self.memory = memory
        self._snapshot: LearnedSnapshot | None = None
        # Writes are batched: one transaction every ~30 s instead of one commit per sensor event (SD cards, CPU).
        self._tr_buffer: list[Transition] = []
        self.twins: TwinMap = TwinMap()
        self._twins_at: datetime | None = None
        self._device_by_entity: dict[str, str] = {}
        self._suppressed: list[dict[str, Any]] = []
        self._suppression_stats: dict[str, int] = {}
        self._num_buffer: dict[tuple[str, datetime], list[float]] = {}
        self._last_flush = time.monotonic()
        self._exception_feedback: dict[str, dict[str, Any]] = {}
        self._daily_exceptions: tuple[str, int] = ("", 0)
        self.settings = settings
        self.smart_home = smart_home
        self.telemetry = telemetry
        self.rules: list[AutomationRule] = []
        self._rules_at: datetime | None = None
        self._controller_overrides: dict[str, bool] = {}  # automation.* -> True (controller) | False (not a controller)
        self._auto_controllers: dict[str, dict[str, str]] = {}  # automation.* -> {alias, reason}
        self._all_automations: dict[str, str] = {}  # automation.* -> alias
        self._patterns: list[MinedPattern] = []
        self._patterns_at: datetime | None = None
        self._rejected_habits: dict[str, RejectedHabit] | None = None  # loaded lazily from the kv store
        self._rejected_seen: set[str] = set()  # rejections that still match a habit in the current history
        self._habit_names: dict[str, str] = {}  # friendly names at the last mining, to match same-named duplicates
        self._baseline_ready_cache: tuple[datetime, bool] | None = None
        self._numeric_baselines: dict[str, tuple[datetime, NumericBaseline]] = {}
        self._reported: dict[str, datetime] = {}
        self._forecast: tuple[datetime, list[dict[str, Any]]] | None = None
        self._automated_movements: dict[str, tuple[datetime, str, str]] = {}
        self._recent_automation_fires: dict[str, datetime] = {}
        self.stats: Counter[str] = Counter()
        self._tz_name = settings.timezone

    # ---------------------------------------------------------------- time
    @property
    def tz(self) -> tzinfo:
        return resolve_tz(self._tz_name)

    async def init_timezone(self) -> None:
        if not self._tz_name:
            try:
                self._tz_name = await self.smart_home.get_timezone()
            except Exception as exc:
                logger.debug("timezone discovery failed: %s", exc)
        if self._tz_name:
            logger.info("Using timezone %s for time-of-day learning", self._tz_name)
        else:
            logger.warning("No timezone configured or discovered; time-of-day patterns use UTC (set BRAIN_TIMEZONE).")

    def local_now(self, now: datetime) -> datetime:
        return to_local(now, self.tz)

    # ----------------------------------------------------------- recording
    def _append_or_coalesce_attr_transition(
        self,
        entity_id: str,
        ts: datetime,
        old_tok: str,
        new_tok: str,
        origin: str,
        user_id: str | None,
    ) -> None:
        """Buffer an attribute transition (`temp:...`, `preset:...`), coalescing multi-tap steps within `ATTR_SETTLE_SECONDS`."""
        ch = state_channel(new_tok)
        for idx in range(len(self._tr_buffer) - 1, -1, -1):
            prev = self._tr_buffer[idx]
            if prev.entity_id != entity_id or state_channel(prev.new_state) != ch:
                continue
            elapsed = (ts - prev.ts).total_seconds()
            if 0.0 <= elapsed <= ATTR_SETTLE_SECONDS and prev.origin == origin:
                if prev.old_state == new_tok:
                    del self._tr_buffer[idx]
                else:
                    self._tr_buffer[idx] = Transition(
                        entity_id, ts, prev.old_state, new_tok, origin, user_id or prev.user_id
                    )
                return
            break
        self._tr_buffer.append(Transition(entity_id, ts, old_tok, new_tok, origin, user_id))

    _TRANSITIONAL_TARGET = {
        "closing": "closed",
        "opening": "open",
        "locking": "locked",
        "unlocking": "unlocked",
        "disarming": "disarmed",
    }

    def _infer_automated_origin(
        self,
        entity_id: str,
        domain: str,
        old_state: str,
        new_state: str,
        ts: datetime,
        eff_origin: str,
        user_id: str | None,
    ) -> str:
        """Carry `ha_automation` / `ai_brain` across physical travel states (`closing` -> `closed`) and async hardware callbacks."""
        movements = getattr(self, "_automated_movements", None)
        fires = getattr(self, "_recent_automation_fires", None)
        if eff_origin in AUTOMATED_ORIGINS:
            if movements is not None:
                if new_state in TRANSITIONAL_STATES:
                    movements[entity_id] = (ts, new_state, eff_origin)
                else:
                    movements.pop(entity_id, None)
            return eff_origin

        if eff_origin == "human_or_physical" and not user_id:
            if movements is not None:
                prev = movements.get(entity_id)
                if prev is not None and old_state == prev[1] and 0.0 <= (ts - prev[0]).total_seconds() <= TRANSITIONAL_MAX_TRAVEL_SECONDS:
                    eff_origin = prev[2]
            if eff_origin == "human_or_physical" and fires:
                target_state = self._TRANSITIONAL_TARGET.get(new_state, new_state)
                max_lag = 120.0 if (domain in ("cover", "lock", "valve") or old_state in TRANSITIONAL_STATES or new_state in TRANSITIONAL_STATES) else 15.0
                twins = getattr(self, "twins", None)
                for rule in getattr(self, "rules", ()):
                    if not rule.entity_state_id or not rule_produces_state(rule, entity_id, target_state, twins=twins):
                        continue
                    fire_ts = fires.get(rule.entity_state_id)
                    if fire_ts is not None and -2.0 <= (ts - fire_ts).total_seconds() <= max_lag:
                        eff_origin = "ha_automation"
                        break
            if movements is not None:
                if eff_origin in AUTOMATED_ORIGINS and new_state in TRANSITIONAL_STATES:
                    movements[entity_id] = (ts, new_state, eff_origin)
                elif new_state not in TRANSITIONAL_STATES:
                    movements.pop(entity_id, None)
        elif movements is not None and new_state not in TRANSITIONAL_STATES:
            movements.pop(entity_id, None)
        return eff_origin

    async def record_event(self, event: StateChangedEvent) -> None:
        """Queue the part of a live event that matters for learning (cheap, local); written in batches."""
        new = event.new_state
        old = event.old_state
        ts = ensure_utc(event.timestamp)
        eff_origin = event.origin.value
        if eff_origin == "ha_automation" and event.triggered_by_automation_id and self.is_controller_automation(event.triggered_by_automation_id):
            eff_origin = "human_or_physical"
        if new.domain in ("automation", "script"):
            last = parse_iso(new.attributes.get("last_triggered"))
            prev_last = parse_iso(old.attributes.get("last_triggered")) if old else None
            if last is not None and last != prev_last:
                if not (new.domain == "automation" and self.is_controller_automation(new.entity_id)):
                    self._tr_buffer.append(Transition(new.entity_id, last, "", AUTOMATION_FIRE_STATE, "ha_automation"))
                    fires = getattr(self, "_recent_automation_fires", None)
                    if fires is not None:
                        fires[new.entity_id] = ensure_utc(last)
                        if len(fires) > 500:
                            fires.pop(next(iter(fires)))
                if new.domain == "script" and eff_origin == "human_or_physical":
                    # Started by hand (not by an autonomous automation or the brain): a habit candidate, like flipping a switch.
                    self._tr_buffer.append(Transition(new.entity_id, last, "off", SCRIPT_RUN_STATE, "human_or_physical", event.context_user_id))
        elif new.domain == "sensor":
            value = new.numeric_value
            if value is not None:
                agg = self._num_buffer.setdefault((new.entity_id, ts.replace(minute=0, second=0, microsecond=0)), [0, 0.0])
                agg[0] += 1
                agg[1] += value
        elif new.domain in RECORDED_DISCRETE_DOMAINS and old is not None:
            if new.state not in NON_STATES and old.state not in NON_STATES:
                if old.state != new.state:
                    eff_origin = self._infer_automated_origin(
                        new.entity_id, new.domain, old.state, new.state, ts, eff_origin, event.context_user_id
                    )
                    self._tr_buffer.append(Transition(new.entity_id, ts, old.state, new.state, eff_origin, event.context_user_id))
                if new.domain in ("climate", "water_heater") and new.state != "off" and old.state != "off":
                    old_temp = format_temp_token(old.attributes.get("temperature"))
                    new_temp = format_temp_token(new.attributes.get("temperature"))
                    if old_temp is not None and new_temp is not None and old_temp != new_temp:
                        self._append_or_coalesce_attr_transition(new.entity_id, ts, old_temp, new_temp, eff_origin, event.context_user_id)
                if new.domain in ("climate", "fan", "humidifier"):
                    attr_key = "mode" if new.domain == "humidifier" else "preset_mode"
                    old_preset = format_preset_token(old.attributes.get(attr_key))
                    new_preset = format_preset_token(new.attributes.get(attr_key))
                    if new_preset is not None and old_preset != new_preset:
                        old_tok = old_preset or "preset:none"
                        if not (old_tok.lower() == "preset:none" and new_preset.lower() == "preset:none"):
                            self._append_or_coalesce_attr_transition(new.entity_id, ts, old_tok, new_preset, eff_origin, event.context_user_id)
        if len(self._tr_buffer) + len(self._num_buffer) >= FLUSH_MAX_BUFFERED or time.monotonic() - self._last_flush >= FLUSH_INTERVAL_SECONDS:
            await self.flush()

    async def flush(self) -> None:
        """Write buffered telemetry in one transaction. Called on a timer, before any read, and on shutdown."""
        if not self._tr_buffer and not self._num_buffer:
            self._last_flush = time.monotonic()
            return
        transitions, self._tr_buffer = self._tr_buffer, []
        numeric, self._num_buffer = self._num_buffer, {}
        self._last_flush = time.monotonic()
        try:
            await self.telemetry.record_transitions(transitions)
            await self.telemetry.record_numeric_hourly([(eid, hour, int(n), total) for (eid, hour), (n, total) in numeric.items()])
        except Exception as exc:  # recording must never break event processing; the next flush retries nothing
            logger.warning("telemetry flush failed (%d transitions dropped): %s", len(transitions), exc)

    async def backfill(self, states: dict[str, EntityState], now: datetime | None = None) -> int:
        """Import recorder history (since the last known transition, at most `store_backfill_hours`) into the store."""
        if not self.settings.store_backfill_hours or not getattr(self.smart_home, "supports_history_backfill", True):
            return 0
        now = now or datetime.now(timezone.utc)
        horizon = now - timedelta(hours=self.settings.store_backfill_hours)
        latest = await self.telemetry.latest_transition_ts()
        since = max(horizon, latest - timedelta(minutes=30)) if latest else horizon
        ids = select_history_entities(states, self.settings.history_max_entities)
        added = 0
        if ids:
            history = await self.smart_home.get_history(ids, since, now)
            transitions, _ = history_to_records(history, since)
            added = await self.telemetry.record_transitions(transitions)
            if history:
                current = parse_iso(await self.telemetry.get_meta("observed_since"))
                if current is None or since < current:
                    await self.telemetry.set_meta("observed_since", since.isoformat())

        # Sensors are much chattier than switches: a shorter window, a bounded entity list, stored as hourly aggregates.
        numeric_ids = select_numeric_entities(states)
        numeric_rows = 0
        if numeric_ids:
            numeric_since = max(since, now - timedelta(hours=NUMERIC_BACKFILL_HOURS))
            history = await self.smart_home.get_history(numeric_ids, numeric_since, now)
            _, samples = history_to_records(history, numeric_since)
            rows = aggregate_hourly(samples)
            if rows:
                await self.telemetry.replace_numeric_since(numeric_since)
                await self.telemetry.record_numeric_hourly(rows)
                numeric_rows = len(rows)
        self.stats["backfilled_transitions"] += added
        logger.info("Imported %d transitions and %d hourly sensor aggregates from Home Assistant history.", added, numeric_rows)
        return added

    # ------------------------------------------------------------- status
    async def window(self, now: datetime) -> tuple[datetime, datetime] | None:
        await self.flush()
        return await self.telemetry.observation_window(now)

    async def days_of_data(self, now: datetime) -> float:
        win = await self.window(now)
        return (win[1] - win[0]).total_seconds() / 86400.0 if win else 0.0

    async def baseline_ready(self, now: datetime) -> bool:
        cached = self._baseline_ready_cache
        if cached and (now - cached[0]).total_seconds() < 600:
            return cached[1]
        ready = await self.days_of_data(now) >= self.settings.baseline_min_days
        self._baseline_ready_cache = (now, ready)
        return ready

    # ------------------------------------------------------------ automations
    async def load_controller_overrides(self) -> dict[str, bool]:
        if self.memory is None:
            return self._controller_overrides
        prefs = await self.memory.get_ui_preferences()
        self._controller_overrides = load_controller_overrides(prefs.get(CONTROLLER_OVERRIDES_KEY))
        self._apply_controller_flags()
        return self._controller_overrides

    def is_controller_automation(self, automation_entity_id: str | None) -> bool:
        """True when `automation_entity_id` is a wall-panel / remote / button controller bridge rather than an autonomous rule."""
        if not automation_entity_id or not automation_entity_id.startswith("automation."):
            return False
        if automation_entity_id in self._controller_overrides:
            return self._controller_overrides[automation_entity_id]
        if automation_entity_id in self._auto_controllers:
            return True
        return is_controller_automation_id(automation_entity_id)

    def _apply_controller_flags(self, states: dict[str, EntityState] | None = None) -> None:
        auto_controllers: dict[str, dict[str, str]] = {}
        all_automations: dict[str, str] = {}
        for r in self.rules:
            eid = r.entity_state_id or (r.automation_id if r.automation_id.startswith("automation.") else f"automation.{r.automation_id}" if r.automation_id else "")
            if not eid:
                continue
            all_automations[eid] = r.alias or eid
            if r.auto_controller:
                auto_controllers[eid] = {
                    "entity_id": eid,
                    "alias": r.alias or eid,
                    "reason": r.controller_reason or "Wall panel or physical controller automation",
                }
            if eid in self._controller_overrides:
                r.is_controller = self._controller_overrides[eid]
            else:
                r.is_controller = r.auto_controller

        if states:
            for eid, st in states.items():
                if st.domain != "automation":
                    continue
                fname = str(st.attributes.get("friendly_name") or eid)
                all_automations.setdefault(eid, fname)
                if eid not in auto_controllers and is_controller_automation_id(f"{eid} {fname}"):
                    auto_controllers[eid] = {
                        "entity_id": eid,
                        "alias": fname,
                        "reason": "Wall panel or physical controller automation",
                    }
        self._auto_controllers = auto_controllers
        self._all_automations = all_automations

    async def set_controller_automation(self, entity_id: str, is_controller: bool | None) -> None:
        """Mark or unmark an `automation.*` entity as a human-interface controller (pass-through), or reset to auto-detected."""
        eid = (entity_id or "").strip()
        if not eid.startswith("automation."):
            raise ValueError("Entity must be an automation.* entity.")
        await self.load_controller_overrides()
        is_auto = eid in self._auto_controllers or is_controller_automation_id(eid)
        if is_controller is None or (is_controller is False and not is_auto) or (is_controller is True and is_auto):
            self._controller_overrides.pop(eid, None)
        else:
            self._controller_overrides[eid] = bool(is_controller)
        if self.memory is not None:
            await self.memory.save_ui_preference(CONTROLLER_OVERRIDES_KEY, dump_controller_overrides(self._controller_overrides))
        self._apply_controller_flags()
        self._patterns_at = None
        self._snapshot = None

    async def reset_controller_overrides(self) -> None:
        self._controller_overrides = {}
        if self.memory is not None:
            await self.memory.save_ui_preference(CONTROLLER_OVERRIDES_KEY, "{}")
        self._apply_controller_flags()
        self._patterns_at = None
        self._snapshot = None

    def controller_automations(self, states: dict[str, EntityState] | None = None) -> dict[str, Any]:
        """Controller / wall-panel automations (active, excluded by homeowner, and candidates to add) for the dashboard."""
        if states:
            self._apply_controller_flags(states)
        active: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        known_ids = sorted(set(self._all_automations) | set(self._auto_controllers) | set(self._controller_overrides))
        for eid in known_ids:
            alias = self._all_automations.get(eid) or (self._auto_controllers.get(eid) or {}).get("alias") or eid
            auto_info = self._auto_controllers.get(eid)
            override = self._controller_overrides.get(eid)
            if self.is_controller_automation(eid):
                reason = (auto_info or {}).get("reason") or (
                    "Marked as a wall panel / controller by you" if override is True else "Wall panel or physical controller automation"
                )
                active.append({
                    "entity_id": eid,
                    "alias": alias,
                    "reason": reason,
                    "auto_detected": bool(auto_info),
                })
            elif override is False and auto_info:
                excluded.append({"entity_id": eid, "alias": alias})
            elif not eid.startswith("automation.ai_brain_"):
                candidates.append({"entity_id": eid, "alias": alias})
        return {"active": active, "excluded": excluded, "candidates": candidates}

    async def refresh_rules(self, states: dict[str, EntityState] | None = None, force: bool = False) -> list[AutomationRule]:
        now = datetime.now(timezone.utc)
        if not force and self._rules_at and (now - self._rules_at).total_seconds() < 1800:
            if states:
                resolve_rule_targets(self.rules, states=states)
                self._apply_controller_flags(states)
            return self.rules
        if self.memory is not None and not self._controller_overrides:
            try:
                prefs = await self.memory.get_ui_preferences()
                self._controller_overrides = load_controller_overrides(prefs.get(CONTROLLER_OVERRIDES_KEY))
            except Exception:
                pass
        try:
            configs = await self.smart_home.get_automation_configs()
        except Exception as exc:
            logger.warning("Could not load automation definitions: %s", exc)
            return self.rules
        rules = [parse_automation_config(c) for c in configs if isinstance(c, dict)]
        facts: list[Any] = []
        if hasattr(self.smart_home, "get_entity_device_facts"):
            try:
                facts = await self.smart_home.get_entity_device_facts()
            except Exception as exc:
                logger.debug("Could not read entity facts for rule target resolution: %s", exc)
        if facts:
            self._device_by_entity = {f.entity_id: f.device_id for f in facts if getattr(f, "entity_id", "") and getattr(f, "device_id", "")}
        resolve_rule_targets(rules, states=states, facts=facts)
        if states:
            by_id = {str(s.attributes.get("id")): s for s in states.values() if s.domain == "automation" and s.attributes.get("id")}
            for r in rules:
                st = by_id.get(r.automation_id) or states.get(f"automation.{r.automation_id}") or states.get(r.automation_id)
                if st is not None:
                    r.entity_state_id = st.entity_id
                    r.enabled = st.state != "off"
                    if not r.auto_controller and is_controller_automation_id(f"{st.entity_id} {st.attributes.get('friendly_name') or ''}"):
                        r.auto_controller = True
                        r.controller_reason = r.controller_reason or "Wall panel or physical controller automation"
                elif r.automation_id:
                    r.entity_state_id = r.automation_id if r.automation_id.startswith("automation.") else f"automation.{r.automation_id}"
        else:
            for r in rules:
                if r.automation_id and not r.entity_state_id:
                    r.entity_state_id = r.automation_id if r.automation_id.startswith("automation.") else f"automation.{r.automation_id}"
        self.rules = rules
        self._apply_controller_flags(states)
        self._rules_at = now
        await self._sync_tracked_automations(configs, rules)
        return rules

    async def _sync_tracked_automations(self, configs: list[dict[str, Any]], rules: list[AutomationRule]) -> None:
        """Keep tracked brain-created automation records aligned with manual edits made in Home Assistant."""
        if self.memory is None:
            return
        try:
            accepted = await self.memory.get_accepted_automations()
        except Exception as exc:
            logger.debug("Could not read accepted automations for live sync: %s", exc)
            return
        if not accepted:
            return
        cfg_by_id = {str(c.get("id") or ""): c for c in configs if isinstance(c, dict) and c.get("id")}
        rule_by_id = {r.automation_id: r for r in rules if r.automation_id}
        for ep in accepted:
            data = dict(ep.service_data or {})
            aid = str(data.get("automation_id") or "")
            cfg = cfg_by_id.get(aid)
            if not aid or cfg is None:
                continue
            rule = rule_by_id.get(aid)
            raw_alias = str(cfg.get("alias") or data.get("alias") or aid).strip()
            stripped = strip_brain_prefix(raw_alias) or raw_alias
            old_alias = str(data.get("alias") or "")
            alias = clean_alias(raw_alias) if old_alias.lower().startswith("[ai brain]") and raw_alias.lower().startswith("[ai brain]") else stripped
            trigger = _listify(cfg.get("trigger") if "trigger" in cfg else cfg.get("triggers"))
            condition = _listify(cfg.get("condition") if "condition" in cfg else cfg.get("conditions"))
            action = _listify(cfg.get("action") if "action" in cfg else cfg.get("actions"))
            new_data = {
                **data,
                "alias": alias,
                "trigger": trigger,
                "condition": condition,
                "action": action,
            }
            if cfg.get("description") is not None:
                new_data["description"] = str(cfg["description"])
            if cfg.get("mode"):
                new_data["mode"] = str(cfg["mode"])
            resolved_targets = rule.targets() if rule is not None else []
            if not resolved_targets:
                try:
                    resolved_targets = NativeAutomationProposal.model_validate(new_data).extract_target_entities()
                except Exception:
                    resolved_targets = [t for t in ep.target_entity_ids if t != f"automation.{aid}"]
            auto_eid = f"automation.{aid}"
            existing_non_auto = [t for t in ep.target_entity_ids if t != auto_eid]
            if set(resolved_targets) == set(existing_non_auto):
                new_targets = list(ep.target_entity_ids)
            else:
                new_targets = ([auto_eid] if auto_eid in ep.target_entity_ids else []) + [t for t in resolved_targets if t != auto_eid]
            if new_data != data or new_targets != ep.target_entity_ids:
                await self.memory.save_feedback(
                    ep.model_copy(update={"service_data": new_data, "target_entity_ids": new_targets})
                )

    def equivalent_rule(self, proposal: NativeAutomationProposal) -> str | None:
        return find_equivalent_rule(
            self.rules,
            {"alias": proposal.alias, "trigger": proposal.trigger, "condition": proposal.condition, "action": proposal.action},
            twins=self.twins,
        )

    # --------------------------------------------------------------- patterns
    async def get_patterns(
        self,
        now: datetime,
        states: dict[str, EntityState] | None = None,
        force: bool = False,
    ) -> list[MinedPattern]:
        """Mined habits, minus the ones the homeowner rejected (they are never shown, proposed or given to an agent)."""
        if not force and self._patterns_at and (now - self._patterns_at).total_seconds() < PATTERN_CACHE_MINUTES * 60:
            return await self._without_rejected(self._patterns, now)
        win = await self.window(now)  # also flushes buffered writes
        if not win:
            return []
        start = max(win[0], now - timedelta(days=MINING_WINDOW_DAYS))
        transitions = await self.telemetry.get_transitions(since=start)
        fires = [
            f for f in await self.telemetry.get_all_fires(since=start) if not self.is_controller_automation(f.entity_id)
        ]  # autonomous automation / script runs: hidden causes, never habits themselves (wall-panel/controller sync runs excluded)
        twin_map = self.twins
        if twin_map:  # one physical device exposed twice: merge its history so it is mined as one device
            transitions = await asyncio.to_thread(canonicalize_transitions, transitions, twin_map)
        patterns, report = await asyncio.to_thread(mine_all_report, transitions, start, win[1], self.tz, fires)
        suppressed = list(report.suppressed)
        if states is not None:
            self._habit_names = {eid: str(st.attributes.get("friendly_name") or "") for eid, st in states.items()}
            patterns = [p for p in patterns if p.entity_id in states]
            twin_seqs = [p for p in patterns if self._is_twin_sequence(p, states)]
            patterns = [p for p in patterns if p not in twin_seqs]
            suppressed += [
                SuppressedHabit(
                    RULE_TWIN, p.trigger_entity or "", p.trigger_state or "", p.entity_id, p.to_state, p.support_days, p.confidence,
                    f"{p.trigger_entity} and {p.entity_id} have the same name and type: one device exposed twice, not a habit.",
                )
                for p in twin_seqs
            ]
        self._suppressed = [s.to_dict() for s in sorted(suppressed, key=lambda s: (s.confidence, s.hits), reverse=True)[:SUPPRESSED_LIST_MAX]]
        self._suppression_stats = {
            "suppressed_total": len(suppressed),
            "ignored_automated_triggers": report.ignored_automated_triggers,
            "ignored_burst_transitions": report.ignored_burst_transitions,
        }
        for p in patterns:
            p.covered_by = pattern_covered_by(self.rules, p, twins=twin_map)
        self._patterns, self._patterns_at = patterns, now
        return await self._without_rejected(patterns, now)

    # ------------------------------------------------------- rejected habits
    async def _load_rejected_habits(self) -> dict[str, RejectedHabit]:
        if self._rejected_habits is None:
            loaded: dict[str, RejectedHabit] = {}
            if self.memory is not None:
                for raw in (await self.memory.list_kv(REJECTED_HABIT_PREFIX)).values():
                    try:
                        r = RejectedHabit.model_validate_json(raw)
                    except ValueError:
                        continue
                    loaded[r.rejection_id] = r
            self._rejected_habits = loaded
        return self._rejected_habits

    async def _without_rejected(self, patterns: list[MinedPattern], now: datetime | None = None) -> list[MinedPattern]:
        rejected = await self._load_rejected_habits()
        kept, self._rejected_seen = split_rejected(patterns, list(rejected.values()), self._habit_names, self.twins.canonical, now=now)
        return kept

    async def reject_habit(self, pattern_id: str, now: datetime, states: dict[str, EntityState] | None = None) -> RejectedHabit:
        """The homeowner says a found habit is not real. Raises KeyError when it is not (or no longer) in the list."""
        pattern = next((p for p in await self.get_patterns(now, states) if p.pattern_id == pattern_id), None)
        if pattern is None:
            raise KeyError(pattern_id)
        rejected = RejectedHabit.from_pattern(pattern, now)
        rejected.status = "rejected"
        if not await self.save_rejected_habit(rejected):
            raise ValueError(f"You already rejected {MAX_REJECTED_HABITS} habits. Delete some old rejections first.")
        self._rejected_seen.add(rejected.rejection_id)
        return rejected

    async def save_rejected_habit(self, rejected: RejectedHabit) -> bool:
        """Store a rejection or deletion (also used by import). Same id replaces; the list is bounded."""
        current = await self._load_rejected_habits()
        if rejected.rejection_id not in current and len(current) >= MAX_REJECTED_HABITS:
            return False
        current[rejected.rejection_id] = rejected
        if self.memory is not None:
            await self.memory.set_kv(REJECTED_HABIT_PREFIX + rejected.rejection_id, rejected.model_dump_json())
        return True

    async def restore_rejected_habit(self, rejection_id: str) -> bool:
        """Undo a rejection: the habit returns to found habits."""
        current = await self._load_rejected_habits()
        if current.pop(rejection_id, None) is None:
            return False
        self._rejected_seen.discard(rejection_id)
        if self.memory is not None:
            await self.memory.delete_kv(REJECTED_HABIT_PREFIX + rejection_id)
        return True

    async def delete_rejected_habit(self, rejection_id: str, now: datetime | None = None) -> bool:
        """The homeowner deletes a habit: it is removed from rejected habits and suppressed from found habits."""
        now = now or datetime.now(timezone.utc)
        current = await self._load_rejected_habits()
        habit = current.get(rejection_id)
        if habit is None or habit.status != "rejected":
            return False
        habit.status = "deleted"
        habit.deleted_at = now
        self._rejected_seen.discard(rejection_id)
        if self.memory is not None:
            await self.memory.set_kv(REJECTED_HABIT_PREFIX + rejection_id, habit.model_dump_json())
        return True

    async def forget_rejected_habit(self, rejection_id: str) -> bool:
        """Deprecated alias for restore_rejected_habit."""
        return await self.restore_rejected_habit(rejection_id)

    async def list_rejected_habits(self) -> list[RejectedHabit]:
        current = await self._load_rejected_habits()
        return sorted(current.values(), key=lambda r: r.rejected_at.isoformat() if r.rejected_at else "", reverse=True)

    async def rejected_habit_cards(self) -> list[dict[str, Any]]:
        """For the dashboard; only active rejections (status == 'rejected'). `still_detected` reflects the last mining."""
        active = [r for r in await self.list_rejected_habits() if r.status == "rejected"]
        return [rejected_habit_card(r, r.rejection_id in self._rejected_seen) for r in active]

    # ------------------------------------------------------------ twin devices
    TWIN_SPLITS_KEY = "twin_splits"
    TWIN_REFRESH_SECONDS = 300

    async def refresh_twins(self, states: dict[str, EntityState], now: datetime | None = None, force: bool = False) -> TwinMap:
        """Recognise one physical device exposed by two integrations from the device registry (serial number + manufacturer)."""
        now = now or datetime.now(timezone.utc)
        if not force and self._twins_at and (now - self._twins_at).total_seconds() < self.TWIN_REFRESH_SECONDS:
            return self.twins
        try:
            facts = await self.smart_home.get_entity_device_facts()
        except Exception as exc:  # the registry is optional: without it nothing is merged
            logger.warning("Could not read device registry facts for twin detection: %s", exc)
            facts = []
        self._device_by_entity = {f.entity_id: f.device_id for f in facts if getattr(f, "entity_id", "") and getattr(f, "device_id", "")}
        prefs = await self.memory.get_ui_preferences() if self.memory is not None else {}
        twins = build_twin_map(facts, states, load_splits(prefs.get(self.TWIN_SPLITS_KEY)))
        before = {(g.group_id, g.canonical) for g in self.twins.groups}
        if {(g.group_id, g.canonical) for g in twins.groups} != before:
            self._patterns_at = None  # habits must be re-mined with the new grouping
            self._snapshot = None
            if twins:
                logger.info("Twin devices: %s", "; ".join(f"{g.canonical} <- {', '.join(m for m in g.members if m != g.canonical)}" for g in twins.groups))
        self.twins, self._twins_at = twins, now
        return twins

    def _one_finding_per_twin_group(self, findings: list[ExceptionFinding]) -> list[ExceptionFinding]:
        """The same device seen twice must not raise the same alert twice: keep the canonical entity's, else the first."""
        if not self.twins:
            return findings
        kept: dict[tuple[str, str], ExceptionFinding] = {}
        out: list[ExceptionFinding] = []
        for f in findings:
            group = self.twins.group_of(f.entity_id)
            if group is None:
                out.append(f)
                continue
            key = (f.kind, group.group_id)
            current = kept.get(key)
            if current is None:
                kept[key] = f
                out.append(f)
            elif f.entity_id == group.canonical and current.entity_id != group.canonical:
                out[out.index(current)] = f
                kept[key] = f
        return out

    def twin_groups(self) -> list[dict[str, Any]]:
        return [{**g.to_dict(), "reason": reason_for_card(g)} for g in self.twins.groups]

    async def set_twin_split(self, group_id: str, split: bool) -> None:
        """The homeowner says a detected group is not one device (or undoes that)."""
        if self.memory is None:
            return
        prefs = await self.memory.get_ui_preferences()
        splits = load_splits(prefs.get(self.TWIN_SPLITS_KEY))
        (splits.add if split else splits.discard)(group_id)
        await self.memory.save_ui_preference(self.TWIN_SPLITS_KEY, dump_splits(splits))
        self._twins_at = None
        self._patterns_at = None
        self._snapshot = None

    async def twin_splits(self) -> list[str]:
        prefs = await self.memory.get_ui_preferences() if self.memory is not None else {}
        return sorted(load_splits(prefs.get(self.TWIN_SPLITS_KEY)))

    def suppressed_habits(self) -> dict[str, Any]:
        """Relations that looked like habits but were dropped (shared trigger, same clock time, ...), with the reason. For the dashboard."""
        return {"items": self._suppressed, **self._suppression_stats}

    @staticmethod
    def _is_twin_sequence(pattern: MinedPattern, states: dict[str, EntityState]) -> bool:
        """A 'sequence' between two entities with the same name and type is one device exposed twice, not a routine."""
        if pattern.kind != "sequence" or not pattern.trigger_entity:
            return False
        a, b = states.get(pattern.trigger_entity), states.get(pattern.entity_id)
        if a is None or b is None or a.domain != b.domain:
            return False
        na, nb = str(a.attributes.get("friendly_name") or "").strip().lower(), str(b.attributes.get("friendly_name") or "").strip().lower()
        return bool(na) and na == nb

    # ---------------------------------------------------------------- context
    async def household(self, states: dict[str, EntityState], now: datetime) -> dict[str, Any]:
        forecast: list[dict[str, Any]] = []
        weather = next((s for s in states.values() if s.domain == "weather"), None)
        if weather is not None:
            if self._forecast and (now - self._forecast[0]).total_seconds() < 1800:
                forecast = self._forecast[1]
            else:
                try:
                    forecast = await self.smart_home.get_weather_forecast(weather.entity_id, "hourly")
                except Exception:
                    forecast = []
                self._forecast = (now, forecast)
        return build_household_context(states, now, self.tz, forecast)

    # -------------------------------------------------------------- baselines
    async def numeric_baseline(self, entity_id: str, now: datetime) -> NumericBaseline:
        cached = self._numeric_baselines.get(entity_id)
        if cached and (now - cached[0]).total_seconds() < 1800:
            return cached[1]
        await self.flush()
        rows = await self.telemetry.get_numeric_hours(entity_id, since=now - timedelta(days=60))
        baseline = NumericBaseline(rows, self.tz)
        self._numeric_baselines[entity_id] = (now, baseline)
        if len(self._numeric_baselines) > 500:
            self._numeric_baselines.pop(next(iter(self._numeric_baselines)))
        return baseline

    async def timeline_for(self, entity_ids: list[str], now: datetime, days: int = 45) -> Timeline:
        await self.flush()
        transitions = await self.telemetry.get_transitions(since=now - timedelta(days=days), entity_ids=entity_ids or None)
        return Timeline(transitions)

    # ----------------------------------------------------------------- gating
    async def should_wake_agent(self, frame: SemanticEventFrame, now: datetime) -> tuple[bool, str]:
        """Decide whether a significant event deserves an LLM call. Returns (wake, reason-if-skipped)."""
        if not self.settings.realtime_gating:
            return True, ""
        if frame.significance_reason.startswith("Exception:") or frame.target_agent_id == "repair_diagnostics_agent":
            return True, ""
        if not frame.trigger_events:
            return True, ""
        ev = frame.trigger_events[0]
        st = ev.new_state
        if is_safety_entity(st) or (st.device_class or "") in SECURITY_DEVICE_CLASSES:
            return True, ""
        if not await self.baseline_ready(now):
            if not self.settings.use_simulator or await self.telemetry.get_meta("observed_since") is not None:
                return False, f"Learning baseline not ready yet (< {self.settings.baseline_min_days}d of history)"
            return True, ""

        if st.domain == "sensor" and st.numeric_value is not None:
            z = (await self.numeric_baseline(st.entity_id, now)).zscore(st.numeric_value, ev.timestamp)
            if z is None:
                if not self.settings.use_simulator or await self.telemetry.get_meta("observed_since") is not None:
                    return False, f"{st.entity_id} has no hourly baseline yet (learning normal range)"
                return True, ""
            if abs(z) < 2.5:
                return False, f"{st.entity_id} is typical for this time of day (z={z:+.1f})"
            return True, ""

        if st.domain in ACTUATOR_DOMAINS:
            covered = next(
                (
                    r.alias
                    for r in self.rules
                    if rule_produces_state(r, st.entity_id, st.state, twins=self.twins)
                ),
                None,
            )
            if covered:
                return False, f"{st.entity_id} -> '{st.state}' is already handled by automation '{covered}'"
            if ev.origin.value == "human_or_physical":
                tl = await self.timeline_for([st.entity_id], now)
                win = await self.window(now)
                learned = expected_state_now(tl, st.entity_id, ev.timestamp, self.tz, win[0]) if win else None
                if learned and learned[2] >= 3 and learned[1] >= 0.8 and learned[0] == st.state:
                    return False, f"{st.entity_id} -> '{st.state}' is a routine for this hour ({learned[1]:.0%} of {learned[2]} days)"
        return True, ""

    # ------------------------------------------------------------- exceptions
    async def _learned_snapshot(self, now: datetime) -> LearnedSnapshot:
        snap = self._snapshot
        if snap is not None and (now - snap.built_at).total_seconds() < SNAPSHOT_MINUTES * 60:
            return snap
        since = now - timedelta(days=45)
        win = await self.window(now)
        start = max(win[0], since) if win else since
        # A script run is a momentary event and attribute tokens (`temp:...`, `preset:...`) are sub-channels:
        # keep them out of primary `.state` dwell / routine statistics.
        transitions = [
            t for t in await self.telemetry.get_transitions(since=since)
            if t.new_state != SCRIPT_RUN_STATE and not is_attribute_state(t.new_state)
        ]
        if self.twins:
            transitions = canonicalize_transitions(transitions, self.twins)
        rows = await self.telemetry.get_all_numeric_hours(since=since)
        tz = self.tz

        def build() -> tuple[Timeline, dict[str, DiscreteProfile], dict[str, NumericBaseline]]:
            return (
                Timeline(transitions),
                build_discrete_profiles(transitions, start, now),
                {eid: NumericBaseline(r, tz) for eid, r in rows.items()},
            )

        timeline, profiles, baselines = await asyncio.to_thread(build)
        self._snapshot = LearnedSnapshot(now, timeline, profiles, rows, baselines)
        return self._snapshot

    # ------------------------------------------------- learning from dismissals
    async def load_exception_feedback(self) -> None:
        if self.memory is None:
            return
        self._exception_feedback = {}
        for key, raw in (await self.memory.list_kv(FEEDBACK_PREFIX)).items():
            try:
                self._exception_feedback[key[len(FEEDBACK_PREFIX):]] = json.loads(raw)
            except ValueError:
                continue

    async def record_exception_feedback(self, feedback_key: str, *, rejected: bool) -> None:
        """A dismissed alert widens that entity's quiet period (x2 each time); a rejected one mutes it until unblocked."""
        fb = self._exception_feedback.setdefault(feedback_key, {"dismissed": 0, "muted": False})
        if rejected:
            fb["muted"] = True
        else:
            fb["dismissed"] = int(fb.get("dismissed", 0)) + 1
        if self.memory is not None:
            await self.memory.set_kv(FEEDBACK_PREFIX + feedback_key, json.dumps(fb))

    async def unmute_exception(self, feedback_key: str) -> None:
        self._exception_feedback.pop(feedback_key, None)
        if self.memory is not None:
            await self.memory.delete_kv(FEEDBACK_PREFIX + feedback_key)

    def muted_exceptions(self) -> list[str]:
        return sorted(k for k, v in self._exception_feedback.items() if v.get("muted"))

    def _cooldown(self, finding: ExceptionFinding) -> timedelta:
        dismissed = int(self._exception_feedback.get(finding.feedback_key, {}).get("dismissed", 0))
        return timedelta(hours=min(EXCEPTION_COOLDOWN_HOURS * (2 ** min(dismissed, 6)), 14 * 24))

    # ------------------------------------------------------------- exceptions
    async def detect_exceptions(
        self,
        states: dict[str, EntityState],
        now: datetime,
        household: dict[str, Any] | None = None,
    ) -> list[ExceptionFinding]:
        """
        Run every detector. Nothing is tied to particular devices: what is 'normal' is learned per entity,
        and only the *severity* depends on whether the entity is safety relevant.
        """
        findings: list[ExceptionFinding] = []
        findings += find_security_while_away(states, now)
        findings += find_missed_automations(rule_expectations(self.rules), states, now, self.tz)
        findings += find_stuck_unavailable(states, now, self.tz)
        if await self.baseline_ready(now):
            win = await self.window(now)
            snap = await self._learned_snapshot(now)
            recent = [
                t for t in await self.telemetry.get_transitions(since=now - timedelta(hours=1))
                if t.new_state != SCRIPT_RUN_STATE and not is_attribute_state(t.new_state)
            ]
            if self.twins:
                recent = canonicalize_transitions(recent, self.twins)
            snap.timeline.extend(recent)
            min_days = self.settings.baseline_min_days
            if win:
                findings += find_routine_deviations(
                    states, snap.timeline, now, self.tz, win[0],
                    min_days=min_days, profiles=snap.profiles, household=household,
                    rules=self.rules, twins=self.twins,
                )
            findings += find_dwell_anomalies(
                states, snap.profiles, now, self.tz, household,
                tl=snap.timeline, rules=self.rules, twins=self.twins, min_days=min_days,
            )
            findings += find_silent_entities(states, snap.profiles, now, self.tz, household)
            recent_counts = Counter(t.entity_id for t in recent)
            findings += find_flapping(dict(recent_counts), states, snap.profiles, now, self.tz, household, min_days=min_days)
            findings += find_numeric_anomalies(states, snap.numeric_rows, snap.baselines, now, self.tz, household, min_days=min_days)

        findings = self._one_finding_per_twin_group(findings)
        findings = collapse_device_findings(findings, self._device_by_entity)
        allowed: list[ExceptionFinding] = []
        for f in findings:
            if self._exception_feedback.get(f.feedback_key, {}).get("muted"):
                continue
            last = self._reported.get(f.dedupe_key)
            if last and (now - last) < self._cooldown(f):
                continue
            allowed.append(f)

        ranked = prioritise(allowed, household, limit=self.settings.max_exceptions_per_cycle)
        day = now.date().isoformat()
        used = self._daily_exceptions[1] if self._daily_exceptions[0] == day else 0
        fresh: list[ExceptionFinding] = []
        for f in ranked:
            if f.severity != "critical":
                if used >= self.settings.max_exceptions_per_day:
                    continue
                used += 1
            fresh.append(f)
        self._daily_exceptions = (day, used)
        return fresh

    def mark_reported(self, finding: ExceptionFinding, now: datetime) -> None:
        self._reported[finding.dedupe_key] = now
        for other_id in finding.also_entities:
            self._reported[finding.dedupe_key_for(other_id)] = now
        while len(self._reported) > 500:
            self._reported.pop(next(iter(self._reported)))

    # --------------------------------------------------------------- backtest
    async def backtest(self, proposal: NativeAutomationProposal, now: datetime) -> BacktestResult:
        win = await self.window(now)
        if not win:
            return BacktestResult(verdict="unverifiable", summary="No history recorded yet.")
        start = max(win[0], now - timedelta(days=MINING_WINDOW_DAYS))
        transitions = await self.telemetry.get_transitions(since=start)
        return await asyncio.to_thread(backtest_automation, proposal, transitions, start, win[1], self.tz)
