import argparse
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from personal_markets.evaluation.metrics import (
    brier_score,
    calibration_bins,
    expected_calibration_error,
    log_loss,
    paired_bootstrap_brier,
)
from personal_markets.forecasting.models import (
    ProbabilityCalibrator,
    build_model,
    feature_columns,
    logistic_contributions,
    split_xy,
)
from personal_markets.forecasting.receipts import ForecastReceipt

SEED = 20260828


def metrics(y: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    clipped = np.clip(probability, 1e-6, 1 - 1e-6)
    calibration = LogisticRegression(C=1e6, max_iter=1000).fit(logit(clipped).reshape(-1, 1), y)
    return {
        "n": len(y),
        "positive_rate": float(np.mean(y)),
        "brier": brier_score(y.tolist(), probability.tolist()),
        "log_loss": log_loss(y.tolist(), probability.tolist()),
        "roc_auc": float(roc_auc_score(y, probability)),
        "pr_auc": float(average_precision_score(y, probability)),
        "ece_10": expected_calibration_error(y.tolist(), probability.tolist()),
        "calibration_intercept": float(calibration.intercept_[0]),
        "calibration_slope": float(calibration.coef_[0, 0]),
        "calibration_bins": [
            asdict(item) for item in calibration_bins(y.tolist(), probability.tolist())
        ],
    }


def choose_calibrator(raw: np.ndarray, y: np.ndarray, groups: np.ndarray) -> str:
    selector = np.asarray(
        [
            int(hashlib.sha256(f"cal:{value}".encode()).hexdigest()[:8], 16) % 2 == 0
            for value in groups
        ],
        dtype=bool,
    )
    scores: dict[str, float] = {}
    for method in ("platt", "isotonic"):
        calibrator = ProbabilityCalibrator.fit(method, raw[selector], y[selector])
        scores[method] = brier_score(
            y[~selector].tolist(), calibrator.predict(raw[~selector]).tolist()
        )
    return min(scores, key=scores.__getitem__)


def write_case_analysis(frame: pd.DataFrame, path: Path) -> None:
    definitions = {
        "isolated_negative_event": frame[
            (frame.assessment_mean_score >= 70)
            & (frame.assessment_score_change < 0)
            & (frame.vle_click_trend_7d >= 0)
        ],
        "repeated_correlated_deterioration": frame[
            (frame.vle_click_trend_7d < 0)
            & (frame.vle_days_since_active >= 7)
            & (frame.assessment_score_change < 0)
        ],
        "sparse_evidence": frame[
            (frame.vle_active_days <= 2) & (frame.assessment_submissions == 0)
        ],
        "conflicting_evidence": frame[
            (frame.assessment_mean_score >= 70) & (frame.vle_active_days <= 5)
        ],
    }
    cases: dict[str, Any] = {}
    columns = [
        "code_module",
        "code_presentation",
        "id_student",
        "checkpoint_day",
        "outcome",
        "assessment_mean_score",
        "assessment_score_change",
        "vle_active_days",
        "vle_click_trend_7d",
        "vle_days_since_active",
        "logistic_probability",
        "final_probability",
    ]
    for name, candidates in definitions.items():
        if candidates.empty:
            cases[name] = {"status": "not_supported_by_frozen_criteria"}
            continue
        row = candidates.nlargest(1, "final_error").iloc[0]
        cases[name] = {
            "status": "observed",
            "selection": "largest final-model error among rows matching frozen criteria",
            "case": {
                column: row[column].item() if isinstance(row[column], np.generic) else row[column]
                for column in columns
            },
        }
    path.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")


def write_reliability_svg(bins: list[dict[str, Any]], path: Path) -> None:
    points = [
        (40 + 300 * item["mean_probability"], 340 - 300 * item["observed_rate"])
        for item in bins
        if item["count"] and item["mean_probability"] is not None
    ]
    circles = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4"/>' for x, y in points)
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="390" '
        'viewBox="0 0 400 390"><style>text{font:12px sans-serif}circle{fill:#1463ff}</style>'
        '<line x1="40" y1="340" x2="340" y2="40" stroke="#777" stroke-dasharray="5 4"/>'
        '<line x1="40" y1="340" x2="340" y2="340" stroke="#111"/>'
        '<line x1="40" y1="340" x2="40" y2="40" stroke="#111"/>'
        f'{circles}<text x="150" y="375">Mean predicted probability</text>'
        '<text x="5" y="25">Observed</text></svg>\n',
        encoding="utf-8",
    )


