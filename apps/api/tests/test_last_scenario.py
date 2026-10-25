import time
from uuid import uuid4

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.identity.testing import invited_principal
from personal_markets.what_if.intervention_models import InterventionChangeResponse
from personal_markets.what_if.last_scenario import LastInterventionStore, relative_scale


def test_relative_scale_tokens() -> None:
    assert relative_scale("What about doing half as much?") == 0.5
    assert relative_scale("do twice as many") == 2.0
    assert relative_scale("okay, actually make it 15") is None


def test_store_expires_and_isolates_owner_goal() -> None:
    store = LastInterventionStore(ttl_seconds=0.05)
    owner = uuid4()
    other = uuid4()
    goal = uuid4()
    other_goal = uuid4()
    change = InterventionChangeResponse(
        metric="weekly_application_rate",
        operation="set",
        value=15,
        unit="count_per_week",
        provenance="agent",
    )
    store.put(owner, goal, "fifteen a week", [change])
    assert store.get(owner, other_goal) is None
    assert store.get(other, goal) is None
    assert store.get(owner, goal) is not None
    time.sleep(0.06)
    assert store.get(owner, goal) is None


def _scripted_goal(client: TestClient) -> str:
    created = client.post(
        "/api/v1/agent/threads",
        json={
            "kind": "create_goal",
            "intent": "I want to receive an SWE offer from a target company by August 2027.",
        },
    )
    thread_id = created.json()["thread_id"]
    confirmed = client.post(
        f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True}
    ).json()
    goal = confirmed["goal"]
    assert isinstance(goal, dict)
    goal_id = goal["goal_id"]
    assert isinstance(goal_id, str)
    return goal_id


def test_http_follow_up_reuses_last_scenario_for_same_owner_goal() -> None:
    app = isolated_app()
    with TestClient(app) as client:
        goal_id = _scripted_goal(client)
        first = client.post(
            "/api/v1/what-if/parse-intervention",
            json={
                "goal_id": goal_id,
                "text": "What if I apply to 15 jobs a week?",
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["changes"]
        original = first.json()["changes"][0]["value"]
        follow = client.post(
            "/api/v1/what-if/parse-intervention",
            json={"goal_id": goal_id, "text": "What if I did half as much instead?"},
        )
        assert follow.status_code == 200, follow.text
        body = follow.json()
        assert body["request_kind"] == "quantitative_scenario"
        assert body["changes"]
        assert body["changes"][0]["value"] == original * 0.5
        assert body["changes"][0]["provenance"] == "last_scenario_relative"
        app.state.auth_bypass_principal = invited_principal("another-user")
        other_goal = _scripted_goal(client)
        missing = client.post(
            "/api/v1/what-if/parse-intervention",
            json={"goal_id": other_goal, "text": "What if I did half as much instead?"},
        )
        assert missing.status_code == 200, missing.text
        assert missing.json()["request_kind"] in {"follow_up", "clarification_needed"}
        assert not missing.json()["changes"]
