from __future__ import annotations

import math
from datetime import UTC, datetime

from personal_markets.forecasting.engine import NumericInputs
from personal_markets.forecasting.families import AssumptionSource
from personal_markets.forecasting.hiring import STAGE_CHAIN, load_hiring_reference
from personal_markets.forecasting.running import load_running_reference
from personal_markets.goals.domain import GoalContract
from personal_markets.what_if.domain import Assumption

DEFAULT_EXECUTION = 0.72
_STAGE_LABELS = {
    "application_to_response": "Application → response conversion",
    "response_to_phone_screen": "Response → phone screen conversion",
    "phone_screen_to_oa": "Phone screen → OA conversion",
    "oa_to_technical": "OA → technical conversion",
    "technical_to_final": "Technical → final conversion",
    "final_to_offer": "Final → offer conversion",
}


def _map_source(source: str) -> AssumptionSource:
    mapping = {
        "REAL_USER_EVIDENCE": AssumptionSource.FITTED,
        "FITTED": AssumptionSource.FITTED,
        "REFERENCE": AssumptionSource.REFERENCE,
        "USER_ASSUMPTION": AssumptionSource.USER,
        "EXPLORATION_ASSUMPTION": AssumptionSource.EXPLORATION,
    }
    return mapping.get(source, AssumptionSource.REFERENCE)


def _assumption(
    *,
    assumption_id: str,
    name: str,
    description: str,
    value: float,
    minimum: float,
    maximum: float,
    step: float,
    source: AssumptionSource,
    unit: str,
    provenance: str,
    editable: bool,
    scope: str,
    model_family: str,
    version: str,
    timestamp: str | None = None,
) -> Assumption:
    return Assumption(
        id=assumption_id,
        name=name,
        description=description,
        value=value,
        minimum=minimum,
        maximum=maximum,
        step=step,
        source=source,
        unit=unit,
        provenance=provenance,
        editable=editable,
        scope=scope,
        model_family=model_family,
        version=version,
        timestamp=timestamp or datetime.now(UTC).isoformat(),
    )


