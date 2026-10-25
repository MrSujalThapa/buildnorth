from __future__ import annotations

import pytest

from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.service import GoalService
from personal_markets.what_if.domain import (
    BlueprintAction,
    ResourceLimitsInput,
    TargetSearchRequest,
)
from personal_markets.what_if.repository import InMemorySimulationRepository
from personal_markets.what_if.reverse_blueprint import (
    DEDUPE_TOLERANCE,
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
    assert blueprint.modeled_probability == pytest.approx(0.8905)
    assert blueprint.delta_pp == pytest.approx((0.8905 - 0.57) * 100)
    assert blueprint.headline.startswith("To reach ~90%: raise monthly contribution to $3,350")
    [change] = blueprint.lever_changes
    assert (change.baseline_value, change.recommended_value, change.effort) == (
        1800, 3350, "moderate"
    )
    assert blueprint.steps[0].startswith("Raise monthly contribution from $1,800 to $3,350")
    assert any("72%" in step for step in blueprint.steps)
    assert [item.lever_changes[0].recommended_value for item in blueprint.alternatives] == [
        2125, 2600, 5000
    ]
    assert [item.reaches_target for item in blueprint.alternatives] == [False, False, True]
    assert all(item.id != "lever:flow:3350" for item in blueprint.alternatives)
    assert any("short of target" in note for note in blueprint.tradeoffs)


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
    assert "out of reach" in blueprint.headline
    # 35 and 50 add under 1 pp over 20, so the plateau's start is the recommendation.
    assert blueprint.lever_changes[0].recommended_value == 20
    assert blueprint.plateau is not None and blueprint.plateau.cause == "follow_through"
    assert blueprint.alternatives
    assert all(not item.reaches_target for item in blueprint.alternatives)


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
    service = LinearWhatIfService(
        GoalService(InMemoryGoalRepository()), InMemorySimulationRepository()
    )
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
