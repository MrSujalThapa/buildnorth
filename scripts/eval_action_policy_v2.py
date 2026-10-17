"""Expanded model-consistent action / policy ranking for hackathon_proof_v2.

NON-CAUSAL / MODEL-CONSISTENT ONLY.
Uses the product's hiring funnel numeric model + deadline-event Monte Carlo
(SimulationEngine) with explicit parameter overrides. No RCT ATEs.
No observational OULAD study-intensity panel: full studentVle.csv is not under data/.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from personal_markets.evidence.mapping import proposal_to_normalized
from personal_markets.forecasting.hiring import build_hiring_numeric_inputs
from personal_markets.goals.domain import GoalContract
from personal_markets.ports import EvidenceEventProposal
from personal_markets.seeding import load_seed
from personal_markets.what_if.baseline_state import proposal_from_goal
from personal_markets.what_if.domain import SimulationConfig
from personal_markets.what_if.simulation import SimulationEngine

SEED = 20260830
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "hackathon_proof_v2"
CAREER_GOAL = UUID("20000000-0000-0000-0000-000000000002")
EXECUTION = 0.72

ACTION_CATALOG: list[dict[str, Any]] = [
    {
        "id": "applications",
        "label": "Raise weekly applications to 15",
        "hours_cost": 8.0,
        "weekly_application_rate": 15.0,
    },
    {
        "id": "response_rate",
        "label": "Improve application→response conversion (+8pp model prior)",
        "hours_cost": 6.0,
        "stage_delta": ("application_to_response", 0.08),
    },
    {
        "id": "tech_rate",
        "label": "Improve OA→technical conversion (+10pp model prior)",
        "hours_cost": 10.0,
        "stage_delta": ("oa_to_technical", 0.10),
    },
    {
        "id": "offer_rate",
        "label": "Improve final→offer conversion (+6pp model prior)",
        "hours_cost": 5.0,
        "stage_delta": ("final_to_offer", 0.06),
    },
]


def _load_career() -> tuple[GoalContract, list[Any]]:
    payload = load_seed(ROOT / "seeds" / "demo.json")
    goal = next(
        GoalContract.model_validate(row)
        for row in payload["goals"]
        if str(row["goal_id"]) == str(CAREER_GOAL)
    )
    evidence = []
    for row in payload.get("evidence_events", []):
        if str(row.get("goal_id")) != str(CAREER_GOAL):
            continue
        proposal = EvidenceEventProposal(
            event_type=row["event_type"],
            domain=row["domain"],
            metric=row["metric"],
            numeric_value=row.get("numeric_value"),
            unit=row.get("unit"),
            observed_at=row["observed_at"],
            summary=row["summary"],
            source_type=row.get("source_type") or "manual",
        )
        evidence.append(
            proposal_to_normalized(
                proposal,
                fingerprint=str(row.get("fingerprint") or row["id"]),
                evidence_id=UUID(str(row["id"])),
            )
        )
    return goal, evidence


def _offer_probability(numeric: Any) -> float:
    transforms = numeric.state.get("pricing_transforms") or {}
    return float(transforms.get("combined_offer_probability") or 0.0)


def _periods(numeric: Any) -> int:
    return int(numeric.state.get("periods_remaining") or 12)


def _stage_rates(numeric: Any) -> dict[str, float]:
    transforms = numeric.state.get("pricing_transforms") or {}
    return {k: float(v) for k, v in (transforms.get("stage_rates") or {}).items()}


def _simulate_pair(
    engine: SimulationEngine,
    *,
    p_base: float,
    p_scene: float,
    periods: int,
    seed: int,
) -> tuple[float, float]:
    cfg = SimulationConfig(
        seed=seed,
        minimum_draws=2000,
        maximum_draws=8000,
        batch_draws=1000,
        probability_se_tolerance=0.01,
    )
    paired = engine.deadline_event(
        baseline_probability=p_base,
        scenario_probability=p_scene,
        periods=periods,
        execution_probability=EXECUTION,
        config=cfg,
    )
    return float(np.mean(paired.baseline_success)), float(np.mean(paired.scenario_success))


def _action_overrides(scaled_rates: dict[str, float], action: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    if "weekly_application_rate" in action:
        out["weekly_application_rate"] = float(action["weekly_application_rate"])
    stage_delta = action.get("stage_delta")
    if stage_delta:
        key, delta = stage_delta
        base = float(scaled_rates[key])
        out[str(key)] = float(min(0.99, max(0.01, base + float(delta))))
    return out


def _oracle_bundle_value(actions: list[dict[str, Any]], budget: float) -> tuple[float, tuple[str, ...]]:
    best_val = 0.0
    best_ids: tuple[str, ...] = ()
    n = len(actions)
    for mask in range(1 << n):
        hours = 0.0
        uplift = 0.0
        ids: list[str] = []
        feasible = True
        for i in range(n):
            if mask & (1 << i):
                hours += float(actions[i]["hours_cost"])
                uplift += float(actions[i]["uplift"])
                ids.append(str(actions[i]["id"]))
                if hours > budget + 1e-9:
                    feasible = False
                    break
        if feasible and uplift > best_val + 1e-15:
            best_val = uplift
            best_ids = tuple(ids)
    return best_val, best_ids


def _greedy_bundle(actions: list[dict[str, Any]], budget: float) -> tuple[float, list[str]]:
    ranked = sorted(
        actions,
        key=lambda r: float(r["uplift"]) / max(float(r["hours_cost"]), 1e-9),
        reverse=True,
    )
    used = 0.0
    value = 0.0
    selected: list[str] = []
    for row in ranked:
        cost = float(row["hours_cost"])
        if used + cost <= budget + 1e-9 and float(row["uplift"]) >= 0:
            selected.append(str(row["id"]))
            used += cost
            value += float(row["uplift"])
    return value, selected


def _equal_value(actions: list[dict[str, Any]]) -> float:
    if not actions:
        return 0.0
    return float(sum(float(a["uplift"]) for a in actions) / len(actions))


def _random_bundle(
    actions: list[dict[str, Any]], budget: float, rng: np.random.Generator
) -> tuple[float, list[str]]:
    order = list(range(len(actions)))
    rng.shuffle(order)
    used = 0.0
    value = 0.0
    selected: list[str] = []
    for i in order:
        row = actions[i]
        cost = float(row["hours_cost"])
        if used + cost <= budget + 1e-9:
            selected.append(str(row["id"]))
            used += cost
            value += float(row["uplift"])
    return value, selected


def _score_case(
    *,
    goal: GoalContract,
    evidence: list[Any],
    proposal: Any,
    engine: SimulationEngine,
    base_weekly: float,
    stage_scale: float,
    budget: float,
    case_id: str,
    rng: np.random.Generator,
    seed: int,
) -> dict[str, Any]:
    reference = build_hiring_numeric_inputs(goal, proposal, evidence, overrides=None)
    assert reference is not None
    base_rates = _stage_rates(reference)
    scaled_rates = {
        k: float(min(0.99, max(0.01, v * stage_scale))) for k, v in base_rates.items()
    }
    baseline_overrides: dict[str, float] = {
        "weekly_application_rate": base_weekly,
        **scaled_rates,
    }
    base_numeric = build_hiring_numeric_inputs(
        goal, proposal, evidence, overrides=baseline_overrides
    )
    assert base_numeric is not None
    p0_model = _offer_probability(base_numeric)
    periods = _periods(base_numeric)

    rows: list[dict[str, Any]] = []
    for action in ACTION_CATALOG:
        ov = {**baseline_overrides, **_action_overrides(scaled_rates, action)}
        scene_numeric = build_hiring_numeric_inputs(goal, proposal, evidence, overrides=ov)
        assert scene_numeric is not None
        p1_model = _offer_probability(scene_numeric)
        p0_mc, p1_mc = _simulate_pair(
            engine, p_base=p0_model, p_scene=p1_model, periods=periods, seed=seed
        )
        rows.append(
            {
                "id": action["id"],
                "label": action["label"],
                "hours_cost": action["hours_cost"],
                "p_baseline_model": p0_model,
                "p_scenario_model": p1_model,
                "p_baseline": p0_mc,
                "p_scenario": p1_mc,
                "uplift": p1_mc - p0_mc,
                "uplift_model_raw": p1_model - p0_model,
            }
        )

    oracle_id = max(rows, key=lambda r: float(r["uplift"]))["id"]
    greedy_id = max(
        rows, key=lambda r: float(r["uplift"]) / max(float(r["hours_cost"]), 1e-9)
    )["id"]
    equal_pick = sorted(rows, key=lambda r: r["id"])[len(rows) // 2]["id"]
    random_id = str(rows[int(rng.integers(0, len(rows)))]["id"])

    greedy_val, greedy_sel = _greedy_bundle(rows, budget)
    equal_val = _equal_value(rows)
    random_val, random_sel = _random_bundle(rows, budget, rng)
    oracle_val, oracle_sel = _oracle_bundle_value(rows, budget)

    def capture(v: float) -> float | None:
        if abs(oracle_val) < 1e-15:
            return None
        return float(v / oracle_val)

    return {
        "case_id": case_id,
        "budget_hours": budget,
        "baseline_weekly_application_rate": base_weekly,
        "stage_scale": stage_scale,
        "actions": rows,
        "best_action_id": oracle_id,
        "top1": {
            "greedy": greedy_id == oracle_id,
            "equal_proxy": equal_pick == oracle_id,
            "random": random_id == oracle_id,
            "oracle": True,
            "greedy_choice": greedy_id,
            "equal_proxy_choice": equal_pick,
            "random_choice": random_id,
            "oracle_choice": oracle_id,
        },
        "policy_value": {
            "greedy": greedy_val,
            "equal_proxy": equal_val,
            "random": random_val,
            "oracle": oracle_val,
        },
        "regret_vs_oracle": {
            "greedy": oracle_val - greedy_val,
            "equal_proxy": oracle_val - equal_val,
            "random": oracle_val - random_val,
            "oracle": 0.0,
        },
        "upside_captured": {
            "greedy": capture(greedy_val),
            "equal_proxy": capture(equal_val),
            "random": capture(random_val),
            "oracle": 1.0 if oracle_val != 0 else None,
        },
        "selected_ids": {
            "greedy": greedy_sel,
            "equal_proxy": [a["id"] for a in rows],
            "random": random_sel,
            "oracle": list(oracle_sel),
        },
    }


def run_eval() -> dict[str, Any]:
    goal, evidence = _load_career()
    proposal = proposal_from_goal(goal)
    engine = SimulationEngine()
    rng = np.random.default_rng(SEED)

    rate_grid = (2.0, 5.0, 12.0, 18.0)
    scale_grid = (0.85, 1.0, 1.15)
    budget_grid = (8.0, 12.0, 20.0)
    cases: list[dict[str, Any]] = []
    case_i = 0
    for rate in rate_grid:
        for scale in scale_grid:
            for budget in budget_grid:
                case_i += 1
                cases.append(
                    _score_case(
                        goal=goal,
                        evidence=evidence,
                        proposal=proposal,
                        engine=engine,
                        base_weekly=rate,
                        stage_scale=scale,
                        budget=budget,
                        case_id=f"career_rate{rate:g}_scale{scale:g}_budget{budget:g}",
                        rng=rng,
                        seed=SEED + case_i,
                    )
                )

    def mean_bool(key: str) -> float:
        vals = [1.0 if c["top1"][key] else 0.0 for c in cases]
        return float(np.mean(vals)) if vals else float("nan")

    def mean_metric(block: str, key: str) -> float:
        vals = [float(c[block][key]) for c in cases if c[block].get(key) is not None]
        return float(np.mean(vals)) if vals else float("nan")

    top1 = {
        "greedy": mean_bool("greedy"),
        "equal_proxy": mean_bool("equal_proxy"),
        "random": mean_bool("random"),
        "oracle": 1.0,
    }
    policy_value = {
        "greedy": mean_metric("policy_value", "greedy"),
        "equal_proxy": mean_metric("policy_value", "equal_proxy"),
        "random": mean_metric("policy_value", "random"),
        "oracle": mean_metric("policy_value", "oracle"),
    }
    regret = {
        "greedy": mean_metric("regret_vs_oracle", "greedy"),
        "equal_proxy": mean_metric("regret_vs_oracle", "equal_proxy"),
        "random": mean_metric("regret_vs_oracle", "random"),
        "oracle": 0.0,
    }
    upside = {
        "greedy": mean_metric("upside_captured", "greedy"),
        "equal_proxy": mean_metric("upside_captured", "equal_proxy"),
        "random": mean_metric("upside_captured", "random"),
        "oracle": 1.0,
    }

    def pct(x: float | None, digits: int = 0) -> str:
        if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
            return "n/a"
        return f"{100 * x:.{digits}f}%"

    best_counts: dict[str, int] = {}
    for c in cases:
        best_counts[c["best_action_id"]] = best_counts.get(c["best_action_id"], 0) + 1

    plain_english = {
        "disclaimer": (
            "NON-CAUSAL / MODEL-CONSISTENT: these figures compare recommendation policies "
            "under Play It Out's hiring funnel numeric model and deadline-event Monte Carlo "
            "with explicit parameter overrides. They are not randomized controlled trial "
            "average treatment effects and must not be reported as real-world causal action impact."
        ),
        "causal_panel_status": (
            "No public RCT / credible quasi-experimental personal-action panel with treatment "
            "variation loaded in this worktree. Full OULAD studentVle.csv is not present under "
            "data/, so no observational study-intensity associative proxy was computed."
        ),
        "top1": (
            f"Across {len(cases)} simulator ranking cases, a greedy uplift/hour policy picked "
            f"the best single action {pct(top1['greedy'], 0)} of the time; equal-proxy "
            f"{pct(top1['equal_proxy'], 0)}; random {pct(top1['random'], 0)}; oracle 100%."
        ),
        "policy_value": (
            f"Mean model-consistent policy uplift under the hours budget: greedy "
            f"{policy_value['greedy']:.4f}, equal-proxy {policy_value['equal_proxy']:.4f}, "
            f"random {policy_value['random']:.4f}, oracle {policy_value['oracle']:.4f}."
        ),
        "regret": (
            f"Mean regret vs oracle (probability points left on the table): greedy "
            f"{regret['greedy']:.4f}, equal-proxy {regret['equal_proxy']:.4f}, "
            f"random {regret['random']:.4f}."
        ),
        "upside_captured": (
            f"Mean fraction of oracle upside captured: greedy {pct(upside['greedy'], 0)}, "
            f"equal-proxy {pct(upside['equal_proxy'], 0)}, random {pct(upside['random'], 0)}."
        ),
        "best_action_mix": (
            "Oracle best-action frequencies across the case grid: "
            + ", ".join(f"{k}={v}" for k, v in sorted(best_counts.items()))
            + "."
        ),
        "reuse_note": (
            "Extends hackathon_proof_v1 policy_regret_model_consistent with a multi-case "
            "ranking grid (baseline application rate × stage-prior scale × budget) and "
            "greedy/equal/random/oracle comparisons on model-priced hiring levers "
            "(weekly applications + stage conversion priors)."
        ),
    }

    return {
        "artifact": "hackathon_proof_v2_action_policy",
        "captured_at": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "label": "NON-CAUSAL / MODEL-CONSISTENT",
        "status": "ok",
        "goal_id": str(CAREER_GOAL),
        "n_cases": len(cases),
        "action_catalog_ids": [a["id"] for a in ACTION_CATALOG],
        "best_action_top1_rates": top1,
        "oracle_best_action_counts": best_counts,
        "mean_policy_value_uplift": policy_value,
        "mean_regret_vs_oracle": regret,
        "mean_upside_captured": upside,
        "plain_english": plain_english,
        "limitations": [
            "Not causal; model-implied uplifts only",
            "Additive bundle value approximation (no joint multi-override MC interaction)",
            "Hours costs are fixed product estimates, not measured opportunity costs",
            "Stage-rate actions are exploration priors in the hiring reference model, not RCT effects",
            "No RCT ATE panel loaded; no OULAD associative proxy computed (data absent)",
        ],
        "cases": cases,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    result = run_eval()
    path = OUT / "action_policy_results.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "path": str(path),
                "status": result["status"],
                "n_cases": result["n_cases"],
                "best_action_top1_rates": result["best_action_top1_rates"],
                "oracle_best_action_counts": result["oracle_best_action_counts"],
                "mean_policy_value_uplift": result["mean_policy_value_uplift"],
                "mean_regret_vs_oracle": result["mean_regret_vs_oracle"],
                "mean_upside_captured": result["mean_upside_captured"],
                "plain_english": result["plain_english"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
