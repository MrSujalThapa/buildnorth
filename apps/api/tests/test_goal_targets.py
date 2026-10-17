from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.targets import (
    resolve_target_number,
    target_is_monetary,
)


def _goal(**success_definition: object) -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Test goal",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition=success_definition,
        deadline=datetime.now(UTC) + timedelta(days=365),
        state_dimensions=["current_value"],
    )


def test_resolve_target_number_reads_canonical_target_key() -> None:
    goal = _goal(metric="savings", target="$20,000")
    assert resolve_target_number(goal) == 20000.0


def test_target_is_monetary_detects_emergency_fund_synonyms() -> None:
    goal = GoalContract(
        goal_id=uuid4(),
        title="Build a $20,000 emergency fund by December 2027",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "emergency_fund_balance", "target": 20000, "unit": "USD"},
        deadline=datetime.now(UTC) + timedelta(days=365),
        state_dimensions=["current_value"],
    )
    assert target_is_monetary(goal) is True


def test_target_is_monetary_false_for_time_goals() -> None:
    goal = GoalContract(
        goal_id=uuid4(),
        title="Run a marathon in under 3:30",
        goal_type=GoalType.THRESHOLD,
        success_definition={"metric": "marathon_time", "target": "3:30:00"},
        deadline=datetime.now(UTC) + timedelta(days=365),
        state_dimensions=["current_value"],
    )
    assert target_is_monetary(goal) is False