def run(root: Path) -> dict[str, Any]:
    artifact_dir = root / ".artifacts" / "oulad_completion_v1"
    committed = root / "benchmarks" / "oulad_completion_v1"
    manifest = json.loads((committed / "benchmark_manifest.json").read_text(encoding="utf-8"))
    frame = pd.read_pickle(artifact_dir / manifest["feature_artifact"])
    train = frame[frame.split == "train"]
    validation = frame[frame.split == "validation"]
    calibration = frame[frame.split == "calibration"]
    test = frame[frame.split == "test"]
    selection: list[dict[str, Any]] = []
    for family in ("logistic_regression", "hist_gradient_boosting"):
        for half_life in (7, 14, 28):
            columns = feature_columns(half_life)
            model = build_model(family, columns)
            started = time.perf_counter()
            model.fit(*split_xy(train, columns))
            probability = model.predict_proba(validation[columns])[:, 1]
            selection.append(
                {
                    "family": family,
                    "half_life_days": half_life,
                    "validation_brier": brier_score(
                        validation.outcome.tolist(), probability.tolist()
                    ),
                    "fit_seconds": time.perf_counter() - started,
                }
            )
    chosen_half_life = min(
        (row for row in selection if row["family"] == "hist_gradient_boosting"),
        key=lambda row: row["validation_brier"],
    )["half_life_days"]
    columns = feature_columns(chosen_half_life)
    train_validation = pd.concat([train, validation], ignore_index=True)
    systems: dict[str, Any] = {}
    predictions: dict[str, np.ndarray] = {}
    raw_predictions: dict[str, np.ndarray] = {}
    fitted_models: dict[str, Any] = {}
    for family in ("logistic_regression", "hist_gradient_boosting"):
        model = build_model(family, columns)
        started = time.perf_counter()
        model.fit(*split_xy(train_validation, columns))
        raw_cal = model.predict_proba(calibration[columns])[:, 1]
        method = choose_calibrator(
            raw_cal, calibration.outcome.to_numpy(), calibration.id_student.to_numpy()
        )
        calibrator = ProbabilityCalibrator.fit(method, raw_cal, calibration.outcome.to_numpy())
        raw_test = model.predict_proba(test[columns])[:, 1]
        calibrated_test = calibrator.predict(raw_test)
        raw_predictions[family] = raw_test
        fitted_models[family] = model
        predictions[family] = calibrated_test
        systems[family] = {
            "calibration_method": method,
            "raw": metrics(test.outcome.to_numpy(), raw_test),
            "calibrated": metrics(test.outcome.to_numpy(), calibrated_test),
            "fit_and_predict_seconds": time.perf_counter() - started,
        }
        joblib.dump(
            {"model": model, "calibrator": calibrator, "columns": columns},
            artifact_dir / f"{family}.joblib",
        )
        systems[family]["artifact_sha256"] = hashlib.sha256(
            (artifact_dir / f"{family}.joblib").read_bytes()
        ).hexdigest()
    prevalence = float(train_validation.outcome.mean())
    prevalence_predictions = np.full(len(test), prevalence)
    comparison = paired_bootstrap_brier(
        test.outcome.tolist(),
        predictions["logistic_regression"].tolist(),
        predictions["hist_gradient_boosting"].tolist(),
        test.id_student.astype(str).tolist(),
        iterations=2000,
        seed=SEED,
    )
    challenging = test.assign(
        logistic_probability=predictions["logistic_regression"],
        final_probability=predictions["hist_gradient_boosting"],
    )
    challenging["final_error"] = abs(challenging.final_probability - challenging.outcome)
    challenge_columns = [
        "code_module",
        "code_presentation",
        "id_student",
        "checkpoint_day",
        "outcome",
        "logistic_probability",
        "final_probability",
        "final_error",
    ]
    challenging.nlargest(100, "final_error")[challenge_columns].to_csv(
        committed / "challenging_cases.csv", index=False
    )
    write_case_analysis(challenging, committed / "challenging_case_analysis.json")
    sample = challenging.sort_values(["id_student", "checkpoint_day"]).iloc[0]
    receipt = ForecastReceipt(
        forecast_id="benchmark-sample-forecast",
        goal_id="oulad-course-completion",
        goal_contract_version=1,
        case_id=f"{sample.code_module}-{sample.code_presentation}-{sample.id_student}-{sample.checkpoint_day}",
        as_of_day=int(sample.checkpoint_day),
        evidence_watermark=f"course-day-{int(sample.checkpoint_day)}",
        relevant_evidence_ids=["aggregated-assessment-events", "aggregated-vle-events"],
        state_snapshot_id=f"state-{sample.id_student}-{sample.checkpoint_day}",
        state_snapshot_version=1,
        run_id="oulad-heldout-20260828",
        raw_probability=float(
            raw_predictions["hist_gradient_boosting"][challenging.index.get_loc(sample.name)]
        ),
        calibrated_probability=float(sample.final_probability),
        forecast_status="CALIBRATED",
        model={"family": "hist_gradient_boosting", "version": "oulad-completion-v1"},
        calibration={
            "method": systems["hist_gradient_boosting"]["calibration_method"],
            "split": "calibration",
        },
        feature_schema_version="oulad-temporal-v1",
        feature_snapshot={
            column: sample[column].item()
            if isinstance(sample[column], np.generic)
            else sample[column]
            for column in columns
        },
        transformations={
            "time_decay_half_life_days": chosen_half_life,
            "future_filter": "event_day <= checkpoint_day",
        },
        training_dataset={"name": "OULAD", "version": "oulad_completion_v1"},
        assumptions=["OULAD cohort represents only the benchmark population"],
        contributions=logistic_contributions(
            fitted_models["logistic_regression"], sample.to_frame().T[columns]
        )[:10],
        provenance={"benchmark": "oulad_completion_v1", "split": "test"},
        limitations=[
            "OULAD population only",
            "observational benchmark",
            "not transportable without validation",
        ],
    )
    (committed / "sample_forecast_receipt.json").write_text(
        receipt.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    result = {
        "benchmark": "oulad_completion_v1",
        "seed": SEED,
        "selection": selection,
        "selected_half_life_days": chosen_half_life,
        "test_touched_after_selection": True,
        "prevalence_baseline": metrics(test.outcome.to_numpy(), prevalence_predictions),
        "systems": systems,
        "paired_bootstrap_logistic_vs_final": comparison,
        "receipt_content_hash": receipt.content_hash(),
    }
    (committed / "evaluation_results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    write_reliability_svg(
        systems["hist_gradient_boosting"]["calibrated"]["calibration_bins"],
        committed / "reliability_diagram.svg",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run frozen OULAD numerical evaluation")
    parser.add_argument("--system", choices=["all", "statistical-baseline", "final"], default="all")
    parser.parse_args()
    print(json.dumps(run(Path(__file__).resolve().parents[1]), indent=2))


if __name__ == "__main__":
    main()
