import math

import pytest

from personal_markets.evaluation.metrics import (
    brier_score,
    calibration_bins,
    expected_calibration_error,
    log_loss,
    paired_bootstrap_brier,
)


def test_brier_score_known_values() -> None:
    assert brier_score([1, 0], [1.0, 0.0]) == 0
    assert brier_score([1, 0], [0.5, 0.5]) == 0.25


def test_log_loss_known_values() -> None:
    assert log_loss([1, 0], [0.5, 0.5]) == pytest.approx(math.log(2))


def test_calibration_bins_preserve_all_points() -> None:
    bins = calibration_bins([0, 1, 1], [0.1, 0.5, 1.0], count=2)
    assert sum(item.count for item in bins) == 3
    assert bins[-1].observed_rate == 1.0


def test_ece_is_zero_for_perfect_group_predictions() -> None:
    assert expected_calibration_error([0, 1], [0.0, 1.0], count=2) == 0


def test_paired_bootstrap_is_reproducible_and_grouped() -> None:
    result = paired_bootstrap_brier(
        [0, 0, 1, 1],
        [0.4, 0.4, 0.6, 0.6],
        [0.1, 0.1, 0.9, 0.9],
        ["a", "a", "b", "b"],
        iterations=100,
        seed=7,
    )
    assert result["mean_brier_improvement"] == pytest.approx(0.15)
    assert result["probability_improvement_gt_zero"] == 1
