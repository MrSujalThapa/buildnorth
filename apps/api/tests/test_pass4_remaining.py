from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.forecasting.families import AssumptionSource
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.what_if.domain import (
    Assumption,
    ContinuousSearchVariable,
    PathComparisonRequest,
    PathDefinition,
    PossibleFuturesRequest,
    ResourceCost,
    ResourceLimitsInput,
    ScenarioDefinition,
    StructuredIntervention,
    TargetSearchRequest,
    WhatIfRequest,
    WhatIfResult,
)
from personal_markets.what_if.optimizer import ActionOptimizer, ResourceLimits
from personal_markets.what_if.repository import InMemorySimulationRepository
from personal_markets.what_if.service import WhatIfService


def make_goal() -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Reach a deterministic target",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "value", "target": 100},
        deadline=datetime.now(UTC) + timedelta(days=365),
        state_dimensions=["value"],
    )


def make_assumptions(flow: float = 3) -> list[Assumption]:
    records = [
        ("flow", flow, 0, 10, 0.1),
        ("growth_mean", 0.01, -0.1, 0.2, 0.01),
        ("growth_volatility", 0.02, 0, 0.5, 0.01),
        ("shock_probability", 0.01, 0, 0.5, 0.01),
        ("shock_fraction", 0.1, 0, 0.9, 0.01),
        ("execution_probability", 1, 0, 1, 0.05),
    ]
    return [
        Assumption(
            name=name,
            value=value,
            minimum=minimum,
            maximum=maximum,
            step=step,
            source=AssumptionSource.USER,
            unit="unit",
        )
        for name, value, minimum, maximum, step in records
    ]


def make_base(goal_id: str, flow: float = 3) -> WhatIfRequest:
    return WhatIfRequest(
        goal_id=goal_id,
        current_value=40,
        target_value=100,
        periods=12,
        assumptions=make_assumptions(flow),
    )


def action(
    action_id: str,
    effect: float,
    hours: float,
    *,
    money: float = 0,
    group: str | None = None,
    diminishing: float = 0,
) -> StructuredIntervention:
    return StructuredIntervention(
        id=action_id,
        title=action_id.title(),
        action_type="flow_change",
        target_dimension="value",
        amount=1,
        unit="unit/period",
        duration_periods=12,
        effect_per_unit=effect,
        effect_source=AssumptionSource.USER,
        diminishing_return=diminishing,
        cost=ResourceCost(hours_per_week=hours, money=money),
        exclusivity_group=group,
    )


class LinearWhatIfService(WhatIfService):
    async def _simulate(self, request: WhatIfRequest, *, persist: bool) -> WhatIfResult:
        del persist
        flow = next(item.value for item in request.assumptions if item.name == "flow")
        effect = request.intervention.effect_per_unit if request.intervention else 0
        probability = min(1.0, 0.25 + flow * 0.05 + float(effect or 0))
        return WhatIfResult(
            priced=True,
            status="EXPLORATORY",
            baseline_probability=0.25 + flow * 0.05,
            scenario_probability=probability,
            expected_outcome=probability * 100,
            downside_probability=0,
            outcome_quantiles={"p10": 80, "p50": 100, "p90": 120},
            execution_probability=1,
            assumptions=request.assumptions,
        )


@pytest.mark.asyncio
async def test_simulation_retry_is_idempotent_and_never_creates_market_history() -> None:
    repo = InMemoryGoalRepository()
    goal = make_goal()
    await repo.upsert_seed(goal)
    artifacts = InMemorySimulationRepository()
    service = WhatIfService(GoalService(repo), artifacts)
    request = make_base(str(goal.goal_id))
    first = await service.simulate(request)
    second = await service.simulate(request)
    history = await service.history(str(goal.goal_id))
    assert first.run_id == second.run_id
    assert first.persisted and not second.persisted
    assert history == []
    assert not first.history_snapshot_created
    assert not second.history_snapshot_created


@pytest.mark.asyncio
async def test_simulation_repository_rejects_baseline_history_writes() -> None:
    artifacts = InMemorySimulationRepository()
    with pytest.raises(ValueError, match="cannot write market_forecast_history"):
        await artifacts.append(
            goal_id=uuid4(),
            run_kind="impact",
            request_hash="history-forbidden",
            state_hash="state",
            assumption_hash="assumptions",
            model_family="continuous_target_transition",
            model_version="1.0.0",
            status="EXPLORATORY",
            receipt={"forecast_status": "EXPLORATORY"},
            probability=0.42,
            evidence_watermark="forbidden",
            material_hash="forbidden-material",
        )


