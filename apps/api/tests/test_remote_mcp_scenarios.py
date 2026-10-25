"""Phase 4 scenarios B-F and H through the real MCP transport and OAuth tokens."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import Request

from personal_markets.agents.state import AgentDependencies
from personal_markets.core.errors import ProviderBudgetExceededError
from personal_markets.forecasting.reprice import BaselineRepriceService
from personal_markets.identity.testing import admin_principal, make_principal
from personal_markets.integrations.fake_inference import (
    FailingInferenceProvider,
    ScriptedInferenceProvider,
)
from personal_markets.wiring import get_what_if_service
from remote_mcp_support import (
    McpHarness,
    create_audience_goal,
    create_hiring_goal,
    register,
    structured,
)

NOW = datetime.now(UTC)


def _evidence(goal_id: str, key: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "goal_id": goal_id,
        "metric": "applications",
        "value": 12,
        "unit": "count",
        "observation_kind": "snapshot",
        "observed_at": NOW.isoformat(),
        "idempotency_key": key,
        "source_category": "job_board",
        "source_identifier": "greenhouse",
    }
    payload.update(overrides)
    return payload


def _deps(harness: McpHarness) -> AgentDependencies:
    deps: AgentDependencies = harness.app.state.agent_workflow._inner._deps
    return deps


def _scripted(harness: McpHarness) -> ScriptedInferenceProvider:
    provider = _deps(harness).inference
    assert isinstance(provider, ScriptedInferenceProvider)
    return provider


async def _history(harness: McpHarness, goal_id: str) -> list[Any]:
    service = _deps(harness).baseline_forecasts
    assert service is not None
    return list(await service.published_history(UUID(goal_id)))


async def _audience_series(harness: McpHarness, token: str, goal_id: str) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for index, (days, value) in enumerate([(90, 800), (60, 950), (30, 1100), (0, 1200)]):
        result = await harness.call(
            token,
            "submit_structured_evidence",
            {
                "goal_id": goal_id,
                "metric": "subscribers",
                "value": value,
                "unit": "subscribers",
                "observation_kind": "snapshot",
                "observed_at": (NOW - timedelta(days=days)).isoformat(),
                "idempotency_key": f"audience-{index:04d}",
                "source_category": "youtube_studio",
            },
        )
        assert result.is_error is False, structured(result)
        last = structured(result)
    return last


# --- Scenario B: career evidence and idempotency -------------------------------------


async def test_b_structured_career_evidence_publishes_without_llm() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        provider = _scripted(harness)
        calls_before = len(provider.calls)
        grant = await harness.connect(name="Career Agent")
        result = await harness.call(
            grant.access_token, "submit_structured_evidence", _evidence(goal_id, "career-0001")
        )
        body = structured(result)
        assert result.is_error is False, body
        assert body["status"] == "committed" and body["llm_calls"] == 0
        assert body["dedup"] == ["new"]
        item = body["evidence"][0]
        assert item["metric"] == "applications_submitted"
        assert item["source_type"] == "personal_agent"
        assert item["verification_status"] == "agent_reported"
        assert body["publication"]["priced"] is True
        assert len(provider.calls) == calls_before

        forecast = structured(
            await harness.call(grant.access_token, "get_forecast", {"goal_id": goal_id})
        )
        history = await _history(harness, goal_id)
        assert forecast["status"] == "PUBLISHED"
        assert forecast["probability"] == pytest.approx(history[-1].probability)
        assert forecast["probability"] == pytest.approx(body["publication"]["probability"])
        assert forecast["llm_used_for_probability"] is False
        assert forecast["evidence_watermark"] and forecast["published_at"]

        rest = (await harness.http.get(f"/api/v1/goals/{goal_id}/evidence")).json()
        provenance = rest[0]["provenance"]
        assert provenance["verification_status"] == "agent_reported"
        submission = provenance["submission"]
        assert submission["client_name"] == "Career Agent"
        assert submission["source_category"] == "job_board"
        assert "career-0001" not in str(submission)


async def test_b_retry_with_same_key_never_double_counts() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        payload = _evidence(goal_id, "retry-0001", observation_kind="increment", value=2)
        first = structured(
            await harness.call(grant.access_token, "submit_structured_evidence", payload)
        )
        second = structured(
            await harness.call(grant.access_token, "submit_structured_evidence", payload)
        )
        assert first["status"] == "committed"
        assert second["status"] == "replayed"
        assert second["evidence"][0]["evidence_id"] == first["evidence"][0]["evidence_id"]
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
        assert len(rows) == 1
        assert len(await _history(harness, goal_id)) == 1


async def test_b_reused_key_with_different_payload_is_rejected() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        await harness.call(
            grant.access_token, "submit_structured_evidence", _evidence(goal_id, "conflict-01")
        )
        result = await harness.call(
            grant.access_token,
            "submit_structured_evidence",
            _evidence(goal_id, "conflict-01", value=40),
        )
    assert result.is_error is True
    assert structured(result)["error"]["code"] == "idempotency_conflict"


async def test_b_distinct_increments_add_and_equal_snapshots_corroborate() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        for key in ("inc-a-0001", "inc-b-0001"):
            await harness.call(
                grant.access_token,
                "submit_structured_evidence",
                _evidence(goal_id, key, observation_kind="increment", value=2),
            )
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
        assert len([row for row in rows if row.provenance.observation_kind == "increment"]) == 2

        await harness.call(
            grant.access_token, "submit_structured_evidence", _evidence(goal_id, "snap-a-0001")
        )
        receipts_before_duplicate = len(await _history(harness, goal_id))
        again = structured(
            await harness.call(
                grant.access_token, "submit_structured_evidence", _evidence(goal_id, "snap-b-0001")
            )
        )
        assert again["dedup"] == ["corroborated_existing"]
        assert again["publication"]["status"] == "unchanged"
        snapshots = [
            row
            for row in await _deps(harness).evidence.list_for_goal(UUID(goal_id))
            if row.provenance.observation_kind == "snapshot"
        ]
        assert len(snapshots) == 1
        assert len(await _history(harness, goal_id)) == receipts_before_duplicate
        latest = structured(await harness.call(
            grant.access_token, "get_forecast", {"goal_id": goal_id}
        ))
        history = structured(await harness.call(
            grant.access_token, "get_forecast_history", {"goal_id": goal_id}
        ))
        assert latest["receipt_id"] == history["points"][-1]["receipt_id"]
        assert latest["published_at"] == history["points"][-1]["published_at"]


async def test_b_agent_report_corroborates_manual_entry_without_upgrading_trust() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        manual = await harness.http.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "applications", "label": "Applications", "value": 12, "unit": "count"}
                ]
            },
        )
        assert manual.status_code == 200, manual.text
        grant = await harness.connect()
        result = structured(
            await harness.call(
                grant.access_token, "submit_structured_evidence", _evidence(goal_id, "corrob-0001")
            )
        )
        assert result["dedup"] == ["corroborated_existing"]
        item = result["evidence"][0]
        assert item["source_type"] == "manual"
        assert item["corroborating_sources"] >= 1
        assert item["verification_status"] not in {"verified_outcome", "provider_backed"}
        assert len(await _history(harness, goal_id)) == 1


async def test_b_invalid_metric_unit_and_kind_are_rejected_with_policy_hints() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        token = grant.access_token
        bad_metric = structured(
            await harness.call(
                token,
                "submit_structured_evidence",
                _evidence(goal_id, "bad-metric1", metric="salary"),
            )
        )
        bad_unit = structured(
            await harness.call(
                token, "submit_structured_evidence", _evidence(goal_id, "bad-unit-01", unit="hours")
            )
        )
        future = structured(
            await harness.call(
                token,
                "submit_structured_evidence",
                _evidence(
                    goal_id, "future-0001", observed_at=(NOW + timedelta(days=5)).isoformat()
                ),
            )
        )
        no_time = structured(
            await harness.call(
                token,
                "submit_structured_evidence",
                _evidence(goal_id, "no-time-001", observed_at=None),
            )
        )
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
    assert bad_metric["error"]["code"] == "invalid_argument"
    assert "applications_submitted" in bad_metric["error"]["details"]["accepted_metrics"]
    assert bad_unit["error"]["code"] == "invalid_argument"
    assert future["error"]["code"] == "invalid_argument"
    assert no_time["error"]["code"] == "invalid_argument"
    assert rows == []


async def test_b_client_cannot_claim_higher_trust() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        result = await harness.call(
            grant.access_token,
            "submit_structured_evidence",
            {**_evidence(goal_id, "trust-00001"), "verification_status": "verified_outcome"},
        )
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
    assert result.is_error is True or rows[0].provenance.verification_status == "agent_reported"
    assert all(row.provenance.verification_status != "verified_outcome" for row in rows)


# --- Scenario C: audience growth through composition ----------------------------------


async def test_c_audience_growth_composes_and_publishes() -> None:
    async with McpHarness() as harness:
        goal_id = await create_audience_goal(harness)
        grant = await harness.connect()
        policy = structured(
            await harness.call(grant.access_token, "get_observation_policy", {"goal_id": goal_id})
        )
        assert policy["model_family"] == "composed_growth"
        assert [item["metric"] for item in policy["metrics"]] == ["subscribers"]
        last = await _audience_series(harness, grant.access_token, goal_id)
        assert last["publication"]["priced"] is True
        forecast = structured(
            await harness.call(grant.access_token, "get_forecast", {"goal_id": goal_id})
        )
        assert forecast["compiler_version"] == "composed_v1"
        assert forecast["model_family"] == "composed_growth"
        assert 0.0 <= forecast["probability"] <= 1.0
        assert any(item["name"] == "primary.mu" for item in forecast["assumptions"])
        history = structured(
            await harness.call(grant.access_token, "get_forecast_history", {"goal_id": goal_id})
        )
        assert history["points"][-1]["probability"] == pytest.approx(forecast["probability"])


# --- Scenario D: What If parity and NOT_PRICED ----------------------------------------


async def _use_mcp_what_if_for_rest(harness: McpHarness) -> None:
    factory = harness.app.state.remote_mcp.tools._what_if

    async def rest_service(request: Request) -> Any:
        return factory(harness.owner)

    harness.app.dependency_overrides[get_what_if_service] = rest_service


async def test_d_what_if_matches_rest_and_never_writes_published_history() -> None:
    async with McpHarness() as harness:
        await _use_mcp_what_if_for_rest(harness)
        goal_id = await create_audience_goal(harness)
        grant = await harness.connect()
        await _audience_series(harness, grant.access_token, goal_id)
        published_before = len(await _history(harness, goal_id))
        change = {"metric": "primary.mu", "operation": "set", "value": 0.2, "unit": "log/month"}
        mcp = structured(
            await harness.call(
                grant.access_token,
                "simulate_intervention",
                {"goal_id": goal_id, "changes": [change]},
            )
        )
        baseline = (await harness.http.get(f"/api/v1/what-if/baseline-state/{goal_id}")).json()
        rest = await harness.http.post(
            "/api/v1/what-if/fast-reprice",
            json={
                "goal_id": goal_id,
                "current_value": baseline["current_value"],
                "target_value": baseline["target_value"],
                "periods": baseline["periods"],
                "direction": baseline["direction"],
                "assumptions": baseline["assumptions"],
                "intervention": None,
                "parsed_changes": [{**change, "provenance": "USER_ASSUMPTION"}],
                "config": baseline["config"],
            },
        )
        assert rest.status_code == 200, rest.text
        rest_body = rest.json()
        assert mcp["priced"] is True, mcp
        assert mcp["status"] == rest_body["status"]
        assert mcp["delta_pp"] > 5, mcp
        # The hiring recency factor decays with wall-clock time between the two calls.
        assert mcp["scenario_probability"] == pytest.approx(
            rest_body["scenario_probability"], abs=1e-6
        )
        assert mcp["scenario_baseline_probability"] == pytest.approx(
            rest_body["baseline_probability"], abs=1e-6
        )
        assert mcp["delta_pp"] == pytest.approx(rest_body["expected_uplift_pp"], abs=1e-6)
        assert mcp["hypothetical"] is True and mcp["writes_published_history"] is False
        assert len(await _history(harness, goal_id)) == published_before


async def test_d_unmapped_action_is_not_priced_on_both_surfaces() -> None:
    async with McpHarness() as harness:
        await _use_mcp_what_if_for_rest(harness)
        goal_id = await create_audience_goal(harness)
        grant = await harness.connect()
        await _audience_series(harness, grant.access_token, goal_id)
        change = {
            "metric": "videos_per_week",
            "operation": "set",
            "value": 2,
            "unit": "videos/week",
        }
        mcp = structured(
            await harness.call(
                grant.access_token,
                "simulate_intervention",
                {"goal_id": goal_id, "changes": [change]},
            )
        )
        baseline = (await harness.http.get(f"/api/v1/what-if/baseline-state/{goal_id}")).json()
        rest = (
            await harness.http.post(
                "/api/v1/what-if/fast-reprice",
                json={
                    "goal_id": goal_id,
                    "current_value": baseline["current_value"],
                    "target_value": baseline["target_value"],
                    "periods": baseline["periods"],
                    "direction": baseline["direction"],
                    "assumptions": baseline["assumptions"],
                    "parsed_changes": [{**change, "provenance": "USER_ASSUMPTION"}],
                    "config": baseline["config"],
                },
            )
        ).json()
    assert mcp["status"] == "NOT_PRICED" == rest["status"]
    assert mcp["causal_status"] == "unmapped_intervention"
    assert rest["receipt"]["causal_status"] == "unmapped_intervention"
    assert mcp["scenario_probability"] is None
    assert mcp["unmapped_changes"] == ["videos_per_week"]


async def test_d_best_interventions_refuses_unsupported_rankings() -> None:
    async with McpHarness() as harness:
        goal_id = await create_audience_goal(harness)
        grant = await harness.connect()
        await _audience_series(harness, grant.access_token, goal_id)
        body = structured(
            await harness.call(grant.access_token, "get_best_interventions", {"goal_id": goal_id})
        )
    assert body["status"] == "UNAVAILABLE"
    assert body["ranked"] == []


async def test_d_unpublished_goal_reports_no_probability() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        body = structured(
            await harness.call(grant.access_token, "get_forecast", {"goal_id": goal_id})
        )
    assert body["status"] == "NOT_PUBLISHED"
    assert body["probability"] is None
    assert body["missing_inputs"][0]["key"] == "applications"
    assert "outside the models" not in body["message"]


# --- Scenario E: tenant isolation -----------------------------------------------------


@pytest.mark.parametrize("intruder_kind", ["member", "admin"])
async def test_e_other_users_goals_are_invisible(intruder_kind: str) -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        intruder = register(
            admin_principal()
            if intruder_kind == "admin"
            else make_principal("intruder", invited=True)
        )
        grant = await harness.connect(intruder)
        token = grant.access_token
        listed = structured(await harness.call(token, "list_goals", {}))
        assert listed["goals"] == []
        for tool, args in [
            ("get_goal", {"goal_id": goal_id}),
            ("get_forecast", {"goal_id": goal_id}),
            ("get_evidence_summary", {"goal_id": goal_id}),
            ("get_observation_policy", {"goal_id": goal_id}),
            ("submit_structured_evidence", _evidence(goal_id, "intrude-0001")),
            (
                "simulate_intervention",
                {
                    "goal_id": goal_id,
                    "changes": [{"metric": "flow", "operation": "set", "value": 1, "unit": "x"}],
                },
            ),
        ]:
            result = await harness.call(token, tool, args)
            assert result.is_error is True, tool
            assert structured(result)["error"]["code"] == "not_found", tool
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
    assert rows == []


async def test_e_supplied_user_id_is_ignored() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        intruder = register(make_principal("spoofer", invited=True))
        grant = await harness.connect(intruder)
        result = await harness.call(
            grant.access_token,
            "get_goal",
            {"goal_id": goal_id, "user_id": str(harness.owner.user_id)},
        )
    assert result.is_error is True


# --- Scenario F: cost -----------------------------------------------------------------


async def test_f_read_and_structured_paths_make_no_model_calls() -> None:
    async with McpHarness() as harness:
        goal_id = await create_audience_goal(harness)
        provider = _scripted(harness)
        before = len(provider.calls)
        grant = await harness.connect()
        await _audience_series(harness, grant.access_token, goal_id)
        for tool in (
            "get_forecast",
            "get_forecast_history",
            "get_evidence_summary",
            "get_best_interventions",
        ):
            await harness.call(grant.access_token, tool, {"goal_id": goal_id})
        await harness.call(
            grant.access_token,
            "simulate_intervention",
            {
                "goal_id": goal_id,
                "changes": [
                    {"metric": "primary.mu", "operation": "set", "value": 0.05, "unit": "x"}
                ],
            },
        )
    assert len(provider.calls) == before


async def test_f_natural_language_requires_inference_consent() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        response = await harness.rpc(
            grant.access_token,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "submit_observation",
                    "arguments": {
                        "goal_id": goal_id,
                        "text": "I sent 12 job applications this week.",
                        "idempotency_key": "nl-consent-01",
                        "source_category": "user_message",
                    },
                },
            },
        )
    assert response.status_code == 403


async def test_f_natural_language_is_charged_once_per_key() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        provider = _scripted(harness)
        grant = await harness.connect(scope="goals:read evidence:write inference:use")
        args = {
            "goal_id": goal_id,
            "text": "I sent 12 job applications this week.",
            "idempotency_key": "nl-charge-001",
            "source_category": "user_message",
        }
        before = len([call for call in provider.calls if call.agent_name == "evidence"])
        first = structured(await harness.call(grant.access_token, "submit_observation", args))
        second = structured(await harness.call(grant.access_token, "submit_observation", args))
        after = len([call for call in provider.calls if call.agent_name == "evidence"])
    assert first["status"] in {"committed", "needs_clarification"}, first
    assert first["llm_calls"] == 1
    assert second["status"] == "replayed" and second["llm_calls"] == 0
    assert after - before == 1
    if first["status"] == "committed":
        assert first["evidence"][0]["verification_status"] == "agent_reported"


async def test_f_budget_exhaustion_is_explicit_and_commits_nothing() -> None:
    harness = McpHarness(
        inference=FailingInferenceProvider(ProviderBudgetExceededError("hosted budget exhausted"))
    )
    async with harness:
        goal_id = await create_audience_goal(harness)
        grant = await harness.connect(scope="goals:read evidence:write inference:use")
        result = await harness.call(
            grant.access_token,
            "submit_observation",
            {
                "goal_id": goal_id,
                "text": "I have 1300 subscribers now.",
                "idempotency_key": "budget-00001",
                "source_category": "user_message",
            },
        )
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
    assert result.is_error is True
    assert structured(result)["error"]["code"] == "budget_exhausted"
    assert rows == []


async def test_f_inference_calls_are_rate_limited() -> None:
    harness = McpHarness(
        inference=FailingInferenceProvider(ProviderBudgetExceededError("hosted budget exhausted"))
    )
    async with harness:
        goal_id = await create_audience_goal(harness)
        grant = await harness.connect(scope="goals:read evidence:write inference:use")
        codes = []
        for index in range(6):
            result = await harness.call(
                grant.access_token,
                "submit_observation",
                {
                    "goal_id": goal_id,
                    "text": "I have 1300 subscribers now.",
                    "idempotency_key": f"ratelimit-{index:03d}",
                    "source_category": "user_message",
                },
            )
            codes.append(structured(result)["error"]["code"])
    assert codes[:4] == ["budget_exhausted"] * 4
    assert codes[4:] == ["rate_limited", "rate_limited"]


# --- Scenario H: failure recovery -----------------------------------------------------


async def test_h_failed_publication_is_completed_by_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        original = BaselineRepriceService.publish_if_priceable
        attempts = {"count": 0}

        async def flaky(self: BaselineRepriceService, goal: Any) -> Any:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("simulated reprice outage")
            return await original(self, goal)

        monkeypatch.setattr(BaselineRepriceService, "publish_if_priceable", flaky)
        payload = _evidence(goal_id, "recover-0001")
        first = structured(
            await harness.call(grant.access_token, "submit_structured_evidence", payload)
        )
        assert first["status"] == "committed"
        assert first["publication"]["status"] == "error"
        assert await _history(harness, goal_id) == []
        second = structured(
            await harness.call(grant.access_token, "submit_structured_evidence", payload)
        )
        assert second["status"] == "replayed"
        assert second["publication"]["priced"] is True
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
        assert len(rows) == 1
        assert len(await _history(harness, goal_id)) == 1


async def test_h_failed_commit_can_be_retried_with_same_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        evidence = _deps(harness).evidence
        original = type(evidence).commit
        attempts = {"count": 0}

        async def flaky(self: Any, **kwargs: Any) -> Any:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("simulated database outage")
            return await original(self, **kwargs)

        monkeypatch.setattr(type(evidence), "commit", flaky)
        payload = _evidence(goal_id, "commitfail-01")
        first = await harness.call(grant.access_token, "submit_structured_evidence", payload)
        assert first.is_error is True
        assert structured(first)["error"]["code"] == "internal_error"
        assert structured(first)["error"]["retryable"] is True
        second = structured(
            await harness.call(grant.access_token, "submit_structured_evidence", payload)
        )
        assert second["status"] == "committed"
        assert len(await evidence.list_for_goal(UUID(goal_id))) == 1


async def test_h_concurrent_duplicate_submissions_commit_once() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        payload = _evidence(goal_id, "concurrent-01", observation_kind="increment", value=3)
        results = await asyncio.gather(
            *[
                harness.call(grant.access_token, "submit_structured_evidence", payload)
                for _ in range(5)
            ]
        )
        statuses = sorted(structured(item)["status"] for item in results)
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
    assert statuses.count("committed") == 1
    assert set(statuses) <= {"committed", "replayed", "in_progress"}
    assert len(rows) == 1


async def test_h_concurrent_distinct_writes_to_one_goal_are_serialized() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        results = await asyncio.gather(
            *[
                harness.call(
                    grant.access_token,
                    "submit_structured_evidence",
                    _evidence(
                        goal_id, f"parallel-{index:03d}", observation_kind="increment", value=1
                    ),
                )
                for index in range(5)
            ]
        )
        rows = await _deps(harness).evidence.list_for_goal(UUID(goal_id))
        history = await _history(harness, goal_id)
    assert all(structured(item)["status"] == "committed" for item in results)
    assert len(rows) == 5
    assert history[-1].evidence_watermark in {str(row.evidence_id) for row in rows}
