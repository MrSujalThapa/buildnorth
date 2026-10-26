# ruff: noqa: E501
from typing import Any

import pytest

from personal_markets.forecasting.families import AssumptionSource
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.ports import InferenceRequest
from personal_markets.what_if.domain import Assumption, ResourceBudget, WhatIfBaselineState
from personal_markets.what_if.intervention_overrides import apply_parsed_changes_to_assumptions
from personal_markets.what_if.operationalize import (
    OPTION_DIRECT,
    OPTION_PROXY,
    OPTION_REPLY_RATE,
    operationalize_strategy,
    plan_summary,
    resolve_option,
)
from test_strategy_agent import _career_goal, _service

COLD_EMAIL = "what if i cold email fdes at startups i want to work at"


def _assumption(name: str, value: float, unit: str, maximum: float = 50.0, step: float = 1.0) -> Assumption:
    return Assumption(
        name=name,
        value=value,
        minimum=0.0 if not unit.startswith("second") else -30.0,
        maximum=maximum,
        step=step,
        source=AssumptionSource.REFERENCE,
        unit=unit,
    )


def _baseline(*assumptions: Assumption, priced: bool = True, hours: float = 0.0) -> WhatIfBaselineState:
    return WhatIfBaselineState(
        goal_id="00000000-0000-0000-0000-000000000001",
        priced=priced,
        status="PRICED" if priced else "UNPRICED",
        assumptions=list(assumptions),
        model_family="test",
        model_version="1",
        periods=20,
        resource_budget=ResourceBudget(hours_per_week=hours),
    )


HIRING = _baseline(
    _assumption("weekly_application_rate", 8, "applications/week"),
    _assumption("application_to_response", 0.1, "probability", maximum=0.99, step=0.02),
    hours=6,
)


def test_counted_activity_outside_the_model_stays_unpriced_on_any_goal() -> None:
    prompts = (
        "What if I have 10 coffee chats with FDEs at startups I'm applying to?",
        "What if I do 4 customer discovery calls a week?",
        "What if I log 3 mobility sessions?",
    )
    for prompt in prompts:
        plan, changes = operationalize_strategy(HIRING, prompt)  # type: ignore[misc]
        assert changes == [] and plan.unpriced and not plan.modeled
        assert plan.family == "unmapped_action" and plan.options == []
        assert plan.stated_quantity and plan.stated_quantity > 0
        assert {item.assumption for item in plan.levers} == {
            "weekly_application_rate",
            "application_to_response",
        }
        assert "no probability change is assumed" in plan.interpretation
    finance = _baseline(_assumption("flow", 1800, "currency/month", maximum=10000))
    plan, changes = operationalize_strategy(finance, "what if I run 12 customer interviews")  # type: ignore[misc]
    assert changes == [] and plan.family == "unmapped_action"
    assert plan.levers[0].assumption == "flow"
    assert operationalize_strategy(HIRING, "what if I dye my hair") is None


def test_cold_email_is_not_silently_treated_as_an_application() -> None:
    plan, changes = operationalize_strategy(HIRING, "what if I cold email 10 founders a week")  # type: ignore[misc]
    assert changes == [] and not plan.modeled
    assert plan.selected_option is None
    assert [item.id for item in plan.options] == [OPTION_REPLY_RATE, OPTION_PROXY]
    assert next(item for item in plan.options if item.id == OPTION_PROXY).proxy
    assert "Offers" in plan.affected_outcomes and "Replies received" in plan.metrics_to_track
    assert any("Choose how to model" in need for need in plan.needs)
    assert plan.options[0].inputs[0].value == 10


def test_cold_email_without_quantity_asks_for_it() -> None:
    plan, changes = operationalize_strategy(HIRING, COLD_EMAIL)  # type: ignore[misc]
    assert changes == []
    lever = plan.levers[0]
    assert lever.assumption == "weekly_application_rate"
    assert lever.suggested_values == [2.0, 4.0, 8.0]
    assert lever.question in plan.needs
    assert "No probability change is assumed" in plan_summary(plan)


def test_explicitly_accepted_proxy_prices_emails_as_applications() -> None:
    plan, changes = operationalize_strategy(HIRING, "cold email 10 founders a week and count them as applications")  # type: ignore[misc]
    assert plan.selected_option == OPTION_PROXY and plan.modeled
    assert [(c.metric, c.operation, c.value) for c in changes] == [("weekly_application_rate", "add", 10)]
    assert apply_parsed_changes_to_assumptions(HIRING.assumptions, changes)[0].value == 18


