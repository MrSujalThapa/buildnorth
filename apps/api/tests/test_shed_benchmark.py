"""Tests for SHED emergency-savings panel benchmark."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from personal_markets.evaluation.shed_benchmark import build_panel, stable_split


def _zip_csv(path: Path, name: str, frame: pd.DataFrame) -> None:
    csv_name = name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(csv_name, frame.to_csv(index=False))


def test_shed_split_buckets() -> None:
    buckets = {stable_split(f"id-{i}") for i in range(300)}
    assert buckets == {"train", "validation", "calibration", "test"}


def test_panel_uses_2022_features_only(tmp_path: Path) -> None:
    raw = tmp_path
    d22 = pd.DataFrame(
        {
            "shedid": [1, 2],
            "EF1": ["Yes", "No"],
            "EF7": ["$2,000 or more", "Under $100"],
            "ppage": [30, 40],
            "ppgender": ["Male", "Female"],
            "ppeducat": ["Bachelor", "High school"],
            "ppinc7": ["$50k", "$25k"],
            "pphhsize": [2, 1],
            "ppmarit5": ["Married", "Never"],
            "ppemploy": ["Working", "Working"],
            "pprent": ["Own", "Rent"],
            "ppmsacat": ["Metro", "Metro"],
        }
    )
    d23 = pd.DataFrame(
        {
            "shedid": [1, 2],
            "EF1": ["Yes", "Yes"],
            "ppage": [99, 99],  # must not become a feature from 2023
        }
    )
    _zip_csv(raw / "SHED_2022.zip", "public2022.csv", d22)
    _zip_csv(raw / "SHED_2023.zip", "public2023.csv", d23)
    panel = build_panel(raw)
    assert set(panel["shedid"]) == {1, 2}
    assert int(panel.loc[panel["shedid"] == 2, "y_ef1_2023"].iloc[0]) == 1
    assert "ppage" in panel.columns
    assert float(panel.loc[panel["shedid"] == 1, "ppage"].iloc[0]) == 30.0
