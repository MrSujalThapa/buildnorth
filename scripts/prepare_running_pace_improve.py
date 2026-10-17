from pathlib import Path
import json
from personal_markets.evaluation.running_pace_improve_benchmark import prepare_benchmark


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    result = prepare_benchmark(
        raw=root / "data" / "running_ww" / "raw",
        committed=root / "benchmarks" / "running_pace_improve_2019_v1",
        artifacts=root / ".artifacts" / "running_pace_improve_2019_v1",
    )
    print(json.dumps(result if "status" in result else {"inspection": result["inspection"], "metrics": result["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
