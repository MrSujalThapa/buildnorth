from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from personal_markets.strategy_learning.offline_eval import (
    PriorOutcome,
    StrategyOutcomeCase,
    partition,
    run_offline_experiment,
)


def test_evaluation_excludes_unconsented_and_unsupported_cases() -> None:
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    cases = [
        StrategyOutcomeCase(
            user_id=uuid5(NAMESPACE_URL, str(index)),
            goal_family="career_interview_30d_v1",
            strategy_key="outreach",
            recommendation_at=stamp,
            horizon_at=stamp + timedelta(days=30),
            observed_at=stamp + timedelta(days=31),
            outcome=index % 2,
            metric="interviews",
            unit="count",
        )
        for index in range(30)
    ]
    result = run_offline_experiment(cases)
    assert result["status"] == "insufficient_data"
    assert result["n_eligible"] == 0
    unsupported = cases[0].model_copy(
        update={"goal_family": "fitness_without_outcome_contract", "synthetic": True}
    )
    assert run_offline_experiment([unsupported])["n_eligible"] == 0


def test_future_history_is_excluded_from_features() -> None:
    from personal_markets.strategy_learning.offline_eval import _features

    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    baseline = StrategyOutcomeCase(
        user_id=uuid5(NAMESPACE_URL, "future-test"),
        goal_family="career_interview_30d_v1",
        strategy_key="outreach",
        recommendation_at=stamp,
        horizon_at=stamp + timedelta(days=30),
        observed_at=stamp + timedelta(days=31),
        outcome=1,
        metric="interviews",
        unit="count",
        synthetic=True,
    )
    future = baseline.model_copy(
        update={
            "past_outcomes": [
                PriorOutcome(
                    user_id=baseline.user_id,
                    observed_at=stamp + timedelta(days=2),
                    available_at=stamp + timedelta(days=2),
                    outcome=1,
                )
            ]
        }
    )
    assert _features(baseline, ["career_interview_30d_v1"], ["outreach"]) == _features(
        future, ["career_interview_30d_v1"], ["outreach"]
    )
    imported_later = baseline.model_copy(
        update={
            "past_outcomes": [
                PriorOutcome(
                    user_id=baseline.user_id,
                    observed_at=stamp - timedelta(days=2),
                    available_at=stamp + timedelta(days=1),
                    outcome=1,
                )
            ]
        }
    )
    other_user = baseline.model_copy(
        update={
            "past_outcomes": [
                PriorOutcome(
                    user_id=uuid5(NAMESPACE_URL, "different-user"),
                    observed_at=stamp - timedelta(days=2),
                    available_at=stamp - timedelta(days=1),
                    outcome=1,
                )
            ]
        }
    )
    for leaked in (imported_later, other_user):
        assert _features(baseline, ["career_interview_30d_v1"], ["outreach"]) == _features(
            leaked, ["career_interview_30d_v1"], ["outreach"]
        )


def test_fixed_synthetic_evaluation_is_reproducible_and_user_disjoint() -> None:
    from personal_markets.strategy_learning.synthetic_fixture import synthetic_cases

    cases = synthetic_cases()
    assert run_offline_experiment(cases) == run_offline_experiment(cases)
    partitions = {
        name: {row.user_id for row in cases if partition(row.user_id) == name}
        for name in ("train", "validation", "test")
    }
    assert not partitions["train"] & partitions["test"]
    result = run_offline_experiment(cases)
    assert result["status"] == "evaluated"
    assert result["test"]["n"] >= 20
