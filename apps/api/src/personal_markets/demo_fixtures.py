"""Deterministic DEV-only What If fixtures for UI parity testing.

Provenance: DEMO_SEED / synthetic_demo — never published forecasts or eval artifacts.
Enabled when PM_DEV_DEMO_FIXTURES=1.
"""

from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

from personal_markets.core.config import get_settings
from personal_markets.forecasting.families import AssumptionSource
from personal_markets.what_if.domain import (
    ActionFrontierResult,
    Assumption,
    CompareCandidate,
    DistributionBin,
    FrontierPoint,
    PathComparisonItem,
    PathComparisonResult,
    ResourceBudget,
    ResourceCost,
    ResourceUsage,
    ScenarioDistribution,
    ScenarioOutcome,
    SensitivityResult,
    SimulationConfig,
    SimulationDiagnostics,
    StructuredIntervention,
    TargetPath,
    TargetSearchResult,
    WhatIfBaselineState,
    WhatIfResult,
)

DEMO_GOAL_IDS = frozenset(
    {
        "20000000-0000-0000-0000-000000000001",
        "20000000-0000-0000-0000-000000000002",
        "20000000-0000-0000-0000-000000000003",
        "20000000-0000-0000-0000-000000000004",
        "20000000-0000-0000-0000-000000000005",
    }
)

DEMO_CURRENT_PROBABILITY: dict[str, float] = {
    "20000000-0000-0000-0000-000000000001": 0.54,
    "20000000-0000-0000-0000-000000000002": 0.41,
    "20000000-0000-0000-0000-000000000003": 0.27,
    "20000000-0000-0000-0000-000000000004": 0.46,
    "20000000-0000-0000-0000-000000000005": 0.22,
}

DEMO_SEED = 20260829


def demo_fixtures_enabled() -> bool:
    import os

    from personal_markets.core.config import _REPO_ROOT

    environment = os.environ.get("PM_ENVIRONMENT", "").strip().lower()
    if environment in {"production", "prod"}:
        return False

    raw = os.environ.get("PM_DEV_DEMO_FIXTURES")
    if raw is not None:
        return raw.lower() in {"1", "true", "yes", "on"}

    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() == "PM_DEV_DEMO_FIXTURES":
                return value.strip().lower() in {"1", "true", "yes", "on"}

    get_settings.cache_clear()
    return get_settings().dev_demo_fixtures


def is_demo_goal(goal_id: str) -> bool:
    return goal_id in DEMO_GOAL_IDS


@lru_cache
def _fixtures_path() -> Path:
    return Path(__file__).resolve().parents[4] / "seeds" / "demo_what_if_fixtures.json"


@lru_cache
def _load_json_fixtures() -> dict[str, Any]:
    path = _fixtures_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _demo_receipt(extra: dict[str, object] | None = None) -> dict[str, object]:
    receipt: dict[str, object] = {
        "provenance": "DEMO_SEED",
        "source": "synthetic_demo",
        "purpose": "ui_parity_verification",
        "not_calibrated": True,
        "not_published_forecast": True,
    }
    if extra:
        receipt.update(extra)
    return receipt


def _demo_assumptions_for_goal(goal_id: str) -> list[Assumption]:
    if goal_id == "20000000-0000-0000-0000-000000000005":
        return [
            Assumption(
                name="build_hours_per_day",
                description="Focused product build time each day",
                value=3,
                minimum=0,
                maximum=8,
                step=0.25,
                source=AssumptionSource.EXPLORATION,
                unit="hours/day",
                provenance="DEMO_SEED",
                editable=True,
            ),
            Assumption(
                name="user_conversations_per_week",
                description="User discovery conversations each week",
                value=5,
                minimum=0,
                maximum=20,
                step=1,
                source=AssumptionSource.REFERENCE,
                unit="count/week",
                provenance="DEMO_SEED",
                editable=True,
            ),
            Assumption(
                name="execution_probability",
                description="Follow-through probability",
                value=0.76,
                minimum=0.2,
                maximum=0.95,
                step=0.01,
                source=AssumptionSource.USER,
                unit="probability",
                provenance="DEMO_SEED",
                editable=True,
            ),
        ]

    if goal_id == "20000000-0000-0000-0000-000000000002":
        return _career_demo_assumptions()

    return [
        Assumption(
            name="focused_hours_per_day",
            description="Focused time on this goal each day",
            value=2,
            minimum=0,
            maximum=6,
            step=0.25,
            source=AssumptionSource.EXPLORATION,
            unit="hours/day",
            provenance="DEMO_SEED",
            editable=True,
        ),
        Assumption(
            name="sessions_per_week",
            description="Meaningful sessions each week",
            value=5,
            minimum=0,
            maximum=20,
            step=1,
            source=AssumptionSource.REFERENCE,
            unit="count/week",
            provenance="DEMO_SEED",
            editable=True,
        ),
        Assumption(
            name="execution_probability",
            description="Follow-through probability",
            value=0.72,
            minimum=0.2,
            maximum=0.95,
            step=0.01,
            source=AssumptionSource.USER,
            unit="probability",
            provenance="DEMO_SEED",
            editable=True,
        ),
    ]


