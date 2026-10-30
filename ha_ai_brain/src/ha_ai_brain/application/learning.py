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
    find_equivalent_rule,
    parse_automation_config,
    pattern_covered_by,
    resolve_rule_targets,
    rule_expectations,
    rule_produces_state,
)
from ha_ai_brain.domain.backtest import Timeline, backtest_automation
from ha_ai_brain.domain.baselines import NumericBaseline
from ha_ai_brain.domain.context import build_household_context
from ha_ai_brain.domain.anomaly import (
    DiscreteProfile,
    build_discrete_profiles,
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
from ha_ai_brain.domain.patterns import MinedPattern, mine_all_report
from ha_ai_brain.domain.sequence_filters import RULE_TWIN, SuppressedHabit
from ha_ai_brain.domain.service_semantics import ACTUATOR_DOMAINS, SCRIPT_RUN_STATE
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
FEEDBACK_PREFIX = "excfb:"


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
        self._patterns: list[MinedPattern] = []
        self._patterns_at: datetime | None = None
        self._baseline_ready_cache: tuple[datetime, bool] | None = None
        self._numeric_baselines: dict[str, tuple[datetime, NumericBaseline]] = {}
        self._reported: dict[str, datetime] = {}
        self._forecast: tuple[datetime, list[dict[str, Any]]] | None = None
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
    async def record_event(self, event: StateChangedEvent) -> None:
        """Queue the part of a live event that matters for learning (cheap, local); written in batches."""
        new = event.new_state
        old = event.old_state
        ts = ensure_utc(event.timestamp)
        if new.domain in ("automation", "script"):
            last = parse_iso(new.attributes.get("last_triggered"))
            prev_last = parse_iso(old.attributes.get("last_triggered")) if old else None
            if last is not None and last != prev_last:
                self._tr_buffer.append(Transition(new.entity_id, last, "", AUTOMATION_FIRE_STATE, "ha_automation"))
                if new.domain == "script" and event.origin.value == "human_or_physical":
                    # Started by hand (not by an automation or the brain): a habit candidate, like flipping a switch.
                    self._tr_buffer.append(Transition(new.entity_id, last, "off", SCRIPT_RUN_STATE, "human_or_physical", event.context_user_id))
        elif new.domain == "sensor":
            value = new.numeric_value
            if value is not None:
                agg = self._num_buffer.setdefault((new.entity_id, ts.replace(minute=0, second=0, microsecond=0)), [0, 0.0])
                agg[0] += 1
                agg[1] += value
        elif new.domain in RECORDED_DISCRETE_DOMAINS and old is not None and old.state != new.state:
            if new.state not in NON_STATES and old.state not in NON_STATES:
                self._tr_buffer.append(Transition(new.entity_id, ts, old.state, new.state, event.origin.value, event.context_user_id))
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
    async def refresh_rules(self, states: dict[str, EntityState] | None = None, force: bool = False) -> list[AutomationRule]:
        now = datetime.now(timezone.utc)
        if not force and self._rules_at and (now - self._rules_at).total_seconds() < 1800:
            return self.rules
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
        resolve_rule_targets(rules, states=states, facts=facts)
        if states:
            by_id = {str(s.attributes.get("id")): s for s in states.values() if s.domain == "automation" and s.attributes.get("id")}
            for r in rules:
                st = by_id.get(r.automation_id)
                if st is not None:
                    r.entity_state_id = st.entity_id
                    r.enabled = st.state != "off"
        self.rules = rules
        self._rules_at = now
        return rules

    def equivalent_rule(self, proposal: NativeAutomationProposal) -> str | None:
        return find_equivalent_rule(
            self.rules,
            {"alias": proposal.alias, "trigger": proposal.trigger, "condition": proposal.condition, "action": proposal.action},
        )

    # --------------------------------------------------------------- patterns
    async def get_patterns(
        self,
        now: datetime,
        states: dict[str, EntityState] | None = None,
        force: bool = False,
    ) -> list[MinedPattern]:
        if not force and self._patterns_at and (now - self._patterns_at).total_seconds() < PATTERN_CACHE_MINUTES * 60:
            return self._patterns
        win = await self.window(now)  # also flushes buffered writes
        if not win:
            return []
        start = max(win[0], now - timedelta(days=MINING_WINDOW_DAYS))
        transitions = await self.telemetry.get_transitions(since=start)
        fires = await self.telemetry.get_all_fires(since=start)  # automation / script runs: hidden causes, never habits themselves
        twins = self.twins
        if twins:  # one physical device exposed twice: merge its history so it is mined as one device
            transitions = await asyncio.to_thread(canonicalize_transitions, transitions, twins)
        patterns, report = await asyncio.to_thread(mine_all_report, transitions, start, win[1], self.tz, fires)
        suppressed = list(report.suppressed)
        if states is not None:
            patterns = [p for p in patterns if p.entity_id in states]
            twins = [p for p in patterns if self._is_twin_sequence(p, states)]
            patterns = [p for p in patterns if p not in twins]
            suppressed += [
                SuppressedHabit(
                    RULE_TWIN, p.trigger_entity or "", p.trigger_state or "", p.entity_id, p.to_state, p.support_days, p.confidence,
                    f"{p.trigger_entity} and {p.entity_id} have the same name and type: one device exposed twice, not a habit.",
                )
                for p in twins
            ]
        self._suppressed = [s.to_dict() for s in sorted(suppressed, key=lambda s: (s.confidence, s.hits), reverse=True)[:SUPPRESSED_LIST_MAX]]
        self._suppression_stats = {
            "suppressed_total": len(suppressed),
            "ignored_automated_triggers": report.ignored_automated_triggers,
            "ignored_burst_transitions": report.ignored_burst_transitions,
        }
        for p in patterns:
            p.covered_by = pattern_covered_by(self.rules, p, twins=twins)
        self._patterns, self._patterns_at = patterns, now
        return patterns

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
        if not frame.trigger_events or not await self.baseline_ready(now):
            return True, ""
        ev = frame.trigger_events[0]
        st = ev.new_state
        if is_safety_entity(st) or (st.device_class or "") in SECURITY_DEVICE_CLASSES:
            return True, ""

        if st.domain == "sensor" and st.numeric_value is not None:
            z = (await self.numeric_baseline(st.entity_id, now)).zscore(st.numeric_value, ev.timestamp)
            if z is not None and abs(z) < 2.5:
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
        # A script run is a momentary event, not a state the script stays in: keep it out of dwell / routine statistics.
        transitions = [t for t in await self.telemetry.get_transitions(since=since) if t.new_state != SCRIPT_RUN_STATE]
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
            recent = [t for t in await self.telemetry.get_transitions(since=now - timedelta(hours=1)) if t.new_state != SCRIPT_RUN_STATE]
            if self.twins:
                recent = canonicalize_transitions(recent, self.twins)
            snap.timeline.extend(recent)
            if win:
                findings += find_routine_deviations(
                    states, snap.timeline, now, self.tz, win[0],
                    min_days=self.settings.baseline_min_days, profiles=snap.profiles, household=household,
                    rules=self.rules, twins=self.twins,
                )
            findings += find_dwell_anomalies(
                states, snap.profiles, now, self.tz, household,
                tl=snap.timeline, rules=self.rules, twins=self.twins,
            )
            findings += find_silent_entities(states, snap.profiles, now, self.tz, household)
            recent_counts = Counter(t.entity_id for t in recent)
            findings += find_flapping(dict(recent_counts), states, snap.profiles, now, self.tz, household)
            findings += find_numeric_anomalies(states, snap.numeric_rows, snap.baselines, now, self.tz, household)

        findings = self._one_finding_per_twin_group(findings)
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
        if len(self._reported) > 500:
            self._reported.pop(next(iter(self._reported)))

    # --------------------------------------------------------------- backtest
    async def backtest(self, proposal: NativeAutomationProposal, now: datetime) -> BacktestResult:
        win = await self.window(now)
        if not win:
            return BacktestResult(verdict="unverifiable", summary="No history recorded yet.")
        start = max(win[0], now - timedelta(days=MINING_WINDOW_DAYS))
        transitions = await self.telemetry.get_transitions(since=start)
        return await asyncio.to_thread(backtest_automation, proposal, transitions, start, win[1], self.tz)
