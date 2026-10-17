from pathlib import Path
import json
from personal_markets.evaluation.running_ww_benchmark import prepare_benchmark

def main() -> None:
    root = Path(__file__).resolve().parents[1]
    raw = root / "data" / "running_ww" / "raw"
    required = raw / "run_ww_2019_w.parquet"
    if not required.is_file():
        raise SystemExit(
            "Running dataset not found. Download run_ww_2019_w.parquet from "
            "https://doi.org/10.6084/m9.figshare.16620238 and place it at "
            f"{required.relative_to(root)}."
        )
    result = prepare_benchmark(
        raw=raw,
        committed=root / "benchmarks" / "running_volume_2019_v1",
        artifacts=root / ".artifacts" / "running_volume_2019_v1",
    )
    print(json.dumps({"inspection": result["inspection"], "metrics": result["metrics"]}, indent=2))

if __name__ == "__main__":
    main()
