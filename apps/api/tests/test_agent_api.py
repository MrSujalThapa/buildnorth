from fastapi.testclient import TestClient

from helpers import isolated_app


def test_create_goal_and_resume_confirmation() -> None:
    with TestClient(isolated_app()) as client:
        response = client.post(
            "/api/v1/agent/threads",
            json={
                "kind": "create_goal",
                "intent": (
                    "I want to receive an SWE/FDE offer from one of my "
                    "target companies by August 2027."
                ),
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "needs_input"
        assert body["interrupt"]["type"] == "confirm_contract"
        thread_id = body["thread_id"]
        resumed = client.post(f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True})
        assert resumed.status_code == 200
        done = resumed.json()
        assert done["status"] in {"limited", "completed", "withheld"}
        assert done["goal"]["title"]
        assert done["pricing"]["raw_probability"] is None
        assert done["critic"]["decision"] in {"publish", "publish_with_limitations", "withhold"}
        listed = client.get("/api/v1/goals")
        assert listed.status_code == 200
        assert any(goal["goal_id"] == done["goal"]["goal_id"] for goal in listed.json())


def test_clarification_cancel() -> None:
    with TestClient(isolated_app()) as client:
        response = client.post(
            "/api/v1/agent/threads", json={"kind": "create_goal", "intent": "I want to get rich."}
        )
        thread_id = response.json()["thread_id"]
        cancelled = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume", json={"cancelled": True}
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
