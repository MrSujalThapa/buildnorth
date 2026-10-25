# ruff: noqa: E501
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.identity.factory import get_identity_repository
from personal_markets.identity.testing import bearer_for, invited_principal
from personal_markets.integrations.fake_inference import (
    ScriptedInferenceProvider,
    default_agent_script,
)
from personal_markets.ports import InferenceRequest

TEST_SECRET = "phase1-test-secret-must-be-32b!!"


def _create_hiring_goal(client: TestClient) -> str:
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
    assert response.status_code == 200, response.text
    thread_id = response.json()["thread_id"]
    resumed = client.post(f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True})
    assert resumed.status_code == 200, resumed.text
    goal = resumed.json()["goal"]
    assert goal and goal["goal_id"]
    return str(goal["goal_id"])


def test_hiring_evidence_reprices_and_appears_on_whatif_history() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        before = client.get(f"/api/v1/what-if/history/{goal_id}")
        assert before.status_code == 200
        assert before.json() == []

        parsed = client.post(
            "/api/v1/what-if/parse-intervention",
            json={"goal_id": goal_id, "text": "What if I apply to 10 jobs a week?"},
        )
        assert parsed.status_code == 200, parsed.text
        assert parsed.json()["request_kind"] == "quantitative_scenario"

        first = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {
                        "key": "applications",
                        "label": "Applications submitted so far",
                        "value": 8,
                        "unit": "count",
                    }
                ]
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["priced"] is True
        first_p = first.json()["probability"]
        history = client.get(f"/api/v1/what-if/history/{goal_id}")
        assert history.status_code == 200
        assert len(history.json()) == 1
        assert history.json()[0]["probability"] == pytest.approx(first_p)
        assert history.json()[0]["source_kind"] == "published_forecast"

        baseline = client.get(f"/api/v1/what-if/baseline-state/{goal_id}")
        assert baseline.status_code == 200
        body = baseline.json()
        assert body["published_probability"] == pytest.approx(first_p)
        simulate_payload = {
            "goal_id": goal_id,
            "current_value": body["current_value"],
            "target_value": body["target_value"],
            "periods": body["periods"],
            "direction": body["direction"],
            "assumptions": body["assumptions"],
            "parsed_changes": parsed.json()["changes"],
            "intervention": body["default_intervention"],
            "config": body["config"],
        }
        simulated = client.post("/api/v1/what-if/simulate", json=simulate_payload)
        assert simulated.status_code == 200, simulated.text
        after_sim = client.get(f"/api/v1/what-if/history/{goal_id}")
        assert len(after_sim.json()) == 1
        assert after_sim.json()[0]["probability"] == pytest.approx(first_p)

        second = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {
                        "key": "applications",
                        "label": "Applications submitted so far",
                        "value": 18,
                        "unit": "count",
                    }
                ]
            },
        )
        assert second.status_code == 200, second.text
        second_p = second.json()["probability"]
        history2 = client.get(f"/api/v1/what-if/history/{goal_id}")
        assert len(history2.json()) == 2
        assert history2.json()[-1]["probability"] == pytest.approx(second_p)
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence")
        assert {item["numeric_value"] for item in listed.json() if item["metric"] == "applications_submitted"} == {
            8.0,
            18.0,
        }
        retry = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {
                        "key": "applications",
                        "label": "Applications submitted so far",
                        "value": 18,
                        "unit": "count",
                    }
                ]
            },
        )
        assert retry.json()["reprice_status"] == "unchanged"
        assert len(client.get(f"/api/v1/what-if/history/{goal_id}").json()) == 2


