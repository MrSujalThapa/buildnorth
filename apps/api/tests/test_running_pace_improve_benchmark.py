"""Tests for running H1→H2 pace-improvement benchmark."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from personal_markets.evaluation.running_pace_improve_benchmark import (
    PACE_IMPROVE_FRACTION,
    PREDICTION_TIME,
    build_cases,
    encode_features,
    stable_split,
)


def test_group_split_matches_volume_seed() -> None:
    assert stable_split(1036) == stable_split(1036)
    buckets = {stable_split(i) for i in range(500)}
    assert buckets == {"train", "validation", "calibration", "test"}


def test_pace_label_and_no_h2_feature_leakage(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = []
    # Athlete 1: H1 slow (6 min/km), H2 5%+ faster (5.5 min/km) → improve=1
    for month, km, pace in [
        (1, 40.0, 6.0),
        (3, 40.0, 6.0),
        (5, 40.0, 6.0),
        (7, 40.0, 5.5),
        (9, 40.0, 5.5),
        (11, 40.0, 5.5),
    ]:
        rows.append(
            {
                "datetime": pd.Timestamp(f"2019-{month:02d}-15"),
                "athlete": 1,
                "distance": km,
                "duration": km * pace,
                "gender": "M",
                "age_group": "18 - 34",
                "country": "United States",
                "major": "BOSTON 2019",
            }
        )
    # Athlete 2: no improvement (same pace)
    for month in (2, 4, 6, 8, 10, 12):
        rows.append(
            {
                "datetime": pd.Timestamp(f"2019-{month:02d}-15"),
                "athlete": 2,
                "distance": 30.0,
                "duration": 180.0,
                "gender": "F",
                "age_group": "35 - 54",
                "country": "Germany",
                "major": "BERLIN 2020",
            }
        )
    # Athlete 3: H2 distance=0 → excluded
    for month in (1, 3, 5):
        rows.append(
            {
                "datetime": pd.Timestamp(f"2019-{month:02d}-15"),
                "athlete": 3,
                "distance": 20.0,
                "duration": 100.0,
                "gender": "M",
                "age_group": "18 - 34",
                "country": "France",
                "major": "NONE",
            }
        )
    pd.DataFrame(rows).to_parquet(raw / "run_ww_2019_w.parquet", index=False)
    cases = build_cases(raw)
    assert set(cases["athlete"].tolist()) == {1, 2}
    assert int(cases.loc[cases["athlete"] == 1, "y_pace_improve"].iloc[0]) == 1
    assert int(cases.loc[cases["athlete"] == 2, "y_pace_improve"].iloc[0]) == 0
    assert cases["prediction_time"].iloc[0] == PREDICTION_TIME.isoformat()
    # H2 km must not leak into YTD feature
    a1 = cases[cases["athlete"] == 1].iloc[0]
    assert a1["km_ytd"] == pytest.approx(120.0)
    assert a1["h2_distance_km"] == pytest.approx(120.0)
    x, cols = encode_features(cases)
    assert "label_pace_h2" not in cols
    assert "h2_distance_km" not in cols
    assert "y_pace_improve" not in cols
    assert "mean_pace_min_per_km_h1" in cols
    assert a1["mean_pace_min_per_km_h1"] == pytest.approx(6.0)
    assert a1["label_pace_h2"] <= a1["label_pace_h1"] * (1.0 - PACE_IMPROVE_FRACTION)
