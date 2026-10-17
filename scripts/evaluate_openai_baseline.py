import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from personal_markets.agents.budget import InMemoryUsageStore, TokenBudget
from personal_markets.agents.models import estimate_cost_usd
from personal_markets.core.config import get_settings
from personal_markets.evaluation.metrics import brier_score
from personal_markets.integrations.openai import OpenAIInferenceProvider
from personal_markets.ports import InferenceRequest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "benchmarks" / "oulad_completion_v1" / "openai_baseline_contract.json"
CACHE_DIR = ROOT / ".artifacts" / "openai_baseline_cache"
PROMPT_VERSION = "openai_probability_baseline_v1"


def _case_id(row: pd.Series) -> str:
    return f"{row.code_module}-{row.code_presentation}-{row.id_student}-{int(row.checkpoint_day)}"


def _cache_key(case_id: str, model: str) -> str:
    blob = f"{case_id}|{PROMPT_VERSION}|{model}|json_schema"
    return hashlib.sha256(blob.encode()).hexdigest()


def _estimate(n: int, model: str) -> float:
    return n * estimate_cost_usd(model, 700, 40)


async def _predict(
    provider: OpenAIInferenceProvider, model: str, features: dict[str, Any]
) -> dict[str, Any]:
    request = InferenceRequest(
        instructions=(
            "Estimate the probability that this anonymized online-course enrollment ends in "
            "Pass or Distinction. Use only the supplied pre-checkpoint features. Return one JSON "
            "object matching the schema. Do not invent evidence."
        ),
        input={"features": features, "checkpoint_day": features.get("checkpoint_day")},
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["probability"],
            "properties": {"probability": {"type": "number", "minimum": 0, "maximum": 1}},
        },
        model=model,
        pool="premium",
        agent_name="baseline",
    )
    response = await provider.complete_structured(request)
    probability = float(response.structured_output["probability"])
    if not 0 <= probability <= 1:
        raise ValueError("baseline probability out of range")
    usage = dict(response.usage)
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return {
        "probability": probability,
        "model": response.model,
        "usage": usage,
        "request_id": response.request_id,
        "latency_ms": response.latency_ms,
        "estimated_cost_usd": estimate_cost_usd(model, input_tokens, output_tokens),
    }


def _write_result(payload: dict[str, Any]) -> Path:
    out = ROOT / "benchmarks" / "oulad_completion_v1" / "openai_baseline_result.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


async def _run_async(
    contract: dict[str, Any],
    model: str,
    api_key: str,
    rows: pd.DataFrame,
    columns: list[str],
) -> dict[str, Any]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    budget = TokenBudget(
        InMemoryUsageStore(),
        high_volume_limit=2_500_000,
        premium_limit=250_000,
        max_cost_usd=float(contract["estimated_cost_guard_usd"]),
    )
    provider = OpenAIInferenceProvider(
        api_key=api_key,
        default_model=model,
        budget=budget,
        max_concurrency=int(contract.get("max_concurrency") or 2),
        max_output_tokens=80,
    )

    async def _one(row: pd.Series) -> tuple[str, dict[str, Any], int]:
        case_id = _case_id(row)
        cache_path = CACHE_DIR / f"{_cache_key(case_id, model)}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            features = {column: row[column] for column in columns if column in row}
            features = {
                key: (value.item() if hasattr(value, "item") else value)
                for key, value in features.items()
            }
            cached = await _predict(provider, model, features)
            cache_path.write_text(json.dumps(cached, default=str) + "\n", encoding="utf-8")
        return case_id, cached, int(row.outcome)

    completed = await asyncio.gather(*[_one(row) for _, row in rows.iterrows()])
    predictions = [{"case_id": case_id, **cached} for case_id, cached, _outcome in completed]
    y = [outcome for _case_id, _cached, outcome in completed]
    p = [float(cached["probability"]) for _case_id, cached, _outcome in completed]
    actual_cost = sum(float(item.get("estimated_cost_usd") or 0) for item in predictions)
    return {
        "status": "executed",
        "contract": contract["name"],
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "n": len(predictions),
        "brier": brier_score(y, p),
        "predictions_written": len(predictions),
        "estimated_cost_usd": round(actual_cost, 6),
        "predictions": [
            {
                "case_id": item["case_id"],
                "probability": item["probability"],
                "model": item["model"],
                "usage": item.get("usage") or {},
                "estimated_cost_usd": item.get("estimated_cost_usd"),
            }
            for item in predictions
        ],
    }


def main() -> int:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    settings = get_settings()
    key = settings.openai_api_key
    model = settings.openai_baseline_model or settings.openai_model
    if not key or not model:
        payload = {
            "status": "not_executed",
            "reason": (
                "PM_OPENAI_API_KEY and PM_OPENAI_BASELINE_MODEL or "
                "PM_OPENAI_MODEL are required"
            ),
            "contract": contract["name"],
            "predictions_written": 0,
        }
        _write_result(payload)
        print(json.dumps(payload), file=sys.stderr)
        return 2
    manifest = json.loads(
        (ROOT / "benchmarks" / "oulad_completion_v1" / "benchmark_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    artifact = ROOT / ".artifacts" / "oulad_completion_v1" / manifest["feature_artifact"]
    if not artifact.exists():
        payload = {
            "status": "not_executed",
            "reason": "Frozen OULAD feature artifact is not present on this machine",
            "contract": contract["name"],
            "predictions_written": 0,
        }
        _write_result(payload)
        print(json.dumps(payload), file=sys.stderr)
        return 2
    frame = pd.read_pickle(artifact)
    test = frame[frame.split == "test"].copy()
    max_cases = int(contract.get("max_cases") or 200)
    subset = test.sort_values(["id_student", "checkpoint_day"]).head(max_cases)
    estimate = _estimate(len(subset), model)
    print(
        json.dumps(
            {
                "status": "cost_estimate",
                "n": len(subset),
                "model": model,
                "estimated_cost_usd": round(estimate, 4),
                "guard_usd": contract["estimated_cost_guard_usd"],
            }
        )
    )
    if estimate > float(contract["estimated_cost_guard_usd"]):
        subset = subset.head(
            max(25, int(len(subset) * contract["estimated_cost_guard_usd"] / estimate))
        )
        estimate = _estimate(len(subset), model)
        print(
            json.dumps(
                {
                    "status": "subset_after_guard",
                    "n": len(subset),
                    "estimated_cost_usd": round(estimate, 4),
                }
            )
        )
    columns = [column for column in manifest["feature_columns"] if column in subset.columns]
    try:
        result = asyncio.run(_run_async(contract, model, key, subset, columns))
    except Exception as error:
        payload = {
            "status": "not_executed",
            "reason": type(error).__name__,
            "contract": contract["name"],
            "model": model,
            "n": len(subset),
            "predictions_written": 0,
        }
        _write_result(payload)
        print(json.dumps(payload), file=sys.stderr)
        return 2
    _write_result(result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
