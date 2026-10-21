from datetime import UTC, datetime
from uuid import uuid4

from personal_markets.collections.domain import CollectionSeries
from personal_markets.collections.portfolio import portfolio_summary


def series(values, *, withheld=False):
    return CollectionSeries(
        goal_id=uuid4(), title="Goal", color="#008080", withheld=withheld,
        points=[{"timestamp": timestamp, "value": value} for timestamp, value in values],
    )


NOW = datetime(2026, 10, 20, 18, tzinfo=UTC)


def test_portfolio_uses_equal_weight_and_comparable_day_snapshots():
    goals = [
        series([("2026-10-19T20:00:00Z", 30), ("2026-10-20T12:00:00Z", 40)]),
        series([("2026-10-19T22:00:00Z", 70), ("2026-10-20T13:00:00Z", 80)]),
    ]
    assert portfolio_summary(goals, now=NOW) == (60, 10, 2)


def test_portfolio_partial_coverage_has_no_invented_change():
    goals = [
        series([("2026-10-19T20:00:00Z", 30), ("2026-10-20T12:00:00Z", 40)]),
        series([("2026-10-20T13:00:00Z", 80)]),
        series([]),
        series([("2026-10-19T22:00:00Z", 90)], withheld=True),
    ]
    assert portfolio_summary(goals, now=NOW) == (60, None, 2)
    assert portfolio_summary([series([])], now=NOW) == (None, None, 0)


def test_stale_portfolio_has_no_today_change():
    goals = [series([("2026-10-18T20:00:00Z", 30), ("2026-10-19T12:00:00Z", 40)])]
    assert portfolio_summary(goals, now=NOW) == (40, None, 1)
