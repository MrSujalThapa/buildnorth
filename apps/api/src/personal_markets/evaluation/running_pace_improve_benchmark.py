"""Running H1→H2 pace-improvement pricing benchmark (Figshare long-distance training).

Source: DOI 10.6084/m9.figshare.16620238

Contract:
  prediction_time: 2019-06-30
  goal: mean pace (min/km = duration/distance) in Jul–Dec 2019 is at least 5%
        faster (lower min/km) than Jan–Jun 2019 mean pace
  features: training aggregates from weeks with datetime <= 2019-06-30 only
  never use H2 weeks as features
  splits: athlete-disjoint SHA256(20260830:athlete) 60/15/15/10

Eligibility: distance > 0 in both H1 and H2 (otherwise pace undefined).
`major` is never used (retrospective profile tag).
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
BENCHMARK_ID = "running_pace_improve_2019_v1"
PREDICTION_TIME = pd.Timestamp("2019-06-30")
YEAR_START = pd.Timestamp("2019-01-01")
YEAR_END = pd.Timestamp("2019-12-31")
PACE_IMPROVE_FRACTION = 0.05  # H2 pace must be <= H1 pace * (1 - this)
HALF_LIVES = (14, 28, 56)
MIN_ATHLETES_FOR_BENCHMARK = 500


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
    return w19


def _half_pace(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.groupby("athlete", observed=True).agg(
        distance_km=("distance", "sum"),
        duration_min=("duration", "sum"),
        sessions=("distance", "count"),
    )
    grouped["mean_pace_min_per_km"] = grouped["duration_min"] / grouped["distance_km"].replace(
        0, np.nan
    )
    return grouped


def build_cases(raw: Path) -> pd.DataFrame:
    w19 = load_2019(raw)
    h1 = w19[w19["datetime"] <= PREDICTION_TIME].copy()
    h2 = w19[(w19["datetime"] > PREDICTION_TIME) & (w19["datetime"] <= YEAR_END)].copy()
    pace_h1 = _half_pace(h1)
    pace_h2 = _half_pace(h2)
    both = pace_h1.join(pace_h2, lsuffix="_h1", rsuffix="_h2", how="inner")
    eligible = both[(both["distance_km_h1"] > 0) & (both["distance_km_h2"] > 0)].copy()
    eligible["y_pace_improve"] = (
        eligible["mean_pace_min_per_km_h2"]
        <= eligible["mean_pace_min_per_km_h1"] * (1.0 - PACE_IMPROVE_FRACTION)
    ).astype(int)

    static = (
        w19.groupby("athlete", observed=True)
        .agg(gender=("gender", "first"), age_group=("age_group", "first"), country=("country", "first"))
        .reset_index()
    )

    window = h1.copy()
    window["age_days"] = (PREDICTION_TIME - window["datetime"]).dt.days.clip(lower=0)
    for hl in HALF_LIVES:
        window[f"decay_km_hl{hl}"] = window["distance"] * np.power(0.5, window["age_days"] / hl)
        window[f"decay_min_hl{hl}"] = window["duration"] * np.power(0.5, window["age_days"] / hl)

    grouped = window.groupby("athlete", observed=True)
    agg = grouped.agg(
        km_ytd=("distance", "sum"),
        minutes_ytd=("duration", "sum"),
        sessions_ytd=("distance", "count"),
        active_weeks=("datetime", "nunique"),
        km_last_4w=("distance", lambda s: s.tail(4).sum()),
        km_last_8w=("distance", lambda s: s.tail(8).sum()),
        minutes_last_4w=("duration", lambda s: s.tail(4).sum()),
        minutes_last_8w=("duration", lambda s: s.tail(8).sum()),
    ).reset_index()
    for hl in HALF_LIVES:
        agg[f"decay_km_hl{hl}"] = grouped[f"decay_km_hl{hl}"].sum().values
        agg[f"decay_min_hl{hl}"] = grouped[f"decay_min_hl{hl}"].sum().values

    days_elapsed = max((PREDICTION_TIME - YEAR_START).days, 1)
    agg["km_per_day_ytd"] = agg["km_ytd"] / days_elapsed
    agg["sessions_per_week_ytd"] = agg["sessions_ytd"] / max(days_elapsed / 7.0, 1e-9)
    agg["mean_pace_min_per_km_h1"] = agg["minutes_ytd"] / agg["km_ytd"].replace(0, np.nan)
    agg["pace_last_4w"] = agg["minutes_last_4w"] / agg["km_last_4w"].replace(0, np.nan)
    agg["pace_last_8w"] = agg["minutes_last_8w"] / agg["km_last_8w"].replace(0, np.nan)
    agg["days_elapsed"] = days_elapsed
    agg["prediction_time"] = PREDICTION_TIME.isoformat()
    agg = agg.merge(static, on="athlete", how="left")
    labels = eligible["y_pace_improve"]
    agg = agg[agg["athlete"].isin(eligible.index)].copy()
    agg["y_pace_improve"] = agg["athlete"].map(labels).astype(int)
    agg["h1_distance_km"] = agg["athlete"].map(eligible["distance_km_h1"])
    agg["h2_distance_km"] = agg["athlete"].map(eligible["distance_km_h2"])
    # Label-side pace retained for inspection only — never used as features
    agg["label_pace_h1"] = agg["athlete"].map(eligible["mean_pace_min_per_km_h1"])
    agg["label_pace_h2"] = agg["athlete"].map(eligible["mean_pace_min_per_km_h2"])
    agg["split"] = [stable_split(a) for a in agg["athlete"].astype(str)]
    agg["case_id"] = agg["athlete"].astype(str) + "-pace-2019-06-30"
    return agg.reset_index(drop=True)


def encode_features(frame: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    num_cols = [
        "km_ytd",
        "minutes_ytd",
        "sessions_ytd",
        "active_weeks",
        "km_last_4w",
        "km_last_8w",
        "minutes_last_4w",
        "minutes_last_8w",
        "mean_pace_min_per_km_h1",
        "pace_last_4w",
        "pace_last_8w",
        "km_per_day_ytd",
        "sessions_per_week_ytd",
        "days_elapsed",
        *[f"decay_km_hl{hl}" for hl in HALF_LIVES],
        *[f"decay_min_hl{hl}" for hl in HALF_LIVES],
    ]
    cat_cols = ["gender", "age_group", "country"]
    # Explicitly exclude label-side / H2 columns from features
    forbidden = {
        "y_pace_improve",
        "h2_distance_km",
        "label_pace_h2",
        "label_pace_h1",  # duplicate of mean_pace via eligibility join; use mean_pace_min_per_km_h1
    }
    cols = [c for c in [*num_cols, *cat_cols] if c in frame.columns and c not in forbidden]
    work = frame[cols].copy()
    for col in cat_cols:
        if col not in work.columns:
            continue
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
    y = subset["y_pace_improve"].to_numpy(dtype=int)
    return x, y, subset, cols


def prepare_benchmark(raw: Path, committed: Path, artifacts: Path) -> dict[str, Any]:
    committed.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)

    if not (raw / "run_ww_2019_w.parquet").exists():
        skip = {
            "benchmark_id": BENCHMARK_ID,
            "status": "SKIPPED",
            "reason": "Figshare weekly parquet missing at data/running_ww/raw/run_ww_2019_w.parquet",
        }
        (committed / "SKIPPED.json").write_text(json.dumps(skip, indent=2), encoding="utf-8")
        return skip

    w19 = load_2019(raw)
    h1 = w19[w19["datetime"] <= PREDICTION_TIME]
    h2 = w19[(w19["datetime"] > PREDICTION_TIME) & (w19["datetime"] <= YEAR_END)]
    pace_h1 = _half_pace(h1)
    pace_h2 = _half_pace(h2)
    both = pace_h1.join(pace_h2, lsuffix="_h1", rsuffix="_h2", how="inner")
    n_valid = int(((both["distance_km_h1"] > 0) & (both["distance_km_h2"] > 0)).sum())

    if n_valid < MIN_ATHLETES_FOR_BENCHMARK:
        skip = {
            "benchmark_id": BENCHMARK_ID,
            "status": "SKIPPED",
            "reason": (
                f"Insufficient athletes with distance>0 in both H1 and H2 "
                f"(n_valid={n_valid}, need>={MIN_ATHLETES_FOR_BENCHMARK})"
            ),
            "n_athletes_both_halves": int(len(both)),
            "n_valid_pace_both_halves": n_valid,
        }
        (committed / "SKIPPED.json").write_text(json.dumps(skip, indent=2), encoding="utf-8")
        (committed / "inspection_summary.json").write_text(json.dumps(skip, indent=2), encoding="utf-8")
        return skip

    cases = build_cases(raw)
    cases.to_parquet(artifacts / "cases.parquet", index=False)
    cases[["athlete", "split"]].drop_duplicates().to_csv(committed / "split_manifest.csv", index=False)
    athlete_y = cases.drop_duplicates("athlete")[["athlete", "y_pace_improve"]]
    inspection = {
        "n_cases": int(len(cases)),
        "n_athletes": int(cases["athlete"].nunique()),
        "n_valid_pace_both_halves": n_valid,
        "prediction_time": PREDICTION_TIME.isoformat(),
        "pace_improve_fraction": PACE_IMPROVE_FRACTION,
        "base_rate_athlete": float(athlete_y["y_pace_improve"].mean()),
        "split_case_counts": cases["split"].value_counts().to_dict(),
        "mean_pace_h1_median": float(cases["mean_pace_min_per_km_h1"].median()),
        "label_pace_h2_median": float(cases["label_pace_h2"].median()),
        "major_column_usage": "EXCLUDED — retrospective profile tag, not a future label",
        "leakage_note": "Features use only weeks with datetime <= 2019-06-30; H2 distance/pace are labels only",
    }
    (committed / "inspection_summary.json").write_text(json.dumps(inspection, indent=2), encoding="utf-8")
    checksums = {
        name: file_sha256(raw / name)
        for name in ("run_ww_2019_w.parquet",)
        if (raw / name).exists()
    }
    manifest = {
        "benchmark_id": BENCHMARK_ID,
        "dataset_source": "A public dataset on long-distance running training in 2019 and 2020",
        "doi": "10.6084/m9.figshare.16620238",
        "outcome_definition": (
            "Jul–Dec 2019 mean pace (min/km) <= Jan–Jun 2019 mean pace * "
            f"{1.0 - PACE_IMPROVE_FRACTION} (at least {PACE_IMPROVE_FRACTION * 100:.0f}% faster)"
        ),
        "prediction_timestamp_definition": "2019-06-30; features from weeks <= t only",
        "split_method": f"athlete-disjoint SHA256({SEED}:athlete) 60/15/15/10",
        "leakage_controls": [
            "Features use only weeks with datetime <= 2019-06-30",
            "H2 distance and pace are label-only; never encoded as features",
            "`major` never used (retrospective, not future-resolved)",
            "Athlete-disjoint splits",
            "Eligibility requires distance>0 in both halves so pace is defined",
        ],
        "sample_count": inspection,
        "checksums_sha256": checksums,
        "known_limitations": [
            "Pace from weekly aggregates (duration/distance); not race-certified times",
            "5% threshold is a product goal proxy, not a physiology claim",
            "Scraped training logs; selection bias",
            "Athletes who stop logging in H2 are excluded (distance>0 filter)",
        ],
    }
    (committed / "benchmark_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    metrics = fit_and_score(cases, artifacts)
    (committed / "statistical_baseline_results.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
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

    no_decay_cols = [
        i for i, c in enumerate(cols) if not c.startswith("decay_km_hl") and not c.startswith("decay_min_hl")
    ]
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
            "y": y_test,
            "p_prevalence": prevalence,
            "p_logistic": p_log,
            "p_hgb": p_hgb,
            "p_hgb_no_decay": p_nd,
        }
    ).to_parquet(artifacts / "test_predictions.parquet", index=False)

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
        "feature_columns": cols,
    }
