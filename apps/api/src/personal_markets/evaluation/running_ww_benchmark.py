"""Running annual volume-goal pricing benchmark (Figshare long-distance training).

Source: DOI 10.6084/m9.figshare.16620238

IMPORTANT: The `major` column is a retrospective profile tag (present on 2019-01-01
rows), not a future-resolved race outcome. It is NOT used as a label.

Contract:
  prediction checkpoints: 2019-03-31, 2019-06-30, 2019-09-30
  goal: accumulate >= VOLUME_THRESHOLD_KM logged running distance by 2019-12-31
  features: training aggregates from weeks with datetime <= checkpoint only
  outcome: sum(distance in 2019) >= threshold
"""

from __future__ import annotations

import hashlib
import json
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
BENCHMARK_ID = "running_volume_2019_v1"
VOLUME_THRESHOLD_KM = 1500.0
CHECKPOINTS = (
    pd.Timestamp("2019-03-31"),
    pd.Timestamp("2019-06-30"),
    pd.Timestamp("2019-09-30"),
)
HALF_LIVES = (14, 28, 56)
YEAR_END = pd.Timestamp("2019-12-31")


def stable_split(entity_id: str | int) -> str:
    value = int(hashlib.sha256(f"{SEED}:{entity_id}".encode()).hexdigest()[:8], 16) % 100
    if value < 60:
        return "train"
    if value < 75:
        return "validation"
    if value < 90:
        return "calibration"
    return "test"


def load_2019(raw: Path) -> pd.DataFrame:
    w19 = pd.read_parquet(raw / "run_ww_2019_w.parquet")
    w19["datetime"] = pd.to_datetime(w19["datetime"], errors="coerce")
    w19 = w19[w19["datetime"].notna()].copy()
    # Drop major from feature path entirely (retrospective; not used)
    return w19


def build_cases(raw: Path) -> pd.DataFrame:
    w19 = load_2019(raw)
    year_total = w19.groupby("athlete", observed=True)["distance"].sum()
    labels = (year_total >= VOLUME_THRESHOLD_KM).astype(int)
    static = (
        w19.groupby("athlete", observed=True)
        .agg(gender=("gender", "first"), age_group=("age_group", "first"), country=("country", "first"))
        .reset_index()
    )
    rows: list[pd.DataFrame] = []
    for ck_i, ck in enumerate(CHECKPOINTS):
        window = w19[w19["datetime"] <= ck].copy()
        window["age_days"] = (ck - window["datetime"]).dt.days.clip(lower=0)
        for hl in HALF_LIVES:
            window[f"decay_km_hl{hl}"] = window["distance"] * np.power(0.5, window["age_days"] / hl)
        grouped = window.groupby("athlete", observed=True)
        agg = grouped.agg(
            km_ytd=("distance", "sum"),
            minutes_ytd=("duration", "sum"),
            sessions_ytd=("distance", "count"),
            active_weeks=("datetime", "nunique"),
            km_last_4w=("distance", lambda s: s.tail(4).sum()),
            km_last_8w=("distance", lambda s: s.tail(8).sum()),
        ).reset_index()
        for hl in HALF_LIVES:
            agg[f"decay_km_hl{hl}"] = grouped[f"decay_km_hl{hl}"].sum().values
        days_elapsed = max((ck - pd.Timestamp("2019-01-01")).days, 1)
        days_remaining = max((YEAR_END - ck).days, 1)
        agg["km_per_day_ytd"] = agg["km_ytd"] / days_elapsed
        agg["projected_km_linear"] = agg["km_ytd"] + agg["km_per_day_ytd"] * days_remaining
        agg["frac_threshold_ytd"] = agg["km_ytd"] / VOLUME_THRESHOLD_KM
        agg["days_elapsed"] = days_elapsed
        agg["days_remaining"] = days_remaining
        agg["checkpoint_index"] = ck_i
        agg["checkpoint"] = ck.isoformat()
        agg["mean_pace_min_per_km"] = agg["minutes_ytd"] / agg["km_ytd"].replace(0, np.nan)
        agg = agg.merge(static, on="athlete", how="left")
        agg["y_volume"] = agg["athlete"].map(labels).fillna(0).astype(int)
        # Already met threshold by checkpoint — still a valid forecast of year-end success
        agg["already_met_by_t"] = (agg["km_ytd"] >= VOLUME_THRESHOLD_KM).astype(int)
        rows.append(agg)
    cases = pd.concat(rows, ignore_index=True)
    cases["split"] = [stable_split(a) for a in cases["athlete"].astype(str)]
    cases["case_id"] = cases["athlete"].astype(str) + "-ck" + cases["checkpoint_index"].astype(str)
    return cases


