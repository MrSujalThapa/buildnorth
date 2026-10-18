"""Binomial Monte Carlo frequency reporting. Not a theoretical probability floor."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

_Z95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class MonteCarloFrequency:
    hits: int
    draws: int
    p_hat: float
    se: float
    ci95_low: float
    ci95_high: float
    converged: bool
    limitations: list[str] = field(default_factory=list)

    def diagnostics(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "estimator": "monte_carlo_frequency",
            "hits": self.hits,
            "n_draws": self.draws,
            "p_hat": self.p_hat,
            "mc_error": self.se,
            "ci95": [self.ci95_low, self.ci95_high],
            "theoretical_floor": None,
            "converged": self.converged,
        }
        if extra:
            payload.update(extra)
        return payload


def monte_carlo_frequency(success: np.ndarray) -> MonteCarloFrequency:
    """Wilson interval and sampling error for Bernoulli draws.

    The point estimate is the observed frequency. Zero hits is 0, not 1e-6.
    """
    draws = int(np.asarray(success).size)
    hits = int(np.asarray(success).sum())
    if draws <= 0:
        return MonteCarloFrequency(
            hits=0,
            draws=0,
            p_hat=0.0,
            se=1.0,
            ci95_low=0.0,
            ci95_high=1.0,
            converged=False,
            limitations=["Monte Carlo ran zero draws."],
        )
    p_hat = hits / draws
    se = math.sqrt(p_hat * (1.0 - p_hat) / draws)
    low, high = _wilson(hits, draws)
    limitations = [
        f"Monte Carlo frequency {hits}/{draws}; binomial SE ≈ {se:.4g}; "
        f"95% Wilson interval [{low:.4g}, {high:.4g}].",
        "This is an empirical simulation frequency, not a 1e-6 theoretical floor.",
    ]
    if hits == 0:
        limitations.append(
            f"Zero successes in {draws} draws. Point estimate is 0. "
            f"Approximate 95% upper bound is {high:.4g}."
        )
    elif hits == draws:
        limitations.append(
            f"All {draws} draws succeeded. Point estimate is 1. "
            f"Approximate 95% lower bound is {low:.4g}."
        )
    relative = se / p_hat if p_hat > 0 else se
    converged = se <= 0.02 or (hits in {0, draws} and draws >= 1_000)
    if not converged:
        limitations.append(
            "Sampling error is large relative to the estimate; treat the figure as exploratory."
        )
    elif relative > 0.5 and 0 < hits < draws:
        limitations.append(
            "Relative Monte Carlo error exceeds 50%; rare-event resolution is limited."
        )
        converged = False
    return MonteCarloFrequency(
        hits=hits,
        draws=draws,
        p_hat=p_hat,
        se=se,
        ci95_low=low,
        ci95_high=high,
        converged=converged,
        limitations=limitations,
    )


def _wilson(hits: int, draws: int, z: float = _Z95) -> tuple[float, float]:
    n = float(draws)
    p = hits / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    spread = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    return max(0.0, center - spread), min(1.0, center + spread)
