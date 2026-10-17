"""GPT vs greedy vs oracle action ranking on the model-consistent hiring grid.

NON-CAUSAL. Oracle is the simulator from action_policy_results.json, not a new RCT.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from personal_markets.agents.budget import TokenBudget
from personal_markets.agents.models import estimate_cost_usd
from personal_markets.core.config import get_settings
from personal_markets.integrations.openai import OpenAIInferenceProvider
from personal_markets.persistence.agent_store import InMemoryUsageStore
from personal_markets.ports import InferenceRequest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "hackathon_proof_v2" / "action_policy_results.json"
OUT = ROOT / "benchmarks" / "hackathon_proof_v2" / "action_ranking_gpt_vs_pio.json"
N_CASES = 12


async def main() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    cases = list(policy.get("cases") or [])[:N_CASES]
    settings = get_settings()
    if not settings.openai_api_key:
        OUT.write_text(
            json.dumps(
                {
                    "status": "skipped_no_openai_key",
                    "captured_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("skipped: no openai key")
        return

    budget = TokenBudget(
        InMemoryUsageStore(),
        settings.openai_daily_token_budget_high_volume,
        settings.openai_daily_token_budget_premium,
        settings.openai_max_cost_usd,
    )
    provider = OpenAIInferenceProvider(
        api_key=settings.openai_api_key,
        default_model=settings.openai_baseline_model,
        budget=budget,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_output_tokens=settings.openai_max_output_tokens,
    )
    rows = []
    for case in cases:
        actions = case.get("actions") or []
        ids = [str(a["id"]) for a in actions]
        catalog = [{"id": a["id"], "label": a["label"], "hours_cost": a["hours_cost"]} for a in actions]
        response = await provider.complete_structured(
            InferenceRequest(
                instructions=(
                    "Choose ONE action to improve hiring-offer odds under an hours budget. "
                    "Return only an action_id from the catalog."
                ),
                input={
                    "budget_hours": case.get("budget_hours"),
                    "actions": catalog,
                },
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["action_id", "reason"],
                    "properties": {
                        "action_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
                model=settings.openai_baseline_model,
                pool="premium",
                agent_name="proof_gpt_action_rank",
            )
        )
        gpt_id = str((response.structured_output or {}).get("action_id") or "")
        if gpt_id not in ids:
            blob = json.dumps(response.structured_output or {}).lower()
            gpt_id = next((action_id for action_id in ids if action_id.lower() in blob), "")
        oracle_id = case.get("best_action_id")
        greedy_id = (case.get("top1") or {}).get("greedy_choice")
        rows.append(
            {
                "case_id": case.get("case_id"),
                "budget_hours": case.get("budget_hours"),
                "oracle": oracle_id,
                "greedy": greedy_id,
                "gpt": gpt_id,
                "gpt_match_oracle": gpt_id == oracle_id,
                "greedy_match_oracle": greedy_id == oracle_id,
                "estimated_cost_usd": estimate_cost_usd(
                    response.model,
                    int(response.usage.get("input_tokens", 0)),
                    int(response.usage.get("output_tokens", 0)),
                ),
            }
        )

    n = len(rows)
    payload = {
        "captured_at": datetime.now(UTC).isoformat(),
        "label": "NON-CAUSAL / MODEL-CONSISTENT",
        "status": "ok",
        "n": n,
        "gpt_top1": sum(1 for row in rows if row["gpt_match_oracle"]) / n if n else 0,
        "greedy_top1": sum(1 for row in rows if row["greedy_match_oracle"]) / n if n else 0,
        "oracle_top1": 1.0,
        "note": (
            "GPT asked to pick one action under the hours budget. Oracle is the hiring "
            "simulator from action_policy_results.json, not a randomized trial. "
            "Greedy is uplift/hour from the same simulator (Play It Out numerical policy)."
        ),
        "rows": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("n", "gpt_top1", "greedy_top1", "label")}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
