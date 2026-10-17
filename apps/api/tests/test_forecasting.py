from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest

from personal_markets.forecasting.decay import ExponentialDecay
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.receipts import (
    BASELINE_RECEIPT_KEYS,
    ForecastReceipt,
    missing_receipt_keys,
)
from personal_markets.forecasting.registry import OuladCompletionApplicabilityPolicy
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.forecasting.temporal import percentage_point_change, summarize_trajectory
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import CriticArtifact, GoalArchitectProposal


def test_exponential_decay_has_known_half_life_and_rejects_future_events() -> None:
    decay = ExponentialDecay(7)
    weights = decay.weights(np.array([0.0, 7.0, 10000.0]))
    assert weights[0] == 1
    assert weights[0] > weights[1] > weights[2] >= 0
    assert decay.aggregate(np.array([10.0]), np.array([7.0])) == pytest.approx(5.0)
    with pytest.raises(ValueError, match="negative"):
        decay.weights(np.array([-1.0]))


def test_applicability_fails_closed_outside_frozen_contract() -> None:
    policy = OuladCompletionApplicabilityPolicy()
    assert policy.evaluate("deadline_event", "course_completion", 35).status == "CALIBRATED"
    rejected = policy.evaluate("threshold", "course_completion", 35)
    assert not rejected.applicable
    assert rejected.status == "EXPLORATORY"


def test_forecast_receipt_is_machine_and_human_readable() -> None:
    receipt = ForecastReceipt(
        forecast_id=str(uuid4()),
        goal_id=str(uuid4()),
        goal_contract_version=1,
        case_id="case-1",
        as_of_day=35,
        evidence_watermark="day-35",
        relevant_evidence_ids=["event-1"],
        state_snapshot_id="state-1",
        state_snapshot_version=1,
        run_id="run-1",
        raw_probability=0.7,
        calibrated_probability=0.65,
        forecast_status="CALIBRATED",
        model={"family": "test"},
        calibration={"method": "platt"},
        feature_schema_version="test-v1",
        feature_snapshot={"clicks": 3},
        transformations={"decay": 7},
        training_dataset={"name": "fixture"},
        assumptions=["fixture"],
        contributions=[],
        provenance={"source": "fixture"},
        limitations=["fixture"],
    )
    assert receipt.model_dump(mode="json")["calibrated_probability"] == 0.65
    assert "65.0%" in receipt.human_summary()
    assert receipt.api_representation().receipt["forecast_id"] == receipt.forecast_id
    assert len(receipt.content_hash()) == 64


def test_repeated_deterioration_is_distinct_from_one_bad_day() -> None:
    isolated = summarize_trajectory([1, 1, 1, -1], [21, 14, 7, 0], half_life_days=14, recent_days=7)
    regime = summarize_trajectory([1, -1, -1, -1], [21, 14, 7, 0], half_life_days=14, recent_days=7)
    assert regime.negative_streak > isolated.negative_streak
    assert regime.exponentially_weighted_mean < isolated.exponentially_weighted_mean


def test_percentage_point_change_is_not_relative_percent() -> None:
    assert percentage_point_change(0.58, 0.64) == pytest.approx(6)


def _goal(goal_type: GoalType = GoalType.DEADLINE_EVENT, **overrides: object) -> GoalContract:
    payload: dict[str, object] = {
        "goal_id": uuid4(),
        "title": "Receive an SWE offer",
        "goal_type": goal_type,
        "success_definition": {"metric": "offer_received", "target": "swe_offer"},
        "deadline": datetime.now(UTC) + timedelta(days=365),
        "state_dimensions": ["interview_outcomes"],
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
            "model_family_compatibility": "exploratory",
        }
    )


def test_baseline_without_numeric_inputs_stays_unpriced() -> None:
    repository = InMemoryBaselineForecastRepository()
    service = BaselineForecastService(repository)
    goal = _goal()
    pricing = service.compute(goal, _proposal(goal), [], {}, [])
    assert pricing.priced is False
    assert pricing.raw_probability is None
    assert pricing.forecast_status == "EXPLORATORY"
    assert pricing.receipt["publication"] == "NOT_PRICED"
    assert pricing.receipt["model"]["family"] == "deadline_event_hazard"
    assert pricing.receipt["llm_used_for_probability"] is False
    assert 0.5 not in {pricing.raw_probability, pricing.calibrated_probability}


