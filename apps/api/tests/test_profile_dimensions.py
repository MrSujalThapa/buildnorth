from datetime import UTC, datetime
from uuid import uuid4

from personal_markets.behavior.portfolio import portfolio_profile
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.identity.domain import ProfileDimension


def test_profile_dimensions_follow_user_order_and_keep_unknown_scores_null() -> None:
    goal = GoalContract(
        goal_id=uuid4(), title="Read 20 books", goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "books_read", "target": 20, "current": 6},
        deadline=datetime(2026, 12, 31, tzinfo=UTC),
        state_dimensions=["books_read"],
    )
    dimensions = [
        ProfileDimension(label="Music"),
        ProfileDimension(label="Reading", goal_ids=[goal.goal_id]),
    ]
    profile = portfolio_profile([goal], {}, dimensions=dimensions)
    assert [item.label for item in profile.dimensions] == ["Music", "Reading"]
    assert profile.dimensions[0].value is None
    assert profile.dimensions[1].value == 0.3
