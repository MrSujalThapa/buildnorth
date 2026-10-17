"""Pass 6 What If parse→simulate matrix across domains (live OpenAI + numerical MC)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from personal_markets.main import app

# Seeded demo goals from local fixtures
CAREER = "20000000-0000-0000-0000-000000000002"
RUNNING = "20000000-0000-0000-0000-000000000004"
FINANCE = "20000000-0000-0000-0000-000000000003"

CASES = [
    {"id": "linkedin", "goal_id": CAREER, "text": "What if I post on LinkedIn 4 times a week?"},
    {"id": "mock-interviews", "goal_id": CAREER, "text": "What if I do 3 mock interviews a week?"},
    {"id": "applications", "goal_id": CAREER, "text": "What if I send 15 more applications a week?"},
    {"id": "running", "goal_id": RUNNING, "text": "What if I run 40 km a week?"},
    {"id": "finance", "goal_id": FINANCE, "text": "What if I invest $1500 per month?"},
    {
        "id": "novel-research",
        "goal_id": CAREER,
        "text": "What if I attend two industry networking events every month for the next quarter?",
    },
]


def summarize_parse(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "understood_action": body.get("understood_action"),
        "pricing_status": body.get("pricing_status"),
        "effect_assigned": body.get("effect_assigned"),
        "changes": body.get("changes"),
        "mechanism": body.get("mechanism"),
        "research_claims": body.get("research_claims"),
        "limitations": body.get("limitations"),
        "unsupported": body.get("unsupported"),
        "agent_run_id": body.get("agent_run_id"),
    }


def summarize_sim(body: dict[str, Any]) -> dict[str, Any]:
    receipt = body.get("receipt") or {}
    return {
        "priced": body.get("priced"),
        "status": body.get("status"),
        "baseline_probability": body.get("baseline_probability"),
        "scenario_probability": body.get("scenario_probability") or body.get("probability"),
        "uplift": body.get("uplift"),
        "uncertainty": {
            "mc_error": (body.get("diagnostics") or {}).get("achieved_mc_error"),
            "n_draws": (body.get("diagnostics") or {}).get("n_draws"),
            "converged": (body.get("diagnostics") or {}).get("converged"),
        },
        "distribution_bins": len(body.get("distribution_bins") or []),
        "assumptions_provenance": [
            {"id": a.get("id") or a.get("name"), "source": a.get("source"), "value": a.get("value")}
            for a in (body.get("assumptions") or [])[:12]
        ],
        "receipt_keys": sorted(receipt.keys()) if isinstance(receipt, dict) else [],
        "limitations": body.get("limitations"),
        "total_latency_ms": body.get("total_latency_ms"),
    }


async def run_case(client: AsyncClient, case: dict[str, str]) -> dict[str, Any]:
    goal_id = case["goal_id"]
    baseline = await client.get(f"/api/v1/what-if/baseline-state/{goal_id}", timeout=120)
    baseline_body = baseline.json() if baseline.status_code == 200 else {"error": baseline.text[:500]}
    parsed = await client.post(
        "/api/v1/what-if/parse-intervention",
        json={"goal_id": goal_id, "text": case["text"]},
        timeout=180,
    )
    parse_body = parsed.json() if parsed.status_code < 500 else {"raw": parsed.text[:2000]}
    if not isinstance(baseline_body, dict) or not baseline_body.get("priced"):
        return {
            "id": case["id"],
            "text": case["text"],
            "goal_id": goal_id,
            "baseline_status": baseline.status_code,
            "baseline": baseline_body,
            "parse_status": parsed.status_code,
            "parse": summarize_parse(parse_body) if isinstance(parse_body, dict) else parse_body,
            "simulate": {"skipped": "baseline not priced"},
        }

    request = {
        "goal_id": goal_id,
        "current_value": baseline_body.get("current_value") or 0,
        "target_value": baseline_body.get("target_value") or 1,
        "periods": baseline_body.get("periods") or 12,
        "direction": baseline_body.get("direction") or "at_least",
        "assumptions": baseline_body.get("assumptions") or [],
        "parsed_changes": parse_body.get("changes") if isinstance(parse_body, dict) else [],
        "intervention": baseline_body.get("default_intervention"),
        "config": baseline_body.get("config") or {"n_draws": 4000, "seed": 20260830},
    }
    sim = await client.post("/api/v1/what-if/simulate", json=request, timeout=180)
    sim_body = sim.json() if sim.status_code < 500 else {"raw": sim.text[:2000]}
    return {
        "id": case["id"],
        "text": case["text"],
        "goal_id": goal_id,
        "baseline_status": baseline.status_code,
        "baseline_priced": True,
        "baseline_probability_hint": baseline_body.get("probability"),
        "parse_status": parsed.status_code,
        "parse": summarize_parse(parse_body) if isinstance(parse_body, dict) else parse_body,
        "simulate_status": sim.status_code,
        "simulate": summarize_sim(sim_body) if isinstance(sim_body, dict) else sim_body,
    }


async def main() -> None:
    transport = ASGITransport(app=app)
    results: list[dict[str, Any]] = []
    async with AsyncClient(transport=transport, base_url="http://test", timeout=600) as client:
        async with app.router.lifespan_context(app):
            goals = await client.get("/api/v1/goals")
            goal_ids = [g.get("goal_id") for g in (goals.json() if goals.status_code == 200 else [])]
            for case in CASES:
                if case["goal_id"] not in goal_ids and goal_ids:
                    # map by title heuristics if fixture IDs differ
                    pass
                results.append(await run_case(client, case))
    out = {
        "captured_at": datetime.now(UTC).isoformat(),
        "goal_ids_available": goal_ids if goals.status_code == 200 else [],
        "cases": results,
    }
    path = Path(__file__).resolve().parents[1] / "benchmarks" / "pass6_eval_v1" / "whatif_simulate_matrix.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
