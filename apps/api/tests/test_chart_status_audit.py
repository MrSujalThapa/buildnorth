"""Published receipts and current publication state are separate contracts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import nan
from types import SimpleNamespace
from uuid import UUID

import pytest

from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.agents.model_planner import refine_architect_proposal
from personal_markets.forecasting.repository import PublishedBaseline
from personal_markets.identity.testing import make_principal
from personal_markets.ports import CriticArtifact, GoalArchitectProposal
from personal_markets.remote_mcp.charting import (
    filter_range,
    is_png,
    render_odds_png,
    series_from_history,
)
from remote_mcp_support import McpHarness, create_hiring_goal, register, structured


@pytest.mark.asyncio
async def test_pending_and_failed_creation_are_not_called_permanently_unpriced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        workflow = harness.app.state.agent_workflow
        for workflow_status, expected in (
            ("evidence_pending", "PENDING"), ("evidence_failed", "FAILED")
        ):
            async def creation_for_goal(
                *_: object, status: str = workflow_status
            ) -> SimpleNamespace:
                return SimpleNamespace(status=status)

            monkeypatch.setattr(workflow, "creation_for_goal", creation_for_goal)
            forecast = structured(await harness.call(
                grant.access_token, "get_forecast", {"goal_id": goal_id}
            ))
            readiness = structured(await harness.call(
                grant.access_token, "get_forecast_readiness", {"goal_id": goal_id}
            ))
            chart = structured(await harness.call(
                grant.access_token, "show_odds_chart", {"goal_id": goal_id}
            ))
            assert forecast["status"] == expected
            assert forecast["probability"] is None
            assert readiness["publication_status"] == expected
            assert chart["current_forecast_status"] == expected
            assert chart["points"] == []


@pytest.mark.asyncio
async def test_withheld_current_forecast_keeps_historical_chart_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        sent = await harness.call(
            grant.access_token,
            "submit_structured_evidence",
            {
                "goal_id": goal_id,
                "metric": "applications",
                "value": 12,
                "unit": "count",
                "observation_kind": "snapshot",
                "observed_at": datetime.now(UTC).isoformat(),
                "idempotency_key": "audit-chart-01",
                "source_category": "job_board",
            },
        )
        assert structured(sent)["publication"]["priced"] is True
        before = structured(
            await harness.call(grant.access_token, "get_forecast", {"goal_id": goal_id})
        )
        assert before["status"] == "PUBLISHED"
        async def later_pending(*_: object) -> SimpleNamespace:
            return SimpleNamespace(status="evidence_pending")

        monkeypatch.setattr(harness.app.state.agent_workflow, "creation_for_goal", later_pending)
        still_published = structured(
            await harness.call(grant.access_token, "get_forecast", {"goal_id": goal_id})
        )
        assert still_published["receipt_id"] == before["receipt_id"]
        deps = harness.app.state.agent_workflow._inner._deps
        await deps.goals.record_publication(
            UUID(goal_id),
            harness.owner.user_id,
            CriticArtifact(decision="withhold", issues=["Missing current evidence"]),
            "withheld",
        )
        current = structured(
            await harness.call(grant.access_token, "get_forecast", {"goal_id": goal_id})
        )
        readiness = structured(
            await harness.call(grant.access_token, "get_forecast_readiness", {"goal_id": goal_id})
        )
        history = structured(
            await harness.call(grant.access_token, "get_forecast_history", {"goal_id": goal_id})
        )
        chart = structured(
            await harness.call(grant.access_token, "show_odds_chart", {"goal_id": goal_id})
        )
        assert current["status"] == "WITHHELD"
        assert current["probability"] is None
        assert readiness["priced"] is False
        assert readiness["publication_status"] == "WITHHELD"
        assert history["total"] == before["published_points"]
        assert history["points"][-1]["receipt_id"] == before["receipt_id"]
        assert chart["status"] == "PUBLISHED"
        assert chart["current_forecast_status"] == "WITHHELD"
        assert chart["points"][-1]["receipt_id"] == before["receipt_id"]
        assert "Historical" in chart["message"]


@pytest.mark.parametrize("count", [0, 1, 2, 18])
def test_chart_series_preserves_real_receipts_across_five_ranges(count: int) -> None:
    stamp = datetime(2026, 10, 25, tzinfo=UTC)
    history = [
        PublishedBaseline(
            goal_id=UUID(int=1),
            probability=0.7646,
            forecast_status="ANCHORED",
            evidence_watermark=f"watermark-{index}",
            model_family="deadline_event_hazard",
            model_version="1",
            assumption_hash=f"assumption-{index}",
            material_hash=f"receipt-{index}",
            source_kind="published_forecast",
            receipt={},
            published_at=stamp - timedelta(days=index),
        )
        for index in range(count)
    ]
    series = series_from_history(list(reversed(history)))
    assert len(series) == count
    assert [item["timestamp_ms"] for item in series] == sorted(
        item["timestamp_ms"] for item in series
    )
    for range_key in ("1D", "1W", "1M", "1Y", "ALL"):
        visible = filter_range(series, range_key)
        assert len(visible) <= count
        assert is_png(render_odds_png(visible, title="FDE"))
    if count:
        assert series[-1]["probability_pct"] == pytest.approx(76.46)
        assert series[-1]["receipt_id"] == "receipt-0"


def test_chart_does_not_render_undated_or_invalid_probabilities() -> None:
    row = PublishedBaseline(
        goal_id=UUID(int=1),
        probability=0.7646,
        forecast_status="ANCHORED",
        evidence_watermark="e",
        model_family="m",
        model_version="1",
        assumption_hash="a",
        material_hash="r",
        source_kind="published_forecast",
        receipt={},
        published_at=None,
    )
    assert series_from_history([row]) == []
    assert (
        series_from_history([replace(row, published_at=datetime.now(UTC), probability=nan)]) == []
    )


@pytest.mark.asyncio
async def test_committed_self_report_populates_profile_after_refetch_but_not_other_owner() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        before = await harness.http.get("/api/v1/profile")
        assert before.status_code == 200
        payload = {
            "goal_id": goal_id,
            "metric": "applications",
            "value": 4,
            "unit": "count",
            "observation_kind": "increment",
            "observed_at": datetime.now(UTC).isoformat(),
            "idempotency_key": "audit-apps-001",
            "source_category": "self_report",
        }
        sent = await harness.call(grant.access_token, "submit_structured_evidence", payload)
        assert structured(sent)["status"] == "committed"
        refreshed = await harness.http.get("/api/v1/profile")
        assert refreshed.status_code == 200
        apps = next(
            row
            for row in refreshed.json()["radar"]["parameters"]
            if row["id"] == "weekly_applications"
        )
        assert apps["raw_value"] == 4
        assert apps["observation_count"] == 1
        assert apps["source_types"] == ["personal_agent"]
        repeated = await harness.call(grant.access_token, "submit_structured_evidence", payload)
        assert structured(repeated)["status"] in {"replayed", "committed"}
        again = await harness.http.get("/api/v1/profile")
        apps_again = next(
            row for row in again.json()["radar"]["parameters"] if row["id"] == "weekly_applications"
        )
        assert apps_again["raw_value"] == 4
        other = register(make_principal("audit-other-owner", invited=True, hosted=True))
        foreign = await harness.http.get("/api/v1/profile", headers=harness.user_headers(other))
        assert foreign.status_code == 200
        foreign_apps = next(
            row
            for row in foreign.json()["radar"]["parameters"]
            if row["id"] == "weekly_applications"
        )
        assert foreign_apps["value"] is None


@pytest.mark.asyncio
async def test_older_goal_without_creation_thread_has_optional_continuation_404() -> None:
    async with McpHarness() as harness:
        proposal = refine_architect_proposal(
            GoalArchitectProposal.model_validate(
                {
                    "ready_to_commit": True,
                    "title": "Ship 10 commits",
                    "goal_type": "threshold",
                    "success_metric": "commits_pushed",
                    "success_operator": ">=",
                    "success_target": "10",
                    "success_unit": "count",
                    "deadline": "2027-06-01",
                    "primitive_kind": "cumulative_count",
                    "state_dimensions": ["commits_pushed"],
                    "current_state_known": {"commits_pushed": "0"},
                    "model_family_compatibility": "deadline_event_hazard",
                }
            )
        )
        goals = harness.app.state.agent_workflow._inner._deps.goals
        goal = await goals.create_goal(proposal_to_contract(proposal), harness.owner.user_id)
        response = await harness.http.get(f"/api/v1/goals/{goal.goal_id}/evidence/continuation")
        assert response.status_code == 404
