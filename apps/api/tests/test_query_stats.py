import asyncio

import pytest
from sqlalchemy import create_engine, text

from personal_markets.persistence.query_stats import instrument, track_queries


def _engine():
    engine = create_engine("sqlite://")
    instrument(engine)
    instrument(engine)
    return engine


def test_counts_queries_and_checkouts_inside_a_request_scope() -> None:
    engine = _engine()
    with track_queries() as stats, engine.connect() as connection:
        connection.execute(text("select 1"))
        connection.execute(text("select 2"))
    assert stats.queries == 2
    assert stats.checkouts == 1
    assert stats.query_ms >= 0
    assert stats.server_timing().startswith("db;dur=")
    assert "2 queries, 1 checkouts" in stats.server_timing()


def test_queries_outside_a_request_scope_are_not_counted() -> None:
    engine = _engine()
    with track_queries() as stats:
        pass
    with engine.connect() as connection:
        connection.execute(text("select 1"))
    assert stats.queries == 0


@pytest.mark.asyncio
async def test_work_in_child_threads_counts_toward_the_request() -> None:
    engine = _engine()

    def run() -> None:
        with engine.connect() as connection:
            connection.execute(text("select 1"))

    with track_queries() as stats:
        await asyncio.gather(asyncio.to_thread(run), asyncio.to_thread(run))
    assert stats.queries == 2
