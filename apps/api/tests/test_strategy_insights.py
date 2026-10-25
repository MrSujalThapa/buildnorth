from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.what_if.strategy_insights import compose_strategy_insights


def _goal(title: str, goal_type: GoalType) -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title=title,
        goal_type=goal_type,
        success_definition={"metric": "offer_received"},
        deadline=datetime.now(UTC) + timedelta(days=180),
        state_dimensions=["applications_submitted"],
    )


def test_vc_evidence_grounds_a_warm_intro_suggestion() -> None:
    insights = compose_strategy_insights(
        _goal("Land an FDE offer", GoalType.DEADLINE_EVENT),
        question="what's a smarter way to get an FDE offer?",
        evidence_summaries=["Pitched a seed VC last month about the startup."],
    )
    titles = " ".join(item.title.lower() for item in insights)
    assert "investor" in titles or "introduction" in titles
    assert all(item.model_status != "MODELED" for item in insights)
    assert any(item.grounded_facts for item in insights)


def test_without_vc_evidence_stays_conditional() -> None:
    insights = compose_strategy_insights(
        _goal("Land an FDE offer", GoalType.DEADLINE_EVENT),
        question="who could help me reach this goal faster?",
        evidence_summaries=["Submitted 8 applications this month."],
    )
    blob = " ".join(f"{item.why_this_fits} {item.assumptions}" for item in insights).lower()
    assert "no authorized evidence" in blob or "conditional" in blob or "assumption" in blob
    assert "pitched a seed vc" not in blob
