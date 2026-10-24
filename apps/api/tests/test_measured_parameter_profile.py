from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.profile.parameters import parameter_profile

NOW = datetime(2026, 10, 24, tzinfo=UTC)


def observation(metric: str, value: float, kind: str, unit: str, days_ago: int = 1):
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
