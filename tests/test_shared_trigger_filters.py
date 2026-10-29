"""Sequence habits must not be mined when the devices only share a hidden trigger (same automation trigger, scene, clock time)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from ha_ai_brain.domain.models import Transition
from ha_ai_brain.domain.patterns import mine_all_report, mine_sequences_report
from ha_ai_brain.domain.sequence_filters import (
    RULE_FAN_OUT,
    RULE_SAME_TIME,
    RULE_SHARED_CAUSE,
    find_burst_transitions,
)
from ha_ai_brain.ports.telemetry import AUTOMATION_FIRE_STATE

START = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
END = START + timedelta(days=12)
DAYS = range(10)


def at(d: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return START + timedelta(days=d, hours=hour - 8, minutes=minute, seconds=second)


def irregular(d: int) -> datetime:
    """A human-like, irregular time of day (not a clock time, not a smooth drift)."""
    return at(d, 17) + timedelta(minutes=(d * 37) % 150)


def run(transitions: list[Transition]):
    return mine_sequences_report(transitions, START, END)


def pairs(patterns) -> set[tuple[str | None, str]]:
    return {(p.trigger_entity, p.entity_id) for p in patterns}


def rules(report) -> set[str]:
    return {s.rule for s in report.suppressed}


class SharedCauseTests(unittest.TestCase):
    def sunset_home(self, with_automation_runs: bool) -> list[Transition]:
        """Three unrelated automations on one trigger (sunset-like, drifting ~1.5 min/day): their lights switch on within a minute."""
        t: list[Transition] = []
        for d in DAYS:
            base = at(d, 17, 30) + timedelta(seconds=90 * d)
            for i, light in enumerate(("light.porch", "light.garden", "light.hall")):
                if with_automation_runs:
                    t.append(Transition(f"automation.dusk_{i}", base + timedelta(seconds=i * 7), "", AUTOMATION_FIRE_STATE, "ha_automation"))
                t.append(Transition(light, base + timedelta(seconds=20 + i * 15), "off", "on", "human_or_physical"))  # origin missed
        return t

    def test_unrelated_automations_on_one_trigger_are_not_a_habit(self) -> None:
        patterns, report = run(self.sunset_home(with_automation_runs=True))
        self.assertEqual(pairs(patterns), set())
        self.assertTrue(report.suppressed)
        self.assertTrue(rules(report) <= {RULE_SHARED_CAUSE, RULE_SAME_TIME, RULE_FAN_OUT})

    def test_shared_cause_is_named_when_an_automation_run_precedes_both(self) -> None:
        t: list[Transition] = []
        for d in DAYS:
            base = irregular(d)  # irregular, so the time-of-day rule cannot be what explains it
            t.append(Transition("automation.evening", base, "", AUTOMATION_FIRE_STATE, "ha_automation"))
            t.append(Transition("light.porch", base + timedelta(seconds=10), "off", "on"))
            t.append(Transition("cover.hall", base + timedelta(seconds=40), "open", "closed"))
        patterns, report = run(t)
        self.assertNotIn(("light.porch", "cover.hall"), pairs(patterns))
        cause = [s for s in report.suppressed if s.rule == RULE_SHARED_CAUSE]
        self.assertTrue(cause)
        self.assertEqual(cause[0].details["cause_entity"], "automation.evening")
        self.assertIn("share a trigger", cause[0].reason)

    def test_same_pair_without_a_hidden_cause_is_kept(self) -> None:
        t: list[Transition] = []
        for d in DAYS:
            base = irregular(d)
            t += [Transition("light.porch", base, "off", "on"), Transition("cover.hall", base + timedelta(seconds=40), "open", "closed")]
        patterns, report = run(t)
        self.assertIn(("light.porch", "cover.hall"), pairs(patterns))
        self.assertFalse(report.suppressed)

    def test_pair_that_also_holds_without_the_cause_is_kept(self) -> None:
        t: list[Transition] = []
        for d in DAYS:
            base = irregular(d)
            if d % 2 == 0:  # on half the days an automation runs first ...
                t.append(Transition("automation.evening", base - timedelta(seconds=5), "", AUTOMATION_FIRE_STATE, "ha_automation"))
            # ... but the person does the same thing on all days
            t += [Transition("light.porch", base, "off", "on"), Transition("cover.hall", base + timedelta(seconds=40), "open", "closed")]
        patterns, _ = run(t)
        self.assertIn(("light.porch", "cover.hall"), pairs(patterns))


class TimeAnchorTests(unittest.TestCase):
    def test_two_fixed_time_events_are_separate_time_habits(self) -> None:
        t: list[Transition] = []
        for d in DAYS:
            t += [Transition("light.porch", at(d, 18, 0), "off", "on"), Transition("cover.hall", at(d, 18, 1), "open", "closed")]
        patterns, report = run(t)
        self.assertEqual(pairs(patterns), set())
        self.assertEqual(rules(report), {RULE_SAME_TIME})
        self.assertIn("two separate time habits", report.suppressed[0].reason)

    def test_time_habits_themselves_are_still_mined(self) -> None:
        t: list[Transition] = []
        for d in DAYS:
            t += [Transition("light.porch", at(d, 18, 0), "off", "on"), Transition("cover.hall", at(d, 18, 1), "open", "closed")]
        patterns, _ = mine_all_report(t, START, END, timezone.utc)
        self.assertEqual({p.entity_id for p in patterns if p.kind == "time_habit"}, {"light.porch", "cover.hall"})


class FanOutAndBurstTests(unittest.TestCase):
    def test_one_trigger_followed_by_many_devices_is_not_a_chain(self) -> None:
        t: list[Transition] = []
        for d in DAYS:
            base = irregular(d)
            t.append(Transition("binary_sensor.entry", base, "off", "on", "sensor_telemetry"))
            for i, light in enumerate(("light.a", "light.b", "light.c", "light.d")):
                t.append(Transition(light, base + timedelta(seconds=60 * (i + 1)), "off", "on"))
        patterns, report = run(t)
        self.assertEqual(pairs(patterns), set())
        self.assertEqual(rules(report), {RULE_FAN_OUT})

    def test_scripted_burst_is_ignored(self) -> None:
        t: list[Transition] = []
        for d in DAYS:
            base = irregular(d)
            t.append(Transition("binary_sensor.entry", base - timedelta(seconds=30), "off", "on", "sensor_telemetry"))
            for i, light in enumerate(("light.a", "light.b", "light.c", "light.d", "light.e")):
                t.append(Transition(light, base + timedelta(seconds=i), "off", "on"))
        patterns, report = run(t)
        self.assertEqual(pairs(patterns), set())
        self.assertGreaterEqual(report.ignored_burst_transitions, 5 * len(DAYS))

    def test_burst_detection_needs_several_devices(self) -> None:
        t = [Transition("light.a", at(0, 18), "off", "on"), Transition("light.b", at(0, 18, 0, 2), "off", "on"), Transition("light.a", at(0, 18, 0, 3), "on", "off")]
        self.assertEqual(find_burst_transitions(t, lambda _t: True), set())

    def test_automated_trigger_is_not_a_human_action_to_react_to(self) -> None:
        t: list[Transition] = []
        for d in DAYS:
            base = irregular(d)
            t += [Transition("light.porch", base, "off", "on", "ha_automation"), Transition("cover.hall", base + timedelta(seconds=40), "open", "closed")]
        patterns, report = run(t)
        self.assertEqual(pairs(patterns), set())
        self.assertEqual(report.ignored_automated_triggers, len(DAYS))


class ScriptRunTests(unittest.IsolatedAsyncioTestCase):
    def script_home(self) -> tuple[list[Transition], list[Transition]]:
        """A script that moves two devices 25 s apart: too slow for a burst, too small for fan-out."""
        moves: list[Transition] = []
        runs: list[Transition] = []
        for d in DAYS:
            base = irregular(d)
            runs.append(Transition("script.movie_mode", base, "", AUTOMATION_FIRE_STATE, "ha_automation"))
            moves += [Transition("light.lounge", base + timedelta(seconds=5), "on", "off"),
                      Transition("cover.lounge_blind", base + timedelta(seconds=30), "open", "closed")]
        return moves, runs

    def test_without_the_script_run_a_small_script_looks_like_a_habit(self) -> None:
        moves, _ = self.script_home()
        patterns, _ = mine_sequences_report(moves, START, END)
        self.assertIn(("light.lounge", "cover.lounge_blind"), pairs(patterns))

    def test_script_run_is_named_as_the_shared_cause(self) -> None:
        moves, runs = self.script_home()
        patterns, report = mine_sequences_report(moves, START, END, cause_events=runs)
        self.assertEqual(pairs(patterns), set())
        self.assertEqual(report.suppressed[0].details["cause_entity"], "script.movie_mode")

    async def test_store_returns_runs_and_learning_records_script_runs(self) -> None:
        from ha_ai_brain.adapters.telemetry_sqlite import SQLiteTelemetryStore
        from ha_ai_brain.domain.models import EntityState, StateChangedEvent

        store = SQLiteTelemetryStore(":memory:")
        _, runs = self.script_home()
        await store.record_transitions(runs)
        got = await store.get_all_fires()
        self.assertEqual([(t.entity_id, t.ts) for t in got], [(t.entity_id, t.ts) for t in runs])
        self.assertEqual(await store.get_transitions(), [])

        from ha_ai_brain.application.learning import LearningEngine
        engine = LearningEngine.__new__(LearningEngine)
        engine._tr_buffer, engine._num_buffer = [], {}
        engine._last_flush = 10**12
        ts = START + timedelta(hours=3)
        old = EntityState(entity_id="script.movie_mode", state="off", attributes={})
        new = EntityState(entity_id="script.movie_mode", state="on", attributes={"last_triggered": ts.isoformat()})
        await engine.record_event(StateChangedEvent(entity_id="script.movie_mode", old_state=old, new_state=new, timestamp=ts))
        self.assertEqual(
            [(t.entity_id, t.new_state) for t in engine._tr_buffer],
            [("script.movie_mode", AUTOMATION_FIRE_STATE), ("script.movie_mode", "run")],  # started by hand: also a habit candidate
        )


class SuppressionReportingTests(unittest.IsolatedAsyncioTestCase):
    async def test_learned_snapshot_exposes_suppressed_habits(self) -> None:
        import tempfile
        from pathlib import Path

        from ha_ai_brain.api.app import build_orchestrator
        from ha_ai_brain.config import BrainSettings

        with tempfile.TemporaryDirectory() as tmp:
            orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db")))
            snap = await orch.get_learned_snapshot()
        sup = snap["suppressed_habits"]
        self.assertEqual(sup["items"], [])
        self.assertTrue(isinstance(sup["items"], list))


if __name__ == "__main__":
    unittest.main()
