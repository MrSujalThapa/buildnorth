"""Deterministic as-of selection over published forecast receipts.

Publication time, evidence observation time, and ingestion time are kept distinct.
Deltas are percentage points (later - earlier) * 100, never relative percent change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from personal_markets.forecasting.repository import PublishedBaseline

# Rolling window, not a calendar month, so the bound does not depend on the day of month.
MONTH_WINDOW_DAYS = 30

RelativeAsOf = Literal[
    "latest",
    "previous",
    "last_week",
    "this_month",
    "since_start",
    "before_evidence",
]
MoveDirection = Literal["increase", "drop"]


def direction_for(relative: str) -> MoveDirection:
    """Map a compare_forecasts selector onto a successive published step."""
    if relative == "largest_increase":
        return "increase"
    if relative == "largest_drop":
        return "drop"
    raise ValueError("relative is not a published-step direction")


def parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("as_of must be ISO-8601") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def sort_history(history: list[PublishedBaseline]) -> list[PublishedBaseline]:
    def key(item: PublishedBaseline) -> tuple[datetime, str]:
        when = item.published_at or datetime.min.replace(tzinfo=UTC)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return (when, item.evidence_watermark)

    return sorted(history, key=key)


def publication_time(item: PublishedBaseline) -> datetime | None:
    when = item.published_at
    if when is None:
        return None
    if when.tzinfo is None:
        return when.replace(tzinfo=UTC)
    return when


def select_as_of(
    history: list[PublishedBaseline],
    *,
    as_of: datetime | None,
    relative: RelativeAsOf | None,
    evidence_observed_at: datetime | None,
    now: datetime,
) -> tuple[PublishedBaseline | None, str]:
    """Return the latest published receipt at or before the requested bound.

    The second value is a short reason when none exists.
    """
    ordered = sort_history(history)
    if not ordered:
        return None, "No forecast has been published for this goal."

    if relative == "latest" or (as_of is None and relative is None):
        return ordered[-1], ""
    if relative == "previous":
        if len(ordered) < 2:
            return None, "There is no earlier published forecast to compare against."
        return ordered[-2], ""

    bound = as_of
    if relative == "since_start":
        dated = [item for item in ordered if publication_time(item) is not None]
        if not dated:
            return None, "No forecast has a publication time."
        return dated[0], ""
    if relative == "last_week":
        bound = now - timedelta(days=7)
    elif relative == "this_month":
        bound = now - timedelta(days=MONTH_WINDOW_DAYS)
    elif relative == "before_evidence":
        if evidence_observed_at is None:
            raise ValueError(
                "before_evidence requires evidence_id so PlayItOut can use that "
                "event's observed_at, not the ingestion or publication time."
            )
        bound = evidence_observed_at

    if bound is None:
        return ordered[-1], ""
    if bound.tzinfo is None:
        bound = bound.replace(tzinfo=UTC)

    eligible = [
        item
        for item in ordered
        if (published := publication_time(item)) is not None and published <= bound
    ]
    if not eligible:
        return None, (
            "No forecast was published at or before that time. PlayItOut will not "
            "invent an earlier probability."
        )
    return eligible[-1], ""


def delta_pp(later: float, earlier: float) -> float:
    """Signed change in percentage points, not a relative percent."""
    return (later - earlier) * 100.0


def largest_consecutive_move(
    history: list[PublishedBaseline], *, direction: MoveDirection
) -> tuple[PublishedBaseline, PublishedBaseline] | None:
    """Largest step between two successive published receipts.

    Ties keep the later pair. Flat steps are not a move. Nothing is interpolated.
    """
    ordered = sort_history(history)
    best: tuple[PublishedBaseline, PublishedBaseline] | None = None
    best_magnitude = -1.0
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        delta = delta_pp(later.probability, earlier.probability)
        if direction == "increase" and delta <= 0:
            continue
        if direction == "drop" and delta >= 0:
            continue
        magnitude = abs(delta)
        if magnitude >= best_magnitude:
            best = (earlier, later)
            best_magnitude = magnitude
    return best


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def evidence_observed_in_window(
    stamps: list[dict[str, Any]],
    *,
    after: datetime | None,
    until: datetime | None,
) -> list[dict[str, Any]]:
    """Evidence whose observation time falls strictly after `after` and at or before `until`.

    Rows without `observed_at` are omitted. Ingestion time is never used as the event time.
    """
    lower = _aware(after) if after is not None else None
    upper = _aware(until) if until is not None else None
    kept: list[dict[str, Any]] = []
    for stamp in stamps:
        observed = stamp.get("observed_at")
        if not isinstance(observed, datetime):
            continue
        observed = _aware(observed)
        if lower is not None and observed <= lower:
            continue
        if upper is not None and observed > upper:
            continue
        kept.append(stamp)
    return kept


def point_view(item: PublishedBaseline) -> dict[str, Any]:
    published = publication_time(item)
    return {
        "probability": item.probability,
        "forecast_status": item.forecast_status,
        "model_family": item.model_family,
        "model_version": item.model_version,
        "evidence_watermark": item.evidence_watermark,
        "published_at": published.isoformat() if published else None,
        "receipt_id": str(item.material_hash),
        "source_kind": item.source_kind,
    }


def parse_uuid(value: str, *, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise ValueError(f"{field} must be a UUID") from None
