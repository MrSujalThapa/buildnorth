from __future__ import annotations

from collections import defaultdict

from personal_markets.behavior.domain import (
    BehaviorDimension,
    BehaviorProfile,
    DimensionProvenance,
)
from personal_markets.behavior.service import BehaviorService
from personal_markets.collections.progress import measurable_progress
from personal_markets.evidence.domain import NormalizedEvidence
from personal_markets.goals.domain import GoalContract

CATEGORY_ORDER = (
    ("career", "Career"),
    ("learning", "Learning"),
    ("health", "Health / Fitness"),
    ("personal", "Personal"),
    ("projects", "Projects / Startups"),
)

_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("career", ("job", "career", "interview", "offer", "promotion", "employment")),
    ("learning", ("school", "university", "course", "read", "book", "degree", "learn")),
    ("health", ("run", "fitness", "health", "weight", "marathon", "sleep", "workout")),
    ("projects", ("startup", "company", "revenue", "founder", "mrr", "hackathon", "ship")),
]


def categorize(goal: GoalContract) -> str:
    blob = f"{goal.title} {goal.goal_type} {' '.join(goal.state_dimensions)}".lower()
    for key, tokens in _PATTERNS:
        if any(token in blob for token in tokens):
            return key
    return "personal"


def portfolio_profile(
    goals: list[GoalContract],
    evidence_by_goal: dict[str, list[NormalizedEvidence]],
) -> BehaviorProfile:
    """Cross-goal radar. Missing categories stay limited rather than fabricated."""
    behavior = BehaviorService()
    grouped: dict[str, list[tuple[GoalContract, float | None]]] = defaultdict(list)
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
        grouped[categorize(goal)].append((goal, score))

    dimensions: list[BehaviorDimension] = []
    for key, label in CATEGORY_ORDER:
        rows = grouped.get(key, [])
        scores = [score for _, score in rows if score is not None]
        limited = len(scores) == 0
        value = None if limited else sum(scores) / len(scores)
        dimensions.append(
            BehaviorDimension(
                key=key,  # type: ignore[arg-type]
                label=label,
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
                    formula=(
                        f"{label}: mean of usable follow-through or measurable progress "
                        "across goals in this category. Null when neither is available."
                    ),
                    details=[
                        f"{len(rows)} goals in {label}",
                        f"{len(scores)} with a usable score",
                    ],
                ),
            )
        )

    usable = [item.value for item in dimensions if item.value is not None]
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
        dimensions=dimensions,
        disclaimer=(
            "This radar summarizes observed follow-through and measurable progress "
            "across your goals. Empty axes mean there is not enough data yet."
        ),
        evidence_sufficiency="insufficient" if not usable else "low",
        n_raw=n_raw,
        n_eff=n_eff,
    )
