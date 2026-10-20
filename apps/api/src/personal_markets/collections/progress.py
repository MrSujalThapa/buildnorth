"""Collection progress is not a joint probability of every member succeeding.

Each goal contributes only when it has a comparable current/target measurement.
Missing or withheld forecasts never invent a value. The optional chart lines are
each goal's published modeled odds, labeled separately from collection progress.
"""

from __future__ import annotations

from personal_markets.collections.domain import CollectionProgress
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.targets import parse_number, resolve_target_number, target_direction

METHODOLOGY = (
    "Equal-weight mean of measurable member progress. Progress uses current/target "
    "from the goal contract when both are numeric. Forecast odds are not averaged "
    "into this figure and are not a probability that every goal completes."
)

_CURRENT_KEYS = ("current", "current_value", "baseline", "start", "current_state")


def _current_value(goal: GoalContract) -> float | None:
    definition = goal.success_definition
    for key in _CURRENT_KEYS:
        if key not in definition:
            continue
        parsed = parse_number(definition[key])
        if parsed is not None:
            return parsed
    known = goal.model_requirements.get("current_state_known")
    if isinstance(known, dict):
        for raw in known.values():
            parsed = parse_number(raw)
            if parsed is not None:
                return parsed
    return None


def measurable_progress(goal: GoalContract) -> float | None:
    target = resolve_target_number(goal)
    current = _current_value(goal)
    if target is None or current is None:
        return None
    direction = target_direction(goal)
    if direction == "at_most":
        if current <= target:
            return 1.0
        start = parse_number(
            goal.success_definition.get("start") or goal.success_definition.get("baseline")
        )
        if start is None or start <= target:
            return None
        return max(0.0, min(1.0, (start - current) / (start - target)))
    if target == 0:
        return 1.0 if current >= 0 else 0.0
    return max(0.0, min(1.0, current / target))


def aggregate_progress(goals: list[GoalContract]) -> CollectionProgress:
    scores: list[float] = []
    notes: list[str] = []
    for goal in goals:
        score = measurable_progress(goal)
        if score is None:
            notes.append(f"{goal.title}: no comparable current/target measurement")
            continue
        scores.append(score)
    if not scores:
        return CollectionProgress(
            value=None,
            available=0,
            total=len(goals),
            incomplete=True,
            methodology=METHODOLOGY,
            notes=notes or ["This collection has no measurable member progress yet."],
        )
    return CollectionProgress(
        value=sum(scores) / len(scores),
        available=len(scores),
        total=len(goals),
        incomplete=len(scores) < len(goals),
        methodology=METHODOLOGY,
        notes=notes,
    )
