from personal_markets.profile.demo_portfolio import demo_portfolio


def test_demo_portfolio_is_isolated_and_nonlinear() -> None:
    payload = demo_portfolio()
    assert payload["demo"] is True
    assert "not written" in str(payload["message"]).lower()
    goals = payload["goals"]
    histories = payload["histories"]
    assert len(goals) == 6
    assert payload["collections"]
    collection = payload["collections"][0]
    assert len(collection["collection"]["goal_ids"]) == 4
    assert collection["priced_goals"] == 4
    assert collection["portfolio_odds"] > 0
    expected_change = sum(
        item["points"][-1]["value"] - item["points"][-2]["value"]
        for item in collection["series"]
    ) / 4
    assert round(collection["change_pp"], 4) == round(expected_change, 4)
    assert collection["progress"]["value"] is None
    assert all(
        0 <= point["value"] <= 100
        for item in collection["series"]
        for point in item["points"]
    )
    for goal in goals:
        points = histories[goal["goal_id"]]
        assert len(points) >= 12
        assert all(item["source_kind"] == "synthetic_demo" for item in points)
        values = [item["probability"] for item in points]
        deltas = [b - a for a, b in zip(values, values[1:], strict=False)]
        assert len(set(round(delta, 4) for delta in deltas)) > 1
