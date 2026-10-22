from dataclasses import replace
from datetime import UTC, datetime, timedelta
from statistics import NormalDist
from uuid import uuid4

import pytest

from personal_markets.agents.goal_mapping import proposal_to_contract
from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.inputs_builder import build_numeric_inputs
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.running import (
    aggregate_running_from_evidence,
    build_running_numeric_inputs,
    fit_performance_trend,
    goal_distance_km,
    is_running_goal,
    is_timed_race_target,
    load_running_reference,
    price_from_numeric_inputs,
    riegel_convert,
)
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import GoalArchitectProposal
from personal_markets.what_if.baseline_state import build_baseline_state


def _goal(**overrides: object) -> GoalContract:
    payload: dict[str, object] = {
        "goal_id": uuid4(),
        "title": "Run a 10K in under 50 minutes",
        "goal_type": GoalType.THRESHOLD,
        "success_definition": {
            "metric": "10k_time_seconds",
            "operator": "<=",
            "value": 3000,
        },
        "deadline": datetime.now(UTC) + timedelta(days=120),
        "state_dimensions": ["recent_race_time", "weekly_distance", "training_consistency"],
    }
    payload.update(overrides)
    return GoalContract.model_validate(payload)


def _proposal(goal: GoalContract) -> GoalArchitectProposal:
    return GoalArchitectProposal.model_validate(
        {
            "ready_to_commit": True,
            "title": goal.title,
            "goal_type": goal.goal_type.value,
            "success_metric": "10k_time_seconds",
            "success_operator": "<=",
            "success_target": "3000",
            "deadline": goal.deadline.date().isoformat(),
            "state_dimensions": goal.state_dimensions,
            "model_family_compatibility": "exploratory_running",
        }
    )


