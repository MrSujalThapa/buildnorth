from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.inputs_builder import build_numeric_inputs
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.forecasting.startup import (
    aggregate_startup_from_evidence,
    build_startup_numeric_inputs,
    derive_outcome_weights,
    load_startup_reference,
    startup_goal_kind,
)
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import GoalArchitectProposal


def _goal(**overrides: object) -> GoalContract:
    payload: dict[str, object] = {
        "goal_id": uuid4(),
        "title": "Raise a seed round by June 2027",
        "goal_type": GoalType.DEADLINE_EVENT,
        "success_definition": {"metric": "seed_round", "target": "closed", "operator": "=="},
        "deadline": datetime.now(UTC) + timedelta(days=365),
        "state_dimensions": ["mrr", "runway", "fundraising_pipeline"],
    }
    payload.update(overrides)
    return GoalContract.model_validate(payload)


def _proposal(goal: GoalContract) -> GoalArchitectProposal:
    return GoalArchitectProposal.model_validate(
        {
            "ready_to_commit": True,
            "title": goal.title,
            "goal_type": goal.goal_type.value,
            "success_metric": str(goal.success_definition.get("metric") or "startup"),
            "success_operator": "==",
            "success_target": str(goal.success_definition.get("target") or ""),
            "deadline": goal.deadline.date().isoformat(),
            "state_dimensions": goal.state_dimensions,
            "model_family_compatibility": "exploratory_startup",
        }
    )


def _evidence(metric: str, value: float | None = None, summary: str = "") -> NormalizedEvidence:
    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type="observation",
        domain="startup",
        metric=metric,
        numeric_value=value,
        unit="USD" if "mrr" in metric else None,
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
        summary=summary,
        fingerprint="test",
    )


def test_startup_reference_loads_and_sums_to_one() -> None:
    ref = load_startup_reference()
    total = sum(ref.base_weights.values())
    assert total == pytest.approx(1.0)


def test_no_startup_evidence_stays_unpriced() -> None:
    goal = _goal()
    assert build_startup_numeric_inputs(goal, _proposal(goal), []) is None


def test_seed_goal_prices_from_typed_evidence() -> None:
    goal = _goal()
    evidence = [
        _evidence("mrr", 8000),
        _evidence("runway_months", 8),
        _evidence("fundraising_conversation", None, summary="fundraising conversation"),
    ]
    numeric = build_startup_numeric_inputs(goal, _proposal(goal), evidence)
    assert numeric is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(
        goal,
        _proposal(goal),
        ["ev-1"],
        {},
        ["startup_outcome_priors.json"],
        numeric,
    )
    assert pricing.priced is True
    assert pricing.raw_probability is not None
    assert 0 < pricing.raw_probability < 1
    assert "startup_quality" not in str(pricing.receipt).lower()


def test_multi_outcome_startup_weights_sum_to_one() -> None:
    goal = _goal(
        goal_type=GoalType.MULTI_OUTCOME,
        title="Build a sustainable startup path",
        success_definition={"metric": "startup_outcome", "target": "raise_external_funding"},
    )
    evidence = [_evidence("mrr", 12000), _evidence("runway_months", 10)]
    numeric = build_startup_numeric_inputs(goal, _proposal(goal), evidence)
    assert numeric is not None
    weights = numeric.state["outcome_weights"]
    assert pytest.approx(sum(weights.values())) == 1.0
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(goal, _proposal(goal), [], {}, [], numeric)
    assert pricing.priced is True


def test_term_sheet_increases_raise_weight() -> None:
    base = derive_outcome_weights(aggregate_startup_from_evidence([_evidence("mrr", 5000)]))
    boosted = derive_outcome_weights(
        aggregate_startup_from_evidence(
            [_evidence("mrr", 5000), _evidence("term_sheet", None, summary="term sheet received")]
        )
    )
    assert boosted["raise_external_funding"] > base["raise_external_funding"]


def test_startup_goal_kind_classification() -> None:
    assert startup_goal_kind(_goal()) == "deadline_event"
    mrr_goal = _goal(
        goal_type=GoalType.THRESHOLD,
        title="Reach 20k MRR",
        success_definition={"metric": "mrr", "operator": ">=", "value": 20000},
    )
    assert startup_goal_kind(mrr_goal) == "threshold"


def test_inputs_builder_routes_startup() -> None:
    goal = _goal()
    evidence = [_evidence("mrr", 4000)]
    assert build_numeric_inputs(goal, _proposal(goal), evidence) is not None
