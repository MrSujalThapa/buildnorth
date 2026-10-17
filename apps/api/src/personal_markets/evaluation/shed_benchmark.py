"""SHED 2022→2023 emergency-savings goal pricing benchmark.

Source: Federal Reserve Board Survey of Household Economics and Decisionmaking
(public-use CSV). Panel overlap via stable `shedid`.

Contract:
  prediction time = 2022 survey wave
  goal = have set aside emergency/rainy-day funds covering 3 months of expenses
         by the 2023 wave (EF1 == Yes)
  features = 2022-only demographics, income, hardship, and prior EF1
  no 2023 fields as predictors
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from personal_markets.evaluation.calibration_fit import calibrate_prefit
from personal_markets.evaluation.metrics import (
    brier_score,
    expected_calibration_error,
    log_loss,
)
from personal_markets.evaluation.oulad_benchmark import file_sha256

SEED = 20260830
BENCHMARK_ID = "shed_emergency_savings_v1"
FEATURE_SCHEMA_VERSION = "shed-ef1-2022to2023-v1"

# 2022 predictors that are safe (no 2023 leakage). EF1_2022 is lagged outcome.
DEMO_FEATURES = [
    "ppage",
    "ppgender",
    "ppeducat",
    "ppinc7",
    "pphhsize",
    "ppmarit5",
    "ppemploy",
    "pprent",
    "ppmsacat",
]
OUTCOME_FEATURES_2022 = ["EF1", "EF7"]


def stable_split(entity_id: str | int) -> str:
    value = int(hashlib.sha256(f"{SEED}:{entity_id}".encode()).hexdigest()[:8], 16) % 100
    if value < 60:
        return "train"
    if value < 75:
        return "validation"
    if value < 90:
        return "calibration"
    return "test"


def _load_year(raw: Path, year: int) -> pd.DataFrame:
    zpath = raw / f"SHED_{year}.zip"
    with zipfile.ZipFile(zpath) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(name) as handle:
            return pd.read_csv(handle, low_memory=False)


def _encode_ef1(series: pd.Series) -> pd.Series:
    mapped = series.map({"Yes": 1, "No": 0})
    return mapped


def _encode_categorical(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = np.nan
            continue
        if pd.api.types.is_numeric_dtype(out[col]):
            continue
        codes, _ = pd.factorize(out[col].astype("string"), sort=True)
        out[col] = codes.astype(float)
        out.loc[codes < 0, col] = np.nan
    return out


def build_panel(raw: Path) -> pd.DataFrame:
    d22 = _load_year(raw, 2022)
    d23 = _load_year(raw, 2023)
    if "shedid" not in d22.columns or "shedid" not in d23.columns:
        raise ValueError("shedid required for panel linkage")
    ids = sorted(set(d22["shedid"]).intersection(set(d23["shedid"])))
    left = d22.set_index("shedid").loc[ids].copy()
    right = d23.set_index("shedid").loc[ids].copy()
    y = _encode_ef1(right["EF1"])
    panel = pd.DataFrame(index=ids)
    panel.index.name = "shedid"
    panel["y_ef1_2023"] = y.values
    panel["ef1_2022"] = _encode_ef1(left["EF1"]).values
    for col in DEMO_FEATURES:
        panel[col] = left[col].values if col in left.columns else np.nan
    # EF7 rainy-day cash band in 2022 as ordinal if present
    if "EF7" in left.columns:
        order = {
            "Under $100": 0,
            "$100 to $499": 1,
            "$500 to $999": 2,
            "$1,000 to $1,999": 3,
            "$2,000 or more": 4,
        }
        panel["ef7_band_2022"] = left["EF7"].map(order).astype(float).values
    else:
        panel["ef7_band_2022"] = np.nan
    panel = panel[panel["y_ef1_2023"].isin([0, 1])].copy()
    panel["split"] = [stable_split(i) for i in panel.index.astype(str)]
    return panel.reset_index()


def feature_columns(panel: pd.DataFrame) -> list[str]:
    cols = ["ef1_2022", "ef7_band_2022", *DEMO_FEATURES]
    return [c for c in cols if c in panel.columns]


def matrix_for_split(panel: pd.DataFrame, split: str) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    subset = panel[panel["split"] == split].copy()
    cols = feature_columns(panel)
    encoded = _encode_categorical(subset, [c for c in cols if c not in {"ef1_2022", "ef7_band_2022", "ppage", "pphhsize"}])
    x = encoded[cols].to_numpy(dtype=float)
    y = subset["y_ef1_2023"].to_numpy(dtype=int)
    return x, y, subset


def inspect_panel(panel: pd.DataFrame) -> dict[str, Any]:
    return {
        "n_panel": int(len(panel)),
        "base_rate_ef1_2023": float(panel["y_ef1_2023"].mean()),
        "split_counts": panel["split"].value_counts().to_dict(),
        "ef1_2022_base_rate": float(panel["ef1_2022"].mean()),
        "feature_columns": feature_columns(panel),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
    }


def prepare_benchmark(raw: Path, committed: Path, artifacts: Path) -> dict[str, Any]:
    committed.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    panel = build_panel(raw)
    panel.to_parquet(artifacts / "panel.parquet", index=False)
    split_manifest = panel[["shedid", "split"]].copy()
    split_manifest.to_csv(committed / "split_manifest.csv", index=False)
    inspection = inspect_panel(panel)
    (committed / "inspection_summary.json").write_text(json.dumps(inspection, indent=2), encoding="utf-8")
    checksums = {
        "SHED_2022.zip": file_sha256(raw / "SHED_2022.zip"),
        "SHED_2023.zip": file_sha256(raw / "SHED_2023.zip"),
    }
    manifest = {
        "benchmark_id": BENCHMARK_ID,
        "dataset_source": "Federal Reserve Board Survey of Household Economics and Decisionmaking",
        "dataset_url": "https://www.federalreserve.gov/consumerscommunities/shed_data.htm",
        "citation": "Board of Governors of the Federal Reserve System, Survey of Household Economics and Decisionmaking",
        "license": "Public use microdata; cite Fed SHED",
        "prediction_time": "2022 SHED wave",
        "deadline_resolution": "2023 SHED wave",
        "outcome_definition": "EF1==Yes in 2023 (3-month emergency/rainy-day funds)",
        "features_at_t": feature_columns(panel),
        "leakage_controls": [
            "No 2023 survey fields used as predictors",
            "Panel linked only via shedid present in both waves",
            "Person-disjoint splits by shedid",
        ],
        "split_method": f"SHA256({SEED}:shedid) → 60/15/15/10 train/val/cal/test",
        "sample_count": inspection,
        "checksums_sha256": checksums,
        "known_limitations": [
            "Annual survey waves (not continuous monitoring)",
            "Self-reported emergency savings, not verified balances",
            "Panel attriters excluded; not representative of full SHED cross-section",
        ],
    }
    (committed / "benchmark_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    metrics = fit_and_score(panel, artifacts)
    (committed / "statistical_baseline_results.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return {"inspection": inspection, "metrics": metrics, "manifest": manifest}


def fit_and_score(panel: pd.DataFrame, artifacts: Path) -> dict[str, Any]:
    x_train, y_train, _ = matrix_for_split(panel, "train")
    x_val, y_val, _ = matrix_for_split(panel, "validation")
    x_cal, y_cal, _ = matrix_for_split(panel, "calibration")
    x_test, y_test, test_meta = matrix_for_split(panel, "test")
    x_fit = np.vstack([x_train, x_val])
    y_fit = np.concatenate([y_train, y_val])

    base_rate = float(y_fit.mean())
    prevalence = np.full(len(y_test), base_rate)

    log_pipe = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            (
                "clf",
                LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED),
            ),
        ]
    )
    log_pipe.fit(x_fit, y_fit)
    p_log = calibrate_prefit(log_pipe, x_cal, y_cal, x_test, method="isotonic")

    hgb = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            (
                "clf",
                HistGradientBoostingClassifier(max_depth=4, learning_rate=0.08, random_state=SEED),
            ),
        ]
    )
    hgb.fit(x_fit, y_fit)
    p_hgb = calibrate_prefit(hgb, x_cal, y_cal, x_test, method="isotonic")

    def pack(name: str, p: np.ndarray) -> dict[str, Any]:
        y = y_test.tolist()
        probs = p.tolist()
        out: dict[str, Any] = {
            "system": name,
            "n": len(y),
            "brier": brier_score(y, probs),
            "log_loss": log_loss(y, probs),
            "ece_10": expected_calibration_error(y, probs),
            "mean_p": float(np.mean(probs)),
            "base_rate": float(np.mean(y)),
        }
        try:
            from sklearn.metrics import roc_auc_score

            out["roc_auc"] = float(roc_auc_score(y, probs))
        except ValueError:
            out["roc_auc"] = None
        return out

    pred_path = artifacts / "test_predictions.parquet"
    pd.DataFrame(
        {
            "shedid": test_meta["shedid"].values,
            "y": y_test,
            "p_prevalence": prevalence,
            "p_logistic": p_log,
            "p_hgb": p_hgb,
        }
    ).to_parquet(pred_path, index=False)

    return {
        "A_prevalence": pack("prevalence", prevalence),
        "C_logistic": pack("logistic_calibrated", p_log),
        "G_hgb": pack("hgb_calibrated", p_hgb),
        "relative_brier_reduction_hgb_vs_prevalence": float(
            (pack("prevalence", prevalence)["brier"] - pack("hgb", p_hgb)["brier"])
            / pack("prevalence", prevalence)["brier"]
        ),
    }
