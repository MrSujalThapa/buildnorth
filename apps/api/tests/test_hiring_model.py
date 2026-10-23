from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.hiring import (
    HiringFunnelState,
    _pipeline_offer_probability,
    _stage_to_offer,
    aggregate_funnel_from_evidence,
    apply_funnel_overrides,
    build_hiring_numeric_inputs,
    funnel_state_to_numeric_inputs,
    is_hiring_goal,
    load_hiring_reference,
)
from personal_markets.forecasting.inputs_builder import build_numeric_inputs
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import GoalArchitectProposal


def _goal(**overrides: object) -> GoalContract:
    payload: dict[str, object] = {
        "goal_id": uuid4(),
        "title": "Receive an SWE offer",
        "goal_type": GoalType.DEADLINE_EVENT,
        "success_definition": {"metric": "offer_received", "target": "swe_offer"},
        "deadline": datetime.now(UTC) + timedelta(days=180),
        "state_dimensions": ["applications_submitted", "interview_outcomes"],
    }
    payload.update(overrides)
    return GoalContract.model_validate(payload)


def _proposal(goal: GoalContract) -> GoalArchitectProposal:
    return GoalArchitectProposal.model_validate(
        {
            "ready_to_commit": True,
            "title": goal.title,
            "goal_type": goal.goal_type.value,
            "success_metric": goal.success_definition["metric"],
            "success_operator": "==",
            "success_target": str(goal.success_definition.get("target") or ""),
            "deadline": goal.deadline.date().isoformat(),
            "state_dimensions": goal.state_dimensions,
            "model_family_compatibility": "exploratory_hiring",
        }
    )


def _evidence(
    *,
    metric: str,
    event_type: str = "observation",
    numeric_value: float | None = None,
    categorical_value: str | None = None,
    unit: str | None = None,
    summary: str = "",
    observed_at: datetime | None = None,
) -> NormalizedEvidence:
    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type=event_type,
        domain="hiring",
        metric=metric,
        numeric_value=numeric_value,
        categorical_value=categorical_value,
        unit=unit or ("count" if numeric_value is not None else None),
        observed_at=observed_at or datetime.now(UTC),
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


def test_hiring_reference_rates_load_with_all_stages() -> None:
    rates = load_hiring_reference()
    assert rates.reference_id == "hiring_funnel_rates.json"
    assert len(rates.stage_rates) == 6
    assert 0 < rates.stage_rates["final_to_offer"] < 1


def test_is_hiring_goal_detects_offer_goals() -> None:
    goal = _goal()
    assert is_hiring_goal(goal, _proposal(goal)) is True


def test_empty_funnel_stays_unpriced() -> None:
    goal = _goal()
    assert build_hiring_numeric_inputs(goal, _proposal(goal), []) is None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(goal, _proposal(goal), [], {}, [], None)
    assert pricing.priced is False


def test_applications_only_produces_reference_backed_logits() -> None:
    goal = _goal()
    evidence = [_evidence(metric="applications_submitted", numeric_value=10, summary="submitted")]
    numeric = build_hiring_numeric_inputs(goal, _proposal(goal), evidence)
    assert numeric is not None
    assert "baseline_logits" in numeric.state
    assert numeric.assumption_sources["baseline_logits"] == "REFERENCE"
    assert "strength" not in str(numeric.state).lower()


def test_technical_pipeline_prices_higher_than_cold_applications() -> None:
    rates = load_hiring_reference().stage_rates
    cold = HiringFunnelState(applications=20)
    warm = HiringFunnelState(applications=20, responses=20, phone_screens=20, oas=20, technicals=1)
    assert _pipeline_offer_probability(warm, rates) > _pipeline_offer_probability(cold, rates)


def test_offer_received_prices_near_certainty_from_evidence() -> None:
    goal = _goal()
    evidence = [_evidence(metric="offer_received", categorical_value="signed", summary="offer")]
    numeric = build_hiring_numeric_inputs(goal, _proposal(goal), evidence)
    assert numeric is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(
        goal, _proposal(goal), ["ev-1"], {}, ["hiring_funnel_rates.json"], numeric
    )
    assert pricing.priced is True
    assert pricing.raw_probability is not None
    assert pricing.raw_probability > 0.99


