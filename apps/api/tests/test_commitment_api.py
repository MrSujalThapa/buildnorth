import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.behavior.commitments import get_commitment_store
from personal_markets.goals.domain import GoalContract, GoalType


def test_commitment_api_keeps_unknown_unscored_and_revisions_visible() -> None:
    get_commitment_store.cache_clear()
    app = isolated_app()
    owner = app.state.auth_bypass_principal.user_id
    goal = GoalContract(
        goal_id=uuid4(),
        title="Solve three per week",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "problems_solved", "target": 100},
        deadline=datetime.now(UTC) + timedelta(days=100),
        state_dimensions=["problems_solved"],
    )
    asyncio.run(app.state.agent_workflow._inner._deps.goals._repository.create(goal, owner))
    start = datetime.now(UTC)
    path = f"/api/v1/goals/{goal.goal_id}/commitments"
    with TestClient(app) as client:
        created = client.post(
            path,
            json={
                "domain": "coding",
                "action": "Solve LeetCode problems",
                "planned_quantity": 3,
                "unit": "problems",
                "window_start": start.isoformat(),
                "window_end": (start + timedelta(days=7)).isoformat(),
            },
        )
        assert created.status_code == 200
        commitment_id = created.json()["id"]
        listed = client.get(path).json()
        assert len(listed["commitments"]) == 1
        assert listed["observations"] == []
        assert (
            client.post(
                f"{path}/{uuid4()}/observations",
                json={
                    "status": "missed",
                    "actual_quantity": 0,
                    "observed_at": start.isoformat(),
                },
            ).status_code
            == 404
        )
        first = client.post(
            f"{path}/{commitment_id}/observations",
            json={
                "status": "partial",
                "actual_quantity": 1,
                "observed_at": (start + timedelta(days=7)).isoformat(),
            },
        )
        assert first.status_code == 200 and first.json()["version"] == 1
        second = client.post(
            f"{path}/{commitment_id}/observations",
            json={
                "status": "completed",
                "actual_quantity": 3,
                "observed_at": (start + timedelta(days=8)).isoformat(),
            },
        )
        assert second.status_code == 200 and second.json()["version"] == 2
        assert len(client.get(path).json()["observations"]) == 2
