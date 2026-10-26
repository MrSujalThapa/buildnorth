from __future__ import annotations

import pytest

from personal_markets.forecasting.hiring import HiringReferenceRates
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.service import GoalService
from personal_markets.what_if.domain import (
    Assumption,
    BlueprintAction,
    ResourceLimitsInput,
    TargetSearchRequest,
    WhatIfRequest,
)
from personal_markets.what_if.repository import InMemorySimulationRepository
from personal_markets.what_if.reverse_blueprint import (
    DEDUPE_TOLERANCE,
    TARGET_TOLERANCE_PP,
    BlueprintInputs,
    LeverScan,
    LeverSetting,
    LeverSpec,
    PricedOption,
    ScanPoint,
    build_reverse_blueprint,
    classify_effort,
    detect_plateau,
    efficient_options,
)
from personal_markets.what_if.reverse_search import (
    COMPOSED_RATE_MAX_MULTIPLE,
    MAX_CONVERSION_RELATIVE_LIFT,
    classify_lever,
    composed_rate_assumptions,
    select_levers,
    unpriced_recommendations,
)
from personal_markets.what_if.service import WhatIfService
from test_pass4_remaining import LinearWhatIfService, action, make_base, make_goal

APPS = LeverSpec(
    lever_id="weekly_application_rate",
    unit="applications/week",
    baseline=2,
    minimum=0,
    maximum=50,
    step=1,
)
FLOW = LeverSpec(
    lever_id="flow", unit="currency/month", baseline=1800, minimum=-5000, maximum=5000, step=25
)


def lever_option(lever: LeverSpec, value: float, probability: float) -> PricedOption:
    return PricedOption(
        id=f"lever:{lever.lever_id}:{value:g}",
        probability=probability,
        settings=(LeverSetting(lever, value),),
    )


def test_efficient_options_dedupes_ties_and_keeps_the_cheapest() -> None:
    options = [
        lever_option(APPS, 30, 0.861),
        lever_option(APPS, 20, 0.858),  # same answer as 30 within 0.5 pp, smaller change
        lever_option(APPS, 10, 0.80),
        lever_option(APPS, 3, 0.70),  # no better than baseline: junk row
        lever_option(APPS, 45, 0.80),  # more effort, lower odds: dominated
    ]
    kept = efficient_options(options, baseline=0.70)
    assert [item.settings[0].value for item in kept] == [10, 20]
    probabilities = [item.probability for item in kept]
    assert probabilities == sorted(probabilities)
    gaps = [b - a for a, b in zip(probabilities, probabilities[1:], strict=False)]
    assert all(gap > DEDUPE_TOLERANCE for gap in gaps)


def test_efficient_options_keeps_the_first_option_that_crosses_the_target() -> None:
    options = [lever_option(APPS, 38, 0.8876), lever_option(APPS, 40, 0.8909)]
    without = efficient_options(options, baseline=0.74)
    assert [item.settings[0].value for item in without] == [38]
    kept = efficient_options(options, baseline=0.74, reaches=lambda p: p + 0.01 >= 0.9)
    assert [item.settings[0].value for item in kept] == [38, 40]


def test_classify_effort_uses_ratio_then_range() -> None:
    assert classify_effort(FLOW, 1800) == "none"
    assert classify_effort(FLOW, 2600) == "light"
    assert classify_effort(FLOW, 3350) == "moderate"
    assert classify_effort(FLOW, 5000) == "heavy"
    zero = LeverSpec(lever_id="weekly_application_rate", unit="applications/week",
                     baseline=0, minimum=0, maximum=40, step=1)
    assert classify_effort(zero, 8) == "light"
    assert classify_effort(zero, 20) == "moderate"
    assert classify_effort(zero, 35) == "heavy"


def test_detect_plateau_names_follow_through_cap() -> None:
    scan = LeverScan(
        APPS,
        (
            ScanPoint(2, 0.40),
            ScanPoint(10, 0.70, 0.82),
            ScanPoint(20, 0.80, 0.985),
            ScanPoint(30, 0.805, 0.99),
            ScanPoint(50, 0.806, 0.995),
        ),
    )
    plateau = detect_plateau(scan, baseline=0.40, follow_through=0.72)
    assert plateau is not None
    assert plateau.cause == "follow_through"
    assert plateau.starts_at_value == 20
    assert plateau.plateau_probability == pytest.approx(0.806)
    assert "72%" in plateau.explanation and "20 applications/week" in plateau.explanation


