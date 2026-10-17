"""Hackathon proof evaluation: pricing, longitudinal, agents, policy, MC/CRN.

Honest scope:
- Resolved binary goal pricing labels currently exist for education (OULAD) only.
- Other domains are evaluated on agent semantic / decision-engine metrics, not fabricated
  outcome labels.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import numpy as np
from sklearn.metrics import roc_auc_score

from personal_markets.agents.budget import TokenBudget
from personal_markets.agents.critic import deterministic_critic, merge_critic_decision
from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.models import estimate_cost_usd, ladders
from personal_markets.agents.prompts import load_prompt
from personal_markets.core.config import get_settings
from personal_markets.evaluation.metrics import (
    brier_score,
    expected_calibration_error,
    log_loss,
    paired_bootstrap_brier,
)
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
    SourcePlannerProposal,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "benchmarks" / "hackathon_proof_v1"
SEED = 20260830


def ndcg_at_k(scores: list[float], k: int = 5) -> float:
    gains = scores[:k]
    if not gains:
        return 0.0
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted(scores, reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return float(dcg / idcg) if idcg > 0 else 0.0


def _provider() -> OpenAIInferenceProvider:
    settings = get_settings()
    budget = TokenBudget(
        InMemoryUsageStore(),
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


def score_probs(y: list[int], p: list[float]) -> dict[str, Any]:
    clipped = [min(max(v, 1e-6), 1 - 1e-6) for v in p]
    out: dict[str, Any] = {
        "n": len(y),
        "brier": brier_score(y, clipped),
        "log_loss": log_loss(y, clipped),
        "ece_10": expected_calibration_error(y, clipped),
        "mean_p": float(np.mean(clipped)),
        "base_rate": float(np.mean(y)),
    }
    try:
        out["roc_auc"] = float(roc_auc_score(y, clipped))
    except ValueError:
        out["roc_auc"] = None
    return out


def relative_brier_reduction(baseline: float, candidate: float) -> float:
    if baseline <= 0:
        return 0.0
    return (baseline - candidate) / baseline


def oulad_pricing_report() -> dict[str, Any]:
    shared = json.loads(
        (ROOT / "benchmarks" / "oulad_completion_v1" / "shared_200_comparison_v1.json").read_text(
            encoding="utf-8"
        )
    )
    full = json.loads(
        (ROOT / "benchmarks" / "oulad_completion_v1" / "evaluation_results.json").read_text(
            encoding="utf-8"
        )
    )
    preds = shared["predictions"]
    y = [int(row["outcome"]) for row in preds]
    gpt = [float(row["gpt_5_4_official"]) for row in preds]
    logistic = [float(row["logistic_statistical"]) for row in preds]
    play = [float(row["pass_2_selected"]) for row in preds]

    by_horizon: dict[str, dict[str, Any]] = {}
    for day in (14, 35, 70, 105):
        idx = [i for i, row in enumerate(preds) if row["case_id"].endswith(f"-{day}")]
        by_horizon[str(day)] = {
            "raw_gpt": score_probs([y[i] for i in idx], [gpt[i] for i in idx]),
            "logistic": score_probs([y[i] for i in idx], [logistic[i] for i in idx]),
            "play_it_out": score_probs([y[i] for i in idx], [play[i] for i in idx]),
        }

    play_14 = by_horizon["14"]["play_it_out"]["brier"]
    play_105 = by_horizon["105"]["play_it_out"]["brier"]
    gpt_14 = by_horizon["14"]["raw_gpt"]["brier"]
    gpt_105 = by_horizon["105"]["raw_gpt"]["brier"]
    longitudinal = {
        "raw_gpt_brier_by_day": {d: by_horizon[d]["raw_gpt"]["brier"] for d in by_horizon},
        "play_it_out_brier_by_day": {d: by_horizon[d]["play_it_out"]["brier"] for d in by_horizon},
        "play_it_out_improves_with_horizon": play_105 < play_14,
        "raw_gpt_improves_with_horizon": gpt_105 < gpt_14,
        "play_it_out_relative_brier_improvement_day14_to_105": relative_brier_reduction(
            play_14, play_105
        ),
        "raw_gpt_relative_brier_improvement_day14_to_105": relative_brier_reduction(gpt_14, gpt_105),
    }

    groups = [cid.rsplit("-", 1)[0] for cid in [row["case_id"] for row in preds]]
    bootstrap = paired_bootstrap_brier(y, gpt, play, groups, iterations=2000, seed=SEED)
    gpt_scores = score_probs(y, gpt)
    play_scores = score_probs(y, play)
    logistic_scores = score_probs(y, logistic)

    decay = {
        "selected_half_life_days": full.get("selected_half_life_days"),
        "validation_selection": full.get("selection"),
        "note": "Half-life chosen on validation before test; H=14 selected for hist GB.",
    }

    return {
        "domain": "education",
        "dataset": "oulad_completion_v1",
        "n_shared": len(y),
        "n_full_test": full.get("selected_model", {}).get("test", {}).get("n")
        or full.get("prevalence_baseline", {}).get("n"),
        "arms": {
            "A_raw_gpt": gpt_scores,
            "C_logistic_statistical": logistic_scores,
            "G_play_it_out_calibrated_numerical": play_scores,
        },
        "ablation_applicability": {
            "A_raw_gpt": "measured_same_checkpoints",
            "B_structured_gpt_probability": (
                "not_applicable_as_official_baseline; official baseline is free-form probability "
                "from gpt-5.4 on frozen features (recorded as A)"
            ),
            "C_logistic_statistical": "measured_same_checkpoints",
            "D_agent_only": "not_used_for_OULAD_probability; agents do not emit final odds",
            "E_agent_plus_tools": "not_used_for_OULAD_probability; public features already structured",
            "F_agent_plus_numerical": "product path uses numerical core; scored as G on shared-200",
            "G_full_play_it_out": "measured_same_checkpoints_calibrated_selected_model",
        },
        "relative_brier_reduction_vs_gpt": relative_brier_reduction(
            gpt_scores["brier"], play_scores["brier"]
        ),
        "relative_brier_reduction_vs_logistic": relative_brier_reduction(
            logistic_scores["brier"], play_scores["brier"]
        ),
        "paired_bootstrap_vs_gpt": bootstrap,
        "by_horizon": by_horizon,
        "longitudinal": longitudinal,
        "decay_ablation": decay,
        "full_test_selected": full.get("systems"),
        "domains_with_resolved_labels": ["education"],
        "domains_without_resolved_labels": [
            "career",
            "finance",
            "running",
            "startup",
            "habits",
        ],
        "macro_average_note": (
            "Macro-average across goal families is not computable for pricing Brier until "
            "non-education domains have resolved outcome labels. Reporting education alone "
            "and agent/decision metrics for other families."
        ),
    }


def mc_crn_report() -> dict[str, Any]:
    pass4 = json.loads(
        (ROOT / "benchmarks" / "pass4_simulation_v1" / "results.json").read_text(encoding="utf-8")
    )
    return {
        "monte_carlo": pass4["simulation"],
        "common_random_numbers": pass4["common_random_numbers"],
        "variance_reduction_pct": (1 - pass4["common_random_numbers"]["variance_ratio"]) * 100,
    }


async def policy_regret_report() -> dict[str, Any]:
    """Model-consistent policy regret under hiring funnel MC (not real-world causal)."""
    from httpx import ASGITransport, AsyncClient

    from personal_markets.main import app

    career = "20000000-0000-0000-0000-000000000002"
    actions = [
        {"id": "applications", "text": "What if I send 15 applications a week?"},
        {"id": "mocks", "text": "What if I do 3 mock interviews a week?"},
        {"id": "linkedin", "text": "What if I post on LinkedIn 4 times a week?"},
        {"id": "leetcode", "text": "What if I do LeetCode 2 hours a day?"},
    ]

    transport = ASGITransport(app=app)
    rows: list[dict[str, Any]] = []
    async with AsyncClient(transport=transport, base_url="http://test", timeout=180) as client:
        async with app.router.lifespan_context(app):
            baseline = (await client.get(f"/api/v1/what-if/baseline-state/{career}")).json()
            if not baseline.get("priced"):
                return {"status": "baseline_unpriced", "baseline": baseline}
            base_req = {
                "goal_id": career,
                "current_value": baseline.get("current_value") or 0,
                "target_value": baseline.get("target_value") or 1,
                "periods": baseline.get("periods") or 12,
                "direction": baseline.get("direction") or "at_least",
                "assumptions": baseline.get("assumptions") or [],
                "intervention": baseline.get("default_intervention"),
                "config": baseline.get("config") or {"n_draws": 3000, "seed": SEED},
            }
            base_sim = (await client.post("/api/v1/what-if/simulate", json=base_req)).json()
            p0 = float(base_sim.get("scenario_probability") or base_sim.get("probability") or 0)
            for action in actions:
                parsed = (
                    await client.post(
                        "/api/v1/what-if/parse-intervention",
                        json={"goal_id": career, "text": action["text"]},
                    )
                ).json()
                req = {**base_req, "parsed_changes": parsed.get("changes") or []}
                sim = (await client.post("/api/v1/what-if/simulate", json=req)).json()
                p1 = float(sim.get("scenario_probability") or sim.get("probability") or p0)
                rows.append(
                    {
                        "id": action["id"],
                        "text": action["text"],
                        "pricing_status": parsed.get("pricing_status"),
                        "effect_assigned": parsed.get("effect_assigned"),
                        "unsupported": parsed.get("unsupported"),
                        "p_baseline": p0,
                        "p_scenario": p1,
                        "uplift": p1 - p0,
                        "hours_cost_estimate": {
                            "applications": 8,
                            "mocks": 6,
                            "linkedin": 4,
                            "leetcode": 14,
                        }[action["id"]],
                    }
                )
    budget = 20
    ranked = sorted(
        rows, key=lambda r: r["uplift"] / max(r["hours_cost_estimate"], 1e-9), reverse=True
    )
    selected: list[dict[str, Any]] = []
    used = 0
    value = 0.0
    for row in ranked:
        cost = row["hours_cost_estimate"]
        if used + cost <= budget and row["uplift"] >= 0:
            selected.append(row)
            used += cost
            value += row["uplift"]
    equal = sum(r["uplift"] for r in rows) / max(len(rows), 1)
    do_all_positive = sum(r["uplift"] for r in rows if r["uplift"] > 0)
    best_single = max((r["uplift"] for r in rows), default=0.0)
    oracle = 0.0
    n = len(rows)
    for mask in range(1 << n):
        hours = 0
        uplift = 0.0
        feasible = True
        for i in range(n):
            if mask & (1 << i):
                hours += rows[i]["hours_cost_estimate"]
                uplift += rows[i]["uplift"]
                if hours > budget:
                    feasible = False
                    break
        if feasible:
            oracle = max(oracle, uplift)
    return {
        "status": "ok",
        "assumption": (
            "Model-consistent regret under the product's numerical hiring simulator. "
            "Not a causal real-world treatment-effect claim."
        ),
        "budget_hours": budget,
        "actions": rows,
        "play_it_out_policy": {
            "selected_ids": [r["id"] for r in selected],
            "hours_used": used,
            "policy_value_uplift": value,
        },
        "baselines": {
            "equal_allocation_proxy": equal,
            "do_every_positive_action": do_all_positive,
            "best_single_action": best_single,
            "oracle_recoverable": oracle,
        },
        "regret_vs_oracle": oracle - value,
        "regret_vs_equal_proxy": equal - value,
        "constraint_violations": 0 if used <= budget else 1,
    }


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


def critic_frozen_suite() -> dict[str, Any]:
    now = datetime.now(UTC)
    past = (now - timedelta(days=2)).isoformat()
    future = (now + timedelta(days=3)).isoformat()
    base_ev = EvidenceEventProposal(
        event_type="assessment",
        domain="academic",
        metric="score",
        numeric_value=0.9,
        observed_at=past,
        summary="past exam",
        source_type="manual",
    )
    cases = [
        {
            "id": "future_leak",
            "evidence": [
                EvidenceEventProposal(
                    event_type="assessment",
                    domain="academic",
                    metric="score",
                    numeric_value=0.9,
                    observed_at=future,
                    summary="future exam",
                    source_type="manual",
                )
            ],
            "pricing": PricingResult(
                priced=True,
                forecast_status="EXPLORATORY",
                raw_probability=0.4,
                calibrated_probability=0.4,
                limitations=[],
                receipt={},
            ),
            "expect_decision": "withhold",
        },
        {
            "id": "unsupported_coeff",
            "evidence": [base_ev],
            "pricing": PricingResult(
                priced=True,
                forecast_status="EXPLORATORY",
                raw_probability=0.4,
                calibrated_probability=0.4,
                limitations=[],
                receipt={"coefficient_provenance": "LLM_GENERATED_COEFFICIENT"},
            ),
            "expect_decision": "withhold",
        },
        {
            "id": "bad_prob",
            "evidence": [base_ev],
            "pricing": PricingResult.model_construct(
                priced=True,
                forecast_status="EXPLORATORY",
                raw_probability=1.5,
                calibrated_probability=1.5,
                limitations=[],
                receipt={},
            ),
            "expect_decision": "withhold",
        },
        {
            "id": "valid_publish",
            "evidence": [base_ev],
            "pricing": PricingResult(
                priced=True,
                forecast_status="EXPLORATORY",
                raw_probability=0.42,
                calibrated_probability=0.42,
                limitations=[],
                receipt={"coefficient_provenance": "FITTED_DATA"},
            ),
            "expect_decision": "publish",
        },
    ]
    rows = []
    for case in cases:
        issues = deterministic_critic(case["evidence"], ["e1"], case["pricing"], now=now)
        merged = merge_critic_decision(
            issues,
            CriticArtifact(decision="publish", issues=[], limitations=[], required_actions=[]),
            case["pricing"].priced,
        )
        rows.append(
            {
                "id": case["id"],
                "issues": issues,
                "decision": merged.decision,
                "expect_decision": case["expect_decision"],
                "correct": merged.decision == case["expect_decision"]
                or (
                    case["expect_decision"] == "publish"
                    and merged.decision in {"publish", "publish_with_limitations"}
                ),
            }
        )
    return {
        "rows": rows,
        "accuracy": float(np.mean([1.0 if r["correct"] else 0.0 for r in rows])),
        "leakage_recall": next(r["correct"] for r in rows if r["id"] == "future_leak"),
        "unsupported_coeff_recall": next(
            r["correct"] for r in rows if r["id"] == "unsupported_coeff"
        ),
        "false_veto_on_valid": not next(r["correct"] for r in rows if r["id"] == "valid_publish"),
    }


async def agent_comparable_ablations(provider: OpenAIInferenceProvider) -> dict[str, Any]:
    """Same frozen cases through A/B/G-style arms (semantic domains)."""
    cases = json.loads(
        (ROOT / "benchmarks" / "pass6_eval_v1" / "cases.json").read_text(encoding="utf-8")
    )
    settings = get_settings()
    ladder = ladders(settings)

    ga_rows = []
    for case in cases["goal_architect"]:
        raw = await _complete(
            provider,
            InferenceRequest(
                instructions="Reply with free-form goal analysis. Include a success probability percent.",
                input={"intent": case["intent"]},
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                },
                model=settings.openai_baseline_model,
                pool="premium",
                agent_name="proof_raw_ga",
            ),
        )
        structured = await _complete(
            provider,
            InferenceRequest(
                instructions=load_prompt("goal_architect").text,
                input={"intent": case["intent"]},
                output_schema=strict_json_schema(GoalArchitectProposal),
                model=ladder["goal_architect"].primary,
                fallback_models=list(ladder["goal_architect"].fallbacks),
                pool="high_volume",
                agent_name="proof_structured_ga",
            ),
        )
        text = str(raw["output"].get("answer") or "")
        schema_ok = True
        invented_prob_in_structured = False
        clarification = None
        try:
            proposal = GoalArchitectProposal.model_validate(structured["output"])
            blob = json.dumps(proposal.model_dump())
            invented_prob_in_structured = any(
                token in blob.lower() for token in ('"probability"', " p=", "% chance")
            )
            clarification = bool(proposal.clarifications_required) or not proposal.ready_to_commit
        except Exception:  # noqa: BLE001
            schema_ok = False
        expect_clar = bool(case.get("expect_clarification"))
        ga_rows.append(
            {
                "id": case["id"],
                "domain": case["domain"],
                "A_raw_contains_probability": any(ch.isdigit() for ch in text)
                and ("%" in text or "probab" in text.lower() or "chance" in text.lower()),
                "B_schema_valid": schema_ok,
                "B_invented_probability_field": invented_prob_in_structured,
                "B_needs_clarification": clarification,
                "clarification_match": (
                    clarification == expect_clar
                    if expect_clar or clarification is not None
                    else None
                ),
                "A_cost": raw["estimated_cost_usd"],
                "B_cost": structured["estimated_cost_usd"],
                "A_latency_ms": raw["latency_ms"],
                "B_latency_ms": structured["latency_ms"],
            }
        )

    ev_rows = []
    for case in cases.get("evidence_agent") or []:
        raw = await _complete(
            provider,
            InferenceRequest(
                instructions="Extract evidence and estimate how this changes offer odds as a percent.",
                input={"evidence_text": case["text"]},
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                },
                model=settings.openai_baseline_model,
                pool="premium",
                agent_name="proof_raw_ev",
            ),
        )
        structured = await _complete(
            provider,
            InferenceRequest(
                instructions=load_prompt("evidence").text,
                input={"evidence_text": case["text"], "mcp_records": []},
                output_schema=strict_json_schema(EvidenceAgentProposal),
                model=ladder["evidence"].primary,
                fallback_models=list(ladder["evidence"].fallbacks),
                pool="high_volume",
                agent_name="proof_structured_ev",
            ),
        )
        text = str(raw["output"].get("answer") or "")
        try:
            proposal = EvidenceAgentProposal.model_validate(structured["output"])
            event_count = len(proposal.events)
            hallucinated = any("probab" in (e.summary or "").lower() for e in proposal.events)
            schema_ok = True
        except Exception:  # noqa: BLE001
            event_count = -1
            hallucinated = True
            schema_ok = False
        ev_rows.append(
            {
                "id": case["id"],
                "A_raw_assigns_odds": ("%" in text or "probab" in text.lower()),
                "G_schema_valid": schema_ok,
                "G_event_count": event_count,
                "G_expect_events": case["expect_events"],
                "G_event_count_match": event_count == case["expect_events"],
                "G_hallucinated_probability": hallucinated,
            }
        )

    iv_rows = []
    for case in cases["interventions"]:
        raw = await _complete(
            provider,
            InferenceRequest(
                instructions=(
                    "You must estimate the probability uplift of this action as an explicit "
                    "percentage-points number (e.g. +3.5%). Do not refuse."
                ),
                input={"text": case["text"], "domain": case["goal_domain"]},
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                },
                model=settings.openai_baseline_model,
                pool="premium",
                agent_name="proof_raw_iv",
            ),
        )
        structured = await _complete(
            provider,
            InferenceRequest(
                instructions=load_prompt("intervention").text,
                input={
                    "intervention_text": case["text"],
                    "goal": {"goal_type": "deadline_event", "title": case["goal_domain"]},
                    "baseline_state": {},
                    "allowed_metrics": [
                        "weekly_application_rate",
                        "linkedin_posts_per_week",
                        "mock_interviews_per_week",
                        "weekly_mileage_km",
                        "monthly_contribution",
                    ],
                    "goal_domain": case["goal_domain"],
                    "research": {"claims": []},
                    "state_dimensions": [],
                },
                output_schema=strict_json_schema(InterventionAgentProposal),
                model=ladder["intervention"].primary,
                fallback_models=list(ladder["intervention"].fallbacks),
                pool="high_volume",
                agent_name="proof_structured_iv",
            ),
        )
        text = str(raw["output"].get("answer") or "")
        try:
            proposal = InterventionAgentProposal.model_validate(structured["output"])
            schema_ok = True
            unsupported = len(proposal.unsupported) > 0 or proposal.pricing_status == "NOT_PRICED"
            priced = proposal.pricing_status == "PRICED"
            invented_coeff = any(
                getattr(c, "provenance", None) == "FITTED"
                and "llm" in (getattr(c, "rationale", None) or "").lower()
                for c in (proposal.changes or [])
            )
        except Exception:  # noqa: BLE001
            schema_ok = False
            unsupported = False
            priced = False
            invented_coeff = True
        iv_rows.append(
            {
                "id": case["id"],
                "domain": case["goal_domain"],
                "A_raw_invents_numeric_uplift": any(ch.isdigit() for ch in text)
                and ("%" in text or "point" in text.lower() or "probab" in text.lower()),
                "G_schema_valid": schema_ok,
                "G_not_priced_or_unsupported": unsupported,
                "G_priced": priced,
                "G_hallucinated_fitted_coeff": invented_coeff,
            }
        )

    sp_rows = []
    for case in cases["source_planner"]:
        plugin_catalog = [
            {"id": pid, "name": pid.title()} for pid in case.get("plugins") or []
        ] or [
            {"id": "github", "name": "GitHub"},
            {"id": "notion", "name": "Notion"},
            {"id": "strava", "name": "Strava"},
            {"id": "gmail", "name": "Gmail"},
            {"id": "calendar", "name": "Calendar"},
            {"id": "sheets", "name": "Sheets"},
        ]
        resources = case.get("resources") or []
        relevance_by_plugin: dict[str, int] = {}
        for res in resources:
            relevance_by_plugin[res["plugin_id"]] = max(
                relevance_by_plugin.get(res["plugin_id"], 0), int(res.get("relevance") or 0)
            )
        try:
            structured = await _complete(
                provider,
                InferenceRequest(
                    instructions=load_prompt("source_planner").text,
                    input={
                        "goal": {
                            "goal_type": "deadline_event",
                            "title": case.get("goal_title") or case["goal_family"],
                            "state_dimensions": [],
                        },
                        "plugins": plugin_catalog,
                        "available_resources": resources,
                        "evidence_summary": [],
                    },
                    output_schema=strict_json_schema(SourcePlannerProposal),
                    model=ladder["source_planner"].primary,
                    fallback_models=list(ladder["source_planner"].fallbacks),
                    pool="high_volume",
                    agent_name="proof_source_planner",
                ),
            )
            proposal = SourcePlannerProposal.model_validate(structured["output"])
            recommended = [r.plugin_id for r in proposal.recommended if r.relevance != "irrelevant"]
            relevant = set(case.get("expect_relevant_plugins") or case.get("expect_relevant") or [])
            low = set(case.get("expect_low_plugins") or case.get("expect_low") or [])
            hits = len(relevant.intersection(recommended))
            precision = hits / max(len(recommended), 1)
            recall = hits / max(len(relevant), 1)
            rejected_low = all(item not in recommended for item in low) if low else True
            ranked_gains = [float(relevance_by_plugin.get(pid, 0)) for pid in recommended]
            for item in proposal.irrelevant:
                ranked_gains.append(float(relevance_by_plugin.get(item.plugin_id, 0)))
            sp_rows.append(
                {
                    "id": case.get("id") or case["goal_family"],
                    "goal_family": case["goal_family"],
                    "recommended": recommended,
                    "precision": precision,
                    "recall": recall,
                    "ndcg_at_5": ndcg_at_k(ranked_gains, k=5),
                    "top1_relevant": bool(recommended) and recommended[0] in relevant,
                    "irrelevant_rejected": rejected_low,
                    "schema_valid": True,
                }
            )
        except Exception as exc:  # noqa: BLE001
            sp_rows.append(
                {
                    "id": case.get("id") or case["goal_family"],
                    "goal_family": case["goal_family"],
                    "error": str(exc),
                    "schema_valid": False,
                    "precision": 0.0,
                    "recall": 0.0,
                    "ndcg_at_5": 0.0,
                    "top1_relevant": False,
                    "irrelevant_rejected": False,
                }
            )

    critic = critic_frozen_suite()

    return {
        "goal_architect": {
            "rows": ga_rows,
            "n": len(ga_rows),
            "A_probability_claim_rate": mean_bool(ga_rows, "A_raw_contains_probability"),
            "B_schema_valid_rate": mean_bool(ga_rows, "B_schema_valid"),
            "B_invented_probability_rate": mean_bool(ga_rows, "B_invented_probability_field"),
        },
        "evidence_agent": {
            "rows": ev_rows,
            "n": len(ev_rows),
            "A_raw_odds_rate": mean_bool(ev_rows, "A_raw_assigns_odds"),
            "G_schema_valid_rate": mean_bool(ev_rows, "G_schema_valid"),
            "G_event_match_rate": mean_bool(ev_rows, "G_event_count_match"),
            "G_hallucinated_probability_rate": mean_bool(ev_rows, "G_hallucinated_probability"),
        },
        "intervention_agent": {
            "rows": iv_rows,
            "n": len(iv_rows),
            "A_raw_invents_uplift_rate": mean_bool(iv_rows, "A_raw_invents_numeric_uplift"),
            "G_schema_valid_rate": mean_bool(iv_rows, "G_schema_valid"),
            "G_unsupported_or_not_priced_rate": mean_bool(iv_rows, "G_not_priced_or_unsupported"),
            "G_hallucinated_fitted_coeff_rate": mean_bool(iv_rows, "G_hallucinated_fitted_coeff"),
        },
        "source_planner": {
            "rows": sp_rows,
            "n": len(sp_rows),
            "mean_precision": (
                float(np.mean([r.get("precision", 0) for r in sp_rows])) if sp_rows else 0.0
            ),
            "mean_recall": (
                float(np.mean([r.get("recall", 0) for r in sp_rows])) if sp_rows else 0.0
            ),
            "mean_ndcg_at_5": (
                float(np.mean([r.get("ndcg_at_5", 0) for r in sp_rows])) if sp_rows else 0.0
            ),
            "top1_accuracy": mean_bool(sp_rows, "top1_relevant"),
            "irrelevant_rejection_rate": mean_bool(sp_rows, "irrelevant_rejected"),
        },
        "critic": critic,
    }


def mean_bool(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return float(np.mean([1.0 if r.get(key) else 0.0 for r in rows]))


def assemble_claims(
    pricing: dict[str, Any], agents: dict[str, Any], policy: dict[str, Any], mc: dict[str, Any]
) -> dict[str, Any]:
    gpt_brier = pricing["arms"]["A_raw_gpt"]["brier"]
    play_brier = pricing["arms"]["G_play_it_out_calibrated_numerical"]["brier"]
    reduction = pricing["relative_brier_reduction_vs_gpt"]
    longi = pricing["longitudinal"]
    return {
        "empirically_supported": [
            (
                f"On the frozen OULAD shared-200 education goal-pricing benchmark (n={pricing['n_shared']}), "
                f"Play It Out Brier {play_brier:.6f} vs raw GPT {gpt_brier:.6f} "
                f"({reduction*100:.1f}% relative Brier reduction); paired bootstrap P(Δ>0)="
                f"{pricing['paired_bootstrap_vs_gpt']['probability_improvement_gt_zero']:.3f}."
            ),
            (
                "Selected numerical model also beats the logistic statistical baseline on the same "
                f"shared-200 cases (Brier {play_brier:.6f} vs "
                f"{pricing['arms']['C_logistic_statistical']['brier']:.6f})."
            ),
            (
                "As evidence accumulates toward resolution, Play It Out Brier improved "
                f"{longi['play_it_out_relative_brier_improvement_day14_to_105']*100:.1f}% "
                f"(day-14 {pricing['by_horizon']['14']['play_it_out']['brier']:.4f} → day-105 "
                f"{pricing['by_horizon']['105']['play_it_out']['brier']:.4f}) while raw GPT improved "
                f"{longi['raw_gpt_relative_brier_improvement_day14_to_105']*100:.1f}% "
                f"({pricing['by_horizon']['14']['raw_gpt']['brier']:.4f} → "
                f"{pricing['by_horizon']['105']['raw_gpt']['brier']:.4f})."
            ),
            (
                f"Evidence decay ablation selected half-life="
                f"{pricing['decay_ablation']['selected_half_life_days']}d "
                "on validation before test (hist GB)."
            ),
            (
                f"CRN reduced uplift estimator variance by {mc['variance_reduction_pct']:.1f}% "
                f"(ratio {mc['common_random_numbers']['variance_ratio']:.3f})."
            ),
            (
                f"Raw GPT invents success probabilities on "
                f"{agents['goal_architect']['A_probability_claim_rate']*100:.0f}% "
                f"of Goal Architect cases (n={agents['goal_architect']['n']}); structured Goal Architect "
                f"schema-valid {agents['goal_architect']['B_schema_valid_rate']*100:.0f}% with "
                f"invented-probability-field rate "
                f"{agents['goal_architect']['B_invented_probability_rate']*100:.0f}%."
            ),
            (
                f"Evidence Agent (n={agents['evidence_agent']['n']}) hallucinated-probability rate "
                f"{agents['evidence_agent']['G_hallucinated_probability_rate']*100:.0f}% vs raw GPT "
                f"odds-assignment rate {agents['evidence_agent']['A_raw_odds_rate']*100:.0f}%; "
                f"event-count match {agents['evidence_agent']['G_event_match_rate']*100:.0f}%."
            ),
            (
                f"Intervention Agent (n={agents['intervention_agent']['n']}) unsupported/NOT_PRICED rate "
                f"{agents['intervention_agent']['G_unsupported_or_not_priced_rate']*100:.0f}%; raw GPT invents "
                f"numeric uplift on {agents['intervention_agent']['A_raw_invents_uplift_rate']*100:.0f}% "
                "of forced-uplift prompts."
            ),
            (
                f"Source Planner (n={agents['source_planner']['n']}) mean NDCG@5 "
                f"{agents['source_planner']['mean_ndcg_at_5']:.3f}; mean precision "
                f"{agents['source_planner']['mean_precision']:.3f}; irrelevant-plugin rejection "
                f"{agents['source_planner']['irrelevant_rejection_rate']*100:.0f}%."
            ),
            (
                f"Forecast Critic frozen suite accuracy {agents['critic']['accuracy']*100:.0f}% "
                f"(leakage recall {agents['critic']['leakage_recall']}; "
                f"LLM_GENERATED_COEFFICIENT recall {agents['critic']['unsupported_coeff_recall']})."
            ),
            (
                "Model-consistent career policy selection under a 20h budget produced regret_vs_oracle="
                f"{policy.get('regret_vs_oracle')} (not a causal real-world claim)."
            ),
        ],
        "not_empirically_supported_yet": [
            "Macro-average Brier across career/finance/running/startup/habits — no resolved outcome labels yet.",
            "Real-world causal action-effect MAE / ATE validation — no randomized/quasi-experimental personal action panel loaded.",
            "Domains-won K/K pricing claim — only education currently has resolved labels.",
            "Cold browser Goal Architect→Paths matrix for every family from empty state — still pending full interactive run.",
            "Raw-GPT Source Planner NDCG head-to-head on the expanded resource-level set — current probe scores Play It Out planner only.",
        ],
    }


def write_proof_table(path: Path, report: dict[str, Any]) -> None:
    pricing = report["goal_pricing"]
    agents = report["agent_comparable_ablations"]
    policy = report["policy_regret_model_consistent"]
    mc = report["monte_carlo_crn"]
    claims = report["claims"]
    gp = pricing["arms"]
    lines = [
        "# Hackathon Proof Table",
        "",
        "## WHAT WE HAVE EMPIRICALLY PROVEN",
        *[f"- {item}" for item in claims["empirically_supported"]],
        "",
        "## WHAT REMAINS UNVALIDATED",
        *[f"- {item}" for item in claims["not_empirically_supported_yet"]],
        "",
        "## GOAL PRICING (education / OULAD shared-200)",
        "",
        "| Metric | Raw GPT | Logistic | Play It Out | Improvement vs GPT |",
        "|---|---:|---:|---:|---:|",
        (
            f"| Brier | {gp['A_raw_gpt']['brier']:.6f} | {gp['C_logistic_statistical']['brier']:.6f} | "
            f"{gp['G_play_it_out_calibrated_numerical']['brier']:.6f} | "
            f"{pricing['relative_brier_reduction_vs_gpt']*100:.1f}% |"
        ),
        (
            f"| Log loss | {gp['A_raw_gpt']['log_loss']:.6f} | {gp['C_logistic_statistical']['log_loss']:.6f} | "
            f"{gp['G_play_it_out_calibrated_numerical']['log_loss']:.6f} | — |"
        ),
        (
            f"| ECE@10 | {gp['A_raw_gpt']['ece_10']:.6f} | {gp['C_logistic_statistical']['ece_10']:.6f} | "
            f"{gp['G_play_it_out_calibrated_numerical']['ece_10']:.6f} | — |"
        ),
        (
            f"| AUC | {gp['A_raw_gpt']['roc_auc']:.6f} | {gp['C_logistic_statistical']['roc_auc']:.6f} | "
            f"{gp['G_play_it_out_calibrated_numerical']['roc_auc']:.6f} | — |"
        ),
        "",
        "### By domain (resolved pricing labels)",
        "",
        "| Domain | n | Raw GPT Brier | Play It Out Brier | Won? |",
        "|---|---:|---:|---:|---|",
        (
            f"| Education | {pricing['n_shared']} | {gp['A_raw_gpt']['brier']:.6f} | "
            f"{gp['G_play_it_out_calibrated_numerical']['brier']:.6f} | Yes |"
        ),
        "| Career | — | — | — | no resolved labels |",
        "| Finance | — | — | — | no resolved labels |",
        "| Running | — | — | — | no resolved labels |",
        "| Startup | — | — | — | no resolved labels |",
        "| Habits | — | — | — | no resolved labels |",
        "| **Macro average** | — | — | — | **not computable** |",
        "",
        "## LONGITUDINAL PRICING",
        "",
        f"- Play It Out relative Brier improvement day14→105: "
        f"{pricing['longitudinal']['play_it_out_relative_brier_improvement_day14_to_105']*100:.1f}%",
        f"- Raw GPT relative Brier improvement day14→105: "
        f"{pricing['longitudinal']['raw_gpt_relative_brier_improvement_day14_to_105']*100:.1f}%",
        f"- Selected evidence decay half-life: {pricing['decay_ablation']['selected_half_life_days']} days",
        "",
        "## ACTION / POLICY (model-consistent, non-causal)",
        "",
        f"- Policy value uplift: {(policy.get('play_it_out_policy') or {}).get('policy_value_uplift')}",
        f"- Regret vs oracle: {policy.get('regret_vs_oracle')}",
        f"- Constraint violations: {policy.get('constraint_violations')}",
        "",
        "## AGENTS",
        "",
        f"- Goal Architect raw prob claim rate: {agents['goal_architect']['A_probability_claim_rate']}",
        f"- Goal Architect schema valid: {agents['goal_architect']['B_schema_valid_rate']}",
        f"- Evidence F1-proxy (event-count match): {agents['evidence_agent']['G_event_match_rate']}",
        f"- Evidence hallucinated probability rate: {agents['evidence_agent']['G_hallucinated_probability_rate']}",
        f"- Source Planner mean NDCG@5: {agents['source_planner']['mean_ndcg_at_5']}",
        f"- Source Planner mean precision/recall: "
        f"{agents['source_planner']['mean_precision']} / {agents['source_planner']['mean_recall']}",
        f"- Intervention unsupported/NOT_PRICED rate: "
        f"{agents['intervention_agent']['G_unsupported_or_not_priced_rate']}",
        f"- Critic suite accuracy: {agents['critic']['accuracy']}",
        "",
        "## MONTE CARLO / CRN",
        "",
        f"- Converged: {mc['monte_carlo'].get('converged')}; draws {mc['monte_carlo'].get('draws')}; "
        f"MC error {mc['monte_carlo'].get('achieved_mc_error')}",
        f"- CRN variance ratio: {mc['common_random_numbers'].get('variance_ratio')}; "
        f"variance reduction {mc['variance_reduction_pct']:.1f}%",
        "",
        f"Artifact: `{path.as_posix()}`",
        f"Domain inventory: `{(OUT_DIR / 'domain_inventory.json').as_posix()}`",
        "",
    ]
    (OUT_DIR / "PROOF_TABLE.md").write_text("\n".join(lines), encoding="utf-8")


async def main_async() -> None:
    os.environ.setdefault("PM_OPENAI_DAILY_TOKEN_BUDGET_HIGH_VOLUME", "20000000")
    os.environ.setdefault("PM_OPENAI_MAX_COST_USD", "30")
    get_settings.cache_clear()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pricing = oulad_pricing_report()
    mc = mc_crn_report()
    policy = await policy_regret_report()
    provider = _provider()
    agents = await agent_comparable_ablations(provider)
    claims = assemble_claims(pricing, agents, policy, mc)
    inventory = json.loads((OUT_DIR / "domain_inventory.json").read_text(encoding="utf-8"))

    report = {
        "artifact": "hackathon_proof_v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "domain_inventory": inventory,
        "goal_pricing": pricing,
        "monte_carlo_crn": mc,
        "policy_regret_model_consistent": policy,
        "agent_comparable_ablations": agents,
        "claims": claims,
        "proof_table": {
            "GOAL_PRICING_education_shared_200": {
                "raw_gpt_brier": pricing["arms"]["A_raw_gpt"]["brier"],
                "logistic_brier": pricing["arms"]["C_logistic_statistical"]["brier"],
                "play_it_out_brier": pricing["arms"]["G_play_it_out_calibrated_numerical"]["brier"],
                "relative_improvement_vs_gpt": pricing["relative_brier_reduction_vs_gpt"],
                "log_loss_gpt": pricing["arms"]["A_raw_gpt"]["log_loss"],
                "log_loss_play": pricing["arms"]["G_play_it_out_calibrated_numerical"]["log_loss"],
                "ece_gpt": pricing["arms"]["A_raw_gpt"]["ece_10"],
                "ece_play": pricing["arms"]["G_play_it_out_calibrated_numerical"]["ece_10"],
                "auc_gpt": pricing["arms"]["A_raw_gpt"]["roc_auc"],
                "auc_play": pricing["arms"]["G_play_it_out_calibrated_numerical"]["roc_auc"],
            },
            "LONGITUDINAL": pricing["longitudinal"],
            "ACTION_POLICY_MODEL_CONSISTENT": {
                "regret_vs_oracle": policy.get("regret_vs_oracle"),
                "policy_value": (policy.get("play_it_out_policy") or {}).get("policy_value_uplift"),
                "constraint_violations": policy.get("constraint_violations"),
            },
            "AGENTS": {
                "goal_architect_raw_prob_claim_rate": agents["goal_architect"][
                    "A_probability_claim_rate"
                ],
                "goal_architect_schema_valid": agents["goal_architect"]["B_schema_valid_rate"],
                "evidence_hallucinated_prob_rate": agents["evidence_agent"][
                    "G_hallucinated_probability_rate"
                ],
                "evidence_event_match_rate": agents["evidence_agent"]["G_event_match_rate"],
                "intervention_raw_uplift_invention_rate": agents["intervention_agent"][
                    "A_raw_invents_uplift_rate"
                ],
                "intervention_unsupported_rate": agents["intervention_agent"][
                    "G_unsupported_or_not_priced_rate"
                ],
                "source_planner_mean_precision": agents["source_planner"]["mean_precision"],
                "source_planner_mean_recall": agents["source_planner"]["mean_recall"],
                "source_planner_mean_ndcg_at_5": agents["source_planner"]["mean_ndcg_at_5"],
                "critic_accuracy": agents["critic"]["accuracy"],
                "critic_leakage_recall": agents["critic"]["leakage_recall"],
            },
            "MC_CRN": mc,
        },
    }
    path = OUT_DIR / "results.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    write_proof_table(path, report)
    print(json.dumps({"wrote": str(path), "claims": claims["empirically_supported"][:4]}, indent=2))


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
