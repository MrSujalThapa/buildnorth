"""Run a fixed synthetic-only strategy experiment; no production reads."""

import json

from personal_markets.strategy_learning.offline_eval import run_offline_experiment
from personal_markets.strategy_learning.synthetic_fixture import SEED, synthetic_cases


def main() -> None:
    result = run_offline_experiment(synthetic_cases())
    result["dataset"] = "pass9b_synthetic_strategy_outcomes_v1"
    result["seed"] = SEED
    result["data_is_synthetic"] = True
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
