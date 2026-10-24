import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal
from personal_markets.what_if.domain import (
    CompareCandidate,
    InterventionChangeInput,
    PathComparisonRequest,
    PathDefinition,
    PossibleFuturesRequest,
    ResourceCost,
    ResourceLimitsInput,
    ScenarioDefinition,
    ScenarioDistribution,
    SimulationConfig,
    StructuredIntervention,
    TargetSearchRequest,
    WhatIfBaselineState,
    WhatIfRequest,
    WhatIfResult,
)
from personal_markets.what_if.futures_decision import parse_futures_decision
from personal_markets.what_if.repository import InMemorySimulationRepository
from personal_markets.what_if.service import WhatIfService
from personal_markets.wiring import get_what_if_service
from test_pass4_remaining import (
    LinearWhatIfService,
    action,
    make_assumptions,
    make_base,
    make_goal,
)


def _finance_goal() -> GoalContract:
    return GoalContract.model_validate(
        {
            "goal_id": uuid4(),
            "title": "Reach one million dollars in net worth",
            "goal_type": GoalType.CONTINUOUS_TARGET,
            "success_definition": {"metric": "net_worth", "operator": ">=", "amount": 1_000_000},
            "deadline": datetime.now(UTC) + timedelta(days=365 * 8),
            "state_dimensions": ["liquid_assets", "income", "expenses"],
        }
    )


async def _finance_service(goal: GoalContract) -> WhatIfService:
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, uuid4())
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    evidence_service = EvidenceService(evidence_repo)
    user_id = uuid4()
    for metric, value, unit in (
        ("net_worth", 180_000.0, "CAD"),
        ("monthly_contribution", 2500.0, "CAD/month"),
    ):
        await evidence_repo.insert(
            user_id,
            goal.goal_id,
            EvidenceEventProposal.model_validate(
                {
                    "source_type": "manual",
                    "event_type": "observation",
                    "domain": "finance",
                    "metric": metric,
                    "numeric_value": value,
                    "unit": unit,
                    "observed_at": datetime.now(UTC).isoformat(),
                    "summary": f"{metric}={value}",
                }
            ),
            fingerprint=f"{metric}-{value}",
            agent_run_id=None,
            conflict="none",
        )
    return WhatIfService(GoalService(goal_repo), evidence=evidence_service)


def _prob(result: ScenarioDistribution, needle: str) -> float:
    for item in result.outcomes:
        if needle.lower() in item.label.lower():
            return float(item.probability or 0)
    raise AssertionError(f"missing outcome containing {needle!r}")


@pytest.mark.asyncio
async def test_futures_parsed_changes_condition_finance_distribution() -> None:
    goal = _finance_goal()
    service = await _finance_service(goal)
    labels = [
        ScenarioDefinition(label="Target reached"),
        ScenarioDefinition(label="Meaningful progress"),
        ScenarioDefinition(label="Current trajectory"),
        ScenarioDefinition(label="Downside outcome", downside=True),
    ]
    baseline = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=str(goal.goal_id),
            name="Baseline futures",
            outcomes=labels,
            include_other=True,
        )
    )
    boosted = await service.possible_futures(
        PossibleFuturesRequest(
            goal_id=str(goal.goal_id),
            name="Higher contribution",
            outcomes=labels,
            include_other=True,
            parsed_changes=[
                InterventionChangeInput(
                    metric="monthly_contribution",
                    operation="set",
                    value=12000,
                    unit="CAD/month",
                    provenance="USER_ASSUMPTION",
                )
            ],
        )
    )
    assert baseline.priced is True
    assert boosted.priced is True
    assert _prob(boosted, "Target") > _prob(baseline, "Target")


