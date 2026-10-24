"""Published-receipt comparisons. No interpolation and no ingestion-time substitution."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from personal_markets.forecasting.repository import PublishedBaseline
from personal_markets.remote_mcp.temporal import (
    MONTH_WINDOW_DAYS,
    direction_for,
    evidence_observed_in_window,
    largest_consecutive_move,
    select_as_of,
)
from personal_markets.remote_mcp.tools import _milestones_from_spec

GOAL = UUID("00000000-0000-4000-8000-000000000010")
NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


def _point(probability: float, when: datetime, watermark: str) -> PublishedBaseline:
    return PublishedBaseline(
        goal_id=GOAL,
        probability=probability,
        forecast_status="CALIBRATED",
        evidence_watermark=watermark,
        model_family="hiring",
        model_version="1",
        assumption_hash="a",
        material_hash=watermark,
        source_kind="model",
        receipt={},
        published_at=when,
    )


def test_direction_for_only_accepts_published_step_selectors() -> None:
    assert direction_for("largest_increase") == "increase"
    assert direction_for("largest_drop") == "drop"
    try:
        direction_for("previous")
    except ValueError as error:
        assert "published-step" in str(error)
    else:
        raise AssertionError("previous is not a move direction")


def test_since_start_is_the_earliest_published_receipt() -> None:
    history = [
        _point(0.2, NOW - timedelta(days=40), "early"),
        _point(0.5, NOW - timedelta(days=2), "late"),
    ]
    selected, reason = select_as_of(
        history, as_of=None, relative="since_start", evidence_observed_at=None, now=NOW
    )
    assert reason == ""
    assert selected is not None
    assert selected.evidence_watermark == "early"


def test_this_month_does_not_invent_a_receipt_before_the_window() -> None:
    history = [_point(0.4, NOW - timedelta(days=3), "recent")]
    selected, reason = select_as_of(
        history, as_of=None, relative="this_month", evidence_observed_at=None, now=NOW
    )
    assert selected is None
    assert "invent" in reason.lower()
    older = _point(0.1, NOW - timedelta(days=MONTH_WINDOW_DAYS + 5), "older")
    selected, reason = select_as_of(
        [older, history[0]],
        as_of=None,
        relative="this_month",
        evidence_observed_at=None,
        now=NOW,
    )
    assert reason == ""
    assert selected is not None
    assert selected.evidence_watermark == "older"


def test_largest_increase_uses_successive_receipts_and_breaks_ties_later() -> None:
    history = [
        _point(0.10, NOW - timedelta(days=9), "a"),
        _point(0.30, NOW - timedelta(days=6), "b"),
        _point(0.20, NOW - timedelta(days=3), "c"),
        _point(0.40, NOW - timedelta(days=1), "d"),
    ]
    pair = largest_consecutive_move(history, direction="increase")
    assert pair is not None
    earlier, later = pair
    assert (earlier.evidence_watermark, later.evidence_watermark) == ("c", "d")
    drop = largest_consecutive_move(history, direction="drop")
    assert drop is not None
    assert drop[0].evidence_watermark == "b"
    flat = [history[0], _point(0.10, NOW, "flat")]
    assert largest_consecutive_move(flat, direction="increase") is None


def test_evidence_window_ignores_ingestion_time() -> None:
    earlier = NOW - timedelta(days=5)
    later = NOW
    inside = {
        "evidence_id": "in",
        "metric": "applications",
        "observed_at": NOW - timedelta(days=1),
        "ingested_at": NOW - timedelta(days=20),
    }
    ingested_only = {
        "evidence_id": "out",
        "metric": "applications",
        "observed_at": NOW - timedelta(days=30),
        "ingested_at": NOW - timedelta(hours=1),
    }
    missing_observed = {
        "evidence_id": "none",
        "metric": "applications",
        "observed_at": None,
        "ingested_at": NOW,
    }
    kept = evidence_observed_in_window(
        [inside, ingested_only, missing_observed], after=earlier, until=later
    )
    assert [item["evidence_id"] for item in kept] == ["in"]


def test_milestones_come_from_stored_primitives_only() -> None:
    listed = _milestones_from_spec(
        {
            "primitives": [
                {
                    "id": "launch",
                    "kind": "deadline_hazard",
                    "metric": "launched",
                    "config": {"target": 1},
                    "prerequisites": [],
                }
            ]
        }
    )
    assert listed[0].id == "launch"
    assert listed[0].metric == "launched"
    assert listed[0].target == "1"
    assert _milestones_from_spec({}) == []
