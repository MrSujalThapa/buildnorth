"""Deterministic as-of selection over published forecast receipts.

Publication time, evidence observation time, and ingestion time are kept distinct.
Deltas are percentage points (later - earlier) * 100, never relative percent change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from personal_markets.forecasting.repository import PublishedBaseline

RelativeAsOf = Literal["latest", "previous", "last_week", "before_evidence"]


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
    if relative == "last_week":
        bound = now - timedelta(days=7)
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