def test_rejection_lowers_probability_vs_advancement() -> None:
    goal = _goal(deadline=datetime.now(UTC) + timedelta(weeks=26))
    advanced = [
        _evidence(metric="applications_submitted", numeric_value=5, summary="applied"),
        _evidence(metric="stage", categorical_value="technical_screen", summary="advanced"),
    ]
    rejected = [
        _evidence(metric="applications_submitted", numeric_value=5, summary="applied"),
        _evidence(
            metric="stage",
            categorical_value="technical_screen",
            summary="rejected after technical",
        ),
    ]
    adv_numeric = build_hiring_numeric_inputs(goal, _proposal(goal), advanced)
    rej_numeric = build_hiring_numeric_inputs(goal, _proposal(goal), rejected)
    assert adv_numeric is not None and rej_numeric is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    adv = service.compute(goal, _proposal(goal), [], {}, [], adv_numeric)
    rej = service.compute(goal, _proposal(goal), [], {}, [], rej_numeric)
    assert adv.raw_probability is not None and rej.raw_probability is not None
    assert adv.raw_probability > rej.raw_probability


def test_what_if_overrides_edit_typed_funnel_quantities() -> None:
    goal = _goal()
    base_state = HiringFunnelState(applications=2)
    overridden = apply_funnel_overrides(base_state, {"applications": 30, "technicals": 2})
    base_numeric = funnel_state_to_numeric_inputs(goal, base_state)
    scenario_numeric = funnel_state_to_numeric_inputs(goal, overridden)
    assert base_numeric is not None and scenario_numeric is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    base = service.compute(goal, _proposal(goal), [], {}, [], base_numeric)
    scenario = service.compute(goal, _proposal(goal), [], {}, [], scenario_numeric)
    assert base.raw_probability is not None and scenario.raw_probability is not None
    assert scenario.raw_probability > base.raw_probability


def test_stage_to_offer_chain_is_deterministic() -> None:
    rates = load_hiring_reference().stage_rates
    full_chain = _stage_to_offer(rates, 0)
    final_only = _stage_to_offer(rates, 5)
    assert full_chain < final_only
    assert full_chain == pytest.approx(
        rates["application_to_response"]
        * rates["response_to_phone_screen"]
        * rates["phone_screen_to_oa"]
        * rates["oa_to_technical"]
        * rates["technical_to_final"]
        * rates["final_to_offer"]
    )


def test_aggregate_splits_independent_interview_events() -> None:
    now = datetime.now(UTC)
    evidence = [
        _evidence(
            metric="applications_submitted",
            numeric_value=5,
            summary="applied",
            observed_at=now - timedelta(days=3),
        ),
        _evidence(
            metric="phone_screen",
            numeric_value=1,
            summary="phone screen completed",
            observed_at=now - timedelta(days=1),
        ),
        _evidence(
            metric="leetcode_practice",
            numeric_value=6,
            unit="hours",
            summary="studied leetcode",
            observed_at=now,
        ),
    ]
    state = aggregate_funnel_from_evidence(evidence, now=now)
    assert state.applications == 5
    assert state.phone_screens == 1
    assert state.practice_hours == 6.0
    assert state.last_activity_at == now


def test_inputs_builder_routes_hiring_goals_only() -> None:
    goal = _goal()
    non_hiring = GoalContract.model_validate(
        {
            **_goal().model_dump(),
            "title": "Maintain daily meditation",
            "success_definition": {"metric": "sessions", "target": "daily"},
            "state_dimensions": ["history"],
            "goal_type": GoalType.HABIT,
        }
    )
    habit_proposal = GoalArchitectProposal.model_validate(
        {
            "ready_to_commit": True,
            "title": non_hiring.title,
            "goal_type": non_hiring.goal_type.value,
            "success_metric": "sessions",
            "success_operator": ">=",
            "success_target": "daily",
            "deadline": non_hiring.deadline.date().isoformat(),
            "state_dimensions": non_hiring.state_dimensions,
            "model_family_compatibility": "habit",
        }
    )
    evidence = [_evidence(metric="applications_submitted", numeric_value=1, summary="applied")]
    assert build_numeric_inputs(goal, _proposal(goal), evidence) is not None
    assert build_numeric_inputs(non_hiring, habit_proposal, evidence) is None


def test_successive_application_snapshots_are_not_summed() -> None:
    now = datetime.now(UTC)
    evidence = [
        _evidence(
            metric="applications_submitted",
            event_type="manual_state_entry",
            numeric_value=6,
            summary="stock",
            observed_at=now - timedelta(days=1),
        ),
        _evidence(
            metric="applications_submitted",
            event_type="manual_state_entry",
            numeric_value=18,
            summary="stock",
            observed_at=now,
        ),
    ]
    state = aggregate_funnel_from_evidence(evidence, now=now)
    assert state.applications == 18


