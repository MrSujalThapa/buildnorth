from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from personal_markets.core.errors import SemanticProviderError
from personal_markets.goals.domain import (
    ForecastStatus,
    GoalContract,
    GoalType,
    ResourceConstraints,
)
from personal_markets.ports import GoalArchitectProposal


def parse_deadline(value: str) -> datetime:
    text = value.strip()
    if len(text) == 7:
        text = f"{text}-28"
    if len(text) == 10:
        text = f"{text}T23:59:59+00:00"
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def proposal_to_contract(
    proposal: GoalArchitectProposal, goal_id: UUID | None = None
) -> GoalContract:
    hours = (
        proposal.hours_per_week if proposal.hours_per_week and proposal.hours_per_week > 0 else None
    )
    dimensions = [item for item in proposal.state_dimensions if item and item != "unspecified"]
    if not dimensions:
        dimensions = [proposal.success_metric or "unspecified_state"]
    unique: list[str] = []
    for item in dimensions:
        if item not in unique:
            unique.append(item)
    try:
        return GoalContract(
            goal_id=goal_id or uuid4(),
            title=proposal.title,
            goal_type=GoalType(proposal.goal_type),
            success_definition={
                "metric": proposal.success_metric,
                "operator": proposal.success_operator,
                "target": proposal.success_target,
            },
            deadline=parse_deadline(proposal.deadline),
            resource_constraints=ResourceConstraints(hours_per_week=hours),
            state_dimensions=unique,
            model_requirements={"compatibility": proposal.model_family_compatibility},
            forecast_status=ForecastStatus.EXPLORATORY,
        )
    except (ValidationError, ValueError) as error:
        raise SemanticProviderError(str(error)) from error


def validation_errors(proposal: GoalArchitectProposal) -> list[str]:
    if proposal.clarifications_required and not proposal.ready_to_commit:
        return []
    errors: list[str] = []
    if not proposal.ready_to_commit:
        errors.append("Proposal is not ready to commit but no clarifications were provided.")
    if proposal.success_metric in {"", "unspecified"}:
        errors.append("success_metric must be specified.")
    if proposal.success_target in {"", "unspecified"}:
        errors.append("success_target must be specified.")
    if not proposal.state_dimensions:
        errors.append("state_dimensions must not be empty.")
    try:
        proposal_to_contract(proposal)
    except SemanticProviderError as error:
        errors.append(str(error))
    return errors
