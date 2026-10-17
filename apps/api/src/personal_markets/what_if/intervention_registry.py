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


def allowed_metrics(goal: GoalContract) -> set[str]:
    domain = goal_domain(goal)
    metrics = set(KNOWN_METRICS["generic"])
    metrics.update(KNOWN_METRICS.get(domain, set()))
    return metrics
