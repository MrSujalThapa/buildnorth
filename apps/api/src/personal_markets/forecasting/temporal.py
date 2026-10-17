from dataclasses import dataclass

import numpy as np

from personal_markets.forecasting.decay import ExponentialDecay


@dataclass(frozen=True, slots=True)
class TemporalSummary:
    exponentially_weighted_mean: float
    recent_mean: float
    long_run_mean: float
    recent_minus_long_run: float
    negative_streak: int


def summarize_trajectory(
    values: list[float], ages_days: list[float], *, half_life_days: float, recent_days: float
) -> TemporalSummary:
    if not values or len(values) != len(ages_days):
        raise ValueError("values and ages must be non-empty and aligned")
    value_array = np.asarray(values, dtype=float)
    age_array = np.asarray(ages_days, dtype=float)
    weights = ExponentialDecay(half_life_days).weights(age_array)
    recent = value_array[age_array <= recent_days]
    negative_streak = 0
    for value in value_array[np.argsort(age_array)]:
        if value < 0:
            negative_streak += 1
        else:
            break
    long_run = float(np.mean(value_array))
    recent_mean = float(np.mean(recent)) if len(recent) else 0.0
    return TemporalSummary(
        exponentially_weighted_mean=float(np.average(value_array, weights=weights)),
        recent_mean=recent_mean,
        long_run_mean=long_run,
        recent_minus_long_run=recent_mean - long_run,
        negative_streak=negative_streak,
    )


def percentage_point_change(before: float, after: float) -> float:
    if not 0 <= before <= 1 or not 0 <= after <= 1:
        raise ValueError("probabilities must be in [0, 1]")
    return (after - before) * 100
