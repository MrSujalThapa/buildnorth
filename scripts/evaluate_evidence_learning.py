"""Score OULAD forecasts at each evidence checkpoint.

Writes benchmarks/oulad_completion_v1/evidence_learning_v1.json only when the
official raw files are on disk. A missing dataset exits 2 and writes nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from personal_markets.evaluation.evidence_learning import learning_curve
from personal_markets.evaluation.oulad_benchmark import (
    build_feature_frame,
    stable_split,
)

ROOT = Path(__file__).resolve().parents[1]
RAW_CANDIDATES = (
    ROOT / "data" / "oulad" / "raw",
    ROOT / "data" / "oulad" / "raw" / "anonymisedData",
)
OUTPUT = ROOT / "benchmarks" / "oulad_completion_v1" / "evidence_learning_v1.json"


def _raw_dir() -> Path | None:
    for path in RAW_CANDIDATES:
        if (path / "studentInfo.csv").exists() and (path / "studentVle.csv").exists():
            return path
    return None


def main() -> int:
    raw = _raw_dir()
    if raw is None:
        print(
            json.dumps(
                {
                    "status": "not_executed",
                    "reason": "Official OULAD raw files are not under data/oulad/raw",
                    "predictions_written": 0,
                }
            ),
            file=sys.stderr,
        )
        return 2
    frame = build_feature_frame(raw)
    frame["split"] = frame.id_student.map(lambda value: stable_split(int(value)))
    report = learning_curve(frame)
    report["feature_source"] = "data/oulad/raw"
    report["status"] = "measured"
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {
        "status": "measured",
        "output": str(OUTPUT.relative_to(ROOT)),
        "n_test_rows": report["n_test_rows"],
        "prior_strength": report["prior_strength"],
        "checkpoints": [
            {
                "checkpoint_day": row["checkpoint_day"],
                "prior_brier": row["models"]["population_prior"]["brier"],
                "logistic_brier": row["models"]["evidence_logistic"]["brier"],
                "shrunk_brier": row["models"]["shrunk_evidence"]["brier"],
                "boosted_brier": row["models"]["hist_gradient_boosting"]["brier"],
            }
            for row in report["checkpoints"]
        ],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
