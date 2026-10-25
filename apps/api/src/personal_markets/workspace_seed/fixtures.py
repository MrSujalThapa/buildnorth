"""Seeded hackathon workspace: goal proposals, observation timelines, commitments.

The proposals are the structured output the Goal Architect would emit; the seed runs
them through the same deterministic refinement and contract compiler. Observations
are self-reported fixture values (source_type `manual`), never provider events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SEED_VERSION = "hackathon_workspace_v1"

OutcomeStatus = Literal["completed", "partial", "missed"]


@dataclass(frozen=True, slots=True)
class SeedObservation:
    days_ago: float
    metric: str
    value: float | None
    unit: str
    summary: str
    kind: Literal["snapshot", "increment", "period", "event"] = "snapshot"
    event_type: str = "observation"
    domain: str = "user_state"
    category: str | None = None


@dataclass(frozen=True, slots=True)
class SeedCommitment:
    days_ago: float
    window_days: float
    action: str
    planned: float
    unit: str
    status: OutcomeStatus
    actual: float | None
    resolved_late_days: float = 0.0


@dataclass(frozen=True, slots=True)
class SeedGoal:
    key: str
    proposal: dict[str, object]
    deadline_days: int
    domain: str
    observations: tuple[SeedObservation, ...]
    commitments: tuple[SeedCommitment, ...] = field(default_factory=tuple)


def _weekly(
    start_days_ago: int,
    count: int,
    action: str,
    planned: float,
    unit: str,
    outcomes: str,
    *,
    actual_scale: tuple[float, ...] | None = None,
    late: str = "",
) -> tuple[SeedCommitment, ...]:
    """Weekly commitments. `outcomes` uses c=completed, p=partial, m=missed per week."""
    rows = []
    for index in range(count):
        status_code = outcomes[index % len(outcomes)]
        status: OutcomeStatus = (
            "completed" if status_code == "c" else "partial" if status_code == "p" else "missed"
        )
        scale = actual_scale[index % len(actual_scale)] if actual_scale else 1.0
        if status == "completed":
            actual: float | None = round(planned * max(1.0, scale), 2)
        elif status == "partial":
            actual = round(planned * min(0.9, max(0.2, scale)), 2)
        else:
            actual = None
        late_days = float(late[index % len(late)]) if late else 0.0
        rows.append(
            SeedCommitment(
                days_ago=start_days_ago - 7 * index,
                window_days=7,
                action=action,
                planned=planned,
                unit=unit,
                status=status,
                actual=actual,
                resolved_late_days=late_days,
            )
        )
    return tuple(rows)


def _counts(
    metric: str, unit: str, label: str, points: list[tuple[float, float]], **extra: object
) -> tuple[SeedObservation, ...]:
    return tuple(
        SeedObservation(
            days_ago=days,
            metric=metric,
            value=value,
            unit=unit,
            summary=f"{label}: {value:g}",
            **extra,  # type: ignore[arg-type]
        )
        for days, value in points
    )


FDE_OFFER = SeedGoal(
    key="fde_offer",
    domain="career",
    deadline_days=160,
    proposal={
        "ready_to_commit": True,
        "title": "Land a forward-deployed engineer offer",
        "goal_type": "deadline_event",
        "success_metric": "offer_received",
        "success_operator": "==",
        "success_target": "signed_offer",
        "state_dimensions": ["applications_submitted", "technical_interview"],
        "hours_per_week": 12,
        "model_family_compatibility": "deadline_event_hazard",
        "success_unit": "event",
    },
    observations=(
        *_counts(
            "applications_submitted",
            "applications",
            "Applications submitted",
            [(104, 5), (90, 11), (76, 18), (62, 24), (48, 27), (34, 33), (20, 38), (6, 44)],
        ),
        SeedObservation(83, "recruiter_responses", 2, "responses", "Recruiter replies: 2"),
        SeedObservation(55, "recruiter_responses", 5, "responses", "Recruiter replies: 5"),
        SeedObservation(27, "recruiter_responses", 7, "responses", "Recruiter replies: 7"),
        SeedObservation(69, "phone_screens", 2, "screens", "Phone screens completed: 2"),
        SeedObservation(41, "phone_screens", 4, "screens", "Phone screens completed: 4"),
        SeedObservation(
            58,
            "rejections",
            1,
            "rejections",
            "Rejected after phone screen",
            kind="event",
            event_type="rejection",
        ),
        SeedObservation(37, "technical_interviews", 2, "interviews", "Technical interviews: 2"),
        SeedObservation(13, "technical_interviews", 3, "interviews", "Technical interviews: 3"),
        SeedObservation(
            24,
            "rejections",
            1,
            "rejections",
            "Rejected after technical round",
            kind="event",
            event_type="rejection",
        ),
        SeedObservation(4, "final_round_interviews", 1, "interviews", "Final round scheduled: 1"),
        SeedObservation(
            3,
            "applications_submitted",
            8,
            "applications",
            "Submitted 8 applications this week",
            kind="event",
        ),
        SeedObservation(
            2,
            "study_hours",
            4,
            "hours",
            "Interview preparation: 4 hours",
            kind="increment",
        ),
    ),
    commitments=_weekly(
        98,
        14,
        "Send targeted applications",
        5,
        "applications",
        "ccpcmcccpcccmc",
        actual_scale=(1.0, 1.2, 0.6, 1.0, 1.0, 1.4, 1.0),
        late="00010000200000",
    )
    + _weekly(
        95,
        13,
        "Solve interview practice problems",
        8,
        "problems",
        "cpccmpccccpcc",
        actual_scale=(1.0, 0.5, 1.0, 1.1, 1.0, 0.6),
    ),
)

STARTUP_RAISE = SeedGoal(
    key="startup_raise",
    domain="startup",
    deadline_days=200,
    proposal={
        "ready_to_commit": True,
        "title": "Raise a $750k pre-seed round for my startup",
        "goal_type": "deadline_event",
        "success_metric": "seed_round_closed",
        "success_operator": "==",
        "success_target": "closed_round",
        "state_dimensions": ["mrr", "runway_months", "fundraising_conversation"],
        "hours_per_week": 25,
        "model_family_compatibility": "deadline_event_hazard",
        "success_unit": "event",
    },
    observations=(
        *_counts(
            "mrr",
            "USD/month",
            "Monthly recurring revenue",
            [(100, 1800), (72, 3100), (44, 4200), (16, 6900)],
        ),
        *_counts(
            "runway_months",
            "months",
            "Runway",
            [(100, 7.5), (65, 4.5), (38, 2.5), (9, 5.0)],
        ),
        SeedObservation(
            86,
            "fundraising_conversation",
            None,
            "event",
            "First fundraising conversation with an angel",
            kind="event",
            event_type="fundraising",
            category="held",
        ),
        SeedObservation(
            51,
            "fundraising_conversation",
            None,
            "event",
            "Fundraising partner meeting at a pre-seed fund",
            kind="event",
            event_type="fundraising",
            category="held",
        ),
        SeedObservation(
            12,
            "term_sheet",
            None,
            "event",
            "Term sheet received from lead investor",
            kind="event",
            event_type="term_sheet",
            category="received",
        ),
    ),
    commitments=_weekly(
        96,
        13,
        "Run investor outreach",
        6,
        "investor emails",
        "cmcpccmpcccpc",
        actual_scale=(1.0, 1.0, 0.5, 1.3, 1.0),
        late="0102000100000",
    ),
)

NET_WORTH = SeedGoal(
    key="net_worth",
    domain="finance",
    deadline_days=820,
    proposal={
        "ready_to_commit": True,
        "title": "Reach $100,000 net worth",
        "goal_type": "continuous_target",
        "success_metric": "net_worth",
        "success_operator": ">=",
        "success_target": "100000",
        "state_dimensions": ["net_worth", "monthly_contribution"],
        "model_family_compatibility": "continuous_target_transition",
        "success_unit": "USD",
    },
    observations=(
        *_counts(
            "net_worth",
            "USD",
            "Net worth",
            [(105, 41200), (75, 43900), (45, 42100), (15, 47800)],
        ),
        *_counts(
            "monthly_contribution",
            "USD/month",
            "Monthly contribution",
            [(105, 1200), (60, 900), (15, 1650)],
            kind="period",
        ),
    ),
    commitments=_weekly(
        91,
        13,
        "Keep weekly spending under budget",
        350,
        "USD",
        "ccmccpcccmccc",
        actual_scale=(1.0, 1.0, 0.7, 1.0),
    ),
)

RUN_10K = SeedGoal(
    key="run_10k",
    domain="running",
    deadline_days=130,
    proposal={
        "ready_to_commit": True,
        "title": "Run a 10K in under 45 minutes",
        "goal_type": "threshold",
        "success_metric": "10k_time_seconds",
        "success_operator": "<=",
        "success_target": "2700",
        "state_dimensions": ["10k_time_seconds", "weekly_distance_km"],
        "model_family_compatibility": "threshold_trend",
        "success_unit": "seconds",
    },
    observations=(
        *_counts(
            "10k_time_seconds",
            "seconds",
            "10K time trial (seconds)",
            [(98, 3060), (77, 2985), (56, 3010), (35, 2890), (14, 2835)],
            kind="event",
            event_type="workout",
            domain="running",
        ),
        *_counts(
            "weekly_distance_km",
            "km/week",
            "Weekly distance",
            [(91, 18), (70, 24), (49, 15), (28, 30), (7, 34)],
            kind="period",
            domain="running",
        ),
    ),
    commitments=_weekly(
        97,
        14,
        "Complete planned runs",
        4,
        "runs",
        "cpcmmccpcccpcc",
        actual_scale=(1.0, 0.5, 1.0, 1.0, 0.75),
        late="00000100000000",
    ),
)

READING = SeedGoal(
    key="reading",
    domain="reading",
    deadline_days=240,
    proposal={
        "ready_to_commit": True,
        "title": "Read 24 books by next summer",
        "goal_type": "threshold",
        "success_metric": "books_read",
        "success_operator": ">=",
        "success_target": "24",
        "state_dimensions": ["books_read"],
        "model_family_compatibility": "composed_cumulative_count",
        "success_unit": "books",
        "primitive_kind": "cumulative_count",
    },
    observations=(
        *_counts(
            "books_read",
            "books",
            "Books finished",
            [(110, 2), (88, 3), (70, 5), (52, 5), (38, 6), (21, 8), (5, 9)],
        ),
        SeedObservation(
            2,
            "reading_minutes",
            90,
            "minutes",
            "Read for 90 minutes",
            kind="increment",
        ),
        SeedObservation(
            5,
            "reading_minutes",
            45,
            "minutes",
            "Read for 45 minutes",
            kind="increment",
        ),
    ),
    commitments=_weekly(
        99,
        14,
        "Read for 30 minutes on five evenings",
        5,
        "sessions",
        "ccpcmmpcccpccc",
        actual_scale=(1.0, 1.0, 0.6, 1.2, 1.0, 0.4),
    ),
)

PROJECT = SeedGoal(
    key="project",
    domain="project",
    deadline_days=150,
    proposal={
        "ready_to_commit": True,
        "title": "Ship 30 features of my distributed key-value store",
        "goal_type": "threshold",
        "success_metric": "features_shipped",
        "success_operator": ">=",
        "success_target": "30",
        "state_dimensions": ["features_shipped"],
        "model_family_compatibility": "composed_cumulative_count",
        "success_unit": "features",
        "primitive_kind": "cumulative_count",
    },
    observations=(
        *_counts(
            "features_shipped",
            "features",
            "Project features shipped",
            [(102, 3), (84, 6), (66, 7), (48, 11), (30, 12), (12, 17)],
        ),
        *_counts(
            "focus_ratio",
            "share",
            "On-task share of a scheduled deep-work block",
            [
                (96, 0.58),
                (89, 0.62),
                (82, 0.49),
                (75, 0.66),
                (61, 0.71),
                (54, 0.55),
                (40, 0.74),
                (33, 0.78),
                (19, 0.69),
                (12, 0.81),
                (5, 0.77),
            ],
            kind="event",
            event_type="focus_session",
            domain="project",
        ),
        SeedObservation(
            30,
            "available_hours_per_week",
            22,
            "hours/week",
            "Free hours this week",
            domain="project",
        ),
        SeedObservation(
            30,
            "committed_hours_per_week",
            26,
            "hours/week",
            "Hours committed across goals this week",
            domain="project",
        ),
    ),
    commitments=_weekly(
        94,
        13,
        "Ship two project features",
        2,
        "features",
        "pcmcpcccpmccc",
        actual_scale=(0.5, 1.0, 1.0, 1.5, 0.5, 1.0),
        late="0300100020000",
    ),
)

FAMILY_DINNERS = SeedGoal(
    key="family_dinners",
    domain="relationships",
    deadline_days=180,
    proposal={
        "ready_to_commit": True,
        "title": "Host 20 dinners with family or friends",
        "goal_type": "threshold",
        "success_metric": "dinners_hosted",
        "success_operator": ">=",
        "success_target": "20",
        "state_dimensions": ["dinners_hosted"],
        "model_family_compatibility": "composed_cumulative_count",
        "success_unit": "dinners",
        "primitive_kind": "cumulative_count",
    },
    observations=_counts(
        "dinners_hosted",
        "dinners",
        "Dinners hosted",
        [(100, 1), (79, 2), (58, 4), (37, 5), (16, 7)],
    ),
    commitments=_weekly(
        93,
        13,
        "Call or see family",
        2,
        "calls",
        "ccccpcccccmcc",
        actual_scale=(1.0, 1.0, 0.5, 1.0),
    ),
)

ML_COURSE = SeedGoal(
    key="ml_course",
    domain="education",
    deadline_days=150,
    proposal={
        "ready_to_commit": True,
        "title": "Complete 40 lessons of a machine learning course",
        "goal_type": "threshold",
        "success_metric": "lessons_completed",
        "success_operator": ">=",
        "success_target": "40",
        "state_dimensions": ["lessons_completed"],
        "model_family_compatibility": "composed_cumulative_count",
        "success_unit": "lessons",
        "primitive_kind": "cumulative_count",
    },
    observations=_counts(
        "lessons_completed",
        "lessons",
        "Lessons completed",
        [(84, 3), (70, 6), (56, 9), (42, 11), (28, 15), (14, 17), (3, 20)],
    ),
    commitments=_weekly(
        83,
        11,
        "Finish two lessons",
        2,
        "lessons",
        "ccpcmcccpcc",
        actual_scale=(1.0, 1.0, 0.5, 1.0),
    ),
)

MEDITATION = SeedGoal(
    key="meditation",
    domain="personal",
    deadline_days=120,
    proposal={
        "ready_to_commit": True,
        "title": "Log 100 meditation sessions",
        "goal_type": "threshold",
        "success_metric": "meditation_sessions",
        "success_operator": ">=",
        "success_target": "100",
        "state_dimensions": ["meditation_sessions"],
        "model_family_compatibility": "composed_cumulative_count",
        "success_unit": "sessions",
        "primitive_kind": "cumulative_count",
    },
    observations=_counts(
        "meditation_sessions",
        "sessions",
        "Meditation sessions logged",
        [(63, 4), (49, 11), (35, 15), (21, 22), (7, 29), (1, 31)],
    ),
    commitments=_weekly(
        62,
        8,
        "Meditate on five mornings",
        5,
        "sessions",
        "cpcmcpcc",
        actual_scale=(1.0, 0.6, 1.0, 1.0),
    ),
)

SEED_GOALS: tuple[SeedGoal, ...] = (
    FDE_OFFER,
    STARTUP_RAISE,
    NET_WORTH,
    RUN_10K,
    READING,
    PROJECT,
    FAMILY_DINNERS,
)

# Published only by dedicated marketplace demo accounts, never the user's own workspace.
MARKETPLACE_ONLY_GOALS: tuple[SeedGoal, ...] = (ML_COURSE, MEDITATION)


@dataclass(frozen=True, slots=True)
class SeedCollection:
    name: str
    description: str
    goal_keys: tuple[str, ...]


SEED_COLLECTIONS: tuple[SeedCollection, ...] = (
    SeedCollection(
        name="Career & company",
        description="Offer search, fundraising and the systems project.",
        goal_keys=("fde_offer", "startup_raise", "project"),
    ),
    SeedCollection(
        name="Health & personal",
        description="Running, reading, money and the people who matter.",
        goal_keys=("run_10k", "reading", "net_worth", "family_dinners"),
    ),
)
