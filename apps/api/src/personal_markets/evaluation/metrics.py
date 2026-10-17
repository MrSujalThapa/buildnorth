import math
from dataclasses import dataclass

import numpy as np

from personal_markets.evaluation.contracts import EvaluationCase, ForecastResult


def _validate_pairs(outcomes: list[int], probabilities: list[float]) -> None:
    if not outcomes or len(outcomes) != len(probabilities):
        raise ValueError("outcomes and probabilities must be non-empty and equal length")
    if any(outcome not in (0, 1) for outcome in outcomes):
        raise ValueError("outcomes must be binary")
    if any(probability < 0 or probability > 1 for probability in probabilities):
        raise ValueError("probabilities must be in [0, 1]")


def brier_score(outcomes: list[int], probabilities: list[float]) -> float:
    _validate_pairs(outcomes, probabilities)
    return sum(
        (probability - outcome) ** 2
        for outcome, probability in zip(outcomes, probabilities, strict=True)
    ) / len(outcomes)


def log_loss(outcomes: list[int], probabilities: list[float], epsilon: float = 1e-15) -> float:
    _validate_pairs(outcomes, probabilities)
    clipped = [min(max(probability, epsilon), 1 - epsilon) for probability in probabilities]
    return -sum(
        outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability)
        for outcome, probability in zip(outcomes, clipped, strict=True)
    ) / len(outcomes)


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_probability: float | None
    observed_rate: float | None


def calibration_bins(
    outcomes: list[int], probabilities: list[float], count: int = 10
) -> list[CalibrationBin]:
    _validate_pairs(outcomes, probabilities)
    if count <= 0:
        raise ValueError("count must be positive")
    bins: list[CalibrationBin] = []
    for index in range(count):
        lower, upper = index / count, (index + 1) / count
        points = [
            (outcome, probability)
            for outcome, probability in zip(outcomes, probabilities, strict=True)
            if (
                lower <= probability <= upper
                if index == count - 1
                else lower <= probability < upper
            )
        ]
        bins.append(
            CalibrationBin(
                lower,
                upper,
                len(points),
                sum(point[1] for point in points) / len(points) if points else None,
                sum(point[0] for point in points) / len(points) if points else None,
            )
        )
    return bins


def paired_comparison(
    cases: list[EvaluationCase], baseline: list[ForecastResult], final: list[ForecastResult]
) -> dict[str, float]:
    outcomes = {case.case_id: case.outcome for case in cases}
    baseline_by_id = {result.case_id: result.probability for result in baseline}
    final_by_id = {result.case_id: result.probability for result in final}
    if set(outcomes) != set(baseline_by_id) or set(outcomes) != set(final_by_id):
        raise ValueError("baseline and final results must cover the same cases")
    ordered = sorted(outcomes)
    baseline_score = brier_score(
        [outcomes[key] for key in ordered], [baseline_by_id[key] for key in ordered]
    )
    final_score = brier_score(
        [outcomes[key] for key in ordered], [final_by_id[key] for key in ordered]
    )
    return {
        "baseline_brier": baseline_score,
        "final_brier": final_score,
        "paired_brier_improvement": baseline_score - final_score,
    }


def expected_calibration_error(
    outcomes: list[int], probabilities: list[float], count: int = 10
) -> float:
    bins = calibration_bins(outcomes, probabilities, count)
    total = len(outcomes)
    return sum(
        item.count / total * abs(item.mean_probability - item.observed_rate)
        for item in bins
        if item.count and item.mean_probability is not None and item.observed_rate is not None
    )


def paired_bootstrap_brier(
    outcomes: list[int],
    baseline: list[float],
    final: list[float],
    groups: list[str],
    *,
    iterations: int = 2000,
    seed: int = 20260828,
) -> dict[str, float]:
    _validate_pairs(outcomes, baseline)
    _validate_pairs(outcomes, final)
    if len(groups) != len(outcomes):
        raise ValueError("groups must align with outcomes")
    unique = np.asarray(sorted(set(groups)))
    positions = {group: np.flatnonzero(np.asarray(groups) == group) for group in unique}
    rng = np.random.default_rng(seed)
    deltas = np.empty(iterations)
    y = np.asarray(outcomes, dtype=float)
    base = np.asarray(baseline, dtype=float)
    candidate = np.asarray(final, dtype=float)
    for index in range(iterations):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        selected = np.concatenate([positions[group] for group in sampled])
        deltas[index] = np.mean((base[selected] - y[selected]) ** 2) - np.mean(
            (candidate[selected] - y[selected]) ** 2
        )
    low, high = np.quantile(deltas, [0.025, 0.975])
    return {
        "mean_brier_improvement": float(np.mean(deltas)),
        "ci_95_low": float(low),
        "ci_95_high": float(high),
        "probability_improvement_gt_zero": float(np.mean(deltas > 0)),
        "iterations": float(iterations),
    }
