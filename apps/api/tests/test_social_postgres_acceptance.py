"""Social persistence and privacy checks against a disposable migrated PostgreSQL database.

The principals here are test identities, not Clerk sessions. This deliberately does not
claim authenticated browser acceptance.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from helpers import isolated_postgres_url
from personal_markets.core.config import Settings
from personal_markets.core.errors import ResourceNotFoundError
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.identity.domain import UserProfile
from personal_markets.identity.service import IdentityService
from personal_markets.identity.store import InMemoryIdentityRepository
from personal_markets.persistence.agent_store import PostgresEvidenceRepository
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresGoalRepository
from personal_markets.ports import EvidenceEventProposal
from personal_markets.social.postgres import PostgresSocialRepository
from personal_markets.social.service import SocialService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_two_owner_social_lifecycle_persists_without_leaking_private_activity() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    owner, visitor = uuid4(), uuid4()
    goals = PostgresGoalRepository(engine)
    repo = PostgresSocialRepository(engine)
    identities = InMemoryIdentityRepository()
    await identities.upsert_profile(
        owner, UserProfile(username="owner_accept", display_name="Owner")
    )
    await identities.upsert_profile(
        visitor, UserProfile(username="visitor_accept", display_name="Visitor")
    )
    service = SocialService(repo, GoalService(goals), IdentityService(identities, Settings()))
    goal = GoalContract(
        goal_id=uuid4(),
        title="Accept a signed offer",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"event": "signed_offer", "milestones": ["Interview"]},
        deadline=datetime.now(UTC) + timedelta(days=90),
        state_dimensions=["interviews"],
    )
    try:
        await goals.create(goal, owner)
        await repo.record_activity(
            owner, "evidence_accepted", datetime.now(UTC).date(), goal.goal_id
        )
        await service.set_visibility(owner, goal.goal_id, "public")
        first, total = await service.search_markets_page(
            query="signed offer",
            category=None,
            sort="recent",
            limit=1,
            offset=0,
            viewer_id=visitor,
        )
        assert total == 1 and [card.goal_id for card in first] == [goal.goal_id]
        detail = await service.public_market(goal.goal_id, visitor)
        assert detail.blueprint.success_criteria["event"] == "signed_offer"
        assert (await service.profile("owner_accept", visitor)).contribution_total == 2
        await service.follow(visitor, "owner_accept")
        await service.star(visitor, goal.goal_id)
        fork = await service.fork(
            visitor,
            goal.goal_id,
            title="My offer",
            deadline=None,
            idempotency_key="acceptance-fork",
        )
        fork_id = fork["goal_id"]

        # Reconstruct all repositories and services to simulate a fresh request/process.
        fresh_repo = PostgresSocialRepository(engine)
        fresh_goals = PostgresGoalRepository(engine)
        fresh = SocialService(
            fresh_repo, GoalService(fresh_goals), IdentityService(identities, Settings())
        )
        assert await fresh_repo.following(visitor, owner)
        assert await fresh_repo.starred(visitor, goal.goal_id)
        assert await fresh_goals.get_for_user(UUID(fork_id), visitor) is not None
        assert await fresh_goals.get_for_user(UUID(fork_id), owner) is None
        stored_fork = await fresh_repo.get_goal_row(UUID(fork_id))
        assert stored_fork is not None and stored_fork["visibility"] == "private"
        detail = await fresh.public_market(goal.goal_id, visitor)
        assert detail.blueprint.success_criteria["event"] == "signed_offer"

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "update goals set success_definition_json = "
                    '\'{"event":"secret_change"}\'::jsonb where id = :id'
                ),
                {"id": goal.goal_id},
            )
        detail = await fresh.public_market(goal.goal_id, visitor)
        assert detail.blueprint.success_criteria["event"] == "signed_offer"
        await fresh.set_visibility(owner, goal.goal_id, "private")
        with pytest.raises(ResourceNotFoundError):
            await fresh.public_market(goal.goal_id, visitor)
        assert (await fresh.profile("owner_accept", visitor)).contribution_total == 0
        starred = await fresh_repo.list_starred_public(
            visitor, viewer_id=visitor, limit=10, offset=0
        )
        assert starred == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_offset_page_can_shift_when_new_market_is_published() -> None:
    """Characterize offset semantics; the browser deduplicates repeated IDs."""
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    owner = uuid4()
    query = f"offset-{owner.hex}"
    goals = PostgresGoalRepository(engine)
    repo = PostgresSocialRepository(engine)
    created = [
        GoalContract(
            goal_id=uuid4(),
            title=f"{query} market {index}",
            goal_type=GoalType.DEADLINE_EVENT,
            success_definition={"event": "completed"},
            deadline=datetime.now(UTC) + timedelta(days=90),
            state_dimensions=["progress"],
        )
        for index in range(3)
    ]
    try:
        for goal in created:
            await goals.create(goal, owner)
        for goal in created[:2]:
            await repo.set_visibility(goal.goal_id, owner, "public", {}, datetime.now(UTC))
        first = await repo.search_public(
            query=query, category=None, sort="newest", limit=1, offset=0
        )
        assert await repo.count_public(query=query, category=None) == 2
        await repo.set_visibility(created[2].goal_id, owner, "public", {}, datetime.now(UTC))
        second = await repo.search_public(
            query=query, category=None, sort="newest", limit=1, offset=1
        )
        assert await repo.count_public(query=query, category=None) == 3
        assert first[0]["id"] == second[0]["id"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_published_updates_project_receipts_without_private_values() -> None:
    import json

    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    owner, visitor = uuid4(), uuid4()
    goals = PostgresGoalRepository(engine)
    repo = PostgresSocialRepository(engine)
    evidence = EvidenceService(PostgresEvidenceRepository(engine))
    identities = InMemoryIdentityRepository()
    service = SocialService(repo, GoalService(goals), IdentityService(identities, Settings()))
    now = datetime.now(UTC)
    goal = GoalContract(
        goal_id=uuid4(),
        title="Submit 40 applications",
        goal_type=GoalType.THRESHOLD,
        success_definition={"metric": "applications_submitted", "operator": ">=", "target": 40},
        deadline=now + timedelta(days=90),
        state_dimensions=["applications_submitted"],
    )

    def observation(metric: str, value: float) -> EvidenceEventProposal:
        return EvidenceEventProposal(
            event_type="observation",
            domain="user_state",
            metric=metric,
            numeric_value=value,
            unit="count",
            observed_at=now.isoformat(),
            source_type="manual",
            summary=f"private note {metric} {value}",
            observation_kind="snapshot",
        )

    try:
        await goals.create(goal, owner)
        await evidence.commit(
            owner,
            goal.goal_id,
            [observation("applications_submitted", 17.25), observation("sleep", 4.5)],
            None,
            [],
        )
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        "select e.id::text, e.metric from evidence_events e join goal_evidence ge"
                        " on ge.evidence_id = e.id where ge.goal_id = :id order by e.metric"
                    ),
                    {"id": goal.goal_id},
                )
            ).all()
            ids = {metric: evidence_id for evidence_id, metric in rows}
            assert set(ids) == {"applications_submitted", "sleep"}, rows
            for index, (probability, evidence_ids) in enumerate(
                [
                    (0.3, [ids["applications_submitted"]]),
                    (0.42, [ids["applications_submitted"], ids["sleep"]]),
                ]
            ):
                receipt = {
                    "normalized_evidence_ids": evidence_ids,
                    "goal_contract_version": 1,
                    "forecast_spec": {"deadline": goal.deadline.isoformat()},
                    "numeric_inputs": {"state": {"current_value": 17.25}},
                    "assumptions": [{"name": "application_rate", "value": 0.734512}],
                }
                await connection.execute(
                    text(
                        """
                        insert into market_forecast_history (
                          goal_id, probability, forecast_status, evidence_watermark,
                          model_family, model_version, assumption_hash, material_hash,
                          source_kind, receipt_json, created_at
                        ) values (
                          :goal_id, :probability, 'EXPLORATORY', :watermark, 'count_process',
                          'v1', 'a', :material, 'published_forecast', cast(:receipt as jsonb),
                          :created_at
                        )
                        """
                    ),
                    {
                        "goal_id": goal.goal_id,
                        "probability": probability,
                        "watermark": evidence_ids[-1],
                        "material": f"m{index}",
                        "receipt": json.dumps(receipt),
                        "created_at": now + timedelta(minutes=index),
                    },
                )
        projected = await repo.published_updates(goal.goal_id)
        assert len(projected) == 2
        assert "numeric_inputs" not in json.dumps(projected[0]["receipt_json"])
        assert projected[0]["receipt_json"]["assumption_names"] == ["application_rate"]
        metrics = await repo.evidence_metrics(goal.goal_id, [ids["sleep"], "not-a-uuid"])
        assert metrics == {ids["sleep"]: "sleep"}

        await service.set_visibility(owner, goal.goal_id, "public")
        detail = await service.public_market(goal.goal_id, visitor)
        assert detail.updates[1].change_points == 12.0
        assert detail.updates[1].new_evidence_count == 1
        assert detail.updates[1].new_evidence_metrics == []
        assert detail.updates[1].other_new_evidence_count == 1
        assert detail.updates[0].new_evidence_metrics == ["applications submitted"]
        payload = detail.model_dump_json()
        for forbidden in ("17.25", "0.734512", "private note", "sleep", *ids.values()):
            assert forbidden not in payload
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_activity_counts_stored_evidence_dates_and_keeps_seed_fixtures_out() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    owner = uuid4()
    goals = PostgresGoalRepository(engine)
    repo = PostgresSocialRepository(engine)
    evidence = EvidenceService(PostgresEvidenceRepository(engine))
    now = datetime.now(UTC)

    def contract(title: str, seeded: bool) -> GoalContract:
        return GoalContract(
            goal_id=uuid4(),
            title=title,
            goal_type=GoalType.THRESHOLD,
            success_definition={"metric": "sessions", "operator": ">=", "target": 10},
            deadline=now + timedelta(days=90),
            state_dimensions=["sessions"],
            model_requirements={"workspace_seed": "fixture"} if seeded else {},
        )

    def observation(days_ago: int, identity: str | None = None) -> EvidenceEventProposal:
        return EvidenceEventProposal(
            event_type="observation",
            domain="user_state",
            metric="sessions",
            numeric_value=float(days_ago),
            unit="sessions",
            observed_at=(now - timedelta(days=days_ago)).isoformat(),
            source_type="manual",
            summary=f"sessions {days_ago}",
            observation_kind="snapshot",
            event_identity=identity,
        )

    real, seeded = contract("Real sessions", False), contract("Seeded sessions", True)
    try:
        await goals.create(real, owner)
        await goals.create(seeded, owner)
        await evidence.commit(owner, real.goal_id, [observation(3), observation(10)], None, [])
        await evidence.commit(
            owner, seeded.goal_id, [observation(5, f"seed:test:{seeded.goal_id}")], None, []
        )
        start, today = (now - timedelta(days=30)).date(), now.date()
        authentic = await repo.activity_counts(owner, start, today)
        assert authentic == {
            (now - timedelta(days=10)).date(): 1,
            (now - timedelta(days=3)).date(): 1,
            today: 1,
        }
        persona = await repo.activity_counts(owner, start, today, include_fixtures=True)
        assert persona[(now - timedelta(days=5)).date()] == 1
        assert persona[today] == 2
        assert await repo.activity_counts(owner, start, today, public_only=True) == {}
    finally:
        await engine.dispose()
