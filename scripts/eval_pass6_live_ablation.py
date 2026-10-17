"""Live frozen A–G ablation for Pass 6 (real OpenAI, no scripted provider)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uuid import UUID

from personal_markets.agents.budget import TokenBudget
from personal_markets.agents.critic import deterministic_critic, merge_critic_decision
from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.models import estimate_cost_usd, ladders
from personal_markets.agents.prompts import load_prompt
from personal_markets.core.config import get_settings
from personal_markets.integrations.openai import OpenAIInferenceProvider
from personal_markets.persistence.agent_store import InMemoryUsageStore
from personal_markets.ports import (
    CriticArtifact,
    EvidenceAgentProposal,
    EvidenceEventProposal,
    GoalArchitectProposal,
    InferenceRequest,
    InterventionAgentProposal,
    PricingResult,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "benchmarks" / "pass6_eval_v1" / "cases.json").read_text(encoding="utf-8"))


def _provider() -> OpenAIInferenceProvider:
    settings = get_settings()
    store = InMemoryUsageStore()
    budget = TokenBudget(
        store,
        settings.openai_daily_token_budget_high_volume,
        settings.openai_daily_token_budget_premium,
        settings.openai_max_cost_usd,
    )
    return OpenAIInferenceProvider(
        api_key=settings.openai_api_key or "",
        default_model=settings.openai_goal_model,
        budget=budget,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_output_tokens=settings.openai_max_output_tokens,
    )


async def _complete(provider: OpenAIInferenceProvider, request: InferenceRequest) -> dict[str, Any]:
    started = time.perf_counter()
    response = await provider.complete_structured(request)
    return {
        "output": response.structured_output,
        "model": response.model,
        "usage": response.usage,
        "latency_ms": response.latency_ms or int((time.perf_counter() - started) * 1000),
        "retries": response.retries,
        "request_id": response.request_id,
        "estimated_cost_usd": estimate_cost_usd(
            response.model,
            int(response.usage.get("input_tokens", 0)),
            int(response.usage.get("output_tokens", 0)),
        ),
    }


async def arm_a_raw_gpt(provider: OpenAIInferenceProvider, intent: str) -> dict[str, Any]:
    request = InferenceRequest(
        instructions=(
            "Estimate the probability this goal succeeds. Reply with free-form text including a percent."
        ),
        input={"intent": intent},
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        },
        model=get_settings().openai_baseline_model,
        pool="premium",
        agent_name="ablation_raw",
    )
    result = await _complete(provider, request)
    text = str(result["output"].get("answer") or "")
    result["contains_probability_claim"] = any(ch.isdigit() for ch in text) and (
        "%" in text or "probability" in text.lower() or "chance" in text.lower()
    )
    return result


async def arm_b_structured(provider: OpenAIInferenceProvider, intent: str) -> dict[str, Any]:
    prompt = load_prompt("goal_architect")
    request = InferenceRequest(
        instructions=prompt.text,
        input={"intent": intent},
        output_schema=strict_json_schema(GoalArchitectProposal),
        model=ladders(get_settings())["goal_architect"].primary,
        fallback_models=list(ladders(get_settings())["goal_architect"].fallbacks),
        pool="high_volume",
        agent_name="ablation_structured",
    )
    result = await _complete(provider, request)
    try:
        GoalArchitectProposal.model_validate(result["output"])
        result["schema_valid"] = True
    except Exception as exc:  # noqa: BLE001
        result["schema_valid"] = False
        result["schema_error"] = str(exc)
    return result


async def arm_evidence(provider: OpenAIInferenceProvider, text: str) -> dict[str, Any]:
    prompt = load_prompt("evidence")
    request = InferenceRequest(
        instructions=prompt.text,
        input={"evidence_text": text, "mcp_records": []},
        output_schema=strict_json_schema(EvidenceAgentProposal),
        model=ladders(get_settings())["evidence"].primary,
        fallback_models=list(ladders(get_settings())["evidence"].fallbacks),
        pool="high_volume",
        agent_name="ablation_evidence",
    )
    result = await _complete(provider, request)
    try:
        proposal = EvidenceAgentProposal.model_validate(result["output"])
        result["schema_valid"] = True
        result["event_count"] = len(proposal.events)
        result["hallucinated_probability"] = any(
            "probab" in (event.summary or "").lower() for event in proposal.events
        )
    except Exception as exc:  # noqa: BLE001
        result["schema_valid"] = False
        result["schema_error"] = str(exc)
    return result


async def arm_intervention(provider: OpenAIInferenceProvider, text: str) -> dict[str, Any]:
    prompt = load_prompt("intervention")
    request = InferenceRequest(
        instructions=prompt.text,
        input={
            "intervention_text": text,
            "goal": {"goal_type": "deadline_event", "title": "career offer"},
            "baseline_state": {},
            "allowed_metrics": ["weekly_application_rate", "linkedin_posts_per_week", "mock_interviews_per_week"],
            "goal_domain": "career",
            "research": {"claims": []},
            "state_dimensions": ["application_pipeline"],
        },
        output_schema=strict_json_schema(InterventionAgentProposal),
        model=ladders(get_settings())["intervention"].primary,
        fallback_models=list(ladders(get_settings())["intervention"].fallbacks),
        pool="high_volume",
        agent_name="ablation_intervention",
    )
    result = await _complete(provider, request)
    try:
        proposal = InterventionAgentProposal.model_validate(result["output"])
        result["schema_valid"] = True
        result["pricing_status"] = proposal.pricing_status
        result["change_count"] = len(proposal.changes)
        result["claims_unsupported"] = len(proposal.unsupported) > 0
        result["assigns_numeric_odds"] = any(
            "probab" in str(item).lower() or "odds" in str(item).lower() for item in proposal.changes
        )
    except Exception as exc:  # noqa: BLE001
        result["schema_valid"] = False
        result["schema_error"] = str(exc)
    return result


def arm_critic_checks() -> dict[str, Any]:
    from datetime import timedelta

    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    leak = EvidenceEventProposal(
        event_type="assessment",
        domain="academic",
        metric="score",
        numeric_value=0.9,
        observed_at=future,
        summary="future exam",
        source_type="manual",
    )
    pricing = PricingResult(
        priced=True,
        forecast_status="EXPLORATORY",
        raw_probability=0.4,
        calibrated_probability=0.4,
        limitations=[],
        receipt={},
    )
    issues = deterministic_critic([leak], ["e1"], pricing)
    llm = CriticArtifact(decision="publish", issues=[], limitations=[], required_actions=[])
    merged = merge_critic_decision(issues, llm, priced=True)
    return {
        "deterministic_issues": issues,
        "merged_decision": merged.decision,
        "vetoes_leakage": "Future leakage" in " ".join(issues) or merged.decision == "withhold",
    }


async def main() -> None:
    os.environ.setdefault("PM_OPENAI_DAILY_TOKEN_BUDGET_HIGH_VOLUME", "15000000")
    os.environ.setdefault("PM_OPENAI_MAX_COST_USD", "25")
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("PM_OPENAI_API_KEY required for live ablation")

    provider = _provider()
    goal_cases = CASES["goal_architect"][:4]
    evidence_texts = [
        "I solved 14 LeetCode mediums this week and failed a Meta phone screen.",
        "Ran 8km this morning",
        "I maybe kind of did some practice",
    ]
    intervention_texts = [item["text"] for item in CASES["interventions"][:4]]

    report: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "suite": "pass6_eval_v1_live_ablation",
        "models": {
            "baseline": settings.openai_baseline_model,
            "goal": settings.openai_goal_model,
            "evidence": settings.openai_evidence_model,
            "research": settings.openai_research_model,
            "critic": settings.openai_critic_model,
        },
        "A_raw_gpt": [],
        "B_structured_gpt": [],
        "C_statistical_note": "OULAD shared-200 remains the statistical baseline (Brier 0.1579936 selected numerical vs 0.2227995 GPT).",
        "D_agent_evidence": [],
        "E_intervention_with_schema": [],
        "F_critic_validation": arm_critic_checks(),
        "G_full_play_it_out_pointer": "benchmarks/pass6_eval_v1/github_evidence_forecast.json + whatif_simulate_matrix.json",
    }

    for case in goal_cases:
        report["A_raw_gpt"].append({"id": case["id"], **(await arm_a_raw_gpt(provider, case["intent"]))})
        report["B_structured_gpt"].append({"id": case["id"], **(await arm_b_structured(provider, case["intent"]))})

    for text in evidence_texts:
        report["D_agent_evidence"].append({"text": text, **(await arm_evidence(provider, text))})

    for text in intervention_texts:
        report["E_intervention_with_schema"].append({"text": text, **(await arm_intervention(provider, text))})

    report["summary"] = {
        "A_probability_claim_rate": sum(1 for row in report["A_raw_gpt"] if row.get("contains_probability_claim"))
        / max(len(report["A_raw_gpt"]), 1),
        "B_schema_valid_rate": sum(1 for row in report["B_structured_gpt"] if row.get("schema_valid"))
        / max(len(report["B_structured_gpt"]), 1),
        "D_schema_valid_rate": sum(1 for row in report["D_agent_evidence"] if row.get("schema_valid"))
        / max(len(report["D_agent_evidence"]), 1),
        "D_hallucinated_probability_rate": sum(
            1 for row in report["D_agent_evidence"] if row.get("hallucinated_probability")
        )
        / max(len(report["D_agent_evidence"]), 1),
        "E_effect_assigned_rate": sum(
            1 for row in report["E_intervention_with_schema"] if row.get("pricing_status") == "PRICED"
        )
        / max(len(report["E_intervention_with_schema"]), 1),
        "E_unsupported_claim_rate": sum(
            1 for row in report["E_intervention_with_schema"] if row.get("claims_unsupported")
        )
        / max(len(report["E_intervention_with_schema"]), 1),
        "F_critic_vetoes_leakage": report["F_critic_validation"].get("vetoes_leakage"),
    }

    out = ROOT / "benchmarks" / "pass6_eval_v1" / "live_ablation_ag.json"
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(out), "summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
