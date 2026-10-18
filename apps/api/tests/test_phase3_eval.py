"""Synthetic evaluation for the generic engine. Not empirical calibration."""

import numpy as np
import pytest
from scipy.stats import poisson

from personal_markets.forecasting.monte_carlo import monte_carlo_frequency
from personal_markets.forecasting.primitives import (
    price_cumulative_count,
    price_dependency_dag,
    price_growth,
)


def test_parameter_recovery_poisson_rate() -> None:
    rng = np.random.default_rng(0)
    true_rate = 2.0
    weeks = np.arange(1, 13)
    increments = rng.poisson(true_rate, size=len(weeks))
    recovered = float(increments.sum() / len(weeks))
    assert abs(recovered - true_rate) < 1.0


def test_brier_on_simulated_poisson_outcomes() -> None:
    rng = np.random.default_rng(1)
    current, target, rate, periods = 0.0, 10.0, 1.5, 8.0
    forecast = price_cumulative_count(current=current, target=target, rate=rate, periods=periods)
    assert forecast.probability is not None
    remaining = int(target - current)
    outcomes = rng.poisson(rate * periods, size=2000) >= remaining
    brier = float(np.mean((forecast.probability - outcomes.astype(float)) ** 2))
    naive = float(np.mean((0.5 - outcomes.astype(float)) ** 2))
    assert brier < naive


def test_growth_monotonic_in_drift() -> None:
    low = price_growth(current=100, target=200, periods=12, mu=0.02, sigma=0.04)
    high = price_growth(current=100, target=200, periods=12, mu=0.08, sigma=0.04)
    assert low.probability is not None and high.probability is not None
    assert high.probability > low.probability


def test_analytical_poisson_matches_library() -> None:
    mu = 12.0
    k = 10
    priced = price_cumulative_count(current=0, target=k, rate=mu, periods=1, n_rate_observations=1)
    assert priced.probability == poisson.sf(k - 1, mu)


def test_zero_success_mc_is_zero_not_one_e_minus_six() -> None:
    result = price_dependency_dag(
        durations_mean=[80.0, 80.0],
        durations_std=[0.01, 0.01],
        horizon=1.0,
        prerequisites=[[], [0]],
        correlation="independent",
        n_draws=2_000,
        seed=3,
    )
    assert result.priced
    assert result.probability == 0.0
    assert result.diagnostics["hits"] == 0
    assert result.diagnostics["theoretical_floor"] is None
    assert result.diagnostics["ci95"][1] > 0
    assert any("empirical simulation frequency" in item for item in result.limitations)


def test_mc_frequency_reports_sampling_error_and_seed_stability() -> None:
    rng = np.random.default_rng(11)
    draws = rng.random(4_000) < 0.2
    first = monte_carlo_frequency(draws)
    second = monte_carlo_frequency(draws)
    assert first.p_hat == second.p_hat
    assert first.se == pytest.approx((first.p_hat * (1.0 - first.p_hat) / 4_000) ** 0.5)
    assert first.ci95_low < first.p_hat < first.ci95_high
    assert first.converged is True


def test_rare_event_interval_covers_one_over_n() -> None:
    success = np.zeros(4_000)
    success[0] = 1.0
    frequency = monte_carlo_frequency(success)
    assert frequency.hits == 1
    assert frequency.p_hat == pytest.approx(1 / 4_000)
    assert frequency.ci95_low <= 1 / 4_000 <= frequency.ci95_high
    assert frequency.converged is False
