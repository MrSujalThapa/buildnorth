from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.behavior.cohort import behavior_cohort_goals
from personal_markets.behavior.commitments import InMemoryCommitmentStore, trials_from_commitments
from personal_markets.behavior.traits import estimate_traits
from personal_markets.collections.repository import InMemoryCollectionRepository
from personal_markets.collections.service import CollectionService
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.service import GoalService
from personal_markets.identity.testing import admin_principal, invited_principal
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal
from personal_markets.profile.parameters import parameter_profile
from personal_markets.workspace_seed.fixtures import SEED_GOALS
from personal_markets.workspace_seed.registry import InMemorySeedRegistry
from personal_markets.workspace_seed.service import WorkspaceSeedService, build_seed_goal


def _service() -> tuple[WorkspaceSeedService, dict[str, object]]:
    goals = GoalService(InMemoryGoalRepository())
    evidence = EvidenceService(InMemoryEvidenceRepository())
    forecasts = InMemoryBaselineForecastRepository()
    commitments = InMemoryCommitmentStore()
    collections = CollectionService(InMemoryCollectionRepository(), goals)
    service = WorkspaceSeedService(
        goals=goals,
        evidence=evidence,
        forecasts=BaselineForecastService(forecasts),
        collections=collections,
        commitments=commitments,
        registry=InMemorySeedRegistry(),
    )
    parts = {
        "goals": goals,
        "evidence": evidence,
        "forecasts": forecasts,
        "commitments": commitments,
        "collections": collections,
    }
    return service, parts


def test_seed_goals_are_ordinary_contracts() -> None:
    now = datetime.now(UTC)
    for seed in SEED_GOALS:
        goal = build_seed_goal(uuid4(), seed, now)
        assert goal.deadline > now
        assert goal.model_requirements["workspace_seed"]
        # evidence_events requires a numeric or categorical value.
        assert all(
            item.value is not None or item.category is not None for item in seed.observations
        ), seed.key


def test_seed_publishes_model_histories_and_is_idempotent() -> None:
    async def run() -> None:
        service, parts = _service()
        owner = uuid4()
        result = await service.seed(owner)
        assert len(result["goals"]) == len(SEED_GOALS) >= 6
        for item in result["goals"]:
            priced = [p["probability"] for p in item["history"] if p["probability"] is not None]
            assert len(priced) >= 3, item["key"]
            assert len({round(value, 3) for value in priced}) >= 3, item["key"]
            # Model trajectories move both ways rather than ramping to a chosen final value.
            steps = [b - a for a, b in zip(priced, priced[1:], strict=False)]
            assert any(step > 0 for step in steps) or any(step < 0 for step in steps)
        goals = parts["goals"]
        assert isinstance(goals, GoalService)
        owned = await goals.list_goals(owner_id=owner)
        assert len(owned) == len(SEED_GOALS)

        evidence = parts["evidence"]
        assert isinstance(evidence, EvidenceService)
        rows = await evidence.list_for_goal(owned[0].goal_id)
        assert rows and all(row.provenance.source_type == "manual" for row in rows)

        again = await service.seed(owner)
        assert {item["status"] for item in again["goals"]} == {"exists"}
        collections = parts["collections"]
        assert isinstance(collections, CollectionService)
        assert len(await collections.list_for(owner)) == 2

    asyncio.run(run())


def test_seed_feeds_context_trait_series() -> None:
    async def run() -> None:
        service, parts = _service()
        owner = uuid4()
        await service.seed(owner)
        goals = parts["goals"]
        commitments = parts["commitments"]
        assert isinstance(goals, GoalService)
        assert isinstance(commitments, InMemoryCommitmentStore)
        ids = [goal.goal_id for goal in await goals.list_goals(owner_id=owner)]
        plans, observations = await commitments.list_for_goals(owner, ids)
        profile = estimate_traits(trials_from_commitments(plans, observations), [])
        labels = {series.id for series in profile.series}
        assert {"career", "personal"} <= labels
        discipline = next(t for t in profile.traits if t.id == "discipline")
        assert discipline.value is not None and 0.3 < discipline.value < 0.95

    asyncio.run(run())


