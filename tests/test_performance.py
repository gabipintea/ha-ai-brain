"""Performance work: compact telemetry layout + migration, maintenance, run-log packing, retention, write buffering,
habit clustering, prompt compaction, agent scope, provider-neutral reasoning hint and log level parsing."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from ha_ai_brain.adapters.llm_litellm import GEMINI_THINKING_BUDGET, _output_tokens
from ha_ai_brain.adapters.memory_sqlite import SQLiteMemoryAdapter
from ha_ai_brain.adapters.telemetry_sqlite import SQLiteTelemetryStore
from ha_ai_brain.application.learning import LearningEngine
from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.agent_scope import agent_can_act, agent_has_scope
from ha_ai_brain.domain.models import AgentRunLog, AgentSpec, DerivedSignal, EntityState, StateChangedEvent, Transition
from ha_ai_brain.domain.patterns import _best_cluster
from ha_ai_brain.domain.promptfmt import dumps, prune
from ha_ai_brain.ports.llm import REASONING_DEFAULT, REASONING_LOW, REASONING_OFF

UTC = timezone.utc
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def spec(**kw) -> AgentSpec:
    base = dict(agent_id="a", name="A", specialty="s", description="d", monitored_domains=["sensor"], controllable_domains=["light", "notify"], goals=["g"])
    base.update(kw)
    return AgentSpec(**base)


def st(eid: str, state: str = "on") -> EntityState:
    return EntityState(entity_id=eid, state=state, domain=eid.split(".")[0])


class ClusterTests(unittest.TestCase):
    def test_cluster_wraps_midnight(self):
        items = [(i, m) for i, m in enumerate([1435, 1438, 2, 5, 1440 - 1])]  # 23:55-00:05, one per date
        centre, members = _best_cluster(items, 20)
        self.assertEqual(len(members), 5)
        self.assertTrue(centre > 1400 or centre < 20)

    def test_one_item_per_date_and_empty(self):
        self.assertEqual(_best_cluster([], 20), (0.0, []))
        _, members = _best_cluster([("d1", 600), ("d1", 605), ("d2", 610)], 20)
        self.assertEqual(sorted(d for d, _ in members), ["d1", "d2"])

    def test_picks_densest_group(self):
        items = [(i, 480) for i in range(5)] + [(i + 10, 1200) for i in range(2)]
        centre, members = _best_cluster(items, 20)
        self.assertEqual(len(members), 5)
        self.assertAlmostEqual(centre, 480, delta=1)


class TelemetryStorageTests(unittest.TestCase):
    def test_roundtrip_and_count_since(self):
        s = SQLiteTelemetryStore(":memory:")
        tr = [Transition("light.a", NOW - timedelta(hours=h), "off", "on", "human_or_physical") for h in range(5)]
        self.assertEqual(run(s.record_transitions(tr)), 5)
        self.assertEqual(run(s.record_transitions(tr)), 0)  # idempotent
        got = run(s.get_transitions(since=NOW - timedelta(days=1)))
        self.assertEqual(len(got), 5)
        self.assertEqual((got[0].old_state, got[0].new_state), ("off", "on"))
        self.assertEqual(run(s.count_since(NOW - timedelta(hours=2, minutes=1))), 3)
        self.assertEqual(run(s.count_since(NOW - timedelta(days=1), ["light.a"])), 5)
        self.assertEqual(run(s.count_since(NOW - timedelta(days=1), ["light.zzz"])), 0)

    def test_numeric_hourly(self):
        s = SQLiteTelemetryStore(":memory:")
        hour = NOW.replace(minute=0)
        run(s.record_numeric_hourly([("sensor.t", hour, 4, 80.0)]))
        rows = run(s.get_numeric_hours("sensor.t"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:], (4, 20.0))
        self.assertIn("sensor.t", run(s.get_all_numeric_hours()))

    def test_legacy_migration(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.db")
            c = sqlite3.connect(path)
            c.executescript(
                """
                CREATE TABLE transitions (entity_id TEXT, ts TEXT, old_state TEXT, new_state TEXT, origin TEXT, user_id TEXT);
                CREATE TABLE numeric_hourly (entity_id TEXT, hour_ts TEXT, n INTEGER, total REAL);
                """
            )
            for h in range(10):
                c.execute("INSERT INTO transitions VALUES (?,?,?,?,?,?)", ("light.a", (NOW - timedelta(hours=h)).isoformat(), "off", "on", "human_or_physical", "u"))
            c.execute("INSERT INTO numeric_hourly VALUES (?,?,?,?)", ("sensor.t", NOW.replace(minute=0).isoformat(), 3, 60.0))
            c.commit()
            c.close()
            s = SQLiteTelemetryStore(path)
            self.assertEqual(len(run(s.get_transitions(since=NOW - timedelta(days=1)))), 10)
            self.assertEqual(run(s.get_numeric_hours("sensor.t"))[0][1:], (3, 20.0))
            tables = {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("transitions", tables)
            self.assertNotIn("numeric_hourly", tables)
            s.close()
            s2 = SQLiteTelemetryStore(path)  # reopening is a no-op
            self.assertEqual(len(run(s2.get_transitions(since=NOW - timedelta(days=1)))), 10)
            s2.close()

    def test_maintenance_shrinks_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.db")
            s = SQLiteTelemetryStore(path)
            old = NOW - timedelta(days=200)
            run(s.record_transitions([Transition(f"light.e{i % 50}", old + timedelta(seconds=i), "off", "on") for i in range(20000)]))
            run(s.maintain())
            big = os.path.getsize(path)
            run(s.prune(30, NOW))
            run(s.maintain())
            self.assertLess(os.path.getsize(path), big * 0.5)
            s.close()


def sample_log(code: str = "x = 1\n" * 400, signals: int = 3) -> AgentRunLog:
    return AgentRunLog(
        agent_id="a", mode="periodic_batch", trigger_summary="t",
        derived_signals=[DerivedSignal(signal_name=f"s{i}", value=float(i), python_code_executed=code) for i in range(signals)],
    )


class MemoryStoreTests(unittest.TestCase):
    def test_run_log_pack_roundtrip_and_compression(self):
        log = sample_log()
        packed = SQLiteMemoryAdapter._pack_log(log)
        self.assertIsInstance(packed, bytes)
        self.assertLess(len(packed), len(log.model_dump_json()) / 3)
        back = SQLiteMemoryAdapter._unpack_log(packed)
        self.assertEqual([s.python_code_executed for s in back.derived_signals], [log.derived_signals[0].python_code_executed] * 3)
        small = SQLiteMemoryAdapter._pack_log(AgentRunLog(agent_id="a", mode="m", trigger_summary="t"))
        self.assertIsInstance(small, str)
        self.assertEqual(SQLiteMemoryAdapter._unpack_log(small).agent_id, "a")

    def test_run_log_save_and_get(self):
        m = SQLiteMemoryAdapter(":memory:")
        log = sample_log()
        run(m.save_run_log(log))
        got = run(m.get_run_log(log.run_id))
        self.assertEqual(got.derived_signals[2].python_code_executed, log.derived_signals[2].python_code_executed)
        self.assertEqual(len(run(m.get_recent_run_logs())), 1)

    def test_run_log_count_cap(self):
        m = SQLiteMemoryAdapter(":memory:")
        m.RUN_LOG_MAX_COUNT = 5
        for _ in range(9):
            run(m.save_run_log(sample_log(signals=0)))
        self.assertEqual(run(m.get_run_logs_count()), 5)

    def test_prune_old_keeps_protected_keys(self):
        m = SQLiteMemoryAdapter(":memory:")
        for key in ("rcache:a:1", "compcode:x", "research:last_run", "research:last_summary", "research:oldcache", "stats:day", "keep:me"):
            run(m.set_kv(key, "v"))
        m._conn.execute("UPDATE kv_store SET updated_at = ?", ((NOW - timedelta(days=400)).isoformat(),))
        m._conn.commit()
        removed = run(m.prune_old(NOW))
        self.assertGreaterEqual(removed["kv"], 4)
        self.assertIsNone(run(m.get_kv("rcache:a:1")))
        self.assertIsNone(run(m.get_kv("compcode:x")))
        self.assertIsNone(run(m.get_kv("research:oldcache")))
        for key in ("research:last_run", "research:last_summary", "keep:me"):
            self.assertEqual(run(m.get_kv(key)), "v")

    def test_auto_vacuum_enabled_on_file(self):
        with tempfile.TemporaryDirectory() as d:
            m = SQLiteMemoryAdapter(os.path.join(d, "m.db"))
            self.assertEqual(m._conn.execute("PRAGMA auto_vacuum").fetchone()[0], 2)
            run(m.maintain())


class _Home:
    supports_history_backfill = False


class LearningBufferTests(unittest.TestCase):
    def _engine(self):
        tel = SQLiteTelemetryStore(":memory:")
        return LearningEngine(BrainSettings(), _Home(), tel), tel

    def test_writes_are_buffered_and_flushed(self):
        eng, tel = self._engine()
        old, new = st("light.a", "off"), st("light.a", "on")
        run(eng.record_event(StateChangedEvent(entity_id="light.a", old_state=old, new_state=new, timestamp=NOW)))
        for i in range(3):
            run(eng.record_event(StateChangedEvent(entity_id="sensor.t", old_state=None, new_state=EntityState(entity_id="sensor.t", state=str(20 + i), domain="sensor"), timestamp=NOW)))
        self.assertEqual(run(tel.count_since(NOW - timedelta(days=1))), 0)  # still in memory
        run(eng.flush())
        self.assertEqual(run(tel.count_since(NOW - timedelta(days=1))), 1)
        rows = run(tel.get_numeric_hours("sensor.t"))
        self.assertEqual(rows[0][1], 3)
        self.assertAlmostEqual(rows[0][2], 21.0)
        run(eng.flush())  # empty flush is harmless

    def test_flush_failure_does_not_raise(self):
        eng, tel = self._engine()
        run(eng.record_event(StateChangedEvent(entity_id="light.a", old_state=st("light.a", "off"), new_state=st("light.a", "on"), timestamp=NOW)))
        with patch.object(tel, "record_transitions", side_effect=RuntimeError("disk")):
            run(eng.flush())


class PureHelperTests(unittest.TestCase):
    def test_promptfmt(self):
        self.assertEqual(prune({"a": None, "b": "", "c": [], "d": {}, "e": 0, "f": False, "g": 1.23456}), {"e": 0, "f": False, "g": 1.235})
        self.assertEqual(dumps({"a": [1, None, {"b": ""}], "c": "x"}), '{"a":[1],"c":"x"}')
        self.assertNotIn(" ", dumps({"k": "v", "n": [1, 2]}))

    def test_agent_scope(self):
        light = spec()
        ok, _ = agent_has_scope(light, {"light.a": st("light.a")})
        self.assertTrue(ok)
        ok, why = agent_has_scope(light, {"cover.a": st("cover.a")})
        self.assertFalse(ok)
        self.assertIn("light", why)
        self.assertTrue(agent_can_act(light, {"light.a": st("light.a")}))
        self.assertFalse(agent_can_act(light, {"cover.a": st("cover.a")}))

    def test_scope_batch_triggers(self):
        diag = spec(controllable_domains=["notify"], batch_trigger="unavailable_only")
        self.assertFalse(agent_has_scope(diag, {"light.a": st("light.a")})[0])
        self.assertTrue(agent_has_scope(diag, {"light.a": st("light.a", "unavailable")})[0])
        self.assertTrue(agent_can_act(diag, {}))
        self.assertTrue(agent_has_scope(spec(batch_trigger="always"), {})[0])
        advisory = spec(controllable_domains=["notify"], monitored_domains=["sensor"])
        self.assertFalse(agent_has_scope(advisory, {"sensor.a": st("sensor.a")})[0])
        many = {f"sensor.s{i}": st(f"sensor.s{i}") for i in range(3)}
        self.assertTrue(agent_has_scope(advisory, many)[0])


class ProviderNeutralTests(unittest.TestCase):
    def test_reasoning_hints_are_plain_strings_mapped_only_for_gemini(self):
        self.assertEqual({REASONING_OFF, REASONING_LOW, REASONING_DEFAULT}, set(GEMINI_THINKING_BUDGET))
        self.assertEqual(GEMINI_THINKING_BUDGET[REASONING_OFF], 0)
        self.assertLess(GEMINI_THINKING_BUDGET[REASONING_LOW], GEMINI_THINKING_BUDGET[REASONING_DEFAULT])

    def test_thinking_tokens_are_billed(self):
        self.assertEqual(_output_tokens({"candidatesTokenCount": 100, "thoughtsTokenCount": 40}), 140)
        self.assertEqual(_output_tokens({"candidatesTokenCount": 100}), 100)
        self.assertEqual(_output_tokens({}), 0)


class ConfigTests(unittest.TestCase):
    def test_log_level_env(self):
        with patch.dict(os.environ, {"BRAIN_LOG_LEVEL": "debug"}):
            self.assertEqual(BrainSettings.from_env().log_level, "DEBUG")
        with patch.dict(os.environ, {"BRAIN_LOG_LEVEL": "nonsense"}):
            self.assertEqual(BrainSettings.from_env().log_level, "INFO")

    def test_new_defaults(self):
        s = BrainSettings()
        self.assertEqual(s.realtime_coalesce_seconds, 90)
        self.assertEqual(s.max_agent_wakeups_per_hour, 6)


if __name__ == "__main__":
    unittest.main()
