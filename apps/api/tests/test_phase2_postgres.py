import asyncio
import base64
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text

from helpers import POSTGRES_MIGRATION_SKIP, isolated_postgres_url
from personal_markets.core.config import Settings
from personal_markets.identity.budget import InferenceBudgetService, PostgresBudgetStore
from personal_markets.identity.credentials import (
    CredentialCipher,
    InferencePreference,
    PostgresCredentialStore,
)
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.identity.testing import make_principal
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.research_store import ResearchStore
from personal_markets.ports import ResearchArtifact

pytestmark = pytest.mark.integration


async def test_postgres_parallel_reservations_obey_five_dollar_cap() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    user = make_principal(
        f"budget-race-{uuid4()}", invited=True, hosted=True, quota_usd=100, quota_tokens=1_000_000
    )
    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('inference_reservations')")):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
            await conn.execute(
                text("insert into app_users (id, clerk_user_id) values (:id, :clerk)"),
                {"id": user.user_id, "clerk": user.clerk_user_id},
            )
        store = PostgresBudgetStore(engine)
        budget = InferenceBudgetService(store, Settings())
        results = await asyncio.gather(
            *[budget.reserve_research(user, 1.0) for _ in range(10)], return_exceptions=True
        )
        assert sum(not isinstance(item, Exception) for item in results) == 5
        assert (await store.counters(str(user.user_id))).reserved_usd == 5.0
    finally:
        await engine.dispose()


