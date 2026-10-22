from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.behavior.commitments import (
    Commitment,
    InMemoryCommitmentStore,
    trials_from_commitments,
)
from personal_markets.behavior.traits import estimate_traits
from personal_markets.core.errors import ResourceNotFoundError, SemanticProviderError
from personal_markets.goals.domain import GoalContract, GoalType


def _plan(owner_id=None, goal_id=None) -> Commitment:
    now = datetime.now(UTC)
    return Commitment(
        owner_id=owner_id or uuid4(),
        goal_id=goal_id or uuid4(),
        domain="coding",
        action="Solve LeetCode problems",
        planned_quantity=3,
        unit="problems",
        window_start=now,
        window_end=now + timedelta(days=7),
    )


@pytest.mark.asyncio
async def test_missing_and_cancelled_commitments_do_not_score_as_failures() -> None:
    store = InMemoryCommitmentStore()
    plan = await store.create(_plan())
    plans, observations = await store.list_for_goals(plan.owner_id, [plan.goal_id])
    assert trials_from_commitments(plans, observations) == []
    await store.observe(
        plan.owner_id,
        plan.id,
        status="cancelled",
        actual_quantity=None,
        observed_at=plan.window_end,
    )
    plans, observations = await store.list_for_goals(plan.owner_id, [plan.goal_id])
    assert trials_from_commitments(plans, observations) == []


@pytest.mark.asyncio
async def test_partial_then_completed_revision_uses_latest_immutable_outcome() -> None:
    store = InMemoryCommitmentStore()
    plan = await store.create(_plan())
    first = await store.observe(
        plan.owner_id,
        plan.id,
        status="partial",
        actual_quantity=1,
        observed_at=plan.window_end,
    )
    second = await store.observe(
        plan.owner_id,
        plan.id,
        status="completed",
        actual_quantity=3,
        observed_at=plan.window_end + timedelta(days=1),
    )
    assert (first.version, second.version) == (1, 2)
    plans, observations = await store.list_for_goals(plan.owner_id, [plan.goal_id])
    trials = trials_from_commitments(plans, observations)
    assert len(trials) == 1 and trials[0].outcome == 1
    assert len(observations) == 2


@pytest.mark.asyncio
async def test_owner_and_quantity_boundaries() -> None:
    store = InMemoryCommitmentStore()
    plan = await store.create(_plan())
    assert await store.list_for_goals(uuid4(), [plan.goal_id]) == ([], [])
    with pytest.raises(ResourceNotFoundError):
        await store.observe(
            uuid4(),
            plan.id,
            status="missed",
            actual_quantity=0,
            observed_at=plan.window_end,
        )
    with pytest.raises(SemanticProviderError):
        await store.observe(
            plan.owner_id,
            plan.id,
            status="completed",
            actual_quantity=2,
            observed_at=plan.window_end,
        )


@pytest.mark.asyncio
async def test_explicit_commitment_changes_radar_without_goal_progress() -> None:
    store = InMemoryCommitmentStore()
    goal_id = uuid4()
    owner_id = uuid4()
    for index in range(8):
        plan = _plan(owner_id, goal_id).model_copy(
            update={
                "id": uuid4(),
                "window_start": datetime.now(UTC) - timedelta(days=15 - index),
                "window_end": datetime.now(UTC) - timedelta(days=14 - index),
            }
        )
        await store.create(plan)
        await store.observe(
            owner_id,
            plan.id,
            status="completed",
            actual_quantity=3,
            observed_at=plan.window_end,
        )
    plans, observations = await store.list_for_goals(owner_id, [goal_id])
    goal = GoalContract(
        goal_id=goal_id,
        title="Solve 100 problems",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "problems_solved", "target": 100, "current": 0},
        deadline=datetime.now(UTC) + timedelta(days=100),
        state_dimensions=["problems_solved"],
    )
    profile = estimate_traits(trials_from_commitments(plans, observations), [])
    discipline = next(item for item in profile.traits if item.id == "discipline")
    assert discipline.value is not None and discipline.value > 0.5
    assert goal.success_definition["current"] == 0
