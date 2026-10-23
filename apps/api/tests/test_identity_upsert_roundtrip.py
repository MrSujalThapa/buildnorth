from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from personal_markets.identity.store import PostgresIdentityRepository
from personal_markets.identity.testing import make_principal


@pytest.mark.asyncio
async def test_upsert_returns_entitlement_in_one_database_round_trip(monkeypatch) -> None:
    principal = make_principal("roundtrip-user")
    row = {
        "id": principal.user_id,
        "clerk_user_id": principal.clerk_user_id,
        "email": principal.email,
        "email_verified": True,
        "role": "user",
        "hosted_enabled": True,
        "quota_usd": 5,
        "quota_tokens": 1000,
    }
    result = MagicMock()
    result.mappings.return_value.one.return_value = row
    connection = MagicMock()
    connection.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def one_connection(_engine):
        yield connection

    monkeypatch.setattr("personal_markets.identity.store.autocommit_connection", one_connection)
    repository = PostgresIdentityRepository(MagicMock())
    stored = await repository.upsert_user(principal)

    assert connection.execute.await_count == 1
    assert stored.user_id == principal.user_id
    assert stored.hosted_enabled is True
    assert stored.hosted_quota_usd == 5
    assert stored.hosted_quota_tokens == 1000