def continuous_target_assumptions(
    goal: GoalContract,
    numeric: NumericInputs,
    *,
    model_family: str,
    model_version: str,
) -> list[Assumption]:
    running_ref = load_running_reference()
    return_distribution = numeric.assumptions.get("return_distribution")
    # Which branch produced the inputs decides the units and ranges. Goal type does
    # not: a savings target and a race time are both THRESHOLD goals but their flow
    # assumption means currency/month in one case and seconds/week in the other.
    is_flow_model = isinstance(return_distribution, dict)
    target_value = float(numeric.state.get("target_value") or 100)

    if isinstance(return_distribution, dict):
        flow = float(return_distribution.get("flow") or 0)
        growth_mean = float(return_distribution.get("growth_mean") or 0)
        growth_volatility = float(return_distribution.get("growth_volatility") or 0.03)
        shock_probability = float(return_distribution.get("shock_probability") or 0.02)
        shock_fraction = float(return_distribution.get("shock_fraction") or 0.08)
        flow_source = _map_source(
            str(numeric.assumption_sources.get("monthly_flow", "REAL_USER_EVIDENCE"))
        )
        flow_scope = "monthly_flow"
        flow_unit = "currency/month"
        flow_desc = "Recurring monthly contribution toward the target."
    else:
        trend = float(numeric.assumptions.get("trend") or 0)
        noise = float(
            numeric.assumptions.get("measurement_noise")
            or running_ref.min_measurement_noise_seconds
        )
        flow = trend
        growth_mean = 0.0
        growth_volatility = min(0.08, max(0.001, noise / max(target_value, 1)))
        shock_probability = 0.02
        shock_fraction = 0.08
        flow_source = _map_source(
            str(numeric.assumption_sources.get("trend", "REAL_USER_EVIDENCE"))
        )
        flow_scope = "training_trend"
        flow_unit = "seconds/week"
        flow_desc = "Weekly pace improvement trend from recent performance evidence."

    if is_flow_model:
        # Negative flow is a real scenario (pausing contributions, higher expenses),
        # so the range has to straddle zero and comfortably contain today's value.
        flow_max = max(target_value * 0.05, abs(flow) * 2.0, 1000.0)
        flow_min = -flow_max
        flow_step = max(1.0, round(flow_max / 200.0))
    else:
        # Negative is improving. The fitted trend can be faster than -30 s/week or a
        # slowdown (> 0), so the range widens to contain it.
        flow_min = min(-30.0, math.floor(flow * 2.0))
        flow_max = max(0.0, math.ceil(flow * 2.0))
        flow_step = 1.0
    ref_version = _reference_version(numeric)

    return [
        _assumption(
            assumption_id="flow",
            name="flow",
            description=flow_desc,
            value=flow,
            minimum=flow_min,
            maximum=flow_max,
            step=flow_step,
            source=flow_source,
            unit=flow_unit,
            provenance=f"Derived from goal evidence via {model_family}@{model_version}",
            editable=True,
            scope=flow_scope,
            model_family=model_family,
            version=model_version,
        ),
        _assumption(
            assumption_id="growth_mean",
            name="growth_mean",
            description="Expected per-period growth rate on the tracked metric.",
            value=growth_mean,
            minimum=-0.02,
            maximum=0.03,
            step=0.001,
            source=AssumptionSource.REFERENCE,
            unit="fraction/period",
            provenance=f"Reference prior for {model_family}; ref={ref_version or 'default'}",
            editable=True,
            scope="return_assumption",
            model_family=model_family,
            version=model_version,
        ),
        _assumption(
            assumption_id="growth_volatility",
            name="growth_volatility",
            description="Volatility of per-period growth around the mean.",
            value=growth_volatility,
            minimum=0.0,
            maximum=0.08,
            step=0.002,
            source=AssumptionSource.REFERENCE,
            unit="fraction/period",
            provenance=f"Reference prior for {model_family}; ref={ref_version or 'default'}",
            editable=True,
            scope="volatility",
            model_family=model_family,
            version=model_version,
        ),
        _assumption(
            assumption_id="shock_probability",
            name="shock_probability",
            description="Probability of a negative shock in any period.",
            value=shock_probability,
            minimum=0.0,
            maximum=0.2,
            step=0.01,
            source=AssumptionSource.REFERENCE,
            unit="probability/period",
            provenance=f"Reference shock prior for {model_family}",
            editable=True,
            scope="shock_assumption",
            model_family=model_family,
            version=model_version,
        ),
        _assumption(
            assumption_id="shock_fraction",
            name="shock_fraction",
            description="Fractional drawdown applied when a shock occurs.",
            value=shock_fraction,
            minimum=0.0,
            maximum=0.5,
            step=0.01,
            source=AssumptionSource.REFERENCE,
            unit="fraction",
            provenance=f"Reference shock severity for {model_family}",
            editable=True,
            scope="shock_assumption",
            model_family=model_family,
            version=model_version,
        ),
        _assumption(
            assumption_id="execution_probability",
            name="execution_probability",
            description="Probability the planned intervention is executed as specified.",
            value=DEFAULT_EXECUTION,
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            source=AssumptionSource.USER,
            unit="probability",
            provenance="User exploration assumption; not inferred from evidence.",
            editable=True,
            scope="execution",
            model_family=model_family,
            version=model_version,
        ),
    ]


