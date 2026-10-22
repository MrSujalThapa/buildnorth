from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from time import monotonic
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from personal_markets.persistence.query_stats import instrument

# Pooled connections idle at least this long are pinged before reuse; a failed ping makes the pool
# discard the connection and retry checkout. Warm reuse skips the ping round trip.
POOL_IDLE_PING_SECONDS = 30.0
_CHECKED_IN_AT = "checked_in_at"
_FRESH = "fresh_connection"


def async_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


@lru_cache(maxsize=8)
def create_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(
        async_database_url(url),
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )
    install_idle_ping(engine.sync_engine, POOL_IDLE_PING_SECONDS)
    instrument(engine.sync_engine)
    return engine


def install_idle_ping(sync_engine: Engine, idle_seconds: float) -> None:
    pool = sync_engine.pool

    def fresh(_dbapi_connection: Any, record: Any) -> None:
        record.info[_FRESH] = True

    def mark(_dbapi_connection: Any, record: Any) -> None:
        record.info[_CHECKED_IN_AT] = monotonic()

    def validate(dbapi_connection: Any, record: Any, _proxy: Any) -> None:
        if record.info.pop(_FRESH, False):
            return
        last = record.info.get(_CHECKED_IN_AT)
        if last is not None and monotonic() - last < idle_seconds:
            return
        # In autocommit the asyncpg adapter pings without wrapping BEGIN/ROLLBACK round trips.
        previous = getattr(dbapi_connection, "autocommit", None)
        try:
            if previous is not None:
                dbapi_connection.autocommit = True
            sync_engine.dialect.do_ping(dbapi_connection)
        except Exception as error:
            raise DisconnectionError("pooled connection failed its idle ping") from error
        finally:
            if previous is not None:
                dbapi_connection.autocommit = previous

    event.listen(pool, "connect", fresh)
    event.listen(pool, "checkin", mark)
    event.listen(pool, "checkout", validate)


@asynccontextmanager
async def transaction(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.begin() as connection:
        yield connection


@asynccontextmanager
async def autocommit_connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Each statement commits on its own, with no BEGIN/ROLLBACK round trips.

    Use for reads and for single atomic statements. Anything that must hold across more than one
    statement belongs in ``transaction``.
    """
    async with engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        yield connection
