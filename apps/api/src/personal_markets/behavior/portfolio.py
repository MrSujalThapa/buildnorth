from __future__ import annotations

from personal_markets.behavior.domain import (
    BehaviorDimension,
    BehaviorProfile,
    DimensionProvenance,
)
from personal_markets.behavior.service import BehaviorService
from personal_markets.collections.progress import measurable_progress
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.goals.domain import GoalContract
from personal_markets.identity.domain import ProfileDimension


def portfolio_profile(
    goals: list[GoalContract],
    evidence_by_goal: dict[str, list[NormalizedEvidence]],
    *,
    dimensions: list[ProfileDimension] | None = None,
) -> BehaviorProfile:
    """User-defined radar over comparable goal evidence; unknown scores stay null."""
    behavior = BehaviorService()
    scores_by_goal: dict[str, float | None] = {}
    n_raw = 0
    n_eff = 0.0
    for goal in goals:
        events = evidence_by_goal.get(str(goal.goal_id), [])
        n_raw += len(events)
        execution = None
        if events:
            estimate = behavior.estimate(events, goal)
            if estimate.usable:
                execution = estimate.probability
                n_eff += estimate.n_eff
        progress = measurable_progress(goal)
        score = execution if execution is not None else progress
        scores_by_goal[str(goal.goal_id)] = score

    categories = dimensions if dimensions else [
        ProfileDimension(label=goal.title[:32], goal_ids=[goal.goal_id]) for goal in goals
    ]
    radar_dimensions: list[BehaviorDimension] = []
    for index, category in enumerate(categories):
        rows = [scores_by_goal[str(goal_id)] for goal_id in category.goal_ids if str(goal_id) in scores_by_goal]
        scores = [score for score in rows if score is not None]
        limited = len(scores) == 0
        value = None if limited else sum(scores) / len(scores)
        radar_dimensions.append(
            BehaviorDimension(
                key=f"dimension-{index}",
                label=category.label,
                value=value,
                display_percent=None if limited or value is None else int(round(value * 100)),
                limited_evidence=limited,
                confidence="insufficient" if limited else "low" if len(scores) < 2 else "medium",
                provenance=DimensionProvenance(
                    comparable_commitments=len(rows),
                    completed=float(len(scores)),
                    recency_weighted_completion=value,
                    sources=["goal_progress", "follow_through"],
                    n_eff=float(len(scores)),
                    formula="Mean of usable follow-through or measurable progress for assigned goals.",
                    details=[
                        f"{len(rows)} assigned goals",
                        f"{len(scores)} with a usable score",
                    ],
                ),
            )
        )

    usable = [item.value for item in radar_dimensions if item.value is not None]
    from datetime import UTC, datetime

    from personal_markets.behavior.domain import ExecutionEstimate

    mean = sum(usable) / len(usable) if usable else 0.0
    return BehaviorProfile(
        estimator_version="portfolio-v1",
        as_of=datetime.now(UTC),
        execution=ExecutionEstimate(
            probability=mean,
            interval=(0.0, 1.0),
            n_eff=n_eff,
            n_raw=n_raw,
            confidence="insufficient" if not usable else "low",
            source="FITTED" if usable else "PRIOR",
            half_life_days=60,
            global_mean=mean,
            domain_mean=mean,
            action_mean=mean,
            usable=bool(usable),
            notes=["Portfolio radar is a category summary, not a personality score."],
        ),
        dimensions=radar_dimensions,
        disclaimer=(
            "This radar summarizes observed follow-through and measurable progress "
            "across your goals. Empty axes mean there is not enough data yet."
        ),
        evidence_sufficiency="insufficient" if not usable else "low",
        n_raw=n_raw,
        n_eff=n_eff,
    )
