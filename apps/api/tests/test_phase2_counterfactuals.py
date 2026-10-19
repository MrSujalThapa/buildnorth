from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import numpy as np
import pytest

from personal_markets.evidence.mapping import proposal_to_normalized
from personal_markets.evidence.metrics import (
    anchor_reported_today_increment,
    canonicalize_metric,
)
from personal_markets.forecasting.hiring import aggregate_funnel_from_evidence
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import EvidenceEventProposal
from personal_markets.what_if.baseline_state import resolve_simulation_context
from personal_markets.what_if.domain import InterventionChangeInput, SimulationConfig
from personal_markets.what_if.simulation import SimulationEngine


def test_relative_today_increment_keeps_order_after_same_day_snapshot() -> None:
    received = datetime(2026, 10, 18, 13, 49, tzinfo=UTC)
    snapshot = EvidenceEventProposal(
        event_type="observation",
        domain="career",
        metric="applications_submitted",
        numeric_value=18,
        unit="count",
        observed_at="2026-10-18T13:45:00+00:00",
        source_type="manual",
        summary="I currently have 18 applications submitted",
        observation_kind="snapshot",
    )
    increment = EvidenceEventProposal(
        event_type="application_submitted",
        domain="career",
        metric="applications_submitted",
        numeric_value=5,
        unit="count",
        observed_at="2026-10-18",
        source_type="manual",
        summary="I sent five more applications today",
        observation_kind="increment",
    )
    anchored = anchor_reported_today_increment(increment, received)
    assert anchored.observed_at == received.isoformat()
    evidence = [
        proposal_to_normalized(snapshot, "snapshot"),
        proposal_to_normalized(anchored, "increment"),
    ]
    assert aggregate_funnel_from_evidence(evidence, now=received).applications == 23
    historical = increment.model_copy(update={"observed_at": "2026-10-10"})
    assert anchor_reported_today_increment(historical, received) is historical
    precise = increment.model_copy(update={"observed_at": "2026-10-18T08:00:00+00:00"})
    assert anchor_reported_today_increment(precise, received) is precise


@pytest.mark.parametrize("metric", ["weekly_application_rate", "applications_per_week"])
@pytest.mark.parametrize(
    "operation,value,expected", [("add", 5, 7), ("subtract", 1, 1), ("set", 8, 8)]
)
def test_hiring_intervention_reprices_once(
    metric: str, operation: str, value: float, expected: float
) -> None:
    now = datetime.now(UTC)
    goal = GoalContract(
        goal_id=uuid4(),
        title="Receive an internship offer",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": "offer_received"},
        deadline=now + timedelta(days=180),
        state_dimensions=["applications_submitted"],
    )
    event = EvidenceEventProposal(
        source_type="manual",
        event_type="observation",
        domain="career",
        metric="applications_submitted",
        numeric_value=18,
        unit="count",
        observed_at=now.isoformat(),
        summary="18 applications",
        observation_kind="snapshot",
    )
    evidence = [proposal_to_normalized(event, "test")]
    baseline = resolve_simulation_context(goal, evidence)
    assert baseline.priced
    scenario = resolve_simulation_context(
        goal,
        evidence,
        parsed_changes=[
            InterventionChangeInput(
                metric=metric,
                operation=operation,
                value=value,
                unit="applications/week",
                provenance="USER_ASSUMPTION",
            )
        ],
    )
    assert (
        next(a.value for a in scenario.assumptions if a.name == "weekly_application_rate")
        == expected
    )
    slider = resolve_simulation_context(
        goal, evidence, assumption_overrides={"weekly_application_rate": expected}
    )
    assert scenario.baseline_probability == pytest.approx(slider.baseline_probability)
    assert scenario.baseline_probability is not None
    assert baseline.baseline_probability is not None
    assert (scenario.baseline_probability > baseline.baseline_probability) == (expected > 2)
    assert resolve_simulation_context(goal, evidence).baseline_probability == pytest.approx(
        baseline.baseline_probability, abs=1e-7
    )


