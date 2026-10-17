"""Calibration helpers compatible with scikit-learn 1.6+ (no cv='prefit')."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


class _PredictProba(Protocol):
    def predict_proba(self, x: Any) -> np.ndarray: ...


class IsotonicProbabilityCalibrator:
    """Fit isotonic mapping on (raw_proba, y) from a held-out calibration split."""

    def __init__(self) -> None:
        self._iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)

    def fit(self, raw_proba: np.ndarray, y: np.ndarray) -> IsotonicProbabilityCalibrator:
        self._iso.fit(np.asarray(raw_proba, dtype=float), np.asarray(y, dtype=float))
        return self

    def transform(self, raw_proba: np.ndarray) -> np.ndarray:
        return np.asarray(self._iso.predict(np.asarray(raw_proba, dtype=float)), dtype=float)


class PlattProbabilityCalibrator:
    def __init__(self) -> None:
        self._clf = LogisticRegression(max_iter=2000)

    def fit(self, raw_proba: np.ndarray, y: np.ndarray) -> PlattProbabilityCalibrator:
        x = np.asarray(raw_proba, dtype=float).reshape(-1, 1)
        self._clf.fit(x, np.asarray(y, dtype=int))
        return self

    def transform(self, raw_proba: np.ndarray) -> np.ndarray:
        x = np.asarray(raw_proba, dtype=float).reshape(-1, 1)
        return self._clf.predict_proba(x)[:, 1]


def calibrate_prefit(
    model: _PredictProba,
    x_cal: np.ndarray,
    y_cal: np.ndarray,
    x_test: np.ndarray,
    *,
    method: str = "isotonic",
) -> np.ndarray:
    raw_cal = model.predict_proba(x_cal)[:, 1]
    raw_test = model.predict_proba(x_test)[:, 1]
    if method == "platt":
        calibrator: IsotonicProbabilityCalibrator | PlattProbabilityCalibrator = (
            PlattProbabilityCalibrator()
        )
    else:
        calibrator = IsotonicProbabilityCalibrator()
    calibrator.fit(raw_cal, y_cal)
    return calibrator.transform(raw_test)
