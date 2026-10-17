from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.hiring import build_hiring_numeric_inputs
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
from personal_markets.ports import EvidenceEventProposal
from personal_markets.what_if.assumptions import hazard_assumptions
from personal_markets.what_if.baseline_state import build_baseline_state, proposal_from_goal
from personal_markets.what_if.domain import Assumption, WhatIfRequest
from personal_markets.what_if.futures_decision import parse_futures_decision
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


def _hiring_goal() -> GoalContract:
    return GoalContract.model_validate(
        {
            "goal_id": uuid4(),
            "title": "Receive a Big Tech SWE offer",
            "goal_type": GoalType.DEADLINE_EVENT,
            "success_definition": {"metric": "offer_received", "target": "swe_offer"},
            "deadline": datetime.now(UTC) + timedelta(days=180),
            "state_dimensions": ["application_pipeline"],
            "resource_constraints": {"hours_per_week": 10},
        }
    )


def test_canonical_assumptions_include_metadata() -> None:
    goal = _hiring_goal()
    evidence = [
        _evidence("career", "applications_submitted", 12),
        _evidence("career", "responses_received", 3),
    ]
    state = build_baseline_state(goal, evidence)
    assert state.priced
    assert state.resource_budget.hours_per_week == 10
    assumption = next(item for item in state.assumptions if item.name == "weekly_application_rate")
    assert assumption.id == "weekly_application_rate"
    assert assumption.provenance
    assert assumption.scope == "pipeline_activity"
    assert assumption.model_family == "deadline_event_hazard"


def test_hiring_assumptions_expose_stage_conversions() -> None:
    goal = _hiring_goal()
    evidence = [_evidence("career", "applications_submitted", 5)]
    numeric = build_hiring_numeric_inputs(goal, proposal_from_goal(goal), evidence)
    assert numeric is not None
    assumptions = hazard_assumptions(
        numeric, model_family="deadline_event_hazard", model_version="1.0.0"
    )
    stage_names = {item.name for item in assumptions if item.scope == "stage_conversion"}
    assert "application_to_response" in stage_names
    assert all(item.source.value == "REFERENCE" for item in assumptions if item.scope == "stage_conversion")


def test_futures_decision_parser_extracts_typed_decision() -> None:
    parsed = parse_futures_decision("What if I quit my internship and work on my startup?")
    assert parsed.decision is not None
    assert parsed.decision.action == "leave_job"
    assert parsed.decision.alternative == "full_time_startup"
    assert parsed.scenario_labels
    assert not parsed.unsupported


async def _seed(repo: InMemoryEvidenceRepository, goal_id, user_id, rows):
    for domain, metric, value, unit in rows:
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
async def test_hiring_sensitivity_is_non_empty() -> None:
    goal = _hiring_goal()
    user_id = uuid4()
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, user_id)
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    await _seed(
        evidence_repo,
        goal.goal_id,
        user_id,
        [
            ("career", "applications_submitted", 15, "count"),
            ("career", "phone_screens_completed", 3, "count"),
        ],
    )
    service = WhatIfService(GoalService(goal_repo), evidence=EvidenceService(evidence_repo))
    evidence = await evidence_repo.list_for_goal(goal.goal_id)
    baseline = build_baseline_state(goal, evidence)
    request = WhatIfRequest.model_validate(
        {
            "goal_id": str(goal.goal_id),
            "current_value": baseline.current_value or 0,
            "target_value": baseline.target_value or 1,
            "periods": baseline.periods or 1,
            "direction": baseline.direction,
            "assumptions": baseline.assumptions,
            "intervention": baseline.default_intervention,
            "config": baseline.config,
        }
    )
    result = await service.fast_reprice(request)
    assert result.priced
    assert result.sensitivity
    assert all(item.swing >= 0 for item in result.sensitivity)
    assert result.sensitivity[0].assumption_id


@pytest.mark.asyncio
async def test_fast_reprice_has_zero_llm_calls_and_no_history_write() -> None:
    goal = GoalContract.model_validate(
        {
            "goal_id": uuid4(),
            "title": "Reach one million dollars in net worth",
            "goal_type": GoalType.CONTINUOUS_TARGET,
            "success_definition": {"metric": "net_worth", "operator": ">=", "amount": 1_000_000},
            "deadline": datetime.now(UTC) + timedelta(days=365 * 5),
            "state_dimensions": ["liquid_assets"],
            "resource_constraints": {"hours_per_week": 8, "budget_amount": 2000, "budget_currency": "CAD"},
        }
    )
    user_id = uuid4()
    goal_repo = InMemoryGoalRepository()
    await goal_repo.create(goal, user_id)
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    await _seed(
        evidence_repo,
        goal.goal_id,
        user_id,
        [
            ("finance", "net_worth", 250_000, "CAD"),
            ("finance", "monthly_contribution", 2000, "CAD/month"),
        ],
    )
    service = WhatIfService(GoalService(goal_repo), evidence=EvidenceService(evidence_repo))
    evidence = await evidence_repo.list_for_goal(goal.goal_id)
    baseline = build_baseline_state(goal, evidence)
    history_before = await service.history(str(goal.goal_id))
    request = WhatIfRequest.model_validate(
        {
            "goal_id": str(goal.goal_id),
            "current_value": baseline.current_value,
            "target_value": baseline.target_value,
            "periods": baseline.periods,
            "direction": baseline.direction,
            "assumptions": [
                Assumption.model_validate(
                    {
                        **item.model_dump(mode="json"),
                        "value": item.value + (item.step if item.name == "flow" else 0),
                    }
                )
                for item in baseline.assumptions
            ],
            "intervention": {
                **baseline.default_intervention.model_dump(mode="json"),
                "effect_per_unit": 500,
                "effect_source": "EXPLORATION_ASSUMPTION",
            },
            "config": baseline.config,
        }
    )
    result = await service.fast_reprice(request)
    history_after = await service.history(str(goal.goal_id))
    assert result.priced
    assert result.llm_calls == 0
    assert len(history_after) == len(history_before)
    assert result.distribution_bins
    assert result.resource_budget is not None