@pytest.mark.asyncio
async def test_possible_futures_fail_closed_then_validate_distribution() -> None:
    goal_id = str(uuid4())
    service = LinearWhatIfService(
        GoalService(InMemoryGoalRepository()), InMemorySimulationRepository()
    )
    unpriced = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=goal_id,
            name="Startup outcomes",
            outcomes=[ScenarioDefinition(label="Raise"), ScenarioDefinition(label="Shutdown")],
        )
    )
    assert not unpriced.priced
    assert all(item.probability is None for item in unpriced.outcomes)
    priced = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=goal_id,
            name="Startup outcomes",
            outcomes=[
                ScenarioDefinition(label="Raise", weight=0.2, weight_source=AssumptionSource.USER),
                ScenarioDefinition(
                    label="Shutdown",
                    weight=0.5,
                    weight_source=AssumptionSource.REFERENCE,
                    downside=True,
                ),
            ],
        )
    )
    assert sum(
        item.probability or 0 for item in priced.outcomes
    ) + priced.other_probability == pytest.approx(1)


@pytest.mark.asyncio
async def test_identical_paths_match_and_dominant_path_wins() -> None:
    goal = make_goal()
    repo = InMemoryGoalRepository()
    await repo.create(goal, uuid4())
    service = LinearWhatIfService(GoalService(repo), InMemorySimulationRepository())
    same = action("same", 0.1, 2)
    result = await service.compare_paths(
        PathComparisonRequest(
            base=make_base(str(goal.goal_id)),
            paths=[
                PathDefinition(id="a", label="A", intervention=same),
                PathDefinition(id="b", label="B", intervention=same.model_copy()),
                PathDefinition(id="c", label="C", intervention=action("better", 0.2, 2)),
            ],
        )
    )
    assert result.paths[0].primary_goal_probability == result.paths[1].primary_goal_probability
    assert result.paths[2].primary_goal_probability > result.paths[0].primary_goal_probability


@pytest.mark.asyncio
async def test_reverse_search_known_answers_and_resimulation() -> None:
    goal = make_goal()
    service = LinearWhatIfService(
        GoalService(InMemoryGoalRepository()), InMemorySimulationRepository()
    )
    base = make_base(str(goal.goal_id))
    limits = ResourceLimitsInput(hours_per_week=5, money=1000, energy=5)
    one = await service.target_search(
        TargetSearchRequest(
            base=base,
            target_probability=0.7,
            candidates=[action("reach", 0.3, 2), action("expensive", 0.4, 5)],
            limits=limits,
        )
    )
    assert one.feasible and one.paths[0].action_ids == ["reach"]
    assert one.paths[0].resulting_probability >= 0.69
    two = await service.target_search(
        TargetSearchRequest(
            base=base,
            target_probability=0.7,
            candidates=[action("a", 0.15, 2), action("b", 0.15, 2)],
            limits=limits,
        )
    )
    assert two.paths[0].action_ids == ["a", "b"]
    impossible = await service.target_search(
        TargetSearchRequest(
            base=base,
            target_probability=0.95,
            candidates=[action("small", 0.05, 1)],
            limits=limits,
        )
    )
    assert not impossible.feasible
    continuous = await service.target_search(
        TargetSearchRequest(
            base=make_base(str(goal.goal_id), flow=0),
            target_probability=0.7,
            candidates=[],
            limits=limits,
            continuous_variable=ContinuousSearchVariable(assumption="flow"),
        )
    )
    assert continuous.feasible
    assert continuous.paths[0].resulting_probability >= 0.69


def test_pareto_frontier_ties_zero_and_constraints() -> None:
    dominated = ActionOptimizer.pareto(
        [("a", 2, 3), ("b", 3, 2), ("c", 4, 6), ("tie", 2, 3), ("zero", 0, 0)]
    )
    assert dominated["b"]
    assert not dominated["a"] and not dominated["tie"] and not dominated["c"]
    bundles = ActionOptimizer().enumerate(
        [action("a", 1, 7), action("b", 1, 6)],
        ResourceLimits(hours_per_week=10, money=0, energy=0),
    )
    assert all(len(item.actions) == 1 for item in bundles)


def test_diminishing_returns_require_provenance_and_reduce_marginal_effect() -> None:
    optimizer = ActionOptimizer()
    linear = action("linear", 2, 1)
    curved = action("curved", 2, 1, diminishing=0.5)
    linear_effect = optimizer.enumerate(
        [linear], ResourceLimits(hours_per_week=2, money=0, energy=0)
    )[0].expected_effect
    curved_effect = optimizer.enumerate(
        [curved], ResourceLimits(hours_per_week=2, money=0, energy=0)
    )[0].expected_effect
    assert curved_effect < linear_effect
