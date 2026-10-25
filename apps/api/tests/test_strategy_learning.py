from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import (
    FailingInferenceProvider,
    ScriptedInferenceProvider,
)
from personal_markets.persistence.database import async_database_url, transaction
from personal_markets.persistence.repositories import PostgresGoalRepository
from personal_markets.ports import InferenceRequest
from personal_markets.strategy_learning.domain import Decision, RecommendationDraft
from personal_markets.strategy_learning.postgres import PostgresStrategyLearningRepository
from personal_markets.strategy_learning.service import (
    GroundedFact,
    RecommendationContext,
    StrategyLearningService,
    _validate_draft,
)


def isolated_postgres_url() -> str | None:
    return os.environ.get("PM_TEST_DATABASE_URL")


def _draft(now: datetime, *, strategy: str = "application_batch") -> dict[str, object]:
    return {
        "strategy_key": strategy,
        "action": f"Try {strategy.replace('_', ' ')} for the next month",
        "why_now": "The goal has a near term deadline and interviews are unobserved.",
        "next_step": "Record the next action and its date",
        "evidence_to_collect": "Interview invitations during the next month",
        "assumptions": ["This is an unpriced experiment"],
        "expected": {
            "metric": "interviews",
            "unit": "count",
            "direction": "increase",
            "target": 2,
            "horizon": (now + timedelta(days=30)).isoformat(),
        },
        "grounded_fact_ids": ["current_pipeline"],
        "external_citations": [],
        "claimed_relationship_ids": [],
    }


def test_recommendation_validation_rejects_ungrounded_and_priced_claims() -> None:
    now = datetime.now(UTC)
    context = RecommendationContext(
        as_of=now,
        facts=[
            GroundedFact(
                fact_id="current_pipeline",
                statement="No interviews recorded",
                observed_at=now,
                provenance="owner entered",
                kind="progress",
            )
        ],
    )
    proposal = RecommendationDraft.model_validate(_draft(now))
    _validate_draft(proposal, context)
    with pytest.raises(ValueError, match="ungrounded"):
        _validate_draft(proposal.model_copy(update={"grounded_fact_ids": ["invented"]}), context)
    with pytest.raises(ValueError, match="probability"):
        _validate_draft(proposal.model_copy(update={"why_now": "Odds rise by 20%"}), context)