def test_detect_plateau_saturation_and_still_rising() -> None:
    saturating = LeverScan(
        APPS, (ScanPoint(2, 0.3), ScanPoint(10, 0.6, 0.6), ScanPoint(30, 0.605, 0.605),
               ScanPoint(50, 0.606, 0.606)),
    )
    plateau = detect_plateau(saturating, baseline=0.3, follow_through=None)
    assert plateau is not None and plateau.cause == "saturation"
    assert plateau.starts_at_value == 10
    rising = LeverScan(APPS, (ScanPoint(2, 0.3), ScanPoint(20, 0.5), ScanPoint(50, 0.7)))
    assert detect_plateau(rising, baseline=0.3, follow_through=0.72) is None


def test_detect_plateau_respects_decreasing_levers() -> None:
    pace = LeverSpec(lever_id="flow", unit="seconds/week", baseline=-5, minimum=-30, maximum=0,
                     step=1, increasing=False)
    scan = LeverScan(pace, (ScanPoint(-5, 0.6), ScanPoint(-15, 0.9, 0.9),
                            ScanPoint(-30, 0.905, 0.905)))
    plateau = detect_plateau(scan, baseline=0.6, follow_through=None)
    assert plateau is not None and plateau.starts_at_value == -15


def test_blueprint_reachable_picks_cheapest_reaching_path() -> None:
    scan_points = ((1800, 0.57), (2125, 0.71), (2600, 0.83), (3350, 0.8905), (5000, 0.8965))
    options = tuple(lever_option(FLOW, value, p) for value, p in scan_points[1:])
    blueprint = build_reverse_blueprint(
        BlueprintInputs(
            target=0.9,
            baseline=0.57,
            tolerance=0.01,
            options=options,
            scans=(LeverScan(FLOW, tuple(ScanPoint(v, p) for v, p in scan_points)),),
            follow_through=0.72,
            levers=(FLOW,),
        )
    )
    assert blueprint.reachable and not blueprint.already_satisfied
    # 89.05% is 0.95 pp short, outside the 0.5 pp tolerance even though the request
    # asked for 1 pp; 89.65% is within it.
    assert blueprint.tolerance_pp == pytest.approx(TARGET_TOLERANCE_PP)
    assert blueprint.modeled_probability == pytest.approx(0.8965)
    assert blueprint.delta_pp == pytest.approx((0.8965 - 0.57) * 100)
    assert blueprint.headline.startswith("Reaches the 90% target (modeled 89.")
    assert "within 0.5 pp): raise monthly contribution to $5,000/month." in blueprint.headline
    [change] = blueprint.lever_changes
    assert (change.baseline_value, change.recommended_value, change.effort) == (
        1800, 5000, "heavy"
    )
    assert blueprint.steps[0].startswith("Raise monthly contribution from $1,800 to $5,000")
    assert any("72%" in step for step in blueprint.steps)
    assert [item.lever_changes[0].recommended_value for item in blueprint.alternatives] == [
        2125, 2600, 3350
    ]
    assert [item.reaches_target for item in blueprint.alternatives] == [False, False, False]
    assert any("short of target" in note for note in blueprint.tradeoffs)
    [action] = blueprint.plan_actions
    assert action.order == 1 and action.required_value == 5000
    assert action.quantity_label == "$5,000/month"


@pytest.mark.parametrize(
    ("modeled", "reaches"), [(0.84, False), (0.8449, False), (0.8452, True), (0.851, True)]
)
def test_reaching_requires_odds_within_half_a_point(modeled: float, reaches: bool) -> None:
    blueprint = build_reverse_blueprint(
        BlueprintInputs(
            target=0.85,
            baseline=0.4,
            tolerance=0.01,
            options=(lever_option(APPS, 17, modeled),),
            levers=(APPS,),
        )
    )
    assert blueprint.reachable is reaches
    assert blueprint.tolerance_pp == pytest.approx(0.5)
    if reaches:
        assert blueprint.headline.startswith("Reaches the 85% target")
    else:
        assert blueprint.headline.startswith(
            "85% is not reachable with the currently modeled levers. Highest modeled odds: "
            f"{modeled * 100:.1f}%"
        )
        assert "Reaches" not in blueprint.headline


