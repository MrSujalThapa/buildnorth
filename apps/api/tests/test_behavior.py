from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.behavior.domain import ActionContext, CommitmentTrial
from personal_markets.behavior.features import collapse_correlated_events, trials_from_evidence
from personal_markets.behavior.model import estimate_execution
from personal_markets.behavior.service import BehaviorService
from personal_markets.evidence.domain import NormalizedEvidence, Provenance
from personal_markets.forecasting.families import AssumptionSource
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.integrations.resource_ranker import rank_resources
from personal_markets.what_if.domain import (
    Assumption,
    ResourceCost,
    StructuredIntervention,
    WhatIfRequest,
)
from personal_markets.what_if.optimizer import ActionOptimizer, ResourceLimits
from personal_markets.what_if.service import WhatIfService


def _trial(
    *,
    outcome: float,
    days_ago: int,
    action: str = "coding",
    domain: str = "career",
    session: str | None = None,
    planned: float = 2.0,
) -> CommitmentTrial:
    stamp = datetime.now(UTC) - timedelta(days=days_ago)
    return CommitmentTrial(
        trial_id=f"{action}-{days_ago}-{outcome}",
        domain=domain,
        action_type=action,
        planned_amount=planned,
        realized_amount=planned * outcome,
        outcome=outcome,
        observed_at=stamp,
        session_key=session or f"{stamp.date()}|{action}|manual",
        tokens=[action, domain],
    )


def test_session_collapse_does_not_count_burst_as_independent() -> None:
    stamp = datetime.now(UTC)
    burst = [
        _trial(outcome=1, days_ago=1, session="same-session")
        for _ in range(20)
    ]
    for index, item in enumerate(burst):
        burst[index] = item.model_copy(update={"trial_id": f"c{index}", "observed_at": stamp})
    collapsed = collapse_correlated_events(burst)
    assert len(collapsed) == 1
    assert collapsed[0].event_count == 20


def test_hierarchical_shrinkage_is_action_specific() -> None:
    coding = [_trial(outcome=1, days_ago=day, action="coding") for day in range(2, 40, 2)]
    coding += [_trial(outcome=0, days_ago=day, action="coding") for day in range(3, 10, 2)]
    fitness = [_trial(outcome=0, days_ago=day, action="fitness", domain="fitness") for day in range(2, 20)]
    as_of = datetime.now(UTC)
    coding_est = estimate_execution(coding + fitness, ActionContext(action_type="coding", domain="career", tokens=["coding"]), as_of=as_of)
    fitness_est = estimate_execution(coding + fitness, ActionContext(action_type="fitness", domain="fitness", tokens=["fitness"]), as_of=as_of)
    assert coding_est.action_mean > fitness_est.action_mean
    assert coding_est.usable


def test_sparse_evidence_is_limited_and_shrinks() -> None:
    sparse = [_trial(outcome=1, days_ago=3)]
    estimate = estimate_execution(
        sparse,
        ActionContext(action_type="coding", domain="career", tokens=["coding"]),
        as_of=datetime.now(UTC),
    )
    assert estimate.confidence == "insufficient"
    assert estimate.usable is False


def _event(event_type: str, category: str, days_ago: int, metric: str = "coding_session") -> NormalizedEvidence:
    stamp = datetime.now(UTC) - timedelta(days=days_ago)
    return NormalizedEvidence(
        event_type=event_type,
        domain="career",
        metric=metric,
        numeric_value=2,
        categorical_value=category,
        unit="hours",
        observed_at=stamp,
        source_quality="user_entered",
        provenance=Provenance(
            source_type="manual",
            source_authority="self_report",
            observed_vs_entered="user_entered",
            parsing_status="ok",
            completeness="complete",
            conflict_status="none",
        ),
        summary=f"{event_type} {metric}",
        fingerprint=f"{event_type}-{days_ago}-{metric}",
    )


def test_trials_require_commitment_pairs() -> None:
    activity = _event("repository_activity", "synced", 2, "commits_pushed")
    assert trials_from_evidence([activity]) == []
    planned = _event("commitment_created", "planned", 8)
    done = _event("commitment_completed", "completed", 7)
    trials = trials_from_evidence([planned, done])
    assert len(trials) == 1
    assert trials[0].outcome == 1


def test_resource_ranker_uses_metadata_not_provider_map() -> None:
    goal = {"title": "Receive a software engineering offer", "state_dimensions": ["interview_practice"]}
    ranked = rank_resources(
        [
            {
                "plugin_id": "notion",
                "id": "leetcode",
                "label": "LeetCode journal",
                "description": "software engineering interview practice completions",
            },
            {
                "plugin_id": "notion",
                "id": "running",
                "label": "Running journal",
                "description": "mileage and training recovery notes",
            },
        ],
        goal,
    )
    assert ranked[0]["label"] == "LeetCode journal"
    assert ranked[0]["recommended"] is True
    running_goal = {"title": "Finish a half marathon training block", "state_dimensions": ["training_consistency"]}
    running = rank_resources(
        [
            {"plugin_id": "notion", "id": "leetcode", "label": "LeetCode journal", "description": "software interview practice"},
            {"plugin_id": "notion", "id": "running", "label": "Running journal", "description": "half marathon training mileage"},
        ],
        running_goal,
    )
    assert running[0]["label"] == "Running journal"