def hazard_assumptions(
    numeric: NumericInputs,
    *,
    model_family: str,
    model_version: str,
) -> list[Assumption]:
    reference = load_hiring_reference()
    weekly_rate = float(
        numeric.assumptions.get("weekly_application_rate") or reference.weekly_application_rate
    )
    weekly_source = _map_source(
        str(numeric.assumption_sources.get("weekly_application_rate", "REFERENCE"))
    )
    periods = int(numeric.state.get("periods_remaining") or 1)
    ref_version = reference.version
    assumptions: list[Assumption] = [
        _assumption(
            assumption_id="weekly_application_rate",
            name="weekly_application_rate",
            description="Expected new applications submitted per week for the remaining horizon.",
            value=weekly_rate,
            minimum=0.0,
            maximum=50.0,
            step=1.0,
            source=weekly_source,
            unit="applications/week",
            provenance=(
                f"Reference default or user override; funnel ref={ref_version}. "
                "Observed application counts remain immutable evidence."
            ),
            editable=True,
            scope="pipeline_activity",
            model_family=model_family,
            version=model_version,
        ),
        _assumption(
            assumption_id="periods_remaining",
            name="periods_remaining",
            description="Weeks remaining until the goal deadline.",
            value=float(periods),
            minimum=1.0,
            maximum=float(max(periods, 52)),
            step=1.0,
            source=AssumptionSource.FITTED,
            unit="weeks",
            provenance="Derived from goal deadline; not a user-editable future assumption.",
            editable=False,
            scope="deadline_hazard",
            model_family=model_family,
            version=model_version,
        ),
    ]
    stage_rates = reference.stage_rates
    transforms = numeric.state.get("pricing_transforms")
    if isinstance(transforms, dict):
        embedded = transforms.get("stage_rates")
        if isinstance(embedded, dict):
            stage_rates = {key: float(embedded[key]) for key in STAGE_CHAIN if key in embedded}

    for stage_key in STAGE_CHAIN:
        rate = float(stage_rates.get(stage_key, reference.stage_rates[stage_key]))
        assumptions.append(
            _assumption(
                assumption_id=f"stage_rate_{stage_key}",
                name=stage_key,
                description=_STAGE_LABELS[stage_key],
                value=rate,
                minimum=0.01,
                maximum=0.99,
                step=0.02,
                source=AssumptionSource.REFERENCE,
                unit="probability",
                provenance=f"Frozen reference prior from {reference.reference_id}@{ref_version}",
                editable=True,
                scope="stage_conversion",
                model_family=model_family,
                version=model_version,
            )
        )

    assumptions.append(
        _assumption(
            assumption_id="execution_probability",
            name="execution_probability",
            description="Probability the planned pipeline changes are sustained.",
            value=DEFAULT_EXECUTION,
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            source=AssumptionSource.USER,
            unit="probability",
            provenance="User exploration assumption for plan follow-through.",
            editable=True,
            scope="execution",
            model_family=model_family,
            version=model_version,
        )
    )
    return assumptions


# The user-controllable rate of each composed primitive. Spread parameters (sigma,
# noise) describe fitted uncertainty and stay read-only.
COMPOSED_LEVER_PARAMETERS = {
    "cumulative_count": ("rate", "additions"),
    "continuous_threshold": ("trend", "change"),
    "growth": ("mu", "log growth"),
}
COMPOSED_READONLY_PARAMETERS = {"growth": ("sigma",), "continuous_threshold": ("noise",)}
# Search/edit bound for a composed rate: a multiple of the larger of today's rate and
# the pace the target requires. A range for the control, not evidence of feasibility.
COMPOSED_RATE_RANGE_MULTIPLE = 4.0
COMPOSED_RATE_STEPS = 200.0


