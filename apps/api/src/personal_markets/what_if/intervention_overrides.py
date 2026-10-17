from __future__ import annotations

from personal_markets.forecasting.families import AssumptionSource
from personal_markets.what_if.domain import Assumption
from personal_markets.what_if.intervention_models import InterventionChangeResponse

_SOURCE_MAP = {
    "USER_ASSUMPTION": AssumptionSource.USER,
    "EXPLORATION_ASSUMPTION": AssumptionSource.EXPLORATION,
    "REFERENCE": AssumptionSource.REFERENCE,
    "FITTED": AssumptionSource.FITTED,
}


def _assumption_source(provenance: str) -> AssumptionSource:
    return _SOURCE_MAP.get(provenance, AssumptionSource.USER)


def apply_parsed_changes_to_assumptions(
    assumptions: list[Assumption],
    changes: list[InterventionChangeResponse],
) -> list[Assumption]:
    """Map parsed intervention metrics onto generic What If assumption sliders.

    Effects are not inferred here; only explicit quantity edits propagate.
    """

    if not changes:
        return assumptions

    by_name = {item.name: item for item in assumptions}

    for change in changes:
        source = _assumption_source(change.provenance)
        if change.metric in by_name:
            # The agent named a model assumption directly (for example `flow`), so the
            # edit is applied as stated. No effect size is inferred here.
            assumption = by_name[change.metric]
            if change.operation == "set":
                value = change.value
            elif change.operation == "subtract":
                value = assumption.value - change.value
            else:
                value = assumption.value + change.value
            by_name[change.metric] = assumption.model_copy(
                update={
                    "value": max(assumption.minimum, min(assumption.maximum, value)),
                    "source": source,
                }
            )
        elif change.metric in {"monthly_contribution", "contribution_per_month"}:
            if "flow" not in by_name:
                continue
            flow = by_name["flow"]
            value = change.value if change.operation == "set" else flow.value + change.value
            by_name["flow"] = flow.model_copy(
                update={"value": max(flow.minimum, min(flow.maximum, value)), "source": source}
            )
        elif change.metric == "weekly_running_km" and "flow" in by_name:
            flow = by_name["flow"]
            km_delta = change.value if change.operation == "set" else change.value
            trend_proxy = -0.25 * km_delta
            value = flow.value + trend_proxy if change.operation == "add" else trend_proxy
            by_name["flow"] = flow.model_copy(
                update={
                    "value": max(flow.minimum, min(flow.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "daily_practice_problems" and "execution_probability" in by_name:
            execution = by_name["execution_probability"]
            boost = min(0.15, change.value * 0.02)
            value = execution.value + boost if change.operation == "add" else min(1.0, 0.5 + boost)
            by_name["execution_probability"] = execution.model_copy(
                update={
                    "value": max(execution.minimum, min(execution.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "applications_per_week" and "weekly_application_rate" in by_name:
            rate = by_name["weekly_application_rate"]
            value = change.value if change.operation == "set" else rate.value + change.value
            by_name["weekly_application_rate"] = rate.model_copy(
                update={
                    "value": max(rate.minimum, min(rate.maximum, value)),
                    "source": source,
                }
            )
        elif change.metric == "burn_monthly" and "flow" in by_name:
            flow = by_name["flow"]
            delta = -abs(change.value) / 1000.0
            value = flow.value + delta if change.operation == "add" else delta
            by_name["flow"] = flow.model_copy(
                update={
                    "value": max(flow.minimum, min(flow.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "mock_interviews_per_week" and "execution_probability" in by_name:
            execution = by_name["execution_probability"]
            boost = min(0.12, change.value * 0.03)
            value = execution.value + boost if change.operation != "set" else min(1.0, 0.45 + boost)
            by_name["execution_probability"] = execution.model_copy(
                update={
                    "value": max(execution.minimum, min(execution.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "linkedin_posts_per_week" and "weekly_application_rate" in by_name:
            rate = by_name["weekly_application_rate"]
            delta = min(3.0, change.value * 0.25)
            value = rate.value + delta if change.operation != "set" else change.value
            by_name["weekly_application_rate"] = rate.model_copy(
                update={
                    "value": max(rate.minimum, min(rate.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "sleep_hours_per_night" and "execution_probability" in by_name:
            execution = by_name["execution_probability"]
            boost = min(0.08, change.value * 0.02)
            value = execution.value + boost
            by_name["execution_probability"] = execution.model_copy(
                update={
                    "value": max(execution.minimum, min(execution.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "running_days_per_week" and "flow" in by_name:
            flow = by_name["flow"]
            trend_proxy = -0.15 * change.value
            value = flow.value + trend_proxy if change.operation == "add" else trend_proxy
            by_name["flow"] = flow.model_copy(
                update={
                    "value": max(flow.minimum, min(flow.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "user_conversations_per_week" and "execution_probability" in by_name:
            execution = by_name["execution_probability"]
            boost = min(0.1, change.value * 0.005)
            value = execution.value + boost
            by_name["execution_probability"] = execution.model_copy(
                update={
                    "value": max(execution.minimum, min(execution.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "hours_on_startup_per_week" and "execution_probability" in by_name:
            execution = by_name["execution_probability"]
            boost = min(0.15, change.value * 0.003)
            value = execution.value + boost
            by_name["execution_probability"] = execution.model_copy(
                update={
                    "value": max(execution.minimum, min(execution.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )
        elif change.metric == "sales_calls_per_week" and "weekly_application_rate" in by_name:
            rate = by_name["weekly_application_rate"]
            delta = min(5.0, change.value * 0.1)
            value = rate.value + delta
            by_name["weekly_application_rate"] = rate.model_copy(
                update={
                    "value": max(rate.minimum, min(rate.maximum, value)),
                    "source": AssumptionSource.EXPLORATION,
                }
            )

    return [by_name[name] for name in (item.name for item in assumptions)]


def changes_to_state_overrides(
    changes: list[InterventionChangeResponse],
) -> dict[str, float | int]:
    """Domain-module override keys for baseline-aware repricing paths."""

    overrides: dict[str, float | int] = {}
    for change in changes:
        if change.metric == "monthly_contribution":
            overrides["monthly_contribution"] = int(change.value)
        elif change.metric == "weekly_running_km":
            overrides["weekly_distance_km"] = float(change.value)
        elif change.metric == "applications_per_week":
            overrides["weekly_application_rate"] = int(change.value)
        elif change.metric == "burn_monthly":
            overrides["burn_monthly"] = float(change.value)
        elif change.metric == "mock_interviews_per_week":
            overrides["mock_interviews_per_week"] = int(change.value)
        elif change.metric == "linkedin_posts_per_week":
            overrides["linkedin_posts_per_week"] = int(change.value)
        elif change.metric == "sleep_hours_per_night":
            overrides["sleep_hours_per_night"] = float(change.value)
        elif change.metric == "running_days_per_week":
            overrides["running_days_per_week"] = int(change.value)
        elif change.metric == "user_conversations_per_week":
            overrides["user_conversations_per_week"] = int(change.value)
        elif change.metric == "hours_on_startup_per_week":
            overrides["hours_on_startup_per_week"] = float(change.value)
        elif change.metric == "sales_calls_per_week":
            overrides["sales_calls_per_week"] = int(change.value)
    return overrides
