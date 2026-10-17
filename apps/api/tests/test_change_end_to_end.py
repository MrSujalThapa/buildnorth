from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.inputs_builder import build_numeric_inputs
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal
from personal_markets.what_if.baseline_state import build_baseline_state, proposal_from_goal
from personal_markets.what_if.domain import InterventionChangeInput, WhatIfRequest
from personal_markets.what_if.intervention_parser import parse_intervention_text
from personal_markets.what_if.service import WhatIfService


def _evidence(domain: str, metric: str, value: float, *, unit: str = "count") -> NormalizedEvidence:
    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type="observation",
        domain=domain,
        metric=metric,
        numeric_value=value,
        unit=unit,
        observed_at=datetime.now(UTC),
        source_quality="user_entered",
        provenance=Provenance(
            source_type="manual",
            source_authority="self_report",
            observed_vs_entered="user_entered",
            parsing_status="ok",
            completeness="complete",
            conflict_status="none",
        ),
        summary=f"{metric}={value}",
        fingerprint=f"{metric}-{value}",
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
            "resource_constraints": {"hours_per_week": 12, "budget_amount": 2500, "budget_currency": "CAD"},
        }
    )


def _running_goal() -> GoalContract:
    return GoalContract.model_validate(
        {
            "goal_id": uuid4(),
            "title": "Run a 10K in under 50 minutes",
            "goal_type": GoalType.THRESHOLD,
            "success_definition": {"metric": "10k_time_seconds", "operator": "<=", "value": 3000},
            "deadline": datetime.now(UTC) + timedelta(days=365),
            "state_dimensions": ["recent_race_time", "weekly_distance"],
            "resource_constraints": {"hours_per_week": 6},
        }
    )


def _hiring_goal() -> GoalContract:
    return GoalContract.model_validate(
        {
            "goal_id": uuid4(),
            "title": "Receive a Big Tech SWE offer",
            "goal_type": GoalType.DEADLINE_EVENT,
            "success_definition": {"metric": "offer_received", "target": "swe_offer"},
            "deadline": datetime.now(UTC) + timedelta(days=180),
            "state_dimensions": ["application_pipeline", "interview_outcomes"],
            "resource_constraints": {"hours_per_week": 20},
        }
    )


def test_finance_baseline_state_from_evidence() -> None:
    goal = _finance_goal()
    evidence = [
        _evidence("finance", "net_worth", 120_000, unit="CAD"),
        _evidence("finance", "monthly_contribution", 2500, unit="CAD/month"),
    ]
    state = build_baseline_state(goal, evidence)
    assert state.priced is True
    assert state.current_value == 120_000
    assert state.target_value == 1_000_000
    flow = next(item for item in state.assumptions if item.name == "flow")
    assert flow.value == 2500


def test_finance_intervention_updates_flow() -> None:
    goal = _finance_goal()
    evidence = [
        _evidence("finance", "net_worth", 150_000, unit="CAD"),
        _evidence("finance", "monthly_contribution", 1800, unit="CAD/month"),
    ]
    parsed = parse_intervention_text("Invest $1,500 per month")
    with_override = build_baseline_state(
        goal,
        evidence,
        parsed_changes=[
            InterventionChangeInput(
                metric=item.metric,
                operation=item.operation,
                value=item.value,
                unit=item.unit,
                provenance=item.provenance,
            )
            for item in parsed.changes
        ],
    )
    flow_after = next(item for item in with_override.assumptions if item.name == "flow").value
    assert flow_after == 1500


def test_running_baseline_state_from_evidence() -> None:
    goal = _running_goal()
    evidence = [
        _evidence("running", "10k_time_seconds", 3300, unit="seconds"),
        _evidence("running", "weekly_distance_km", 35, unit="km/week"),
    ]
    state = build_baseline_state(goal, evidence)
    assert state.priced is True
    assert state.direction == "at_most"


