"""Isolated synthetic cases for evaluator checks; never loaded into accounts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from personal_markets.strategy_learning.offline_eval import PriorOutcome, StrategyOutcomeCase

SEED = 20261025


def synthetic_cases() -> list[StrategyOutcomeCase]:
    rng = np.random.default_rng(SEED)
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    cases = []
    for index in range(400):
        user = uuid5(NAMESPACE_URL, f"pass9b-synthetic-person-{index}")
        family = "career_interview_30d_v1" if index % 2 else "education_practice_30d_v1"
        metric = "interviews" if index % 2 else "practice_sessions"
        strategy = "targeted" if index % 3 == 0 else "broad"
        past = [
            int(rng.random() < (0.65 if strategy == "targeted" else 0.25)) for _ in range(index % 5)
        ]
        when = origin + timedelta(days=index)
        history = [
            PriorOutcome(
                user_id=user,
                observed_at=when - timedelta(days=30 * (j + 1)),
                available_at=when - timedelta(days=30 * (j + 1)),
                outcome=value,
            )
            for j, value in enumerate(past)
        ]
        rate = 0.20 + 0.30 * (strategy == "targeted") + 0.12 * (sum(past) / max(1, len(past)))
        label = int(rng.random() < rate)
        cases.append(
            StrategyOutcomeCase(
                user_id=user,
                goal_family=family,
                strategy_key=strategy,
                recommendation_at=when,
                horizon_at=when + timedelta(days=30),
                observed_at=when + timedelta(days=31),
                past_outcomes=history,
                outcome=label,
                synthetic=True,
                metric=metric,
                unit="count",
            )
        )
    return cases