def _evidence(
    metric: str,
    value: float,
    *,
    unit: str | None = "seconds",
    summary: str = "",
    observed_at: datetime | None = None,
) -> NormalizedEvidence:
    return NormalizedEvidence(
        evidence_id=uuid4(),
        event_type="observation",
        domain="running",
        metric=metric,
        numeric_value=value,
        unit=unit,
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


def test_running_reference_loads() -> None:
    ref = load_running_reference()
    assert ref.reference_id == "running_performance_assumptions.json"
    assert ref.riegel_exponent > 1.0


def test_is_running_goal() -> None:
    assert is_running_goal(_goal(), _proposal(_goal())) is True


def test_no_running_evidence_stays_unpriced() -> None:
    goal = _goal()
    assert build_running_numeric_inputs(goal, _proposal(goal), []) is None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(goal, _proposal(goal), [], {}, [], None)
    assert pricing.priced is False


def test_improving_10k_trend_prices_with_nonzero_probability() -> None:
    goal = _goal()
    now = datetime.now(UTC)
    evidence = [
        _evidence("10k_time_seconds", 3240, observed_at=now - timedelta(days=60)),
        _evidence("10k_time_seconds", 3190, observed_at=now - timedelta(days=30)),
        _evidence("10k_time_seconds", 3130, observed_at=now - timedelta(days=7)),
    ]
    numeric = build_running_numeric_inputs(goal, _proposal(goal), evidence, now=now)
    assert numeric is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(
        goal,
        _proposal(goal),
        ["ev-1"],
        {},
        ["running_performance_assumptions.json"],
        numeric,
    )
    assert pricing.priced is True
    assert pricing.raw_probability is not None
    assert pricing.raw_probability > 0
    assert pricing.forecast_status in {"EXPLORATORY", "ANCHORED"}
    transforms = pricing.receipt["feature_transforms"]
    assert transforms["running_state"]["observation_count"] == 3
    assert transforms["running_state"]["direct_goal_distance_count"] == 3
    assert "fitness" not in str(transforms).lower()


def test_already_meets_target_has_high_probability() -> None:
    goal = _goal()
    evidence = [_evidence("10k_time_seconds", 2970, summary="10k race")]
    numeric = build_running_numeric_inputs(goal, _proposal(goal), evidence)
    assert numeric is not None
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    pricing = service.compute(goal, _proposal(goal), [], {}, [], numeric)
    assert pricing.raw_probability is not None
    assert pricing.raw_probability > 0.99


def test_projected_crossing_is_uncertain_not_already_achieved() -> None:
    goal = _goal()
    now = datetime.now(UTC)
    evidence = [
        _evidence("10k_time_seconds", 3150, observed_at=now - timedelta(days=60)),
        _evidence("10k_time_seconds", 3100, observed_at=now - timedelta(days=7)),
    ]
    numeric = build_running_numeric_inputs(goal, _proposal(goal), evidence, now=now)
    assert numeric is not None
    # The improving trend projects past the latest trial, shrunk toward no change.
    assert 3000 - 30 < numeric.state["current_value"] < 3100
    probability, transforms = price_from_numeric_inputs(numeric)
    assert probability is not None
    diagnostics = transforms["threshold_diagnostics"]
    expected = NormalDist(
        diagnostics["projected_seconds"], diagnostics["sigma_deadline_seconds"]
    ).cdf(3000)
    assert probability == pytest.approx(expected, abs=1e-9)
    assert probability < 0.995


def test_projected_probability_is_continuous_at_the_target() -> None:
    goal = _goal()
    numeric = build_running_numeric_inputs(
        goal, _proposal(goal), [_evidence("10k_time_seconds", 3100)]
    )
    assert numeric is not None
    below = replace(numeric, state={**numeric.state, "current_value": 2999.0})
    above = replace(numeric, state={**numeric.state, "current_value": 3001.0})
    p_below, _ = price_from_numeric_inputs(below)
    p_above, _ = price_from_numeric_inputs(above)
    assert p_below is not None and p_above is not None
    assert abs(p_below - p_above) < 0.05


def test_five_k_only_records_conversion_path() -> None:
    goal = _goal()
    evidence = [_evidence("5k_time_seconds", 1500, summary="5k time trial")]
    state = aggregate_running_from_evidence(evidence, goal=goal)
    assert len(state.observations) == 1
    assert state.observations[0].conversion_applied is True
    assert state.observations[0].original_distance_km == pytest.approx(5.0)
    numeric = build_running_numeric_inputs(goal, _proposal(goal), evidence)
    assert numeric is not None
    transforms = numeric.state["pricing_transforms"]
    assert transforms["distance_conversion"]["model"] == "riegel"
    assert transforms["running_state"]["converted_count"] == 1


def test_worsening_runs_reduce_probability_vs_improving() -> None:
    goal = _goal(deadline=datetime.now(UTC) + timedelta(days=90))
    now = datetime.now(UTC)
    improving = [
        _evidence("10k_time_seconds", 3300, observed_at=now - timedelta(days=40)),
        _evidence("10k_time_seconds", 3200, observed_at=now - timedelta(days=20)),
        _evidence("10k_time_seconds", 3100, observed_at=now - timedelta(days=5)),
    ]
    worsening = [
        _evidence("10k_time_seconds", 3100, observed_at=now - timedelta(days=40)),
        _evidence("10k_time_seconds", 3200, observed_at=now - timedelta(days=20)),
        _evidence("10k_time_seconds", 3300, observed_at=now - timedelta(days=5)),
    ]
    service = BaselineForecastService(InMemoryBaselineForecastRepository())
    up = service.compute(
        goal,
        _proposal(goal),
        [],
        {},
        [],
        build_running_numeric_inputs(goal, _proposal(goal), improving, now=now),
    )
    down = service.compute(
        goal,
        _proposal(goal),
        [],
        {},
        [],
        build_running_numeric_inputs(goal, _proposal(goal), worsening, now=now),
    )
    assert up.raw_probability is not None and down.raw_probability is not None
    assert up.raw_probability > down.raw_probability


def test_riegel_conversion_is_deterministic() -> None:
    ref = load_running_reference()
    converted = riegel_convert(1500, 5.0, 10.0, ref.riegel_exponent)
    assert converted > 1500
    assert converted == pytest.approx(1500 * (2.0**ref.riegel_exponent))


def test_weekly_mileage_uses_latest_period_not_insert_order() -> None:
    now = datetime.now(UTC)
    evidence = [
        _evidence("weekly_distance_km", 40, unit="km", observed_at=now),
        _evidence("weekly_distance_km", 32, unit="km", observed_at=now - timedelta(days=8)),
    ]
    state = aggregate_running_from_evidence(evidence, goal=_goal())
    assert state.weekly_distance_km == pytest.approx(40)


def test_weekly_mileage_does_not_create_fitness_score() -> None:
    goal = _goal()
    evidence = [
        _evidence("10k_time_seconds", 3200),
        _evidence("weekly_distance_km", 32, unit="km"),
    ]
    state = aggregate_running_from_evidence(evidence, goal=goal)
    assert state.weekly_distance_km == pytest.approx(32)
    numeric = build_running_numeric_inputs(goal, _proposal(goal), evidence)
    assert isinstance(numeric, NumericInputs)
    assert "fitness" not in str(numeric.state).lower()


def test_fit_trend_negative_slope_means_improving() -> None:
    ref = load_running_reference()
    now = datetime.now(UTC)
    observations = aggregate_running_from_evidence(
        [
            _evidence("10k_time_seconds", 3300, observed_at=now - timedelta(days=30)),
            _evidence("10k_time_seconds", 3200, observed_at=now - timedelta(days=15)),
            _evidence("10k_time_seconds", 3100, observed_at=now - timedelta(days=1)),
        ],
        goal=_goal(),
        now=now,
    ).observations
    fit = fit_performance_trend(observations, _goal().deadline, now, ref)
    assert fit.trend_seconds_per_day < 0


def test_inputs_builder_routes_running_goals() -> None:
    goal = _goal()
    evidence = [_evidence("10k_time_seconds", 3200)]
    assert build_numeric_inputs(goal, _proposal(goal), evidence) is not None


def _half_marathon_goal() -> GoalContract:
    return _goal(
        title="Half marathon under 2 hours at an official race by 2027-05-15",
        success_definition={
            "metric": "Finish time at an official half marathon race",
            "operator": "<=",
            "value": 7200,
        },
    )


@pytest.mark.parametrize(
    "title,metric,expected",
    [
        ("Half marathon under 2 hours", "Finish time at an official half marathon race", 21.0975),
        ("Run a marathon under 4 hours", "marathon_time_seconds", 42.195),
        ("Run a 10K in under 50 minutes", "10k_time_seconds", 10.0),
    ],
)
def test_goal_distance_recognizes_race_distances(title: str, metric: str, expected: float) -> None:
    goal = _goal(title=title, success_definition={"metric": metric, "operator": "<=", "value": 1})
    assert goal_distance_km(goal) == pytest.approx(expected)


def test_half_marathon_time_trials_price_at_goal_distance() -> None:
    goal = _half_marathon_goal()
    now = datetime.now(UTC)
    evidence = [
        _evidence("half_marathon_time_seconds", 8280, observed_at=now - timedelta(days=60)),
        _evidence(
            "half marathon finish time (time trial)", 8040, observed_at=now - timedelta(days=30)
        ),
        _evidence(
            "half_marathon_time_seconds",
            7950,
            observed_at=now - timedelta(days=6),
            summary="Half marathon time trial 2:12:30",
        ),
    ]
    state = aggregate_running_from_evidence(evidence, goal=goal, now=now)
    assert len(state.observations) == 3
    assert all(item.distance_km == pytest.approx(21.0975) for item in state.observations)
    assert not any(item.conversion_applied for item in state.observations)
    numeric = build_running_numeric_inputs(goal, _proposal(goal), evidence, now=now)
    assert numeric is not None
    running_state = numeric.state["pricing_transforms"]["running_state"]
    assert running_state["direct_goal_distance_count"] == 3
    assert running_state["goal_distance_km"] == pytest.approx(21.0975)


def test_finish_time_race_labelled_deadline_event_becomes_running_threshold() -> None:
    proposal = GoalArchitectProposal.model_validate(
        {
            "ready_to_commit": True,
            "title": "Run a half marathon in under 2 hours at an official race by 2027-05-15",
            "goal_type": "deadline_event",
            "success_metric": "Finish time of a half marathon at an officially timed race",
            "success_operator": "<=",
            "success_target": "7200",
            "success_unit": "seconds",
            "deadline": "2027-05-15",
            "state_dimensions": ["weekly running volume (km/week)"],
            "primitive_kind": "continuous_threshold",
            "model_family_compatibility": "composed_continuous_threshold",
        }
    )
    labelled = _goal(
        title=proposal.title,
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": proposal.success_metric, "operator": "<=", "value": 7200},
    )
    assert is_timed_race_target(labelled) is True
    goal = proposal_to_contract(proposal)
    assert goal.goal_type == GoalType.THRESHOLD
    assert is_running_goal(goal, proposal) is True
    assert goal.model_requirements["forecast_spec"].get("family") == "threshold_trend"
    now = datetime.now(UTC)
    evidence = [
        _evidence("half_marathon_seconds", 8280, observed_at=now - timedelta(days=60)),
        _evidence("half_marathon_seconds", 7950, observed_at=now - timedelta(days=6)),
    ]
    numeric = build_running_numeric_inputs(goal, proposal, evidence, now=now)
    assert numeric is not None
    running_state = numeric.state["pricing_transforms"]["running_state"]
    assert running_state["goal_distance_km"] == pytest.approx(21.0975)
    state = build_baseline_state(goal, evidence)
    assert state.current_value is not None and state.periods is not None


@pytest.mark.parametrize("weekly_change", [-35.0, 12.0])
def test_what_if_baseline_accepts_any_fitted_training_trend(weekly_change: float) -> None:
    goal = _goal()
    now = datetime.now(UTC)
    evidence = [
        _evidence(
            "10k_time_seconds",
            3200 - weekly_change * (8 - week),
            observed_at=now - timedelta(weeks=8 - week),
        )
        for week in range(0, 8, 2)
    ]
    state = build_baseline_state(goal, evidence)
    flow = next(item for item in state.assumptions if item.id == "flow")
    assert flow.minimum <= flow.value <= flow.maximum
    # The fitted trend keeps its sign and is shrunk toward zero by the slope prior.
    assert 0.6 * abs(weekly_change) < abs(flow.value) < abs(weekly_change)
    assert (flow.value > 0) == (weekly_change > 0)


def test_what_if_baseline_reports_the_goal_unit_for_outcome_values() -> None:
    goal = _goal(model_requirements={"forecast_spec": {"units": "seconds"}})
    now = datetime.now(UTC)
    evidence = [
        _evidence("10k_time_seconds", 3200 - 20 * week, observed_at=now - timedelta(weeks=8 - week))
        for week in range(0, 8, 2)
    ]
    state = build_baseline_state(goal, evidence)
    assert state.priced
    assert state.target_unit == "seconds"
    assert build_baseline_state(_goal(), evidence).target_unit is None


def test_single_trial_carries_prior_trend_uncertainty() -> None:
    goal = _goal()
    now = datetime.now(UTC)
    one = build_running_numeric_inputs(
        goal, _proposal(goal), [_evidence("10k_time_seconds", 3150, observed_at=now)], now=now
    )
    assert one is not None
    assert one.assumptions["trend_projection_uncertainty"] > 0
    probability, _ = price_from_numeric_inputs(one)
    assert probability is not None and 0.0001 < probability < 0.5


def test_race_entry_deadline_event_without_time_target_is_not_running_threshold() -> None:
    goal = _goal(
        title="Register for the city marathon",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": "registered", "operator": "==", "value": 1},
    )
    assert is_timed_race_target(goal) is False
    assert is_running_goal(goal) is False