@pytest.mark.asyncio
async def test_compare_unpriced_path_stays_null() -> None:
    goal = make_goal()
    repo = InMemoryGoalRepository()
    await repo.create(goal, uuid4())

    class MixedPriceService(WhatIfService):
        async def _simulate(self, request: WhatIfRequest, *, persist: bool) -> WhatIfResult:
            del persist
            if request.parsed_changes:
                return WhatIfResult(
                    priced=True,
                    status="PRICED",
                    scenario_probability=0.55,
                    expected_outcome=55,
                    outcome_quantiles={"p10": 0.4, "p50": 0.55, "p90": 0.7},
                    downside_probability=0.2,
                    execution_probability=0.8,
                    assumptions=request.assumptions,
                )
            return WhatIfResult(
                priced=False,
                status="NOT_PRICED",
                scenario_probability=None,
                assumptions=request.assumptions,
            )

    service = MixedPriceService(GoalService(repo), InMemorySimulationRepository())
    result = await service.compare_paths(
        PathComparisonRequest(
            base=make_base(str(goal.goal_id)),
            paths=[
                PathDefinition(id="a", label="Unmapped", intervention=action("a", 0.1, 1)),
                PathDefinition(
                    id="b",
                    label="Mapped",
                    intervention=action("b", 0.1, 1),
                    parsed_changes=[
                        InterventionChangeInput(
                            metric="flow",
                            operation="set",
                            value=8,
                            unit="unit",
                            provenance="USER_ASSUMPTION",
                        )
                    ],
                ),
            ],
        )
    )
    unpriced = next(item for item in result.paths if item.id == "a")
    priced = next(item for item in result.paths if item.id == "b")
    assert unpriced.primary_goal_probability is None
    assert unpriced.median is None
    assert priced.primary_goal_probability == 0.55


@pytest.mark.asyncio
async def test_deeper_compare_prices_two_measured_finance_paths_and_persists() -> None:
    goal = _finance_goal()
    service = await _finance_service(goal)
    state = await service.baseline_state(str(goal.goal_id))
    assert state.priced
    base = WhatIfRequest(
        goal_id=str(goal.goal_id),
        current_value=state.current_value or 0,
        target_value=state.target_value or 1,
        periods=state.periods or 8,
        direction=state.direction,
        assumptions=state.assumptions,
        intervention=None,
        config=SimulationConfig(
            seed=state.config.seed,
            minimum_draws=8000,
            batch_draws=4000,
            maximum_draws=20000,
            include_sensitivity=True,
        ),
    )
    paths = [
        PathDefinition(
            id=f"path-{contribution}",
            label=f"Save {contribution} each month",
            intervention=StructuredIntervention(
                id=f"path-{contribution}",
                title="Monthly contribution",
                action_type="flow_change",
                target_dimension="net_worth",
                amount=1,
                unit="currency/month",
                duration_periods=base.periods,
                effect_per_unit=None,
                cost=ResourceCost(),
            ),
            parsed_changes=[
                InterventionChangeInput(
                    metric="monthly_contribution",
                    operation="set",
                    value=contribution,
                    unit="CAD/month",
                    provenance="USER_ASSUMPTION",
                )
            ],
        )
        for contribution in (3000.0, 6000.0)
    ]
    result = await service.compare_paths(PathComparisonRequest(base=base, paths=paths))
    assert len(result.paths) == 2
    low = result.paths[0].primary_goal_probability
    high = result.paths[1].primary_goal_probability
    assert low is not None and high is not None
    assert high > low
    assert result.run_id is not None


@pytest.mark.asyncio
async def test_reverse_finance_finds_feasible_measured_flow_without_catalog() -> None:
    goal = _finance_goal()
    service = await _finance_service(goal)
    state = await service.baseline_state(str(goal.goal_id))
    assert state.priced
    request = TargetSearchRequest(
        base=WhatIfRequest(
            goal_id=str(goal.goal_id),
            current_value=state.current_value or 0,
            target_value=state.target_value or 1,
            periods=state.periods or 8,
            direction=state.direction,
            assumptions=state.assumptions,
            intervention=None,
            config=state.config,
        ),
        target_probability=0.7,
        candidates=[],
        limits=ResourceLimitsInput(hours_per_week=20, money=20000, energy=20),
    )
    result = await service.target_search(request)
    assert result.feasible, result.message
    assert result.paths
    assert all(path.resulting_probability is not None for path in result.paths)


