"""Live Goal Architect on unseen prompts (not in frozen fixtures)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "hackathon_proof_v2" / "unseen_goal_architect.json"
API = os.environ.get("PM_API_BASE", "http://127.0.0.1:8000")

# Deliberately not the canonical career/running/finance/newsletter fixtures.
UNSEEN = [
    "Qualify for USAPL raw nationals by hitting a 500 kg total at a sanctioned meet in 2027",
    "Ship a bilingual children's picture book with a traditional publisher by next fall",
    "Cut my household Scope 2 electricity kgCO2e by 30% versus last year by December 2027",
    "Win a regional amateur salsa competition before I turn 30",
    "Get a vintage motorcycle restored and registered street-legal in Ontario by June 2027",
]


def _summarize(body: dict) -> dict:
    interrupt = body.get("interrupt") or {}
    proposal = interrupt.get("proposal") or {}
    goal = body.get("goal") or {}
    pricing = body.get("pricing") or {}
    invented = []
    for key in ("raw_probability", "calibrated_probability"):
        value = pricing.get(key)
        if value not in (None, 0, 0.0) and not pricing.get("priced"):
            invented.append(key)
    return {
        "input_status": body.get("status"),
        "current_step": body.get("current_step"),
        "interrupt_type": interrupt.get("type"),
        "contract_title": proposal.get("title") or goal.get("title"),
        "goal_type": proposal.get("goal_type") or goal.get("goal_type"),
        "success_metric": proposal.get("success_metric") or (goal.get("success_definition") or {}).get("metric"),
        "deadline": proposal.get("deadline") or goal.get("deadline"),
        "model_family": (pricing.get("receipt") or {}).get("model_family")
        or pricing.get("model_family")
        or goal.get("forecast_status"),
        "forecast_status": pricing.get("forecast_status") or goal.get("forecast_status"),
        "priced": pricing.get("priced"),
        "clarification": interrupt.get("type") == "clarification",
        "clarification_message": interrupt.get("message") if interrupt.get("type") == "clarification" else None,
        "unsupported_fact_invented": bool(invented),
        "invented_fields": invented,
        "limitations": pricing.get("limitations") or [],
    }


def run_one(client: httpx.Client, prompt: str) -> dict:
    started = client.post(
        f"{API}/api/v1/agent/threads",
        json={"kind": "create_goal", "intent": prompt},
        timeout=180,
    )
    row = {
        "input": prompt,
        "http_start": started.status_code,
        "start_error": None if started.status_code < 400 else started.text[:800],
    }
    if started.status_code >= 400:
        return row
    body = started.json()
    thread_id = body.get("thread_id")
    # Confirm if a contract is ready; answer clarifications minimally then confirm.
    for _ in range(4):
        interrupt = body.get("interrupt") or {}
        if interrupt.get("type") == "clarification":
            answers = {
                str(q.get("id")): "Use a reasonable default implied by the stated goal."
                for q in interrupt.get("questions") or []
            }
            resumed = client.post(
                f"{API}/api/v1/agent/threads/{thread_id}/resume",
                json={"answers": answers},
                timeout=180,
            )
            row["http_resume"] = resumed.status_code
            if resumed.status_code >= 400:
                row["resume_error"] = resumed.text[:800]
                break
            body = resumed.json()
            continue
        if interrupt.get("type") == "confirm_contract":
            resumed = client.post(
                f"{API}/api/v1/agent/threads/{thread_id}/resume",
                json={"confirmed": True},
                timeout=180,
            )
            row["http_resume"] = resumed.status_code
            if resumed.status_code >= 400:
                row["resume_error"] = resumed.text[:800]
                break
            body = resumed.json()
            continue
        break
    row["thread_id"] = thread_id
    row.update(_summarize(body))
    return row


def main() -> None:
    results = []
    with httpx.Client() as client:
        health = client.get(f"{API}/health", timeout=10)
        if health.status_code != 200:
            raise SystemExit(f"API unhealthy: {health.status_code}")
        for prompt in UNSEEN:
            results.append(run_one(client, prompt))
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "api": API,
        "n": len(results),
        "note": "Live Goal Architect on prompts absent from frozen fixtures. No fixture-matching required.",
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"n": len(results), "out": str(OUT), "statuses": [r.get("input_status") for r in results]}, indent=2))


if __name__ == "__main__":
    main()