def test_identical_application_increments_on_different_days_are_summed() -> None:
    now = datetime.now(UTC)
    evidence = [
        _evidence(
            metric="applications_submitted",
            event_type="increment",
            numeric_value=1,
            summary="sent one",
            observed_at=now - timedelta(days=1),
        ),
        _evidence(
            metric="applications_submitted",
            event_type="increment",
            numeric_value=1,
            summary="sent one",
            observed_at=now,
        ),
    ]
    state = aggregate_funnel_from_evidence(evidence, now=now)
    assert state.applications == 2


def test_later_increments_add_to_latest_snapshot() -> None:
    now = datetime.now(UTC)
    evidence = [
        _evidence(
            metric="applications_submitted",
            event_type="manual_state_entry",
            numeric_value=6,
            summary="stock",
            observed_at=now - timedelta(days=2),
        ),
        _evidence(
            metric="applications_submitted",
            event_type="increment",
            numeric_value=1,
            summary="sent one",
            observed_at=now,
        ),
    ]
    state = aggregate_funnel_from_evidence(evidence, now=now)
    assert state.applications == 7


def test_later_snapshot_replaces_earlier_increments() -> None:
    now = datetime.now(UTC)
    evidence = [
        _evidence(
            metric="applications_submitted",
            event_type="increment",
            numeric_value=1,
            summary="sent one",
            observed_at=now - timedelta(days=2),
        ),
        _evidence(
            metric="applications_submitted",
            event_type="manual_state_entry",
            numeric_value=18,
            summary="stock",
            observed_at=now,
        ),
    ]
    state = aggregate_funnel_from_evidence(evidence, now=now)
    assert state.applications == 18


def test_snapshot_aggregation_reprices_eighteen_not_the_sum() -> None:
    now = datetime.now(UTC)
    goal = _goal(deadline=now + timedelta(weeks=26))
    proposal = _proposal(goal)
    sequential = [
        _evidence(
            metric="applications_submitted",
            event_type="manual_state_entry",
            numeric_value=6,
            summary="stock",
            observed_at=now - timedelta(days=1),
        ),
        _evidence(
            metric="applications_submitted",
            event_type="manual_state_entry",
            numeric_value=18,
            summary="stock",
            observed_at=now,
        ),
    ]
    eighteen = [
        _evidence(
            metric="applications_submitted",
            event_type="manual_state_entry",
            numeric_value=18,
            summary="stock",
            observed_at=now,
        )
    ]
    sequential_numeric = build_hiring_numeric_inputs(goal, proposal, sequential, now=now)
    eighteen_numeric = build_hiring_numeric_inputs(goal, proposal, eighteen, now=now)
    twenty_four_numeric = funnel_state_to_numeric_inputs(
        goal, HiringFunnelState(applications=24), now=now
    )
    assert sequential_numeric is not None and eighteen_numeric is not None
    assert twenty_four_numeric is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    sequential_price = service.compute(goal, proposal, ["a", "b"], {}, [], sequential_numeric)
    eighteen_price = service.compute(goal, proposal, ["c"], {}, [], eighteen_numeric)
    twenty_four_price = service.compute(goal, proposal, ["d"], {}, [], twenty_four_numeric)
    assert sequential_price.raw_probability == pytest.approx(eighteen_price.raw_probability)
    assert sequential_price.raw_probability != pytest.approx(twenty_four_price.raw_probability)
    assert sequential_numeric.state["funnel"]["applications"] == 18


def test_receipt_includes_funnel_transforms_not_strength_scores() -> None:
    goal = _goal()
    numeric = build_hiring_numeric_inputs(
        goal,
        _proposal(goal),
        [_evidence(metric="applications_submitted", numeric_value=8, summary="applied")],
    )
    assert isinstance(numeric, NumericInputs)
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(
        goal, _proposal(goal), ["ev-1"], {}, ["hiring_funnel_rates.json"], numeric
    )
    transforms = pricing.receipt["feature_transforms"]
    assert "funnel_state" in transforms
    assert "candidate_strength" not in transforms
    assert pricing.receipt["reference_versions"]


def _snapshot(metric: str, value: float, event_type: str, summary: str) -> NormalizedEvidence:
    item = _evidence(metric=metric, event_type=event_type, numeric_value=value, summary=summary)
    return item.model_copy(
        update={"provenance": item.provenance.model_copy(update={"observation_kind": "snapshot"})}
    )


