"""Per-request database round-trip accounting.

The counter lives in a ContextVar set by the request middleware, so concurrent requests never
share counts. SQLAlchemy runs asyncpg calls in greenlets that inherit the caller's context.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


@dataclass(slots=True)
class QueryStats:
    queries: int = 0
    checkouts: int = 0
    query_ms: float = 0.0
    connection_ms: float = 0.0

    def server_timing(self) -> str:
        return (
            f'db;dur={self.query_ms:.1f};desc="{self.queries} queries, {self.checkouts} checkouts", '
            f'db-acquire;dur={self.connection_ms:.1f}'
        )


_current: ContextVar[QueryStats | None] = ContextVar("db_query_stats", default=None)
_START_KEY = "query_stats_started"


@contextmanager
def track_queries() -> Iterator[QueryStats]:
    stats = QueryStats()
    token = _current.set(stats)
    try:
        yield stats
    finally:
        _current.reset(token)


def record_connection_acquire(duration_ms: float) -> None:
    stats = _current.get()
    if stats is not None:
        stats.connection_ms += duration_ms


def instrument(engine: Engine) -> None:
    if event.contains(engine, "before_cursor_execute", _before_execute):
        return
    event.listen(engine, "before_cursor_execute", _before_execute)
    event.listen(engine, "after_cursor_execute", _after_execute)
    event.listen(engine.pool, "checkout", _on_checkout)


def _before_execute(conn: Any, _cursor: Any, *_args: Any) -> None:
    if _current.get() is not None:
        conn.info[_START_KEY] = perf_counter()


def _after_execute(conn: Any, _cursor: Any, *_args: Any) -> None:
    stats = _current.get()
    started = conn.info.pop(_START_KEY, None)
    if stats is None or started is None:
        return
    stats.queries += 1
    stats.query_ms += (perf_counter() - started) * 1000


def _on_checkout(*_args: Any) -> None:
    stats = _current.get()
    if stats is not None:
        stats.checkouts += 1
