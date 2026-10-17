from pathlib import Path
import json

from personal_markets.evaluation.jth_benchmark import BenchmarkPaths, prepare_benchmark


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = root / "data" / "jth" / "raw"
    required = ["candidates.csv", "jobs.csv", "history.csv"]
    missing = [name for name in required if not (raw / name).is_file()]
    if missing:
        raise SystemExit(
            "JTH dataset not found. Download the files from https://zenodo.org/records/21390581 "
            f"and place them in {raw.relative_to(root)}. Missing: {', '.join(missing)}"
        )
    result = prepare_benchmark(
        BenchmarkPaths(
            raw=raw,
            committed=root / "benchmarks" / "jth_offer_v1",
            artifacts=root / ".artifacts" / "jth_offer_v1",
        )
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