def test_career_intervention_maps_application_rate() -> None:
    goal = _hiring_goal()
    evidence = [
        _evidence("career", "applications_submitted", 8),
        _evidence("career", "responses_received", 2),
    ]
    proposal = proposal_from_goal(goal)
    numeric = build_numeric_inputs(
        goal, proposal, evidence, overrides={"weekly_application_rate": 10}
    )
    assert numeric is not None
    assert numeric.assumptions.get("weekly_application_rate") == 10


def test_unsupported_intervention_has_no_probability_side_effect() -> None:
    parsed = parse_intervention_text("Maybe try harder sometimes")
    assert not parsed.changes
    assert parsed.unsupported


async def _seed_evidence(
    repo: InMemoryEvidenceRepository, goal_id, user_id, items: list[tuple[str, str, float, str]]
) -> None:
    for domain, metric, value, unit in items:
        await repo.insert(
            user_id,
            goal_id,
            EvidenceEventProposal.model_validate(
                {
                    "source_type": "manual",
                    "event_type": "observation",
                    "domain": domain,
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


@pytest.mark.asyncio
async def test_finance_change_simulation_end_to_end() -> None:
    goal = _finance_goal()
    user_id = uuid4()
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, user_id)
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    await _seed_evidence(
        evidence_repo,
        goal.goal_id,
        user_id,
        [
            ("finance", "net_worth", 200_000, "CAD"),
            ("finance", "monthly_contribution", 3000, "CAD/month"),
        ],
    )
    service = WhatIfService(GoalService(goal_repo), evidence=EvidenceService(evidence_repo))
    evidence = await evidence_repo.list_for_goal(goal.goal_id)
    baseline = build_baseline_state(goal, evidence)
    assert baseline.priced
    parsed = parse_intervention_text("Invest $4,000 per month")
    request = WhatIfRequest.model_validate(
        {
            "goal_id": str(goal.goal_id),
            "current_value": baseline.current_value,
            "target_value": baseline.target_value,
            "periods": baseline.periods,
            "direction": baseline.direction,
            "assumptions": baseline.assumptions,
            "parsed_changes": [
                {
                    "metric": item.metric,
                    "operation": item.operation,
                    "value": item.value,
                    "unit": item.unit,
                    "provenance": item.provenance,
                }
                for item in parsed.changes
            ],
            "intervention": baseline.default_intervention,
            "config": baseline.config,
        }
    )
    result = await service.simulate(request)
    assert result.priced
    assert result.scenario_probability is not None
    assert result.baseline_probability is not None


@pytest.mark.asyncio
async def test_career_deadline_simulation_uses_domain_probability() -> None:
    goal = _hiring_goal()
    user_id = uuid4()
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, user_id)
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    await _seed_evidence(
        evidence_repo,
        goal.goal_id,
        user_id,
        [
            ("career", "applications_submitted", 15, "count"),
            ("career", "phone_screens_completed", 3, "count"),
            ("career", "technical_interviews_completed", 1, "count"),
        ],
    )
    service = WhatIfService(GoalService(goal_repo), evidence=EvidenceService(evidence_repo))
    evidence = await evidence_repo.list_for_goal(goal.goal_id)
    baseline = build_baseline_state(goal, evidence)
    assert baseline.priced
    parsed = parse_intervention_text("10 applications per week")
    request = WhatIfRequest.model_validate(
        {
            "goal_id": str(goal.goal_id),
            "current_value": baseline.current_value or 0,
            "target_value": baseline.target_value or 1,
            "periods": baseline.periods or 1,
            "direction": baseline.direction,
            "assumptions": baseline.assumptions,
            "parsed_changes": [
                {
                    "metric": item.metric,
                    "operation": item.operation,
                    "value": item.value,
                    "unit": item.unit,
                    "provenance": item.provenance,
                }
                for item in parsed.changes
            ],
            "intervention": baseline.default_intervention,
            "config": baseline.config,
        }
    )
    result = await service.simulate(request)
    assert result.priced
    assert result.scenario_probability is not None
