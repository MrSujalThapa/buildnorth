from datetime import UTC, datetime
from uuid import uuid4

from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.identity.domain import ProfileDimension
from personal_markets.profile.parameters import build_parameter_profile, flatten_goal_evidence


def test_profile_parameters_do_not_use_life_area_or_trait_axes() -> None:
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
    profile = build_parameter_profile(flatten_goal_evidence({str(goal.goal_id): []}))
    assert profile.dimensions == []
    forbidden = {"Follow-through", "Reading", "Music"}
    assert all(item.label not in forbidden for item in profile.dimensions)
    assert [item.label for item in dimensions] == ["Music", "Reading"]