def _career_demo_assumptions() -> list[Assumption]:
    return [
        Assumption(
            name="weekly_application_rate",
            description="Applications per week",
            value=8,
            minimum=0,
            maximum=30,
            step=1,
            source=AssumptionSource.REFERENCE,
            unit="count/week",
            provenance="DEMO_SEED",
            editable=True,
        ),
        Assumption(
            name="execution_probability",
            description="Follow-through probability",
            value=0.72,
            minimum=0.2,
            maximum=0.95,
            step=0.01,
            source=AssumptionSource.USER,
            unit="probability",
            provenance="DEMO_SEED",
            editable=True,
        ),
        Assumption(
            name="interview_prep_hours",
            description="Daily interview prep hours",
            value=2,
            minimum=0,
            maximum=6,
            step=0.25,
            source=AssumptionSource.EXPLORATION,
            unit="hours/day",
            provenance="DEMO_SEED",
            editable=True,
        ),
    ]


def _demo_assumptions() -> list[Assumption]:
    return _career_demo_assumptions()


def _default_intervention_for_goal(goal_id: str) -> StructuredIntervention:
    if goal_id == "20000000-0000-0000-0000-000000000005":
        return StructuredIntervention(
            id="build-and-talk",
            title="Build 3 hours a day and talk to users weekly",
            action_type="flow_change",
            target_dimension="startup_traction",
            amount=3,
            unit="hours/day",
            duration_periods=10,
            effect_per_unit=0.05,
            effect_source=AssumptionSource.EXPLORATION,
            diminishing_return=0.03,
            cost=ResourceCost(hours_per_week=21, money=0, energy=0.4),
        )
    return _default_intervention()


def _default_intervention() -> StructuredIntervention:
    return StructuredIntervention(
        id="leetcode-daily",
        title="Study LeetCode 2 hours a day",
        action_type="flow_change",
        target_dimension="interview_readiness",
        amount=2,
        unit="hours/day",
        duration_periods=8,
        effect_per_unit=0.04,
        effect_source=AssumptionSource.EXPLORATION,
        diminishing_return=0.03,
        cost=ResourceCost(hours_per_week=14, money=0, energy=0.35),
    )


def _distribution_bins(center: float, spread: float = 0.08) -> list[DistributionBin]:
    bins: list[DistributionBin] = []
    start = max(0.05, center - spread * 3)
    width = (spread * 6) / 12
    for index in range(12):
        lower = start + index * width
        upper = lower + width
        distance = abs((lower + upper) / 2 - center)
        mass = max(0.01, 0.22 - distance * 1.4)
        bins.append(DistributionBin(lower=lower, upper=upper, mass=mass))
    total = sum(item.mass for item in bins)
    return [
        DistributionBin(lower=item.lower, upper=item.upper, mass=item.mass / total)
        for item in bins
    ]


def _fan_curve(baseline: float, uplift: float, steps: int = 8) -> list[dict[str, float]]:
    fan: list[dict[str, float]] = []
    for step in range(steps):
        ratio = step / max(steps - 1, 1)
        mid = baseline + uplift * ratio
        spread = 0.04 + ratio * 0.03
        fan.append({"step": float(step), "p10": mid - spread, "p50": mid, "p90": mid + spread})
    return fan


