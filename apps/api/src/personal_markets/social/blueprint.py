from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from personal_markets.core.errors import ConflictError
from personal_markets.goals.domain import GoalContract, GoalType, ResourceConstraints
from personal_markets.social.domain import PublicBlueprint, PublicForecastState, PublicHistoryPoint
from personal_markets.social.playbook import normalize_steps, suggest_playbook

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
        "value",
        "amount",
        "description",
        "milestones",
        "strategy",
        "strategies",
        "strategies_source",
        "milestones_source",
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


TARGET_KEYS = ("target", "target_value", "threshold", "value", "amount", "seconds")
CURRENCY_UNITS = frozenset({"$", "usd", "cad", "dollars", "dollar"})
OPERATOR_VERBS = {
    ">=": "Reach",
    "gte": "Reach",
    "at_least": "Reach",
    ">": "Exceed",
    "gt": "Exceed",
    "<=": "Stay at or under",
    "lte": "Stay at or under",
    "at_most": "Stay at or under",
    "<": "Get under",
    "lt": "Get under",
    "==": "Hit",
    "=": "Hit",
    "eq": "Hit",
}
FORECAST_SPEC_PRIVATE_KEYS = frozenset(
    {
        "goal_id",
        "owner_id",
        "goal_contract_version",
        "parameter_provenance",
        "status",
    }
)
FORECAST_SPEC_EVIDENCE_PARTS = ("evidence", "observation", "observed", "current_value")
BLUEPRINT_SCHEMA_VERSION = 2
MAX_TRACKED_METRICS = 12
MAX_METRIC_NAME_LENGTH = 60


def tracked_metric_names(success: dict[str, Any], state_dimensions: list[Any]) -> list[str]:
    """Metric names the goal definition tracks: success metric first, then dimensions."""
    names: list[str] = []
    for item in [success.get("metric"), *state_dimensions]:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if not name or len(name) > MAX_METRIC_NAME_LENGTH or name in names:
            continue
        if any(part in name.lower() for part in SENSITIVE_KEY_PARTS):
            continue
        names.append(name)
    return names[:MAX_TRACKED_METRICS]


def forecast_units(model_requirements: dict[str, Any]) -> str | None:
    spec = model_requirements.get("forecast_spec")
    if not isinstance(spec, dict):
        return None
    units = spec.get("units")
    if not isinstance(units, str):
        return None
    return units.strip()[:60] or None


def _format_number(value: Any) -> str:
    try:
        number = float(str(value).replace(",", ""))
    except ValueError:
        return str(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_deadline(deadline: datetime) -> str:
    return f"{deadline:%b} {deadline.day}, {deadline.year}"


def success_summary(success: dict[str, Any], deadline: datetime | None) -> str:
    """Deterministic, public-safe sentence describing the success contract."""
    by = f" by {_format_deadline(deadline)}" if deadline else ""
    metric = success.get("metric")
    target = next((success[key] for key in TARGET_KEYS if success.get(key) is not None), None)
    if isinstance(metric, str) and metric.strip() and target is not None:
        words = metric.replace("_", " ").strip()
        unit = str(success.get("unit") or "").strip()
        amount = _format_number(target)
        if unit.lower() in CURRENCY_UNITS:
            phrase = f"${amount} in {words}"
        elif unit and unit.lower() in words.lower():
            phrase = f"{amount} {words}"
        elif unit:
            phrase = f"{amount} {unit} of {words}"
        else:
            phrase = f"{amount} {words}"
        verb = OPERATOR_VERBS.get(str(success.get("operator") or "").strip().lower(), "Reach")
        return f"{verb} {phrase}{by}"
    event = success.get("event") or success.get("success_event")
    if isinstance(event, str) and event.strip():
        return f"Achieve {event.replace('_', ' ').strip()}{by}"
    return ""


def enriched_success_definition(
    success_definition: dict[str, Any], model_requirements: dict[str, Any]
) -> dict[str, Any]:
    success = public_success_definition(success_definition)
    units = forecast_units(model_requirements)
    if units and not success.get("unit"):
        success["unit"] = units
    return success


def _strip_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_evidence(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in FORECAST_SPEC_EVIDENCE_PARTS)
        }
    if isinstance(value, list):
        return [_strip_evidence(item) for item in value]
    return value


