"""Canonical evidence metric names and observation kinds.

Agents and forms emit equivalent labels for the same state variable. Normalization
happens at ingest so fingerprints and model inputs share one vocabulary.

Observation kinds:
- snapshot: absolute stock ("applications submitted so far is 18"). Latest value wins.
- increment: a dated occurrence ("sent 1 application today"). Sum occurrences.
- period: a measurement for a week or month. One value per period; periods do not collapse.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from personal_markets.ports import EvidenceEventProposal

ObservationKind = Literal["snapshot", "increment", "period", "rate", "continuous", "categorical"]

# Map observed labels onto the vocabulary already used by model families.
_METRIC_ALIASES: dict[str, str] = {
    "application": "applications_submitted",
    "applications": "applications_submitted",
    "application_count": "applications_submitted",
    "applications_submitted_count": "applications_submitted",
    "applications_sent": "applications_submitted",
    "apps_submitted": "applications_submitted",
    "job_applications": "applications_submitted",
    "job_applications_submitted": "applications_submitted",
    "product_launch": "launched",
    "product_launched": "launched",
    "launch_status": "launched",
    "launch_date": "launched",
    "product_launch_date": "launched",
    "number_of_paying_customers": "customers",
    "paying_customer_count": "customers",
    "monthly_recurring_revenue": "mrr",
    "monthly_recurring_revenue_usd": "mrr",
    "revenue_monthly": "mrr",
    "weekly_mileage": "weekly_distance_km",
    "weekly_distance": "weekly_distance_km",
    "runway": "runway_months",
    "monthly_burn": "burn_monthly",
    "burn": "burn_monthly",
    "subscribers": "subscribers",
    "subscriber_count": "subscribers",
    "youtube_subscribers": "subscribers",
    "follower_count": "subscribers",
    "followers": "subscribers",
    "countries": "countries_visited",
    "countries_visited": "countries_visited",
    "country_count": "countries_visited",
    "customers": "customers",
    "paying_customers": "customers",
    "customer_count": "customers",
    "mrr_usd": "mrr",
}

_SNAPSHOT_METRICS = frozenset(
    {
        "applications_submitted",
        "current_balance",
        "net_worth",
        "liquid_assets",
        "runway_months",
        "subscribers",
        "countries_visited",
        "customers",
        "mrr",
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


_STOCK_CONCEPTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("subscriber", "follower"), "subscribers"),
    (("countr",), "countries_visited"),
    (("customer",), "customers"),
    (("mrr", "monthly_recurring_revenue"), "mrr"),
)
_RATE_LABEL_WORDS = frozenset(
    {"per", "rate", "gain", "gains", "growth", "frequency", "average", "avg", "velocity"}
)


def is_rate_label(label: str) -> bool:
    """True for labels that describe a flow or average rather than a stock level."""
    words = re.split(r"[^a-z0-9]+", label.lower())
    return any(word in _RATE_LABEL_WORDS for word in words)


def stock_concept(label: str) -> str | None:
    """Canonical stock metric a descriptive label refers to, when unambiguous."""
    normalized = canonicalize_metric(label)
    if normalized in _SNAPSHOT_METRICS:
        return normalized
    if is_rate_label(label):
        return None
    matches = {
        canonical
        for tokens, canonical in _STOCK_CONCEPTS
        if any(token in normalized for token in tokens)
    }
    return matches.pop() if len(matches) == 1 else None


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


def anchor_reported_today_increment(
    event: EvidenceEventProposal, received_at: datetime
) -> EvidenceEventProposal:
    """Use report receipt time for a same-day relative increment with date-only precision.

    A provider may turn "five more today" into midnight. Ordering that instant before
    a same-day snapshot silently loses the increment, although the later report says
    it is additional. Historical dates and precise timestamps retain their meaning.
    """
    if (
        event.source_type != "manual"
        or event.observation_kind != "increment"
        or not re.search(r"\btoday\b", event.summary, flags=re.IGNORECASE)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event.observed_at)
    ):
        return event
    try:
        stated_day = datetime.fromisoformat(event.observed_at).date()
    except ValueError:
        return event
    if abs((stated_day - received_at.date()).days) > 1:
        return event
    return event.model_copy(update={"observed_at": received_at.isoformat()})


METRIC_NAME_LIMIT = 80


def clip_metric_name(metric: str, limit: int = METRIC_NAME_LIMIT) -> str:
    return (metric or "").strip()[:limit]


def observation_kind(
    metric: str,
    event_type: str,
    explicit: str | None = None,
    unit: str | None = None,
) -> ObservationKind:
    if explicit == "event":
        return "increment"
    if explicit == "rate":
        return "period"
    if explicit in {"continuous", "categorical"}:
        return "snapshot"
    if explicit in {"snapshot", "increment", "period"}:
        return explicit  # type: ignore[return-value]
    if explicit == "uncertain":
        raise ValueError("Observation aggregation requires clarification")
    canonical = canonicalize_metric(metric)
    normalized_type = event_type.strip().lower()
    if normalized_type in _INCREMENT_EVENT_TYPES:
        return "increment"
    normalized_unit = (unit or "").lower().replace(" ", "")
    if any(
        token in normalized_unit
        for token in ("/week", "perweek", "/month", "permonth", "/day", "perday")
    ):
        return "period"
    if canonical in _PERIOD_METRICS:
        return "period"
    if normalized_type == "manual_state_entry" or canonical in _SNAPSHOT_METRICS:
        return "snapshot"
    return "increment"


def reduce_stock_value(
    observations: list[tuple[datetime, float, ObservationKind]],
) -> float:
    """Latest absolute snapshot wins; period rates never become stock totals."""
    if not observations:
        return 0.0
    snapshots = [item for item in observations if item[2] == "snapshot"]
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


def period_key(
    kind: ObservationKind, metric: str, observed_at: datetime | None, unit: str | None = None
) -> str:
    if observed_at is None or kind == "snapshot":
        return ""
    if kind == "period":
        canonical = canonicalize_metric(metric)
        unit_label = (unit or "").lower().replace(" ", "")
        if canonical.startswith("weekly_") or "/week" in unit_label or "perweek" in unit_label:
            iso = observed_at.isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        if canonical.startswith("daily_") or "/day" in unit_label or "perday" in unit_label:
            return observed_at.date().isoformat()
        return observed_at.strftime("%Y-%m")
    return observed_at.date().isoformat()


def canonicalize_event(event: EvidenceEventProposal) -> EvidenceEventProposal:
    canonical = clip_metric_name(canonicalize_metric(event.metric))
    if canonical == event.metric:
        return event
    return event.model_copy(update={"metric": canonical})
