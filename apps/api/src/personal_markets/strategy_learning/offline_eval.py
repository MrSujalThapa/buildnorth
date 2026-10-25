"""Reproducible, consent-gated offline strategy-outcome experiment.

Only resolved binary intermediate outcomes from explicit feature/outcome contracts
may enter this experiment. This module never reads the production database.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field
from sklearn.linear_model import LogisticRegression

from personal_markets.evaluation.metrics import (
    brier_score,
    expected_calibration_error,
    log_loss,
)

MODEL_VERSION = "strategy_outcome_logistic_offline_v1"
SUPPORTED_CONTRACTS = {
    "career_interview_30d_v1": ("interviews", "count", 30),
    "education_practice_30d_v1": ("practice_sessions", "count", 30),
}


class PriorOutcome(BaseModel):
    user_id: UUID
    observed_at: datetime
    available_at: datetime
    outcome: int = Field(ge=0, le=1)


class StrategyOutcomeCase(BaseModel):
    user_id: UUID
    goal_family: str
    strategy_key: str
    recommendation_at: datetime
    horizon_at: datetime
    observed_at: datetime
    past_outcomes: list[PriorOutcome] = Field(default_factory=list)
    outcome: int = Field(ge=0, le=1)
    consented: bool = False
    synthetic: bool = False
    metric: str
    unit: str


def partition(user_id: UUID) -> str:
    bucket = int.from_bytes(hashlib.sha256(user_id.bytes).digest()[:8], "big") % 10
    return "train" if bucket < 6 else "validation" if bucket < 8 else "test"


def _features(case: StrategyOutcomeCase, families: list[str], strategies: list[str]) -> list[float]:
    # Only context available at recommendation time; no current/future outcome.
    prior = [
        row
        for row in case.past_outcomes
        if row.user_id == case.user_id
        and row.observed_at < case.recommendation_at
        and row.available_at < case.recommendation_at
    ]
    return [
        float(len(prior)),
        sum(row.outcome for row in prior) / max(1, len(prior)),
        *[float(case.goal_family == family) for family in families],
        *[float(case.strategy_key == strategy) for strategy in strategies],
    ]


def run_offline_experiment(cases: list[StrategyOutcomeCase]) -> dict[str, Any]:
    eligible = []
    for case in cases:
        contract = SUPPORTED_CONTRACTS.get(case.goal_family)
        if contract is None or (case.metric, case.unit) != contract[:2]:
            continue
        if not case.synthetic and not case.consented:
            continue
        if case.observed_at < case.horizon_at or case.recommendation_at >= case.horizon_at:
            continue
        eligible.append(case)
    groups: dict[str, list[StrategyOutcomeCase]] = defaultdict(list)
    for case in eligible:
        groups[partition(case.user_id)].append(case)
    if any(len(groups[name]) < 20 for name in ("train", "validation", "test")):
        return {
            "status": "insufficient_data",
            "n_eligible": len(eligible),
            "partition_counts": {key: len(value) for key, value in groups.items()},
            "model_version": MODEL_VERSION,
        }
    identities = {key: {row.user_id for row in rows} for key, rows in groups.items()}
    if any(
        identities[a] & identities[b]
        for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))
    ):
        raise ValueError("User-level split leaked")
    families = sorted(SUPPORTED_CONTRACTS)
    train, validation, test = (groups[key] for key in ("train", "validation", "test"))
    strategies = sorted({row.strategy_key for row in train})
    x_train = np.asarray([_features(row, families, strategies) for row in train])
    y_train = np.asarray([row.outcome for row in train])
    if len(set(y_train)) < 2:
        return {"status": "insufficient_labels", "n_eligible": len(eligible)}
    candidate = LogisticRegression(max_iter=500, random_state=9)
    candidate.fit(x_train, y_train)
    base_rate = {
        family: float(np.mean([row.outcome for row in train if row.goal_family == family]))
        for family in families
    }
    global_rate = float(np.mean(y_train))

    def score(rows: list[StrategyOutcomeCase]) -> dict[str, Any]:
        labels = [row.outcome for row in rows]
        reference = [base_rate.get(row.goal_family, global_rate) for row in rows]
        informed = candidate.predict_proba(
            np.asarray([_features(row, families, strategies) for row in rows])
        )[:, 1].tolist()

        def metrics(probabilities: list[float]) -> dict[str, float]:
            return {
                "brier": brier_score(labels, probabilities),
                "log_loss": log_loss(labels, probabilities),
                "ece_10": expected_calibration_error(labels, probabilities),
            }

        return {
            "n": len(rows),
            "n_users": len({row.user_id for row in rows}),
            "reference": metrics(reference),
            "candidate": metrics(informed),
        }

    validation_result, test_result = score(validation), score(test)
    improvement = test_result["reference"]["brier"] - test_result["candidate"]["brier"]
    return {
        "status": "evaluated",
        "model_version": MODEL_VERSION,
        "feature_contract": "dated prior outcomes before recommendation; goal family; "
        "strategy types seen in training",
        "outcome_contracts": SUPPORTED_CONTRACTS,
        "split": "sha256(user_id) modulo 10: train 0-5, validation 6-7, test 8-9",
        "n_eligible": len(eligible),
        "n_excluded": len(cases) - len(eligible),
        "train": {"n": len(train), "n_users": len(identities["train"])},
        "validation": validation_result,
        "test": test_result,
        "held_out_brier_improvement": improvement,
        "fixture_brier_better": improvement > 0,
        "production_improvement_supported": False,
        "limitation": "Association only; selection bias and confounding remain. "
        "Synthetic evaluation cannot establish production accuracy.",
    }
