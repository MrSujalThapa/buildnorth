from personal_markets.profile.demo_portfolio import demo_portfolio


def test_demo_portfolio_is_isolated_and_nonlinear() -> None:
    payload = demo_portfolio()
    assert payload["demo"] is True
    assert "not written" in str(payload["message"]).lower()
    goals = payload["goals"]
    histories = payload["histories"]
    assert len(goals) >= 4
    assert payload["collections"]
    for goal in goals:
        points = histories[goal["goal_id"]]
        assert len(points) >= 12
        assert all(item["source_kind"] == "synthetic_demo" for item in points)
        values = [item["probability"] for item in points]
        deltas = [b - a for a, b in zip(values, values[1:], strict=False)]
        assert len(set(round(delta, 4) for delta in deltas)) > 1