@pytest.mark.integration
async def test_persistent_personal_learning_and_owner_isolation() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("An isolated migrated PostgreSQL database is required")
    engine = create_async_engine(async_database_url(url))
    owner, outsider, goal_id, evidence_id, outsider_goal = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    now = datetime.now(UTC).replace(microsecond=0)
    async with transaction(engine) as connection:
        for user_id in (owner, outsider):
            await connection.execute(
                text("""
                insert into app_users(id,clerk_user_id) values (:id,:clerk)
            """),
                {"id": user_id, "clerk": f"test_strategy_{user_id}"},
            )
        await connection.execute(
            text("""
            insert into goals (id,user_id,title,goal_type,success_definition_json,deadline,
              state_dimensions_json) values (:id,:owner,'Receive an FDE offer',
              'deadline_event',cast(:success as jsonb),:deadline,'["interviews"]'::jsonb)
        """),
            {
                "id": goal_id,
                "owner": owner,
                "deadline": now + timedelta(days=180),
                "success": '{"offer":1}',
            },
        )
        await connection.execute(
            text("""
            insert into evidence_events (id,user_id,event_type,domain,metric,numeric_value,
              unit,observed_at,source_quality,provenance_json)
            values (:id,:owner,'interview_count','career','interviews',0,'count',
              :observed,'user_entered','{"observation_kind":"snapshot"}'::jsonb)
        """),
            {"id": evidence_id, "owner": owner, "observed": now + timedelta(days=2)},
        )
        await connection.execute(
            text("""
            insert into goals (id,user_id,title,goal_type,success_definition_json,deadline,
              state_dimensions_json) values (:id,:owner,'Receive an FDE offer',
              'deadline_event',cast(:success as jsonb),:deadline,'["interviews"]'::jsonb)
        """),
            {
                "id": outsider_goal,
                "owner": outsider,
                "deadline": now + timedelta(days=180),
                "success": '{"offer":1}',
            },
        )
        await connection.execute(
            text("""
            insert into goal_evidence (goal_id,evidence_id) values (:goal,:evidence)
        """),
            {"goal": goal_id, "evidence": evidence_id},
        )

    def script(request: InferenceRequest) -> dict[str, object]:
        previous = request.input["previous_strategy_outcomes"]["past_trials"]
        strategy = (
            "targeted_outreach"
            if previous and previous[0]["outcome_status"] == "unsuccessful"
            else "application_batch"
        )
        return _draft(datetime.fromisoformat(request.input["as_of"]), strategy=strategy)

    inference = ScriptedInferenceProvider(script)
    repo = PostgresStrategyLearningRepository(engine)
    service = StrategyLearningService(repo, GoalService(PostgresGoalRepository(engine)), inference)
    context = RecommendationContext(
        as_of=now,
        progress={"interviews": 0},
        evidence_gaps=["No interviews recorded"],
        user_constraints=["10 hours per week"],
        facts=[
            GroundedFact(
                fact_id="current_pipeline",
                statement="No interviews recorded",
                observed_at=now,
                provenance="test goal record",
                kind="progress",
            )
        ],
    )
    first = await service.recommend(owner, goal_id, context)
    assert first.provenance["model"] == "scripted"
    assert (await service.learning_context(owner, goal_id, as_of=now)).past_trials == []
    assert (await service.learning_context(outsider, outsider_goal)).past_trials == []
    assert (
        await service.recommend(owner, goal_id, context)
    ).recommendation_id == first.recommendation_id
    assert (
        await service.feedback(
            owner, first.recommendation_id, Decision.ACCEPTED, at=now + timedelta(hours=1)
        )
    ).decision == Decision.ACCEPTED
    result = await service.record_outcome(
        owner,
        first.recommendation_id,
        idempotency_key="first-month",
        attempted=True,
        observed_value=0,
        evidence_ids=[evidence_id],
        observed_at=now + timedelta(days=31),
        provenance={"kind": "owner_confirmed"},
        observation_confidence=0.8,
    )
    assert result.status == "unsuccessful"
    with pytest.raises(DBAPIError, match="append-only"):
        async with transaction(engine) as connection:
            await connection.execute(
                text("""
                update strategy_outcome_observations set status='successful' where id=:id
            """),
                {"id": result.observation_id},
            )
    again = await service.record_outcome(
        owner,
        first.recommendation_id,
        idempotency_key="first-month",
        attempted=True,
        observed_value=0,
        evidence_ids=[evidence_id],
        observed_at=now + timedelta(days=31),
        provenance={"kind": "owner_confirmed"},
        observation_confidence=0.8,
    )
    assert again.observation_id == result.observation_id
    learned = await service.learning_context(owner, goal_id, as_of=now + timedelta(days=31))
    assert len(learned.past_trials) == 1
    assert learned.past_trials[0]["evidence_ids"] == [str(evidence_id)]
    assert learned.past_trials[0]["outcome_status"] == "unsuccessful"
    assert (
        await service.learning_context(owner, goal_id, as_of=now + timedelta(days=1))
    ).past_trials[0]["outcome_status"] == "not_observed"
    later = context.model_copy(update={"as_of": now + timedelta(days=32)})
    second = await service.recommend(owner, goal_id, later)
    assert second.strategy_key != first.strategy_key
    assert (
        inference.calls[-1].input["previous_strategy_outcomes"]["past_trials"][0]["outcome_status"]
        == "unsuccessful"
    )
    assert await repo.get(outsider, first.recommendation_id) is None
    assert (
        await service.feedback(
            owner, second.recommendation_id, Decision.DECLINED, at=now + timedelta(days=33)
        )
    ).decision == Decision.DECLINED
    with pytest.raises(ValueError, match="different feedback"):
        await service.feedback(
            owner, second.recommendation_id, Decision.ACCEPTED, at=now + timedelta(days=34)
        )
    unresolved = await service.record_outcome(
        owner,
        second.recommendation_id,
        idempotency_key="no-record-yet",
        attempted=None,
        observed_value=None,
        evidence_ids=[],
        observed_at=now + timedelta(days=34),
        provenance={"kind": "unknown"},
        observation_confidence=0,
    )
    assert unresolved.status == "pending"
    missing = await service.record_outcome(
        owner,
        second.recommendation_id,
        idempotency_key="still-no-record",
        attempted=None,
        observed_value=None,
        evidence_ids=[],
        observed_at=now + timedelta(days=63),
        provenance={"kind": "unknown"},
        observation_confidence=0,
    )
    assert missing.status == "insufficient_evidence"
    with pytest.raises(ValueError, match="owner"):
        await service.record_outcome(
            outsider,
            first.recommendation_id,
            idempotency_key="cross-owner",
            attempted=True,
            observed_value=1,
            evidence_ids=[evidence_id],
            observed_at=now + timedelta(days=35),
            provenance={},
            observation_confidence=1,
        )
    with pytest.raises(ValueError, match="different outcome"):
        await service.record_outcome(
            owner,
            first.recommendation_id,
            idempotency_key="first-month",
            attempted=None,
            observed_value=0,
            evidence_ids=[evidence_id],
            observed_at=now + timedelta(days=31),
            provenance={},
            observation_confidence=1,
        )
    async with transaction(engine) as connection:
        await connection.execute(
            text("""
            update evidence_events set status='retracted' where id=:evidence and user_id=:owner
        """),
            {"evidence": evidence_id, "owner": owner},
        )
    after_retraction = await service.learning_context(
        owner, goal_id, as_of=now + timedelta(days=64)
    )
    original = next(
        item
        for item in after_retraction.past_trials
        if item["recommendation_id"] == str(first.recommendation_id)
    )
    assert original["outcome_status"] == "inconclusive"
    assert original["provenance"]["current_evidence_status"] == "retracted"


