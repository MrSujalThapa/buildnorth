import hashlib
import json
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from personal_markets.evaluation.metrics import brier_score


def _case_id(row: Any) -> str:
    return (
        f"{row.code_module}-{row.code_presentation}-"
        f"{int(row.id_student)}-{int(row.checkpoint_day)}"
    )


def run(root: Path) -> dict[str, Any]:
    started = time.perf_counter()
    committed = root / "benchmarks" / "oulad_completion_v1"
    artifact_dir = root / ".artifacts" / "oulad_completion_v1"
    baseline_path = committed / "openai_baseline_result.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    manifest = json.loads((committed / "benchmark_manifest.json").read_text(encoding="utf-8"))
    frame = pd.read_pickle(artifact_dir / manifest["feature_artifact"])
    test = frame[frame.split == "test"].copy()
    test["case_id"] = [_case_id(row) for row in test.itertuples()]
    by_case = test.set_index("case_id", drop=False)
    case_ids = [item["case_id"] for item in baseline["predictions"]]
    if len(case_ids) != 200 or len(set(case_ids)) != 200:
        raise ValueError("official baseline artifact must contain 200 unique frozen cases")
    missing = sorted(set(case_ids) - set(by_case.index))
    if missing:
        raise ValueError(f"baseline cases missing from frozen test split: {missing[:3]}")
    subset = by_case.loc[case_ids]
    outcomes = subset.outcome.to_numpy(dtype=int)
    llm = np.asarray([item["probability"] for item in baseline["predictions"]], dtype=float)
    predictions: dict[str, np.ndarray] = {"gpt_5_4_official": llm}
    model_info: dict[str, Any] = {
        "gpt_5_4_official": {
            "model": baseline["model"],
            "prompt_version": baseline["prompt_version"],
            "source_artifact_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        }
    }
    for name, artifact_name in (
        ("logistic_statistical", "logistic_regression.joblib"),
        ("pass_2_selected", "hist_gradient_boosting.joblib"),
    ):
        path = artifact_dir / artifact_name
        bundle = joblib.load(path)
        raw = bundle["model"].predict_proba(subset[bundle["columns"]])[:, 1]
        predictions[name] = bundle["calibrator"].predict(raw)
        model_info[name] = {
            "family": artifact_name.removesuffix(".joblib"),
            "version": "oulad-completion-v1",
            "calibration": type(bundle["calibrator"].model).__name__,
            "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    briers = {
        name: brier_score(outcomes.tolist(), values.tolist())
        for name, values in predictions.items()
    }
    rows = []
    for index, case_id in enumerate(case_ids):
        rows.append(
            {
                "case_id": case_id,
                "outcome": int(outcomes[index]),
                **{name: float(values[index]) for name, values in predictions.items()},
            }
        )
    result = {
        "artifact_version": "oulad-shared-200-v1",
        "benchmark": "oulad_completion_v1",
        "n": len(case_ids),
        "case_ids_sha256": hashlib.sha256(("\n".join(case_ids) + "\n").encode()).hexdigest(),
        "case_ids": case_ids,
        "systems": model_info,
        "brier": briers,
        "paired_brier_differences": {
            "gpt_5_4_minus_logistic": briers["gpt_5_4_official"]
            - briers["logistic_statistical"],
            "gpt_5_4_minus_pass_2": briers["gpt_5_4_official"]
            - briers["pass_2_selected"],
            "logistic_minus_pass_2": briers["logistic_statistical"]
            - briers["pass_2_selected"],
        },
        "predictions": rows,
        "runtime_seconds": time.perf_counter() - started,
        "evaluation_command": "uv run python scripts/evaluate_shared_subset.py",
    }
    output = committed / "shared_200_comparison_v1.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run(Path(__file__).resolve().parents[1]), indent=2))