def test_blueprint_unreachable_explains_the_plateau() -> None:
    points = ((2, 0.30), (10, 0.55, 0.9), (20, 0.58, 0.98), (35, 0.585, 0.99), (50, 0.586, 0.99))
    options = tuple(lever_option(APPS, item[0], item[1]) for item in points[1:])
    blueprint = build_reverse_blueprint(
        BlueprintInputs(
            target=0.9,
            baseline=0.30,
            tolerance=0.01,
            options=options,
            scans=(LeverScan(APPS, tuple(ScanPoint(*item) for item in points)),),
            follow_through=0.72,
            levers=(APPS,),
        )
    )
    assert not blueprint.reachable
    assert "not reachable with the currently modeled levers" in blueprint.headline
    # Unreachable targets report the highest modeled odds and the plan that gets there.
    assert blueprint.lever_changes[0].recommended_value == 50
    assert blueprint.modeled_probability == pytest.approx(0.586)
    assert "58.6%" in blueprint.headline
    assert blueprint.plateau is not None and blueprint.plateau.cause == "follow_through"
    assert blueprint.alternatives
    assert all(not item.reaches_target for item in blueprint.alternatives)
    notes = blueprint.missing_capabilities
    assert any("Follow-through is modeled at 72%" in note for note in notes)


def test_blueprint_unreachable_still_rising_names_the_lever_range() -> None:
    points = ((2, 0.2), (25, 0.4), (50, 0.6))
    blueprint = build_reverse_blueprint(
        BlueprintInputs(
            target=0.9,
            baseline=0.2,
            tolerance=0.01,
            options=tuple(lever_option(APPS, v, p) for v, p in points[1:]),
            scans=(LeverScan(APPS, tuple(ScanPoint(v, p) for v, p in points)),),
            levers=(APPS,),
        )
    )
    assert not blueprint.reachable
    assert blueprint.plateau is not None and blueprint.plateau.cause == "lever_range"


def test_blueprint_combines_an_action_with_a_lever() -> None:
    mock = BlueprintAction(action_id="mock", title="Weekly mock interview", hours_per_week=2)
    combo = PricedOption(
        id="combo", probability=0.91, settings=(LeverSetting(APPS, 6),), actions=(mock,)
    )
    lever_only = lever_option(APPS, 30, 0.905)
    blueprint = build_reverse_blueprint(
        BlueprintInputs(
            target=0.9,
            baseline=0.6,
            tolerance=0.01,
            options=(lever_only, combo, PricedOption(id="mock", probability=0.7, actions=(mock,))),
            levers=(APPS,),
        )
    )
    assert blueprint.reachable
    assert blueprint.actions == [mock]
    assert blueprint.lever_changes[0].recommended_value == 6
    assert "add Weekly mock interview" in blueprint.headline
    assert any(step.startswith("Add Weekly mock interview") for step in blueprint.steps)


def test_blueprint_already_satisfied_keeps_current_plan() -> None:
    blueprint = build_reverse_blueprint(
        BlueprintInputs(target=0.5, baseline=0.74, tolerance=0.01, levers=(APPS,))
    )
    assert blueprint.already_satisfied and blueprint.reachable
    assert blueprint.lever_changes[0].effort == "none"
    assert blueprint.modeled_probability == pytest.approx(0.74)


@pytest.mark.asyncio
async def test_target_search_blueprint_is_snapped_and_matches_priced_paths() -> None:
    goal = make_goal()
    repository = InMemoryGoalRepository()
    await repository.upsert_seed(goal)
    service = LinearWhatIfService(GoalService(repository), InMemorySimulationRepository())
    result = await service.target_search(
        TargetSearchRequest(
            base=make_base(str(goal.goal_id), flow=3),
            target_probability=0.7,
            candidates=[action("small", 0.05, 1)],
            limits=ResourceLimitsInput(hours_per_week=5, money=1000, energy=5),
        )
    )
    blueprint = result.blueprint
    assert blueprint is not None and blueprint.reachable
    assert blueprint.baseline_probability == pytest.approx(result.current_probability)
    assert blueprint.modeled_probability is not None
    assert blueprint.modeled_probability + 0.01 >= 0.7
    for change in blueprint.lever_changes:
        steps = change.recommended_value / 0.1
        assert steps == pytest.approx(round(steps))
    priced = {round(path.resulting_probability, 9) for path in result.paths}
    assert round(blueprint.modeled_probability, 9) in priced
    odds = [item.modeled_probability for item in blueprint.alternatives]
    assert len(odds) == len({round(value, 3) for value in odds})


# --- Multi-lever Reverse search -------------------------------------------------


