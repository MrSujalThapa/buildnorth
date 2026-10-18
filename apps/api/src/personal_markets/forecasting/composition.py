"""Compile a validated ForecastSpec plus evidence into a FamilyPrice.

Existing domain adapters stay preferred. This path is for registered primitives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.compiler import ForecastSpecV2, PrimitiveNode, spec_from_mapping
from personal_markets.forecasting.engine import FamilyPrice, NumericInputs
from personal_markets.forecasting.estimation import (
    current_stock,
    estimate_linear_trend,
    estimate_log_growth,
    estimate_rate,
    periods_until,
)
from personal_markets.forecasting.monte_carlo import monte_carlo_frequency
from personal_markets.forecasting.primitives import (
    COMPILER_VERSION,
    PrimitivePrice,
    price_continuous_threshold,
    price_cumulative_count,
    price_deadline_hazard,
    price_dependency_dag,
    price_funnel,
    price_growth,
    price_habit,
    waiting_time_loglinear,
    waiting_time_poisson,
)
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.targets import resolve_target_number, target_direction


def composition_numeric_inputs(
    goal: GoalContract,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> NumericInputs | None:
    spec = spec_from_mapping(goal.model_requirements.get("forecast_spec"))
    if spec is None:
        return None
    compiled = _prepare(goal, spec, evidence, overrides=overrides, now=now)
    return compiled.inputs


def price_composition(
    goal: GoalContract,
    inputs: NumericInputs,
) -> FamilyPrice | None:
    spec = spec_from_mapping(goal.model_requirements.get("forecast_spec"))
    if spec is None:
        return None
    prepared = inputs.state.get("composition_prepared")
    if not isinstance(prepared, dict):
        return _family_unpriced(spec, ["Composition state was not prepared from evidence."])
    result = _price_prepared(spec, prepared, inputs)
    limitations = list(result.limitations)
    engine_ready = any(item.get("used_by_engine") for item in spec.parameter_provenance)
    if spec.research_required and not engine_ready:
        return _family_unpriced(
            spec,
            [
                *limitations,
                "Required external parameters remain unapproved; research candidates cannot price.",
            ],
        )
    used: list[dict[str, Any]] = []
    for node_id, node in (prepared.get("nodes") or {}).items():
        sources = node.get("sources") or {}
        for key, value in (node.get("parameters") or {}).items():
            used.append(
                {
                    "name": f"{node_id}.{key}",
                    "value": value,
                    "source": sources.get(key, "estimated"),
                }
            )
    if not used:
        used = [
            {
                "name": item.get("parameter", "parameter"),
                "value": item.get("value"),
                "source": item.get("source_kind", "estimated"),
            }
            for item in result.used_parameters
        ]
    if not result.priced or result.probability is None:
        return FamilyPrice(
            priced=False,
            raw_probability=None,
            forecast_status="EXPLORATORY",
            limitations=[*limitations, f"compiler={COMPILER_VERSION}"],
            transforms=result.diagnostics,
            used_assumptions=used,
        )
    return FamilyPrice(
        priced=True,
        raw_probability=result.probability,
        forecast_status="EXPLORATORY",
        limitations=[*limitations, f"compiler={COMPILER_VERSION}"],
        transforms={"composition": result.diagnostics, "method": result.method},
        used_assumptions=used,
    )


class _Prepared:
    def __init__(
        self, spec: ForecastSpecV2, inputs: NumericInputs, prepared: dict[str, Any]
    ) -> None:
        self.spec = spec
        self.inputs = inputs
        self.prepared = prepared


def _prepare(
    goal: GoalContract,
    spec: ForecastSpecV2,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> _Prepared:
    moment = now or datetime.now(UTC)
    overrides = overrides or {}
    days = {"day": 1.0, "week": 7.0, "month": 30.437}.get(
        str((spec.primitives[0].config if spec.primitives else {}).get("time_unit") or "week"),
        7.0,
    )
    horizon = float(
        overrides.get("periods") or periods_until(goal.deadline, moment, days_per_period=days)
    )
    node_state: dict[str, dict[str, Any]] = {}
    assumptions: dict[str, Any] = {}
    sources: dict[str, str] = {}
    missing: list[str] = []
    for node in spec.primitives:
        packed, gaps = _node_state(goal, spec, node, evidence, overrides, moment, horizon, days)
        node_state[node.id] = packed
        missing.extend(gaps)
        for key, value in packed.get("parameters", {}).items():
            assumptions[f"{node.id}.{key}"] = value
            sources[f"{node.id}.{key}"] = packed.get("sources", {}).get(key, "estimated")
    prepared = {
        "horizon": horizon,
        "nodes": node_state,
        "missing": missing,
        "join": spec.composition.join,
        "correlation": spec.composition.correlation,
        "seed": int(overrides.get("seed") or spec.primitives[0].config.get("seed", 42))
        if spec.primitives
        else 42,
        "n_draws": int(overrides.get("n_draws") or 4_000),
    }
    target = resolve_target_number(goal)
    current = None
    if spec.primitives:
        current = node_state[spec.primitives[0].id].get("current")
    inputs = NumericInputs(
        state={
            "composition_prepared": prepared,
            "current_value": current,
            "target_value": target,
            "periods": horizon,
            "direction": target_direction(goal),
            "family": spec.family,
        },
        assumptions=assumptions,
        assumption_sources=sources,
    )
    return _Prepared(spec, inputs, prepared)


def _aliases(spec: ForecastSpecV2, metric: str) -> tuple[str, ...]:
    for item in spec.observable_inputs:
        if item.metric == metric:
            return tuple(item.aliases)
    return ()


def _node_state(
    goal: GoalContract,
    spec: ForecastSpecV2,
    node: PrimitiveNode,
    evidence: list[NormalizedEvidence],
    overrides: dict[str, Any],
    now: datetime,
    horizon: float,
    days: float,
) -> tuple[dict[str, Any], list[str]]:
    metric = node.state_bindings.get("current") or node.metric
    aliases = _aliases(spec, metric)
    current = overrides.get(metric)
    if current is None:
        current = current_stock(evidence, metric, aliases)
    gaps: list[str] = []
    parameters: dict[str, float] = dict(node.parameters)
    sources: dict[str, str] = {key: "user_assumption" for key in node.parameters}
    for item in spec.parameter_provenance:
        name = str(item.get("parameter") or "")
        if not name or item.get("value") is None:
            continue
        if not item.get("used_by_engine"):
            continue
        parameters.setdefault(name.split(".")[-1], float(item["value"]))
        sources[name.split(".")[-1]] = "prior"
    for key, value in overrides.items():
        if key in parameters or key in {metric, f"{node.id}.{key}"}:
            short = key.split(".", 1)[-1]
            try:
                parameters[short] = float(value)
                sources[short] = "user_assumption"
            except (TypeError, ValueError):
                pass
    if node.kind == "deadline_hazard":
        completed = current is not None and float(current) >= 1
        if not completed and not any(
            key in parameters for key in ("logit", "baseline_logit", "baseline_logits")
        ):
            gaps.append(f"hazard for {metric} (observed completion or a period logit)")
    if node.kind in {"cumulative_count", "growth", "continuous_threshold"} and current is None:
        gaps.append(f"current {metric}")
    if node.kind == "cumulative_count" and "rate" not in parameters:
        estimated = estimate_rate(evidence, metric, now=now, aliases=aliases, time_unit_days=days)
        if estimated.usable and estimated.value is not None:
            parameters["rate"] = estimated.value
            sources["rate"] = "estimated"
            parameters["n_rate_observations"] = float(estimated.n_observations)
        else:
            gaps.append("addition rate from dated history")
    if node.kind == "growth":
        if "mu" not in parameters:
            estimated = estimate_log_growth(evidence, metric, aliases=aliases, time_unit_days=days)
            if estimated.usable and estimated.value is not None:
                parameters["mu"] = estimated.value
                parameters["sigma"] = float(estimated.std_error or 0.05)
                parameters["n_observations"] = float(estimated.n_observations)
                sources["mu"] = "estimated"
            else:
                gaps.append("growth history (at least three positive measurements)")
        parameters.setdefault("sigma", 0.05)
    if node.kind == "continuous_threshold":
        if "trend" not in parameters:
            estimated = estimate_linear_trend(
                evidence, metric, aliases=aliases, time_unit_days=days
            )
            if estimated.usable and estimated.value is not None:
                parameters["trend"] = estimated.value
                parameters["noise"] = float(estimated.std_error or 1.0)
                sources["trend"] = "estimated"
            else:
                gaps.append("performance history (at least two dated measurements)")
        parameters.setdefault("noise", 1.0)
    if node.kind == "funnel":
        stages = [str(item) for item in node.config.get("stages") or []]
        counts = []
        for stage in stages:
            bound = node.state_bindings.get(stage, stage)
            value = overrides.get(bound)
            if value is None:
                value = current_stock(evidence, bound, _aliases(spec, bound))
            counts.append(0 if value is None else int(value))
        parameters["expected_new_starts"] = (
            float(
                overrides.get("weekly_application_rate")
                or overrides.get("inflow_rate")
                or parameters.get("inflow_rate")
                or 0.0
            )
            * horizon
        )
        packed_counts = counts
    else:
        packed_counts = []
        stages = []
    raw_target = node.config.get("target", node.parameters.get("target"))
    if raw_target is not None:
        try:
            target = float(raw_target)
        except (TypeError, ValueError):
            target = resolve_target_number(goal)
    else:
        target = resolve_target_number(goal)
    if node.kind in {"cumulative_count", "growth", "continuous_threshold"} and target is None:
        gaps.append("numeric success target")
    return (
        {
            "kind": node.kind,
            "metric": metric,
            "current": None if current is None else float(current),
            "target": target,
            "horizon": horizon,
            "parameters": parameters,
            "sources": sources,
            "config": node.config,
            "independence": node.independence,
            "prerequisites": list(node.prerequisites),
            "stage_counts": packed_counts,
            "stages": stages,
            "gaps": gaps,
        },
        gaps,
    )


def _price_prepared(
    spec: ForecastSpecV2, prepared: dict[str, Any], inputs: NumericInputs
) -> PrimitivePrice:
    missing = list(prepared.get("missing") or [])
    if missing:
        return PrimitivePrice(
            priced=False,
            probability=None,
            method="composition",
            limitations=[
                "NOT_PRICED: missing "
                + ", ".join(dict.fromkeys(missing))
                + ". No parameter was invented."
            ],
            diagnostics=prepared,
        )
    nodes = prepared["nodes"]
    join = prepared.get("join") or "single"
    if join == "single" or len(nodes) == 1:
        node_id = spec.composition.nodes[0] if spec.composition.nodes else spec.primitives[0].id
        return _price_node(nodes[node_id], inputs)
    if join == "funnel" and len(spec.primitives) == 1:
        return _price_node(nodes[spec.primitives[0].id], inputs)
    return _price_sequential(spec, prepared, inputs)


def _price_node(node: dict[str, Any], inputs: NumericInputs) -> PrimitivePrice:
    kind = node["kind"]
    params = node["parameters"]
    horizon = float(node["horizon"])
    if kind == "cumulative_count":
        if node["current"] is None or node["target"] is None or "rate" not in params:
            return PrimitivePrice(
                priced=False,
                probability=None,
                method="cumulative_count",
                limitations=["NOT_PRICED: count model needs current stock, target, and rate."],
            )
        return price_cumulative_count(
            current=float(node["current"]),
            target=float(node["target"]),
            rate=float(params["rate"]),
            periods=horizon,
            n_rate_observations=int(params.get("n_rate_observations") or 0),
            overdispersion=params.get("overdispersion"),
            seed=int(inputs.state.get("seed") or 42),
        )
    if kind == "growth":
        if node["current"] is None or node["target"] is None or "mu" not in params:
            return PrimitivePrice(
                priced=False,
                probability=None,
                method="growth",
                limitations=[
                    "NOT_PRICED: growth model needs current level, target, and fitted drift."
                ],
            )
        process = str(node["config"].get("process") or "loglinear")
        if process not in {"loglinear", "logistic"}:
            process = "loglinear"
        return price_growth(
            current=float(node["current"]),
            target=float(node["target"]),
            periods=horizon,
            mu=float(params["mu"]),
            sigma=float(params.get("sigma") or 0.05),
            process=process,  # type: ignore[arg-type]
            saturation=params.get("saturation") or node["config"].get("saturation_level"),
            direction="at_least",
            n_observations=int(params.get("n_observations") or 0),
        )
    if kind == "continuous_threshold":
        if node["current"] is None or node["target"] is None or "trend" not in params:
            return PrimitivePrice(
                priced=False,
                probability=None,
                method="continuous_threshold",
                limitations=["NOT_PRICED: threshold model needs current, target, and trend."],
            )
        direction = str(node["config"].get("direction") or "at_most")
        if direction not in {"at_least", "at_most"}:
            direction = "at_most"
        return price_continuous_threshold(
            current=float(node["current"]),
            target=float(node["target"]),
            periods=horizon,
            trend=float(params["trend"]),
            noise=float(params.get("noise") or 1.0),
            direction=direction,  # type: ignore[arg-type]
        )
    if kind == "funnel":
        conversions = [
            float(params[key])
            for key in params
            if key.startswith("conversion_") or key.startswith("stage_rate_")
        ]
        if not conversions:
            listed = node["config"].get("conversions")
            if isinstance(listed, list):
                conversions = [float(item) for item in listed]
        stages = node.get("stage_counts") or []
        independence = node.get("independence") or "unspecified"
        if independence not in {"assumed_independent", "unspecified"}:
            independence = "unspecified"
        if not conversions or len(stages) != len(conversions) + 1:
            return PrimitivePrice(
                priced=False,
                probability=None,
                method="funnel",
                limitations=["NOT_PRICED: funnel needs stage counts and conversion rates."],
            )
        return price_funnel(
            stage_counts=[int(item) for item in stages],
            conversions=conversions,
            expected_new_starts=float(params.get("expected_new_starts") or 0.0),
            independence=independence,  # type: ignore[arg-type]
        )
    if kind == "deadline_hazard":
        logits = params.get("baseline_logits")
        if logits is None and "logit" in params:
            logits = [float(params["logit"])] * max(1, int(round(horizon)))
        if logits is None:
            return PrimitivePrice(
                priced=False,
                probability=None,
                method="deadline_hazard",
                limitations=["NOT_PRICED: hazard model needs logits or a period logit."],
            )
        values = (
            logits if isinstance(logits, list) else [float(logits)] * max(1, int(round(horizon)))
        )
        return price_deadline_hazard(values)
    if kind == "habit":
        history = node["config"].get("history") or []
        if not isinstance(history, list) or not history:
            return PrimitivePrice(
                priced=False,
                probability=None,
                method="habit",
                limitations=["NOT_PRICED: habit model needs a trial history."],
            )
        return price_habit(
            history=[bool(item) for item in history],
            half_life=float(params.get("half_life") or 28.0),
            alpha=float(params.get("prior_alpha") or 1.0),
            beta=float(params.get("prior_beta") or 1.0),
            target_rate=params.get("target_rate"),
        )
    if kind == "dependency_dag":
        dag_nodes = node["config"].get("nodes") or []
        means = [
            float(item.get("duration_mean") or params.get("duration_mean") or 0.0)
            for item in dag_nodes
        ]
        stds = [
            float(item.get("duration_std") or max(mean * 0.3, 0.01))
            for item, mean in zip(dag_nodes, means, strict=True)
        ]
        index = {str(item.get("id")): i for i, item in enumerate(dag_nodes)}
        prereq = []
        for item in dag_nodes:
            prereq.append(
                [index[name] for name in item.get("prerequisites") or [] if name in index]
            )
        successes = [
            float(item["success_probability"])
            if item.get("success_probability") is not None
            else 1.0
            for item in dag_nodes
        ]
        correlation = str(node["config"].get("correlation") or "unspecified")
        if correlation not in {"independent", "shared_factor", "unspecified"}:
            correlation = "unspecified"
        return price_dependency_dag(
            durations_mean=means,
            durations_std=stds,
            horizon=horizon,
            prerequisites=prereq,
            success_probabilities=successes,
            correlation=correlation,  # type: ignore[arg-type]
            n_draws=int(node["config"].get("n_draws") or 4_000),
            seed=int(node["config"].get("seed") or 42),
        )
    if kind == "financial":
        return PrimitivePrice(
            priced=False,
            probability=None,
            method="financial",
            limitations=[
                "NOT_PRICED: use the existing finance adapter for monetary compound paths."
            ],
        )
    return PrimitivePrice(
        priced=False,
        probability=None,
        method=str(kind),
        limitations=[f"NOT_PRICED: primitive {kind} is registered but not executable here."],
    )


def _price_sequential(
    spec: ForecastSpecV2, prepared: dict[str, Any], inputs: NumericInputs
) -> PrimitivePrice:
    """Joint P(all stages complete by horizon) via waiting-time Monte Carlo.

    Does not multiply independent success probabilities. Each primitive contributes
    a waiting time; the path succeeds only if the sum (respecting prerequisites)
    is within the horizon.
    """
    rng = np.random.default_rng(int(prepared.get("seed") or 42))
    draws = min(max(int(prepared.get("n_draws") or 4_000), 200), 20_000)
    order = spec.composition.nodes or [node.id for node in spec.primitives]
    nodes = prepared["nodes"]
    horizon = float(prepared["horizon"])
    success = np.zeros(draws)
    terminals = np.zeros(draws)
    for draw in range(draws):
        elapsed = 0.0
        ok = True
        finished: dict[str, float] = {}
        for node_id in order:
            node = nodes[node_id]
            start = 0.0
            for pred in node.get("prerequisites") or []:
                start = max(start, finished.get(pred, 0.0))
            start = max(start, elapsed if not node.get("prerequisites") else start)
            wait = _waiting_time(node, horizon - start, rng)
            done = start + wait
            finished[node_id] = done
            elapsed = max(elapsed, done)
            if wait == math_inf() or done > horizon:
                ok = False
                break
        success[draw] = 1.0 if ok else 0.0
        terminals[draw] = elapsed
    frequency = monte_carlo_frequency(success)
    limitations = [
        "Sequential composition uses waiting-time Monte Carlo, "
        "not a product of stage probabilities.",
        *frequency.limitations,
    ]
    if spec.composition.correlation == "unspecified":
        limitations.append(
            "Cross-stage shocks are unspecified; draws treat waiting times as independent."
        )
    return PrimitivePrice(
        priced=True,
        probability=frequency.p_hat,
        method="sequential_waiting_time_mc",
        limitations=limitations,
        diagnostics=frequency.diagnostics(
            {
                "mean_terminal": float(np.mean(terminals)),
                "horizon": horizon,
                "join": "sequential_and",
                "seed": int(prepared.get("seed") or 42),
            }
        ),
        used_parameters=[
            {"parameter": "composition", "estimator": "waiting_time_mc", "source_kind": "estimated"}
        ],
    )


def math_inf() -> float:
    return float("inf")


def _waiting_time(node: dict[str, Any], remaining: float, rng: np.random.Generator) -> float:
    kind = node["kind"]
    params = node["parameters"]
    if remaining <= 0:
        return math_inf()
    if kind == "cumulative_count":
        current = float(node["current"] or 0.0)
        target = float(node["target"] or 0.0)
        remaining_count = max(int(np.ceil(target - current)), 0)
        return waiting_time_poisson(remaining_count, float(params.get("rate") or 0.0), rng)
    if kind == "growth":
        return waiting_time_loglinear(
            float(node["current"] or 0.0),
            float(node["target"] or 0.0),
            float(params.get("mu") or 0.0),
        )
    if kind == "dependency_dag":
        means = [
            float(item.get("duration_mean") or 1.0) for item in node["config"].get("nodes") or [{}]
        ]
        return float(max(means))
    if kind == "deadline_hazard":
        if float(node["current"] or 0.0) >= 1:
            return 0.0
        logit = params.get("logit", params.get("baseline_logit"))
        if logit is None:
            return math_inf()
        hazard = float(1.0 / (1.0 + np.exp(-float(logit))))
        if hazard <= 0:
            return math_inf()
        return float(rng.geometric(max(min(hazard, 1.0 - 1e-9), 1e-9)))
    if kind == "continuous_threshold":
        current = float(node["current"] or 0.0)
        target = float(node["target"] or 0.0)
        trend = float(params.get("trend") or 0.0)
        direction = str(node["config"].get("direction") or "at_most")
        if direction == "at_most":
            if current <= target:
                return 0.0
            if trend >= 0:
                return math_inf()
            return (current - target) / abs(trend)
        if current >= target:
            return 0.0
        if trend <= 0:
            return math_inf()
        return (target - current) / trend
    if kind == "funnel":
        conversions = node["config"].get("conversions") or []
        path = 1.0
        for rate in conversions:
            path *= float(rate)
        stage_counts = node.get("stage_counts") or []
        starts = float(
            node["parameters"].get("expected_new_starts")
            or (stage_counts[0] if stage_counts else 0.0)
        )
        rate = max(starts * path / max(remaining, 1e-6), 0.0)
        return waiting_time_poisson(1, rate, rng) if rate > 0 else math_inf()
    return math_inf()


def _family_unpriced(spec: ForecastSpecV2, limitations: list[str]) -> FamilyPrice:
    return FamilyPrice(
        priced=False,
        raw_probability=None,
        forecast_status="EXPLORATORY",
        limitations=limitations,
        transforms={"compiler_version": spec.compiler_version, "family": spec.family},
        used_assumptions=[],
    )
