"""Tests for the local learning engine: pattern mining, backtesting, exceptions, gating, undo and lifecycle."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ha_ai_brain.adapters.telemetry_sqlite import SQLiteTelemetryStore
from ha_ai_brain.api.app import build_orchestrator, create_app
from ha_ai_brain.config import AutonomyLevel, BrainSettings
from ha_ai_brain.domain.automation_rules import (
    RuleAction,
    RuleExpectation,
    find_equivalent_rule,
    is_state_automated,
    parse_automation_config,
    pattern_covered_by,
    resolve_rule_targets,
)
from ha_ai_brain.domain.backtest import Timeline, backtest_automation
from ha_ai_brain.domain.baselines import NumericBaseline
from ha_ai_brain.domain.expectations import (
    ExceptionFinding,
    find_missed_automations,
    find_routine_deviations,
    find_security_while_away,
)
from ha_ai_brain.domain.knowledge import select_knowledge
from ha_ai_brain.domain.lifecycle import review_deployed_automation
from ha_ai_brain.domain.models import (
    ActionIntent,
    EntityState,
    ExpectedOutcome,
    FeedbackEpisode,
    FeedbackPolarity,
    NativeAutomationProposal,
    Transition,
)
from ha_ai_brain.domain.outcomes import evaluate_outcome
from ha_ai_brain.domain.patterns import automation_from_pattern, mine_sequences, mine_time_habits
from ha_ai_brain.domain.privacy import PrivacyScrubber
from ha_ai_brain.domain.series import summarize_series
from ha_ai_brain.domain.timeutil import is_quiet_hours, parse_iso
from ha_ai_brain.domain.undo import build_undo_calls, capture_snapshot
from ha_ai_brain.application.agent_registry import get_builtin_agents
from ha_ai_brain.ports.telemetry import AUTOMATION_FIRE_STATE

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # a Wednesday


def at(days_ago: int, hour: int, minute: int = 0, base: datetime = NOW) -> datetime:
    return (base - timedelta(days=days_ago)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def nightly_light(entity: str = "light.living", days: int = 10, base: datetime = NOW) -> list[Transition]:
    out: list[Transition] = []
    for d in range(1, days + 1):
        out.append(Transition(entity, at(d, 18, 0, base), "off", "on", "human_or_physical"))
        out.append(Transition(entity, at(d, 23, d % 3 + 1, base), "on", "off", "human_or_physical"))
    return out


class TestPatternMining(unittest.TestCase):
    def test_time_habit_is_found_and_becomes_an_automation(self) -> None:
        trans = nightly_light()
        patterns = mine_time_habits(trans, NOW - timedelta(days=11), NOW, UTC)
        off = [p for p in patterns if p.to_state == "off"]
        self.assertEqual(len(off), 1)
        p = off[0]
        self.assertGreaterEqual(p.confidence, 0.85)
        self.assertAlmostEqual(p.minute_of_day, 23 * 60 + 2, delta=3)
        proposal = automation_from_pattern(p, {"light.living": "Living Room Light"})
        assert proposal is not None
        self.assertEqual(proposal.trigger[0]["platform"], "time")
        self.assertTrue(proposal.trigger[0]["at"].startswith("23:0"))
        self.assertEqual(proposal.action[0]["service"], "light.turn_off")
        self.assertEqual(proposal.source_pattern_id, p.pattern_id)

    def test_automated_and_ai_caused_transitions_are_not_human_habits(self) -> None:
        trans = [Transition(t.entity_id, t.ts, t.old_state, t.new_state, "ha_automation") for t in nightly_light()]
        self.assertEqual(mine_time_habits(trans, NOW - timedelta(days=11), NOW, UTC), [])

    def test_weekday_only_habit_is_not_turned_into_a_daily_rule(self) -> None:
        trans = []
        for d in range(1, 15):
            day = NOW - timedelta(days=d)
            if day.weekday() < 5:
                trans.append(Transition("switch.coffee", day.replace(hour=7, minute=d % 4), "off", "on", "human_or_physical"))
        patterns = mine_time_habits(trans, NOW - timedelta(days=15), NOW, UTC)
        self.assertTrue(patterns)
        self.assertEqual(patterns[0].day_class, "weekday")
        proposal = automation_from_pattern(patterns[0])
        assert proposal is not None
        self.assertEqual(proposal.condition[0]["weekday"], ["mon", "tue", "wed", "thu", "fri"])

    def test_unlock_is_never_proposed_as_automation(self) -> None:
        trans = [Transition("lock.front", at(d, 7, 0), "locked", "unlocked", "human_or_physical") for d in range(1, 11)]
        patterns = mine_time_habits(trans, NOW - timedelta(days=11), NOW, UTC)
        self.assertEqual(patterns, [])

    def test_sequence_with_statistical_lift_is_found(self) -> None:
        trans: list[Transition] = []
        for d in range(1, 11):
            t = at(d, 17, 0) + timedelta(minutes=(d * 37) % 150)  # irregular, human-like time (a fixed clock time is a time habit)
            trans.append(Transition("binary_sensor.motion", t, "on", "off", "sensor_telemetry"))
            trans.append(Transition("light.hall", t + timedelta(minutes=4), "on", "off", "human_or_physical"))
        seq = mine_sequences(trans, NOW - timedelta(days=11), NOW)
        self.assertTrue(seq)
        p = seq[0]
        self.assertEqual((p.trigger_entity, p.trigger_state, p.entity_id, p.to_state), ("binary_sensor.motion", "off", "light.hall", "off"))
        proposal = automation_from_pattern(p)
        assert proposal is not None
        self.assertEqual(proposal.trigger[0]["platform"], "state")
        self.assertEqual(proposal.trigger[0]["for"], "00:03:00")

    def test_presence_condition_added_when_switching_things_on(self) -> None:
        trans = [Transition("light.porch", at(d, 18, 0), "off", "on", "human_or_physical") for d in range(1, 11)]
        p = mine_time_habits(trans, NOW - timedelta(days=11), NOW, UTC)[0]
        proposal = automation_from_pattern(p, presence_entities=["person.a", "person.b"])
        assert proposal is not None
        self.assertEqual(proposal.condition[0]["condition"], "or")


class TestAutomationRules(unittest.TestCase):
    CONFIG = {
        "id": "abc",
        "alias": "Night off",
        "trigger": [{"platform": "time", "at": "23:00:00"}],
        "condition": [],
        "action": [{"service": "light.turn_off", "target": {"entity_id": "light.living"}}],
    }

    def test_old_and_new_style_configs_parse(self) -> None:
        old = parse_automation_config(self.CONFIG)
        new = parse_automation_config(
            {
                "id": "n",
                "alias": "New style",
                "triggers": [{"trigger": "time", "at": "07:30"}],
                "conditions": [{"condition": "time", "weekday": ["mon", "tue"]}],
                "actions": [{"action": "cover.open_cover", "target": {"entity_id": ["cover.a", "cover.b"]}}],
            }
        )
        self.assertEqual(old.time_triggers, [1380])
        self.assertEqual(old.targets(), ["light.living"])
        self.assertEqual(new.time_triggers, [450])
        self.assertEqual(new.weekdays, {0, 1})
        self.assertEqual(new.targets(), ["cover.a", "cover.b"])

    def test_coverage_and_equivalence(self) -> None:
        rule = parse_automation_config(self.CONFIG)
        pattern = mine_time_habits(nightly_light(), NOW - timedelta(days=11), NOW, UTC)[-1]
        off = next(p for p in mine_time_habits(nightly_light(), NOW - timedelta(days=11), NOW, UTC) if p.to_state == "off")
        self.assertEqual(pattern_covered_by([rule], off), "Night off")
        proposal = {"alias": "dup", "trigger": [{"platform": "time", "at": "23:10:00"}], "action": self.CONFIG["action"]}
        self.assertEqual(find_equivalent_rule([rule], proposal), "Night off")
        other = {"alias": "x", "trigger": [{"platform": "time", "at": "06:00:00"}], "action": self.CONFIG["action"]}
        self.assertIsNone(find_equivalent_rule([rule], other))

    def test_device_actions_parallel_and_target_resolution(self) -> None:
        from ha_ai_brain.domain.twins import EntityFacts

        cfg = {
            "id": "climate_dry",
            "alias": "Dehumidify study",
            "triggers": [{"trigger": "numeric_state", "entity_id": "sensor.study_humidity", "above": 60}],
            "actions": [
                {
                    "parallel": [
                        {"domain": "climate", "device_id": "dev_ac", "entity_id": "reg_ac_uuid", "type": "set_hvac_mode", "hvac_mode": "dry"},
                        {"action": "climate.turn_off", "target": {"area_id": "study"}},
                    ]
                }
            ],
        }
        rule = parse_automation_config(cfg)
        facts = [EntityFacts(entity_id="climate.study_ac", device_id="dev_ac", registry_id="reg_ac_uuid")]
        states = {"climate.study_heater": EntityState(entity_id="climate.study_heater", state="off", area_id="study")}
        resolve_rule_targets([rule], states=states, facts=facts)
        self.assertEqual(rule.targets(), ["climate.study_ac", "climate.study_heater"])
        self.assertTrue(is_state_automated("climate.study_ac", "dry", [rule], since=NOW - timedelta(minutes=30), now=NOW, tz=UTC))
        self.assertTrue(is_state_automated("climate.study_heater", "off", [rule], since=NOW - timedelta(minutes=30), now=NOW, tz=UTC))
        self.assertFalse(is_state_automated("climate.study_ac", "heat", [rule], since=NOW - timedelta(minutes=30), now=NOW, tz=UTC))


class TestBacktest(unittest.TestCase):
    def _proposal(self, at_time: str) -> NativeAutomationProposal:
        return NativeAutomationProposal(
            alias="t",
            description="",
            trigger=[{"platform": "time", "at": at_time}],
            action=[{"service": "light.turn_off", "target": {"entity_id": "light.living"}}],
        )

    def test_matching_habit_is_supported_and_mismatch_is_weak(self) -> None:
        trans = nightly_light()
        good = backtest_automation(self._proposal("23:00:00"), trans, NOW - timedelta(days=11), NOW, UTC)
        self.assertEqual(good.verdict, "supported")
        self.assertGreaterEqual(good.aligned, 8)
        bad = backtest_automation(self._proposal("20:00:00"), trans, NOW - timedelta(days=11), NOW, UTC)
        self.assertEqual(bad.verdict, "weak")

    def test_too_little_history_and_unreplayable_triggers_are_unverifiable(self) -> None:
        short = backtest_automation(self._proposal("23:00:00"), nightly_light(), NOW - timedelta(days=1), NOW, UTC)
        self.assertEqual(short.verdict, "unverifiable")
        numeric = NativeAutomationProposal(
            alias="n",
            description="",
            trigger=[{"platform": "numeric_state", "entity_id": "sensor.x", "above": 60}],
            action=[{"service": "light.turn_off", "target": {"entity_id": "light.living"}}],
        )
        res = backtest_automation(numeric, nightly_light(), NOW - timedelta(days=11), NOW, UTC)
        self.assertEqual(res.verdict, "unverifiable")
        self.assertTrue(res.approximate)

    def test_state_trigger_with_condition_is_replayed(self) -> None:
        trans = nightly_light()
        proposal = NativeAutomationProposal(
            alias="s",
            description="",
            trigger=[{"platform": "state", "entity_id": "light.living", "to": "on"}],
            condition=[{"condition": "time", "weekday": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}],
            action=[{"service": "light.turn_off", "target": {"entity_id": "light.living"}}],
        )
        res = backtest_automation(proposal, trans, NOW - timedelta(days=11), NOW, UTC)
        self.assertEqual(res.fires, 10)


class TestExceptions(unittest.TestCase):
    def _lock_timeline(self) -> Timeline:
        trans = []
        for d in range(1, 11):
            trans.append(Transition("lock.front_door", at(d, 7, 0), "locked", "unlocked", "human_or_physical"))
            trans.append(Transition("lock.front_door", at(d, 22, 0), "unlocked", "locked", "human_or_physical"))
        return Timeline(trans)

    def test_unlocked_at_night_is_a_critical_routine_deviation(self) -> None:
        now = NOW.replace(hour=3)
        lock = EntityState(entity_id="lock.front_door", state="unlocked", last_changed=now - timedelta(minutes=60))
        found = find_routine_deviations({lock.entity_id: lock}, self._lock_timeline(), now, UTC, NOW - timedelta(days=11))
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].severity, found[0].expected_state), ("critical", "locked"))
        recent = EntityState(entity_id="lock.front_door", state="unlocked", last_changed=now - timedelta(minutes=5))
        self.assertEqual(find_routine_deviations({recent.entity_id: recent}, self._lock_timeline(), now, UTC, NOW - timedelta(days=11)), [])

    def test_normal_daytime_unlocked_is_not_reported(self) -> None:
        now = NOW  # noon: the door is normally unlocked
        lock = EntityState(entity_id="lock.front_door", state="unlocked", last_changed=now - timedelta(hours=3))
        self.assertEqual(find_routine_deviations({lock.entity_id: lock}, self._lock_timeline(), now, UTC, NOW - timedelta(days=11)), [])

    def test_state_set_by_native_automation_or_rule_is_not_a_routine_deviation(self) -> None:
        trans: list[Transition] = []
        for d in range(1, 10):
            trans.append(Transition("climate.study_ac", at(d, 8, 0), "dry", "off", "human_or_physical"))
            trans.append(Transition("climate.study_heater", at(d, 8, 0), "off", "heat", "human_or_physical"))
        now = NOW.replace(hour=16, minute=42)
        changed = now - timedelta(minutes=33)
        ac = EntityState(entity_id="climate.study_ac", state="dry", last_changed=changed)
        heater = EntityState(entity_id="climate.study_heater", state="off", last_changed=changed)
        states = {ac.entity_id: ac, heater.entity_id: heater}

        # 1. Without an automation rule or automated transition origin, both deviate from the 9-day routine
        tl_manual = Timeline(trans + [
            Transition("climate.study_ac", changed, "off", "dry", "human_or_physical"),
            Transition("climate.study_heater", changed, "heat", "off", "human_or_physical"),
        ])
        self.assertEqual(len(find_routine_deviations(states, tl_manual, now, UTC, NOW - timedelta(days=10))), 2)

        # 2. When the transition into the current state came from ha_automation, it is not flagged
        tl_auto = Timeline(trans + [
            Transition("climate.study_ac", changed, "off", "dry", "ha_automation"),
            Transition("climate.study_heater", changed, "heat", "off", "ha_automation"),
        ])
        self.assertEqual(find_routine_deviations(states, tl_auto, now, UTC, NOW - timedelta(days=10)), [])

        # 3. Even if the hardware integration did not preserve event context (origin='human_or_physical'),
        #    an enabled HA automation rule that sets those states suppresses the false routine deviation
        rule = parse_automation_config(
            {
                "id": "study_dehumidify",
                "alias": "Study dehumidify",
                "trigger": [{"platform": "numeric_state", "entity_id": "sensor.study_humidity", "above": 60}],
                "action": [
                    {"service": "climate.set_hvac_mode", "target": {"entity_id": "climate.study_ac"}, "data": {"hvac_mode": "dry"}},
                    {"service": "climate.set_hvac_mode", "target": {"entity_id": "climate.study_heater"}, "data": {"hvac_mode": "off"}},
                ],
            }
        )
        self.assertEqual(
            find_routine_deviations(states, tl_manual, now, UTC, NOW - timedelta(days=10), rules=[rule]),
            [],
        )

        # 4. Safety entities (such as a lock unlocked at night) still alert even if an automation unlocked them
        night = NOW.replace(hour=3)
        lock_tl = self._lock_timeline()
        lock_tl.extend([Transition("lock.front_door", night - timedelta(minutes=60), "locked", "unlocked", "ha_automation")])
        lock = EntityState(entity_id="lock.front_door", state="unlocked", last_changed=night - timedelta(minutes=60))
        self.assertEqual(len(find_routine_deviations({lock.entity_id: lock}, lock_tl, night, UTC, NOW - timedelta(days=11))), 1)

    def test_security_while_away(self) -> None:
        person = EntityState(entity_id="person.a", state="not_home", last_changed=NOW - timedelta(minutes=40))
        lock = EntityState(entity_id="lock.front_door", state="unlocked", last_changed=NOW - timedelta(hours=2))
        garage = EntityState(entity_id="cover.garage_door", state="open", last_changed=NOW - timedelta(hours=2))
        found = find_security_while_away({s.entity_id: s for s in (person, lock, garage)}, NOW)
        self.assertEqual({f.entity_id for f in found}, {"lock.front_door", "cover.garage_door"})
        home = EntityState(entity_id="person.a", state="home", last_changed=NOW - timedelta(minutes=40))
        self.assertEqual(find_security_while_away({s.entity_id: s for s in (home, lock)}, NOW), [])

    def test_automation_that_did_not_run_is_detected_unless_overridden(self) -> None:
        exp = [RuleExpectation("a", "Night off", "light.living", "off", 23 * 60, None)]
        now = NOW.replace(hour=23, minute=20)
        stuck = EntityState(entity_id="light.living", state="on", last_changed=NOW.replace(hour=18))
        self.assertEqual(len(find_missed_automations(exp, {stuck.entity_id: stuck}, now, UTC)), 1)
        overridden = EntityState(entity_id="light.living", state="on", last_changed=NOW.replace(hour=23, minute=10))
        self.assertEqual(find_missed_automations(exp, {overridden.entity_id: overridden}, now, UTC), [])


class TestSmallDomainModules(unittest.TestCase):
    def test_numeric_baseline_zscore(self) -> None:
        rows = [((NOW - timedelta(days=d)).replace(minute=0).isoformat(), 4, 22.0 + (0.1 if d % 2 else -0.1)) for d in range(1, 30)]
        base = NumericBaseline(rows, UTC)
        self.assertLess(abs(base.zscore(22.2, NOW)), 2.5)
        self.assertGreater(base.zscore(30.0, NOW), 5)
        self.assertIsNone(NumericBaseline(rows[:2], UTC).zscore(22.0, NOW))

    def test_outcome_evaluation(self) -> None:
        self.assertEqual(evaluate_outcome("decrease_humidity_below_55_percent", 66, 52)[0], "success")
        self.assertEqual(evaluate_outcome("decrease_humidity_below_55_percent", 66, 60)[0], "failure")
        self.assertEqual(evaluate_outcome("reach_21.5C", 19, 21.4)[0], "success")
        self.assertEqual(evaluate_outcome("decrease_by_at_least_3", 60, 56)[0], "success")
        self.assertEqual(evaluate_outcome("decrease_by_at_least_3", 60, 59)[0], "failure")
        self.assertEqual(evaluate_outcome("something vague", "x", 3)[0], "unknown")

    def test_series_summary(self) -> None:
        pts = [{"state": str(20 + i), "last_changed": (NOW + timedelta(hours=i)).isoformat()} for i in range(5)]
        s = summarize_series(pts)
        assert s is not None
        self.assertEqual((s["kind"], s["min"], s["max"], s["slope_per_hour"]), ("numeric", 20.0, 24.0, 1.0))
        d = summarize_series([{"state": "on"}, {"state": "off"}, {"state": "on"}])
        assert d is not None
        self.assertEqual((d["kind"], d["changes"]), ("discrete", 2))

    def test_privacy_scrubber_round_trip(self) -> None:
        sc = PrivacyScrubber()
        prompt = json.dumps(
            {
                "person.jane": {"state": "home", "friendly_name": "Jane Doe", "latitude": 1.2},
                "notify": ["notify.mobile_app_janes_phone"],
                "site": "mail jane@example.com router 192.0.2.7 aa:bb:cc:dd:ee:ff",
                "light.kitchen": {"state": "on"},
            }
        )
        out = sc.scrub_prompt(prompt)
        for leaked in ("jane", "Jane", "example.com", "192.0.2", "aa:bb"):
            self.assertNotIn(leaked, out)
        self.assertIn("light.kitchen", out)
        alias = next(k for k in json.loads(out) if k.startswith("person."))
        restored = sc.restore({"actions": [{"target": alias, "service": "notify.mobile_app_n1"}]})
        self.assertEqual(restored["actions"][0]["target"], "person.jane")
        self.assertEqual(restored["actions"][0]["service"], "notify.mobile_app_janes_phone")

    def test_knowledge_selection_is_relevant_and_cited(self) -> None:
        climate = next(a for a in get_builtin_agents() if a.agent_id == "climate_thermal_agent")
        states = {
            "sensor.bedroom_humidity": EntityState(entity_id="sensor.bedroom_humidity", state="55", device_class="humidity"),
            "climate.living_ufh": EntityState(entity_id="climate.living_ufh", state="heat"),
        }
        ids = {e["id"] for e in select_knowledge(climate, states)}
        self.assertIn("humidity-comfort", ids)
        self.assertIn("floor-heating-inertia", ids)

    def test_undo_calls_restore_previous_state_but_never_unlock(self) -> None:
        states = {
            "light.a": EntityState(entity_id="light.a", state="on", attributes={"brightness": 120}),
            "cover.b": EntityState(entity_id="cover.b", state="open", attributes={"current_position": 40}),
            "lock.c": EntityState(entity_id="lock.c", state="unlocked"),
        }
        calls = build_undo_calls(capture_snapshot(states, ["light.a", "cover.b", "lock.c"]))
        by_entity = {c["entity_ids"][0]: c for c in calls}
        self.assertEqual(by_entity["light.a"]["service_data"], {"brightness": 120})
        self.assertEqual(by_entity["cover.b"]["service"], "set_cover_position")
        self.assertNotIn("lock.c", by_entity)

    def test_quiet_hours_across_midnight(self) -> None:
        self.assertTrue(is_quiet_hours(NOW.replace(hour=23, minute=30), "22:00", "07:00"))
        self.assertTrue(is_quiet_hours(NOW.replace(hour=3), "22:00", "07:00"))
        self.assertFalse(is_quiet_hours(NOW, "22:00", "07:00"))
        self.assertFalse(is_quiet_hours(NOW, "", ""))

    def test_lifecycle_verdicts(self) -> None:
        tl = Timeline([])
        action = RuleAction("light.living", "light", "turn_off")
        on = EntityState(entity_id="automation.x", state="on")
        kwargs = dict(automation_id="x", alias="X", now=NOW, actions=[action], tl=tl)
        fresh = review_deployed_automation(deployed_at=NOW - timedelta(hours=2), state=on, fires=[], **kwargs)
        self.assertEqual(fresh.verdict, "too_new")
        silent = review_deployed_automation(deployed_at=NOW - timedelta(days=9), state=on, fires=[], **kwargs)
        self.assertEqual(silent.verdict, "never_fired")
        gone = review_deployed_automation(deployed_at=NOW - timedelta(days=9), state=None, fires=[], **kwargs)
        self.assertEqual(gone.verdict, "missing")
        fires = [NOW - timedelta(days=d, hours=1) for d in range(1, 6)]
        fought = Timeline([Transition("light.living", f + timedelta(minutes=5), "off", "on", "human_or_physical") for f in fires])
        overridden = review_deployed_automation(
            deployed_at=NOW - timedelta(days=9), state=on, fires=fires, **{**kwargs, "tl": fought}
        )
        self.assertEqual(overridden.verdict, "overridden")

    def test_automation_last_triggered_attribute_marks_child_events_as_ha_automation(self) -> None:
        from ha_ai_brain.adapters.ha_websocket_rest import HomeAssistantAdapter
        from ha_ai_brain.domain.models import EventOrigin

        adapter = HomeAssistantAdapter("http://localhost:8123", "", "token")
        auto_evt = {
            "data": {
                "entity_id": "automation.study_dehumidify",
                "old_state": {"entity_id": "automation.study_dehumidify", "state": "on", "attributes": {"last_triggered": "2026-10-29T16:00:00Z"}},
                "new_state": {"entity_id": "automation.study_dehumidify", "state": "on", "attributes": {"last_triggered": "2026-10-30T16:09:00Z"}},
            },
            "context": {"id": "ctx_auto_1", "parent_id": "ctx_sensor_1", "user_id": None},
        }
        adapter._parse_state_changed(auto_evt["data"], auto_evt["context"])
        child_evt = {
            "data": {
                "entity_id": "climate.study_ac",
                "old_state": {"entity_id": "climate.study_ac", "state": "off", "attributes": {}},
                "new_state": {"entity_id": "climate.study_ac", "state": "dry", "attributes": {}},
            },
            "context": {"id": "ctx_call_1", "parent_id": "ctx_auto_1", "user_id": None},
        }
        parsed = adapter._parse_state_changed(child_evt["data"], child_evt["context"])
        assert parsed is not None
        self.assertEqual(parsed.origin, EventOrigin.HA_AUTOMATION)


class TestTelemetryStore(unittest.IsolatedAsyncioTestCase):
    async def test_idempotent_recording_window_fires_and_prune(self) -> None:
        store = SQLiteTelemetryStore(":memory:")
        trans = nightly_light(days=5)
        self.assertEqual(await store.record_transitions(trans), len(trans))
        self.assertEqual(await store.record_transitions(trans), 0)
        await store.record_transitions([Transition("automation.x", NOW, "", AUTOMATION_FIRE_STATE, "ha_automation")])
        self.assertEqual(len(await store.get_transitions()), len(trans))  # fires are not state transitions
        self.assertEqual(await store.get_fires("automation.x"), [NOW])
        window = await store.observation_window(NOW)
        assert window is not None
        self.assertEqual(window[0], at(5, 18))
        await store.record_numeric([("sensor.t", NOW, 20.0), ("sensor.t", NOW + timedelta(minutes=5), 22.0)])
        hours = await store.get_numeric_hours("sensor.t")
        self.assertEqual((hours[0][1], hours[0][2]), (2, 21.0))
        self.assertGreater(await store.prune(2, NOW), 0)
        store.close()


class StubLike:
    """Minimal LLM stand-in for the graph (only generate_json is used there)."""

    async def generate_json(self, system_prompt, user_prompt, use_fast_tier=False, context_hint=None):
        return {}


class TestOrchestratorIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = BrainSettings(
            use_simulator=True,
            db_path=str(Path(self._tmp.name) / "t.db"),
            custom_agents_dir=self._tmp.name,
            timezone="UTC",
        )
        self.orch = build_orchestrator(self.settings)
        self.now = datetime.now(UTC)

    async def asyncTearDown(self) -> None:
        self.orch.memory._conn.close()
        self.orch.telemetry.close()
        self._tmp.cleanup()

    def _seed_nightly(self, entity: str, days: int = 10) -> list[Transition]:
        out = []
        for d in range(1, days + 1):
            out.append(Transition(entity, at(d, 18, 0, self.now), "off", "on", "human_or_physical"))
            out.append(Transition(entity, at(d, 22, 31 + d % 3, self.now), "on", "off", "human_or_physical"))
        return out

    async def test_learned_habit_becomes_backtested_approval_without_llm_tokens(self) -> None:
        await self.orch.telemetry.record_transitions(self._seed_nightly("light.kitchen_ceiling"))
        tokens_before = (await self.orch.llm.get_quota_status()).prompt_tokens_session
        log = await self.orch.run_pattern_cycle()
        assert log is not None
        self.assertEqual(log.agent_id, "pattern_miner")
        self.assertTrue(any(r["status"] == "awaiting_user_approval" for r in log.execution_results))
        pending = await self.orch.memory.get_pending_approvals()
        self.assertEqual(len(pending), 2)  # "on in the evening" and "off at night" are two different habits
        for p in pending:
            self.assertEqual(p.intent.backtest.verdict, "supported", p.intent.backtest.summary)
            self.assertTrue(p.intent.native_automation.source_pattern_id)
        times = sorted(p.intent.native_automation.trigger[0]["at"][:5] for p in pending)
        self.assertEqual(times, ["18:00", "22:30"])
        self.assertEqual((await self.orch.llm.get_quota_status()).prompt_tokens_session, tokens_before)

        again = await self.orch.run_pattern_cycle()  # must not pile up duplicates
        self.assertEqual(len(await self.orch.memory.get_pending_approvals()), 2)
        if again is not None:
            self.assertFalse(any(r["status"] == "awaiting_user_approval" for r in again.execution_results))

    async def test_typical_sensor_changes_do_not_wake_the_llm_but_outliers_do(self) -> None:
        eid = "sensor.living_room_temperature"
        rows = [(eid, self.now - timedelta(hours=h), 22.0 + (0.1 if h % 2 else -0.1)) for h in range(1, 28 * 24)]
        await self.orch.telemetry.record_numeric(rows)
        await self.orch.telemetry.set_meta("observed_since", (self.now - timedelta(days=28)).isoformat())
        sim = self.orch.smart_home
        logs = await self.orch.process_state_changed_event(sim.emit_simulated_state_change(eid, "22.9"))
        self.assertEqual(logs, [])
        self.assertGreaterEqual(self.orch.learning.stats["llm_calls_avoided"], 1)
        logs = await self.orch.process_state_changed_event(sim.emit_simulated_state_change(eid, "28.0"))
        self.assertTrue(logs)

    async def test_pause_blocks_real_time_runs_and_execution(self) -> None:
        self.orch.settings.paused = True
        sim = self.orch.smart_home
        self.assertEqual(await self.orch.process_state_changed_event(sim.emit_simulated_state_change("sensor.master_bedroom_humidity", "75")), [])
        self.orch._cached_states = await sim.get_all_states()
        intent = ActionIntent(agent_id="lighting_pattern_agent", domain="light", service="turn_off", target_entity_ids=["light.kitchen_ceiling"], cause_category="t", rationale="t")
        res = await self.orch._evaluate_and_dispatch_intents([intent])
        self.assertEqual(res[0]["status"], "shadow_logged")

    async def test_domain_autonomy_undo_and_rate_limit(self) -> None:
        sim = self.orch.smart_home
        self.orch._cached_states = await sim.get_all_states()
        self.orch.settings.domain_autonomy = {"light": AutonomyLevel.AUTONOMOUS}
        self.orch.settings.max_actions_per_hour = 1

        def light(eid: str, service: str) -> ActionIntent:
            return ActionIntent(agent_id="lighting_pattern_agent", domain="light", service=service, target_entity_ids=[eid], cause_category="t", rationale="t")

        first, second = await self.orch._evaluate_and_dispatch_intents(
            [light("light.kitchen_ceiling", "turn_off"), light("light.living_room_dimmer", "turn_on")]
        )
        self.assertEqual(first["status"], "executed")
        self.assertEqual(second["status"], "awaiting_user_approval")
        self.assertIn("Held for approval", second["reason"])

        records = await self.orch.list_undo_records()
        self.assertEqual(len(records), 1)
        calls_before = len(sim.service_call_log)
        result = await self.orch.handle_undo(records[0]["undo_id"])
        self.assertEqual(result["reverted"], ["light.kitchen_ceiling"])
        last = sim.service_call_log[-1]
        self.assertEqual((last["service"], len(sim.service_call_log) - calls_before), ("turn_on", 1))
        with self.assertRaises(KeyError):
            await self.orch.handle_undo(records[0]["undo_id"])  # exactly once
        feedback = await self.orch.memory.get_relevant_feedback("lighting_pattern_agent")
        self.assertIn(FeedbackPolarity.OVERRIDDEN_IMPLICIT, [f.polarity for f in feedback])

    async def test_exception_creates_one_urgent_insight(self) -> None:
        states = await self.orch.smart_home.get_all_states()
        self.orch.settings.default_autonomy = AutonomyLevel.SHADOW  # exceptions must alert even in shadow mode
        finding = ExceptionFinding(
            kind="routine_deviation", entity_id="lock.front_door", severity="critical",
            summary="Exception: Front Door has been 'unlocked' for 60 min, but it is normally 'locked'.",
            expected_state="locked", current_state="unlocked", confidence=0.95,
        )
        await self.orch._handle_exception(finding, states, [], self.now)
        await self.orch._handle_exception(finding, states, [], self.now)
        insights = [i for i in await self.orch.memory.get_advisory_insights(status="active") if i.category == "exception"]
        self.assertEqual(len(insights), 1)
        sent = [n for n in self.orch.notification.sent_notifications if n["type"] == "advisory_insight"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["payload"]["data"]["push"]["interruption-level"], "time-sensitive")

    async def test_unlocked_door_exception_leads_to_a_lock_now_proposal_even_at_night(self) -> None:
        """Alert -> the Security agent proposes lock.lock -> co-pilot asks (push breaks through quiet hours), autonomous just does it."""
        from ha_ai_brain.domain.expectations import ExceptionFinding

        class LockingLLM(StubLike):
            async def generate_json(self, system_prompt, user_prompt, use_fast_tier=False, context_hint=None):
                if (context_hint or {}).get("task") == "synthesize_realtime_reactions":
                    return {"actions": [{"domain": "lock", "service": "lock", "target_entity_ids": ["lock.front_door"], "cause_category": "unlocked_unexpectedly", "rationale": "Front door is unlocked while it is normally locked at this hour.", "risk_level": "low"}]}
                return {}

        self.orch.agent_graph.llm = LockingLLM()
        states = await self.orch.smart_home.get_all_states()
        self.orch._cached_states = states
        local = self.orch.learning.local_now(self.now)
        self.orch.settings.quiet_hours_start = (local - timedelta(hours=1)).strftime("%H:%M")
        self.orch.settings.quiet_hours_end = (local + timedelta(hours=1)).strftime("%H:%M")
        self.assertTrue(self.orch._in_quiet_hours())

        finding = ExceptionFinding("routine_deviation", "lock.front_door", "critical", "Exception: Front Door has been 'unlocked' for 60 min, but it is normally 'locked'.", "locked", "unlocked", 0.95)
        await self.orch._handle_exception(finding, states, [], self.now)
        pending = await self.orch.memory.get_pending_approvals()
        self.assertEqual([(p.intent.domain, p.intent.service, p.intent.target_entity_ids) for p in pending], [("lock", "lock", ["lock.front_door"])])
        kinds = [n["type"] for n in self.orch.notification.sent_notifications]
        self.assertEqual(kinds.count("advisory_insight"), 1)  # the alert
        self.assertEqual(kinds.count("approval_request"), 1)  # the "lock it now?" push is not held back by quiet hours
        self.assertEqual(self.orch._deferred_approval_pushes, set())

        # an ordinary, non-urgent proposal at the same time IS held back
        routine = ActionIntent(agent_id="lighting_pattern_agent", domain="light", service="turn_off", target_entity_ids=["light.kitchen_ceiling"], cause_category="t", rationale="t")
        await self.orch._evaluate_and_dispatch_intents([routine])
        self.assertEqual(len(self.orch._deferred_approval_pushes), 1)

        # in autonomous mode for locks the door is simply locked, and you are told (no Undo button: locks are never auto-reverted)
        await self.orch.dismiss_all_pending()
        self.orch.settings.domain_autonomy = {"lock": AutonomyLevel.AUTONOMOUS}
        self.orch.settings.quiet_hours_start = self.orch.settings.quiet_hours_end = ""
        lock_intent = ActionIntent(agent_id="security_safety_agent", domain="lock", service="lock", target_entity_ids=["lock.front_door"], cause_category="t", rationale="t")
        result = (await self.orch._evaluate_and_dispatch_intents([lock_intent]))[0]
        self.assertEqual(result["status"], "executed")
        notice = [n for n in self.orch.notification.sent_notifications if n["type"] == "action_taken"][-1]
        self.assertNotIn("actions", notice["payload"]["data"])
        self.assertEqual(await self.orch.list_undo_records(), [])

    async def test_outcome_verification_writes_feedback(self) -> None:
        self.orch._cached_states = await self.orch.smart_home.get_all_states()
        outcome = ExpectedOutcome(
            action_id="a1", agent_id="climate_thermal_agent", monitored_entity_id="sensor.master_bedroom_humidity",
            baseline_value=66, expected_direction_or_target="decrease_humidity_below_55_percent", check_after_minutes=1,
        )
        await self.orch.memory.save_expected_outcome(outcome)
        self.assertEqual(await self.orch.verify_due_outcomes(), 0)  # not due yet
        self.orch.memory._conn.execute("UPDATE expected_outcomes SET due_at = ?", ((self.now - timedelta(minutes=1)).isoformat(),))
        self.assertEqual(await self.orch.verify_due_outcomes(), 1)
        feedback = await self.orch.memory.get_relevant_feedback("climate_thermal_agent")
        self.assertIn(FeedbackPolarity.OUTCOME_VERIFIED_SUCCESS, [f.polarity for f in feedback])

    async def test_lifecycle_trust_and_digest_jobs(self) -> None:
        mem = self.orch.memory
        await mem.save_feedback(
            FeedbackEpisode(
                agent_id="lighting_pattern_agent", cause_category="learned_habit",
                action_signature="sig:lighting_pattern_agent:automation.upsert_native_automation:night:light.x",
                target_entity_ids=["light.x"], service_called="automation.upsert_native_automation",
                service_data={"automation_id": "ai_brain_x", "alias": "Night", "action": [{"service": "light.turn_off", "target": {"entity_id": "light.x"}}]},
                polarity=FeedbackPolarity.ENDORSED_ONCE, created_at=self.now - timedelta(days=10),
            )
        )
        reviews = await self.orch.review_deployed_automations()
        self.assertEqual([r.verdict for r in reviews], ["missing"])
        self.assertTrue(any(i.category == "automation_review" for i in await mem.get_advisory_insights(status="active")))

        for _ in range(5):
            await mem.save_feedback(
                FeedbackEpisode(
                    agent_id="lighting_pattern_agent", cause_category="x", action_signature="sig:l",
                    target_entity_ids=["light.y"], service_called="light.turn_off", polarity=FeedbackPolarity.ENDORSED_ONCE,
                )
            )
        self.assertEqual(await self.orch.propose_trust_promotions(), 1)
        self.assertEqual(await self.orch.propose_trust_promotions(), 0)

        self.assertFalse(await self.orch.maybe_send_weekly_digest())  # first call only arms the timer
        await mem.set_kv("digest:last", (self.now - timedelta(days=8)).isoformat())
        self.assertTrue(await self.orch.maybe_send_weekly_digest())

    async def test_housekeeping_tick_bootstraps_without_errors(self) -> None:
        await self.orch.housekeeping_tick()
        self.assertTrue(self.orch._bootstrapped)

    async def test_detect_exceptions_skips_automated_states_and_extends_cached_timeline(self) -> None:
        from ha_ai_brain.domain.twins import EntityFacts

        trans = []
        for d in range(1, 10):
            trans.append(Transition("climate.study_ac", at(d, 9, 0, self.now), "off", "cool", "human_or_physical"))
            trans.append(Transition("climate.study_ac", at(d, 12, 0, self.now), "cool", "off", "human_or_physical"))
            trans.append(Transition("climate.study_heater", at(d, 8, 0, self.now), "off", "heat", "human_or_physical"))
            trans.append(Transition("climate.study_heater", at(d, 22, 0, self.now), "heat", "off", "human_or_physical"))
        await self.orch.telemetry.record_transitions(trans)
        now = at(0, 16, 42, self.now)

        # Warm the cached snapshot before the automation fires at 16:09
        await self.orch.learning._learned_snapshot(now - timedelta(minutes=34))

        # Automation fires at 16:09 (after snapshot was cached) and sets study_ac to 'dry'
        await self.orch.telemetry.record_transitions(
            [Transition("climate.study_ac", now - timedelta(minutes=33), "off", "dry", "ha_automation")]
        )

        # And a UI device-action automation rule covers study_heater -> off
        states = {
            "climate.study_ac": EntityState(
                entity_id="climate.study_ac", state="dry", last_changed=now - timedelta(minutes=33)
            ),
            "climate.study_heater": EntityState(
                entity_id="climate.study_heater", state="off", last_changed=now - timedelta(minutes=33)
            ),
        }
        facts = {
            "climate.study_heater": EntityFacts(
                entity_id="climate.study_heater",
                device_id="dev_heater_1",
                registry_id="reg_heater_1",
            )
        }
        async def _fake_configs():
            return [
                {
                    "id": "study_humidity_dehumidify",
                    "alias": "Study dehumidify",
                    "triggers": [{"trigger": "numeric_state", "entity_id": "sensor.study_humidity", "above": 60}],
                    "actions": [
                        {
                            "domain": "climate",
                            "type": "set_hvac_mode",
                            "device_id": "dev_heater_1",
                            "entity_id": "reg_heater_1",
                            "hvac_mode": "off",
                        }
                    ],
                }
            ]

        async def _fake_facts():
            return list(facts.values())

        self.orch.smart_home.get_automation_configs = _fake_configs  # type: ignore[method-assign]
        self.orch.smart_home.get_entity_device_facts = _fake_facts  # type: ignore[attr-defined]
        await self.orch.learning.refresh_rules(states, force=True)

        from ha_ai_brain.domain.models import SemanticEventFrame, StateChangedEvent

        findings = await self.orch.learning.detect_exceptions(states, now)
        self.assertEqual([f.entity_id for f in findings], [])
        frame = SemanticEventFrame(
            target_agent_id="climate_thermal_agent",
            trigger_events=[
                StateChangedEvent(
                    entity_id="climate.study_heater",
                    new_state=states["climate.study_heater"],
                    timestamp=now,
                )
            ],
        )
        wake, reason = await self.orch.learning.should_wake_agent(frame, now)
        self.assertFalse(wake)
        self.assertIn("Study dehumidify", reason)


class TestLearningApi(unittest.IsolatedAsyncioTestCase):
    async def test_learned_snapshot_pause_domain_autonomy_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db"), custom_agents_dir=tmp, timezone="UTC"))
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                learned = (await client.get("/api/learned")).json()
                for key in ("days_of_data", "baseline_ready", "patterns", "stats_7d", "tokens_today", "undo_records"):
                    self.assertIn(key, learned)
                res = await client.post("/api/settings", json={"paused": True, "domain_autonomy": {"Light": "autonomous"}, "quiet_hours_start": "22:00", "quiet_hours_end": "07:00"})
                self.assertEqual(res.status_code, 200)
                status = (await client.get("/api/status")).json()
                self.assertTrue(status["settings"]["paused"])
                self.assertEqual(status["settings"]["domain_autonomy"], {"light": "autonomous"})
                self.assertEqual((await client.post("/api/settings", json={"quiet_hours_start": "25:99"})).status_code, 400)
                self.assertEqual((await client.post("/api/undo/missing")).status_code, 404)
            app.state.orchestrator.memory._conn.close()
            app.state.orchestrator.telemetry.close()

            # Settings persist across restarts
            app2 = create_app(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db"), custom_agents_dir=tmp, timezone="UTC"))
            self.assertTrue(app2.state.orchestrator.settings.paused)
            self.assertEqual(app2.state.orchestrator.settings.domain_autonomy, {"light": AutonomyLevel.AUTONOMOUS})
            app2.state.orchestrator.memory._conn.close()
            app2.state.orchestrator.telemetry.close()


if __name__ == "__main__":
    unittest.main()
