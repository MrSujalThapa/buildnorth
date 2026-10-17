"""Canonical evidence metric names and observation kinds.

Agents and forms emit equivalent labels for the same state variable. Normalization
happens at ingest so fingerprints and model inputs share one vocabulary.

Observation kinds:
- snapshot: absolute stock ("applications submitted so far is 18"). Latest value wins.
- increment: a dated occurrence ("sent 1 application today"). Sum occurrences.
- period: a measurement for a week or month. One value per period; periods do not collapse.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from personal_markets.ports import EvidenceEventProposal

ObservationKind = Literal["snapshot", "increment", "period"]

# Map observed labels onto the vocabulary already used by model families.
_METRIC_ALIASES: dict[str, str] = {
    "application": "applications_submitted",
    "applications": "applications_submitted",
    "application_count": "applications_submitted",
    "applications_sent": "applications_submitted",
    "apps_submitted": "applications_submitted",
    "job_applications": "applications_submitted",
    "job_applications_submitted": "applications_submitted",
    "monthly_recurring_revenue": "mrr",
    "revenue_monthly": "mrr",
    "weekly_mileage": "weekly_distance_km",
    "weekly_distance": "weekly_distance_km",
    "runway": "runway_months",
    "monthly_burn": "burn_monthly",
    "burn": "burn_monthly",
}

_SNAPSHOT_METRICS = frozenset(
    {
        "applications_submitted",
        "current_balance",
        "net_worth",
        "liquid_assets",
        "runway_months",
    }
)

_PERIOD_METRICS = frozenset(
    {
        "weekly_distance_km",
        "monthly_income",
        "monthly_expenses",
        "monthly_contribution",
        "burn_monthly",
        "mrr",
    }
)

# Occurrence rows, not restated stocks. Snapshot metrics still default to snapshot
# unless the event type marks a dated increment.
_INCREMENT_EVENT_TYPES = frozenset(
    {
        "increment",
        "occurrence",
        "applied",
        "application_sent",
        "delta",
    }
)


def canonicalize_metric(metric: str) -> str:
    normalized = metric.strip().lower().replace(" ", "_").replace("-", "_")
    normalized = "_".join(part for part in normalized.split("_") if part)
    return _METRIC_ALIASES.get(normalized, normalized)


def is_snapshot_metric(metric: str) -> bool:
    return canonicalize_metric(metric) in _SNAPSHOT_METRICS


def is_period_metric(metric: str) -> bool:
    return canonicalize_metric(metric) in _PERIOD_METRICS


def parse_observed_at(value: str | None) -> datetime | None:
    if not value or value.lower() in {"unknown", "unspecified"}:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def observation_kind(
    metric: str,
    event_type: str,
) -> ObservationKind:
    canonical = canonicalize_metric(metric)
    normalized_type = event_type.strip().lower()
    if canonical in _PERIOD_METRICS:
        return "period"
    if normalized_type in _INCREMENT_EVENT_TYPES:
        return "increment"
    if normalized_type == "manual_state_entry" or canonical in _SNAPSHOT_METRICS:
        return "snapshot"
    return "increment"


def reduce_stock_value(
    observations: list[tuple[datetime, float, ObservationKind]],
) -> float:
    """Latest snapshot/period wins; dated increments after that snapshot still add."""
    if not observations:
        return 0.0
    snapshots = [item for item in observations if item[2] in {"snapshot", "period"}]
    increments = [item for item in observations if item[2] == "increment"]
    if not snapshots:
        return float(sum(item[1] for item in increments))
    latest = max(snapshots, key=lambda item: item[0])
    extra = sum(item[1] for item in increments if item[0] > latest[0])
    return float(latest[1] + extra)


def latest_metric_value(
    evidence: list[Any],
    metric: str,
) -> float | None:
    """Most recent numeric reading for a metric, using observed_at rather than insert order."""
    canonical = canonicalize_metric(metric)
    dated: list[tuple[datetime, float]] = []
    for item in evidence:
        if canonicalize_metric(getattr(item, "metric", "")) != canonical:
            continue
        value = getattr(item, "numeric_value", None)
        if value is None:
            continue
        observed = getattr(item, "observed_at", None) or datetime.min.replace(tzinfo=UTC)
        dated.append((observed, float(value)))
    if not dated:
        return None
    dated.sort(key=lambda item: item[0])
    return dated[-1][1]


def period_key(kind: ObservationKind, metric: str, observed_at: datetime | None) -> str:
    if observed_at is None or kind == "snapshot":
        return ""
    if kind == "period":
        canonical = canonicalize_metric(metric)
        if canonical.startswith("weekly_"):
            iso = observed_at.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        return observed_at.strftime("%Y-%m")
    return observed_at.date().isoformat()


def canonicalize_event(event: EvidenceEventProposal) -> EvidenceEventProposal:
    canonical = canonicalize_metric(event.metric)
    if canonical == event.metric:
        return event
    return event.model_copy(update={"metric": canonical})
