"""Registered mathematical primitives. No LLM. No arbitrary code execution.

Each function returns a probability in (0, 1) or None when the inputs cannot
support a defensible price. Formulas are documented on the functions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from scipy.special import expit
from scipy.stats import nbinom, norm, poisson

COMPILER_VERSION = "composed_v1"
PRIMITIVE_VERSIONS = {
    "deadline_hazard": "1.0.0",
    "funnel": "1.0.0",
    "cumulative_count": "1.0.0",
    "growth": "1.0.0",
    "continuous_threshold": "1.0.0",
    "habit": "1.0.0",
    "dependency_dag": "1.0.0",
    "financial": "1.0.0",
}
REGISTERED_PRIMITIVES = tuple(PRIMITIVE_VERSIONS)
_EPS = 1e-6
# The current measurement already meets the target; residual doubt covers whether it counts.
THRESHOLD_ACHIEVED_PROBABILITY = 0.995
_MAX_DRAWS = 20_000


@dataclass(frozen=True, slots=True)
class PrimitivePrice:
    priced: bool
    probability: float | None
    method: str
    limitations: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    used_parameters: list[dict[str, Any]] = field(default_factory=list)


def _clip(probability: float) -> float:
    return float(min(max(probability, _EPS), 1.0 - _EPS))


def at_numerical_bound(probability: float, *, eps: float = _EPS) -> bool:
    """True when a priced probability sits on the primitive clip floor or ceiling."""
    return probability <= eps or probability >= 1.0 - eps


def _unpriced(
    method: str, reasons: list[str], diagnostics: dict[str, Any] | None = None
) -> PrimitivePrice:
    return PrimitivePrice(
        priced=False,
        probability=None,
        method=method,
        limitations=["NOT_PRICED: " + reason for reason in reasons],
        diagnostics=diagnostics or {},
    )


def _priced(
    probability: float,
    method: str,
    *,
    limitations: list[str] | None = None,
    diagnostics: dict[str, Any] | None = None,
    used_parameters: list[dict[str, Any]] | None = None,
    clip: bool = True,
) -> PrimitivePrice:
    value = _clip(probability) if clip else float(min(max(probability, 0.0), 1.0))
    return PrimitivePrice(
        priced=True,
        probability=value,
        method=method,
        limitations=list(limitations or []),
        diagnostics=diagnostics or {},
        used_parameters=list(used_parameters or []),
    )


def deadline_hazard_probability(logits: np.ndarray) -> float:
    """Discrete-time logistic hazard: P = 1 - ∏_t (1 - σ(ℓ_t))."""
    hazards = expit(np.asarray(logits, dtype=float))
    return float(1.0 - np.prod(1.0 - hazards))


def price_deadline_hazard(logits: list[float] | np.ndarray) -> PrimitivePrice:
    values = np.asarray(logits, dtype=float)
    if values.size == 0 or not np.all(np.isfinite(values)):
        return _unpriced(
            "discrete_time_logistic_hazard", ["hazard logits are missing or non-finite"]
        )
    return _priced(
        deadline_hazard_probability(values),
        "discrete_time_logistic_hazard",
        diagnostics={"periods": int(values.size), "mean_hazard": float(np.mean(expit(values)))},
        used_parameters=[
            {"parameter": "baseline_logits", "estimator": "supplied", "source_kind": "estimated"}
        ],
    )


def funnel_path_probability(conversions: list[float]) -> float | None:
    """Independent stage product π = ∏ p_i. Returns None if any rate is invalid."""
    if not conversions:
        return None
    product = 1.0
    for rate in conversions:
        if rate < 0.0 or rate > 1.0 or not math.isfinite(rate):
            return None
        product *= rate
    return product


def price_funnel(
    *,
    stage_counts: list[int],
    conversions: list[float],
    expected_new_starts: float = 0.0,
    independence: Literal["assumed_independent", "unspecified"] = "unspecified",
) -> PrimitivePrice:
    """Concurrent attempts through a conversion chain.

    For n items at stage s, remaining path π_s = ∏_{i≥s} p_i.
    Under independence, P(at least one success from that stage) = 1 - (1-π_s)^n.
    New starts use the same product. Independence is an explicit assumption.
    """
    if len(stage_counts) != len(conversions) + 1:
        return _unpriced(
            "funnel_conversion",
            ["funnel requires counts at every stage including success and one conversion per edge"],
        )
    if any(count < 0 for count in stage_counts) or expected_new_starts < 0:
        return _unpriced("funnel_conversion", ["stage counts and inflow cannot be negative"])
    limitations: list[str] = []
    if independence != "assumed_independent":
        limitations.append(
            "Stage conversions are treated as independent; "
            "correlated outcomes would lower this probability."
        )
    fail_prob = 1.0
    for index, count in enumerate(stage_counts[:-1]):
        path = funnel_path_probability(conversions[index:])
        if path is None:
            return _unpriced("funnel_conversion", ["conversion rates must be in [0, 1]"])
        if count:
            fail_prob *= (1.0 - path) ** count
    new_path = funnel_path_probability(conversions)
    if new_path is None:
        return _unpriced("funnel_conversion", ["conversion rates must be in [0, 1]"])
    if expected_new_starts > 0:
        # Non-integer inflow uses e^{-λ π} survival of a Poisson number of new attempts.
        fail_prob *= math.exp(-expected_new_starts * new_path)
    already = stage_counts[-1]
    if already > 0:
        return _priced(
            1.0 - _EPS,
            "funnel_conversion",
            limitations=limitations,
            diagnostics={"already_succeeded": already, "path_probability": new_path},
        )
    probability = 1.0 - fail_prob
    return _priced(
        probability,
        "funnel_conversion",
        limitations=limitations,
        diagnostics={
            "path_probability": new_path,
            "stage_counts": list(stage_counts),
            "conversions": list(conversions),
            "expected_new_starts": expected_new_starts,
            "independence": independence,
        },
        used_parameters=[
            {"parameter": "conversions", "estimator": "supplied", "source_kind": "estimated"},
        ],
    )


def price_cumulative_count(
    *,
    current: float,
    target: float,
    rate: float,
    periods: float,
    n_rate_observations: int = 0,
    overdispersion: float | None = None,
    seed: int = 42,
    n_draws: int = 4_000,
) -> PrimitivePrice:
    """Count process toward a threshold.

    Plug-in Poisson: P(N ≥ k) = 1 - F_pois(k-1; λT) with k = target - current.
    Overdispersed: NegativeBinomial with mean μ and var = μ + α μ².
    Rate uncertainty (n≥3): average Poisson survival over λ ~ LogNormal.
    """
    if periods <= 0 or not math.isfinite(periods):
        return _unpriced("cumulative_count", ["evaluation horizon must be positive"])
    if not math.isfinite(current) or not math.isfinite(target):
        return _unpriced("cumulative_count", ["current and target counts must be finite"])
    remaining = math.ceil(target - current)
    if remaining <= 0:
        return _priced(
            1.0 - _EPS,
            "cumulative_count",
            diagnostics={"remaining": 0, "current": current, "target": target},
        )
    if rate < 0 or not math.isfinite(rate):
        return _unpriced("cumulative_count", ["addition rate is missing or invalid"])
    mu = rate * periods
    limitations: list[str] = []
    if overdispersion is not None:
        if overdispersion <= 0:
            return _unpriced("cumulative_count", ["overdispersion must be positive"])
        # nbinom in scipy is number of failures before n successes; mean = n(1-p)/p.
        # var = μ + α μ² ⇒ p = 1 / (1 + α μ), n = 1 / α.
        n_nb = 1.0 / overdispersion
        p = 1.0 / (1.0 + overdispersion * mu)
        probability = float(nbinom.sf(remaining - 1, n_nb, p))
        method = "negative_binomial_count"
        limitations.append("Negative-binomial overdispersion is an estimated process assumption.")
    elif n_rate_observations >= 3 and mu > 0:
        rng = np.random.default_rng(seed)
        se_log = 1.0 / math.sqrt(n_rate_observations)
        draws = rng.lognormal(
            mean=math.log(max(mu, _EPS)),
            sigma=se_log,
            size=min(max(int(n_draws), 200), 20_000),
        )
        probability = float(np.mean(poisson.sf(remaining - 1, draws)))
        method = "poisson_count_rate_uncertainty"
        limitations.append(
            "Rate uncertainty is estimated from the observation count, not a population prior."
        )
    else:
        probability = float(poisson.sf(remaining - 1, mu))
        method = "poisson_count"
        if n_rate_observations < 3:
            limitations.append("Rate treated as known; sparse history understates uncertainty.")
    return _priced(
        probability,
        method,
        limitations=limitations,
        diagnostics={
            "current": current,
            "target": target,
            "remaining": remaining,
            "rate": rate,
            "periods": periods,
            "mu": mu,
            "n_rate_observations": n_rate_observations,
            "overdispersion": overdispersion,
        },
        used_parameters=[
            {
                "parameter": "rate",
                "value": rate,
                "estimator": "mle_or_supplied",
                "source_kind": "estimated",
            }
        ],
    )


def price_growth(
    *,
    current: float,
    target: float,
    periods: float,
    mu: float,
    sigma: float,
    process: Literal["loglinear", "logistic"] = "loglinear",
    saturation: float | None = None,
    direction: Literal["at_least", "at_most"] = "at_least",
    n_observations: int = 0,
) -> PrimitivePrice:
    """Trajectory toward a level.

    Log-linear: log x_T ~ N(log x_0 + μ T, σ² T), P(x_T ≥ target) via lognormal.
    Logistic: x(t) = L / (1 + ((L/x_0)-1) e^{-r t}) with Gaussian residual noise.
    Exponential growth is not assumed forever: a 10× projection without saturation
    is flagged, and logistic is used when L is supplied.
    """
    if current <= 0 or target <= 0 or periods <= 0:
        return _unpriced("growth", ["growth requires positive current, target, and horizon"])
    if sigma < 0 or not math.isfinite(sigma) or not math.isfinite(mu):
        return _unpriced("growth", ["growth drift and volatility must be finite; volatility ≥ 0"])
    limitations: list[str] = []
    if n_observations < 3:
        limitations.append("Growth fitted from fewer than three observations remains exploratory.")
    if process == "logistic" or saturation is not None:
        level = saturation if saturation is not None else max(target * 1.5, current * 2.0)
        if saturation is None:
            limitations.append(
                "Saturation level was not identified; logistic level is a scenario assumption."
            )
            return _unpriced("growth", limitations)
        if current >= level:
            projected = level
        else:
            rate = mu if mu > 0 else 0.0
            projected = level / (1.0 + ((level / current) - 1.0) * math.exp(-rate * periods))
        scale = max(sigma * math.sqrt(max(periods, 1.0)) * max(projected, 1.0), _EPS)
        if direction == "at_least":
            probability = float(1.0 - norm.cdf(target, loc=projected, scale=scale))
        else:
            probability = float(norm.cdf(target, loc=projected, scale=scale))
        method = "logistic_growth"
        diagnostics = {"projected": projected, "saturation": level, "mu": mu, "sigma": sigma}
    else:
        log_mean = math.log(current) + mu * periods
        log_std = max(sigma * math.sqrt(max(periods, 1.0)), _EPS)
        projected = math.exp(log_mean)
        if projected > 10.0 * current:
            limitations.append(
                "Log-linear projection exceeds 10× current level; "
                "exponential growth is not assumed forever."
            )
        z = (math.log(target) - log_mean) / log_std
        probability = float(1.0 - norm.cdf(z)) if direction == "at_least" else float(norm.cdf(z))
        method = "loglinear_growth"
        diagnostics = {
            "log_mean": log_mean,
            "log_std": log_std,
            "projected": projected,
            "mu": mu,
            "sigma": sigma,
        }
    if (direction == "at_least" and current >= target) or (
        direction == "at_most" and current <= target
    ):
        probability = 1.0 - _EPS
    return _priced(
        probability,
        method,
        limitations=limitations,
        diagnostics={**diagnostics, "current": current, "target": target, "periods": periods},
        used_parameters=[
            {
                "parameter": "mu",
                "value": mu,
                "estimator": "ols_or_supplied",
                "source_kind": "estimated",
            },
            {
                "parameter": "sigma",
                "value": sigma,
                "estimator": "residual_std",
                "source_kind": "estimated",
            },
        ],
    )


def price_continuous_threshold(
    *,
    current: float,
    target: float,
    periods: float,
    trend: float,
    noise: float,
    direction: Literal["at_least", "at_most"] = "at_most",
) -> PrimitivePrice:
    """Normal forecast of a measured quantity: x_T ~ N(x_0 + trend·T, σ²)."""
    if not all(math.isfinite(value) for value in (current, target, periods, trend, noise)):
        return _unpriced("continuous_threshold", ["threshold inputs must be finite"])
    if periods <= 0 or noise < 0:
        return _unpriced("continuous_threshold", ["horizon must be positive and noise ≥ 0"])
    projected = current + trend * periods
    sigma = max(noise, _EPS)
    achieved = current <= target if direction == "at_most" else current >= target
    if achieved:
        probability = THRESHOLD_ACHIEVED_PROBABILITY
    elif direction == "at_most":
        probability = float(norm.cdf(target, loc=projected, scale=sigma))
    else:
        probability = float(1.0 - norm.cdf(target, loc=projected, scale=sigma))
    return _priced(
        probability,
        "normal_threshold_trend",
        diagnostics={
            "projected": projected,
            "target": target,
            "sigma": sigma,
            "trend": trend,
            "direction": direction,
        },
        used_parameters=[
            {
                "parameter": "trend",
                "value": trend,
                "estimator": "ols_or_supplied",
                "source_kind": "estimated",
            },
            {
                "parameter": "noise",
                "value": noise,
                "estimator": "residual_std",
                "source_kind": "estimated",
            },
        ],
    )


def price_habit(
    *,
    history: list[bool],
    half_life: float = 28.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    target_rate: float | None = None,
    evaluation_periods: int | None = None,
) -> PrimitivePrice:
    """Recency-weighted Beta-Bernoulli mean, optionally as P(mean ≥ target)."""
    if half_life <= 0 or alpha <= 0 or beta <= 0:
        return _unpriced("habit", ["half-life and Beta priors must be positive"])
    if not history:
        return _unpriced("habit", ["habit pricing needs at least one observed trial"])
    ages = np.arange(len(history) - 1, -1, -1, dtype=float)
    weights = np.exp2(-ages / half_life)
    values = np.asarray(history, dtype=float)
    posterior_a = alpha + float(np.sum(weights * values))
    posterior_b = beta + float(np.sum(weights * (1.0 - values)))
    mean = posterior_a / (posterior_a + posterior_b)
    if target_rate is None:
        probability = mean
        method = "habit_beta_mean"
    else:
        if not 0.0 <= target_rate <= 1.0:
            return _unpriced("habit", ["habit target rate must be in [0, 1]"])
        # Beta posterior predictive that a new trial exceeds the target is the mean
        # compared to the target; multi-period uses binomial with the posterior mean.
        periods = evaluation_periods or 1
        if periods <= 1:
            probability = 1.0 if mean >= target_rate else mean / max(target_rate, _EPS) * 0.5
            # Honest: P(p ≥ target) from Beta CDF.
            from scipy.stats import beta as beta_dist

            probability = float(1.0 - beta_dist.cdf(target_rate, posterior_a, posterior_b))
        else:
            from scipy.stats import beta as beta_dist

            probability = float(1.0 - beta_dist.cdf(target_rate, posterior_a, posterior_b))
        method = "habit_beta_threshold"
    return _priced(
        probability,
        method,
        diagnostics={
            "mean": mean,
            "strength": posterior_a + posterior_b,
            "trials": len(history),
            "target_rate": target_rate,
        },
        used_parameters=[
            {
                "parameter": "prior_alpha",
                "value": alpha,
                "estimator": "supplied",
                "source_kind": "prior",
            },
            {
                "parameter": "prior_beta",
                "value": beta,
                "estimator": "supplied",
                "source_kind": "prior",
            },
        ],
    )


def price_dependency_dag(
    *,
    durations_mean: list[float],
    durations_std: list[float],
    horizon: float,
    prerequisites: list[list[int]] | None = None,
    success_probabilities: list[float] | None = None,
    correlation: Literal["independent", "shared_factor", "unspecified"] = "unspecified",
    n_draws: int = 4_000,
    seed: int = 42,
) -> PrimitivePrice:
    """P(all milestones complete by horizon) via Monte Carlo on durations.

    Sequential AND of durations uses a critical-path max over predecessors plus
    own duration. Success flags, when present, are applied after timing.
    Independent multiplication of success probabilities alone is refused.
    """
    n_nodes = len(durations_mean)
    if n_nodes == 0 or len(durations_std) != n_nodes:
        return _unpriced("dependency_dag", ["each DAG node needs a duration mean and std"])
    if any(
        mean <= 0 or std < 0 or not math.isfinite(mean) or not math.isfinite(std)
        for mean, std in zip(durations_mean, durations_std, strict=True)
    ):
        return _unpriced("dependency_dag", ["duration means must be positive and stds ≥ 0"])
    if horizon <= 0:
        return _unpriced("dependency_dag", ["DAG horizon must be positive"])
    if success_probabilities is not None:
        if len(success_probabilities) != n_nodes:
            return _unpriced("dependency_dag", ["success probabilities must match node count"])
        if any(not 0.0 <= p <= 1.0 for p in success_probabilities):
            return _unpriced("dependency_dag", ["success probabilities must be in [0, 1]"])
        if all(mean <= 1e-9 for mean in durations_mean) and correlation == "unspecified":
            return _unpriced(
                "dependency_dag",
                [
                    "Refusing to multiply milestone probabilities without a "
                    "duration or dependence model."
                ],
            )
    edges = prerequisites or [[] for _ in range(n_nodes)]
    if len(edges) != n_nodes:
        return _unpriced("dependency_dag", ["prerequisite lists must match node count"])
    draws = min(max(n_draws, 200), _MAX_DRAWS)
    rng = np.random.default_rng(seed)
    # Lognormal durations parameterized by mean/std on the original scale.
    means = np.asarray(durations_mean, dtype=float)
    stds = np.asarray(durations_std, dtype=float)
    variance = stds**2
    sigma = np.sqrt(np.log1p(variance / np.maximum(means**2, _EPS)))
    mu = np.log(np.maximum(means, _EPS)) - 0.5 * sigma**2
    shared = rng.standard_normal(draws) if correlation == "shared_factor" else None
    if correlation == "unspecified":
        limitations = ["Duration draws are treated as independent; shared shocks are unspecified."]
    elif correlation == "shared_factor":
        limitations = ["A shared Gaussian factor correlates milestone durations."]
    else:
        limitations = ["Milestone durations are modeled as independent."]
    success_flags = np.ones((draws, n_nodes))
    if success_probabilities is not None:
        if correlation == "shared_factor" and shared is not None:
            # Gaussian copula: correlated Bernoulli via the same factor.
            from scipy.stats import norm as gauss

            latent = 0.6 * shared[:, None] + 0.8 * rng.standard_normal((draws, n_nodes))
            thresholds = gauss.ppf(1.0 - np.asarray(success_probabilities))
            success_flags = (latent > thresholds).astype(float)
        else:
            success_flags = (
                rng.random((draws, n_nodes)) < np.asarray(success_probabilities)
            ).astype(float)
    idiosyncratic = rng.standard_normal((draws, n_nodes))
    z = 0.5 * shared[:, None] + 0.866 * idiosyncratic if shared is not None else idiosyncratic
    sampled = np.exp(mu + sigma * z)
    finish = np.zeros((draws, n_nodes))
    for index in range(n_nodes):
        preds = edges[index]
        start = np.max(finish[:, preds], axis=1) if preds else np.zeros(draws)
        finish[:, index] = start + sampled[:, index]
    terminal = np.max(finish, axis=1)
    complete = (terminal <= horizon) & (success_flags.min(axis=1) > 0.5)
    from personal_markets.forecasting.monte_carlo import monte_carlo_frequency

    frequency = monte_carlo_frequency(complete.astype(float))
    limitations.extend(frequency.limitations)
    return _priced(
        frequency.p_hat,
        "dependency_dag_mc",
        limitations=limitations,
        diagnostics=frequency.diagnostics(
            {
                "seed": seed,
                "horizon": horizon,
                "mean_terminal": float(np.mean(terminal)),
                "correlation": correlation,
            }
        ),
        used_parameters=[
            {"parameter": "durations_mean", "estimator": "supplied", "source_kind": "estimated"},
        ],
        clip=False,
    )


def waiting_time_poisson(remaining: int, rate: float, rng: np.random.Generator) -> float:
    """Erlang waiting time for `remaining` events at rate `rate` per period."""
    if remaining <= 0:
        return 0.0
    if rate <= 0:
        return math.inf
    return float(rng.gamma(shape=remaining, scale=1.0 / rate))


def waiting_time_loglinear(current: float, target: float, mu: float) -> float:
    """Deterministic time for log-linear growth to hit target. inf if μ≤0 and below target."""
    if current >= target:
        return 0.0
    if mu <= 0 or current <= 0:
        return math.inf
    return math.log(target / current) / mu