def _hiring_assumptions() -> tuple[list[Assumption], HiringReferenceRates]:
    from personal_markets.forecasting.hiring import load_hiring_reference
    from personal_markets.what_if.baseline_state import build_baseline_state
    from test_change_end_to_end import _evidence, _hiring_goal

    goal = _hiring_goal()
    state = build_baseline_state(
        goal,
        [
            _evidence("career", "applications_submitted", 15),
            _evidence("career", "phone_screens_completed", 3),
        ],
    )
    assert state.priced
    return state.assumptions, load_hiring_reference()


def test_hiring_levers_are_volume_plus_bounded_conversions_never_execution() -> None:
    assumptions, reference = _hiring_assumptions()
    selection = select_levers(assumptions)
    kinds = {lever.lever_id: lever.kind for lever in selection.levers}
    assert kinds.pop("weekly_application_rate") == "behavioral_volume"
    assert set(kinds) == set(reference.stage_rates)
    assert set(kinds.values()) == {"conversion"}
    excluded = {item.name for item in selection.excluded}
    assert {"execution_probability", "periods_remaining"} <= excluded
    for lever in selection.levers:
        if lever.kind != "conversion":
            continue
        cap = lever.baseline * (1 + MAX_CONVERSION_RELATIVE_LIFT)
        assert lever.minimum == pytest.approx(lever.baseline)
        assert lever.baseline < lever.maximum <= cap + 1e-9
        assert cap - lever.maximum < lever.step
        assert "not evidence" in lever.bound_source


def test_finance_levers_exclude_market_parameters_and_execution() -> None:
    from personal_markets.what_if.baseline_state import build_baseline_state
    from test_change_end_to_end import _evidence, _finance_goal

    state = build_baseline_state(
        _finance_goal(),
        [
            _evidence("finance", "net_worth", 120_000, unit="CAD"),
            _evidence("finance", "monthly_contribution", 2500, unit="CAD/month"),
        ],
    )
    selection = select_levers(state.assumptions)
    assert [lever.lever_id for lever in selection.levers] == ["flow"]
    excluded = {item.name: item.reason for item in selection.excluded}
    for name in ("growth_mean", "growth_volatility", "shock_probability", "shock_fraction"):
        assert "not under your control" in excluded[name]
    assert "never searched" in excluded["execution_probability"]


def test_execution_probability_is_never_a_lever_even_if_mislabelled() -> None:
    from personal_markets.forecasting.families import AssumptionSource
    from personal_markets.what_if.domain import Assumption

    sneaky = Assumption(
        name="execution_probability", value=0.72, minimum=0, maximum=1, step=0.01,
        source=AssumptionSource.USER, unit="probability", scope="pipeline_activity",
    )
    assert classify_lever(sneaky) is None


def test_composed_rate_becomes_a_bounded_volume_lever() -> None:
    [assumption] = composed_rate_assumptions(
        {"primary.rate": "count/week", "primary.mu": "log_growth/week"},
        {"primary.rate": 0.3, "primary.mu": 0.1},
    )
    [lever] = select_levers([assumption]).levers
    assert lever.kind == "behavioral_volume" and lever.lever_id == "primary.rate"
    assert lever.origin == pytest.approx(0.3)
    assert lever.maximum == pytest.approx(0.3 * COMPOSED_RATE_MAX_MULTIPLE)
    assert "not evidence" in lever.bound_source


def test_unpriced_recommendations_are_unmapped_career_actions() -> None:
    assumptions, _ = _hiring_assumptions()
    names = {item.name for item in assumptions}
    items = unpriced_recommendations("career", names, {"weekly_application_rate"})
    metrics = {item.metric for item in items}
    assert {
        "mock_interviews_per_week", "linkedin_posts_per_week", "networking_events_per_week"
    } <= metrics
    assert not metrics & {
        "applications_per_week", "applications_per_month", "weekly_application_rate"
    }
    assert all(item.priced is False for item in items)
    assert all("not priced" in item.measurement for item in items)
    assert all("probab" not in item.model_dump_json().lower() for item in items)


