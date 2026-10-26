import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.identity.domain import Principal, UserProfile
from personal_markets.identity.factory import get_identity_repository
from personal_markets.identity.testing import invited_principal
from personal_markets.social.updates import (
    derive_updates,
    modeled_sensitivity,
    new_evidence_ids,
    receipt_facts,
)

E1, E2, E3, E4, E5 = (str(uuid4()) for _ in range(5))
SECRET_ASSUMPTION_VALUE = 0.734512
SECRET_STATE_VALUE = 13.37
START = datetime(2026, 10, 1, tzinfo=UTC)


def _receipt(
    ids: list[str],
    *,
    version: int = 1,
    deadline: str = "2026-12-31T23:59:59+00:00",
) -> dict[str, Any]:
    return {
        "normalized_evidence_ids": ids,
        "evidence_watermark": ids[-1],
        "goal_contract_version": version,
        "forecast_spec": {"deadline": deadline, "outcome": {"private_journal": "secret"}},
        "numeric_inputs": {"state": {"current_value": SECRET_STATE_VALUE}},
        "assumptions": [
            {"name": "application_rate", "value": SECRET_ASSUMPTION_VALUE, "source": "estimated"},
            {"name": "follow_through", "value": 0.91, "source": "behavior"},
            {"name": "current_value", "value": SECRET_STATE_VALUE},
            {"name": "offer_conversion", "value": [0.1, 0.2]},
        ],
    }


def _history() -> list[dict[str, Any]]:
    return [
        {
            "probability": 0.30,
            "created_at": START,
            "source_kind": "published_forecast",
            "forecast_status": "EXPLORATORY",
            "model_family": "count_process",
            "model_version": "v1",
            "receipt_json": _receipt([E1, E2]),
        },
        {
            "probability": 0.421,
            "created_at": START + timedelta(days=5),
            "source_kind": "published_forecast",
            "forecast_status": "EXPLORATORY",
            "model_family": "count_process",
            "model_version": "v1",
            "receipt_json": _receipt([E1, E2, E3, E4]),
        },
        {
            "probability": 0.9,
            "created_at": START + timedelta(days=6),
            "source_kind": "synthetic_demo",
        },
        {
            "probability": 0.35,
            "created_at": START + timedelta(days=9),
            "source_kind": "published_forecast",
            "forecast_status": "ANCHORED",
            "model_family": "count_process",
            "model_version": "v2",
            "receipt_json": _receipt(
                [E2, E3, E4, E5], version=2, deadline="2027-03-01T00:00:00+00:00"
            ),
        },
    ]


METRICS = {
    E1: "applications_submitted",
    E2: "interviews",
    E3: "applications_submitted",
    E4: "therapy_sessions",
    E5: "interviews",
}
TRACKED = ["applications_submitted", "interviews"]


def test_updates_describe_recorded_changes_between_publications() -> None:
    facts = receipt_facts(_history())
    assert new_evidence_ids(facts) == {E1, E2, E3, E4, E5}
    first, second, third = derive_updates(facts, tracked_metrics=TRACKED, evidence_metrics=METRICS)

    assert first.kind == "first_publication"
    assert first.change_points is None
    assert first.evidence_total == 2
    assert first.new_evidence_metrics == ["applications submitted", "interviews"]

    assert second.kind == "update"
    assert second.previous_probability == 0.30
    assert second.change_points == 12.1
    assert second.new_evidence_count == 2
    assert second.new_evidence_metrics == ["applications submitted"]
    assert second.other_new_evidence_count == 1
    assert second.retired_evidence_count == 0
    assert second.model_change is None
    assert not second.definition_revised and not second.deadline_changed

    assert third.change_points == -7.1
    assert third.new_evidence_count == 1
    assert third.retired_evidence_count == 1
    assert third.new_evidence_metrics == ["interviews"]
    assert third.model_change is not None
    assert (third.model_change.previous, third.model_change.current) == (
        "count_process@v1",
        "count_process@v2",
    )
    assert third.status_change is not None
    assert (third.status_change.previous, third.status_change.current) == (
        "exploratory",
        "anchored",
    )
    assert third.definition_revised and third.deadline_changed


