from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from personal_markets.goals.service import GoalService
from personal_markets.identity.testing import invited_principal
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.main import create_app
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresGoalRepository
from personal_markets.ports import InferenceRequest
from personal_markets.strategy_learning.api import get_strategy_learning_service
from personal_markets.strategy_learning.context_source import PostgresGoalContextSource
from personal_markets.strategy_learning.postgres import PostgresStrategyLearningRepository
from personal_markets.strategy_learning.service import StrategyLearningService


@pytest.mark.integration
def test_pollable_recommendations_and_feedback_are_owner_scoped() -> None:
    url = os.environ.get("PM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("An isolated migrated PostgreSQL database is required")
    principal = invited_principal(f"strategy-api-{uuid4()}")
    goal_id = uuid4()
    evidence_id = uuid4()
    now = datetime.now(UTC)
    with psycopg.connect(url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "insert into app_users(id,clerk_user_id) values (%s,%s)",
            (principal.user_id, principal.clerk_user_id),
        )
        cursor.execute(
            """
            insert into goals (id,user_id,title,goal_type,success_definition_json,
              deadline,state_dimensions_json)
            values (%s,%s,'Receive an offer','deadline_event',%s::jsonb,%s,%s::jsonb)
        """,
            (
                goal_id,
                principal.user_id,
                '{"offer":1}',
                now + timedelta(days=180),
                '["interviews"]',
            ),
        )
        cursor.execute(
            """
            insert into evidence_events (id,user_id,event_type,domain,metric,
              numeric_value,unit,observed_at,source_quality,provenance_json)
            values (%s,%s,'interview_count','career','interviews',1,'count',%s,
              'user_entered','{"observation_kind":"snapshot"}'::jsonb)
        """,
            (evidence_id, principal.user_id, now - timedelta(days=1)),
        )
        cursor.execute(
            "insert into goal_evidence(goal_id,evidence_id) values (%s,%s)", (goal_id, evidence_id)
        )

    def script(request: InferenceRequest) -> dict[str, object]:
        stamp = datetime.fromisoformat(request.input["as_of"])
        assert request.input["current_progress"]["recent_observations"][0]["evidence_id"] == str(
            evidence_id
        )
        return {
            "strategy_key": "targeted_outreach",
            "action": "Contact relevant hiring teams",
            "why_now": "The offer deadline is approaching",
            "next_step": "Select one team to contact",
            "evidence_to_collect": "Record interview invitations",
            "assumptions": ["No numerical effect is claimed"],
            "expected": {
                "metric": "interviews",
                "unit": "count",
                "direction": "increase",
                "target": 1,
                "horizon": (stamp + timedelta(days=30)).isoformat(),
            },
            "grounded_fact_ids": [f"evidence:{evidence_id}"],
            "external_citations": [],
            "claimed_relationship_ids": [],
        }

    engine = create_engine(url)
    inference = ScriptedInferenceProvider(script)
    service = StrategyLearningService(
        PostgresStrategyLearningRepository(engine),
        GoalService(PostgresGoalRepository(engine)),
        inference,
        PostgresGoalContextSource(engine),
    )
    app = create_app()
    app.dependency_overrides[get_strategy_learning_service] = lambda: service
    app.state.auth_bypass_principal = principal
    path = f"/api/v1/goals/{goal_id}/strategy-recommendations"
    with TestClient(app) as client:
        assert client.get(path).json()["past_trials"] == []
        assert (
            client.post(
                path,
                json={
                    "facts": [
                        {
                            "fact_id": "r",
                            "statement": "I know the hiring manager",
                            "observed_at": now.isoformat(),
                            "provenance": "user",
                            "kind": "relationship",
                        }
                    ]
                },
            ).status_code
            == 422
        )
        generated = client.post(path, json={})
        assert generated.status_code == 200, generated.text
        identifier = generated.json()["recommendation_id"]
        assert generated.json()["provenance"]["model"] == "scripted"
        repeated = client.post(path, json={})
        assert repeated.status_code == 200
        assert repeated.json()["recommendation_id"] == identifier
        assert len(inference.calls) == 1
        listed = client.get(path)
        assert listed.status_code == 200
        assert listed.json()["past_trials"][0]["recommendation_id"] == identifier
        feedback = client.post(f"{path}/{identifier}/feedback", json={"decision": "accepted"})
        assert feedback.status_code == 200
        assert feedback.json()["decision"] == "accepted"
        outcome_path = f"{path}/{identifier}/outcomes"
        outcome_at = now + timedelta(days=31)
        old_evidence = client.post(
            outcome_path,
            json={
                "idempotency_key": "old-evidence",
                "attempted": True,
                "observed_value": 1,
                "evidence_ids": [str(evidence_id)],
                "observed_at": outcome_at.isoformat(),
                "observation_confidence": 0.8,
            },
        )
        assert old_evidence.status_code == 422
        later_evidence_id = uuid4()
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                insert into evidence_events (id,user_id,event_type,domain,metric,
                  numeric_value,unit,observed_at,source_quality,provenance_json)
                values (%s,%s,'interview_count','career','interviews',1,'count',%s,
                  'user_entered','{"observation_kind":"snapshot"}'::jsonb)
            """,
                (later_evidence_id, principal.user_id, now + timedelta(days=2)),
            )
            cursor.execute(
                "insert into goal_evidence(goal_id,evidence_id) values (%s,%s)",
                (goal_id, later_evidence_id),
            )
        mismatched = client.post(
            outcome_path,
            json={
                "idempotency_key": "mismatched-value",
                "attempted": True,
                "observed_value": 2,
                "evidence_ids": [str(later_evidence_id)],
                "observed_at": outcome_at.isoformat(),
                "observation_confidence": 0.8,
            },
        )
        assert mismatched.status_code == 422
        unverified_final = client.post(
            outcome_path,
            json={
                "idempotency_key": "unverified-final",
                "attempted": True,
                "observed_value": 1,
                "evidence_ids": [str(later_evidence_id)],
                "observed_at": outcome_at.isoformat(),
                "observation_confidence": 0.8,
                "outcome_kind": "final",
            },
        )
        assert unverified_final.status_code == 422
        result = client.post(
            outcome_path,
            json={
                "idempotency_key": "later-evidence",
                "attempted": True,
                "observed_value": 1,
                "evidence_ids": [str(later_evidence_id)],
                "observed_at": outcome_at.isoformat(),
                "observation_confidence": 0.8,
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "successful"
        app.state.auth_bypass_principal = invited_principal(f"other-{uuid4()}")
        assert client.get(path).status_code == 404
        assert (
            client.post(f"{path}/{identifier}/feedback", json={"decision": "declined"}).status_code
            == 404
        )
