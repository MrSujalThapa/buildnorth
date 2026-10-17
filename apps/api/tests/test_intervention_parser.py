from personal_markets.what_if.intervention_parser import parse_intervention_text


def test_parse_leetcode_daily() -> None:
    parsed = parse_intervention_text("What if I solve 2 LeetCode problems every day?")
    assert len(parsed.changes) == 1
    assert parsed.changes[0].metric == "daily_practice_problems"
    assert parsed.changes[0].value == 2.0


def test_parse_monthly_contribution() -> None:
    parsed = parse_intervention_text("What if I invest $1500/month instead of $800?")
    assert any(item.metric == "monthly_contribution" for item in parsed.changes)
    assert parsed.changes[0].value == 1500.0


def test_parse_weekly_running_km() -> None:
    parsed = parse_intervention_text("What if I run 30 km/week?")
    assert len(parsed.changes) == 1
    assert parsed.changes[0].metric == "weekly_running_km"
    assert parsed.changes[0].value == 30.0


def test_parser_never_assigns_probability_effect() -> None:
    parsed = parse_intervention_text("What if I run 4 days per week?")
    assert all("probability" not in item.metric for item in parsed.changes)
