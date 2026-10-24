"""Keep explicitly synthetic workspace histories out of authentic behavior estimates."""

from collections.abc import Iterable

from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.goals.domain import GoalContract


def behavior_cohort_goals(
    goals: Iterable[GoalContract], *, synthetic: bool = False
) -> list[GoalContract]:
    """Return only goals from the requested authentic or fixture cohort."""
    return [
        goal for goal in goals if bool(goal.model_requirements.get("workspace_seed")) is synthetic
    ]


def authentic_evidence(rows: Iterable[NormalizedEvidence]) -> list[NormalizedEvidence]:
    """Exclude recognized fixture observations even if linked to an authentic goal."""
    return [
        row
        for row in rows
        if row.source_quality not in {"demo_fixture", "synthetic_demo"}
        and not (row.provenance.event_identity or "").startswith("seed:")
    ]