def _assumptions(execution: float = 0.72) -> list[Assumption]:
    values = {
        "flow": (5, -10, 20, "units/period"),
        "growth_mean": (0.01, -0.1, 0.2, "fraction/period"),
        "growth_volatility": (0.03, 0, 0.5, "fraction/period"),
        "shock_probability": (0.02, 0, 0.5, "probability/period"),
        "shock_fraction": (0.1, 0, 0.9, "fraction"),
        "execution_probability": (execution, 0, 1, "probability"),
    }
    return [
        Assumption(
            name=name,
            value=value,
            minimum=lo,
            maximum=hi,
            step=0.01,
            source=AssumptionSource.EXPLORATION if name == "execution_probability" else AssumptionSource.USER,
            unit=unit,
        )
        for name, (value, lo, hi, unit) in values.items()
    ]


@pytest.mark.asyncio
async def test_user_a_vs_user_b_execution_adjusted_what_if() -> None:
    repo = InMemoryGoalRepository()
    goals = GoalService(repo)
    service = WhatIfService(goals)
    goal_a = GoalContract(
        goal_id=uuid4(),
        title="Get an FDE offer",
        goal_type=GoalType.CONTINUOUS_TARGET,
        success_definition={"metric": "savings", "target": 150},
        deadline=datetime.now(UTC) + timedelta(days=200),
        state_dimensions=["coding"],
    )
    goal_b = goal_a.model_copy(update={"goal_id": uuid4()})
    user = uuid4()
    await repo.create(goal_a, user)
    await repo.create(goal_b, user)
    coding = ActionContext(action_type="coding", domain="career", planned_amount=2, tokens=["leetcode", "coding"])
    hist_a = [_trial(outcome=1 if i % 7 else 0, days_ago=i, action="coding") for i in range(2, 50)]
    hist_b = [_trial(outcome=1 if i % 4 == 0 else 0, days_ago=i, action="coding") for i in range(2, 50)]
    est_a = estimate_execution(hist_a, coding, as_of=datetime.now(UTC))
    est_b = estimate_execution(hist_b, coding, as_of=datetime.now(UTC))
    assert est_a.probability > 0.7
    assert est_b.probability < 0.5

    intervention = StructuredIntervention(
        id="leetcode",
        title="LeetCode 2 hours per day",
        action_type="coding",
        target_dimension="savings",
        amount=2,
        unit="hours",
        duration_periods=12,
        effect_per_unit=2,
        effect_source=AssumptionSource.USER,
        diminishing_return=0.05,
        cost=ResourceCost(hours_per_week=14),
    )
    request_a = WhatIfRequest(
        goal_id=str(goal_a.goal_id),
        current_value=80,
        target_value=150,
        periods=12,
        assumptions=_assumptions(est_a.probability),
        intervention=intervention,
    )
    request_b = request_a.model_copy(
        update={"goal_id": str(goal_b.goal_id), "assumptions": _assumptions(est_b.probability)}
    )
    result_a = await service.simulate(request_a)
    result_b = await service.simulate(request_b)
    assert result_a.priced and result_b.priced
    assert result_a.conditional_on_execution_probability == pytest.approx(
        result_b.conditional_on_execution_probability, abs=0.03
    )
    assert result_a.execution_probability != result_b.execution_probability
    assert (result_a.scenario_probability or 0) > (result_b.scenario_probability or 0)
    assert result_a.execution_breakdown is not None
    assert result_a.execution_breakdown["conditional_on_full_execution"] != result_a.execution_breakdown["execution_adjusted_probability"]


def test_optimizer_uses_execution_adjusted_value() -> None:
    high = StructuredIntervention(
        id="high",
        title="Reliable action",
        action_type="coding",
        target_dimension="x",
        amount=2,
        unit="h",
        duration_periods=4,
        effect_per_unit=1,
        effect_source=AssumptionSource.USER,
        execution_probability=0.9,
        cost=ResourceCost(hours_per_week=2),
    )
    shiny = StructuredIntervention(
        id="shiny",
        title="Unfollowed action",
        action_type="coding",
        target_dimension="x",
        amount=2,
        unit="h",
        duration_periods=4,
        effect_per_unit=1.2,
        effect_source=AssumptionSource.USER,
        execution_probability=0.2,
        cost=ResourceCost(hours_per_week=2),
    )
    bundles = ActionOptimizer().enumerate([high, shiny], ResourceLimits(hours_per_week=4, money=10, energy=10))
    singles = [item for item in bundles if len(item.actions) == 1]
    by_id = {item.actions[0].id: item.expected_effect for item in singles}
    assert by_id["high"] > by_id["shiny"]


def test_behavior_profile_does_not_use_radar_for_math() -> None:
    history = [_trial(outcome=1, days_ago=i, action="coding") for i in range(2, 30)]
    goal = GoalContract(
        goal_id=uuid4(),
        title="Ship interview prep",
        goal_type=GoalType.HABIT,
        success_definition={"metric": "practice", "target": 1},
        deadline=datetime.now(UTC) + timedelta(days=90),
        state_dimensions=["coding"],
    )
    events = [
        _event("commitment_created", "planned", day, "coding")
        for day in range(4, 40, 2)
    ] + [
        _event("commitment_completed", "completed", day - 1, "coding")
        for day in range(4, 40, 2)
    ]
    profile = BehaviorService().profile_from_evidence(events, goal)
    assert profile.execution.probability == pytest.approx(
        estimate_execution(trials_from_evidence(events), ActionContext(action_type="coding", domain="coding", tokens=["coding"]), as_of=profile.as_of).probability,
        abs=0.08,
    )
    area = 0
    for dim in profile.dimensions:
        if dim.value is not None:
            area += dim.value
    assert profile.execution.probability != pytest.approx(
        area / max(len(profile.dimensions), 1), abs=0.001
    )
    assert history
