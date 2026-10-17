from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.forecasting.engine import NumericInputs
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.targets import resolve_target_duration_seconds, target_direction
from personal_markets.ports import GoalArchitectProposal

REFERENCE_ID = "running_performance_assumptions.json"


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[5]


@dataclass(frozen=True, slots=True)
class RunObservation:
    distance_km: float
    duration_seconds: float
    observed_at: datetime
    metric: str
    conversion_applied: bool = False
    conversion_source: str | None = None
    original_distance_km: float | None = None
    original_duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class RunningState:
    observations: tuple[RunObservation, ...] = ()
    weekly_distance_km: float | None = None
    missed_sessions: int = 0
    goal_distance_km: float | None = None


@dataclass(frozen=True, slots=True)
class RunningReference:
    riegel_exponent: float
    conversion_uncertainty_seconds: float
    measurement_noise_seconds: float
    min_measurement_noise_seconds: float
    trend_uncertainty_seconds_per_day: float
    adherence: float
    goal_distance_tolerance_km: float
    reference_id: str
    version: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrendFit:
    projected_seconds: float
    trend_seconds_per_day: float
    measurement_noise_seconds: float
    observation_count: int
    best_recent_seconds: float
    direct_goal_distance_count: int
    converted_count: int
    slope_seconds_per_day: float
    residual_std_seconds: float


def load_running_reference(root: Path | None = None) -> RunningReference:
    path = (root or _repo_root() / "data" / "reference") / REFERENCE_ID
    payload = json.loads(path.read_text(encoding="utf-8"))
    defaults = payload.get("defaults") or {}
    conversion = (payload.get("models") or {}).get("distance_conversion") or {}
    return RunningReference(
        riegel_exponent=float(conversion.get("exponent", 1.06)),
        conversion_uncertainty_seconds=float(
            conversion.get("conversion_uncertainty_seconds", 45.0)
        ),
        measurement_noise_seconds=float(defaults.get("measurement_noise_seconds", 35.0)),
        min_measurement_noise_seconds=float(defaults.get("min_measurement_noise_seconds", 15.0)),
        trend_uncertainty_seconds_per_day=float(
            defaults.get("trend_uncertainty_seconds_per_day", 2.5)
        ),
        adherence=float(defaults.get("adherence", 1.0)),
        goal_distance_tolerance_km=float(defaults.get("goal_distance_tolerance_km", 0.75)),
        reference_id=REFERENCE_ID,
        version=str(payload.get("version") or "unknown"),
        limitations=tuple(payload.get("limitations") or []),
    )


def is_running_goal(goal: GoalContract, proposal: GoalArchitectProposal | None = None) -> bool:
    blob = " ".join(
        [
            goal.title,
            str(goal.success_definition),
            " ".join(goal.state_dimensions),
            proposal.success_metric if proposal else "",
        ]
    ).lower()
    metric = str(goal.success_definition.get("metric") or "").lower()
    tokens = (
        "10k",
        "10k_time",
        "run",
        "running",
        "race",
        "marathon",
        "5k",
        "pace",
        "weekly_distance",
        "training",
    )
    return goal.goal_type.value == "threshold" and (
        metric in {"10k_time_seconds", "race_time_seconds", "run_time_seconds"}
        or any(token in blob for token in tokens)
    )


def goal_distance_km(goal: GoalContract) -> float:
    metric = str(goal.success_definition.get("metric") or "").lower()
    if "10k" in metric or "10_k" in metric:
        return 10.0
    if "5k" in metric or "5_k" in metric:
        return 5.0
    blob = goal.title.lower()
    if "10k" in blob or "10 k" in blob:
        return 10.0
    if "5k" in blob or "5 k" in blob:
        return 5.0
    return 10.0


def target_time_seconds(goal: GoalContract) -> float | None:
    """Race-time targets arrive either as seconds or as a clock string like 1:40:00."""
    return resolve_target_duration_seconds(goal)


def goal_direction(goal: GoalContract) -> Literal["at_most", "at_least"]:
    direction = target_direction(goal, default="at_most")
    return "at_most" if direction == "at_most" else "at_least"