def test_deadline_hazard_prices_from_explicit_logits() -> None:
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    goal = _goal()
    pricing = service.compute(
        goal,
        _proposal(goal),
        ["ev-1"],
        {"goal_architect": "run-1"},
        ["ref-1"],
        NumericInputs(
            state={"baseline_logits": [0.0, 0.0]},
            assumption_sources={"baseline_logits": "REFERENCE"},
        ),
    )
    assert pricing.priced is True
    assert pricing.raw_probability == pytest.approx(0.75)
    assert pricing.forecast_status == "ANCHORED"
    assert pricing.receipt["evidence_watermark"] == "ev-1"
    assert pricing.receipt["forecast_kind"] == "baseline"
    assert missing_receipt_keys(pricing.receipt, BASELINE_RECEIPT_KEYS) == []
    assert pricing.receipt["llm_used_for_probability"] is False
    assert pricing.receipt["calibration"]["applied"] is False


@pytest.mark.asyncio
async def test_publish_writes_history_only_for_priced_approved_forecasts() -> None:
    repository = InMemoryBaselineForecastRepository()
    service = BaselineForecastService(repository)
    goal = _goal()
    unpriced = service.compute(goal, _proposal(goal), [], {}, [])
    withheld = await service.publish(
        goal,
        unpriced,
        CriticArtifact(decision="withhold", issues=[], limitations=[], required_actions=[]),
    )
    assert withheld == "withheld"
    assert service.history(goal.goal_id) == []

    limited = await service.publish(
        goal,
        unpriced,
        CriticArtifact(
            decision="publish_with_limitations", issues=[], limitations=[], required_actions=[]
        ),
    )
    assert limited == "limited"
    assert service.history(goal.goal_id) == []

    priced = service.compute(
        goal,
        _proposal(goal),
        ["ev-2"],
        {},
        [],
        NumericInputs(assumptions={"baseline_logit": 0.0}, state={"periods_remaining": 2}),
    )
    completed = await service.publish(
        goal,
        priced,
        CriticArtifact(decision="publish", issues=[], limitations=[], required_actions=[]),
    )
    assert completed == "completed"
    history = service.history(goal.goal_id)
    assert len(history) == 1
    assert history[0].probability == pytest.approx(0.75)
    assert history[0].source_kind == "published_forecast"
    assert history[0].model_family == "deadline_event_hazard"


def test_habit_family_prices_from_binary_history() -> None:
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    goal = _goal(
        GoalType.HABIT,
        title="Train five days a week",
        success_definition={"metric": "training_days", "target": "5"},
        state_dimensions=["history"],
    )
    pricing = service.compute(
        goal,
        _proposal(goal),
        [],
        {},
        [],
        NumericInputs(
            state={"history": [True, True, True, False]},
            assumptions={"prior_alpha": 1.0, "prior_beta": 1.0},
        ),
    )
    assert pricing.priced is True
    assert pricing.raw_probability is not None
    assert 0 < pricing.raw_probability < 1
    assert pricing.receipt["model"]["family"] == "habit_beta_recency"


def test_multi_outcome_rejects_weights_that_do_not_sum_to_one() -> None:
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    goal = _goal(
        GoalType.MULTI_OUTCOME,
        title="Quit and work on a startup",
        success_definition={"metric": "startup_outcome", "target": "raise"},
        state_dimensions=["outcomes"],
    )
    pricing = service.compute(
        goal,
        _proposal(goal),
        [],
        {},
        [],
        NumericInputs(state={"outcome_weights": {"raise": 0.4, "fail": 0.4}}),
    )
    assert pricing.priced is False
    assert pricing.raw_probability is None
    assert any("sum to 1" in item for item in pricing.limitations)


def test_proposal_cannot_inject_a_probability() -> None:
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    goal = _goal()
    proposal = _proposal(goal).model_copy(update={"notes": "probability=0.91"})
    pricing = service.compute(goal, proposal, [], {}, [])
    assert pricing.raw_probability is None
    assert pricing.priced is False