def test_finance_deeper_compare_and_reverse_http_journey() -> None:
    """Exercise parsed measured levers, pricing and persistence at the API boundary."""
    app = isolated_app()
    goal = _finance_goal()
    owner = app.state.auth_bypass_principal.user_id
    goals = InMemoryGoalRepository()
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    simulations = InMemorySimulationRepository()

    async def prepare() -> None:
        await goals.create(goal, owner)
        for metric, value, unit in (
            ("net_worth", 180_000.0, "CAD"),
            ("monthly_contribution", 2500.0, "CAD/month"),
        ):
            await evidence_repo.insert(
                owner,
                goal.goal_id,
                EvidenceEventProposal.model_validate(
                    {
                        "source_type": "manual",
                        "event_type": "observation",
                        "domain": "finance",
                        "metric": metric,
                        "numeric_value": value,
                        "unit": unit,
                        "observed_at": datetime.now(UTC).isoformat(),
                        "summary": f"{metric}={value}",
                    }
                ),
                fingerprint=f"http-{metric}-{value}",
                agent_run_id=None,
                conflict="none",
            )

    asyncio.run(prepare())
    service = WhatIfService(
        GoalService(goals), simulations, evidence=EvidenceService(evidence_repo), owner_id=owner
    )
    app.dependency_overrides[get_what_if_service] = lambda: service
    with TestClient(app) as client:
        baseline_response = client.get(f"/api/v1/what-if/baseline-state/{goal.goal_id}")
        assert baseline_response.status_code == 200, baseline_response.text
        state = WhatIfBaselineState.model_validate(baseline_response.json())
        assert state.priced
        base = WhatIfRequest(
            goal_id=str(goal.goal_id),
            current_value=state.current_value or 0,
            target_value=state.target_value or 1,
            periods=state.periods or 8,
            direction=state.direction,
            assumptions=state.assumptions,
            intervention=None,
            config=SimulationConfig(
                seed=state.config.seed,
                minimum_draws=8000,
                batch_draws=4000,
                maximum_draws=20000,
                include_sensitivity=True,
            ),
        )
        changed = client.post(
            "/api/v1/what-if/simulate",
            json=base.model_copy(
                update={
                    "parsed_changes": [
                        InterventionChangeInput(
                            metric="monthly_contribution",
                            operation="set",
                            value=6000,
                            unit="CAD/month",
                            provenance="USER_ASSUMPTION",
                        )
                    ]
                }
            ).model_dump(mode="json"),
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["priced"] is True
        assert changed.json()["scenario_probability"] is not None
        assert changed.json()["run_id"]

        outcomes = [
            ScenarioDefinition(label="Target reached"),
            ScenarioDefinition(label="Meaningful progress"),
            ScenarioDefinition(label="Current trajectory"),
            ScenarioDefinition(label="Downside outcome", downside=True),
        ]
        futures = client.post(
            "/api/v1/what-if/possible-futures",
            json=PossibleFuturesRequest(
                goal_id=str(goal.goal_id),
                name="Higher contribution",
                outcomes=outcomes,
                include_other=True,
                parsed_changes=[
                    InterventionChangeInput(
                        metric="monthly_contribution",
                        operation="set",
                        value=12000,
                        unit="CAD/month",
                        provenance="USER_ASSUMPTION",
                    )
                ],
            ).model_dump(mode="json"),
        )
        assert futures.status_code == 200, futures.text
        assert futures.json()["priced"] is True
        assert futures.json()["run_id"]
        paths = [
            PathDefinition(
                id=f"save-{amount}",
                label=f"Save {amount} monthly",
                intervention=StructuredIntervention(
                    id=f"save-{amount}",
                    title="Monthly contribution",
                    action_type="flow_change",
                    target_dimension="net_worth",
                    amount=1,
                    unit="currency/month",
                    duration_periods=base.periods,
                    effect_per_unit=None,
                    cost=ResourceCost(),
                ),
                parsed_changes=[
                    InterventionChangeInput(
                        metric="monthly_contribution",
                        operation="set",
                        value=amount,
                        unit="CAD/month",
                        provenance="USER_ASSUMPTION",
                    )
                ],
            )
            for amount in (3000.0, 6000.0)
        ]
        compared = client.post(
            "/api/v1/what-if/compare-paths",
            json=PathComparisonRequest(base=base, paths=paths).model_dump(mode="json"),
        )
        assert compared.status_code == 200, compared.text
        comparison = compared.json()
        low, high = [path["primary_goal_probability"] for path in comparison["paths"]]
        assert isinstance(low, float) and isinstance(high, float)
        assert high > low
        assert comparison["run_id"]

        reverse = client.post(
            "/api/v1/what-if/target-search",
            json=TargetSearchRequest(
                base=base,
                target_probability=0.7,
                candidates=[],
                limits=ResourceLimitsInput(hours_per_week=20, money=20000, energy=20),
            ).model_dump(mode="json"),
        )
        assert reverse.status_code == 200, reverse.text
        search = reverse.json()
        assert search["feasible"] is True, search
        assert search["paths"]
        assert all(path["resulting_probability"] is not None for path in search["paths"])

    impact_runs = asyncio.run(simulations.list_runs(goal.goal_id, run_kind="impact"))
    future_runs = asyncio.run(simulations.list_runs(goal.goal_id, run_kind="possible_futures"))
    comparison_runs = asyncio.run(simulations.list_runs(goal.goal_id, run_kind="path_comparison"))
    search_runs = asyncio.run(simulations.list_runs(goal.goal_id, run_kind="target_search"))
    assert impact_runs and future_runs and comparison_runs and search_runs
    assert comparison_runs[0].receipt["paths"]
    assert search_runs[0].receipt["paths"]


@pytest.mark.asyncio
async def test_reverse_reports_missing_levers_instead_of_false_infeasibility() -> None:
    goal = make_goal()
    repo = InMemoryGoalRepository()
    await repo.create(goal, uuid4())

    class NoLeverService(WhatIfService):
        async def _simulate(self, request: WhatIfRequest, *, persist: bool) -> WhatIfResult:
            del request, persist
            return WhatIfResult(
                priced=True,
                status="EXPLORATORY",
                baseline_probability=0.2,
                scenario_probability=0.2,
            )

    unsupported = StructuredIntervention(
        id="unknown",
        title="Unknown effect",
        action_type="resource_allocation",
        target_dimension="target",
        amount=1,
        unit="units/period",
        duration_periods=8,
        effect_per_unit=None,
    )
    result = await NoLeverService(GoalService(repo)).target_search(
        TargetSearchRequest(
            base=make_base(str(goal.goal_id)).model_copy(update={"assumptions": []}),
            target_probability=0.7,
            candidates=[unsupported],
            limits=ResourceLimitsInput(hours_per_week=5, money=0, energy=5),
        )
    )
    assert result.feasible is False
    assert result.search_method == "no_supported_levers"
    assert result.paths == []


@pytest.mark.asyncio
async def test_reverse_fills_empty_candidates_from_baseline() -> None:
    goal = make_goal()
    reach = action("reach", 0.3, 2)

    class ReverseFillService(LinearWhatIfService):
        async def baseline_state(self, goal_id: str) -> WhatIfBaselineState:
            return WhatIfBaselineState(
                goal_id=goal_id,
                priced=True,
                status="PRICED",
                model_family="continuous_target_transition",
                model_version="1.0.0",
                assumptions=make_assumptions(),
                compare_candidates=[
                    CompareCandidate(id="reach", title="Reach", intervention=reach),
                ],
            )

    service = ReverseFillService(
        GoalService(InMemoryGoalRepository()), InMemorySimulationRepository()
    )
    result = await service.target_search(
        TargetSearchRequest(
            base=make_base(str(goal.goal_id)),
            target_probability=0.7,
            candidates=[],
            limits=ResourceLimitsInput(hours_per_week=5, money=1000, energy=5),
        )
    )
    assert result.feasible
    assert result.paths
    assert any(path.resulting_probability + 0.01 >= 0.7 for path in result.paths)


@pytest.mark.asyncio
async def test_reverse_discovers_assumption_levers_without_catalog() -> None:
    goal = make_goal()
    service = LinearWhatIfService(
        GoalService(InMemoryGoalRepository()), InMemorySimulationRepository()
    )
    result = await service.target_search(
        TargetSearchRequest(
            base=make_base(str(goal.goal_id), flow=3),
            target_probability=0.7,
            candidates=[],
            limits=ResourceLimitsInput(hours_per_week=5, money=1000, energy=5),
        )
    )
    assert result.feasible
    assert result.paths
    assert any(
        "flow" in path.label.lower() or path.action_ids[:1] == ["lever:flow:0.85"]
        for path in result.paths
    )
    assert all(path.resulting_probability > result.current_probability for path in result.paths)


def test_parse_decision_uses_goal_family_not_regex_taxonomy() -> None:
    parsed = parse_futures_decision("What if I skip half my classes?", goal=_finance_goal())
    assert parsed.unsupported == ()
    assert "Target reached" in parsed.scenario_labels
    assert parsed.decision is not None
    assert parsed.decision.action == "adjust_plan"
