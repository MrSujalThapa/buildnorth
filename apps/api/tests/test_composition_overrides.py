"""Explicit What If edits must replace parameters that were estimated from history."""

from datetime import UTC, datetime, timedelta

import pytest

from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.agents.model_planner import refine_architect_proposal
from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.composition import composition_numeric_inputs, price_composition
from personal_markets.forecasting.engine import FamilyPrice
from personal_markets.goals.domain import GoalContract
from personal_markets.ports import GoalArchitectProposal


def _goal() -> GoalContract:
    proposal = refine_architect_proposal(
        GoalArchitectProposal.model_validate(
            {
                "ready_to_commit": True,
                "title": "Reach 10000 subscribers",
                "goal_type": "threshold",
                "success_metric": "subscribers",
                "success_operator": ">=",
                "success_target": "10000",
                "deadline": (datetime.now(UTC) + timedelta(days=365)).date().isoformat(),
                "primitive_kind": "growth",
                "state_dimensions": ["subscribers"],
                "current_state_known": {"subscribers": "1200"},
                "model_family_compatibility": "deadline_event_hazard",
            }
        )
    )
    return proposal_to_contract(proposal)


def _evidence() -> list[NormalizedEvidence]:
    now = datetime.now(UTC)
    return [
        NormalizedEvidence(
            event_type="uploaded_measurement",
            domain="user_state",
            metric="subscribers",
            numeric_value=value,
            unit="subscribers",
            observed_at=now - timedelta(days=days),
            source_quality="user_imported",
            provenance=Provenance(
                source_type="upload",
                source_authority="user_file",
                observed_vs_entered="imported",
                parsing_status="ok",
                completeness="complete",
                conflict_status="none",
                observation_kind="snapshot",
            ),
            summary="subscribers",
            fingerprint=f"subscribers-{days}",
        )
        for days, value in [(90, 800), (60, 950), (30, 1100), (0, 1200)]
    ]


def _price(
    goal: GoalContract, overrides: dict[str, float] | None = None
) -> tuple[float, FamilyPrice]:
    inputs = composition_numeric_inputs(goal, _evidence(), overrides=overrides)
    assert inputs is not None
    price = price_composition(goal, inputs)
    assert price is not None and price.priced and price.raw_probability is not None
    return price.raw_probability, price


@pytest.mark.parametrize("key", ["mu", "primary.mu"])
def test_override_replaces_estimated_growth_rate(key: str) -> None:
    goal = _goal()
    baseline, _ = _price(goal)
    edited, price = _price(goal, {key: 0.2})
    assert edited > baseline + 0.05
    used = {item["name"]: item for item in price.used_assumptions}
    assert used["primary.mu"]["value"] == pytest.approx(0.2)


def test_unknown_override_does_not_change_estimate() -> None:
    goal = _goal()
    baseline, _ = _price(goal)
    edited, _ = _price(goal, {"other.mu": 0.9})
    assert edited == pytest.approx(baseline)


def test_clipped_growth_override_keeps_raw_probabilities() -> None:
    from personal_markets.forecasting.primitives import at_numerical_bound

    goal = _goal()
    baseline, _ = _price(goal, {"mu": -2.0})
    edited, price = _price(goal, {"mu": 2.0})
    assert at_numerical_bound(baseline) or baseline < 0.01
    assert edited > baseline
    assert price.raw_probability == pytest.approx(edited)
    assert price.raw_probability is not None
    assert 0 < price.raw_probability < 1


@pytest.mark.parametrize("key", ["rate", "primary.rate"])
def test_missing_count_rate_can_be_supplied_as_manual_state(key: str) -> None:
    proposal = refine_architect_proposal(
        GoalArchitectProposal.model_validate(
            {
                "ready_to_commit": True,
                "title": "Read 20 books",
                "goal_type": "threshold",
                "success_metric": "books_read_count",
                "success_operator": ">=",
                "success_target": "20",
                "deadline": (datetime.now(UTC) + timedelta(days=365)).date().isoformat(),
                "primitive_kind": "cumulative_count",
                "state_dimensions": ["books_read_count"],
                "current_state_known": {"books_read_count": "5"},
                "model_family_compatibility": "exploratory_general",
            }
        )
    )
    goal = proposal_to_contract(proposal)
    evidence = [_evidence()[-1].model_copy(update={"metric": "books_read_count", "numeric_value": 5})]
    baseline = price_composition(goal, composition_numeric_inputs(goal, evidence))
    assert baseline is not None and not baseline.priced

    inputs = composition_numeric_inputs(goal, evidence, overrides={key: 0.5})
    assert inputs is not None
    priced = price_composition(goal, inputs)
    assert priced is not None and priced.priced
    assert priced.raw_probability is not None
    assert inputs.assumptions["primary.rate"] == pytest.approx(0.5)

    manual_rate = evidence[0].model_copy(
        update={"event_type": "manual_state_entry", "metric": "rate", "numeric_value": 0.5}
    )
    from_evidence = composition_numeric_inputs(goal, [*evidence, manual_rate])
    assert from_evidence is not None
    published = price_composition(goal, from_evidence)
    assert published is not None and published.priced
    assert from_evidence.assumptions["primary.rate"] == pytest.approx(0.5)
