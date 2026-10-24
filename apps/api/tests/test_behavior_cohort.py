from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.behavior.cohort import behavior_cohort_goals
from personal_markets.goals.domain import GoalContract, GoalType


def _goal(*, synthetic: bool) -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Read twenty books",
        goal_type=GoalType.THRESHOLD,
        success_definition={"target": 20},
        deadline=datetime.now(UTC) + timedelta(days=30),
        state_dimensions=["books"],
        model_requirements={"workspace_seed": "fixture-v1"} if synthetic else {},
    )


def test_synthetic_commitments_are_separate_from_authentic_behavior() -> None:
    authentic, fixture = _goal(synthetic=False), _goal(synthetic=True)
    assert behavior_cohort_goals([authentic, fixture]) == [authentic]
    assert behavior_cohort_goals([authentic, fixture], synthetic=True) == [fixture]
    assert behavior_cohort_goals([fixture]) == []