def public_forecast_spec(model_requirements: dict[str, Any]) -> dict[str, Any] | None:
    """Model specification without owner identity, lineage, or observed evidence."""
    spec = model_requirements.get("forecast_spec")
    if not isinstance(spec, dict) or not spec:
        return None
    cleaned = {key: value for key, value in spec.items() if key not in FORECAST_SPEC_PRIVATE_KEYS}
    public = _public_value(_strip_evidence(cleaned))
    return public if isinstance(public, dict) else None


def _blueprint_from_parts(
    *,
    title: str,
    goal_type: str,
    success_definition: dict[str, Any],
    deadline: datetime | None,
    model_requirements: dict[str, Any],
    description: str = "",
    state_dimensions: list[Any] | None = None,
    goal_contract_version: int | None = None,
    snapshot_at: datetime | None = None,
) -> PublicBlueprint:
    success = enriched_success_definition(success_definition, model_requirements)
    requirements = public_model_configuration(model_requirements)
    creator_milestones = normalize_steps(
        success.get("milestones") or requirements.get("milestones") or []
    )
    evidence_types = (
        requirements.get("suggested_evidence") or requirements.get("evidence_types") or []
    )
    if not isinstance(evidence_types, list):
        evidence_types = []
    integrations = requirements.get("suggested_integrations") or []
    if not isinstance(integrations, list):
        integrations = []
    creator_strategies = normalize_steps(
        success.get("strategies")
        or requirements.get("strategies")
        or success.get("strategy")
        or requirements.get("strategy")
    )
    suggested_steps, suggested_milestones, suggested_evidence = suggest_playbook(
        title=title,
        success=success,
        category=str(model_requirements.get("life_area") or goal_type),
        goal_type=goal_type,
    )
    strategies = creator_strategies or suggested_steps
    milestones = creator_milestones or suggested_milestones
    if not evidence_types:
        evidence_types = suggested_evidence
    text = (
        description
        or str(success_definition.get("description") or "")
        or success_summary(success, deadline)
    )
    return PublicBlueprint(
        title=title,
        description=text[:2000],
        category=str(model_requirements.get("life_area") or goal_type),
        deadline=deadline,
        success_criteria=success,
        milestones=milestones,
        strategies=strategies,
        strategies_source="creator" if creator_strategies else "suggested",
        milestones_source="creator" if creator_milestones else "suggested",
        evidence_types=[str(item) for item in evidence_types],
        suggested_integrations=[str(item) for item in integrations],
        model_configuration=requirements,
        forecast=forecast_state_from_requirements(model_requirements),
        blueprint_version=BLUEPRINT_SCHEMA_VERSION,
        snapshot_at=snapshot_at,
        goal_contract_version=goal_contract_version,
        tracked_metrics=tracked_metric_names(success, state_dimensions or []),
    )


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def blueprint_from_row(row: dict[str, Any]) -> PublicBlueprint:
    """Live blueprint from goal columns; used for owner views and gap filling."""
    deadline = row.get("deadline")
    version = row.get("version")
    return _blueprint_from_parts(
        title=str(row["title"]),
        goal_type=str(row["goal_type"]),
        success_definition=_json_dict(row.get("success_definition_json")),
        deadline=deadline if isinstance(deadline, datetime) else None,
        model_requirements=_json_dict(row.get("model_requirements_json")),
        state_dimensions=_json_list(row.get("state_dimensions_json")),
        goal_contract_version=version if isinstance(version, int) else None,
    )


