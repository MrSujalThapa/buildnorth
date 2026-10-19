"""Sampling intervals for What If uplifts. Never invent width."""

from __future__ import annotations

import math

import numpy as np

_MIN_WIDTH_PP = 1e-9


def sampling_uplift_interval_pp(
    deltas: np.ndarray,
    *,
    q_low: float = 0.1,
    q_high: float = 0.9,
) -> tuple[float, float] | None:
    """Return a percentile interval in percentage points, or None if there is no variation.

    A zero-width interval is omitted rather than reported as ``[0, 0]``. The point
    estimate is left unchanged; this function does not adjust probabilities.
    """
    values = np.asarray(deltas, dtype=float)
    if values.size < 2:
        return None
    lo = float(np.quantile(values, q_low) * 100.0)
    hi = float(np.quantile(values, q_high) * 100.0)
    if not math.isfinite(lo) or not math.isfinite(hi):
        return None
    if abs(hi - lo) < _MIN_WIDTH_PP:
        return None
    return (lo, hi)
