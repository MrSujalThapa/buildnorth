import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text

from helpers import isolated_postgres_url
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresSeedRepository
from personal_markets.seeding import load_seed
from personal_markets.what_if.repository import PostgresSimulationRepository

pytestmark = pytest.mark.integration
SEED_PATH = Path(__file__).resolve().parents[3] / "seeds" / "demo.json"


@pytest.mark.asyncio
async def test_seed_is_transactional_idempotent_and_persists_raw_events() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    try:
        payload = load_seed(SEED_PATH)
        repository = PostgresSeedRepository(engine)
        await repository.seed(payload)
        await repository.seed(payload)
        goal_ids = [UUID(goal["goal_id"]) for goal in payload["goals"]]
        event_ids = [UUID(event["id"]) for event in payload["raw_source_events"]]
        async with engine.connect() as connection:
            goals = await connection.scalar(
                text("select count(*) from goals where id in :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": goal_ids},
            )
            events = await connection.scalar(
                text("select count(*) from raw_source_events where id in :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": event_ids},
            )
            raw = await connection.scalar(
                text("select raw_payload_json from raw_source_events where id = :id"),
                {"id": event_ids[0]},
            )
        assert goals == len(goal_ids)
        assert events == len(event_ids)
        assert isinstance(raw, dict)
        assert json.dumps(raw)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_simulation_artifacts_are_idempotent_and_immutable() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    try:
        payload = load_seed(SEED_PATH)
        await PostgresSeedRepository(engine).seed(payload)
        goal_id = UUID(payload["goals"][2]["goal_id"])
        repository = PostgresSimulationRepository(engine)
        test_key = uuid4().hex
        receipt = {
            "forecast_status": "EXPLORATORY",
            "model": {"family": "continuous_target_transition", "version": "1.0.0"},
            "assumption_hash": "assumption-hash",
        }
        first = await repository.append(
            goal_id=goal_id,
            run_kind="impact",
            request_hash=f"integration-request-{test_key}",
            state_hash="state-hash",
            assumption_hash="assumption-hash",
            model_family="continuous_target_transition",
            model_version="1.0.0",
            status="EXPLORATORY",
            receipt=receipt,
            probability=None,
            evidence_watermark="integration",
            material_hash=None,
        )
        second = await repository.append(
            goal_id=goal_id,
            run_kind="impact",
            request_hash=f"integration-request-{test_key}",
            state_hash="state-hash",
            assumption_hash="assumption-hash",
            model_family="continuous_target_transition",
            model_version="1.0.0",
            status="EXPLORATORY",
            receipt=receipt,
            probability=None,
            evidence_watermark="integration",
            material_hash=None,
        )
        assert first[0].id == second[0].id
        assert first[1:] == (True, False)
        assert second[1:] == (False, False)
        listed = await repository.list_runs(goal_id, run_kind="impact")
        assert any(item.id == first[0].id for item in listed)
        history = await repository.history(goal_id)
        assert sum(point.simulation_artifact_id == first[0].id for point in history) == 0
        with pytest.raises(Exception, match="append-only"):
            async with engine.begin() as connection:
                await connection.execute(
                    text("update simulation_artifacts set status='changed' where id=:id"),
                    {"id": first[0].id},
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_shared_invite_redemptions_are_atomic_and_idempotent() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")

    from personal_markets.core.config import Settings
    from personal_markets.identity.service import IdentityService
    from personal_markets.identity.store import PostgresIdentityRepository
    from personal_markets.identity.testing import admin_principal, make_principal

    engine = create_engine(url)
    try:
        repo = PostgresIdentityRepository(engine)
        identity = IdentityService(repo, Settings(environment="test", invite_max_redemptions=20))
        admin = admin_principal(f"pg-admin-{uuid4().hex[:8]}")
        await repo.upsert_user(admin)
        invitation = await identity.create_invitation(admin, max_redemptions=3, note="pg-shared")
        assert invitation.token is not None
        users = []
        for _ in range(5):
            user = make_principal(f"pg-shared-{uuid4().hex[:8]}")
            await repo.upsert_user(user)
            users.append(user)
        results = await asyncio.gather(
            *[identity.redeem_invitation(user, invitation.token) for user in users],
            return_exceptions=True,
        )
        successes = [item for item in results if not isinstance(item, Exception)]
        assert len(successes) == 3
        winner = successes[0]
        again = await identity.redeem_invitation(winner, invitation.token)
        stored = await repo.get_invitation_by_hash(
            hashlib.sha256(invitation.token.encode("utf-8")).hexdigest()
        )
        assert stored is not None
        assert stored.redemption_count == 3
        assert again.hosted_quota_usd == winner.hosted_quota_usd
        entitled = await repo.get_user(winner.user_id)
        assert entitled is not None
        assert entitled.hosted_enabled is True
    finally:
        await engine.dispose()
