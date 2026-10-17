from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.forecasting.families import (
    AssumptionSource,
    DeadlineEventModel,
    HabitPersistenceModel,
)
from personal_markets.forecasting.receipts import IMPACT_RECEIPT_KEYS, missing_receipt_keys
from personal_markets.forecasting.registry import ForecastModelRegistry
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.what_if.domain import (
    Assumption,
    ResourceCost,
    SimulationConfig,
    StructuredIntervention,
    WhatIfRequest,
)
from personal_markets.what_if.optimizer import ActionOptimizer, ResourceLimits
from personal_markets.what_if.service import WhatIfService
from personal_markets.what_if.simulation import PairedSimulation, SimulationEngine


def goal(goal_type: GoalType = GoalType.CONTINUOUS_TARGET) -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Reach a measurable target",
        goal_type=goal_type,
        success_definition={"metric": "savings", "target": 150},
        deadline=datetime.now(UTC) + timedelta(days=365),
        state_dimensions=["current_value"],
    )


def assumptions() -> list[Assumption]:
    values = {
        "flow": (5, -10, 20, "units/period"),
        "growth_mean": (0.01, -0.1, 0.2, "fraction/period"),
        "growth_volatility": (0.03, 0, 0.5, "fraction/period"),
        "shock_probability": (0.02, 0, 0.5, "probability/period"),
        "shock_fraction": (0.1, 0, 0.9, "fraction"),
        "execution_probability": (0.7, 0, 1, "probability"),
    }
    return [
        Assumption(
            name=name,
            value=value,
            minimum=minimum,
            maximum=maximum,
            step=0.01,
            source=AssumptionSource.USER,
            unit=unit,
        )
        for name, (value, minimum, maximum, unit) in values.items()
    ]


def intervention(effect: float | None = 2) -> StructuredIntervention:
    return StructuredIntervention(
        id="save-more",
        title="Save more",
        action_type="flow_change",
        target_dimension="savings",
        amount=2,
        unit="units/period",
        duration_periods=12,
        effect_per_unit=effect,
        effect_source=AssumptionSource.USER if effect is not None else None,
        diminishing_return=0.05,
        cost=ResourceCost(hours_per_week=2),
    )


def test_registry_selects_one_declared_family() -> None:
    selected = ForecastModelRegistry().select(goal(GoalType.THRESHOLD))
    assert selected.descriptor.family == "threshold_trend"
    assert selected.descriptor.required_assumptions


def test_deadline_hazard_uses_survival_product() -> None:
    probability = DeadlineEventModel.probability(np.array([0.0, 0.0]))
    assert probability == pytest.approx(0.75)


def test_long_history_single_miss_deteriorates_less() -> None:
    short_before = HabitPersistenceModel.posterior([True] * 4)[0]
    short_after = HabitPersistenceModel.posterior([True] * 4 + [False])[0]
    long_before = HabitPersistenceModel.posterior([True] * 42)[0]
    long_after = HabitPersistenceModel.posterior([True] * 42 + [False])[0]
    assert long_before - long_after < short_before - short_after


def test_paired_simulation_is_seeded_and_uses_common_worlds() -> None:
    engine = SimulationEngine()
    config = SimulationConfig(seed=7, minimum_draws=1000, batch_draws=1000, maximum_draws=1000)
    def simulate() -> PairedSimulation:
        return engine.continuous_target(
            current_value=100,
            target_value=150,
            periods=12,
            direction="at_least",
            flow=3,
            growth_mean=0.01,
            growth_volatility=0.04,
            shock_probability=0.02,
            shock_fraction=0.1,
            execution_probability=0.8,
            intervention_effect=2,
            config=config,
        )

    first = simulate()
    second = simulate()
    assert np.array_equal(first.scenario_outcome, second.scenario_outcome)
    assert np.all(first.scenario_outcome >= first.baseline_outcome)
    assert first.diagnostics.n_draws == 1000


def _continuous(engine: SimulationEngine, **overrides: float) -> PairedSimulation:
    kwargs: dict = {
        "current_value": 100.0,
        "target_value": 150.0,
        "periods": 12,
        "direction": "at_least",
        "flow": 3.0,
        "growth_mean": 0.01,
        "growth_volatility": 0.04,
        "shock_probability": 0.02,
        "shock_fraction": 0.1,
        "execution_probability": 0.8,
        "intervention_effect": 0.0,
        "config": SimulationConfig(
            seed=11, minimum_draws=8000, batch_draws=8000, maximum_draws=8000
        ),
    }
    kwargs.update(overrides)
    return engine.continuous_target(**kwargs)


def test_scenario_state_defaults_to_baseline_state() -> None:
    """Callers that only pass an intervention effect keep the old paired behaviour."""
    engine = SimulationEngine()
    paired = _continuous(engine, intervention_effect=2.0)
    assert np.all(paired.scenario_outcome >= paired.baseline_outcome)
    # No scenario state was supplied, so unexecuted paths must match baseline exactly.
    unexecuted = ~paired.execution
    assert np.allclose(
        paired.scenario_outcome[unexecuted], paired.baseline_outcome[unexecuted]
    )


