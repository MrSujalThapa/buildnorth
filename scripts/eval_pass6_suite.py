"""Pass 6 frozen evaluation runner — goal, intervention, and ablation metrics."""

from __future__ import annotations

import json
from pathlib import Path

from personal_markets.evaluation.agent_eval import run_agent_evaluation


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    cases_path = root / "benchmarks" / "pass6_eval_v1" / "cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    agent_result = run_agent_evaluation()
    output = {
        "suite_version": cases["version"],
        "frozen_cases": cases,
        "agent_eval": agent_result,
        "ablation": agent_result.get("ablation", {}),
        "notes": [
            "Intervention and source-planner live scoring require OPENAI_API_KEY and are run via scripts/evaluate_agents.py.",
            "Numerical forecast metrics remain on OULAD benchmark; no fabricated cross-domain labels.",
        ],
    }
    out_dir = root / "benchmarks" / "pass6_eval_v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(out_path), "goal_cases": len(cases["goal_architect"])}, indent=2))


if __name__ == "__main__":
    main()