def aggregate_running_from_evidence(
    evidence: list[NormalizedEvidence],
    *,
    goal: GoalContract | None = None,
    now: datetime | None = None,
) -> RunningState:
    clock = now or datetime.now(UTC)
    observations: list[RunObservation] = []
    weekly_distance: float | None = None
    missed_sessions = 0
    target_distance = goal_distance_km(goal) if goal else None

    for item in evidence:
        metric = item.metric.lower()
        summary = item.summary.lower()
        observed = item.observed_at or clock
        if _is_missed_session(metric, summary):
            missed_sessions += 1
            continue
        if metric in {"weekly_distance_km", "weekly_mileage_km", "weekly_distance"}:
            if item.numeric_value is not None:
                weekly_distance = float(item.numeric_value)
            continue
        parsed = _parse_run_observation(item, observed)
        if parsed is not None:
            observations.append(parsed)

    observations.sort(key=lambda item: item.observed_at)
    if target_distance is not None:
        observations = _normalize_to_goal_distance(
            observations, target_distance, load_running_reference()
        )
    return RunningState(
        observations=tuple(observations),
        weekly_distance_km=weekly_distance,
        missed_sessions=missed_sessions,
        goal_distance_km=target_distance,
    )


def apply_running_overrides(
    state: RunningState, overrides: dict[str, Any] | None
) -> RunningState:
    if not overrides:
        return state
    updated = state
    if "weekly_distance_km" in overrides:
        updated = replace(updated, weekly_distance_km=float(overrides["weekly_distance_km"]))
    if "missed_sessions" in overrides:
        updated = replace(updated, missed_sessions=int(overrides["missed_sessions"]))
    return updated


