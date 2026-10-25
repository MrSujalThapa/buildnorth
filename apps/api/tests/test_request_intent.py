from personal_markets.what_if.request_intent import classify_what_if_request


def test_application_rate_is_quantitative() -> None:
    classified = classify_what_if_request("What if I apply to 10 jobs a week?")
    assert classified.kind == "quantitative_scenario"


def test_completed_applications_are_evidence() -> None:
    classified = classify_what_if_request("I actually submitted 10 applications this week.")
    assert classified.kind == "evidence_report"
    assert classified.needs_confirmation is True


def test_hedged_guess_is_uncertain_evidence() -> None:
    classified = classify_what_if_request("I think I did around 20 applications")
    assert classified.kind == "evidence_report"
    assert classified.uncertain is True
    assert classified.needs_confirmation is False


def test_planned_future_is_not_confirmed_evidence() -> None:
    classified = classify_what_if_request("I plan to run 10 km tomorrow")
    assert classified.kind == "evidence_report"
    assert classified.uncertain is True


def test_opportunity_question_is_not_priced() -> None:
    classified = classify_what_if_request("what's the smartest move I haven't tried yet?")
    assert classified.kind == "opportunity_discovery"


def test_current_odds_is_distinct_from_scenario() -> None:
    classified = classify_what_if_request("what are my odds rn")
    assert classified.kind == "current_odds"


def test_follow_up_without_baseline_asks_for_context() -> None:
    classified = classify_what_if_request("okay, actually make it 15")
    assert classified.kind in {"follow_up", "clarification_needed"}
