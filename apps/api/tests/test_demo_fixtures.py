from personal_markets.demo_fixtures import (
    DEMO_GOAL_IDS,
    fixture_compare,
    fixture_futures,
    fixture_simulate,
    fixture_target_search,
    is_demo_goal,
)


def test_demo_goal_ids() -> None:
    assert len(DEMO_GOAL_IDS) == 5
    assert is_demo_goal("20000000-0000-0000-0000-000000000002")


def test_career_simulate_fixture_is_marked_demo_seed() -> None:
    result = fixture_simulate("20000000-0000-0000-0000-000000000002")
    assert result is not None
    assert result.status == "DEMO_SEED"
    assert result.receipt.get("provenance") == "DEMO_SEED"
    assert result.baseline_probability == 0.41
    assert result.scenario_probability == 0.53
    assert len(result.distribution_bins) >= 8
    assert len(result.sensitivity) >= 4
    assert len(result.fan) >= 6
    assert isinstance(result.receipt.get("demo_simulation_points"), list)


def test_compare_and_futures_fixtures() -> None:
    goal = "20000000-0000-0000-0000-000000000002"
    compare = fixture_compare(goal)
    futures = fixture_futures(goal)
    paths = fixture_target_search(goal)
    assert compare is not None and len(compare.paths) == 3
    assert futures is not None and len(futures.outcomes) == 4
    assert paths is not None and len(paths.paths) >= 3
