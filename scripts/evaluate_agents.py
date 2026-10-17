import json
from pathlib import Path

from personal_markets.evaluation.agent_eval import run_agent_evaluation


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    result = run_agent_evaluation()
    directory = root / "benchmarks" / "agent_eval_v1"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "results.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
