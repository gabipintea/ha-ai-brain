"""Shared SQLite housekeeping: WAL tuning, one-time switch to incremental auto-vacuum, and routine space reclaim."""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

JOURNAL_SIZE_LIMIT_BYTES = 8 * 1024 * 1024  # keeps the -wal file from lingering at its high-water mark


def configure_connection(conn: sqlite3.Connection) -> None:
    """WAL keeps readers non-blocking and survives unclean shutdowns; NORMAL sync avoids an fsync per commit."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA journal_size_limit={JOURNAL_SIZE_LIMIT_BYTES}")


def ensure_incremental_vacuum(conn: sqlite3.Connection, db_path: str) -> bool:
    """
    Make deleted rows actually shrink the database file. Switching the mode needs a one-time VACUUM, which rewrites the
    file (it needs free disk space about the size of the database); on any failure the database simply keeps working.
    """
    if not db_path or db_path == ":memory:":
        return False
    try:
        if conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2:
            return False
        conn.commit()
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("VACUUM")
        logger.info("Database switched to incremental auto-vacuum (one-time compaction done).")
        return True
    except sqlite3.Error as exc:
        logger.warning("Could not enable incremental auto-vacuum (continuing without it): %s", exc)
        return False


def run_maintenance(conn: sqlite3.Connection) -> None:
    """Return freed pages to the filesystem and truncate the write-ahead log."""
    try:
        conn.commit()
        conn.execute("PRAGMA incremental_vacuum").fetchall()  # the pragma frees pages as its rows are consumed
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        logger.warning("Database maintenance skipped: %s", exc)
