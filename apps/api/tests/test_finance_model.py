from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.finance import (
    aggregate_finance_from_evidence,
    apply_finance_overrides,
    build_finance_numeric_inputs,
    finance_state_to_numeric_inputs,
    is_finance_goal,
    load_finance_reference,
    monte_carlo_success_probability,
    resolve_current_net_worth,
)
from personal_markets.forecasting.inputs_builder import build_numeric_inputs
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import GoalArchitectProposal


def _goal(**overrides: object) -> GoalContract:
    payload: dict[str, object] = {
        "goal_id": uuid4(),
        "title": "Reach one million dollars in net worth",
        "goal_type": GoalType.CONTINUOUS_TARGET,
        "success_definition": {
            "metric": "net_worth",
            "operator": ">=",
            "amount": 1_000_000,
            "currency": "CAD",
        },
        "deadline": datetime.now(UTC) + timedelta(days=365 * 8),
        "state_dimensions": ["liquid_assets", "income", "expenses", "illiquid_equity"],
    }
    payload.update(overrides)
    return GoalContract.model_validate(payload)


def _proposal(goal: GoalContract) -> GoalArchitectProposal:
    return GoalArchitectProposal.model_validate(
        {
            "ready_to_commit": True,
            "title": goal.title,
            "goal_type": goal.goal_type.value,
            "success_metric": "net_worth",
            "success_operator": ">=",
            "success_target": "1000000",
            "deadline": goal.deadline.date().isoformat(),
            "state_dimensions": goal.state_dimensions,
            "model_family_compatibility": "exploratory_finance",
        }
    )


def _evidence(metric: str, value: float) -> NormalizedEvidence:
    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type="observation",
        domain="finance",
        metric=metric,
        numeric_value=value,
        unit="CAD",
        observed_at=datetime.now(UTC),
        source_quality="user_entered",
        provenance=Provenance(
            source_type="csv",
            source_authority="user_file",
            observed_vs_entered="imported",
            parsing_status="ok",
            completeness="complete",
            conflict_status="none",
        ),
        summary=f"{metric}={value}",
        fingerprint="test",
    )


def test_finance_reference_loads() -> None:
    ref = load_finance_reference()
    assert ref.reference_id == "net_worth_assumptions.json"
    assert ref.annual_return_mean > 0


def test_is_finance_goal() -> None:
    goal = _goal()
    assert is_finance_goal(goal, _proposal(goal)) is True


def test_missing_net_worth_and_flow_stays_unpriced() -> None:
    goal = _goal()
    assert build_finance_numeric_inputs(goal, _proposal(goal), []) is None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(goal, _proposal(goal), [], {}, [], None)
    assert pricing.priced is False


def test_liquid_assets_minus_liabilities_prices() -> None:
    goal = _goal()
    evidence = [
        _evidence("liquid_assets", 38000),
        _evidence("debt", 9000),
        _evidence("monthly_income", 7200),
        _evidence("monthly_expenses", 4100),
    ]
    numeric = build_finance_numeric_inputs(goal, _proposal(goal), evidence)
    assert numeric is not None
    net_worth = resolve_current_net_worth(aggregate_finance_from_evidence(evidence))
    assert net_worth == pytest.approx(29000)
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(
        goal, _proposal(goal), ["ev-1"], {}, ["net_worth_assumptions.json"], numeric
    )
    assert pricing.priced is True
    assert pricing.raw_probability is not None
    assert 0 <= pricing.raw_probability < 1
    assert pricing.forecast_status == "EXPLORATORY"
    assert pricing.receipt["model"]["family"] == "continuous_target_transition"


def test_finance_overrides_change_probability() -> None:
    goal = _goal()
    base_state = aggregate_finance_from_evidence(
        [
            _evidence("liquid_assets", 38000),
            _evidence("debt", 9000),
            _evidence("monthly_income", 7200),
            _evidence("monthly_expenses", 4100),
        ]
    )
    boosted = apply_finance_overrides(base_state, {"monthly_contribution": 5000})
    base_numeric = finance_state_to_numeric_inputs(goal, base_state)
    boosted_numeric = finance_state_to_numeric_inputs(goal, boosted)
    assert base_numeric is not None and boosted_numeric is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    base = service.compute(goal, _proposal(goal), [], {}, [], base_numeric)
    boosted_pricing = service.compute(goal, _proposal(goal), [], {}, [], boosted_numeric)
    assert base.raw_probability is not None and boosted_pricing.raw_probability is not None
    assert boosted_pricing.raw_probability > base.raw_probability


def test_monte_carlo_is_deterministic_with_fixed_seed() -> None:
    kwargs = {
        "current_value": 50000,
        "target_value": 100000,
        "periods": 24,
        "direction": "at_least",
        "flow": 1000,
        "growth_mean": 0.005,
        "growth_volatility": 0.03,
        "shock_probability": 0.01,
        "shock_fraction": 0.05,
    }
    first, _ = monte_carlo_success_probability(**kwargs)
    second, _ = monte_carlo_success_probability(**kwargs)
    assert first == pytest.approx(second)


def test_inputs_builder_routes_finance_goals() -> None:
    goal = _goal()
    evidence = [
        _evidence("liquid_assets", 50000),
        _evidence("monthly_income", 6000),
        _evidence("monthly_expenses", 4000),
    ]
    assert build_numeric_inputs(goal, _proposal(goal), evidence) is not None
