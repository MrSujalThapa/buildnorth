from pathlib import Path
import json
from personal_markets.evaluation.shed_benchmark import prepare_benchmark

def main() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = root / "data" / "shed" / "raw"
    required = ["SHED_2022.zip", "SHED_2023.zip"]
    missing = [name for name in required if not (raw / name).is_file()]
    if missing:
        raise SystemExit(
            "Fed SHED dataset not found. Download the 2022 and 2023 public-use files from "
            "https://www.federalreserve.gov/consumerscommunities/shed_data.htm and place "
            f"them in {raw.relative_to(root)}. Missing: {', '.join(missing)}"
        )
    result = prepare_benchmark(
        raw=raw,
        committed=root / "benchmarks" / "shed_emergency_savings_v1",
        artifacts=root / ".artifacts" / "shed_emergency_savings_v1",
    )
    print(json.dumps({"inspection": result["inspection"], "metrics": result["metrics"]}, indent=2))

if __name__ == "__main__":
    main()
