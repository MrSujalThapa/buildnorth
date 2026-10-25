from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.social.domain import PublicBlueprint, PublicForecastState, PublicHistoryPoint

PUBLIC_SUCCESS_KEYS = frozenset(
    {
        "metric",
        "operator",
        "seconds",
        "event",
        "success_event",
        "threshold",
        "unit",
        "target",
        "description",
        "milestones",
        "strategy",
        "criteria",
        "target_value",
        "direction",
        "window",
        "habit",
    }
)
PUBLIC_REQUIREMENT_KEYS = frozenset(
    {
        "family",
        "model_family",
        "suggested_evidence",
        "evidence_types",
        "suggested_integrations",
        "strategy",
        "milestones",
    }
)
SENSITIVE_KEY_PARTS = (
    "email",
    "token",
    "secret",
    "password",
    "instruction",
    "clerk",
    "raw_payload",
    "credential",
    "account",
    "upload",
)


def _public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public_value(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_public_value(item) for item in value[:40]]
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:500]


def public_success_definition(source: dict[str, Any]) -> dict[str, Any]:
    return {key: _public_value(source[key]) for key in PUBLIC_SUCCESS_KEYS if key in source}


def public_model_configuration(source: dict[str, Any]) -> dict[str, Any]:
    return {key: _public_value(source[key]) for key in PUBLIC_REQUIREMENT_KEYS if key in source}


def forecast_state_from_requirements(requirements: dict[str, Any]) -> PublicForecastState:
    publication = requirements.get("last_publication")
    if not isinstance(publication, dict):
        return PublicForecastState(status="unpublished")
    status = str(publication.get("status") or "unpublished")
    if status == "withheld":
        return PublicForecastState(
            status="withheld",
            category=str(publication.get("category") or "") or None,
        )
    if status in {"completed", "limited", "publish", "publish_with_limitations"}:
        return PublicForecastState(status="published")
    return PublicForecastState(status="unpublished")


def build_public_blueprint(goal: GoalContract, description: str = "") -> PublicBlueprint:
    success = public_success_definition(goal.success_definition)
    requirements = public_model_configuration(goal.model_requirements)
    milestones = success.get("milestones") or requirements.get("milestones") or []
    if not isinstance(milestones, list):
        milestones = []
    evidence_types = (
        requirements.get("suggested_evidence") or requirements.get("evidence_types") or []
    )
    if not isinstance(evidence_types, list):
        evidence_types = []
    integrations = requirements.get("suggested_integrations") or []
    if not isinstance(integrations, list):
        integrations = []
    strategy = success.get("strategy") or requirements.get("strategy")
    return PublicBlueprint(
        title=goal.title,
        description=description or str(goal.success_definition.get("description") or ""),
        category=goal.goal_type.value,
        success_criteria=success,
        milestones=[item for item in milestones if isinstance(item, (str, dict))],
        strategies=[str(strategy)] if strategy else [],
        evidence_types=[str(item) for item in evidence_types],
        suggested_integrations=[str(item) for item in integrations],
        model_configuration=requirements,
        forecast=forecast_state_from_requirements(goal.model_requirements),
    )


def history_points(rows: list[dict[str, Any]]) -> list[PublicHistoryPoint]:
    points: list[PublicHistoryPoint] = []
    for row in rows:
        if str(row.get("source_kind") or "published_forecast") == "synthetic_demo":
            continue
        probability = row.get("probability")
        created = row.get("created_at")
        if probability is None or created is None:
            continue
        points.append(PublicHistoryPoint(created_at=created, probability=float(probability)))
    return points


def fork_goal(
    source: GoalContract,
    *,
    owner_title: str | None,
    deadline: datetime | None,
    new_goal_id: UUID,
) -> GoalContract:
    title = (owner_title or source.title).strip() or source.title
    chosen_deadline = deadline or source.deadline
    if chosen_deadline.tzinfo is None:
        chosen_deadline = chosen_deadline.replace(tzinfo=UTC)
    if chosen_deadline <= datetime.now(UTC):
        chosen_deadline = datetime.now(UTC) + timedelta(days=90)
    success = public_success_definition(source.success_definition) or dict(
        source.success_definition
    )
    requirements = public_model_configuration(source.model_requirements)
    return GoalContract(
        goal_id=new_goal_id,
        title=title[:200],
        goal_type=GoalType(source.goal_type),
        success_definition=success,
        deadline=chosen_deadline,
        target_probability=None,
        resource_constraints=source.resource_constraints,
        state_dimensions=list(source.state_dimensions),
        model_requirements=requirements,
        forecast_status=source.forecast_status.__class__("EXPLORATORY"),
        version=1,
    )
