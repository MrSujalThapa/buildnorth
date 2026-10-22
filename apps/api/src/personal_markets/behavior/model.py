from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime

import numpy as np

from personal_markets.behavior.domain import (
    ActionContext,
    CommitmentTrial,
    ExecutionEstimate,
    HierarchicalPosterior,
)
from personal_markets.behavior.tokenize import overlap_score
from personal_markets.forecasting.decay import ExponentialDecay

ESTIMATOR_VERSION = "behavior_hierarchical_beta_v2_dual_horizon"
PRIOR_ALPHA = 2.0
PRIOR_BETA = 2.0
K_DOMAIN = 8.0
K_ACTION = 6.0
MIN_N_EFF = 4.0
HALF_LIFE_CANDIDATES = (7.0, 14.0, 21.0, 28.0, 42.0)
DEFAULT_HALF_LIFE = 21.0
LONG_BASELINE_HALF_LIFE_DAYS = 365.0
LONG_BASELINE_WEIGHT = 0.5

# Fitted later on the frozen train split; defaults are weakly regularized.
DEFAULT_LOGISTIC = {
    "intercept": 0.0,
    "logit_theta": 1.0,
    "log_commitment": -0.15,
    "momentum": 0.35,
    "overcommit": -0.45,
    "recovery": 0.20,
}


def recency_weights(ages_days: np.ndarray, half_life_days: float) -> np.ndarray:
    ages = ages_days.astype(np.float64)
    recent = ExponentialDecay(half_life_days).weights(ages)
    baseline = ExponentialDecay(LONG_BASELINE_HALF_LIFE_DAYS).weights(ages)
    return (1.0 - LONG_BASELINE_WEIGHT) * recent + LONG_BASELINE_WEIGHT * baseline


def beta_posterior(
    outcomes: np.ndarray,
    weights: np.ndarray,
    *,
    alpha0: float = PRIOR_ALPHA,
    beta0: float = PRIOR_BETA,
) -> HierarchicalPosterior:
    successes = float(np.sum(weights * outcomes))
    failures = float(np.sum(weights * (1.0 - outcomes)))
    alpha = alpha0 + successes
    beta = beta0 + failures
    n_eff = successes + failures
    return HierarchicalPosterior(
        mean=alpha / (alpha + beta),
        n_eff=n_eff,
        alpha=alpha,
        beta=beta,
        half_life_days=0.0,
        scope="custom",
    )


def _ages(trials: list[CommitmentTrial], as_of: datetime) -> np.ndarray:
    ages = np.array(
        [max(0.0, (as_of - item.observed_at).total_seconds() / 86400) for item in trials],
        dtype=float,
    )
    return ages


def _mask(trials: list[CommitmentTrial], predicate) -> np.ndarray:
    return np.array([bool(predicate(item)) for item in trials], dtype=bool)


def hierarchical_posteriors(
    trials: list[CommitmentTrial],
    context: ActionContext,
    *,
    as_of: datetime,
    half_life_days: float = DEFAULT_HALF_LIFE,
) -> dict[str, HierarchicalPosterior]:
    if not trials:
        empty = HierarchicalPosterior(
            mean=PRIOR_ALPHA / (PRIOR_ALPHA + PRIOR_BETA),
            n_eff=0.0,
            alpha=PRIOR_ALPHA,
            beta=PRIOR_BETA,
            half_life_days=half_life_days,
            scope="empty",
        )
        return {"global": empty, "domain": empty, "action": empty}

    outcomes = np.array([item.outcome for item in trials], dtype=float)
    ages = _ages(trials, as_of)
    weights = recency_weights(ages, half_life_days)
    global_post = beta_posterior(outcomes, weights).model_copy(
        update={"half_life_days": half_life_days, "scope": "global"}
    )

    domain_mask = _mask(
        trials,
        lambda item: (
            item.domain == context.domain or overlap_score(item.tokens, [context.domain]) > 0.2
        ),
    )
    if not np.any(domain_mask):
        domain_mask = np.ones(len(trials), dtype=bool)
    domain_raw = beta_posterior(outcomes[domain_mask], weights[domain_mask])
    lambda_d = domain_raw.n_eff / (domain_raw.n_eff + K_DOMAIN)
    domain_mean = lambda_d * domain_raw.mean + (1.0 - lambda_d) * global_post.mean
    domain_post = domain_raw.model_copy(
        update={"mean": domain_mean, "half_life_days": half_life_days, "scope": "domain"}
    )

    action_mask = _mask(
        trials,
        lambda item: (
            item.action_type == context.action_type
            or overlap_score(item.tokens, context.tokens, item.action_type, context.action_type)
            >= 0.12
        ),
    )
    if not np.any(action_mask):
        action_post = domain_post.model_copy(update={"scope": "action", "n_eff": 0.0})
        return {"global": global_post, "domain": domain_post, "action": action_post}

    action_raw = beta_posterior(outcomes[action_mask], weights[action_mask])
    lambda_a = action_raw.n_eff / (action_raw.n_eff + K_ACTION)
    action_mean = lambda_a * action_raw.mean + (1.0 - lambda_a) * domain_mean
    action_post = action_raw.model_copy(
        update={"mean": action_mean, "half_life_days": half_life_days, "scope": "action"}
    )
    return {"global": global_post, "domain": domain_post, "action": action_post}


