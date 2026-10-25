from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.errors import TransientProviderError
from personal_markets.identity.testing import invited_principal
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
        assert resumed.json()["status"] == "evidence_pending"
        assert resumed.json()["pricing"] is None
        done = client.get(f"/api/v1/agent/threads/{thread_id}").json()
        assert done["status"] == "evidence_pending"
        assert done["goal"]["title"]
        assert done["pricing"] is None
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
        assert resumed.json()["status"] == "evidence_pending"
        body = client.get(f"/api/v1/agent/threads/{thread_id}").json()
        assert body["status"] == "evidence_failed"
        assert body["debug"]["goal_committed"] is True
        assert body["goal"] and body["goal"]["goal_id"]
        goal_id = body["goal"]["goal_id"]
        assert any(item["goal_id"] == goal_id for item in client.get("/api/v1/goals").json())
        polled = client.get(f"/api/v1/agent/threads/{thread_id}")
        assert polled.json()["goal"]["goal_id"] == goal_id


def test_evidence_failure_explicit_retry_completes_without_duplicate_goal() -> None:
    attempts = 0

    def script(request: InferenceRequest) -> dict[str, object]:
        nonlocal attempts
        output = default_agent_script(request)
        if request.agent_name == "goal_architect":
            output["current_state_known"] = {"phone_screen_result": "completed"}
        if request.agent_name == "evidence":
            attempts += 1
            if attempts == 1:
                raise TransientProviderError("provider timed out")
        return output

    with TestClient(isolated_app(inference=ScriptedInferenceProvider(script))) as client:
        created = client.post("/api/v1/agent/threads", json={
            "kind": "create_goal",
            "intent": "Receive an SWE offer by August 2027 after a phone screen this month.",
        }).json()
        thread_id = created["thread_id"]
        pending = client.post(f"/api/v1/agent/threads/{thread_id}/resume", json={
            "confirmed": True,
        }).json()
        goal_id = pending["goal"]["goal_id"]
        assert pending["status"] == "evidence_pending"
        assert pending["pricing"] is None
        failed = client.get(f"/api/v1/agent/threads/{thread_id}").json()
        assert failed["status"] == "evidence_failed"
        assert failed["pricing"] is None
        assert client.get(f"/api/v1/what-if/history/{goal_id}").json() == []
        continuation = client.get(f"/api/v1/goals/{goal_id}/evidence/continuation")
        assert continuation.json()["status"] == "evidence_failed"
        repeated = client.post(f"/api/v1/agent/threads/{thread_id}/resume", json={
            "confirmed": True,
        })
        assert repeated.status_code == 409
        retry = client.post(f"/api/v1/agent/threads/{thread_id}/evidence/retry")
        assert retry.status_code == 200, retry.text
        done = client.get(f"/api/v1/agent/threads/{thread_id}").json()
        assert done["status"] in {"completed", "limited", "withheld", "needs_input"}
        assert done["goal"]["goal_id"] == goal_id
        assert attempts == 2
        assert len([goal for goal in client.get("/api/v1/goals").json()
                    if goal["goal_id"] == goal_id]) == 1
        assert client.post(f"/api/v1/agent/threads/{thread_id}/evidence/retry").status_code == 409


def test_evidence_continuation_and_retry_are_owner_scoped() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        created = client.post("/api/v1/agent/threads", json={
            "kind": "create_goal", "intent": "Read 20 books by December 2027",
        }).json()
        thread_id = created["thread_id"]
        confirmed = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True}
        ).json()
        goal_id = confirmed["goal"]["goal_id"]
        app.state.auth_bypass_principal = invited_principal("another-user")
        assert client.get(f"/api/v1/agent/threads/{thread_id}").status_code == 404
        assert client.post(f"/api/v1/agent/threads/{thread_id}/evidence/retry").status_code == 404
        assert client.get(f"/api/v1/goals/{goal_id}/evidence/continuation").status_code == 404
