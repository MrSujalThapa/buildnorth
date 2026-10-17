import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from personal_markets.evaluation.oulad import OuladDatasetAdapter

KEYS = ["code_module", "code_presentation", "id_student"]
CHECKPOINTS = (14, 35, 70, 105)
HALF_LIVES = (7, 14, 28)
SEED = 20260828
FEATURE_SCHEMA_VERSION = "oulad-temporal-v1"


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


def stable_split(student_id: int) -> str:
    value = int(hashlib.sha256(f"{SEED}:{student_id}".encode()).hexdigest()[:8], 16) % 100
    if value < 60:
        return "train"
    if value < 75:
        return "validation"
    if value < 90:
        return "calibration"
    return "test"


def inspect_dataset(raw: Path) -> dict[str, Any]:
    OuladDatasetAdapter().validate_directory(raw)
    result: dict[str, Any] = {"dataset_version": OuladDatasetAdapter.version, "tables": {}}
    for path in sorted(raw.glob("*.csv")):
        frame = pd.read_csv(path)
        result["tables"][path.name] = {
            "rows": len(frame),
            "columns": list(frame.columns),
            "sha256": file_sha256(path),
            "duplicate_rows": int(frame.duplicated().sum()),
            "missing": {key: int(value) for key, value in frame.isna().sum().items()},
        }
    students = pd.read_csv(raw / "studentInfo.csv")
    result["population"] = {
        "enrollments": len(students),
        "students": int(students.id_student.nunique()),
        "presentations": int(
            students[["code_module", "code_presentation"]].drop_duplicates().shape[0]
        ),
        "outcomes": {
            str(key): int(value) for key, value in students.final_result.value_counts().items()
        },
    }
    registrations = pd.read_csv(raw / "studentRegistration.csv")
    submissions = pd.read_csv(raw / "studentAssessment.csv")
    assessment_defs = pd.read_csv(raw / "assessments.csv")
    vle = pd.read_csv(raw / "studentVle.csv", usecols=["date", "sum_click"])
    result["temporal_profile"] = {
        "registration_day_range": [
            int(registrations.date_registration.min()),
            int(registrations.date_registration.max()),
        ],
        "unregistration_records": int(registrations.date_unregistration.notna().sum()),
        "unregistration_day_range": [
            int(registrations.date_unregistration.min()),
            int(registrations.date_unregistration.max()),
        ],
        "submission_day_range": [
            int(submissions.date_submitted.min()),
            int(submissions.date_submitted.max()),
        ],
        "vle_day_range": [int(vle.date.min()), int(vle.date.max())],
    }
    result["assessment_structure"] = {
        "definitions": len(assessment_defs),
        "types": {
            str(key): int(value)
            for key, value in assessment_defs.assessment_type.value_counts().items()
        },
        "weight_range": [float(assessment_defs.weight.min()), float(assessment_defs.weight.max())],
        "missing_scores": int(submissions.score.isna().sum()),
        "banked_submissions": int(submissions.is_banked.sum()),
    }
    result["vle_activity"] = {
        "click_quantiles": {
            str(key): float(value)
            for key, value in vle.sum_click.quantile([0, 0.5, 0.9, 0.99, 1]).items()
        },
        "negative_day_rows": int((vle.date < 0).sum()),
        "zero_click_rows": int((vle.sum_click == 0).sum()),
    }
    result["target_alternatives"] = {
        "A_completion_including_withdrawal_as_failure": {"n": len(students)},
        "B_completion_excluding_withdrawal": {
            "n": int((students.final_result != "Withdrawn").sum())
        },
        "C_four_class": {"n": len(students), "classes": 4},
    }
    return result


def create_split_manifest(raw: Path) -> pd.DataFrame:
    students = pd.read_csv(raw / "studentInfo.csv", usecols=["id_student"])
    unique = sorted(int(value) for value in students.id_student.unique())
    return pd.DataFrame({"id_student": unique, "split": [stable_split(value) for value in unique]})


def _aggregate_vle(raw: Path, checkpoint: int) -> pd.DataFrame:
    source = pd.read_csv(
        raw / "studentVle.csv",
        usecols=KEYS + ["id_site", "date", "sum_click"],
        dtype={
            "code_module": "category",
            "code_presentation": "category",
            "id_student": "int32",
            "id_site": "int32",
            "date": "int16",
            "sum_click": "int32",
        },
    )
    source = source[(source.date >= 0) & (source.date <= checkpoint)].copy()
    source["recent_7"] = source.sum_click.where(source.date > checkpoint - 7, 0)
    source["previous_7"] = source.sum_click.where(
        (source.date > checkpoint - 14) & (source.date <= checkpoint - 7), 0
    )
    source["recent_28"] = source.sum_click.where(source.date > checkpoint - 28, 0)
    for half_life in HALF_LIVES:
        source[f"decayed_clicks_hl{half_life}"] = source.sum_click * np.power(
            0.5, (checkpoint - source.date) / half_life
        )
    grouped = source.groupby(KEYS, observed=True)
    result = grouped.agg(
        vle_total_clicks=("sum_click", "sum"),
        vle_active_days=("date", "nunique"),
        vle_unique_sites=("id_site", "nunique"),
        vle_last_active_day=("date", "max"),
        vle_clicks_7d=("recent_7", "sum"),
        vle_clicks_previous_7d=("previous_7", "sum"),
        vle_clicks_28d=("recent_28", "sum"),
        **{f"vle_decayed_clicks_hl{h}": (f"decayed_clicks_hl{h}", "sum") for h in HALF_LIVES},
    ).reset_index()
    result["vle_days_since_active"] = checkpoint - result.vle_last_active_day
    result["vle_click_trend_7d"] = result.vle_clicks_7d - result.vle_clicks_previous_7d
    daily = source.groupby(KEYS + ["date"], observed=True).sum_click.sum().reset_index()
    volatility = daily.groupby(KEYS, observed=True).sum_click.std().rename("vle_daily_click_std")
    result = result.merge(volatility.reset_index(), on=KEYS, how="left")
    return result