def feature_vector(
    trials: list[CommitmentTrial], context: ActionContext, as_of: datetime
) -> dict[str, float]:
    if not trials:
        return {
            "n_raw": 0.0,
            "recent_rate": 0.5,
            "longrun_rate": 0.5,
            "momentum": 0.0,
            "overcommit": 0.0,
            "recovery": 0.5,
            "realism": 1.0,
            "variance": 0.25,
            "burstiness": 0.0,
            "mean_delay": 0.0,
            "relevance": 0.0,
        }
    outcomes = np.array([item.outcome for item in trials], dtype=float)
    ages = _ages(trials, as_of)
    recent = ages <= 28
    prior = ages > 28
    recent_rate = float(np.mean(outcomes[recent])) if np.any(recent) else float(np.mean(outcomes))
    longrun_rate = float(np.mean(outcomes[prior])) if np.any(prior) else float(np.mean(outcomes))
    ratios = []
    overcommits = 0
    delays = []
    for item in trials:
        if item.planned_amount and item.planned_amount > 0 and item.realized_amount is not None:
            ratios.append(min(2.0, item.realized_amount / item.planned_amount))
            if item.planned_amount > 1.25 * max(item.realized_amount, 1e-6) and item.outcome < 1:
                overcommits += 1
        if item.delay_days is not None:
            delays.append(item.delay_days)
    realism = float(np.median(ratios)) if ratios else 1.0
    recovery = _recovery_rate(trials)
    stamps = sorted(item.observed_at for item in trials)
    gaps = np.array(
        [
            (later - earlier).total_seconds() / 86400
            for earlier, later in zip(stamps, stamps[1:], strict=False)
        ],
        dtype=float,
    )
    if gaps.size:
        mu = float(np.mean(gaps))
        sigma = float(np.std(gaps))
        burstiness = (sigma - mu) / (sigma + mu) if (sigma + mu) > 0 else 0.0
    else:
        burstiness = 0.0
    relevance = float(
        np.mean(
            [
                overlap_score(item.tokens, context.tokens, item.action_type, context.action_type)
                for item in trials
            ]
        )
    )
    return {
        "n_raw": float(len(trials)),
        "recent_rate": recent_rate,
        "longrun_rate": longrun_rate,
        "momentum": recent_rate - longrun_rate,
        "overcommit": overcommits / max(len(trials), 1),
        "recovery": recovery,
        "realism": max(0.0, min(1.0, realism)),
        "variance": float(np.var(outcomes)),
        "burstiness": float(burstiness),
        "mean_delay": float(np.mean(delays)) if delays else 0.0,
        "relevance": relevance,
    }


def _recovery_rate(trials: list[CommitmentTrial], horizon_days: float = 7.0) -> float:
    ordered = sorted(trials, key=lambda item: item.observed_at)
    resumes = 0
    misses = 0
    for index, item in enumerate(ordered):
        if item.outcome >= 0.5:
            continue
        misses += 1
        for later in ordered[index + 1 :]:
            gap = (later.observed_at - item.observed_at).total_seconds() / 86400
            if gap > horizon_days:
                break
            if later.outcome >= 0.5:
                resumes += 1
                break
    if misses == 0:
        return 0.5
    return resumes / misses


def logistic_execution(
    theta: float, features: dict[str, float], coefficients: dict[str, float] | None = None
) -> float:
    coef = coefficients or DEFAULT_LOGISTIC
    theta = min(1.0 - 1e-6, max(1e-6, theta))
    amount = max(features.get("planned_amount", 0.0), 0.0)
    logit = (
        coef["intercept"]
        + coef["logit_theta"] * math.log(theta / (1.0 - theta))
        + coef["log_commitment"] * math.log1p(amount)
        + coef["momentum"] * features.get("momentum", 0.0)
        + coef["overcommit"] * features.get("overcommit", 0.0)
        + coef["recovery"] * (features.get("recovery", 0.5) - 0.5)
    )
    return 1.0 / (1.0 + math.exp(-logit))