def test_explicit_zero_offer_snapshot_is_not_an_offer() -> None:
    goal = _goal()
    evidence = [
        _snapshot("applications_submitted_cumulative", 40, "internship_application_submitted",
                  "User reports 40 internship applications submitted in total as of today."),
        _snapshot("offers_received_cumulative", 0, "offer_update",
                  "User reports no internship offers received yet."),
    ]
    state = aggregate_funnel_from_evidence(evidence)
    assert state.offers == 0
    numeric = build_hiring_numeric_inputs(goal, _proposal(goal), evidence)
    assert numeric is not None
    assert "offer_already_received" not in str(numeric.state)
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(
        goal, _proposal(goal), ["ev-1"], {}, ["hiring_funnel_rates.json"], numeric
    )
    assert pricing.raw_probability is not None and pricing.raw_probability < 0.99


def test_first_round_interviews_do_not_become_application_stock() -> None:
    interviews = _snapshot(
        "first_round_interviews_scheduled_cumulative", 2, "interview_scheduled",
        "User reports 2 first-round interviews received.",
    )
    applications = _snapshot(
        "applications_submitted_cumulative", 40, "internship_application_submitted",
        "User reports 40 internship applications submitted in total as of today.",
    )
    applications = applications.model_copy(update={"observed_at": interviews.observed_at})
    for order in ([interviews, applications], [applications, interviews]):
        state = aggregate_funnel_from_evidence(order)
        assert state.applications == 40
        assert state.technicals == 2


def test_resolved_rejections_shrink_the_reference_rate() -> None:
    goal = _goal()
    proposal = _proposal(goal)
    reference = load_hiring_reference()
    prior = reference.stage_rates["application_to_response"]
    pseudo = reference.resolved_outcome_pseudo_counts
    applications = [
        _evidence(metric="applications_submitted", numeric_value=10, summary="submitted")
    ]
    resolved = [
        *applications,
        _evidence(metric="responses", numeric_value=2, summary="recruiter response"),
        _evidence(
            metric="application_rejections",
            numeric_value=8,
            summary="application rejected",
        ),
    ]
    bare = build_hiring_numeric_inputs(goal, proposal, applications)
    fitted = build_hiring_numeric_inputs(goal, proposal, resolved)
    assert bare is not None and fitted is not None
    assert bare.assumption_sources["baseline_logits"] == "REFERENCE"
    assert "strength" not in str(bare.state).lower()
    assert fitted.state["prediction"]["method"] == "FITTED_STATISTICAL"
    assert fitted.state["prediction"]["trained_classifier"] is None
    assert fitted.state["prediction"]["calibration"]["applied"] is False
    expected = (2 + pseudo * prior) / (10 + pseudo)
    stage = fitted.state["prediction"]["uncertainty"]["fitted_stages"][0]
    assert stage["fitted_rate"] == pytest.approx(expected)
    assert stage["stage"] == "application_to_response"
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    before = service.compute(goal, proposal, ["e1"], {}, ["hiring_funnel_rates.json"], bare)
    after = service.compute(goal, proposal, ["e1", "e2"], {}, ["hiring_funnel_rates.json"], fitted)
    assert before.raw_probability is not None and after.raw_probability is not None
    assert after.raw_probability != pytest.approx(before.raw_probability)
    assert before.receipt["prediction"]["method"] == "REFERENCE_MODEL"
    assert after.receipt["prediction"]["method"] == "FITTED_STATISTICAL"
    assert after.receipt["calibration"]["applied"] is False
    rejected = {item["model_id"] for item in after.receipt["prediction"]["rejected_classifiers"]}
    assert rejected == {"jth_offer_v1"}
    assert after.receipt["llm_used_for_probability"] is False


def test_practice_hours_do_not_change_the_fitted_probability() -> None:
    goal = _goal()
    proposal = _proposal(goal)
    base = [
        _evidence(metric="applications_submitted", numeric_value=10, summary="submitted"),
        _evidence(
            metric="application_rejections",
            numeric_value=8,
            summary="application rejected",
        ),
    ]
    practiced = [
        *base,
        _evidence(metric="practice_hours", numeric_value=40, summary="interview practice hours"),
    ]
    without = build_hiring_numeric_inputs(goal, proposal, base)
    with_practice = build_hiring_numeric_inputs(goal, proposal, practiced)
    assert without is not None and with_practice is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    first = service.compute(goal, proposal, ["e1"], {}, [], without)
    second = service.compute(goal, proposal, ["e1", "e2"], {}, [], with_practice)
    assert first.raw_probability == pytest.approx(second.raw_probability)

