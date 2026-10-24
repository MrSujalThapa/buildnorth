"""One local, isolated Spur-backed course-goal acceptance run.

The command requires --confirm-paid and caps estimated provider usage at $5.
It never writes to the configured database or a production account.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from personal_markets.agents.budget import InMemoryUsageStore, TokenBudget
from personal_markets.core.config import get_settings
from personal_markets.integrations.spur import SpurInferenceProvider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid", action="store_true")
    args = parser.parse_args()
    if not args.confirm_paid:
        parser.error("Pass --confirm-paid to authorize a capped local Spur run")
    os.environ["PM_ENVIRONMENT"] = "test"
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.spur_api_key:
        parser.error("Spur is not configured")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api/tests"))
    from helpers import isolated_app

    usage = InMemoryUsageStore()
    provider = SpurInferenceProvider(
        settings.spur_api_key,
        settings.spur_base_url,
        settings.resolved_spur_model(),
        TokenBudget(usage, high_volume_limit=100_000, premium_limit=100_000,
                    max_cost_usd=5.0),
        timeout_seconds=90,
        max_retries=0,
        max_output_tokens=3000,
    )
    app = isolated_app(inference=provider)
    goal_created = False
    workflow_finished = False
    grade_ok = False
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/agent/threads",
            json={
                "kind": "create_goal",
                "intent": (
                    "Earn at least 80% in my university course by December 31, 2026. "
                    "The midterm is worth 30% and I scored 90%. The final exam is worth "
                    "70% and has not happened yet."
                ),
            },
        )
        print("create_http", created.status_code)
        body = created.json()
        print("create_status", body.get("status"))
        if (
            body.get("status") == "needs_input"
            and body.get("interrupt", {}).get("type") == "confirm_contract"
        ):
            resumed = client.post(
                f"/api/v1/agent/threads/{body['thread_id']}/resume",
                json={"confirmed": True},
            )
            print("resume_http", resumed.status_code)
            body = resumed.json()
            print("resume_status", body.get("status"))
            if resumed.status_code != 200:
                print("resume_error", str(body.get("detail") or body.get("message"))[:250])
        goal = body.get("goal") or {}
        goal_created = bool(goal.get("goal_id"))
        workflow_finished = body.get("status") in {"completed", "limited", "withheld"}
        if not goal_created and created.status_code == 200:
            snapshot = client.get(f"/api/v1/agent/threads/{created.json()['thread_id']}")
            if snapshot.status_code == 200:
                snap = snapshot.json()
                print("thread_status_after_error", snap.get("status"))
                print("thread_step_after_error", snap.get("current_step"))
                goal = snap.get("goal") or {}
                goal_created = bool(goal.get("goal_id"))
        print("goal_created", goal_created)
        if goal.get("goal_id"):
            listed = client.get("/api/v1/goals").json()
            print("goal_persisted", any(item.get("goal_id") == goal["goal_id"] for item in listed))
        grade = client.post(
            "/api/v1/what-if/course-grade",
            json={
                "components": [
                    {"label": "midterm", "score": 90, "weight": 30},
                    {"label": "final", "score": None, "weight": 70, "known": False},
                ],
                "target": 80,
                "scenarios": [50, 80],
            },
        )
        result = grade.json()
        print("grade_http", grade.status_code)
        print("grade_status", result.get("status"))
        print("grade_arithmetic_only", result.get("arithmetic_only"))
        grade_ok = (
            grade.status_code == 200
            and result.get("arithmetic_only") is True
            and result.get("writes_evidence") is False
        )
        print("scenario_averages", json.dumps({
            item["remaining_score"]: item["average"] for item in result.get("scenarios", [])
        }, sort_keys=True))
    print("estimated_usage", json.dumps(asyncio.run(usage.totals(date.today())), sort_keys=True))
    if not goal_created or not workflow_finished or not grade_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