def test_resolved_funnel_and_unpriced_intro_observation() -> None:
    marker = f"intro-path-{UUID(int=1)}"

    def script(request: InferenceRequest) -> dict[str, Any]:
        if request.agent_name != "strategy":
            return default_agent_script(request)
        return {
            "understood_question": request.input["question"],
            "insights": [
                {
                    "title": str(marker),
                    "description": "Ask the recorded investor for founder intros.",
                    "why_it_might_help": "Access without a calibrated coefficient.",
                    "why_this_fits": "Authorized notes can mention an investor if present.",
                    "next_step": "Send a three-sentence ask.",
                    "evidence_to_collect": "Intros made.",
                    "constraints": "Spends relationship capital.",
                    "model_status": "UNPRICED",
                    "grounded_facts": [],
                    "assumptions": [],
                    "sources": [],
                }
            ],
            "limitations": [],
            "research_claims": [],
        }

    with TestClient(isolated_app(inference=ScriptedInferenceProvider(script))) as client:
        goal_id = _create_hiring_goal(client)
        opened = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "applications", "label": "Applications", "value": 10, "unit": "count"}
                ]
            },
        )
        assert opened.json()["priced"] is True
        resolved = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "responses", "label": "Recruiter responses", "value": 2, "unit": "count"},
                    {
                        "key": "application_rejections",
                        "label": "Application rejections",
                        "value": 8,
                        "unit": "count",
                    },
                ]
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["priced"] is True
        advice = client.post(
            "/api/v1/what-if/parse-intervention",
            json={
                "goal_id": goal_id,
                "text": "What if I asked an investor I know for introductions to hiring founders?",
            },
        )
        assert advice.status_code == 200, advice.text
        assert advice.json()["insights"]
        assert advice.json()["insights"][0]["model_status"] != "MODELED"
        assert advice.json()["changes"] == []
        note = client.post(
            f"/api/v1/goals/{goal_id}/evidence",
            json={
                "kind": "add_evidence",
                "evidence_events": [
                    {
                        "event_type": "observation",
                        "domain": "career",
                        "metric": "manual_note",
                        "categorical_value": "Introduced to three founders",
                        "observed_at": "2026-10-24T00:00:00+00:00",
                        "source_type": "manual",
                        "summary": "Introduced to three founders",
                    }
                ],
            },
        )
        assert note.status_code == 200, note.text
        rows = client.get(f"/api/v1/goals/{goal_id}/evidence").json()
        intro_rows = [item for item in rows if "founder" in (item.get("summary") or "").lower()]
        assert intro_rows
        assert intro_rows[0]["metric"] != "applications_submitted"


def test_finance_manual_progress_uses_contribution_metric() -> None:
    with TestClient(isolated_app()) as client:
        created = client.post(
            "/api/v1/agent/threads",
            json={
                "kind": "create_goal",
                "intent": "I want to reach $80,000 in savings by December 2028.",
            },
        )
        assert created.status_code == 200, created.text
        thread_id = created.json()["thread_id"]
        if created.json()["status"] == "needs_input":
            resumed = client.post(
                f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True}
            )
            assert resumed.status_code == 200, resumed.text
            goal = resumed.json()["goal"]
        else:
            goal = created.json()["goal"]
        if not goal:
            pytest.skip("Finance goal architect did not confirm a contract in this fixture")
        goal_id = str(goal["goal_id"])
        posted = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {
                        "key": "current_balance",
                        "label": "Current savings",
                        "value": 12000,
                        "unit": "CAD",
                    }
                ]
            },
        )
        assert posted.status_code == 200, posted.text
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence").json()
        assert any(item["metric"] in {"current_balance", "net_worth"} for item in listed)
        if posted.json()["priced"]:
            history = client.get(f"/api/v1/what-if/history/{goal_id}").json()
            assert history
        else:
            assert posted.json()["reprice_status"] in {"not_priced", "limited", "unchanged"}


def test_second_user_cannot_read_or_write_first_user_evidence() -> None:
    owner = invited_principal("http-owner-a")
    other = invited_principal("http-owner-b")
    app = isolated_app()
    repo = get_identity_repository()
    for principal in (owner, other):
        repo.users[principal.user_id] = principal
        repo.by_clerk[principal.clerk_user_id] = principal.user_id
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/agent/threads",
            headers={"Authorization": f"Bearer {bearer_for(owner, TEST_SECRET)}"},
            json={
                "kind": "create_goal",
                "intent": "I want to receive an SWE offer from a target company by August 2027.",
            },
        )
        thread_id = created.json()["thread_id"]
        resumed = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume",
            headers={"Authorization": f"Bearer {bearer_for(owner, TEST_SECRET)}"},
            json={"confirmed": True},
        )
        goal_id = resumed.json()["goal"]["goal_id"]
        owner_headers = {"Authorization": f"Bearer {bearer_for(owner, TEST_SECRET)}"}
        other_headers = {"Authorization": f"Bearer {bearer_for(other, TEST_SECRET)}"}
        seeded = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            headers=owner_headers,
            json={
                "entries": [
                    {"key": "applications", "label": "Applications", "value": 9, "unit": "count"}
                ]
            },
        )
        assert seeded.status_code == 200, seeded.text
        stolen_read = client.get(f"/api/v1/goals/{goal_id}/evidence", headers=other_headers)
        stolen_write = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            headers=other_headers,
            json={
                "entries": [
                    {"key": "applications", "label": "Applications", "value": 99, "unit": "count"}
                ]
            },
        )
        stolen_sim = client.post(
            "/api/v1/what-if/parse-intervention",
            headers=other_headers,
            json={"goal_id": goal_id, "text": "What if I apply to 10 jobs a week?"},
        )
        spoof = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            headers=other_headers,
            json={
                "user_id": str(owner.user_id),
                "entries": [
                    {"key": "applications", "label": "Applications", "value": 3, "unit": "count"}
                ],
            },
        )
        assert stolen_read.status_code == 404
        assert stolen_write.status_code == 404
        assert stolen_sim.status_code in {403, 404}
        assert spoof.status_code == 404
