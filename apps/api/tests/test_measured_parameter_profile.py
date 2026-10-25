from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.profile.parameters import parameter_profile

NOW = datetime(2026, 10, 24, tzinfo=UTC)


def observation(
    metric: str,
    value: float,
    kind: Literal["snapshot", "increment", "period", "event", "uncertain"],
    unit: str,
    days_ago: int = 1,
) -> NormalizedEvidence:
    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type="observation",
        domain="personal",
        metric=metric,
        numeric_value=value,
        unit=unit,
        observed_at=NOW - timedelta(days=days_ago),
        source_quality="platform_public",
        provenance=Provenance(
            source_type="mcp_sync",
            source_authority="platform_public",
            observed_vs_entered="directly_observed",
            parsing_status="ok",
            completeness="complete",
            conflict_status="none",
            observation_kind=kind,
        ),
        summary=metric,
        fingerprint=str(uuid4()),
    )


def test_parameter_radar_keeps_cumulative_books_out_of_reading_duration() -> None:
    books = observation("books_read", 7, "snapshot", "books")
    minutes = observation("reading_minutes", 45, "increment", "minutes")
    profile = parameter_profile([books, minutes], as_of=NOW)
    reading = next(item for item in profile.parameters if item.id == "reading_minutes")
    assert reading.raw_value == 45
    assert reading.observation_count == 1
    assert reading.source_types == ["mcp_sync"]
    assert reading.evidence_ids == [str(minutes.evidence_id)]
    assert profile.evidence_count == 1


def test_duplicate_links_and_repeated_periods_do_not_inflate_latest_rate() -> None:
    old = observation("weekly_distance_km", 15, "period", "km/week", 14)
    latest = observation("weekly_distance_km", 24, "period", "km/week", 3)
    profile = parameter_profile([old, latest, latest], as_of=NOW)
    running = next(item for item in profile.parameters if item.id == "weekly_running_km")
    assert running.raw_value == 24
    assert running.observation_count == 2
    assert profile.evidence_count == 2


def test_missing_units_and_mixed_currencies_are_withheld() -> None:
    invalid = observation("reading_minutes", 45, "snapshot", "minutes")
    cad = observation("monthly_contribution", 500, "period", "CAD/month")
    usd = observation("monthly_contribution", 600, "period", "USD/month")
    profile = parameter_profile([invalid, cad, usd], as_of=NOW)
    assert all(item.value is None for item in profile.parameters)
    assert profile.evidence_count == 0


def test_selection_keeps_unknown_axes_honest() -> None:
    profile = parameter_profile([], selected_ids=["reading_minutes", "monthly_savings"], as_of=NOW)
    assert [item.id for item in profile.parameters] == ["reading_minutes", "monthly_savings"]
    assert all(item.raw_value is None and item.value is None for item in profile.parameters)


def test_actual_application_increments_populate_weekly_axis_without_stock_double_count() -> None:
    first = observation("applications_submitted", 4, "increment", "count", 2)
    first.source_quality = "user_entered"
    first.provenance.source_type = "manual"
    first.provenance.source_authority = "self_report"
    linked = first.model_copy(update={"evidence_id": uuid4()})
    linked.provenance = first.provenance.model_copy(update={"event_identity": "shared-report"})
    first.provenance.event_identity = "shared-report"
    second = observation("applications_submitted", 3, "increment", "count", 1)
    stock = observation("applications_submitted", 50, "snapshot", "count", 1)
    old = observation("applications_submitted", 8, "increment", "count", 9)
    profile = parameter_profile([first, linked, second, stock, old], as_of=NOW)
    axis = next(item for item in profile.parameters if item.id == "weekly_applications")
    assert axis.raw_value == 7
    assert axis.window_days == 7
    assert axis.aggregation == "sum_increments"
    assert axis.observation_count == 2
    assert axis.source_types == ["manual", "mcp_sync"]


def test_dated_study_and_running_activity_populate_only_matching_units() -> None:
    study = observation("study_hours", 2.5, "increment", "hours", 2)
    run = observation("weekly_distance_km", 6, "increment", "km", 1)
    wrong = observation("weekly_distance_km", 4, "increment", "miles", 1)
    profile = parameter_profile([study, run, wrong], as_of=NOW)
    by_id = {item.id: item for item in profile.parameters}
    assert by_id["weekly_study_hours"].raw_value == 2.5
    assert by_id["weekly_running_km"].raw_value == 6
    assert by_id["weekly_running_km"].observation_count == 1


def test_canonical_period_metrics_match_weekly_radar_axes() -> None:
    applications = observation("applications_submitted", 12, "period", "count/week", 1)
    practice = observation("practice_hours", 6, "period", "hours/week", 1)
    profile = parameter_profile([applications, practice], as_of=NOW)
    by_id = {item.id: item for item in profile.parameters}
    assert by_id["weekly_applications"].raw_value == 12
    assert by_id["weekly_applications"].aggregation == "latest_period"
    assert by_id["weekly_study_hours"].raw_value == 6


def test_recent_period_supersedes_components_and_currency_is_not_converted() -> None:
    activity = observation("monthly_contribution", 100, "increment", "USD", 8)
    period = observation("monthly_contribution", 800, "period", "USD/month", 1)
    profile = parameter_profile([activity, period], as_of=NOW)
    savings = next(item for item in profile.parameters if item.id == "monthly_savings")
    assert savings.raw_value == 800
    assert savings.aggregation == "latest_period"
    assert savings.unit == "USD/month"
    cad = observation("monthly_contribution", 200, "increment", "CAD", 1)
    usd = observation("monthly_contribution", 100, "increment", "USD", 2)
    mixed = parameter_profile([cad, usd], as_of=NOW)
    assert next(item for item in mixed.parameters if item.id == "monthly_savings").value is None
    usd_only = parameter_profile([usd], as_of=NOW)
    usd_axis = next(item for item in usd_only.parameters if item.id == "monthly_savings")
    assert usd_axis.raw_value == 100
    assert usd_axis.unit == "USD/30 days"
    invalid = observation("monthly_contribution", 100, "period", "hours/month", 1)
    assert (
        next(
            item
            for item in parameter_profile([invalid], as_of=NOW).parameters
            if item.id == "monthly_savings"
        ).value
        is None
    )
    abbreviated = observation("monthly_contribution", 100, "period", "hrs/month", 1)
    assert (
        next(
            item
            for item in parameter_profile([abbreviated], as_of=NOW).parameters
            if item.id == "monthly_savings"
        ).value
        is None
    )