def test_seed_is_excluded_from_authentic_profile_but_retained_in_fixture_cohort() -> None:
    async def run() -> None:
        service, parts = _service()
        owner = uuid4()
        await service.seed(owner)
        goals = parts["goals"]
        evidence = parts["evidence"]
        commitments = parts["commitments"]
        assert isinstance(goals, GoalService)
        assert isinstance(evidence, EvidenceService)
        assert isinstance(commitments, InMemoryCommitmentStore)
        fixture_goals = await goals.list_goals(owner_id=owner)
        assert behavior_cohort_goals(fixture_goals) == []
        fixture_ids = [
            item.goal_id for item in behavior_cohort_goals(fixture_goals, synthetic=True)
        ]
        fixture_plans, fixture_outcomes = await commitments.list_for_goals(owner, fixture_ids)
        assert (len(fixture_ids), len(fixture_plans), len(fixture_outcomes)) == (7, 106, 106)
        assert len(trials_from_commitments(fixture_plans, fixture_outcomes)) == 106

        authentic = build_seed_goal(owner, SEED_GOALS[3], datetime.now(UTC)).model_copy(
            update={"goal_id": uuid4(), "model_requirements": {}}
        )
        await goals.create_goal(authentic, owner)
        await evidence.commit(
            owner,
            authentic.goal_id,
            [
                EvidenceEventProposal(
                    event_type="observation",
                    domain="learning",
                    metric="reading_minutes",
                    numeric_value=45,
                    unit="minutes",
                    observed_at=datetime.now(UTC).isoformat(),
                    source_type="manual",
                    summary="Read for 45 minutes",
                    observation_kind="increment",
                )
            ],
            None,
            [],
        )
        authentic_ids = [
            item.goal_id for item in behavior_cohort_goals(await goals.list_goals(owner_id=owner))
        ]
        plans, outcomes = await commitments.list_for_goals(owner, authentic_ids)
        rows = await evidence.list_for_goals(authentic_ids)
        selected = [row for items in rows.values() for row in items]
        radar = parameter_profile(selected)
        assert authentic_ids == [authentic.goal_id]
        assert len(plans) == len(outcomes) == 0
        assert len(selected) == radar.evidence_count == 1
        assert radar.parameters[-1].raw_value == 45
        assert radar.parameters[-1].source_types == ["manual"]
        assert radar.parameters[-1].evidence_ids == [str(selected[0].evidence_id)]

    asyncio.run(run())


def test_remove_archives_only_seeded_records() -> None:
    async def run() -> None:
        service, parts = _service()
        owner = uuid4()
        goals = parts["goals"]
        assert isinstance(goals, GoalService)
        mine = build_seed_goal(owner, SEED_GOALS[0], datetime.now(UTC)).model_copy(
            update={"goal_id": uuid4(), "title": "My own goal"}
        )
        await goals.create_goal(mine, owner)
        await service.seed(owner)
        removed = await service.remove(owner)
        assert removed["archived_goals"] == len(SEED_GOALS)
        remaining = await goals.list_goals(owner_id=owner)
        assert [goal.title for goal in remaining] == ["My own goal"]
        reseeded = await service.seed(owner)
        assert {item["status"] for item in reseeded["goals"]} == {"created"}

    asyncio.run(run())


def test_failed_goal_is_retired_and_rebuilt_on_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        service, parts = _service()
        owner = uuid4()
        replay = service._replay
        calls = {"n": 0}

        async def flaky(*args: object, **kwargs: object) -> list[dict[str, object]]:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("database hiccup")
            return await replay(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(service, "_replay", flaky)
        with pytest.raises(RuntimeError):
            await service.seed(owner)
        goals = parts["goals"]
        assert isinstance(goals, GoalService)
        assert len(await goals.list_goals(owner_id=owner)) == 1

        result = await service.seed(owner)
        statuses = {item["key"]: item["status"] for item in result["goals"]}
        assert statuses[SEED_GOALS[0].key] == "exists"
        assert statuses[SEED_GOALS[1].key] == "created"
        assert len(await goals.list_goals(owner_id=owner)) == len(SEED_GOALS)
        assert (await service.status(owner))["records"]["goal"] == len(SEED_GOALS)

    asyncio.run(run())


def test_seed_endpoint_requires_admin_and_scopes_to_caller() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        app.state.auth_bypass_principal = invited_principal()
        assert client.post("/api/v1/admin/workspace-seed").status_code == 403
        app.state.auth_bypass_principal = admin_principal()
        seeded = client.post("/api/v1/admin/workspace-seed")
        assert seeded.status_code == 200, seeded.text
        status = client.get("/api/v1/admin/workspace-seed").json()
        assert status["records"]["goal"] == len(SEED_GOALS)
        authentic_profile = client.get("/api/v1/profile")
        assert authentic_profile.status_code == 200
        assert authentic_profile.json()["radar"]["evidence_count"] == 0
        demo_profile = client.get("/api/v1/profile/demo-radar")
        assert demo_profile.status_code == 200
        assert demo_profile.json()["synthetic"] is True
        assert demo_profile.json()["fixture_goal_count"] == len(SEED_GOALS)
        assert demo_profile.json()["commitment_count"] == 106
        assert demo_profile.json()["radar"]["synthetic"] is True
        assert demo_profile.json()["radar"]["evidence_count"] > 0
        dashboard = client.get("/api/v1/goals/dashboard")
        assert dashboard.status_code == 200
        app.state.auth_bypass_principal = invited_principal("someone-else")
        assert client.get("/api/v1/goals").json() == []