async def _hiring_service() -> tuple[WhatIfService, WhatIfRequest]:
    from uuid import uuid4

    from personal_markets.evidence.service import EvidenceService
    from personal_markets.persistence.agent_store import InMemoryEvidenceRepository
    from personal_markets.what_if.baseline_state import build_baseline_state
    from personal_markets.what_if.domain import WhatIfRequest
    from test_change_end_to_end import _hiring_goal, _seed_evidence

    goal = _hiring_goal()
    user_id = uuid4()
    goals = InMemoryGoalRepository()
    await goals.create(goal, user_id)
    evidence_repo = InMemoryEvidenceRepository({goal.goal_id: True})
    await _seed_evidence(
        evidence_repo,
        goal.goal_id,
        user_id,
        [
            ("career", "applications_submitted", 15, "count"),
            ("career", "phone_screens_completed", 3, "count"),
        ],
    )
    service = WhatIfService(GoalService(goals), evidence=EvidenceService(evidence_repo))
    state = build_baseline_state(goal, await evidence_repo.list_for_goal(goal.goal_id))
    base = WhatIfRequest.model_validate(
        {
            "goal_id": str(goal.goal_id),
            "current_value": state.current_value or 0,
            "target_value": state.target_value or 1,
            "periods": state.periods or 1,
            "direction": state.direction,
            "assumptions": state.assumptions,
            "config": state.config,
        }
    )
    return service, base


def _search(base: WhatIfRequest, target: float) -> TargetSearchRequest:
    return TargetSearchRequest(
        base=base,
        target_probability=target,
        limits=ResourceLimitsInput(hours_per_week=20, money=0, energy=1),
    )


@pytest.mark.asyncio
async def test_hiring_target_search_recommends_a_multi_lever_plan() -> None:
    service, base = await _hiring_service()
    result = await service.target_search(_search(base, 0.6))
    blueprint = result.blueprint
    assert blueprint is not None and blueprint.reachable
    assert blueprint.tolerance_pp == pytest.approx(0.5)
    assert blueprint.modeled_probability is not None
    assert blueprint.modeled_probability >= 0.6 - TARGET_TOLERANCE_PP / 100
    kinds = [action.kind for action in blueprint.plan_actions]
    assert len(kinds) >= 2 and kinds[0] == "behavioral_volume" and "conversion" in kinds
    assert [action.order for action in blueprint.plan_actions] == list(
        range(1, len(kinds) + 1)
    )
    for step in blueprint.plan_actions:
        assert step.required_value is not None and step.quantity_label
        assert "26 weeks" in step.timeline
        if step.kind == "conversion":
            assert step.requires_evidence and "interview prep or referrals" in step.constraint
    searched = {item.lever_id for item in blueprint.searched_levers}
    assert "weekly_application_rate" in searched and "final_to_offer" in searched
    assert "execution_probability" not in searched
    # The recommended plan is an engine price that the feasible paths carry too.
    priced = {round(path.resulting_probability, 9) for path in result.paths}
    assert round(blueprint.modeled_probability, 9) in priced
    # Applications alone also reach 60%, but cost more effort than the combination.
    assert any(
        item.reaches_target and len(item.lever_changes) == 1 for item in blueprint.alternatives
    )


@pytest.mark.asyncio
async def test_hiring_unreachable_target_reports_highest_modeled_plan() -> None:
    service, base = await _hiring_service()
    result = await service.target_search(_search(base, 0.9))
    blueprint = result.blueprint
    assert blueprint is not None and not blueprint.reachable and not result.feasible
    assert blueprint.modeled_probability is not None
    assert blueprint.modeled_probability < 0.9 - TARGET_TOLERANCE_PP / 100
    assert blueprint.modeled_probability == pytest.approx(blueprint.max_modeled_probability)
    assert blueprint.headline.startswith(
        "90% is not reachable with the currently modeled levers. Highest modeled odds: "
    )
    assert blueprint.plan_actions
    assert any("Follow-through" in note for note in blueprint.missing_capabilities)
    assert {item.metric for item in blueprint.unpriced_recommendations} >= {
        "mock_interviews_per_week"
    }


@pytest.mark.asyncio
async def test_reverse_uses_the_same_follow_through_as_change() -> None:
    from personal_markets.what_if.domain import InterventionChangeInput

    service, base = await _hiring_service()
    change = await service.fast_reprice(
        base.model_copy(
            update={
                "parsed_changes": [
                    InterventionChangeInput(
                        metric="weekly_application_rate",
                        operation="set",
                        value=10,
                        unit="applications/week",
                        provenance="EXPLORATION_ASSUMPTION",
                    )
                ]
            }
        )
    )
    result = await service.target_search(_search(base, 0.9))
    assert result.blueprint is not None
    assert result.blueprint.follow_through_probability == pytest.approx(
        change.execution_probability
    )
    assert result.blueprint.follow_through_source == "default"