@pytest.mark.parametrize("execution", [0, 0.4, 1])
@pytest.mark.parametrize("baseline,scenario", [(0.2, 0.7), (0.7, 0.1), (0.3, 0.3)])
def test_deadline_common_worlds_and_execution_mixture(
    execution: float, baseline: float, scenario: float
) -> None:
    config = SimulationConfig(minimum_draws=10000, maximum_draws=20000)
    result = SimulationEngine().deadline_event(
        baseline_probability=baseline,
        scenario_probability=scenario,
        periods=8,
        execution_probability=execution,
        config=config,
    )
    expected = baseline + execution * (scenario - baseline)
    assert np.mean(result.scenario_success) == pytest.approx(expected, abs=0.02)
    assert np.array_equal(
        result.baseline_success[~result.execution], result.scenario_success[~result.execution]
    )
    assert np.allclose(result.scenario_trajectory[:, -1], result.scenario_outcome)
    assert np.all(result.scenario_trajectory[~result.execution] == baseline)
    repeated = SimulationEngine().deadline_event(
        baseline_probability=baseline,
        scenario_probability=scenario,
        periods=8,
        execution_probability=execution,
        config=config,
    )
    assert np.array_equal(result.scenario_success, repeated.scenario_success)
    assert result.diagnostics.converged
    if baseline == scenario:
        assert np.array_equal(result.baseline_success, result.scenario_success)


def test_deadline_reports_draw_cap_instead_of_false_convergence() -> None:
    result = SimulationEngine().deadline_event(
        baseline_probability=0.5,
        scenario_probability=0.6,
        periods=3,
        execution_probability=0.8,
        config=SimulationConfig(
            minimum_draws=100, maximum_draws=100, probability_se_tolerance=0.001
        ),
    )
    assert not result.diagnostics.converged
    assert result.diagnostics.achieved_mc_error > 0.001


def test_live_evidence_alias_and_date_are_canonical_and_aware() -> None:
    rows = []
    observations: list[tuple[int, Literal["snapshot", "increment"], str]] = [
        (18, "snapshot", "2026-10-17"),
        (5, "increment", "2026-10-18"),
    ]
    for value, kind, date in observations:
        event = EvidenceEventProposal(
            source_type="manual",
            event_type="observation",
            domain="career",
            metric=canonicalize_metric("applications_submitted_count"),
            numeric_value=value,
            unit="count",
            observed_at=date,
            summary="reported applications",
            observation_kind=kind,
        )
        row = proposal_to_normalized(event, str(value))
        assert row.observed_at is not None
        assert row.observed_at.tzinfo is not None
        rows.append(row)
    assert rows[0].metric == "applications_submitted"
    assert aggregate_funnel_from_evidence(rows).applications == 23


class _StaticEvidence:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def list_for_goal(self, goal_id: object) -> list:
        return self._rows


@pytest.mark.asyncio
async def test_unmapped_hiring_intervention_is_not_priced_or_persisted() -> None:
    from personal_markets.goals.adapters import InMemoryGoalRepository
    from personal_markets.goals.service import GoalService
    from personal_markets.what_if.domain import WhatIfRequest
    from personal_markets.what_if.repository import InMemorySimulationRepository
    from personal_markets.what_if.service import WhatIfService

    now = datetime.now(UTC)
    goal = GoalContract(
        goal_id=uuid4(),
        title="Receive an internship offer",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": "offer_received"},
        deadline=now + timedelta(days=180),
        state_dimensions=["applications_submitted"],
    )
    goals = InMemoryGoalRepository()
    await goals.upsert_seed(goal)
    event = EvidenceEventProposal(
        source_type="manual", event_type="observation", domain="career",
        metric="applications_submitted", numeric_value=18, unit="count",
        observed_at=now.isoformat(), summary="18 applications", observation_kind="snapshot",
    )
    simulations = InMemorySimulationRepository()
    service = WhatIfService(
        GoalService(goals), simulations,
        evidence=_StaticEvidence([proposal_to_normalized(event, "test")]),  # type: ignore[arg-type]
    )
    base = await service.baseline_state(str(goal.goal_id))
    assert base.priced and base.current_value is not None and base.target_value is not None
    request = WhatIfRequest(
        goal_id=str(goal.goal_id),
        current_value=base.current_value,
        target_value=base.target_value,
        periods=base.periods or 1,
        assumptions=base.assumptions,
        config=base.config,
    )
    unmapped = await service.simulate(request)
    assert not unmapped.priced
    assert unmapped.status == "NOT_PRICED"
    assert unmapped.receipt.get("causal_status") == "unmapped_intervention"
    assert unmapped.persisted is False
    assert await service.explorations(str(goal.goal_id)) == []

    mapped = await service.simulate(request.model_copy(update={"parsed_changes": [
        InterventionChangeInput(metric="weekly_application_rate", operation="add", value=5,
                                unit="applications/week", provenance="USER_ASSUMPTION"),
    ]}))
    assert mapped.priced and mapped.expected_uplift_pp is not None
    assert mapped.expected_uplift_pp > 0
