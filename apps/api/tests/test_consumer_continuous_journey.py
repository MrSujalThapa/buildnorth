# ruff: noqa: E501
"""Continuous consumer journeys through real FastAPI routes. Isolated in-memory app."""

from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.what_if.request_intent import classify_what_if_request


def _create_goal(client: TestClient, intent: str) -> str:
    created = client.post("/api/v1/agent/threads", json={"kind": "create_goal", "intent": intent})
    assert created.status_code == 200, created.text
    body = created.json()
    thread_id = body["thread_id"]
    if body["status"] == "needs_input":
        resumed = client.post(
            f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True}
        )
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
    goal = body.get("goal")
    assert goal and goal["goal_id"], body
    return str(goal["goal_id"])


def test_career_create_evidence_whatif_reprice_reload_journey() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_goal(
            client,
            "I want to receive an FDE offer from a target company by August 2027.",
        )
        stored = client.get(f"/api/v1/goals/{goal_id}")
        assert stored.status_code == 200
        assert stored.json()["goal_id"] == goal_id

        first = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "applications", "label": "Applications so far", "value": 12, "unit": "count"}
                ]
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["priced"] is True
        before = first.json()["probability"]
        history = client.get(f"/api/v1/what-if/history/{goal_id}").json()
        assert history
        receipt_id = history[-1]["id"]
        watermark = history[-1]["evidence_watermark"]

        baseline = client.get(f"/api/v1/what-if/baseline-state/{goal_id}").json()
        parsed = client.post(
            "/api/v1/what-if/parse-intervention",
            json={"goal_id": goal_id, "text": "What if I do 4 mock interviews per week?"},
        )
        assert parsed.status_code == 200, parsed.text
        assert parsed.json()["request_kind"] == "quantitative_scenario"
        simulated = client.post(
            "/api/v1/what-if/simulate",
            json={
                "goal_id": goal_id,
                "current_value": baseline["current_value"],
                "target_value": baseline["target_value"],
                "periods": baseline["periods"],
                "direction": baseline["direction"],
                "assumptions": baseline["assumptions"],
                "parsed_changes": parsed.json()["changes"],
                "intervention": baseline["default_intervention"],
                "config": baseline["config"],
            },
        )
        assert simulated.status_code == 200, simulated.text
        after_sim = client.get(f"/api/v1/what-if/history/{goal_id}").json()
        assert after_sim[-1]["id"] == receipt_id
        assert after_sim[-1]["probability"] == before

        strategy = client.post(
            "/api/v1/what-if/parse-intervention",
            json={
                "goal_id": goal_id,
                "text": "I keep reaching final rounds and getting no offers. What should I change?",
            },
        )
        assert strategy.status_code == 200, strategy.text
        assert strategy.json()["request_kind"] in {
            "strategic_advice",
            "opportunity_discovery",
            "exploratory_hypothetical",
        }
        assert strategy.json()["changes"] == []
        if strategy.json()["insights"]:
            assert all(item["model_status"] != "MODELED" for item in strategy.json()["insights"])

        diagnostic = client.post(
            "/api/v1/what-if/parse-intervention",
            json={"goal_id": goal_id, "text": "Why did my odds go down?"},
        )
        assert diagnostic.json()["request_kind"] == "diagnostic"
        assert diagnostic.json()["insights"] == []
        assert "invent" in diagnostic.json()["consumer_summary"].lower() or "priced" in diagnostic.json()["consumer_summary"].lower()

        second = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "responses", "label": "Recruiter responses", "value": 3, "unit": "count"},
                    {"key": "application_rejections", "label": "Rejections", "value": 6, "unit": "count"},
                ]
            },
        )
        assert second.status_code == 200, second.text
        after = second.json()["probability"]
        history2 = client.get(f"/api/v1/what-if/history/{goal_id}").json()
        assert history2[-1]["id"] != receipt_id
        assert history2[-1]["evidence_watermark"] != watermark
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence").json()
        assert any(item["metric"] == "application_rejections" for item in listed)

        retry = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "responses", "label": "Recruiter responses", "value": 3, "unit": "count"},
                    {"key": "application_rejections", "label": "Rejections", "value": 6, "unit": "count"},
                ]
            },
        )
        assert retry.json()["reprice_status"] == "unchanged"
        assert retry.json()["probability"] == after
        assert len(client.get(f"/api/v1/what-if/history/{goal_id}").json()) == len(history2)


def test_finance_domain_does_not_force_unpriceable_publish() -> None:
    with TestClient(isolated_app()) as client:
        goal_id = _create_goal(client, "I want to reach $80,000 in savings by December 2028.")
        posted = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "current_balance", "label": "Current savings", "value": 18000, "unit": "CAD"}
                ]
            },
        )
        assert posted.status_code == 200, posted.text
        listed = client.get(f"/api/v1/goals/{goal_id}/evidence").json()
        assert any(item["metric"] in {"current_balance", "net_worth"} for item in listed)
        if posted.json()["priced"]:
            history = client.get(f"/api/v1/what-if/history/{goal_id}").json()
            assert history
            contrib = client.post(
                f"/api/v1/goals/{goal_id}/evidence/manual",
                json={
                    "entries": [
                        {
                            "key": "monthly_contribution",
                            "label": "Monthly contribution",
                            "value": 900,
                            "unit": "CAD/month",
                        }
                    ]
                },
            )
            assert contrib.status_code == 200, contrib.text
        else:
            assert posted.json()["reprice_status"] in {"not_priced", "limited", "unchanged"}


def test_mixed_natural_language_routing_and_policy() -> None:
    cases = [
        ("What am I overlooking?", "opportunity_discovery"),
        ("I already tried that and it didn't work.", "evidence_report"),
        ("What's a better way to reach the same outcome?", "opportunity_discovery"),
        ("What would change your recommendation?", "diagnostic"),
        ("Why did my odds move even though I didn't change my plan?", "diagnostic"),
        ("I did it yesterday—can you record that?", "evidence_report"),
        ("What if I did half as much instead?", "follow_up"),
        ("Is the thing you suggested actually modeled or just an idea?", "strategic_advice"),
    ]
    mismatches = [
        (text, expected, classify_what_if_request(text).kind)
        for text, expected in cases
        if classify_what_if_request(text).kind != expected
    ]
    with TestClient(isolated_app()) as client:
        goal_id = _create_goal(
            client, "I want to receive an SWE offer from a target company by August 2027."
        )
        client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "applications", "label": "Applications", "value": 5, "unit": "count"}
                ]
            },
        )
        for text, expected in cases:
            parsed = client.post(
                "/api/v1/what-if/parse-intervention",
                json={"goal_id": goal_id, "text": text},
            )
            assert parsed.status_code == 200, parsed.text
            body = parsed.json()
            assert body["request_kind"] == expected, (text, body["request_kind"], mismatches)
            if expected in {"current_odds", "diagnostic", "evidence_report", "follow_up"}:
                assert body["insights"] == []
            if expected == "follow_up":
                assert "missing" in body["consumer_summary"].lower() or body["unsupported"]
            if expected == "evidence_report":
                assert body["confirmation_needed"] is True or "evidence" in body["consumer_summary"].lower()
    assert mismatches == []
