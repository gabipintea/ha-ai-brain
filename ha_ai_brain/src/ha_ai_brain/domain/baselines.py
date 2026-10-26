"""Hour-of-day baselines for numeric sensors, used to decide whether a reading is actually unusual."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, tzinfo

from ha_ai_brain.domain.timeutil import day_class, to_local, parse_iso


class NumericBaseline:
    """Mean / spread of an entity's hourly averages per (day class, local hour)."""

    def __init__(self, rows: list[tuple[str, int, float]], tz: tzinfo) -> None:
        # rows: (hour_ts ISO, sample count, hourly mean)
        self.tz = tz
        buckets: dict[tuple[str, int], list[float]] = defaultdict(list)
        for hour_ts, n, mean in rows:
            ts = parse_iso(hour_ts)
            if ts is None or n <= 0:
                continue
            local = to_local(ts, tz)
            buckets[(day_class(local), local.hour)].append(mean)
        self.stats: dict[tuple[str, int], tuple[int, float, float]] = {}
        for key, values in buckets.items():
            mean = sum(values) / len(values)
            std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) if len(values) > 1 else 0.0
            self.stats[key] = (len(values), mean, std)

    def zscore(self, value: float, at: datetime, min_samples: int = 6) -> float | None:
        local = to_local(at, self.tz)
        stat = self.stats.get((day_class(local), local.hour))
        if stat is None or stat[0] < min_samples:
            return None
        n, mean, std = stat
        # Floor the spread so a perfectly flat history does not turn tiny changes into "infinite" anomalies.
        floor = max(0.5, abs(mean) * 0.03)
        return (value - mean) / max(std, floor)