def build_running_numeric_inputs(
    goal: GoalContract,
    proposal: GoalArchitectProposal | None,
    evidence: list[NormalizedEvidence],
    *,
    overrides: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> NumericInputs | None:
    if not is_running_goal(goal, proposal):
        return None
    state = aggregate_running_from_evidence(evidence, goal=goal, now=now)
    state = apply_running_overrides(state, overrides)
    return running_state_to_numeric_inputs(goal, state, now=now)


def running_state_to_numeric_inputs(
    goal: GoalContract,
    state: RunningState,
    *,
    reference: RunningReference | None = None,
    now: datetime | None = None,
) -> NumericInputs | None:
    ref = reference or load_running_reference()
    clock = now or datetime.now(UTC)
    target = target_time_seconds(goal)
    goal_km = state.goal_distance_km or goal_distance_km(goal)
    if target is None or not state.observations:
        return None

    fit = fit_performance_trend(state.observations, goal.deadline, clock, ref)
    direction = goal_direction(goal)
    periods = max(1, math.ceil((goal.deadline - clock).total_seconds() / 604800))

    transforms: dict[str, Any] = {
        "running_state": {
            "observation_count": fit.observation_count,
            "direct_goal_distance_count": fit.direct_goal_distance_count,
            "converted_count": fit.converted_count,
            "best_recent_seconds": fit.best_recent_seconds,
            "projected_seconds": fit.projected_seconds,
            "trend_seconds_per_day": fit.trend_seconds_per_day,
            "weekly_distance_km": state.weekly_distance_km,
            "missed_sessions": state.missed_sessions,
            "goal_distance_km": goal_km,
        },
        "reference_version": ref.version,
    }
    if fit.converted_count:
        transforms["distance_conversion"] = {
            "model": "riegel",
            "exponent": ref.riegel_exponent,
            "source": "REFERENCE",
        }

    return NumericInputs(
        state={
            "current_value": fit.projected_seconds,
            "target_value": target,
            "periods": periods,
            "direction": direction,
            "observations": [
                {
                    "duration_seconds": item.duration_seconds,
                    "distance_km": item.distance_km,
                    "observed_at": item.observed_at.isoformat(),
                    "conversion_applied": item.conversion_applied,
                }
                for item in state.observations
            ],
            "pricing_transforms": transforms,
        },
        assumptions={
            "trend": fit.trend_seconds_per_day * 7.0,
            "measurement_noise": fit.measurement_noise_seconds,
            "adherence": ref.adherence,
        },
        assumption_sources={
            "trend": "REAL_USER_EVIDENCE" if fit.observation_count >= 2 else "REFERENCE",
            "measurement_noise": "REAL_USER_EVIDENCE"
            if fit.residual_std_seconds > ref.min_measurement_noise_seconds
            else "REFERENCE",
            "adherence": "REFERENCE",
        },
    )


def price_from_numeric_inputs(inputs: NumericInputs) -> tuple[float | None, dict[str, Any]]:
    current = inputs.state.get("current_value")
    target = inputs.state.get("target_value")
    direction = str(inputs.state.get("direction") or "at_most")
    if current is None or target is None:
        return None, {}
    try:
        projected = float(current)
        target_value = float(target)
        noise = float(inputs.assumptions.get("measurement_noise") or 35.0)
        trend_weekly = float(inputs.assumptions.get("trend") or 0.0)
    except (TypeError, ValueError):
        return None, {}

    periods = int(inputs.state.get("periods") or 1)
    trend_daily = trend_weekly / 7.0
    ref = load_running_reference()
    trend_sigma = ref.trend_uncertainty_seconds_per_day * math.sqrt(max(1, periods * 7))
    sigma = math.sqrt(noise**2 + trend_sigma**2)

    if direction == "at_most":
        if projected <= target_value:
            probability = 0.995
        else:
            probability = _normal_cdf(target_value, projected, sigma)
    else:
        if projected >= target_value:
            probability = 0.995
        else:
            probability = 1.0 - _normal_cdf(target_value, projected, sigma)

    probability = min(max(probability, 1e-6), 1.0 - 1e-6)
    transforms = inputs.state.get("pricing_transforms")
    if not isinstance(transforms, dict):
        transforms = {}
    diagnostics = {
        "projected_seconds": projected,
        "target_seconds": target_value,
        "measurement_noise_seconds": noise,
        "trend_seconds_per_week": trend_weekly,
        "trend_seconds_per_day": trend_daily,
        "sigma_deadline_seconds": sigma,
        "direction": direction,
    }
    return probability, {**transforms, "threshold_diagnostics": diagnostics}


def fit_performance_trend(
    observations: tuple[RunObservation, ...],
    deadline: datetime,
    now: datetime,
    reference: RunningReference,
) -> TrendFit:
    times = np.array([item.duration_seconds for item in observations], dtype=float)
    days_ago = np.array(
        [(now - item.observed_at).total_seconds() / 86400.0 for item in observations],
        dtype=float,
    )
    best_recent = float(np.min(times))
    direct_count = sum(1 for item in observations if not item.conversion_applied)
    converted_count = sum(1 for item in observations if item.conversion_applied)

    if len(observations) == 1:
        slope = 0.0
        projected = float(times[0])
        residual_std = reference.measurement_noise_seconds
    else:
        slope, intercept = _linear_fit(days_ago, times)
        days_to_deadline = max(0.0, (deadline - now).total_seconds() / 86400.0)
        projected = float(intercept - slope * days_to_deadline)
        residuals = times - (intercept + slope * days_ago)
        residual_std = float(np.std(residuals, ddof=1)) if len(times) > 1 else 0.0
        residual_std = max(residual_std, reference.min_measurement_noise_seconds)

    if converted_count and not direct_count:
        residual_std = math.sqrt(residual_std**2 + reference.conversion_uncertainty_seconds**2)

    noise = max(residual_std, reference.measurement_noise_seconds)
    return TrendFit(
        projected_seconds=projected,
        trend_seconds_per_day=float(-slope),
        measurement_noise_seconds=noise,
        observation_count=len(observations),
        best_recent_seconds=best_recent,
        direct_goal_distance_count=direct_count,
        converted_count=converted_count,
        slope_seconds_per_day=float(slope),
        residual_std_seconds=residual_std,
    )


def _normalize_to_goal_distance(
    observations: list[RunObservation],
    goal_distance_km: float,
    reference: RunningReference,
) -> list[RunObservation]:
    normalized: list[RunObservation] = []
    tolerance = reference.goal_distance_tolerance_km
    for item in observations:
        if abs(item.distance_km - goal_distance_km) <= tolerance:
            normalized.append(item)
            continue
        converted = riegel_convert(
            item.duration_seconds,
            item.distance_km,
            goal_distance_km,
            reference.riegel_exponent,
        )
        normalized.append(
            replace(
                item,
                duration_seconds=converted,
                distance_km=goal_distance_km,
                conversion_applied=True,
                conversion_source="riegel",
                original_distance_km=item.distance_km,
                original_duration_seconds=item.duration_seconds,
            )
        )
    return normalized


def riegel_convert(
    duration_seconds: float, from_km: float, to_km: float, exponent: float
) -> float:
    if from_km <= 0 or to_km <= 0:
        return duration_seconds
    return float(duration_seconds * (to_km / from_km) ** exponent)


def _parse_run_observation(
    item: NormalizedEvidence, observed: datetime
) -> RunObservation | None:
    metric = item.metric.lower()
    summary = item.summary.lower()
    value = item.numeric_value
    unit = (item.unit or "").lower()

    if metric in {"10k_time_seconds", "race_time_seconds", "run_time_seconds", "duration_seconds"}:
        if value is None:
            return None
        distance = _distance_from_metric(metric, summary, item.categorical_value)
        return RunObservation(
            distance_km=distance,
            duration_seconds=float(value),
            observed_at=observed,
            metric=metric,
        )

    if metric in {"distance_km", "run_distance_km"} and value is not None:
        duration = _duration_from_summary(summary)
        if duration is None:
            return None
        return RunObservation(
            distance_km=float(value),
            duration_seconds=duration,
            observed_at=observed,
            metric=metric,
        )

    if metric in {"pace_seconds_per_km", "pace"} and value is not None:
        distance = _distance_from_summary(summary) or 5.0
        return RunObservation(
            distance_km=distance,
            duration_seconds=float(value) * distance,
            observed_at=observed,
            metric=metric,
        )

    if "10k" in metric or "10k" in summary:
        if value is None:
            return None
        seconds = float(value)
        if unit in {"minutes", "minute", "min"}:
            seconds *= 60
        return RunObservation(10.0, seconds, observed, metric)

    if "5k" in metric or "5k" in summary:
        if value is None:
            return None
        seconds = float(value)
        if unit in {"minutes", "minute", "min"}:
            seconds *= 60
        return RunObservation(5.0, seconds, observed, metric)

    return None


def _distance_from_metric(metric: str, summary: str, category: str | None) -> float:
    blob = " ".join([metric, summary, category or ""]).lower()
    if "10" in blob and "k" in blob:
        return 10.0
    if "5" in blob and "k" in blob:
        return 5.0
    if "8" in blob and "k" in blob:
        return 8.0
    return 10.0


def _distance_from_summary(summary: str) -> float | None:
    if not summary:
        return None
    lowered = summary.lower()
    if "10" in lowered and "k" in lowered:
        return 10.0
    if "8" in lowered and "k" in lowered:
        return 8.0
    if "5" in lowered and "k" in lowered:
        return 5.0
    return None


def _duration_from_summary(summary: str) -> float | None:
    if not summary:
        return None
    for token in summary.replace(":", " ").split():
        if token.endswith("s") and token[:-1].isdigit():
            return float(token[:-1])
    return None


def _is_missed_session(metric: str, summary: str) -> bool:
    blob = f"{metric} {summary}".lower()
    return "missed" in blob or "skipped" in blob or "completion" in blob and "missed" in blob


def _linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    if x.size < 2:
        return 0.0, float(y[0])
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


def _normal_cdf(x: float, mean: float, std: float) -> float:
    if std <= 0:
        return 1.0 if x >= mean else 0.0
    z = (x - mean) / (std * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))