def _sensitivity_rows() -> list[SensitivityResult]:
    rows = [
        ("Follow-through rate", 6.8),
        ("Interview prep hours", 5.4),
        ("Application volume", 3.9),
        ("Technical screen pass rate", 3.1),
        ("Offer conversion", 2.4),
    ]
    return [
        SensitivityResult(
            assumption_id=f"demo-{index}",
            label=label,
            baseline_value=0.5,
            lower_value=0.4,
            upper_value=0.6,
            probability_at_lower=0.45,
            probability_at_baseline=0.53,
            probability_at_upper=0.58,
            swing=swing,
            direction="increases",
            probability_swing_pp=swing,
        )
        for index, (label, swing) in enumerate(rows)
    ]


def generate_demo_simulation_points(seed: int = DEMO_SEED, count: int = 240) -> list[dict[str, object]]:
    rng = random.Random(seed)
    clusters = ["strong", "steady", "fragile", "stretch"]
    points: list[dict[str, object]] = []
    for index in range(count):
        cluster = clusters[index % len(clusters)]
        x = min(95, max(8, rng.gauss(52 if cluster != "fragile" else 38, 9)))
        y = min(95, max(8, rng.gauss(58 if cluster == "strong" else 48, 11)))
        points.append(
            {
                "id": index,
                "x": round(x, 2),
                "y": round(y, 2),
                "clusterId": cluster,
                "goalHit": x >= 41,
                "seed": seed + index,
            }
        )
    return points


