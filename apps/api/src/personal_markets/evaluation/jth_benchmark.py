"""Frozen JTH career-hiring offer pricing benchmark (no fabricated labels)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

SEED = 20260830
SPLIT_HASH_PREFIX = "20260830"
FEATURE_SCHEMA_VERSION = "jth-offer-temporal-v1"
BENCHMARK_NAME = "jth_offer_v1"
DAY_CHECKPOINTS = (0, 7, 14, 30)
STAGE_CHECKPOINTS = ("after_start", "after_shortlist", "after_1st_interview")

REQUIRED_RAW_FILES = ("candidates.csv", "jobs.csv", "history.csv")

FUNNEL_DATE_COLUMNS = (
    "spontaneous_application_date",
    "shortlist_date",
    "qualification_date",
    "resume_sent_to_company_date",
    "1st_interview_date",
    "2nd_interview_date",
    "3rd_interview_date",
    "4th_interview_date",
)
INTERVIEW_DATE_COLUMNS = (
    "1st_interview_date",
    "2nd_interview_date",
    "3rd_interview_date",
    "4th_interview_date",
)
OFFER_DATE_COLUMNS = ("job_offer_proposed_date", "job_offer_accepted_date")
START_DATE_COLUMNS = (
    "spontaneous_application_date",
    "shortlist_date",
    "qualification_date",
    "resume_sent_to_company_date",
    "1st_interview_date",
)

EXPERIENCE_ORDINAL = {
    "0-2": 1,
    "0-2 years": 1,
    "3-6": 2,
    "3-6 years": 2,
    "+6": 3,
    "+6 years": 3,
}
DIPLOMA_ORDINAL = {
    "none": 0,
    "high school": 1,
    "associate": 2,
    "bachelor": 3,
    "master": 4,
    "mba": 4,
    "phd": 5,
    "doctorate": 5,
}
SENIORITY_ORDINAL = {
    "intern": 0,
    "junior": 1,
    "mid": 2,
    "middle": 2,
    "senior": 3,
    "lead": 4,
    "manager": 4,
    "director": 5,
    "executive": 5,
}

# Columns returned by build_feature_matrix as X (documented contract).
FEATURE_COLUMNS = (
    "cand_years_experience_ord",
    "cand_skill_count",
    "cand_hard_skill_count",
    "cand_soft_skill_count",
    "cand_diploma_ord",
    "cand_seniority_ord",
    "cand_management_experience",
    "cand_from_top_university",
    "cand_previous_positions",
    "cand_unique_employers",
    "job_years_experience_ord",
    "job_skill_count",
    "job_seniority_ord",
    "job_required_diploma_ord",
    "job_required_years",
    "job_is_startup",
    "job_is_large_company",
    "job_remote_possible",
    "job_salary_log1p",
    "days_since_start",
    "reached_spontaneous",
    "reached_shortlist",
    "reached_qualification",
    "reached_resume_sent",
    "reached_1st_interview",
    "reached_2nd_interview",
    "reached_3rd_interview",
    "reached_4th_interview",
    "interviews_completed_by_t",
    "checkpoint_day",
    "is_stage_after_start",
    "is_stage_after_shortlist",
    "is_stage_after_1st_interview",
)

META_COLUMNS = (
    "application_id",
    "candidate_id",
    "job_id",
    "checkpoint_type",
    "checkpoint_key",
    "checkpoint_date",
    "process_start",
    "process_end",
    "end_of_process_imputed",
    "outcome",
    "split",
)

SplitName = Literal["train", "val", "cal", "test"]


@dataclass(frozen=True, slots=True)
class BenchmarkPaths:
    raw: Path
    committed: Path
    artifacts: Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_split(candidate_id: str | int) -> SplitName:
    """Candidate-disjoint split via SHA256('20260830:{candidate_id}') % 100."""
    value = int(hashlib.sha256(f"{SPLIT_HASH_PREFIX}:{candidate_id}".encode()).hexdigest()[:8], 16) % 100
    if value < 60:
        return "train"
    if value < 75:
        return "val"
    if value < 90:
        return "cal"
    return "test"


def _parse_dates(frame: pd.DataFrame, columns: list[str] | tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_datetime(result[column], errors="coerce")
    return result


def _semicolon_count(value: object) -> int:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return 0
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return 0
    return sum(1 for part in text.split(";") if part.strip())


def _ordinal_map(value: object, mapping: dict[str, int]) -> int:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return -1
    key = str(value).strip().lower()
    if not key or key == "nan":
        return -1
    if key in mapping:
        return mapping[key]
    for candidate, code in mapping.items():
        if candidate in key:
            return code
    return -1


def _bool01(value: object) -> int:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return 0
    if isinstance(value, (bool, np.bool_)):
        return int(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "t", "y"}:
        return 1
    return 0


def _to_float(value: object, default: float = 0.0) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_raw_directory(raw: Path) -> None:
    missing = [name for name in REQUIRED_RAW_FILES if not (raw / name).exists()]
    if missing:
        raise ValueError(f"JTH raw directory missing required files: {missing}")


def inspect_dataset(raw: Path) -> dict[str, Any]:
    validate_raw_directory(raw)
    result: dict[str, Any] = {
        "dataset": "JTH",
        "source": {
            "zenodo_record": "21390581",
            "url": "https://zenodo.org/records/21390581",
            "license": "CC BY-NC 4.0",
            "code": "https://github.com/Aunsiels/JTH",
        },
        "tables": {},
    }
    for name in REQUIRED_RAW_FILES:
        path = raw / name
        frame = pd.read_csv(path, low_memory=False)
        result["tables"][name] = {
            "rows": len(frame),
            "columns": list(frame.columns),
            "sha256": file_sha256(path),
            "duplicate_rows": int(frame.duplicated().sum()),
            "missing": {key: int(value) for key, value in frame.isna().sum().items()},
        }

    history = _parse_dates(
        pd.read_csv(raw / "history.csv", low_memory=False),
        list(FUNNEL_DATE_COLUMNS) + list(OFFER_DATE_COLUMNS) + ["end_of_process_date"],
    )
    offer = history["job_offer_proposed_date"].notna()
    result["population"] = {
        "applications": len(history),
        "unique_application_ids": int(history["application_id"].nunique()),
        "unique_candidate_job_pairs": int(
            history[["candidate_id", "job_id"]].drop_duplicates().shape[0]
        ),
        "candidates": int(history["candidate_id"].nunique()),
        "jobs": int(history["job_id"].nunique()),
        "offer_proposed_n": int(offer.sum()),
        "offer_proposed_rate": float(offer.mean()),
        "end_of_process_date_non_null": int(history["end_of_process_date"].notna().sum()),
        "last_stage_reached": {
            str(key): int(value)
            for key, value in history["last_stage_reached"].value_counts(dropna=False).items()
        },
    }
    result["funnel_non_null"] = {
        column: int(history[column].notna().sum()) for column in FUNNEL_DATE_COLUMNS
    }
    result["outcome_definition"] = {
        "goal": "Will this application receive a job offer by end of process?",
        "y": "1 iff job_offer_proposed_date is not null",
        "unit": "application_id (candidate_id + job_id trajectory row)",
    }
    result["leakage_controls"] = {
        "excluded_from_features_at_t": [
            "job_offer_proposed_date",
            "job_offer_accepted_date",
            "last_stage_reached",
            "any funnel date strictly after checkpoint t",
            "days_until_end / process_end as a predictive feature",
        ],
        "process_end_imputation": (
            "When end_of_process_date is null, process_end = max(recorded event dates); "
            "never used as an X feature."
        ),
    }
    return result


def create_split_manifest(raw: Path) -> pd.DataFrame:
    history = pd.read_csv(raw / "history.csv", usecols=["candidate_id"], low_memory=False)
    unique = sorted(str(value) for value in history["candidate_id"].unique())
    return pd.DataFrame(
        {"candidate_id": unique, "split": [stable_split(value) for value in unique]}
    )


def _series_or_default(frame: pd.DataFrame, column: str, default: object) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([default] * len(frame), index=frame.index)


def _static_candidate_features(candidates: pd.DataFrame) -> pd.DataFrame:
    frame = candidates.copy()
    return pd.DataFrame(
        {
            "candidate_id": frame["candidate_id"].astype(str),
            "cand_create": pd.to_datetime(_series_or_default(frame, "create_date", pd.NaT), errors="coerce"),
            "cand_years_experience_ord": [
                _ordinal_map(value, EXPERIENCE_ORDINAL)
                for value in _series_or_default(frame, "years_experience", None)
            ],
            "cand_skill_count": [
                _semicolon_count(value) for value in _series_or_default(frame, "skills", None)
            ],
            "cand_hard_skill_count": [
                _semicolon_count(value) for value in _series_or_default(frame, "llm_hard_skills", None)
            ],
            "cand_soft_skill_count": [
                _semicolon_count(value) for value in _series_or_default(frame, "llm_soft_skills", None)
            ],
            "cand_diploma_ord": [
                _ordinal_map(value, DIPLOMA_ORDINAL)
                for value in _series_or_default(frame, "llm_highest_diploma", None)
            ],
            "cand_seniority_ord": [
                _ordinal_map(value, SENIORITY_ORDINAL)
                for value in _series_or_default(frame, "llm_seniority_level", None)
            ],
            "cand_management_experience": [
                _bool01(value) for value in _series_or_default(frame, "llm_management_experience", 0)
            ],
            "cand_from_top_university": [
                _bool01(value) for value in _series_or_default(frame, "llm_from_top_university", 0)
            ],
            "cand_previous_positions": [
                int(_to_float(value, 0.0))
                for value in _series_or_default(frame, "llm_number_of_previous_positions", 0)
            ],
            "cand_unique_employers": [
                int(_to_float(value, 0.0))
                for value in _series_or_default(frame, "llm_number_of_unique_employers", 0)
            ],
        }
    )


def _static_job_features(jobs: pd.DataFrame) -> pd.DataFrame:
    frame = jobs.copy()
    salary = _series_or_default(frame, "salary", np.nan).map(lambda value: _to_float(value, np.nan))
    return pd.DataFrame(
        {
            "job_id": frame["job_id"].astype(str),
            "job_create": pd.to_datetime(_series_or_default(frame, "create_date", pd.NaT), errors="coerce"),
            "job_years_experience_ord": [
                _ordinal_map(value, EXPERIENCE_ORDINAL)
                for value in _series_or_default(frame, "years_experience", None)
            ],
            "job_skill_count": [
                _semicolon_count(value) for value in _series_or_default(frame, "skills", None)
            ],
            "job_seniority_ord": [
                _ordinal_map(value, SENIORITY_ORDINAL)
                for value in _series_or_default(frame, "llm_seniority_level", None)
            ],
            "job_required_diploma_ord": [
                _ordinal_map(value, DIPLOMA_ORDINAL)
                for value in _series_or_default(frame, "llm_required_lowest_diploma", None)
            ],
            "job_required_years": [
                _to_float(value, -1.0)
                for value in _series_or_default(frame, "llm_required_years_of_work_experience", -1)
            ],
            "job_is_startup": [
                _bool01(value) for value in _series_or_default(frame, "llm_is_startup", 0)
            ],
            "job_is_large_company": [
                _bool01(value) for value in _series_or_default(frame, "llm_is_large_company", 0)
            ],
            "job_remote_possible": [
                _bool01(value) for value in _series_or_default(frame, "llm_remote_possible", 0)
            ],
            "job_salary_log1p": np.log1p(salary.fillna(0.0).clip(lower=0.0)),
        }
    )


def _application_base(raw: Path) -> pd.DataFrame:
    history = _parse_dates(
        pd.read_csv(raw / "history.csv", low_memory=False),
        list(FUNNEL_DATE_COLUMNS) + list(OFFER_DATE_COLUMNS) + ["end_of_process_date"],
    )
    history["application_id"] = history["application_id"].astype(str)
    history["candidate_id"] = history["candidate_id"].astype(str)
    history["job_id"] = history["job_id"].astype(str)

    candidates = _static_candidate_features(pd.read_csv(raw / "candidates.csv", low_memory=False))
    jobs = _static_job_features(pd.read_csv(raw / "jobs.csv", low_memory=False))
    base = history.merge(candidates, on="candidate_id", how="left", validate="many_to_one")
    base = base.merge(jobs, on="job_id", how="left", validate="many_to_one")

    start_parts = list(START_DATE_COLUMNS) + ["cand_create", "job_create"]
    base["process_start"] = base[start_parts].min(axis=1)

    event_cols = list(FUNNEL_DATE_COLUMNS) + list(OFFER_DATE_COLUMNS) + ["end_of_process_date"]
    event_max = base[event_cols].max(axis=1)
    imputed = base["end_of_process_date"].isna()
    base["end_of_process_imputed"] = imputed.astype(int)
    base["process_end"] = base["end_of_process_date"].where(~imputed, event_max)
    base["outcome"] = base["job_offer_proposed_date"].notna().astype(int)
    base["split"] = [stable_split(value) for value in base["candidate_id"]]

    missing_bounds = base["process_start"].isna() | base["process_end"].isna()
    if bool(missing_bounds.any()):
        base = base.loc[~missing_bounds].copy()
    invalid = base["process_start"] > base["process_end"]
    if bool(invalid.any()):
        base = base.loc[~invalid].copy()
    return base.reset_index(drop=True)


def _reached(date_series: pd.Series, checkpoint: pd.Series) -> pd.Series:
    return (date_series.notna() & (date_series <= checkpoint)).astype(int)


def _attach_temporal_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    checkpoint = result["checkpoint_date"]
    result["days_since_start"] = (checkpoint - result["process_start"]).dt.days.astype(int)
    result["reached_spontaneous"] = _reached(result["spontaneous_application_date"], checkpoint)
    result["reached_shortlist"] = _reached(result["shortlist_date"], checkpoint)
    result["reached_qualification"] = _reached(result["qualification_date"], checkpoint)
    result["reached_resume_sent"] = _reached(result["resume_sent_to_company_date"], checkpoint)
    result["reached_1st_interview"] = _reached(result["1st_interview_date"], checkpoint)
    result["reached_2nd_interview"] = _reached(result["2nd_interview_date"], checkpoint)
    result["reached_3rd_interview"] = _reached(result["3rd_interview_date"], checkpoint)
    result["reached_4th_interview"] = _reached(result["4th_interview_date"], checkpoint)
    result["interviews_completed_by_t"] = (
        result["reached_1st_interview"]
        + result["reached_2nd_interview"]
        + result["reached_3rd_interview"]
        + result["reached_4th_interview"]
    )
    result["is_stage_after_start"] = (result["checkpoint_key"] == "after_start").astype(int)
    result["is_stage_after_shortlist"] = (result["checkpoint_key"] == "after_shortlist").astype(int)
    result["is_stage_after_1st_interview"] = (
        result["checkpoint_key"] == "after_1st_interview"
    ).astype(int)
    return result


def build_feature_frame(raw: Path) -> pd.DataFrame:
    """Build leakage-safe application × checkpoint feature rows from raw JTH CSVs."""
    base = _application_base(raw)
    frames: list[pd.DataFrame] = []

    for day in DAY_CHECKPOINTS:
        frame = base.copy()
        frame["checkpoint_type"] = "day"
        frame["checkpoint_key"] = f"day_{day}"
        frame["checkpoint_day"] = day
        frame["checkpoint_date"] = frame["process_start"] + pd.to_timedelta(day, unit="D")
        frame = frame.loc[frame["checkpoint_date"] <= frame["process_end"]].copy()
        frames.append(_attach_temporal_features(frame))

    stage_specs = (
        ("after_start", None),
        ("after_shortlist", "shortlist_date"),
        ("after_1st_interview", "1st_interview_date"),
    )
    for key, date_column in stage_specs:
        frame = base.copy()
        frame["checkpoint_type"] = "stage"
        frame["checkpoint_key"] = key
        frame["checkpoint_day"] = -1
        if date_column is None:
            frame["checkpoint_date"] = frame["process_start"]
        else:
            frame = frame.loc[frame[date_column].notna()].copy()
            frame["checkpoint_date"] = frame[date_column]
        frame = frame.loc[frame["checkpoint_date"] <= frame["process_end"]].copy()
        frames.append(_attach_temporal_features(frame))

    combined = pd.concat(frames, ignore_index=True)
    ordered = list(META_COLUMNS) + list(FEATURE_COLUMNS)
    # Keep raw funnel dates out of the returned frame to avoid accidental leakage downstream.
    return combined[ordered].copy()


def build_feature_matrix(
    split: SplitName,
    *,
    paths: BenchmarkPaths | None = None,
    features: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Return (X, y, meta) for one candidate-disjoint split.

    X columns are FEATURE_COLUMNS (documented). y is offer-proposed outcome.
    meta carries identifiers and checkpoint provenance only.
    """
    if features is None:
        if paths is None:
            raise ValueError("paths is required when features is not provided")
        artifact = _resolve_feature_artifact(paths)
        if artifact is not None and artifact.exists():
            features = pd.read_pickle(artifact)
        else:
            features = build_feature_frame(paths.raw)
    partition = features.loc[features["split"] == split].copy()
    if partition.empty:
        raise ValueError(f"no rows for split={split!r}")
    x = partition.loc[:, list(FEATURE_COLUMNS)].copy()
    y = partition["outcome"].astype(int).copy()
    meta = partition.loc[:, list(META_COLUMNS)].copy()
    return x, y, meta


