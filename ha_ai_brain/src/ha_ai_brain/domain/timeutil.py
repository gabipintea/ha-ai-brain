"""Timezone-aware helpers shared by pattern mining, expectations and backtesting."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@lru_cache(maxsize=16)
def resolve_tz(name: str) -> tzinfo:
    """Return a tzinfo for an IANA name, falling back to UTC for empty / unknown names."""
    if not name:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def to_local(ts: datetime, tz: tzinfo) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(tz)


def ensure_utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def parse_iso(value: str | datetime | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (including trailing Z) into an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def minute_of_day(local_ts: datetime) -> int:
    return local_ts.hour * 60 + local_ts.minute


def day_class(local_ts: datetime | date) -> str:
    """'weekend' for Saturday/Sunday, else 'weekday'."""
    weekday = local_ts.weekday()
    return "weekend" if weekday >= 5 else "weekday"


def circular_distance(a: float, b: float, period: int = 1440) -> float:
    d = abs(a - b) % period
    return min(d, period - d)


def circular_mean(minutes: list[int], period: int = 1440) -> float:
    """Mean of times on a clock face (handles clusters straddling midnight)."""
    import math

    if not minutes:
        return 0.0
    angles = [2 * math.pi * m / period for m in minutes]
    x = sum(math.cos(a) for a in angles)
    y = sum(math.sin(a) for a in angles)
    return (math.atan2(y, x) % (2 * math.pi)) * period / (2 * math.pi)


def format_minute(minute: float) -> str:
    m = int(round(minute)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_hhmm(value: str | None) -> int | None:
    """'HH:MM' or 'HH:MM:SS' -> minute of day; None if invalid."""
    if not value or not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    try:
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def is_quiet_hours(now_local: datetime, start: str, end: str) -> bool:
    """True when `now_local` falls inside the [start, end) quiet window (supports windows crossing midnight)."""
    s, e = parse_hhmm(start), parse_hhmm(end)
    if s is None or e is None or s == e:
        return False
    cur = minute_of_day(now_local)
    return (s <= cur < e) if s < e else (cur >= s or cur < e)


def local_day_start(local_ts: datetime) -> datetime:
    return datetime.combine(local_ts.date(), time(0, 0), tzinfo=local_ts.tzinfo)


def local_at(day: date, minute: int, tz: tzinfo) -> datetime:
    return datetime.combine(day, time(minute // 60, minute % 60), tzinfo=tz)


def iter_days(start: datetime, end: datetime, tz: tzinfo):
    """Yield each local calendar date between two instants (inclusive)."""
    d = to_local(start, tz).date()
    last = to_local(end, tz).date()
    while d <= last:
        yield d
        d += timedelta(days=1)