def generate_demo_representatives(points: list[dict[str, object]]) -> list[dict[str, object]]:
    if not points:
        return []
    by_x = sorted(points, key=lambda item: float(item["x"]))
    picks = [
        ("likely", "Most likely path", by_x[len(by_x) // 2]),
        ("upside", "Upside case", by_x[int(len(by_x) * 0.85)]),
        ("downside", "Downside case", by_x[int(len(by_x) * 0.15)]),
    ]
    return [{"kind": kind, "label": label, "point": point} for kind, label, point in picks]


def fixture_simulate(goal_id: str) -> WhatIfResult | None:
    if goal_id != "20000000-0000-0000-0000-000000000002":
        baseline = DEMO_CURRENT_PROBABILITY.get(goal_id, 0.3)
        scenario = min(0.95, baseline + 0.08)
        return WhatIfResult(
            priced=True,
            status="DEMO_SEED",
            message="Synthetic demo scenario for UI parity only.",
            baseline_probability=baseline,
            scenario_probability=scenario,
            conditional_on_execution_probability=min(0.95, scenario + 0.07),
            execution_probability=0.72,
            expected_uplift_pp=(scenario - baseline) * 100,
            uplift_interval_pp=((scenario - baseline) * 50, (scenario - baseline) * 140),
            p_uplift_positive=0.71,
            outcome_quantiles={"p10": baseline - 0.05, "p50": scenario, "p90": scenario + 0.06},
            distribution_bins=_distribution_bins(scenario),
            fan=_fan_curve(baseline, scenario - baseline),
            sensitivity=_sensitivity_rows()[:3],
            resource_usage=ResourceUsage(hours_per_week=10, money_per_month=0, within_budget=True),
            resource_budget=ResourceBudget(hours_per_week=20, money_per_month=500),
            opportunity_costs=["Less time for side projects", "Reduced social recovery time"],
            diagnostics=SimulationDiagnostics(
                n_draws=4000,
                seed=DEMO_SEED,
                converged=True,
                criterion="demo_fixture",
                achieved_mc_error=0.004,
                duration_ms=12.0,
            ),
            assumptions=_demo_assumptions_for_goal(goal_id),
            receipt=_demo_receipt(),
            persisted=False,
            history_snapshot_created=False,
        )

    baseline = 0.41
    scenario = 0.53
    points = generate_demo_simulation_points()
    return WhatIfResult(
        priced=True,
        status="DEMO_SEED",
        message="Synthetic LeetCode prep scenario for UI parity only.",
        baseline_probability=baseline,
        scenario_probability=scenario,
        conditional_on_execution_probability=0.61,
        execution_probability=0.72,
        expected_uplift_pp=12.0,
        uplift_interval_pp=(4.0, 18.0),
        p_uplift_positive=0.78,
        outcome_quantiles={"p10": 0.38, "p50": 0.53, "p90": 0.67},
        distribution_bins=_distribution_bins(scenario),
        fan=_fan_curve(baseline, scenario - baseline),
        sensitivity=_sensitivity_rows(),
        resource_usage=ResourceUsage(hours_per_week=14, money_per_month=0, within_budget=True),
        resource_budget=ResourceBudget(hours_per_week=20, money_per_month=500),
        opportunity_costs=[
            "Less time for startup side work",
            "Fewer networking events each week",
        ],
        diagnostics=SimulationDiagnostics(
            n_draws=4000,
            seed=DEMO_SEED,
            converged=True,
            criterion="demo_fixture",
            achieved_mc_error=0.0035,
            duration_ms=14.0,
        ),
        assumptions=_demo_assumptions_for_goal("20000000-0000-0000-0000-000000000002"),
        receipt=_demo_receipt(
            {
                "demo_simulation_points": points,
                "demo_representatives": generate_demo_representatives(points),
                "intervention": "What if I study LeetCode 2 hours a day?",
            }
        ),
        persisted=False,
        history_snapshot_created=False,
    )


def patch_baseline_state(state: WhatIfBaselineState) -> WhatIfBaselineState:
    goal_id = state.goal_id
    current = DEMO_CURRENT_PROBABILITY.get(goal_id)
    if current is None:
        return state

    compare = _load_json_fixtures().get("compare_candidates", {}).get(goal_id, [])
    candidates: list[CompareCandidate] = []
    for item in compare:
        candidates.append(
            CompareCandidate(
                id=item["id"],
                title=item["label"],
                intervention=_default_intervention_for_goal(goal_id).model_copy(
                    update={"id": item["id"], "title": item["label"]}
                ),
                provenance=["DEMO_SEED"],
            )
        )

    return state.model_copy(
        update={
            "priced": True,
            "status": "DEMO_SEED",
            "message": "Synthetic demo baseline for UI parity only.",
            "current_probability": current,
            "current_value": 0.41 if goal_id.endswith("000002") else current,
            "target_value": 1.0,
            "periods": 8,
            "assumptions": _demo_assumptions_for_goal(goal_id),
            "default_intervention": _default_intervention_for_goal(goal_id),
            "compare_candidates": candidates or state.compare_candidates,
            "limitations": [*state.limitations, "DEMO_SEED: not a calibrated forecast"],
            "config": SimulationConfig(seed=DEMO_SEED),
        }
    )


def fixture_compare(goal_id: str) -> PathComparisonResult | None:
    payload = _load_json_fixtures().get("compare", {}).get(goal_id)
    if payload is None:
        return None
    paths = [
        PathComparisonItem.model_validate({**item, "assumptions": _demo_assumptions_for_goal(goal_id)})
        for item in payload["paths"]
    ]
    return PathComparisonResult(
        paths=paths,
        model_family="demo_fixture",
        model_version="ui-parity-v1",
        seed=DEMO_SEED,
        receipt=_demo_receipt(),
    )


def fixture_futures(goal_id: str) -> ScenarioDistribution | None:
    payload = _load_json_fixtures().get("futures", {}).get(goal_id)
    if payload is None:
        return None
    outcomes = [ScenarioOutcome.model_validate(item) for item in payload["outcomes"]]
    return ScenarioDistribution(
        outcomes=outcomes,
        mutually_exclusive=True,
        collectively_exhaustive=True,
        other_probability=0,
        seed=DEMO_SEED,
        model_version="demo_fixture@ui-parity-v1",
        priced=True,
        message="DEMO_SEED futures for UI parity only.",
        receipt=_demo_receipt(),
    )


def fixture_target_search(goal_id: str) -> TargetSearchResult | None:
    payload = _load_json_fixtures().get("paths", {}).get(goal_id)
    if payload is None:
        return None
    paths = [
        TargetPath.model_validate({**item, "assumptions": _demo_assumptions_for_goal(goal_id)})
        for item in payload["paths"]
    ]
    return TargetSearchResult(
        target_probability=payload["target_probability"],
        current_probability=payload["current_probability"],
        gap_pp=payload["gap_pp"],
        feasible=True,
        message="DEMO_SEED ranked paths for UI parity only.",
        paths=paths,
        search_method="demo_fixture",
        receipt=_demo_receipt({"frontier": payload.get("frontier", [])}),
    )


def fixture_action_frontier(goal_id: str) -> ActionFrontierResult | None:
    payload = _load_json_fixtures().get("paths", {}).get(goal_id, {})
    frontier = payload.get("frontier")
    if not frontier:
        return None
    points = [FrontierPoint.model_validate(item) for item in frontier["points"]]
    return ActionFrontierResult(
        points=points,
        frontier_ids=list(frontier.get("frontier_ids", [])),
        selected_id=frontier.get("selected_id"),
    )