def test_legacy_rows_without_receipts_report_nothing_invented() -> None:
    rows = [
        {"probability": 0.2, "created_at": START, "source_kind": "published_forecast"},
        {"probability": 0.25, "created_at": START + timedelta(days=1)},
    ]
    first, second = derive_updates(
        receipt_facts(rows), tracked_metrics=TRACKED, evidence_metrics={}
    )
    for update in (first, second):
        assert update.receipt_recorded is False
        assert update.evidence_total is None
        assert update.new_evidence_count is None
        assert update.model is None
    assert second.change_points == 5.0


def test_update_after_unrecorded_receipt_does_not_claim_new_evidence() -> None:
    rows = [
        {"probability": 0.2, "created_at": START},
        {
            "probability": 0.3,
            "created_at": START + timedelta(days=1),
            "receipt_json": {"normalized_evidence_ids": [E1, E2]},
        },
    ]
    _first, second = derive_updates(
        receipt_facts(rows), tracked_metrics=TRACKED, evidence_metrics=METRICS
    )
    assert second.receipt_recorded is True
    assert second.evidence_total == 2
    assert second.new_evidence_count is None
    assert second.new_evidence_metrics == []


def test_modeled_sensitivity_lists_public_assumption_names_only() -> None:
    sensitivity = modeled_sensitivity(receipt_facts(_history()))
    assert sensitivity is not None
    assert sensitivity.model == "count_process@v2"
    assert sensitivity.drivers == ["application rate", "offer conversion"]


def test_projected_postgres_receipt_shape_is_supported() -> None:
    row = {
        "probability": 0.4,
        "created_at": START,
        "model_family": "count_process",
        "model_version": "v1",
        "receipt_json": json.dumps(
            {
                "normalized_evidence_ids": [E1],
                "goal_contract_version": 1,
                "forecast_spec": {"deadline": None},
                "assumption_names": ["application_rate", None, "execution_probability"],
            }
        ),
    }
    facts = receipt_facts([row])
    assert facts[0].assumption_names == ("application_rate", "execution_probability")
    sensitivity = modeled_sensitivity(facts)
    assert sensitivity is not None and sensitivity.drivers == ["application rate"]


def _register(principal: Principal) -> None:
    repo = get_identity_repository()
    repo.users[principal.user_id] = principal
    repo.by_clerk[principal.clerk_user_id] = principal.user_id


def _goal() -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Land an FDE offer",
        goal_type=GoalType.THRESHOLD,
        success_definition={
            "metric": "applications_submitted",
            "operator": ">=",
            "target": 40,
            "milestones": ["Ship portfolio", "First onsite"],
            "strategy": "Two tailored applications per weekday",
            "private_journal": "Felt anxious after the recruiter call",
        },
        deadline=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
        state_dimensions=["applications_submitted", "interviews"],
    )


def test_public_payload_never_contains_private_evidence_or_measurements() -> None:
    app = isolated_app()
    owner = app.state.auth_bypass_principal
    visitor = invited_principal("updates-visitor")
    _register(visitor)
    asyncio.run(
        get_identity_repository().upsert_profile(
            owner.user_id, UserProfile(username="updates-owner", display_name="Owner")
        )
    )
    goal = _goal()
    asyncio.run(app.state.goal_repository.create(goal, owner.user_id))
    repo = app.state.social_repository
    repo.add_history(goal.goal_id, _history())
    repo.add_evidence_metrics(goal.goal_id, METRICS)
    with TestClient(app) as client:
        published = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/visibility", json={"visibility": "public"}
        )
        assert published.status_code == 200
        app.state.auth_bypass_principal = visitor
        response = client.get(f"/api/v1/public/markets/{goal.goal_id}")
    assert response.status_code == 200
    body = response.json()
    updates = body["updates"]
    assert [item["kind"] for item in updates] == ["first_publication", "update", "update"]
    assert updates[1]["change_points"] == 12.1
    assert updates[1]["new_evidence_metrics"] == ["applications submitted"]
    assert updates[1]["other_new_evidence_count"] == 1
    assert body["modeled_sensitivity"]["drivers"] == ["application rate", "offer conversion"]

    text = json.dumps(body)
    for forbidden in (
        str(SECRET_ASSUMPTION_VALUE),
        str(SECRET_STATE_VALUE),
        "numeric_inputs",
        "normalized_evidence_ids",
        "evidence_watermark",
        "follow_through",
        "therapy",
        "private_journal",
        "anxious",
        *METRICS.keys(),
    ):
        assert forbidden not in text, forbidden


