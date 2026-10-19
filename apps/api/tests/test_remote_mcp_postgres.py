"""PostgresRemoteMcpStore atomicity against the isolated test database."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from helpers import isolated_postgres_url
from personal_markets.persistence.database import create_engine
from personal_markets.remote_mcp.store import (
    AuditRecord,
    AuthorizationRequestRecord,
    ClientRecord,
    CodeRecord,
    ConnectionRecord,
    PostgresRemoteMcpStore,
    SubmissionRecord,
    TokenRecord,
    digest,
    now_utc,
)

StoreAndEngine = tuple[PostgresRemoteMcpStore, AsyncEngine]


@pytest.fixture
async def store() -> AsyncIterator[StoreAndEngine]:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("Isolated Postgres is not configured")
    engine = create_engine(url)
    try:
        async with engine.connect() as connection:
            present = (
                await connection.execute(text("select to_regclass('remote_mcp_tokens')"))
            ).scalar()
    except Exception as error:  # pragma: no cover - environment dependent
        await engine.dispose()
        pytest.skip(f"Isolated Postgres unavailable: {type(error).__name__}")
    if present is None:
        await engine.dispose()
        pytest.skip("Migration 0015 is not applied to the isolated database")
    yield PostgresRemoteMcpStore(engine), engine
    await engine.dispose()


async def _user(engine: AsyncEngine) -> UUID:
    user_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text("insert into app_users (id, clerk_user_id, email) values (:id, :clerk, :email)"),
            {"id": user_id, "clerk": f"mcp-{user_id}", "email": f"{user_id}@example.test"},
        )
    return user_id


async def _client(store: PostgresRemoteMcpStore) -> str:
    client_id = f"client-{uuid4()}"
    await store.save_client(
        ClientRecord(
            client_id=client_id,
            info={
                "client_id": client_id,
                "client_name": "Agent",
                "redirect_uris": ["http://127.0.0.1:9999/cb"],
                "token_endpoint_auth_method": "none",
            },
        )
    )
    return client_id


async def _connection(
    store: PostgresRemoteMcpStore, user_id: UUID, client_id: str
) -> ConnectionRecord:
    record = ConnectionRecord(
        id=uuid4(),
        user_id=user_id,
        client_id=client_id,
        client_name="Agent",
        scopes=["goals:read"],
        resource="http://127.0.0.1:8000/mcp",
    )
    await store.create_connection(record)
    return record


async def test_public_client_round_trip_and_secret_requires_cipher(store: StoreAndEngine) -> None:
    pg, _ = store
    client_id = await _client(pg)
    loaded = await pg.get_client(client_id)
    assert loaded is not None and loaded.client_secret is None
    with pytest.raises(RuntimeError):
        await pg.save_client(
            ClientRecord(client_id=f"c-{uuid4()}", info={"redirect_uris": []}, client_secret="s")
        )


async def test_consent_decision_is_single_use_under_concurrency(store: StoreAndEngine) -> None:
    pg, engine = store
    user_id = await _user(engine)
    client_id = await _client(pg)
    request_id = f"req-{uuid4()}"
    await pg.save_request(
        AuthorizationRequestRecord(
            id=request_id,
            client_id=client_id,
            redirect_uri="http://127.0.0.1:9999/cb",
            redirect_uri_provided_explicitly=True,
            scopes=["goals:read"],
            code_challenge="x" * 43,
            expires_at=now_utc() + timedelta(minutes=5),
        )
    )
    results = await asyncio.gather(
        *[pg.decide_request(request_id, user_id, "approved", now_utc()) for _ in range(5)]
    )
    assert sum(item is not None for item in results) == 1


async def test_code_is_consumed_once_under_concurrency(store: StoreAndEngine) -> None:
    pg, engine = store
    user_id = await _user(engine)
    client_id = await _client(pg)
    connection = await _connection(pg, user_id, client_id)
    code_hash = digest(f"code-{uuid4()}")
    await pg.save_code(
        CodeRecord(
            code_hash=code_hash,
            client_id=client_id,
            user_id=user_id,
            redirect_uri="http://127.0.0.1:9999/cb",
            redirect_uri_provided_explicitly=True,
            scopes=["goals:read"],
            code_challenge="x" * 43,
            resource="http://127.0.0.1:8000/mcp",
            expires_at=now_utc() + timedelta(minutes=5),
        )
    )
    results = await asyncio.gather(
        *[pg.consume_code(code_hash, connection.id, now_utc()) for _ in range(5)]
    )
    assert results.count(True) == 1
    stored = await pg.get_code(code_hash)
    assert stored is not None
    assert stored.consumed_at is not None and stored.connection_id == connection.id


async def test_revoking_connection_revokes_its_tokens_and_is_owner_scoped(
    store: StoreAndEngine,
) -> None:
    pg, engine = store
    owner = await _user(engine)
    other = await _user(engine)
    client_id = await _client(pg)
    connection = await _connection(pg, owner, client_id)
    token_hash = digest(f"pio_at_{uuid4()}")
    await pg.save_token(
        TokenRecord(
            token_hash=token_hash,
            kind="access",
            connection_id=connection.id,
            client_id=client_id,
            user_id=owner,
            scopes=["goals:read"],
            resource="http://127.0.0.1:8000/mcp",
            expires_at=now_utc() + timedelta(hours=1),
        )
    )
    assert await pg.revoke_connection(connection.id, other, now_utc()) is None
    before = await pg.get_token(token_hash)
    assert before is not None and before.revoked_at is None
    revoked = await pg.revoke_connection(connection.id, owner, now_utc())
    assert revoked is not None and revoked.revoked_at is not None
    after = await pg.get_token(token_hash)
    assert after is not None and after.revoked_at is not None
    assert await pg.revoke_token(token_hash, now_utc()) is False


async def test_submission_claim_is_exclusive_and_failed_claims_are_reclaimable(
    store: StoreAndEngine,
) -> None:
    pg, engine = store
    user_id = await _user(engine)
    key = f"key-{uuid4()}"
    record = SubmissionRecord(
        user_id=user_id, idempotency_key=key, goal_id=uuid4(), payload_hash="h1"
    )
    results = await asyncio.gather(*[pg.claim_submission(record) for _ in range(5)])
    assert [created for _, created in results].count(True) == 1
    await pg.finish_submission(user_id, key, "failed", {})
    reclaimed, created = await pg.claim_submission(record)
    assert created is True and reclaimed.status == "pending"
    other_payload, created = await pg.claim_submission(
        record.model_copy(update={"payload_hash": "h2"})
    )
    assert created is False and other_payload.payload_hash == "h1"
    await pg.finish_submission(user_id, key, "committed", {"status": "committed"})
    done, created = await pg.claim_submission(record)
    assert created is False and done.status == "committed"


async def test_audit_rows_hold_no_token_material(store: StoreAndEngine) -> None:
    pg, engine = store
    user_id = await _user(engine)
    await pg.audit(
        AuditRecord(event="tool.call", outcome="ok", user_id=user_id, tool_name="list_goals")
    )
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text("select * from remote_mcp_audit_log where user_id = :id"), {"id": user_id}
                )
            )
            .mappings()
            .one()
        )
    assert row["event"] == "tool.call"
    assert "pio_" not in str(dict(row))
