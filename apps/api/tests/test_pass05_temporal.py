from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.forecasting.repository import PublishedBaseline
from personal_markets.remote_mcp.charting import (
    filter_range,
    is_png,
    render_odds_png,
    series_from_history,
)
from personal_markets.remote_mcp.temporal import delta_pp, select_as_of
from personal_markets.remote_mcp.weighted import (
    WeightedComponent,
    WeightedScoreRequest,
    compute_weighted_score,
)


def _point(probability: float, days: int, now: datetime) -> PublishedBaseline:
    published = now - timedelta(days=days)
    return PublishedBaseline(
        goal_id=uuid4(),
        probability=probability,
        forecast_status="ANCHORED",
        evidence_watermark=f"wm-{days}",
        model_family="deadline_event_hazard",
        model_version="1",
        assumption_hash="a",
        material_hash=f"m-{days}",
        source_kind="published_forecast",
        receipt={},
        published_at=published,
    )


def test_delta_is_percentage_points_not_relative_percent() -> None:
    assert delta_pp(0.40, 0.20) == 20.0


def test_as_of_last_week_uses_publication_time() -> None:
    now = datetime(2026, 10, 18, tzinfo=UTC)
    history = [_point(0.2, 14, now), _point(0.3, 3, now), _point(0.4, 0, now)]
    selected, reason = select_as_of(
        history, as_of=None, relative="last_week", evidence_observed_at=None, now=now
    )
    assert reason == ""
    assert selected is not None and selected.probability == 0.2


def test_before_evidence_requires_observed_at() -> None:
    now = datetime(2026, 10, 18, tzinfo=UTC)
    try:
        select_as_of(
            [_point(0.2, 1, now)],
            as_of=None,
            relative="before_evidence",
            evidence_observed_at=None,
            now=now,
        )
    except ValueError as error:
        assert "observed_at" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_no_earlier_receipt_is_explicit() -> None:
    now = datetime(2026, 10, 18, tzinfo=UTC)
    selected, reason = select_as_of(
        [_point(0.4, 0, now)],
        as_of=now - timedelta(days=30),
        relative=None,
        evidence_observed_at=None,
        now=now,
    )
    assert selected is None
    assert "invent" in reason


def test_weighted_score_asks_for_remaining_component() -> None:
    result = compute_weighted_score(
        WeightedScoreRequest(
            components=[
                WeightedComponent(label="midterm", score=90, weight=30),
                WeightedComponent(label="final", score=None, weight=70, known=False),
            ]
        )
    )
    assert result.status == "needs_clarification"
    assert result.average is None


def test_weighted_score_is_arithmetic_when_complete() -> None:
    result = compute_weighted_score(
        WeightedScoreRequest(
            components=[
                WeightedComponent(label="midterm", score=50, weight=0.3),
                WeightedComponent(label="final", score=80, weight=0.7),
            ]
        )
    )
    assert result.status == "computed"
    assert result.average == 71.0
    assert result.arithmetic_only is True


def test_one_receipt_in_1d_stays_a_single_point() -> None:
    now = datetime(2026, 10, 18, tzinfo=UTC)
    points = series_from_history([_point(0.42, 10, now)])
    filtered = filter_range(points, "1D")
    assert len(filtered) == 1
    assert filtered[0]["probability"] == 0.42


def test_png_is_labeled_static_and_valid() -> None:
    now = datetime(2026, 10, 18, tzinfo=UTC)
    points = series_from_history([_point(0.42, 2, now), _point(0.51, 0, now)])
    png = render_odds_png(points, title="Internship")
    assert is_png(png)
    empty = render_odds_png([], title="Internship")
    assert is_png(empty)
