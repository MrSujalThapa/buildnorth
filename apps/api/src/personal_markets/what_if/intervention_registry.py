from __future__ import annotations

from personal_markets.goals.domain import GoalContract, GoalType

KNOWN_METRICS: dict[str, set[str]] = {
    "finance": {
        "monthly_contribution",
        "contribution_per_month",
        "net_worth",
        "burn_monthly",
    },
    "running": {
        "weekly_running_km",
        "running_days_per_week",
        "weekly_distance_km",
        "10k_time_seconds",
    },
    "career": {
        "applications_per_week",
        "applications_per_month",
        "daily_practice_problems",
        "weekly_application_rate",
        "mock_interviews_per_week",
        "linkedin_posts_per_week",
        "networking_events_per_week",
        "sleep_hours_per_night",
    },
    "startup": {
        "user_conversations_per_week",
        "burn_monthly",
        "hours_on_startup_per_week",
        "sales_calls_per_week",
    },
    # `execution_probability` is deliberately absent: follow-through is estimated from
    # observed behavior, so an intervention proposal may never set it directly.
    "generic": {
        "flow",
    },
}


def goal_domain(goal: GoalContract) -> str:
    dims = " ".join(goal.state_dimensions).lower()
    title = goal.title.lower()
    if goal.goal_type == GoalType.CONTINUOUS_TARGET or "net worth" in title or "finance" in dims:
        return "finance"
    if goal.goal_type == GoalType.THRESHOLD and ("run" in title or "10k" in title or "running" in dims):
        return "running"
    if goal.goal_type == GoalType.MULTI_OUTCOME or "startup" in title:
        return "startup"
    if goal.goal_type == GoalType.DEADLINE_EVENT and any(
        token in title or token in dims for token in ("offer", "career", "interview", "fde", "swe", "job")
    ):
        return "career"
    return "generic"


_COMPOSED_PARAMETERS: dict[str, tuple[str, str]] = {
    "cumulative_count": ("rate", "count/{time_unit}"),
    "growth": ("mu", "log_growth/{time_unit}"),
    "continuous_threshold": ("trend", "{unit}/{time_unit}"),
}


def composed_metric_units(goal: GoalContract) -> dict[str, str]:
    """Simulator parameters of a composed forecast spec, keyed `node.parameter`, with units."""
    spec = goal.model_requirements.get("forecast_spec")
    if not isinstance(spec, dict) or not str(spec.get("family") or "").startswith("composed_"):
        return {}
    units: dict[str, str] = {}
    for node in spec.get("primitives") or []:
        entry = _COMPOSED_PARAMETERS.get(str(node.get("kind")))
        if entry is None:
            continue
        parameter, template = entry
        config = node.get("config") or {}
        units[f"{node.get('id')}.{parameter}"] = template.format(
            time_unit=config.get("time_unit") or "week",
            unit=node.get("unit") or spec.get("units") or "units",
        )
    return units


def allowed_metrics(goal: GoalContract) -> set[str]:
    composed = composed_metric_units(goal)
    domain = goal_domain(goal)
    metrics = set(KNOWN_METRICS["generic"])
    metrics.update(KNOWN_METRICS.get(domain, set()))
    if not composed:
        return metrics
    extras = set(composed)
    if domain == "career":
        extras.update(
            {
                "applications_per_week",
                "applications_per_month",
                "weekly_application_rate",
            }
        )
    return extras
