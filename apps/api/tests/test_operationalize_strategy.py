# ruff: noqa: E501
from typing import Any

import pytest

from personal_markets.forecasting.families import AssumptionSource
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.ports import InferenceRequest
from personal_markets.what_if.domain import Assumption, WhatIfBaselineState
from personal_markets.what_if.intervention_overrides import apply_parsed_changes_to_assumptions
from personal_markets.what_if.operationalize import operationalize_strategy, plan_summary
from test_strategy_agent import _career_goal, _service

COLD_EMAIL = "what if i cold email fdes at startups i want to work at"


def _assumption(name: str, value: float, unit: str, maximum: float = 50.0) -> Assumption:
    return Assumption(
        name=name,
        value=value,
        minimum=0.0 if not unit.startswith("second") else -30.0,
        maximum=maximum,
        step=1.0,
        source=AssumptionSource.REFERENCE,
        unit=unit,
    )


def _baseline(*assumptions: Assumption, priced: bool = True) -> WhatIfBaselineState:
    return WhatIfBaselineState(
        goal_id="00000000-0000-0000-0000-000000000001",
        priced=priced,
        status="PRICED" if priced else "UNPRICED",
        assumptions=list(assumptions),
        model_family="test",
        model_version="1",
    )


HIRING = _baseline(_assumption("weekly_application_rate", 8, "applications/week"))


def test_cold_email_without_quantity_asks_instead_of_assuming_an_effect() -> None:
    result = operationalize_strategy(HIRING, COLD_EMAIL)
    assert result is not None
    plan, changes = result
    assert changes == []
    assert plan.family == "outreach"
    assert not plan.modeled
    lever = plan.levers[0]
    assert lever.assumption == "weekly_application_rate"
    assert lever.baseline_value == 8
    assert lever.suggested_values == [2.0, 4.0, 8.0]
    assert plan.needs == [lever.question]
    assert "No probability change is assumed" in plan_summary(plan)
    assert "strategy question" not in plan_summary(plan).lower()


def test_stated_quantity_becomes_a_priced_change_on_the_modeled_lever() -> None:
    plan, changes = operationalize_strategy(HIRING, "what if I cold email 10 founders a week")  # type: ignore[misc]
    assert plan.modeled and plan.stated_quantity == 10
    assert [(c.metric, c.operation, c.value) for c in changes] == [
        ("weekly_application_rate", "add", 10)
    ]
    applied = apply_parsed_changes_to_assumptions(HIRING.assumptions, changes)
    assert applied[0].value == 18


def test_daily_quantity_converts_to_weekly_units() -> None:
    _, changes = operationalize_strategy(HIRING, "what if I message 2 recruiters a day")  # type: ignore[misc]
    assert changes[0].value == 14


def test_monthly_savings_maps_to_money_flow_only() -> None:
    finance = _baseline(_assumption("flow", 1800, "currency/month", maximum=10000))
    plan, changes = operationalize_strategy(finance, "what if I start a side hustle and save 500 a month")  # type: ignore[misc]
    assert plan.family == "savings"
    assert changes[0].value == 500
    assert operationalize_strategy(finance, "what if I read more") is None


def test_pace_flow_is_never_given_a_positive_more() -> None:
    running = _baseline(_assumption("flow", -5, "seconds/week", maximum=0))
    assert operationalize_strategy(running, "what if I train more") is None


def test_composed_rate_lever_for_count_goals() -> None:
    reading = _baseline(_assumption("books.rate", 0.5, "count/week", maximum=10))
    plan, changes = operationalize_strategy(reading, "what if I read every night")  # type: ignore[misc]
    assert plan.levers[0].assumption == "books.rate"
    assert changes == []


def test_unpriced_baseline_or_unmapped_action_returns_none() -> None:
    assert operationalize_strategy(_baseline(priced=False), COLD_EMAIL) is None
    assert operationalize_strategy(HIRING, "what if I dye my hair") is None


@pytest.mark.asyncio
async def test_cold_email_prompt_returns_a_plan_without_any_inference_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    goal = _career_goal()
    monkeypatch.setattr(
        "personal_markets.agents.intervention_service.build_baseline_state",
        lambda *_: HIRING.model_copy(update={"goal_id": str(goal.goal_id)}),
    )

    def script(request: InferenceRequest) -> dict[str, Any]:
        calls.append(request.agent_name)
        raise AssertionError("no inference expected")

    service = await _service(goal, inference=ScriptedInferenceProvider(script))
    parsed = await service.parse(str(goal.goal_id), COLD_EMAIL)
    assert calls == []
    assert parsed.strategy_plan is not None
    assert parsed.pricing_status == "NOT_PRICED"
    assert parsed.changes == []
    assert "This is a strategy question" not in parsed.consumer_summary

    quantified = await service.parse(str(goal.goal_id), "what if I cold email 10 FDEs a week")
    assert calls == []
    assert quantified.pricing_status == "PRICED"
    assert quantified.request_kind == "quantitative_scenario"
    assert quantified.changes[0].metric == "weekly_application_rate"