def reviewed_blueprint(row: dict[str, Any], *, live: bool) -> PublicBlueprint:
    """Owner (`live`) sees the current goal; visitors see the reviewed snapshot.

    Gaps in an older snapshot are filled from public-safe goal columns, and the
    forecast state always reflects the latest publication decision.
    """
    current = blueprint_from_row(row)
    if live:
        return current
    stored = _json_dict(row.get("public_blueprint_json"))
    if not stored:
        return current
    snapshot = PublicBlueprint.model_validate(stored)
    updates: dict[str, Any] = {"forecast": current.forecast}
    if not snapshot.success_criteria:
        updates["success_criteria"] = current.success_criteria
    elif not snapshot.success_criteria.get("unit") and current.success_criteria.get("unit"):
        updates["success_criteria"] = {
            **snapshot.success_criteria,
            "unit": current.success_criteria["unit"],
        }
    if snapshot.deadline is None:
        updates["deadline"] = current.deadline
    if not snapshot.description:
        criteria = updates.get("success_criteria", snapshot.success_criteria)
        deadline = updates.get("deadline", snapshot.deadline)
        updates["description"] = success_summary(criteria, deadline) or current.description
    stored_steps = normalize_steps(snapshot.strategies)
    if stored_steps != snapshot.strategies or not stored_steps:
        updates["strategies"] = stored_steps or current.strategies
        updates["strategies_source"] = (
            snapshot.strategies_source if stored_steps else current.strategies_source
        )
    stored_milestones = normalize_steps(snapshot.milestones)
    if stored_milestones != list(snapshot.milestones) or not stored_milestones:
        updates["milestones"] = stored_milestones or current.milestones
        updates["milestones_source"] = (
            snapshot.milestones_source if stored_milestones else current.milestones_source
        )
    if not snapshot.evidence_types and current.evidence_types:
        updates["evidence_types"] = current.evidence_types
    if not snapshot.tracked_metrics and current.tracked_metrics:
        updates["tracked_metrics"] = current.tracked_metrics
    return snapshot.model_copy(update=updates)


def build_public_blueprint(
    goal: GoalContract, description: str = "", *, snapshot_at: datetime | None = None
) -> PublicBlueprint:
    return _blueprint_from_parts(
        title=goal.title,
        goal_type=goal.goal_type.value,
        success_definition=goal.success_definition,
        deadline=goal.deadline,
        model_requirements=goal.model_requirements,
        description=description,
        state_dimensions=list(goal.state_dimensions),
        goal_contract_version=goal.version,
        snapshot_at=snapshot_at,
    )


def history_points(rows: list[dict[str, Any]]) -> list[PublicHistoryPoint]:
    points: list[PublicHistoryPoint] = []
    for row in rows:
        if str(row.get("source_kind") or "published_forecast") != "published_forecast":
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
    success = public_success_definition(source.success_definition)
    if not success:
        raise ConflictError("This blueprint has no public success criteria to fork")
    requirements = public_model_configuration(source.model_requirements)
    life_area = source.model_requirements.get("life_area")
    if isinstance(life_area, str) and life_area.strip():
        requirements["life_area"] = life_area.strip()[:80]
    spec = public_forecast_spec(source.model_requirements)
    if spec is not None:
        requirements["forecast_spec"] = {
            **spec,
            "goal_id": str(new_goal_id),
            "goal_contract_version": 1,
            "deadline": chosen_deadline.isoformat(),
        }
    return GoalContract(
        goal_id=new_goal_id,
        title=title[:200],
        goal_type=GoalType(source.goal_type),
        success_definition=success,
        deadline=chosen_deadline,
        target_probability=None,
        resource_constraints=ResourceConstraints(),
        state_dimensions=list(source.state_dimensions),
        model_requirements=requirements,
        forecast_status=source.forecast_status.__class__("EXPLORATORY"),
        version=1,
    )