def _aggregate_assessments(raw: Path, checkpoint: int) -> pd.DataFrame:
    submissions = pd.read_csv(raw / "studentAssessment.csv")
    definitions = pd.read_csv(raw / "assessments.csv")
    joined = submissions.merge(definitions, on="id_assessment", how="left", validate="many_to_one")
    joined = joined[(joined.date_submitted >= 0) & (joined.date_submitted <= checkpoint)].copy()
    joined["weighted_score"] = joined.score * joined.weight
    joined["on_time"] = (joined.date.isna() | (joined.date_submitted <= joined.date)).astype(int)
    grouped = joined.groupby(KEYS, observed=True)
    result = grouped.agg(
        assessment_submissions=("id_assessment", "count"),
        assessment_mean_score=("score", "mean"),
        assessment_score_std=("score", "std"),
        assessment_weight_submitted=("weight", "sum"),
        assessment_weighted_score_sum=("weighted_score", "sum"),
        assessment_on_time_rate=("on_time", "mean"),
        assessment_last_submission_day=("date_submitted", "max"),
    ).reset_index()
    ordered = joined.sort_values("date_submitted").groupby(KEYS, observed=True).score
    score_change = (ordered.last() - ordered.first()).rename("assessment_score_change")
    result = result.merge(score_change.reset_index(), on=KEYS, how="left")
    result["assessment_days_since_submission"] = checkpoint - result.assessment_last_submission_day
    return result


def build_feature_frame(raw: Path) -> pd.DataFrame:
    students = pd.read_csv(raw / "studentInfo.csv")
    courses = pd.read_csv(raw / "courses.csv")
    base = students.merge(courses, on=["code_module", "code_presentation"], validate="many_to_one")
    base["outcome"] = base.final_result.isin(["Pass", "Distinction"]).astype(int)
    selected = base[
        KEYS + ["num_of_prev_attempts", "studied_credits", "module_presentation_length", "outcome"]
    ]
    frames: list[pd.DataFrame] = []
    for checkpoint in CHECKPOINTS:
        frame = selected.copy()
        frame["checkpoint_day"] = checkpoint
        frame = frame.merge(_aggregate_vle(raw, checkpoint), on=KEYS, how="left")
        frame = frame.merge(_aggregate_assessments(raw, checkpoint), on=KEYS, how="left")
        numeric = [column for column in frame if column not in KEYS + ["outcome"]]
        frame[numeric] = frame[numeric].fillna(0)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def prepare_benchmark(paths: BenchmarkPaths) -> dict[str, Any]:
    paths.committed.mkdir(parents=True, exist_ok=True)
    paths.artifacts.mkdir(parents=True, exist_ok=True)
    inspection = inspect_dataset(paths.raw)
    split = create_split_manifest(paths.raw)
    split.to_csv(paths.committed / "split_manifest.csv", index=False)
    source_hash = hashlib.sha256(
        json.dumps(
            {name: table["sha256"] for name, table in inspection["tables"].items()},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cache_key = hashlib.sha256(
        f"{source_hash}:{FEATURE_SCHEMA_VERSION}:{CHECKPOINTS}:{HALF_LIVES}:{SEED}".encode()
    ).hexdigest()[:16]
    feature_artifact = paths.artifacts / f"features-{cache_key}.pkl"
    if feature_artifact.exists():
        features = pd.read_pickle(feature_artifact)
    else:
        features = build_feature_frame(paths.raw).merge(
            split, on="id_student", validate="many_to_one"
        )
        features.to_pickle(feature_artifact)
    summary = {
        "benchmark": "oulad_completion_v1",
        "seed": SEED,
        "target": {"success": ["Pass", "Distinction"], "failure": ["Fail", "Withdrawn"]},
        "checkpoints_days": list(CHECKPOINTS),
        "half_life_candidates_days": list(HALF_LIVES),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "cache_key": cache_key,
        "feature_artifact": feature_artifact.name,
        "feature_artifact_sha256": file_sha256(feature_artifact),
        "split_students": {str(k): int(v) for k, v in split.split.value_counts().items()},
        "split_checkpoint_rows": {
            str(key): int(value) for key, value in features.split.value_counts().items()
        },
        "split_target_frequency": {
            str(name): {
                str(int(target)): int(count)
                for target, count in partition.outcome.value_counts().items()
            }
            for name, partition in features.groupby("split")
        },
        "split_manifest_sha256": file_sha256(paths.committed / "split_manifest.csv"),
        "feature_rows": len(features),
        "feature_columns": list(features.columns),
        "leakage_exclusions": [
            "final_result",
            "date_unregistration",
            "gender",
            "region",
            "highest_education",
            "imd_band",
            "age_band",
            "disability",
            "all events after each checkpoint",
        ],
    }
    for name, payload in (
        ("inspection_summary.json", inspection),
        ("benchmark_manifest.json", summary),
    ):
        (paths.committed / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return summary
