from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from personal_markets.goals.domain import ForecastStatus, GoalContract, GoalType


def valid_goal() -> dict[str, object]:
    return {
        "goal_id": uuid4(),
        "title": "Run a sub-50 minute 10K",
        "goal_type": GoalType.THRESHOLD,
        "success_definition": {"metric": "10k_time", "operator": "<=", "seconds": 3000},
        "deadline": datetime.now(UTC) + timedelta(days=90),
        "state_dimensions": ["recent_10k_time", "weekly_training_load"],
    }


def test_goal_contract_accepts_measurable_goal() -> None:
    goal = GoalContract.model_validate(valid_goal())
    assert goal.forecast_status is ForecastStatus.EXPLORATORY
    assert goal.version == 1


@pytest.mark.parametrize("field,value", [("success_definition", {}), ("state_dimensions", [])])
def test_goal_contract_rejects_incomplete_goal(field: str, value: object) -> None:
    payload = valid_goal()
    payload[field] = value
    with pytest.raises(ValidationError):
        GoalContract.model_validate(payload)


def test_forecast_status_values_are_stable() -> None:
    assert [status.value for status in ForecastStatus] == ["CALIBRATED", "ANCHORED", "EXPLORATORY"]