def test_publish_snapshot_is_versioned_and_complete() -> None:
    app = isolated_app()
    goal = _goal()
    asyncio.run(app.state.goal_repository.create(goal, app.state.auth_bypass_principal.user_id))
    repo = app.state.social_repository
    with TestClient(app) as client:
        client.post(
            f"/api/v1/social/markets/{goal.goal_id}/visibility", json={"visibility": "public"}
        )
        stored = repo._blueprint[goal.goal_id]
        assert stored["blueprint_version"] == 2
        assert stored["snapshot_at"]
        assert stored["goal_contract_version"] == 1
        assert stored["tracked_metrics"] == ["applications_submitted", "interviews"]
        assert stored["success_criteria"]["operator"] == ">="
        assert stored["success_criteria"]["target"] == 40
        assert stored["deadline"].startswith("2026-12-31")
        assert stored["milestones"] == ["Ship portfolio", "First onsite"]
        assert stored["strategies"] == ["Two tailored applications per weekday"]
        assert "private_journal" not in json.dumps(stored)

        legacy = {key: value for key, value in stored.items() if key != "tracked_metrics"}
        legacy.pop("blueprint_version")
        legacy.pop("snapshot_at")
        repo._blueprint[goal.goal_id] = legacy
        detail = client.get(f"/api/v1/social/markets/{goal.goal_id}").json()
    preview = detail["public_preview"]
    assert preview["blueprint_version"] == 1
    assert preview["snapshot_at"] is None
    assert preview["tracked_metrics"] == ["applications_submitted", "interviews"]


def test_fork_copies_blueprint_structure_but_not_progress() -> None:
    app = isolated_app()
    owner = app.state.auth_bypass_principal
    visitor = invited_principal("updates-forker")
    _register(visitor)
    goal = _goal()
    asyncio.run(app.state.goal_repository.create(goal, owner.user_id))
    repo = app.state.social_repository
    repo.add_history(goal.goal_id, _history())
    repo.add_evidence_metrics(goal.goal_id, METRICS)
    with TestClient(app) as client:
        client.post(
            f"/api/v1/social/markets/{goal.goal_id}/visibility", json={"visibility": "public"}
        )
        app.state.auth_bypass_principal = visitor
        body = client.post(
            f"/api/v1/social/markets/{goal.goal_id}/fork",
            json={"idempotency_key": "updates-fork-key"},
        ).json()
        assert {"milestones", "strategy", "tracked_metrics", "success_criteria"} <= set(
            body["carried_fields"]
        )
        fork_id = UUID(body["goal_id"])
        forked = app.state.goal_repository._goals[fork_id]
        assert forked.success_definition["milestones"] == ["Ship portfolio", "First onsite"]
        assert forked.success_definition["strategy"] == "Two tailored applications per weekday"
        assert "private_journal" not in forked.success_definition
        assert list(forked.state_dimensions) == ["applications_submitted", "interviews"]
        metadata = forked.model_requirements["forked_blueprint"]
        assert metadata["source_blueprint_version"] == 2
        assert metadata["source_snapshot_at"]
        own_view = client.get(f"/api/v1/public/markets/{fork_id}").json()
    assert own_view["history"] == []
    assert own_view["updates"] == []
    assert own_view["modeled_sensitivity"] is None
