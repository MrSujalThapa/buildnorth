import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text

from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresSeedRepository
from personal_markets.seeding import load_seed
from personal_markets.what_if.repository import PostgresSimulationRepository

pytestmark = pytest.mark.integration
SEED_PATH = Path(__file__).resolve().parents[3] / "seeds" / "demo.json"


@pytest.mark.asyncio
async def test_seed_is_transactional_idempotent_and_persists_raw_events() -> None:
    url = os.environ.get("PM_TEST_DATABASE_URL")
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
        assert goals == 4
        assert events == 15
        assert isinstance(raw, dict)
        assert json.dumps(raw)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_simulation_artifacts_are_idempotent_and_immutable() -> None:
    url = os.environ.get("PM_TEST_DATABASE_URL")
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
