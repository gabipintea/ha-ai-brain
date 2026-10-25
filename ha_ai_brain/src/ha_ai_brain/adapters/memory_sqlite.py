"""SQLite Persistence Adapter for Episodic Feedback Memory, Repeatable Approval Rules & Run Logs."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from typing import Any

from ha_ai_brain.domain.models import (
    AdvisoryInsight,
    AgentRunLog,
    ApprovalRule,
    ExpectedOutcome,
    FeedbackEpisode,
    FeedbackPolarity,
    IgnoredTarget,
    PendingApproval,
    UserContextNote,
)
from ha_ai_brain.ports.memory import MemoryStorePort


class SQLiteMemoryAdapter(MemoryStorePort):
    """
    Stores feedback loops, endorsed repeatable action signatures, pending approvals,
    advisory insights, and full agent reasoning logs in a local SQLite database.
    """

    def __init__(self, db_path: str = "ha_ai_brain.db") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS feedback_episodes (
                episode_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                area_id TEXT,
                action_signature TEXT NOT NULL,
                polarity TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approval_rules (
                signature TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                auto_approve INTEGER NOT NULL,
                execution_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_approvals (
                approval_id TEXT PRIMARY KEY,
                signature TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS run_logs (
                run_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS advisory_insights (
                insight_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS expected_outcomes (
                outcome_id TEXT PRIMARY KEY,
                action_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_context_notes (
                note_id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ignored_targets (
                ignore_id TEXT PRIMARY KEY,
                pattern TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ui_preferences (
                pref_key TEXT PRIMARY KEY,
                pref_value TEXT NOT NULL
            );
            """
        )

        # Migration: Add status column to existing advisory_insights table if upgrading from < v0.1.10
        try:
            columns_info = cur.execute("PRAGMA table_info(advisory_insights)").fetchall()
            existing_cols = {col[1] for col in columns_info}
            if "status" not in existing_cols:
                cur.execute("ALTER TABLE advisory_insights ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        except Exception:
            pass

        # Create indexes only after all tables and columns are guaranteed to exist
        cur.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status);
            CREATE INDEX IF NOT EXISTS idx_run_logs_created ON run_logs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_advisory_insights_created ON advisory_insights(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_advisory_insights_status ON advisory_insights(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_episodes_agent ON feedback_episodes(agent_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_context_notes_active ON user_context_notes(active, created_at DESC);
            """
        )
        self._conn.commit()

    async def save_feedback(self, episode: FeedbackEpisode) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO feedback_episodes
            (episode_id, agent_id, area_id, action_signature, polarity, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode.episode_id,
                episode.agent_id,
                episode.area_id,
                episode.action_signature,
                episode.polarity.value,
                episode.created_at.isoformat(),
                episode.model_dump_json(),
            ),
        )
        self._conn.commit()

    async def get_relevant_feedback(
        self,
        agent_id: str,
        area_id: str | None = None,
        limit: int = 20,
    ) -> list[FeedbackEpisode]:
        if area_id:
            rows = self._conn.execute(
                """
                SELECT payload_json FROM feedback_episodes
                WHERE agent_id = ? AND (area_id = ? OR area_id IS NULL)
                ORDER BY created_at DESC LIMIT ?
                """,
                (agent_id, area_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT payload_json FROM feedback_episodes
                WHERE agent_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [FeedbackEpisode.model_validate_json(r["payload_json"]) for r in rows]

    async def save_approval_rule(self, rule: ApprovalRule) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO approval_rules
            (signature, agent_id, auto_approve, execution_count, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                rule.signature,
                rule.agent_id,
                1 if rule.auto_approve else 0,
                rule.execution_count,
                rule.created_at.isoformat(),
                rule.model_dump_json(),
            ),
        )
        self._conn.commit()

    async def increment_rule_usage(self, signature: str) -> None:
        row = self._conn.execute(
            "SELECT payload_json FROM approval_rules WHERE signature = ?",
            (signature,),
        ).fetchone()
        if not row:
            return
        rule = ApprovalRule.model_validate_json(row["payload_json"])
        rule.execution_count += 1
        await self.save_approval_rule(rule)

    async def get_endorsed_rules(self) -> dict[str, ApprovalRule]:
        rows = self._conn.execute("SELECT payload_json FROM approval_rules WHERE auto_approve = 1").fetchall()
        rules: dict[str, ApprovalRule] = {}
        for r in rows:
            rule = ApprovalRule.model_validate_json(r["payload_json"])
            rules[rule.signature] = rule
        return rules

    async def delete_approval_rule(self, signature: str) -> bool:
        cur = self._conn.execute("DELETE FROM approval_rules WHERE signature = ?", (signature,))
        self._conn.commit()
        return cur.rowcount > 0

    async def get_rejected_suggestions(self) -> list[FeedbackEpisode]:
        rows = self._conn.execute(
            "SELECT payload_json FROM feedback_episodes WHERE polarity = ? ORDER BY created_at DESC",
            (FeedbackPolarity.REJECTED_EXPLICIT.value,),
        ).fetchall()
        seen: set[str] = set()
        latest: list[FeedbackEpisode] = []
        for r in rows:
            ep = FeedbackEpisode.model_validate_json(r["payload_json"])
            if ep.action_signature in seen:
                continue
            seen.add(ep.action_signature)
            latest.append(ep)
        return latest

    async def unblock_rejected_signature(self, signature: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM feedback_episodes WHERE action_signature = ? AND polarity = ?",
            (signature, FeedbackPolarity.REJECTED_EXPLICIT.value),
        )
        self._conn.commit()
        return cur.rowcount > 0

    async def get_rejected_signatures(self) -> set[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT action_signature FROM feedback_episodes WHERE polarity = ?",
            (FeedbackPolarity.REJECTED_EXPLICIT.value,),
        ).fetchall()
        return {str(r["action_signature"]) for r in rows}

    async def save_pending_approval(self, pending: PendingApproval) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pending_approvals
            (approval_id, signature, status, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                pending.approval_id,
                pending.signature,
                pending.status,
                pending.created_at.isoformat(),
                pending.model_dump_json(),
            ),
        )
        self._conn.commit()

    async def get_pending_approvals(self) -> list[PendingApproval]:
        rows = self._conn.execute(
            "SELECT payload_json FROM pending_approvals WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        return [PendingApproval.model_validate_json(r["payload_json"]) for r in rows]

    async def resolve_pending_approval(self, approval_id: str, status: str) -> PendingApproval | None:
        row = self._conn.execute(
            "SELECT payload_json FROM pending_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if not row:
            return None
        pending = PendingApproval.model_validate_json(row["payload_json"])
        pending.status = status
        pending.resolved_at = datetime.now(timezone.utc)
        await self.save_pending_approval(pending)
        return pending

    async def dismiss_pending_approval(self, approval_id: str) -> bool:
        """Dismiss a pending proposal without executing or adding to rejected memory."""
        res = await self.resolve_pending_approval(approval_id=approval_id, status="dismissed")
        return res is not None

    async def dismiss_all_pending_approvals(self) -> int:
        """Dismiss all pending proposals in one shot."""
        rows = self._conn.execute(
            "SELECT approval_id, payload_json FROM pending_approvals WHERE status = 'pending'"
        ).fetchall()
        now = datetime.now(timezone.utc)
        count = 0
        for r in rows:
            pending = PendingApproval.model_validate_json(r["payload_json"])
            pending.status = "dismissed"
            pending.resolved_at = now
            await self.save_pending_approval(pending)
            count += 1
        return count

    async def save_run_log(self, log: AgentRunLog) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO run_logs
            (run_id, agent_id, mode, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                log.run_id,
                log.agent_id,
                log.mode,
                log.created_at.isoformat(),
                log.model_dump_json(),
            ),
        )
        # Keep recent 300 logs in SQLite to prevent unbound storage growth
        self._conn.execute(
            """
            DELETE FROM run_logs WHERE run_id NOT IN (
                SELECT run_id FROM run_logs ORDER BY created_at DESC LIMIT 300
            )
            """
        )
        self._conn.commit()

    async def get_recent_run_logs(self, limit: int = 25, offset: int = 0) -> list[AgentRunLog]:
        rows = self._conn.execute(
            "SELECT payload_json FROM run_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [AgentRunLog.model_validate_json(r["payload_json"]) for r in rows]

    async def get_run_log(self, run_id: str) -> AgentRunLog | None:
        row = self._conn.execute(
            "SELECT payload_json FROM run_logs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        return AgentRunLog.model_validate_json(row["payload_json"])

    async def get_run_logs_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM run_logs").fetchone()
        return int(row[0]) if row else 0

    async def clear_run_logs(self) -> int:
        cur = self._conn.execute("DELETE FROM run_logs")
        self._conn.commit()
        return cur.rowcount

    async def save_advisory_insight(self, insight: AdvisoryInsight) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO advisory_insights
            (insight_id, agent_id, status, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                insight.insight_id,
                insight.agent_id,
                insight.status,
                insight.created_at.isoformat(),
                insight.model_dump_json(),
            ),
        )
        self._conn.commit()

    async def get_advisory_insights(self, limit: int = 50, status: str | None = None) -> list[AdvisoryInsight]:
        if status:
            rows = self._conn.execute(
                "SELECT payload_json FROM advisory_insights WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT payload_json FROM advisory_insights ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [AdvisoryInsight.model_validate_json(r["payload_json"]) for r in rows]

    async def get_active_insights_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM advisory_insights WHERE status = 'active'").fetchone()
        return int(row[0]) if row else 0

    async def resolve_advisory_insight(self, insight_id: str, status: str, rejection_reason: str = "") -> AdvisoryInsight | None:
        row = self._conn.execute(
            "SELECT payload_json FROM advisory_insights WHERE insight_id = ?",
            (insight_id,),
        ).fetchone()
        if not row:
            return None
        insight = AdvisoryInsight.model_validate_json(row["payload_json"])
        insight.status = status
        if rejection_reason:
            insight.rejection_reason = rejection_reason
        insight.resolved_at = datetime.now(timezone.utc)
        await self.save_advisory_insight(insight)
        return insight

    async def delete_advisory_insight(self, insight_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM advisory_insights WHERE insight_id = ?", (insight_id,))
        self._conn.commit()
        return cur.rowcount > 0

    async def dismiss_all_advisory_insights(self) -> int:
        rows = self._conn.execute("SELECT payload_json FROM advisory_insights WHERE status = 'active'").fetchall()
        now = datetime.now(timezone.utc)
        count = 0
        for r in rows:
            insight = AdvisoryInsight.model_validate_json(r["payload_json"])
            insight.status = "dismissed"
            insight.resolved_at = now
            await self.save_advisory_insight(insight)
            count += 1
        return count

    async def delete_all_advisory_insights(self, status: str | None = None) -> int:
        if status:
            cur = self._conn.execute("DELETE FROM advisory_insights WHERE status = ?", (status,))
        else:
            cur = self._conn.execute("DELETE FROM advisory_insights")
        self._conn.commit()
        return cur.rowcount

    async def get_rejected_insights(self) -> list[AdvisoryInsight]:
        rows = self._conn.execute(
            "SELECT payload_json FROM advisory_insights WHERE status = 'rejected' ORDER BY created_at DESC"
        ).fetchall()
        return [AdvisoryInsight.model_validate_json(r["payload_json"]) for r in rows]

    async def unblock_rejected_insight(self, insight_id: str) -> bool:
        row = self._conn.execute(
            "SELECT payload_json FROM advisory_insights WHERE insight_id = ?",
            (insight_id,),
        ).fetchone()
        if not row:
            return False
        insight = AdvisoryInsight.model_validate_json(row["payload_json"])
        # Also remove associated FeedbackEpisode if any
        sig = f"insight:{insight.category}:{insight.title}"
        self._conn.execute(
            "DELETE FROM feedback_episodes WHERE action_signature = ?",
            (sig,),
        )
        cur = self._conn.execute(
            "UPDATE advisory_insights SET status = 'dismissed' WHERE insight_id = ?",
            (insight_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    async def save_expected_outcome(self, outcome: ExpectedOutcome) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO expected_outcomes
            (outcome_id, action_id, status, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                outcome.outcome_id,
                outcome.action_id,
                outcome.status,
                outcome.model_dump_json(),
            ),
        )
        self._conn.commit()

    async def save_user_context_note(self, note: UserContextNote) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO user_context_notes
            (note_id, scope, active, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                note.note_id,
                note.scope,
                1 if note.active else 0,
                note.created_at.isoformat(),
                note.model_dump_json(),
            ),
        )
        self._conn.commit()

    async def get_user_context_notes(self, active_only: bool = True) -> list[UserContextNote]:
        if active_only:
            rows = self._conn.execute(
                "SELECT payload_json FROM user_context_notes WHERE active = 1 ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT payload_json FROM user_context_notes ORDER BY created_at DESC"
            ).fetchall()
        return [UserContextNote.model_validate_json(r["payload_json"]) for r in rows]

    async def delete_user_context_note(self, note_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM user_context_notes WHERE note_id = ?",
            (note_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    async def save_ignored_target(self, target: IgnoredTarget) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ignored_targets
            (ignore_id, pattern, created_at, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                target.ignore_id,
                target.pattern,
                target.created_at.isoformat(),
                target.model_dump_json(),
            ),
        )
        self._conn.commit()

    async def get_ignored_targets(self) -> list[IgnoredTarget]:
        rows = self._conn.execute(
            "SELECT payload_json FROM ignored_targets ORDER BY created_at DESC"
        ).fetchall()
        return [IgnoredTarget.model_validate_json(r["payload_json"]) for r in rows]

    async def delete_ignored_target(self, ignore_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM ignored_targets WHERE ignore_id = ?",
            (ignore_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    async def save_ui_preference(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO ui_preferences (pref_key, pref_value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def get_ui_preferences_sync(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT pref_key, pref_value FROM ui_preferences").fetchall()
        return {str(r["pref_key"]): str(r["pref_value"]) for r in rows}

    async def get_ui_preferences(self) -> dict[str, str]:
        return self.get_ui_preferences_sync()
