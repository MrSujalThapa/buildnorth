from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from personal_markets.behavior.dimensions import build_profile
from personal_markets.behavior.domain import (
    ActionContext,
    BehaviorProfile,
    CommitmentTrial,
    ExecutionEstimate,
)
from personal_markets.behavior.features import context_from_text, trials_from_evidence
from personal_markets.behavior.model import DEFAULT_HALF_LIFE, estimate_execution
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.goals.domain import GoalContract


class BehaviorService:
    def __init__(
        self,
        *,
        half_life_days: float = DEFAULT_HALF_LIFE,
        logistic_coefficients: dict[str, float] | None = None,
    ) -> None:
        self._half_life_days = half_life_days
        self._logistic = logistic_coefficients

    def profile_from_evidence(
        self,
        events: Iterable[NormalizedEvidence],
        goal: GoalContract,
        context: ActionContext | None = None,
        *,
        as_of: datetime | None = None,
        commitment_trials: list[CommitmentTrial] | None = None,
    ) -> BehaviorProfile:
        stamp = as_of or datetime.now(UTC)
        action = context or context_from_text(
            " ".join([goal.title, *goal.state_dimensions]),
            domain=(goal.state_dimensions[0] if goal.state_dimensions else "general"),
        )
        trials = [*trials_from_evidence(events), *(commitment_trials or [])]
        execution = estimate_execution(
            trials,
            action,
            as_of=stamp,
            half_life_days=self._half_life_days,
            logistic_coefficients=self._logistic,
        )
        return build_profile(trials, action, execution, as_of=stamp)

    def estimate(
        self,
        events: Iterable[NormalizedEvidence],
        goal: GoalContract,
        context: ActionContext | None = None,
        *,
        as_of: datetime | None = None,
        commitment_trials: list[CommitmentTrial] | None = None,
    ) -> ExecutionEstimate:
        return self.profile_from_evidence(
            events,
            goal,
            context,
            as_of=as_of,
            commitment_trials=commitment_trials,
        ).execution
