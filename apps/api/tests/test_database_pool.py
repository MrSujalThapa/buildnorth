from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import QueuePool

from personal_markets.persistence.database import install_idle_ping


def _engine(idle_seconds: float, pings: list[str], *, fail_once: bool = False) -> Engine:
    engine = create_engine("sqlite:///:memory:", poolclass=QueuePool, pool_size=1)
    state = {"fail": fail_once}

    def ping(_dbapi_connection: Any) -> bool:
        pings.append("ping")
        if state["fail"]:
            state["fail"] = False
            raise OSError("connection reset")
        return True

    setattr(engine.dialect, "do_ping", ping)  # noqa: B010
    install_idle_ping(engine, idle_seconds)
    return engine


def _read(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text("select 1")).scalar_one())


def test_fresh_and_recently_used_connections_skip_the_ping() -> None:
    pings: list[str] = []
    engine = _engine(60.0, pings)
    _read(engine)
    _read(engine)
    assert pings == []


def test_idle_connections_are_pinged_before_reuse() -> None:
    pings: list[str] = []
    engine = _engine(0.0, pings)
    _read(engine)
    _read(engine)
    assert pings == ["ping"]


def test_failed_idle_ping_discards_the_connection_and_retries() -> None:
    pings: list[str] = []
    engine = _engine(0.0, pings, fail_once=True)
    _read(engine)
    assert _read(engine) == 1
    assert pings == ["ping"]


@pytest.mark.parametrize("idle_seconds", [0.0, 60.0])
def test_transactions_are_unaffected(idle_seconds: float) -> None:
    engine = _engine(idle_seconds, [])
    with engine.begin() as connection:
        connection.execute(text("create table t (x int)"))
        connection.execute(text("insert into t values (1)"))
    with engine.connect() as connection:
        assert connection.execute(text("select count(*) from t")).scalar_one() == 1
