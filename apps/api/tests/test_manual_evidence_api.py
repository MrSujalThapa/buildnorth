from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.errors import ProviderNotConfiguredError
from personal_markets.evidence.service import evidence_fingerprint
from personal_markets.integrations.fake_inference import (
    FailingInferenceProvider,
    ScriptedInferenceProvider,
)
from personal_markets.ports import EvidenceEventProposal, ResumePayload, WorkflowRequest
from personal_markets.wiring import build_in_memory_workflow


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
    assert response.status_code == 200
    thread_id = response.json()["thread_id"]
    resumed = client.post(f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True})
    assert resumed.status_code == 200
    goal = resumed.json()["goal"]
    assert goal and goal["goal_id"]
    return str(goal["goal_id"])


def test_manual_numeric_evidence_does_not_crash_reprice_dependency() -> None:
    """Regression: reprice DI must receive Request so manual numeric evidence can publish."""
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        response = client.post(
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
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["events"]
        assert body["events"][0]["metric"] == "applications_submitted"
        assert body["reprice_status"] in {"completed", "limited"}
        assert body["priced"] is True
        assert body["probability"] is not None
        history = client.app.state.agent_workflow._inner._deps.baseline_forecasts.history(
            UUID(goal_id)
        )
        assert history
        assert history[-1].source_kind == "published_forecast"
        assert history[-1].probability == pytest.approx(body["probability"])
        assert history[-1].receipt.get("llm_used_for_probability") is False


def test_successive_application_snapshots_reprice_latest_not_sum() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        first = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {
                        "key": "applications",
                        "label": "Applications submitted so far",
                        "value": 6,
                        "unit": "count",
                    }
                ]
            },
        )
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
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence")
        application_rows = [
            item for item in listed.json() if item["metric"] == "applications_submitted"
        ]
        assert {item["numeric_value"] for item in application_rows} == {6.0, 18.0}
        history = client.app.state.agent_workflow._inner._deps.baseline_forecasts.history(
            UUID(goal_id)
        )
        assert history
        funnel = history[-1].receipt["feature_transforms"]["funnel_state"]
        assert funnel["applications"] == 18
        assert second.json()["probability"] == pytest.approx(history[-1].probability)


def test_duplicate_manual_evidence_is_idempotent() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        payload = {
            "entries": [
                {
                    "key": "applications",
                    "label": "Applications submitted so far",
                    "value": 8,
                    "unit": "count",
                }
            ]
        }
        first = client.post(f"/api/v1/goals/{goal_id}/evidence/manual", json=payload)
        second = client.post(f"/api/v1/goals/{goal_id}/evidence/manual", json=payload)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["reprice_status"] == "unchanged"
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        history = client.app.state.agent_workflow._inner._deps.baseline_forecasts.history(
            UUID(goal_id)
        )
        assert len(history) == 1


@pytest.mark.asyncio
async def test_structured_evidence_skips_evidence_agent() -> None:
    provider = ScriptedInferenceProvider()
    workflow = build_in_memory_workflow(inference=provider)
    started = await workflow.start(
        WorkflowRequest(
            kind="create_goal",
            intent=(
                "I want to receive an SWE/FDE offer from one of my "
                "target companies by August 2027."
            ),
        )
    )
    resumed = await workflow.resume(started.thread_id, ResumePayload(confirmed=True))
    assert resumed.goal is not None
    evidence_calls_after_goal = [
        call.agent_name for call in provider.calls if call.agent_name == "evidence"
    ]
    await workflow.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=resumed.goal.goal_id,
            evidence_events=[
                EvidenceEventProposal(
                    event_type="manual_state_entry",
                    domain="user_state",
                    metric="applications",
                    numeric_value=12,
                    unit="count",
                    observed_at=datetime.now(UTC).isoformat(),
                    source_type="csv",
                    summary="Applications imported from CSV",
                )
            ],
        )
    )
    evidence_calls = [call.agent_name for call in provider.calls if call.agent_name == "evidence"]
    assert evidence_calls == evidence_calls_after_goal
    critic_calls = [call.agent_name for call in provider.calls if call.agent_name == "critic"]
    assert critic_calls == []
    research_calls = [call.agent_name for call in provider.calls if call.agent_name == "research"]
    assert research_calls == []
    rows = await workflow._inner._deps.evidence.list_for_goal(resumed.goal.goal_id)
    assert rows
    assert rows[0].metric == "applications_submitted"