def credible_interval(alpha: float, beta: float, q: float = 0.10) -> tuple[float, float]:
    # Normal approximation to Beta is enough for UI ranges; clamps to [0, 1].
    mean = alpha / (alpha + beta)
    variance = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1))
    width = 1.28155 * math.sqrt(max(variance, 1e-9))
    return (max(0.0, mean - width), min(1.0, mean + width))


def estimate_execution(
    trials: list[CommitmentTrial],
    context: ActionContext,
    *,
    as_of: datetime,
    half_life_days: float = DEFAULT_HALF_LIFE,
    logistic_coefficients: dict[str, float] | None = None,
    allow_logistic: bool = False,
) -> ExecutionEstimate:
    posts = hierarchical_posteriors(trials, context, as_of=as_of, half_life_days=half_life_days)
    action = posts["action"]
    features = feature_vector(trials, context, as_of)
    features["planned_amount"] = float(context.planned_amount or 0.0)
    notes: list[str] = []
    usable = action.n_eff >= MIN_N_EFF or posts["global"].n_eff >= MIN_N_EFF
    if not usable:
        notes.append("Limited evidence; shrinking to the weakly informative prior.")
        probability = posts["global"].mean
        source: str = "PRIOR"
        confidence = "insufficient"
    else:
        probability = action.mean
        source = "FITTED"
        if allow_logistic and action.n_eff >= MIN_N_EFF:
            probability = logistic_execution(action.mean, features, logistic_coefficients)
        if action.n_eff >= 16:
            confidence = "high"
        elif action.n_eff >= 8:
            confidence = "medium"
        else:
            confidence = "low"
            notes.append("Sparse action-specific history; domain/global shrinkage is material.")
    low, high = credible_interval(action.alpha, action.beta)
    return ExecutionEstimate(
        probability=float(min(1.0, max(0.0, probability))),
        interval=(low, high),
        n_eff=action.n_eff,
        n_raw=len(trials),
        confidence=confidence,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        half_life_days=half_life_days,
        global_mean=posts["global"].mean,
        domain_mean=posts["domain"].mean,
        action_mean=action.mean,
        usable=usable,
        notes=notes,
        features=features,
    )


def select_half_life(
    train: list[tuple[list[CommitmentTrial], ActionContext, float, datetime]],
    candidates: Iterable[float] = HALF_LIFE_CANDIDATES,
) -> float:
    """Pick H by held-in Brier on past→next trial folds."""

    best_h = DEFAULT_HALF_LIFE
    best_score = float("inf")
    for half_life in candidates:
        errors: list[float] = []
        for history, context, label, as_of in train:
            estimate = estimate_execution(
                history, context, as_of=as_of, half_life_days=half_life, allow_logistic=False
            )
            errors.append((estimate.probability - label) ** 2)
        score = float(np.mean(errors)) if errors else float("inf")
        if score < best_score:
            best_score = score
            best_h = float(half_life)
    return best_h


def fit_logistic(
    rows: list[tuple[list[CommitmentTrial], ActionContext, float, datetime]],
    half_life_days: float,
) -> dict[str, float]:
    """One-pass weighted least-squares on logit residuals; falls back to defaults."""

    xs: list[list[float]] = []
    ys: list[float] = []
    for history, context, label, as_of in rows:
        posts = hierarchical_posteriors(
            history, context, as_of=as_of, half_life_days=half_life_days
        )
        features = feature_vector(history, context, as_of)
        features["planned_amount"] = float(context.planned_amount or 0.0)
        theta = min(1.0 - 1e-6, max(1e-6, posts["action"].mean))
        y = min(1.0 - 1e-6, max(1e-6, label))
        xs.append(
            [
                1.0,
                math.log(theta / (1.0 - theta)),
                math.log1p(features["planned_amount"]),
                features["momentum"],
                features["overcommit"],
                features["recovery"] - 0.5,
            ]
        )
        ys.append(math.log(y / (1.0 - y)))
    if len(xs) < 12:
        return dict(DEFAULT_LOGISTIC)
    matrix = np.asarray(xs, dtype=float)
    target = np.asarray(ys, dtype=float)
    ridge = 0.5 * np.eye(matrix.shape[1])
    try:
        coef = np.linalg.solve(matrix.T @ matrix + ridge, matrix.T @ target)
    except np.linalg.LinAlgError:
        return dict(DEFAULT_LOGISTIC)
    return {
        "intercept": float(coef[0]),
        "logit_theta": float(coef[1]),
        "log_commitment": float(coef[2]),
        "momentum": float(coef[3]),
        "overcommit": float(coef[4]),
        "recovery": float(coef[5]),
    }
