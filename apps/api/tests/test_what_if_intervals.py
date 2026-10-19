import numpy as np
import pytest

from personal_markets.forecasting.primitives import at_numerical_bound, price_growth
from personal_markets.what_if.intervals import sampling_uplift_interval_pp


def test_degenerate_sampling_interval_is_omitted_not_invented() -> None:
    assert sampling_uplift_interval_pp(np.zeros(200)) is None
    assert sampling_uplift_interval_pp(np.array([0.001])) is None
    assert sampling_uplift_interval_pp(np.array([np.nan, np.nan])) is None
    interval = sampling_uplift_interval_pp(np.array([-0.02, 0.0, 0.03, 0.01, -0.005]))
    assert interval is not None
    assert interval[0] < interval[1]


def test_growth_clip_floor_uplift_is_not_rescaled() -> None:
    baseline = price_growth(
        current=10.0,
        target=1_000_000.0,
        periods=1.0,
        mu=0.0,
        sigma=1e-12,
        n_observations=8,
    )
    scenario = price_growth(
        current=10.0,
        target=1_000_000.0,
        periods=1.0,
        mu=20.0,
        sigma=1e-12,
        n_observations=8,
    )
    assert baseline.priced and scenario.priced
    assert baseline.probability is not None and scenario.probability is not None
    assert at_numerical_bound(baseline.probability)
    assert scenario.probability > baseline.probability
    uplift_pp = (scenario.probability - baseline.probability) * 100.0
    assert uplift_pp == pytest.approx(99.9998, abs=1e-4)
    assert sampling_uplift_interval_pp(np.array([uplift_pp / 100.0, uplift_pp / 100.0])) is None
