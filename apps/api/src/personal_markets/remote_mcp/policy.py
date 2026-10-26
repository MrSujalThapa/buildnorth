"""What evidence a goal accepts, derived from its ForecastSpec and evidence contracts.

The policy is read-only metadata: it never decides a probability. It tells an external
agent which canonical metrics the goal's model consumes, in which unit, and how each
observation kind is aggregated, so structured submissions do not need an LLM.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from personal_markets.evidence.metrics import (
    canonicalize_metric,
    clip_metric_name,
    is_period_metric,
)
from personal_markets.forecasting.inputs_builder import proposal_from_goal
from personal_markets.forecasting.priceability import requirements_for
from personal_markets.goals.domain import GoalContract

Kind = Literal["snapshot", "increment", "period"]

KIND_SEMANTICS: dict[str, str] = {
    "snapshot": (
        "The current total or level at observed_at (for example 'applications submitted so "
        "far is 18'). The latest snapshot replaces earlier ones; repeating the same value "
        "corroborates rather than adds."
    ),
    "increment": (
        "Additional occurrences on the day of observed_at (for example 'sent 2 more "
        "applications today'). Increments after the latest snapshot add to it. Each distinct "
        "idempotency_key is a distinct occurrence; retrying the same key never adds twice."
    ),
    "period": (
        "One measurement for a period (ISO week for weekly_* metrics, calendar month "
        "otherwise), derived from observed_at or the explicit period. A later value for the "
        "same period is a separate reading; the latest reading is used."
    ),
}

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")
_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_GENERIC_COUNT_UNITS = {"count", "units", "items", "number", "#"}
_MAX_FUTURE = timedelta(days=1)

VALIDATION_RULES = [
    "metric must be one of the canonical metrics or aliases listed here.",
    "unit must match the metric's declared unit (case-insensitive).",
    "observation_kind is required and must be one of the metric's accepted_kinds.",
    "Provide observed_at (ISO-8601) or period ('YYYY-Www' for weekly metrics, 'YYYY-MM' "
    "otherwise). observed_at may not be more than 1 day in the future.",
    "idempotency_key is required: 8-128 characters of letters, digits, '.', '_', ':' or '-'. "
    "Reusing a key with a different payload is rejected.",
    "Evidence submitted by an agent is recorded as agent_reported. Trust is assigned by "
    "PlayItOut, not by the submitter.",
]


class MetricPolicy(BaseModel):
    metric: str
    label: str
    unit: str
    required: bool
    accepted_names: list[str]
    accepted_kinds: list[Kind]
    default_kind: Kind
    example: str | None = None
    why: str


class ObservationPolicy(BaseModel):
    goal_id: str
    model_family: str | None
    priceable_family: bool
    metrics: list[MetricPolicy]
    kind_semantics: dict[str, str]
    validation_rules: list[str]
    limitations: list[str]


def _spec_kinds(goal: GoalContract) -> dict[str, str]:
    spec = goal.model_requirements.get("forecast_spec") or {}
    kinds: dict[str, str] = {}
    for item in spec.get("observable_inputs") or []:
        metric = str(item.get("metric") or "")
        if metric:
            kinds[canonicalize_metric(metric)] = str(item.get("kind") or "snapshot")
    return kinds


def _accepted(canonical: str, unit: str, spec_kind: str | None) -> list[Kind]:
    normalized = unit.strip().lower()
    if spec_kind == "rate":
        return ["period", "snapshot"]
    if spec_kind in {"continuous", "categorical"}:
        return ["snapshot"]
    if is_period_metric(canonical) or "/" in normalized:
        return ["period", "snapshot"]
    if normalized in {"seconds", "percent", "%", "parameter"} or normalized.startswith("fraction"):
        return ["snapshot"]
    return ["snapshot", "increment", "period"]


def _default(accepted: list[Kind], spec_kind: str | None) -> Kind:
    if spec_kind in accepted:
        return spec_kind  # type: ignore[return-value]
    return accepted[0]


def observation_policy(goal: GoalContract) -> ObservationPolicy:
    match = requirements_for(goal, proposal_from_goal(goal))
    if match is None:
        return ObservationPolicy(
            goal_id=str(goal.goal_id),
            model_family=None,
            priceable_family=False,
            metrics=[],
            kind_semantics=KIND_SEMANTICS,
            validation_rules=VALIDATION_RULES,
            limitations=[
                "No numerical model family covers this goal yet, so structured evidence "
                "cannot move a forecast. PlayItOut will not invent a probability for it."
            ],
        )
    family, requirements = match
    spec_kinds = _spec_kinds(goal)
    metrics: list[MetricPolicy] = []
    for requirement in requirements:
        if requirement.unit == "parameter":
            continue
        canonical = canonicalize_metric(requirement.key)
        names = sorted(
            {canonical, requirement.key, *(canonicalize_metric(a) for a in requirement.aliases)}
        )
        spec_kind = spec_kinds.get(canonical)
        accepted = _accepted(canonical, requirement.unit, spec_kind)
        metrics.append(
            MetricPolicy(
                metric=canonical,
                label=requirement.label,
                unit=requirement.unit,
                required=requirement.required,
                accepted_names=names,
                accepted_kinds=accepted,
                default_kind=_default(accepted, spec_kind),
                example=requirement.example,
                why=requirement.why,
            )
        )
    limitations = []
    if any(requirement.unit == "parameter" for requirement in requirements):
        limitations.append(
            "Some model parameters are fitted from history or set as explicit assumptions; "
            "they are not accepted as evidence."
        )
    return ObservationPolicy(
        goal_id=str(goal.goal_id),
        model_family=family,
        priceable_family=True,
        metrics=metrics,
        kind_semantics=KIND_SEMANTICS,
        validation_rules=VALIDATION_RULES,
        limitations=limitations,
    )


def informational_policy(metric: str, unit: str | None = None, kind: str | None = None) -> MetricPolicy:
    """Persist a legitimate observation the numerical model cannot consume."""
    accepted: list[Kind] = ["snapshot", "increment", "period"]
    default: Kind = kind if kind in accepted else "increment"
    clipped = clip_metric_name(metric)
    return MetricPolicy(
        metric=clipped,
        label=clipped.replace("_", " "),
        unit=(unit or "count"),
        required=False,
        accepted_names=[clipped, metric],
        accepted_kinds=accepted,
        default_kind=default,
        why="Recorded as informational evidence. The numerical model has no coefficient for it.",
    )


def match_metric(policy: ObservationPolicy, metric: str) -> MetricPolicy | None:
    canonical = canonicalize_metric(metric)
    for item in policy.metrics:
        if canonical == item.metric or canonical in item.accepted_names:
            return item
    return None


def unit_matches(declared: str, provided: str, metric: MetricPolicy) -> bool:
    left = declared.strip().lower()
    right = provided.strip().lower()
    if left == right:
        return True
    if left in _GENERIC_COUNT_UNITS:
        tokens = {part for part in re.split(r"[_\s]+", metric.metric) if part}
        return right in _GENERIC_COUNT_UNITS or right in tokens or right.rstrip("s") in tokens
    if left.startswith("currency"):
        suffix = left.removeprefix("currency")
        return bool(re.fullmatch(r"[a-z]{3}" + re.escape(suffix), right))
    return False


def resolve_observed_at(
    metric: MetricPolicy, observed_at: str | None, period: str | None, now: datetime
) -> datetime:
    """Return the timestamp a submission is filed under, or raise ValueError."""
    if observed_at:
        try:
            parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("observed_at must be ISO-8601") from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed > now + _MAX_FUTURE:
            raise ValueError("observed_at is in the future")
        return parsed
    if not period:
        raise ValueError("observed_at or period is required")
    weekly = metric.metric.startswith("weekly_")
    week = _WEEK.match(period)
    month = _MONTH.match(period)
    if weekly and week:
        start = datetime.fromisocalendar(int(week.group(1)), int(week.group(2)), 1)
    elif not weekly and month:
        start = datetime(int(month.group(1)), int(month.group(2)), 1)
    else:
        expected = "YYYY-Www" if weekly else "YYYY-MM"
        raise ValueError(f"period must look like {expected} for {metric.metric}")
    start = start.replace(tzinfo=UTC)
    if start > now + _MAX_FUTURE:
        raise ValueError("period is in the future")
    return start
