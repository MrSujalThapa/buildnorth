import asyncio
import json
from uuid import UUID

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.identity.testing import invited_principal
from personal_markets.social.playbook import normalize_steps, suggest_playbook
from test_social_marketplace import _goal, _register


def test_strategy_lists_stay_separate_steps() -> None:
    raw = str(["Send targeted applications", "Cold email founders"])
    assert normalize_steps(raw) == ["Send targeted applications", "Cold email founders"]
    assert normalize_steps(["Keep the written plan"]) == ["Keep the written plan"]


def test_suggested_playbooks_match_domain_without_claiming_progress() -> None:
    hiring, hiring_marks, hiring_logs = suggest_playbook(
        title="Land a forward-deployed engineer offer",
        success={"metric": "offer_received", "target": "signed_offer", "unit": "event"},
        category="career",
        goal_type="deadline_event",
    )
    assert len(hiring) >= 4
    assert any("not an application" in step for step in hiring)
    assert "Signed offer" in hiring_marks
    assert "Outreach emails sent" in hiring_logs

    reading, reading_marks, _ = suggest_playbook(
        title="Read 24 books by next summer",
        success={"metric": "books_read", "target": "24", "unit": "books"},
        category="reading",
        goal_type="threshold",
    )
    assert any("weekly" in step for step in reading)
    assert reading_marks == [
        "6 books finished",
        "12 books finished",
        "18 books finished",
        "24 books finished",
    ]

    saving, saving_marks, _ = suggest_playbook(
        title="Reach $100,000 net worth",
        success={"metric": "net_worth", "target": "100000", "unit": "USD"},
        category="finance",
        goal_type="continuous_target",
    )
    assert any("monthly" in step.lower() for step in saving)
    assert "$100,000 reached" in saving_marks
    assert "probability" not in json.dumps((hiring, reading, saving)).lower()


def test_creator_plan_wins_and_incomplete_snapshot_is_filled() -> None:
    app = isolated_app()
    owner = app.state.auth_bypass_principal
    visitor = invited_principal("playbook-visitor")
    _register(visitor)
    goal = _goal("Land a forward-deployed engineer offer")
    goal.success_definition = {
        "event": "signed_offer",
        "strategy": ["Apply to matching roles", "Log cold emails separately"],
        "private_journal": "recruiter@example.com secret",
    }
    bare = _goal("Land a forward-deployed engineer offer")
    bare.success_definition = {"event": "signed_offer", "private_journal": "hidden contact"}
    asyncio.run(app.state.goal_repository.create(goal, owner.user_id))
    asyncio.run(app.state.goal_repository.create(bare, owner.user_id))
    with TestClient(app) as client:
        for item in (goal, bare):
            assert (
                client.post(
                    f"/api/v1/social/markets/{item.goal_id}/visibility",
                    json={"visibility": "public"},
                ).status_code
                == 200
            )
        stored = app.state.social_repository._blueprint[goal.goal_id]
        assert stored["strategies"] == ["Apply to matching roles", "Log cold emails separately"]
        assert stored["strategies_source"] == "creator"
        assert "recruiter@example.com" not in json.dumps(stored)
        stored["strategies"] = [str(["Apply narrowly", "Track replies"])]
        restored = client.get(f"/api/v1/public/markets/{goal.goal_id}").json()["blueprint"]
        assert restored["strategies"] == ["Apply narrowly", "Track replies"]
        assert restored["strategies_source"] == "creator"

        old = app.state.social_repository._blueprint[bare.goal_id]
        old["strategies"] = []
        old["milestones"] = []
        old["evidence_types"] = []
        app.state.auth_bypass_principal = visitor
        detail = client.get(f"/api/v1/public/markets/{bare.goal_id}").json()["blueprint"]
        assert detail["strategies_source"] == "suggested"
        assert len(detail["strategies"]) >= 4
        assert any("not an application" in step for step in detail["strategies"])
        assert detail["milestones_source"] == "suggested"
        assert "Signed offer" in detail["milestones"]
        assert "private_journal" not in json.dumps(detail)
        assert "hidden contact" not in json.dumps(detail)

        forked = client.post(
            f"/api/v1/social/markets/{bare.goal_id}/fork",
            json={"idempotency_key": "playbook-fork"},
        ).json()
        copied = client.get(f"/api/v1/goals/{forked['goal_id']}").json()
        assert copied["success_definition"]["strategies"] == detail["strategies"]
        assert copied["success_definition"]["milestones"] == detail["milestones"]
        assert copied["success_definition"]["strategies_source"] == "suggested"
        assert "private_journal" not in json.dumps(copied)
        fork_id = UUID(forked["goal_id"])
        assert "observed" not in app.state.goal_repository._goals[fork_id].model_requirements


def test_reading_and_savings_templates_are_forkable() -> None:
    app = isolated_app()
    owner = app.state.auth_bypass_principal
    reading = _goal("Read 24 books by next summer")
    reading.success_definition = {
        "metric": "books_read",
        "operator": ">=",
        "target": "24",
        "unit": "books",
    }
    reading.model_requirements = {"life_area": "reading"}
    savings = _goal("Reach $100,000 net worth")
    savings.success_definition = {
        "metric": "net_worth",
        "operator": ">=",
        "target": "100000",
        "unit": "USD",
    }
    savings.model_requirements = {"life_area": "finance"}
    asyncio.run(app.state.goal_repository.create(reading, owner.user_id))
    asyncio.run(app.state.goal_repository.create(savings, owner.user_id))
    with TestClient(app) as client:
        for goal in (reading, savings):
            assert (
                client.post(
                    f"/api/v1/social/markets/{goal.goal_id}/visibility",
                    json={"visibility": "public"},
                ).status_code
                == 200
            )
        books = client.get(f"/api/v1/public/markets/{reading.goal_id}").json()["blueprint"]
        money = client.get(f"/api/v1/public/markets/{savings.goal_id}").json()["blueprint"]
    assert books["strategies_source"] == "suggested"
    assert "6 books finished" in books["milestones"]
    assert money["strategies_source"] == "suggested"
    assert "$100,000 reached" in money["milestones"]
    assert "email" not in json.dumps(money).lower()