async def test_encrypted_credentials_preferences_ledger_and_research_reload() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("Isolated Postgres is not configured")
    engine = create_engine(url)
    user = make_principal(
        f"phase2-pg-{uuid4()}", invited=True, hosted=True, quota_usd=1, quota_tokens=10_000
    )
    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('provider_credentials')")):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
            await conn.execute(
                text("""
                insert into app_users (id, clerk_user_id) values (:id, :clerk)
            """),
                {"id": user.user_id, "clerk": user.clerk_user_id},
            )
        cipher = CredentialCipher({"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()}, "v1")
        secret = "sk-pg-secret-never-returned"
        store = PostgresCredentialStore(engine)
        await store.put(
            user.user_id, "openai", cipher.encrypt(user.user_id, "openai", secret), "rned"
        )
        await store.set_preference(
            user.user_id, InferencePreference(mode="byok", provider="openai", model="gpt-5.4-mini")
        )
        reloaded = PostgresCredentialStore(engine)
        assert (await reloaded.preference(user.user_id)).mode == "byok"
        row = await reloaded.get(user.user_id, "openai")
        assert row and secret not in repr(row) and secret not in row.ciphertext
        assert cipher.decrypt(user.user_id, "openai", row.ciphertext) == secret
        assert await reloaded.get(uuid4(), "openai") is None

        budget_store = PostgresBudgetStore(engine)
        checks = await asyncio.gather(
            *[budget_store.consume_rate(user.user_id, "phase2-ip", 2, 100) for _ in range(8)],
            return_exceptions=True,
        )
        assert sum(check is None for check in checks) == 2
        audit = InferenceAudit(budget_store)
        await audit.record(
            {
                "execution_id": uuid4(),
                "user_id": user.user_id,
                "clerk_user_id": user.clerk_user_id,
                "agent_name": "evidence",
                "provider": "openai",
                "model": "gpt-5.4-mini",
                "billing_mode": "byok",
                "credential_version": row.version,
                "input_tokens": 20,
                "output_tokens": 10,
                "estimated_cost_usd": 0.0001,
                "outcome": "success",
                "latency_ms": 5,
            }
        )
        summary = await InferenceAudit(PostgresBudgetStore(engine)).byok_summary(user.user_id)
        assert summary["calls"] == 1 and summary["input_tokens"] == 20
        assert (await budget_store.counters(str(user.user_id))).spent_tokens == 0
        assert (await audit.byok_summary(uuid4()))["calls"] == 0
        from datetime import timedelta

        from personal_markets.goals.domain import GoalContract, GoalType
        from personal_markets.goals.service import GoalService
        from personal_markets.persistence.repositories import PostgresGoalRepository
        from personal_markets.ports import ResearchClaim

        goal = GoalContract(
            goal_id=uuid4(),
            title="Research provenance fixture",
            goal_type=GoalType.DEADLINE_EVENT,
            deadline=datetime.now(UTC) + timedelta(days=180),
            success_definition={"metric": "offer_received", "target": "offer"},
            state_dimensions=["applications_submitted"],
        )
        await GoalService(PostgresGoalRepository(engine)).create_goal(goal, user.user_id)
        artifact = ResearchArtifact(
            claims=[
                ResearchClaim(
                    claim="Fixture candidate prior",
                    source="https://example.org/fixture-study",
                    source_type="web",
                    evidence_class="assumption",
                    retrieved_at=datetime.now(UTC).isoformat(),
                    parameter="baseline_logit",
                    value=-4,
                    unit="logit",
                    supporting_quote="Fixture text",
                    population="fixture population",
                )
            ]
        )
        research_run = uuid4()
        await ResearchStore(engine).save(user.user_id, goal.goal_id, research_run, artifact)
        rows = await ResearchStore(engine).list_for_goal(user.user_id, goal.goal_id)
        assert rows[0]["claims"][0]["source"] == "https://example.org/fixture-study"
        assert await ResearchStore(engine).list_for_goal(uuid4(), goal.goal_id) == []
        await store.delete(user.user_id, "openai")
        assert await reloaded.get(user.user_id, "openai") is None
    finally:
        await engine.dispose()


async def test_cancelled_hosted_provider_settles_postgres_reservation() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("Isolated Postgres is not configured")
    from personal_markets.core.config import Settings
    from personal_markets.identity.budget import InferenceBudgetService
    from personal_markets.identity.credentials import InMemoryCredentialStore
    from personal_markets.identity.inference_router import InferenceRouter
    from personal_markets.ports import InferenceRequest, InferenceResponse

    engine = create_engine(url)
    user = make_principal(
        f"phase2-cancel-{uuid4()}", invited=True, hosted=True,
        quota_usd=10, quota_tokens=100_000,
    )
    entered = asyncio.Event()

    class SlowAdapter:
        def __init__(self, provider: str, key: str) -> None:
            assert provider == "spur" and key == "fake-hosted-test-key"

        async def complete_structured(self, req: InferenceRequest) -> InferenceResponse:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("cancelled provider call must not complete")

    async def lookup(owner):
        return user if owner == user.user_id else None

    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('inference_reservations')")):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
            if not await conn.scalar(text("""
                select exists (
                  select 1 from information_schema.columns
                  where table_name='inference_ledger' and column_name='billing_mode'
                )
            """)):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
            await conn.execute(
                text("insert into app_users (id, clerk_user_id) values (:id, :clerk)"),
                {"id": user.user_id, "clerk": user.clerk_user_id},
            )
        settings = Settings(
            _env_file=None, inference_provider="spur", spur_api_key="fake-hosted-test-key",
            byok_encryption_keys={"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()},
        )
        budget_store = PostgresBudgetStore(engine)
        router = InferenceRouter(
            settings, InMemoryCredentialStore(), InferenceBudgetService(budget_store, settings),
            InferenceAudit(budget_store), lookup, SlowAdapter,
        )
        task = asyncio.create_task(
            router.complete_structured(
                InferenceRequest(
                    user_id=user.user_id, agent_name="evidence", input={},
                    instructions="Return a JSON object", output_schema={"type": "object"},
                )
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with engine.connect() as conn:
            status = await conn.scalar(
                text("select status from inference_reservations where user_id=:id"),
                {"id": user.user_id},
            )
            ledger_count = await conn.scalar(
                text("select count(*) from inference_ledger where user_id=:id"),
                {"id": user.user_id},
            )
        counters = await budget_store.counters(str(user.user_id))
        assert status == "settled" and ledger_count == 1
        assert counters.reserved_tokens == 0 and counters.spent_tokens > 0
    finally:
        await engine.dispose()
