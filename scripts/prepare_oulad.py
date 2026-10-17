import argparse
import json
from pathlib import Path

from personal_markets.evaluation.oulad_benchmark import BenchmarkPaths, prepare_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and prepare frozen OULAD benchmark")
    parser.add_argument("--raw", type=Path, default=Path("data/oulad/raw"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = prepare_benchmark(
        BenchmarkPaths(
            raw=(root / args.raw).resolve(),
            committed=root / "benchmarks" / "oulad_completion_v1",
            artifacts=root / ".artifacts" / "oulad_completion_v1",
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
