"""Tests for running volume-goal benchmark (no retrospective major labels)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from personal_markets.evaluation.running_ww_benchmark import (
    VOLUME_THRESHOLD_KM,
    build_cases,
    stable_split,
)


def test_group_split_is_deterministic_and_bucketed() -> None:
    assert stable_split(1036) == stable_split(1036)
    buckets = {stable_split(i) for i in range(500)}
    assert buckets == {"train", "validation", "calibration", "test"}


def test_volume_label_and_no_future_leakage(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    rows = []
    # Athlete 1: low early volume, high late volume → year total above threshold
    for month, km in [(1, 50.0), (2, 50.0), (3, 50.0), (7, 800.0), (10, 800.0)]:
        rows.append(
            {
                "datetime": pd.Timestamp(f"2019-{month:02d}-15"),
                "athlete": 1,
                "distance": km,
                "duration": km * 6,
                "gender": "M",
                "age_group": "18 - 34",
                "country": "United States",
                "major": "BOSTON 2019",  # must be ignored as label
            }
        )
    # Athlete 2: stays below threshold
    for month in (1, 2, 3, 7, 10):
        rows.append(
            {
                "datetime": pd.Timestamp(f"2019-{month:02d}-15"),
                "athlete": 2,
                "distance": 40.0,
                "duration": 240.0,
                "gender": "F",
                "age_group": "35 - 54",
                "country": "Germany",
                "major": "BERLIN 2020",
            }
        )
    pd.DataFrame(rows).to_parquet(raw / "run_ww_2019_w.parquet", index=False)
    cases = build_cases(raw)
    assert "major" not in cases.columns
    a1 = cases[cases["athlete"] == 1]
    a2 = cases[cases["athlete"] == 2]
    assert int(a1["y_volume"].iloc[0]) == 1
    assert int(a2["y_volume"].iloc[0]) == 0
    # March checkpoint must not include July km in km_ytd
    march = a1[a1["checkpoint_index"] == 0].iloc[0]
    assert march["km_ytd"] == pytest.approx(150.0)
    assert march["km_ytd"] < VOLUME_THRESHOLD_KM