def _resolve_feature_artifact(paths: BenchmarkPaths) -> Path | None:
    manifest_path = paths.committed / "benchmark_manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    name = manifest.get("feature_artifact")
    if not name:
        return None
    return paths.artifacts / str(name)


def prepare_benchmark(paths: BenchmarkPaths) -> dict[str, Any]:
    paths.committed.mkdir(parents=True, exist_ok=True)
    paths.artifacts.mkdir(parents=True, exist_ok=True)

    inspection = inspect_dataset(paths.raw)
    split = create_split_manifest(paths.raw)
    split_path = paths.committed / "split_manifest.csv"
    split.to_csv(split_path, index=False)

    source_hash = hashlib.sha256(
        json.dumps(
            {name: table["sha256"] for name, table in inspection["tables"].items()},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cache_key = hashlib.sha256(
        f"{source_hash}:{FEATURE_SCHEMA_VERSION}:{DAY_CHECKPOINTS}:{STAGE_CHECKPOINTS}:{SEED}".encode()
    ).hexdigest()[:16]
    feature_artifact = paths.artifacts / f"features-{cache_key}.pkl"
    if feature_artifact.exists():
        features = pd.read_pickle(feature_artifact)
    else:
        features = build_feature_frame(paths.raw)
        features.to_pickle(feature_artifact)

    application_splits = (
        features.drop_duplicates("application_id")
        .groupby("split", observed=True)
        .size()
        .to_dict()
    )
    application_outcomes = (
        features.drop_duplicates("application_id")
        .groupby("split", observed=True)["outcome"]
        .agg(["sum", "count"])
    )
    base_rate = float(features.drop_duplicates("application_id")["outcome"].mean())

    summary: dict[str, Any] = {
        "benchmark": BENCHMARK_NAME,
        "seed": SEED,
        "split_hash_prefix": SPLIT_HASH_PREFIX,
        "source": inspection["source"],
        "outcome": inspection["outcome_definition"],
        "checkpoints": {
            "day_offsets_from_process_start": list(DAY_CHECKPOINTS),
            "stage_snapshots": list(STAGE_CHECKPOINTS),
            "rule": (
                "Day checkpoints at process_start + {0,7,14,30} only if checkpoint_date <= "
                "process_end. Stage snapshots: after_start, after_shortlist, after_1st_interview "
                "using funnel dates that occurred on or before t."
            ),
        },
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "meta_columns": list(META_COLUMNS),
        "cache_key": cache_key,
        "feature_artifact": feature_artifact.name,
        "feature_artifact_sha256": file_sha256(feature_artifact),
        "raw_checksums": {name: table["sha256"] for name, table in inspection["tables"].items()},
        "split_candidates": {str(key): int(value) for key, value in split["split"].value_counts().items()},
        "split_applications": {str(key): int(value) for key, value in application_splits.items()},
        "split_checkpoint_rows": {
            str(key): int(value) for key, value in features["split"].value_counts().items()
        },
        "split_offer_counts": {
            str(name): {"offers": int(row["sum"]), "applications": int(row["count"])}
            for name, row in application_outcomes.iterrows()
        },
        "base_rate_offer_proposed": base_rate,
        "feature_rows": len(features),
        "split_manifest_sha256": file_sha256(split_path),
        "leakage_controls": inspection["leakage_controls"],
        "process_end_imputed_applications": int(
            features.drop_duplicates("application_id")["end_of_process_imputed"].sum()
        ),
    }

    (paths.committed / "inspection_summary.json").write_text(
        json.dumps(inspection, indent=2) + "\n", encoding="utf-8"
    )
    (paths.committed / "benchmark_manifest.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def expected_calibration_error(
    y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10
) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    total = len(y_true)
    if total == 0:
        return float("nan")
    ece = 0.0
    for index in range(n_bins):
        lower, upper = bins[index], bins[index + 1]
        if index == n_bins - 1:
            mask = (y_prob >= lower) & (y_prob <= upper)
        else:
            mask = (y_prob >= lower) & (y_prob < upper)
        count = int(mask.sum())
        if count == 0:
            continue
        ece += (count / total) * abs(float(y_true[mask].mean()) - float(y_prob[mask].mean()))
    return float(ece)


def fit_baseline_models(
    paths: BenchmarkPaths,
    *,
    calibration: Literal["isotonic", "platt"] = "isotonic",
) -> dict[str, Any]:
    """Optional train/eval helpers: logistic + HGB, calibrate on cal, score test."""
    from personal_markets.evaluation.calibration_fit import calibrate_prefit
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    artifact = _resolve_feature_artifact(paths)
    features = pd.read_pickle(artifact) if artifact and artifact.exists() else build_feature_frame(paths.raw)

    x_train, y_train, _ = build_feature_matrix("train", features=features)
    x_val, y_val, _ = build_feature_matrix("val", features=features)
    x_cal, y_cal, _ = build_feature_matrix("cal", features=features)
    x_test, y_test, _ = build_feature_matrix("test", features=features)

    # Fit on train+val for capacity; calibrate strictly on cal; report on test.
    x_fit = pd.concat([x_train, x_val], ignore_index=True)
    y_fit = pd.concat([y_train, y_val], ignore_index=True)

    models: dict[str, Any] = {
        "logistic": Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=2000,
                        class_weight="balanced",
                        random_state=SEED,
                    ),
                ),
            ]
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_depth=6,
            learning_rate=0.08,
            max_iter=200,
            random_state=SEED,
        ),
    }

    method = "isotonic" if calibration == "isotonic" else "platt"
    results: dict[str, Any] = {"calibration": calibration, "models": {}}
    for name, model in models.items():
        model.fit(x_fit, y_fit)
        prob = calibrate_prefit(
            model,
            np.asarray(x_cal, dtype=float),
            np.asarray(y_cal, dtype=int),
            np.asarray(x_test, dtype=float),
            method=method,
        )
        y_np = y_test.to_numpy(dtype=int)
        results["models"][name] = {
            "brier": float(brier_score_loss(y_np, prob)),
            "logloss": float(log_loss(y_np, prob, labels=[0, 1])),
            "ece": expected_calibration_error(y_np, prob),
            "auc": float(roc_auc_score(y_np, prob)) if len(np.unique(y_np)) > 1 else float("nan"),
            "n_test_rows": int(len(y_np)),
            "test_positive_rate": float(y_np.mean()),
        }
    return results
