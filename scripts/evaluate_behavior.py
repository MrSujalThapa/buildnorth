from __future__ import annotations

import json
from pathlib import Path

from personal_markets.evaluation.behavior_eval import generate_dataset, run_behavior_evaluation

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "behavior_adherence_v1"


def main() -> None:
    dataset = OUT / "dataset.jsonl"
    if not dataset.exists():
        generate_dataset(dataset)
    result = run_behavior_evaluation(dataset)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
