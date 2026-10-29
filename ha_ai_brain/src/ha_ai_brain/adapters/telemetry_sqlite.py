"""
SQLite implementation of the telemetry store (shares the add-on database file).

Compact layout: entity and state names are stored once in small dictionary tables and rows reference them by integer id;
timestamps are epoch seconds; the big tables are WITHOUT ROWID so each row exists exactly once. This is several times
smaller than a naive text layout. Databases written by earlier versions are migrated in place on first start.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from ha_ai_brain.adapters.sqlite_maintenance import configure_connection, ensure_incremental_vacuum, run_maintenance
from ha_ai_brain.domain.models import Transition
from ha_ai_brain.domain.timeutil import ensure_utc, parse_iso
from ha_ai_brain.ports.telemetry import AUTOMATION_FIRE_STATE, TelemetryStorePort

logger = logging.getLogger(__name__)

ORIGINS = ("unknown", "sensor_telemetry", "human_or_physical", "ha_automation", "ai_brain")
_ORIGIN_ID = {name: i for i, name in enumerate(ORIGINS)}
UTC = timezone.utc
MIGRATION_BATCH = 20000


def _epoch(ts: datetime) -> int:
    return int(ensure_utc(ts).timestamp())


def _hour_index(ts: datetime) -> int:
    return _epoch(ts) // 3600


class SQLiteTelemetryStore(TelemetryStorePort):
    def __init__(self, db_path: str = ":memory:") -> None:
        self._path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        configure_connection(self._conn)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tel_entity (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS tel_state (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS tr (
                e INTEGER NOT NULL, ts INTEGER NOT NULL, s INTEGER NOT NULL, p INTEGER NOT NULL, o INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (e, ts, s)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS tr_ts ON tr(ts);
            CREATE TABLE IF NOT EXISTS nh (
                e INTEGER NOT NULL, h INTEGER NOT NULL, n INTEGER NOT NULL, total REAL NOT NULL,
                PRIMARY KEY (e, h)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS nh_h ON nh(h);
            CREATE TABLE IF NOT EXISTS telemetry_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        self._conn.commit()
        self._ent: dict[str, int] = {}
        self._ent_rev: dict[int, str] = {}
        self._st: dict[str, int] = {}
        self._st_rev: dict[int, str] = {}
        self._hour_iso: dict[int, str] = {}
        for r in self._conn.execute("SELECT id, name FROM tel_entity"):
            self._ent[r["name"]] = r["id"]
            self._ent_rev[r["id"]] = r["name"]
        for r in self._conn.execute("SELECT id, name FROM tel_state"):
            self._st[r["name"]] = r["id"]
            self._st_rev[r["id"]] = r["name"]
        self._migrate_legacy()
        ensure_incremental_vacuum(self._conn, db_path)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ dictionaries
    def _eid(self, name: str) -> int:
        i = self._ent.get(name)
        if i is None:
            self._conn.execute("INSERT OR IGNORE INTO tel_entity (name) VALUES (?)", (name,))
            i = self._conn.execute("SELECT id FROM tel_entity WHERE name = ?", (name,)).fetchone()["id"]
            self._ent[name], self._ent_rev[i] = i, name
        return i

    def _sid(self, name: str) -> int:
        i = self._st.get(name)
        if i is None:
            self._conn.execute("INSERT OR IGNORE INTO tel_state (name) VALUES (?)", (name,))
            i = self._conn.execute("SELECT id FROM tel_state WHERE name = ?", (name,)).fetchone()["id"]
            self._st[name], self._st_rev[i] = i, name
        return i

    def _iso_hour(self, h: int) -> str:
        iso = self._hour_iso.get(h)
        if iso is None:
            iso = datetime.fromtimestamp(h * 3600, UTC).isoformat()
            if len(self._hour_iso) > 200_000:
                self._hour_iso.clear()
            self._hour_iso[h] = iso
        return iso

    # ------------------------------------------------------------------ migration
    def _migrate_legacy(self) -> None:
        tables = {r["name"] for r in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        migrated = 0
        if "transitions" in tables:
            cur = self._conn.execute("SELECT entity_id, ts, old_state, new_state, origin FROM transitions")
            while True:
                rows = cur.fetchmany(MIGRATION_BATCH)
                if not rows:
                    break
                batch = []
                for r in rows:
                    ts = parse_iso(r["ts"])
                    if ts is None:
                        continue
                    batch.append((self._eid(r["entity_id"]), _epoch(ts), self._sid(r["new_state"]), self._sid(r["old_state"] or ""), _ORIGIN_ID.get(r["origin"], 0)))
                self._conn.executemany("INSERT OR IGNORE INTO tr (e, ts, s, p, o) VALUES (?,?,?,?,?)", batch)
                migrated += len(batch)
            self._conn.execute("DROP TABLE transitions")
        if "numeric_hourly" in tables:
            cur = self._conn.execute("SELECT entity_id, hour_ts, n, total FROM numeric_hourly")
            while True:
                rows = cur.fetchmany(MIGRATION_BATCH)
                if not rows:
                    break
                batch = []
                for r in rows:
                    ts = parse_iso(r["hour_ts"])
                    if ts is not None:
                        batch.append((self._eid(r["entity_id"]), _hour_index(ts), int(r["n"]), float(r["total"])))
                self._conn.executemany("INSERT OR REPLACE INTO nh (e, h, n, total) VALUES (?,?,?,?)", batch)
                migrated += len(batch)
            self._conn.execute("DROP TABLE numeric_hourly")
        if "transitions" in tables or "numeric_hourly" in tables:
            self._conn.commit()
            run_maintenance(self._conn)
            logger.info("Migrated %d telemetry rows to the compact layout.", migrated)

    # ------------------------------------------------------------------ transitions
    async def record_transitions(self, transitions: list[Transition]) -> int:
        if not transitions:
            return 0
        rows = [
            (self._eid(t.entity_id), _epoch(t.ts), self._sid(t.new_state), self._sid(t.old_state or ""), _ORIGIN_ID.get(t.origin, 0))
            for t in transitions
        ]
        before = self._conn.total_changes
        # dictionary inserts above are part of the same transaction; count only the row inserts
        self._conn.executemany("INSERT OR IGNORE INTO tr (e, ts, s, p, o) VALUES (?,?,?,?,?)", rows)
        added = self._conn.total_changes - before
        self._conn.commit()
        first = datetime.fromtimestamp(min(r[1] for r in rows), UTC).isoformat()
        current = await self.get_meta("observed_since")
        if current is None or first < current:
            await self.set_meta("observed_since", first)
        return added

    async def get_transitions(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        entity_ids: list[str] | None = None,
    ) -> list[Transition]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("ts >= ?")
            params.append(_epoch(since))
        if until is not None:
            clauses.append("ts <= ?")
            params.append(_epoch(until))
        if entity_ids:
            ids = [self._ent[e] for e in entity_ids if e in self._ent]
            if not ids:
                return []
            clauses.append(f"e IN ({','.join('?' * len(ids))})")
            params.extend(ids)
        fire = self._st.get(AUTOMATION_FIRE_STATE)
        if fire is not None:
            clauses.append("s != ?")
            params.append(fire)
        sql = "SELECT e, ts, s, p, o FROM tr" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY ts"
        ent, st = self._ent_rev, self._st_rev
        return [
            Transition(ent[r[0]], datetime.fromtimestamp(r[1], UTC), st.get(r[3], ""), st.get(r[2], ""), ORIGINS[r[4]] if r[4] < len(ORIGINS) else "unknown")
            for r in self._conn.execute(sql, params)
        ]

    async def get_all_fires(self, since: datetime | None = None) -> list[Transition]:
        s = self._st.get(AUTOMATION_FIRE_STATE)
        if s is None:
            return []
        sql, params = "SELECT e, ts FROM tr WHERE s = ?", [s]
        if since is not None:
            sql += " AND ts >= ?"
            params.append(_epoch(since))
        ent = self._ent_rev
        return [
            Transition(ent[r[0]], datetime.fromtimestamp(r[1], UTC), "", AUTOMATION_FIRE_STATE, "ha_automation")
            for r in self._conn.execute(sql + " ORDER BY ts", params)
        ]

    async def get_fires(self, automation_entity_id: str, since: datetime | None = None) -> list[datetime]:
        e, s = self._ent.get(automation_entity_id), self._st.get(AUTOMATION_FIRE_STATE)
        if e is None or s is None:
            return []
        sql, params = "SELECT ts FROM tr WHERE e = ? AND s = ?", [e, s]
        if since is not None:
            sql += " AND ts >= ?"
            params.append(_epoch(since))
        return [datetime.fromtimestamp(r[0], UTC) for r in self._conn.execute(sql + " ORDER BY ts", params)]

    async def observation_window(self, now: datetime) -> tuple[datetime, datetime] | None:
        since = parse_iso(await self.get_meta("observed_since"))
        if since is None:
            row = self._conn.execute("SELECT MIN(ts) FROM tr").fetchone()
            since = datetime.fromtimestamp(row[0], UTC) if row and row[0] is not None else None
        return (since, ensure_utc(now)) if since else None

    async def latest_transition_ts(self) -> datetime | None:
        row = self._conn.execute("SELECT MAX(ts) FROM tr").fetchone()
        return datetime.fromtimestamp(row[0], UTC) if row and row[0] is not None else None

    async def count_since(self, since: datetime, entity_ids: list[str] | None = None) -> int:
        sql, params = "SELECT COUNT(*) FROM tr WHERE ts >= ?", [_epoch(since)]
        if entity_ids is not None:
            ids = [self._ent[e] for e in entity_ids if e in self._ent]
            if not ids:
                return 0
            sql += f" AND e IN ({','.join('?' * len(ids))})"
            params.extend(ids)
        return int(self._conn.execute(sql, params).fetchone()[0])

    # ------------------------------------------------------------------ numeric hourly aggregates
    async def record_numeric(self, rows: list[tuple[str, datetime, float]]) -> None:
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT INTO nh (e, h, n, total) VALUES (?,?,1,?)
            ON CONFLICT(e, h) DO UPDATE SET n = n + 1, total = total + excluded.total
            """,
            [(self._eid(eid), _hour_index(ts), float(v)) for eid, ts, v in rows],
        )
        self._conn.commit()

    async def record_numeric_hourly(self, rows: list[tuple[str, datetime, int, float]]) -> None:
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT INTO nh (e, h, n, total) VALUES (?,?,?,?)
            ON CONFLICT(e, h) DO UPDATE SET n = n + excluded.n, total = total + excluded.total
            """,
            [(self._eid(eid), _hour_index(ts), int(n), float(total)) for eid, ts, n, total in rows],
        )
        self._conn.commit()

    async def replace_numeric_since(self, since: datetime) -> None:
        self._conn.execute("DELETE FROM nh WHERE h >= ?", (_hour_index(since),))
        self._conn.commit()

    async def get_numeric_hours(self, entity_id: str, since: datetime | None = None) -> list[tuple[str, int, float]]:
        e = self._ent.get(entity_id)
        if e is None:
            return []
        sql, params = "SELECT h, n, total FROM nh WHERE e = ?", [e]
        if since is not None:
            sql += " AND h >= ?"
            params.append(_hour_index(since))
        return [(self._iso_hour(r[0]), int(r[1]), float(r[2]) / max(1, int(r[1]))) for r in self._conn.execute(sql + " ORDER BY h", params)]

    async def get_all_numeric_hours(self, since: datetime | None = None) -> dict[str, list[tuple[str, int, float]]]:
        sql, params = "SELECT e, h, n, total FROM nh", []
        if since is not None:
            sql += " WHERE h >= ?"
            params.append(_hour_index(since))
        out: dict[str, list[tuple[str, int, float]]] = {}
        for r in self._conn.execute(sql + " ORDER BY e, h", params):
            out.setdefault(self._ent_rev[r[0]], []).append((self._iso_hour(r[1]), int(r[2]), float(r[3]) / max(1, int(r[2]))))
        return out

    # ------------------------------------------------------------------ housekeeping
    async def prune(self, retention_days: int, now: datetime) -> int:
        cutoff = ensure_utc(now) - timedelta(days=retention_days)
        a = self._conn.execute("DELETE FROM tr WHERE ts < ?", (_epoch(cutoff),)).rowcount
        b = self._conn.execute("DELETE FROM nh WHERE h < ?", (_hour_index(cutoff),)).rowcount
        self._conn.commit()
        return a + b

    async def maintain(self) -> None:
        run_maintenance(self._conn)

    async def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM telemetry_meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    async def set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO telemetry_meta (key, value) VALUES (?, ?)", (key, value))
        self._conn.commit()

    async def stats(self) -> dict[str, Any]:
        fire = self._st.get(AUTOMATION_FIRE_STATE, -1)
        t = self._conn.execute("SELECT COUNT(*), COUNT(DISTINCT e) FROM tr WHERE s != ?", (fire,)).fetchone()
        h = self._conn.execute("SELECT COUNT(*), COUNT(DISTINCT e) FROM nh").fetchone()
        return {
            "transitions": int(t[0]),
            "entities_with_transitions": int(t[1]),
            "numeric_hours": int(h[0]),
            "entities_with_numeric": int(h[1]),
        }
