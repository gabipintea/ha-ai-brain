"""Port for the compact, long-retention telemetry store that powers pattern mining and baselines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from ha_ai_brain.domain.models import Transition

AUTOMATION_FIRE_STATE = "__triggered__"


class TelemetryStorePort(ABC):
    """Keeps discrete state transitions and hourly numeric aggregates well beyond Home Assistant's recorder window."""

    @abstractmethod
    async def record_transitions(self, transitions: list[Transition]) -> int:
        """Idempotently store transitions; returns how many were new."""

    @abstractmethod
    async def record_numeric(self, rows: list[tuple[str, datetime, float]]) -> None:
        """Add (entity_id, timestamp, value) samples to the hourly aggregates."""

    @abstractmethod
    async def record_numeric_hourly(self, rows: list[tuple[str, datetime, int, float]]) -> None:
        """Add pre-aggregated (entity_id, hour, sample count, sum) rows to the hourly aggregates."""

    @abstractmethod
    async def replace_numeric_since(self, since: datetime) -> None:
        """Drop numeric aggregates from the hour of `since` onward (before re-importing that window from history)."""

    @abstractmethod
    async def get_transitions(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        entity_ids: list[str] | None = None,
    ) -> list[Transition]:
        """Transitions ordered by time."""

    @abstractmethod
    async def get_numeric_hours(self, entity_id: str, since: datetime | None = None) -> list[tuple[str, int, float]]:
        """(hour_ts ISO, sample count, hourly mean) rows."""

    @abstractmethod
    async def get_all_numeric_hours(self, since: datetime | None = None) -> dict[str, list[tuple[str, int, float]]]:
        """Hourly rows for every numeric entity in one query."""

    @abstractmethod
    async def get_fires(self, automation_entity_id: str, since: datetime | None = None) -> list[datetime]:
        """Recorded run times of an automation entity."""

    async def get_all_fires(self, since: datetime | None = None) -> list[Transition]:
        """Every recorded automation / script run as a Transition (new_state == AUTOMATION_FIRE_STATE). Default: none."""
        return []

    @abstractmethod
    async def observation_window(self, now: datetime) -> tuple[datetime, datetime] | None:
        """(first observed, now) or None when nothing was recorded yet."""

    @abstractmethod
    async def latest_transition_ts(self) -> datetime | None: ...

    @abstractmethod
    async def count_since(self, since: datetime, entity_ids: list[str] | None = None) -> int:
        """Transitions since `since`, optionally only for the given entities."""

    async def maintain(self) -> None:
        """Reclaim free pages and truncate the write-ahead log (default: nothing to do)."""

    @abstractmethod
    async def prune(self, retention_days: int, now: datetime) -> int: ...

    @abstractmethod
    async def get_meta(self, key: str) -> str | None: ...

    @abstractmethod
    async def set_meta(self, key: str, value: str) -> None: ...

    @abstractmethod
    async def stats(self) -> dict[str, Any]: ...