def test_scenario_state_applies_only_on_executed_paths() -> None:
    """A state change is an action: it must be gated on follow-through like any other."""
    engine = SimulationEngine()
    paired = _continuous(engine, scenario_flow=9.0)
    unexecuted = ~paired.execution
    assert np.allclose(
        paired.scenario_outcome[unexecuted], paired.baseline_outcome[unexecuted]
    )
    assert np.all(paired.scenario_outcome[paired.execution] > paired.baseline_outcome[paired.execution])


def test_execution_adjusted_probability_is_the_execution_mixture() -> None:
    """realistic == P(execute)*P(goal | executed) + (1-P(execute))*P(goal | baseline)."""
    engine = SimulationEngine()
    execution_probability = 0.6
    paired = _continuous(
        engine, scenario_flow=9.0, execution_probability=execution_probability
    )
    executed = paired.execution
    realistic = float(np.mean(paired.scenario_success))
    conditional = float(np.mean(paired.scenario_success[executed]))
    unexecuted_success = float(np.mean(paired.scenario_success[~executed]))
    observed_rate = float(np.mean(executed))
    expected = observed_rate * conditional + (1 - observed_rate) * unexecuted_success
    assert realistic == pytest.approx(expected, abs=1e-9)
    assert abs(observed_rate - execution_probability) < 0.02
    # The realistic figure must sit strictly between doing nothing and full execution.
    baseline = float(np.mean(paired.baseline_success))
    assert baseline < realistic < conditional


def test_larger_flow_never_lowers_success_probability() -> None:
    """Declared-monotonic assumption: more contribution cannot reduce the odds."""
    engine = SimulationEngine()
    probabilities = [
        float(np.mean(_continuous(engine, scenario_flow=flow).scenario_success))
        for flow in (3.0, 4.0, 5.0, 6.0, 8.0)
    ]
    assert probabilities == sorted(probabilities)


def test_higher_follow_through_never_lowers_a_beneficial_scenario() -> None:
    engine = SimulationEngine()
    probabilities = [
        float(
            np.mean(
                _continuous(
                    engine, scenario_flow=9.0, execution_probability=p
                ).scenario_success
            )
        )
        for p in (0.1, 0.3, 0.5, 0.7, 0.9)
    ]
    assert probabilities == sorted(probabilities)


@pytest.mark.asyncio
async def test_unmapped_action_is_not_priced() -> None:
    repository = InMemoryGoalRepository()
    record = goal()
    await repository.upsert_seed(record)
    service = WhatIfService(GoalService(repository))
    result = await service.simulate(
        WhatIfRequest(
            goal_id=str(record.goal_id),
            current_value=100,
            target_value=150,
            periods=12,
            assumptions=assumptions(),
            intervention=intervention(None),
        )
    )
    assert not result.priced
    assert result.status == "NOT_PRICED"


@pytest.mark.asyncio
async def test_plan_execution_is_reported_separately() -> None:
    repository = InMemoryGoalRepository()
    record = goal()
    await repository.upsert_seed(record)
    result = await WhatIfService(GoalService(repository)).simulate(
        WhatIfRequest(
            goal_id=str(record.goal_id),
            current_value=100,
            target_value=150,
            periods=12,
            assumptions=assumptions(),
            intervention=intervention(),
        )
    )
    assert result.priced
    assert result.execution_probability == 0.7
    assert result.conditional_on_execution_probability is not None
    assert result.diagnostics is not None
    assert result.sensitivity
    assert result.fragility_pp is not None
    assert result.receipt is not None
    assert missing_receipt_keys(result.receipt, IMPACT_RECEIPT_KEYS) == []
    assert result.receipt["llm_used"] is False


def test_bounded_optimizer_respects_constraints_and_exclusivity() -> None:
    a = intervention()
    b = intervention()
    b.id = "other"
    b.exclusivity_group = "choice"
    c = intervention()
    c.id = "exclusive"
    c.exclusivity_group = "choice"
    bundles = ActionOptimizer().enumerate(
        [a, b, c], ResourceLimits(hours_per_week=4, money=0, energy=0)
    )
    assert bundles
    assert all(item.cost.hours_per_week <= 4 for item in bundles)
    assert all(
        not ({action.id for action in item.actions} >= {"other", "exclusive"}) for item in bundles
    )


def test_what_if_api_contract_fails_closed_for_unknown_goal() -> None:
    with TestClient(isolated_app()) as client:
        response = client.post(
            "/api/v1/what-if/simulate",
            json={
                "goal_id": str(uuid4()),
                "current_value": 100,
                "target_value": 150,
                "periods": 12,
                "assumptions": [item.model_dump(mode="json") for item in assumptions()],
            },
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_explorations_lists_persisted_impact_runs() -> None:
    repository = InMemoryGoalRepository()
    record = goal()
    await repository.upsert_seed(record)
    service = WhatIfService(GoalService(repository))
    await service.simulate(
        WhatIfRequest(
            goal_id=str(record.goal_id),
            current_value=100,
            target_value=150,
            periods=12,
            assumptions=assumptions(),
            intervention=intervention(),
        )
    )
    items = await service.explorations(str(record.goal_id))
    assert len(items) == 1
    assert items[0].goal_id == str(record.goal_id)
    assert items[0].run_kind == "impact"
    assert items[0].intervention_title == "Save more"
    assert items[0].baseline_probability is not None
    assert items[0].scenario_probability is not None
    assert items[0].expected_uplift_pp is not None