@pytest.mark.integration
async def test_synthetic_evidence_cannot_link_to_authentic_learning() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("An isolated migrated PostgreSQL database is required")
    engine = create_async_engine(async_database_url(url))
    owner, goal_id, evidence_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC).replace(microsecond=0)
    async with transaction(engine) as connection:
        await connection.execute(
            text("insert into app_users(id,clerk_user_id) values (:id,:clerk)"),
            {"id": owner, "clerk": f"test_strategy_{owner}"},
        )
        await connection.execute(
            text("""
            insert into goals (id,user_id,title,goal_type,success_definition_json,deadline,
              state_dimensions_json) values (:id,:owner,'Study for exams',
              'deadline_event',cast(:success as jsonb),:deadline,'["study"]'::jsonb)
        """),
            {
                "id": goal_id,
                "owner": owner,
                "deadline": now + timedelta(days=180),
                "success": '{"pass":1}',
            },
        )
        await connection.execute(
            text("""
            insert into evidence_events (id,user_id,event_type,domain,metric,numeric_value,
              unit,observed_at,source_quality,provenance_json)
            values (:id,:owner,'study','education','study_hours',8,'hours',
              :observed,'user_entered','{}'::jsonb)
        """),
            {"id": evidence_id, "owner": owner, "observed": now + timedelta(days=1)},
        )
        await connection.execute(
            text("insert into goal_evidence(goal_id,evidence_id) values (:goal,:id)"),
            {"goal": goal_id, "id": evidence_id},
        )
        await connection.execute(
            text("""
            insert into workspace_seed_records(owner_id,seed_version,entity_type,entity_id)
            values (:owner,'pass9b-test','evidence',:id)
        """),
            {"owner": owner, "id": evidence_id},
        )

    def script(request: InferenceRequest) -> dict[str, object]:
        output = _draft(datetime.fromisoformat(request.input["as_of"]))
        output["grounded_fact_ids"] = []
        return output

    provider = ScriptedInferenceProvider(script)
    service = StrategyLearningService(
        PostgresStrategyLearningRepository(engine),
        GoalService(PostgresGoalRepository(engine)),
        provider,
    )
    context = RecommendationContext(as_of=now)
    trial = await service.recommend(owner, goal_id, context)
    with pytest.raises(ValueError, match="synthetic"):
        await service.record_outcome(
            owner,
            trial.recommendation_id,
            idempotency_key="synthetic",
            attempted=True,
            observed_value=8,
            evidence_ids=[evidence_id],
            observed_at=now + timedelta(days=31),
            provenance={},
            observation_confidence=1,
        )
    async with transaction(engine) as connection:
        await connection.execute(
            text("""
            insert into workspace_seed_records(owner_id,seed_version,entity_type,entity_id)
            values (:owner,'pass9b-test','goal',:id)
        """),
            {"owner": owner, "id": goal_id},
        )
    assert (await service.learning_context(owner, goal_id)).past_trials == []
    demo = await service.learning_context(owner, goal_id, include_synthetic=True)
    assert len(demo.past_trials) == 1


@pytest.mark.integration
async def test_inference_failure_does_not_persist_a_trial() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("An isolated migrated PostgreSQL database is required")
    engine = create_async_engine(async_database_url(url))
    owner, goal_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    async with transaction(engine) as connection:
        await connection.execute(
            text("insert into app_users(id,clerk_user_id) values (:id,:clerk)"),
            {"id": owner, "clerk": f"test_strategy_{owner}"},
        )
        await connection.execute(
            text("""
            insert into goals (id,user_id,title,goal_type,success_definition_json,deadline,
              state_dimensions_json) values (:id,:owner,'Practice running',
              'deadline_event',cast(:success as jsonb),:deadline,'["distance"]'::jsonb)
        """),
            {
                "id": goal_id,
                "owner": owner,
                "deadline": now + timedelta(days=180),
                "success": '{"distance":1}',
            },
        )
    repo = PostgresStrategyLearningRepository(engine)
    service = StrategyLearningService(
        repo,
        GoalService(PostgresGoalRepository(engine)),
        FailingInferenceProvider(RuntimeError("offline")),
    )
    with pytest.raises(RuntimeError, match="offline"):
        await service.recommend(owner, goal_id, RecommendationContext(as_of=now))
    assert await repo.history(owner, goal_id, now + timedelta(days=1)) == []
    attempts = 0

    def retry_script(request: InferenceRequest) -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {}
        output = _draft(
            datetime.fromisoformat(request.input["as_of"]), strategy="practice_schedule"
        )
        output["grounded_fact_ids"] = []
        output["expected"] = {
            "metric": "distance",
            "unit": "km",
            "direction": "increase",
            "target": 5,
            "horizon": (now + timedelta(days=30)).isoformat(),
        }
        return output

    provider = ScriptedInferenceProvider(retry_script)
    retry_service = StrategyLearningService(
        repo, GoalService(PostgresGoalRepository(engine)), provider
    )
    recovered = await retry_service.recommend(owner, goal_id, RecommendationContext(as_of=now))
    assert recovered.strategy_key == "practice_schedule"
    assert len(provider.calls) == 2
    assert len(await repo.history(owner, goal_id, now + timedelta(days=1))) == 1
