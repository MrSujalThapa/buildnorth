from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.inputs_builder import build_numeric_inputs
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.running import (
    aggregate_running_from_evidence,
    build_running_numeric_inputs,
    fit_performance_trend,
    is_running_goal,
    load_running_reference,
    riegel_convert,
)
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.ports import GoalArchitectProposal


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