def test_http_structured_evidence_skips_inference() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        response = client.post(
            f"/api/v1/goals/{goal_id}/evidence",
            json={
                "kind": "add_evidence",
                "evidence_events": [
                    {
                        "event_type": "manual_state_entry",
                        "domain": "user_state",
                        "metric": "applications",
                        "numeric_value": 15,
                        "unit": "count",
                        "observed_at": datetime.now(UTC).isoformat(),
                        "source_type": "csv",
                        "summary": "Applications imported from CSV",
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] in {"completed", "limited"}
        assert body["pricing"]["priced"] is True
        assert body["pricing"]["receipt"]["llm_used_for_probability"] is False
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence")
        assert any(item["metric"] == "applications_submitted" for item in listed.json())


def test_manual_and_natural_language_same_event_do_not_double_count() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        manual = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {
                        "key": "applications",
                        "label": "Applications submitted so far",
                        "value": 12,
                        "unit": "count",
                    }
                ]
            },
        )
        assert manual.status_code == 200, manual.text
        first_probability = manual.json()["probability"]
        natural_language = client.post(
            f"/api/v1/goals/{goal_id}/evidence",
            json={
                "kind": "add_evidence",
                "evidence_text": "I sent 12 job applications this week.",
            },
        )
        assert natural_language.status_code == 200, natural_language.text
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence")
        assert listed.status_code == 200
        application_rows = [
            item
            for item in listed.json()
            if item["metric"] == "applications_submitted" and item["numeric_value"] == 12
        ]
        assert len(application_rows) == 1
        provenance = application_rows[0]["provenance"]
        assert provenance["source_type"] == "manual"
        corroborating = provenance.get("corroborating_sources") or []
        assert corroborating
        assert any(
            item["source_type"] != "manual" or item["summary"] != application_rows[0]["summary"]
            for item in corroborating
        )
        history = client.app.state.agent_workflow._inner._deps.baseline_forecasts.history(
            UUID(goal_id)
        )
        assert len(history) == 1
        assert history[0].probability == pytest.approx(first_probability)


def test_invalid_manual_evidence_is_rejected() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        response = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={"entries": []},
        )
        assert response.status_code == 422


def test_unpriceable_manual_evidence_returns_explicit_reason() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        response = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {
                        "key": "sleep_hours",
                        "label": "Hours slept",
                        "value": 7.5,
                        "unit": "hours",
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["priced"] is False
        assert body["reprice_status"] == "not_priced"
        assert body["reason"]
        history = client.app.state.agent_workflow._inner._deps.baseline_forecasts.history(
            UUID(goal_id)
        )
        assert history == []


def test_natural_language_evidence_publishes_with_scripted_provider() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_hiring_goal(client)
        response = client.post(
            f"/api/v1/goals/{goal_id}/evidence",
            json={"kind": "add_evidence", "evidence_text": "I sent 12 job applications this week."},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] in {"completed", "limited"}
        assert body["pricing"]["priced"] is True
        assert body["pricing"]["raw_probability"] is not None
        assert body["pricing"]["receipt"]["llm_used_for_probability"] is False
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence")
        assert listed.status_code == 200
        assert any(item["metric"] == "applications_submitted" for item in listed.json())
        history = client.app.state.agent_workflow._inner._deps.baseline_forecasts.history(
            UUID(goal_id)
        )
        assert history
        assert history[-1].source_kind == "published_forecast"


def test_inference_failure_is_explicit() -> None:
    app = isolated_app(
        inference=FailingInferenceProvider(ProviderNotConfiguredError("inference down"))
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/agent/threads",
            json={"kind": "create_goal", "intent": "I want a software offer by 2027."},
        )
        assert response.status_code == 503
        assert "inference down" in response.text


def test_unknown_goal_manual_evidence_is_not_found() -> None:
    with TestClient(isolated_app()) as client:
        response = client.post(
            f"/api/v1/goals/{uuid4()}/evidence/manual",
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
        assert response.status_code == 404


def test_manual_state_fingerprint_ignores_timestamp() -> None:
    user = uuid4()
    first = EvidenceEventProposal(
        event_type="manual_state_entry",
        domain="user_state",
        metric="applications",
        numeric_value=8,
        unit="count",
        observed_at="2026-01-01T00:00:00Z",
        source_type="manual",
        summary="Applications submitted so far",
    )
    second = first.model_copy(update={"observed_at": "2026-08-30T12:00:00Z"})
    assert evidence_fingerprint(user, first) == evidence_fingerprint(user, second)
