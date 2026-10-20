"""Portfolio summary over immutable published forecast histories."""

from __future__ import annotations

from datetime import UTC, datetime, time
from math import isfinite

from personal_markets.collections.domain import CollectionSeries


def portfolio_summary(
    series: list[CollectionSeries], *, now: datetime | None = None
) -> tuple[float | None, float | None, int]:
    """Return current mean odds, UTC calendar-day change in percentage points, coverage.

    Today's comparison uses exactly the currently eligible goals. If any of them
    lacks a published point before the UTC day boundary, no change is reported.
    """
    as_of = (now or datetime.now(UTC)).astimezone(UTC)
    day_start = datetime.combine(as_of.date(), time.min, UTC)
    current: list[float] = []
    previous: list[float] = []
    for item in series:
        if item.withheld:
            continue
        points: list[tuple[datetime, float]] = []
        for point in item.points:
            try:
                timestamp = datetime.fromisoformat(str(point["timestamp"]).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    continue
                value = float(point["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if timestamp <= as_of and isfinite(value) and 0 <= value <= 100:
                points.append((timestamp.astimezone(UTC), value))
        if not points:
            continue
        points.sort(key=lambda point: point[0])
        current.append(points[-1][1])
        earlier = [value for timestamp, value in points if timestamp < day_start]
        if earlier:
            previous.append(earlier[-1])
    if not current:
        return None, None, 0
    odds = sum(current) / len(current)
    change = odds - sum(previous) / len(previous) if len(previous) == len(current) else None
    return odds, change, len(current)
