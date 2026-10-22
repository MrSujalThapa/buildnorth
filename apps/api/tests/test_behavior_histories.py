"""Deterministic synthetic histories; never loaded into user or production storage."""

from datetime import UTC, datetime, timedelta

from personal_markets.behavior.domain import ActionContext, CommitmentTrial
from personal_markets.behavior.model import estimate_execution

AS_OF = datetime(2026, 10, 21, tzinfo=UTC)
CONTEXT = ActionContext(domain="fitness", action_type="gym", tokens=["gym"])


def history(outcomes: list[float], *, every_days: int = 7) -> list[CommitmentTrial]:
    return [
        CommitmentTrial(
            trial_id=f"synthetic-{i}",
            domain="fitness",
            action_type="gym",
            outcome=outcome,
            observed_at=AS_OF - timedelta(days=i * every_days),
            session_key=f"synthetic-{i}",
            source="synthetic_test_only",
        )
        for i, outcome in enumerate(outcomes)
    ]


def test_four_year_history_has_more_evidence_than_three_recent_sessions() -> None:
    long = estimate_execution(history([1] * 208), CONTEXT, as_of=AS_OF)
    sparse = estimate_execution(history([1] * 3), CONTEXT, as_of=AS_OF)
    assert long.n_eff > 10 * sparse.n_eff
    assert long.probability > sparse.probability
    assert sparse.usable is False


def test_consistent_inconsistent_and_improving_histories_separate() -> None:
    consistent = estimate_execution(history([1] * 32), CONTEXT, as_of=AS_OF)
    inconsistent = estimate_execution(history([0, 1] * 16), CONTEXT, as_of=AS_OF)
    improving = estimate_execution(history([1] * 12 + [0] * 20), CONTEXT, as_of=AS_OF)
    assert consistent.probability > improving.probability > inconsistent.probability


def test_recent_deterioration_changes_long_term_prediction() -> None:
    stable = estimate_execution(history([1] * 208), CONTEXT, as_of=AS_OF)
    deteriorated = estimate_execution(history([0] * 8 + [1] * 200), CONTEXT, as_of=AS_OF)
    assert deteriorated.probability < stable.probability - 0.05