def composed_assumptions(
    goal: GoalContract,
    numeric: NumericInputs,
    *,
    model_family: str,
    model_version: str,
) -> list[Assumption]:
    """Expose each composed primitive's fitted rate as an editable lever.

    The composition engine already accepts `node.parameter` overrides; this only
    makes them visible so What If and Reverse can price them instead of guessing.
    """
    prepared = numeric.state.get("composition_prepared")
    nodes = prepared.get("nodes") if isinstance(prepared, dict) else None
    spec = goal.model_requirements.get("forecast_spec") or {}
    primitives = spec.get("primitives") if isinstance(spec, dict) else None
    if not isinstance(nodes, dict) or not isinstance(primitives, list):
        return []
    horizon = float(numeric.state.get("periods") or 1.0)
    target = numeric.state.get("target_value")
    assumptions: list[Assumption] = []
    for primitive in primitives:
        if not isinstance(primitive, dict):
            continue
        node_id = str(primitive.get("id") or "")
        kind = str(primitive.get("kind") or "")
        node = nodes.get(node_id)
        lever = COMPOSED_LEVER_PARAMETERS.get(kind)
        if not isinstance(node, dict) or lever is None:
            continue
        parameters = node.get("parameters") or {}
        parameter, noun = lever
        if parameter not in parameters:
            continue
        value = float(parameters[parameter])
        metric = str(primitive.get("metric") or node_id).replace("_", " ")
        time_unit = str((primitive.get("config") or {}).get("time_unit") or "week")
        unit_text = str(primitive.get("unit") or metric)
        current = node.get("current")
        node_target = node.get("target", target)
        required = 0.0
        if current is not None and node_target is not None:
            gap = (
                math.log(float(node_target) / float(current))
                if kind == "growth" and float(current) > 0 and float(node_target) > 0
                else float(node_target) - float(current)
            )
            required = abs(gap) / max(horizon, 1.0)
        span = max(abs(value), required, 1e-6) * COMPOSED_RATE_RANGE_MULTIPLE
        if kind == "growth":
            minimum, maximum, unit = -span, span, f"log growth/{time_unit}"
        elif kind == "cumulative_count":
            minimum, maximum, unit = 0.0, span, f"{unit_text}/{time_unit}"
        else:
            minimum, maximum, unit = -span, span, f"{unit_text}/{time_unit}"
        source_tag = str(numeric.assumption_sources.get(f"{node_id}.{parameter}") or "estimated")
        assumptions.append(
            _assumption(
                assumption_id=f"{node_id}.{parameter}",
                name=f"{node_id}.{parameter}",
                description=(
                    f"Expected {noun} in {metric} per {time_unit} for the rest of the horizon."
                ),
                value=value,
                minimum=minimum,
                maximum=maximum,
                step=max(span / COMPOSED_RATE_STEPS, 1e-4),
                source=AssumptionSource.USER
                if source_tag == "user_assumption"
                else AssumptionSource.FITTED,
                unit=unit,
                provenance=f"{source_tag} {kind} parameter via {model_family}@{model_version}",
                editable=True,
                scope="composed_rate",
                model_family=model_family,
                version=model_version,
            )
        )
        for readonly in COMPOSED_READONLY_PARAMETERS.get(kind, ()):
            if readonly not in parameters:
                continue
            spread = float(parameters[readonly])
            assumptions.append(
                _assumption(
                    assumption_id=f"{node_id}.{readonly}",
                    name=f"{node_id}.{readonly}",
                    description=f"Fitted uncertainty around the {metric} {noun} rate.",
                    value=spread,
                    minimum=0.0,
                    maximum=max(spread * 2.0, 1e-3),
                    step=max(spread / 100.0, 1e-4),
                    source=AssumptionSource.FITTED,
                    unit=unit,
                    provenance=f"Fitted spread via {model_family}@{model_version}",
                    editable=False,
                    scope="composed_spread",
                    model_family=model_family,
                    version=model_version,
                )
            )
    if not any(item.editable for item in assumptions):
        return assumptions
    assumptions.append(
        _assumption(
            assumption_id="execution_probability",
            name="execution_probability",
            description="Probability the planned change in rate is sustained.",
            value=DEFAULT_EXECUTION,
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            source=AssumptionSource.USER,
            unit="probability",
            provenance="User exploration assumption for plan follow-through.",
            editable=True,
            scope="execution",
            model_family=model_family,
            version=model_version,
        )
    )
    return assumptions


def editable_assumption_names(assumptions: list[Assumption]) -> tuple[str, ...]:
    return tuple(item.name for item in assumptions if item.editable)


def _reference_version(numeric: NumericInputs) -> str | None:
    transforms = numeric.state.get("pricing_transforms")
    if isinstance(transforms, dict):
        version = transforms.get("reference_version")
        if isinstance(version, str):
            return version
    return None
