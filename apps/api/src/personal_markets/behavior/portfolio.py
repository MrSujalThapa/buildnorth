from __future__ import annotations

from datetime import UTC, datetime

from personal_markets.behavior.dimensions import build_profile
from personal_markets.behavior.domain import ActionContext, BehaviorProfile
from personal_markets.behavior.features import trials_from_evidence
from personal_markets.behavior.model import estimate_execution
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.goals.domain import GoalContract
from personal_markets.identity.domain import ProfileDimension


def portfolio_profile(
    goals: list[GoalContract],
    evidence_by_goal: dict[str, list[NormalizedEvidence]],
    *,
    dimensions: list[ProfileDimension] | None = None,
    as_of: datetime | None = None,
) -> BehaviorProfile:
    """Overall execution traits from paired commitments, never goal progress.

    Saved profile dimensions represent optional interest-area filters. They do not
    define radar axes, which always describe behavior. The caller may pass a
    subset of goals to build one such filtered profile.
    """
    _ = dimensions  # Retained at the API boundary for existing saved profiles.
    stamp = as_of or datetime.now(UTC)
    trials = []
    for goal in goals:
        for trial in trials_from_evidence(evidence_by_goal.get(str(goal.goal_id), [])):
            trials.append(trial.model_copy(update={"trial_id": f"{goal.goal_id}:{trial.trial_id}"}))
    context = ActionContext(action_type="overall", domain="overall")
    execution = estimate_execution(trials, context, as_of=stamp)
    profile = build_profile(trials, context, execution, as_of=stamp)
    return profile.model_copy(update={
        "dimensions": [
            item for item in profile.dimensions
            if item.key in {
                "follow_through", "consistency", "commitment_realism",
                "momentum", "reliability", "recovery",
            }
        ],
        "disclaimer": (
            "Execution traits use observed planned-versus-completed actions. "
            "Goal progress and forecast odds are separate."
        ),
    })