def encode_features(frame: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    num_cols = [
        "checkpoint_index",
        "km_ytd",
        "minutes_ytd",
        "sessions_ytd",
        "active_weeks",
        "km_last_4w",
        "km_last_8w",
        "mean_pace_min_per_km",
        "km_per_day_ytd",
        "projected_km_linear",
        "frac_threshold_ytd",
        "days_elapsed",
        "days_remaining",
        "already_met_by_t",
        *[f"decay_km_hl{hl}" for hl in HALF_LIVES],
    ]
    cat_cols = ["gender", "age_group", "country"]
    cols = [c for c in [*num_cols, *cat_cols] if c in frame.columns]
    work = frame[cols].copy()
    for col in cat_cols:
        codes, _ = pd.factorize(work[col].astype("string"), sort=True)
        work[col] = codes.astype(float)
        work.loc[codes < 0, col] = np.nan
    for col in work.columns:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    return work.to_numpy(dtype=float), cols


def matrix_for_split(
    cases: pd.DataFrame, split: str
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame, list[str]]:
    subset = cases[cases["split"] == split].copy()
    x, cols = encode_features(subset)
    y = subset["y_volume"].to_numpy(dtype=int)
    return x, y, subset, cols


def prepare_benchmark(raw: Path, committed: Path, artifacts: Path) -> dict[str, Any]:
    committed.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    cases = build_cases(raw)
    cases.to_parquet(artifacts / "cases.parquet", index=False)
    cases[["athlete", "split"]].drop_duplicates().to_csv(committed / "split_manifest.csv", index=False)
    athlete_y = cases.drop_duplicates("athlete")[["athlete", "y_volume"]]
    inspection = {
        "n_cases": int(len(cases)),
        "n_athletes": int(cases["athlete"].nunique()),
        "volume_threshold_km": VOLUME_THRESHOLD_KM,
        "base_rate_athlete": float(athlete_y["y_volume"].mean()),
        "cases_by_checkpoint": cases["checkpoint_index"].value_counts().sort_index().to_dict(),
        "split_case_counts": cases["split"].value_counts().to_dict(),
        "major_column_usage": "EXCLUDED — retrospective profile tag, not a future label",
    }
    (committed / "inspection_summary.json").write_text(json.dumps(inspection, indent=2), encoding="utf-8")
    checksums = {name: file_sha256(raw / name) for name in ("run_ww_2019_w.parquet",) if (raw / name).exists()}
    manifest = {
        "benchmark_id": BENCHMARK_ID,
        "dataset_source": "A public dataset on long-distance running training in 2019 and 2020",
        "doi": "10.6084/m9.figshare.16620238",
        "outcome_definition": f"Total 2019 logged distance >= {VOLUME_THRESHOLD_KM} km",
        "prediction_timestamp_definition": "2019-03-31 / 06-30 / 09-30; features from weeks <= t",
        "split_method": f"athlete-disjoint SHA256({SEED}:athlete) 60/15/15/10",
        "leakage_controls": [
            "Features use only weeks with datetime <= checkpoint",
            "Year-end total is label only",
            "`major` never used (retrospective, not future-resolved)",
            "Athlete-disjoint splits",
        ],
        "sample_count": inspection,
        "checksums_sha256": checksums,
        "known_limitations": [
            "Volume goal proxies training consistency, not race finish time",
            "Scraped training logs; selection bias",
            "Weekly aggregation loses session-level structure",
        ],
    }
    (committed / "benchmark_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    metrics = fit_and_score(cases, artifacts)
    (committed / "statistical_baseline_results.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return {"inspection": inspection, "metrics": metrics, "manifest": manifest}


def fit_and_score(cases: pd.DataFrame, artifacts: Path) -> dict[str, Any]:
    x_train, y_train, _, cols = matrix_for_split(cases, "train")
    x_val, y_val, _, _ = matrix_for_split(cases, "validation")
    x_cal, y_cal, _, _ = matrix_for_split(cases, "calibration")
    x_test, y_test, test_meta, _ = matrix_for_split(cases, "test")
    x_fit = np.vstack([x_train, x_val])
    y_fit = np.concatenate([y_train, y_val])
    base_rate = float(y_fit.mean())
    prevalence = np.full(len(y_test), base_rate)

    log_pipe = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=3000, class_weight="balanced", random_state=SEED)),
        ]
    )
    log_pipe.fit(x_fit, y_fit)
    p_log = calibrate_prefit(log_pipe, x_cal, y_cal, x_test, method="isotonic")

    best_hl = 28
    best_brier = 1.0
    for hl in HALF_LIVES:
        if f"decay_km_hl{hl}" not in cols:
            continue
        clf = Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("clf", HistGradientBoostingClassifier(max_depth=4, random_state=SEED)),
            ]
        )
        clf.fit(x_fit, y_fit)
        p = clf.predict_proba(x_val)[:, 1]
        score = brier_score(y_val.tolist(), p.tolist())
        if score < best_brier:
            best_brier = score
            best_hl = hl

    hgb = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("clf", HistGradientBoostingClassifier(max_depth=4, learning_rate=0.07, random_state=SEED)),
        ]
    )
    hgb.fit(x_fit, y_fit)
    p_hgb = calibrate_prefit(hgb, x_cal, y_cal, x_test, method="isotonic")

    no_decay_cols = [i for i, c in enumerate(cols) if not c.startswith("decay_km_hl")]
    hgb_nd = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("clf", HistGradientBoostingClassifier(max_depth=4, learning_rate=0.07, random_state=SEED)),
        ]
    )
    hgb_nd.fit(x_fit[:, no_decay_cols], y_fit)
    p_nd = calibrate_prefit(
        hgb_nd, x_cal[:, no_decay_cols], y_cal, x_test[:, no_decay_cols], method="isotonic"
    )

    def pack(name: str, p: np.ndarray, y_arr: np.ndarray | None = None) -> dict[str, Any]:
        y_use = y_test if y_arr is None else y_arr
        y = y_use.tolist()
        probs = [float(min(max(v, 1e-6), 1 - 1e-6)) for v in np.asarray(p).tolist()]
        if not y:
            return {
                "system": name,
                "n": 0,
                "brier": None,
                "log_loss": None,
                "ece_10": None,
                "mean_p": None,
                "base_rate": None,
                "roc_auc": None,
            }
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

            out["roc_auc"] = float(roc_auc_score(y, probs)) if len(set(y)) > 1 else None
        except ValueError:
            out["roc_auc"] = None
        return out

    pd.DataFrame(
        {
            "case_id": test_meta["case_id"].values,
            "athlete": test_meta["athlete"].values,
            "checkpoint_index": test_meta["checkpoint_index"].values,
            "y": y_test,
            "p_prevalence": prevalence,
            "p_logistic": p_log,
            "p_hgb": p_hgb,
            "p_hgb_no_decay": p_nd,
        }
    ).to_parquet(artifacts / "test_predictions.parquet", index=False)

    by_h: dict[str, Any] = {}
    for ck in sorted(test_meta["checkpoint_index"].unique()):
        mask = test_meta["checkpoint_index"].to_numpy() == ck
        y_ck = y_test[mask]
        by_h[str(int(ck))] = {
            "prevalence": pack(f"prev_{ck}", prevalence[mask], y_ck),
            "logistic": pack(f"log_{ck}", p_log[mask], y_ck),
            "hgb": pack(f"hgb_{ck}", p_hgb[mask], y_ck),
        }

    return {
        "A_prevalence": pack("prevalence", prevalence),
        "C_logistic": pack("logistic_calibrated", p_log),
        "G_hgb": pack("hgb_calibrated", p_hgb),
        "decay_ablation": {
            "selected_half_life_days_on_validation": best_hl,
            "validation_brier_proxy": best_brier,
            "G_with_decay": pack("hgb_decay", p_hgb),
            "G_without_decay": pack("hgb_no_decay", p_nd),
            "relative_brier_change_removing_decay": float(
                (pack("nd", p_nd)["brier"] - pack("d", p_hgb)["brier"])
                / max(pack("d", p_hgb)["brier"], 1e-12)
            ),
        },
        "by_checkpoint": by_h,
        "feature_columns": cols,
    }