def test_stated_reply_rate_blends_the_response_stage() -> None:
    plan, changes = operationalize_strategy(HIRING, "cold email 10 founders a week with a 20% reply rate")  # type: ignore[misc]
    assert plan.selected_option == OPTION_REPLY_RATE
    by_metric = {c.metric: c for c in changes}
    assert by_metric["weekly_application_rate"].value == 10
    assert by_metric["application_to_response"].operation == "set"
    assert by_metric["application_to_response"].value == pytest.approx((8 * 0.1 + 10 * 0.2) / 18, abs=1e-4)
    assert all(c.provenance == "USER_ASSUMPTION" for c in changes)


def test_daily_quantity_converts_to_weekly_units() -> None:
    _, changes = operationalize_strategy(HIRING, "what if I message 2 recruiters a day as applications")  # type: ignore[misc]
    assert changes[0].value == 14


def test_out_of_range_and_over_budget_plans_are_conflicts_not_runs() -> None:
    too_many = resolve_option(HIRING, "outreach", OPTION_PROXY, {"amount": 60})
    assert too_many.changes == [] and "supported range" in too_many.conflicts[0]
    over_budget = resolve_option(HIRING, "outreach", OPTION_PROXY, {"amount": 5, "hours_per_week": 9})
    assert over_budget.changes == [] and "time budget" in over_budget.conflicts[0]
    missing_rate = resolve_option(HIRING, "outreach", OPTION_REPLY_RATE, {"amount": 5})
    assert missing_rate.changes == [] and "reply" in missing_rate.conflicts[0]
    ok = resolve_option(HIRING, "outreach", OPTION_REPLY_RATE, {"amount": 5, "reply_rate_pct": 15, "hours_per_week": 3})
    assert len(ok.changes) == 2 and not ok.conflicts and not ok.proxy


def test_monthly_savings_maps_to_money_flow_only() -> None:
    finance = _baseline(_assumption("flow", 1800, "currency/month", maximum=10000))
    plan, changes = operationalize_strategy(finance, "what if I start a side hustle and save 500 a month")  # type: ignore[misc]
    assert plan.family == "savings" and plan.selected_option == OPTION_DIRECT
    assert changes[0].value == 500
    assert operationalize_strategy(finance, "what if I read more") is None


def test_decreases_are_priced_as_future_assumptions() -> None:
    finance = _baseline(_assumption("flow", 1800, "currency/month", maximum=10000))
    plan, changes = operationalize_strategy(finance, "what if I save 500 less a month for 3 months")  # type: ignore[misc]
    assert plan.levers[0].operation == "subtract"
    assert [(c.operation, c.value) for c in changes] == [("subtract", 500)]
    assert any(point.heading == "Limitation" for point in plan.analysis)
    assert operationalize_strategy(finance, "what if I spend less and save 300 a month")[1][0].operation == "add"  # type: ignore[index]
    floor = resolve_option(finance, "savings", OPTION_DIRECT, {"amount": 2500}, "save less")
    assert floor.changes == [] and "supported range" in floor.conflicts[0]


def test_strategy_without_a_lever_is_described_not_priced() -> None:
    finance = _baseline(_assumption("flow", 1800, "currency/month", maximum=10000))
    plan, changes = operationalize_strategy(finance, COLD_EMAIL)  # type: ignore[misc]
    assert changes == [] and plan.unpriced and plan.levers == [] and plan.options == []
    assert plan.metrics_to_track
    assert "will not put a number on it" in plan.interpretation


def test_pace_flow_is_never_given_a_positive_more() -> None:
    running = _baseline(_assumption("flow", -5, "seconds/week", maximum=0))
    assert operationalize_strategy(running, "what if I train more") is None


def test_composed_rate_lever_uses_the_goal_metric() -> None:
    reading = _baseline(_assumption("primary.rate", 0.25, "books_read_count/week", maximum=10, step=0.01))
    plan, changes = operationalize_strategy(reading, "what if I read 1 more book a week")  # type: ignore[misc]
    lever = plan.levers[0]
    assert lever.assumption == "primary.rate"
    assert lever.label == "books read per week"
    assert [(c.metric, c.value) for c in changes] == [("primary.rate", 1)]


def test_unpriced_baseline_or_unmapped_action_returns_none() -> None:
    assert operationalize_strategy(_baseline(priced=False), COLD_EMAIL) is None
    assert operationalize_strategy(HIRING, "what if I dye my hair") is None


@pytest.mark.asyncio
async def test_cold_email_prompts_return_a_plan_without_any_inference_call(
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
    for prompt in (COLD_EMAIL, "What if I start cold emailing founders?", "what if I cold email 10 FDEs a week"):
        parsed = await service.parse(str(goal.goal_id), prompt)
        assert parsed.strategy_plan is not None
        assert parsed.pricing_status == "NOT_PRICED" and parsed.changes == []
    assert calls == []

    quantified = await service.parse(str(goal.goal_id), "what if I cold email 10 FDEs a week with a 15% reply rate")
    assert calls == []
    assert quantified.pricing_status == "PRICED"
    assert {c.metric for c in quantified.changes} == {"weekly_application_rate", "application_to_response"}
