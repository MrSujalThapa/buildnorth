from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.errors import TransientProviderError
from personal_markets.integrations.fake_inference import (
    ScriptedInferenceProvider,
    default_agent_script,
)
from personal_markets.ports import InferenceRequest


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


def test_confirmed_goal_survives_downstream_provider_timeout() -> None:
    def script(request: InferenceRequest) -> dict[str, object]:
        if request.agent_name == "evidence":
            raise TransientProviderError("provider timed out")
        output = default_agent_script(request)
        if request.agent_name == "goal_architect":
            output["current_state_known"] = {"phone_screen_result": "completed"}
        return output

    with TestClient(isolated_app(inference=ScriptedInferenceProvider(script))) as client:
        created = client.post(
            "/api/v1/agent/threads",
            json={
                "kind": "create_goal",
                "intent": "Receive an SWE offer by August 2027 after a phone screen this month.",
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["status"] == "needs_input"
        thread_id = created.json()["thread_id"]
        resumed = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True}
        )
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert body["status"] == "failed"
        assert body["debug"]["goal_committed"] is True
        assert body["goal"] and body["goal"]["goal_id"]
        goal_id = body["goal"]["goal_id"]
        assert any(item["goal_id"] == goal_id for item in client.get("/api/v1/goals").json())
        polled = client.get(f"/api/v1/agent/threads/{thread_id}")
        assert polled.json()["goal"]["goal_id"] == goal_id
