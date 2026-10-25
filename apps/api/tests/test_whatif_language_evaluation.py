"""Deterministic consumer-language safety corpus; no paid model calls."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.agents.intervention_critic import critique_intervention
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.integrations.fake_inference import _intervention
from personal_markets.ports import InterventionAgentProposal
from personal_markets.what_if.intervention_overrides import unmapped_change_metrics
from personal_markets.what_if.intervention_registry import allowed_metrics

# domain, question, expected handling, metric, quantity, operation. The latter
# three are populated only where the numerical lever is directly modeled.
QUESTIONS = [
    (
        "career",
        "what if i apply to 20 jobs next week",
        "priced",
        "applications_per_week",
        20,
        "set",
    ),
    (
        "career",
        "what if i send 5 more applications every week",
        "priced",
        "applications_per_week",
        5,
        "add",
    ),
    (
        "career",
        "what if i submit 5 additional applications each week",
        "priced",
        "applications_per_week",
        5,
        "add",
    ),
    ("career", "what if i do 10 applications a week", "priced", "applications_per_week", 10, "set"),
    ("career", "instead of 2 applications a week what if i do 10", "clarify", None, None, None),
    ("career", "what if i stop applying for 2 weeks", "clarify", None, None, None),
    ("career", "what if i do 3 mock interviews a week", "unpriced", None, None, None),
    (
        "career",
        "should i focus on cold emailing founders or applying directly",
        "clarify",
        None,
        None,
        None,
    ),
    ("career", "what if i spend 4 hours a day on leetcode", "unpriced", None, None, None),
    ("career", "can i get my chances to 90% before december", "unsupported", None, None, None),
    ("career", "what if i get rejected from my next interview", "unpriced", None, None, None),
    ("career", "what if i apply to 10 jobs and study 3 hours daily", "clarify", None, None, None),
    ("fitness", "what if i skip the gym tmrw", "unpriced", None, None, None),
    ("fitness", "what if i start running 5km every morning", "unpriced", None, None, None),
    ("fitness", "what if i only work out twice this week", "unpriced", None, None, None),
    ("fitness", "what if i train 6 days a week", "unpriced", None, None, None),
    (
        "fitness",
        "can i still hit my 10k target if i take a week off",
        "unsupported",
        None,
        None,
        None,
    ),
    ("fitness", "what if i run 20 miles a week instead of 10", "unpriced", None, None, None),
    ("fitness", "how much more training do i need to hit 80%", "unsupported", None, None, None),
    ("fitness", "skip gym tomorrow?", "unpriced", None, None, None),
    ("academic", "what if i study 2 hours tonight", "unpriced", None, None, None),
    ("academic", "what if i study 10 hours a day before my exam", "unpriced", None, None, None),
    ("academic", "what if i miss tomorrow's lecture", "unpriced", None, None, None),
    ("academic", "what if i get 85 on my midterm", "unpriced", None, None, None),
    ("academic", "what if i only have 3 days left", "clarify", None, None, None),
    ("academic", "how do i get my chances of passing above 95%", "unsupported", None, None, None),
    ("academic", "what if i dont study tmr", "unpriced", None, None, None),
    ("finance", "what if i save 500 bucks every month", "unpriced", None, None, None),
    ("finance", "what if i spend an extra 200 this week", "unpriced", None, None, None),
    ("finance", "what if my income drops by 20%", "unpriced", None, None, None),
    ("finance", "what if i invest another 1000", "clarify", None, None, None),
    ("finance", "what if i save 50 a week instead of 100", "clarify", None, None, None),
    ("finance", "can i reach 20k by december", "unsupported", None, None, None),
    ("finance", "what's the minimum i need to save each month", "unsupported", None, None, None),
    ("finance", "what if i contribute 1500 every month", "unpriced", None, None, None),
    ("personal", "what if i don't practice guitar this week", "unpriced", None, None, None),
    ("personal", "what if i practice for 30 minutes every day", "unpriced", None, None, None),
    ("personal", "what if i read 2 books a month", "unpriced", None, None, None),
    ("personal", "what if i miss 3 days", "clarify", None, None, None),
    ("personal", "what if i practice twice as much", "clarify", None, None, None),
    ("personal", "am i still on track", "unsupported", None, None, None),
    ("personal", "what if i double it", "clarify", None, None, None),
    ("startup", "what if i talk to 20 customers this month", "unpriced", None, None, None),
    ("startup", "what if i get 5 paying customers", "unpriced", None, None, None),
    ("startup", "what if i spend 15 hours a week building", "unpriced", None, None, None),
    ("startup", "what if i don't launch until next month", "unpriced", None, None, None),
    ("startup", "should i prioritize outreach or product development", "clarify", None, None, None),
    ("startup", "nah make it 5 a week", "clarify", None, None, None),
    ("startup", "which one is better", "clarify", None, None, None),
    ("startup", "what are my odds rn", "unsupported", None, None, None),
]

ADVERSARIAL = [
    ("career", "I already applied to 5 jobs last week"),
    ("career", "what if i sent 5 applications yesterday"),
    ("career", "what if i send 5 more applications each month"),
    ("career", "what if i send 5 cold emails and 10 applications a week"),
    ("career", "what if i apply to 10 jobs a week and study 3 hours daily"),
    ("career", "what if i submit 5 applications every day"),
    ("career", "okay what about 3 instead"),
    ("fitness", "what if i run 40 km each week"),
    ("finance", "what if i cut rent by 500 bucks every month"),
    ("academic", "what if i scored 95 on an exam yesterday"),
    ("personal", "what if i read 100 books next week"),
    ("startup", "what if i send 20 cold emails each week"),
]


def _goal(domain: str) -> GoalContract:
    labels = {
        "career": ("Land an offer", GoalType.DEADLINE_EVENT, ["applications_submitted"]),
        "fitness": ("Run a 10k", GoalType.THRESHOLD, ["running_distance"]),
        "academic": ("Pass my exam", GoalType.DEADLINE_EVENT, ["exam_grade"]),
        "finance": ("Reach net worth target", GoalType.CONTINUOUS_TARGET, ["monthly_contribution"]),
        "personal": ("Read more books", GoalType.THRESHOLD, ["books_read"]),
        "startup": ("Launch startup", GoalType.MULTI_OUTCOME, ["customers"]),
    }
    title, goal_type, dimensions = labels[domain]
    return GoalContract(
        goal_id=uuid4(),
        title=title,
        goal_type=goal_type,
        success_definition={"metric": dimensions[0], "target": 10},
        deadline=datetime.now(UTC) + timedelta(days=180),
        state_dimensions=dimensions,
    )


@pytest.mark.parametrize("domain,question,handling,metric,quantity,operation", QUESTIONS)
def test_consumer_question_is_priced_only_for_a_stated_model_lever(
    domain: str,
    question: str,
    handling: str,
    metric: str | None,
    quantity: int | None,
    operation: str | None,
) -> None:
    goal = _goal(domain)
    proposal = InterventionAgentProposal.model_validate(
        _intervention(
            {"intervention_text": question, "allowed_metrics": list(allowed_metrics(goal))}
        )
    )
    critique = critique_intervention(goal, proposal, question)
    assumptions = {"weekly_application_rate"} if domain == "career" else {"flow"}
    actual_priced = bool(
        critique.approved
        and critique.validated_changes
        and not unmapped_change_metrics(
            assumptions, [change.metric for change in critique.validated_changes]
        )
    )
    assert actual_priced == (handling == "priced"), question
    if metric:
        assert critique.validated_changes[0].metric == metric
        assert critique.validated_changes[0].value == quantity
        assert critique.validated_changes[0].operation == operation


@pytest.mark.parametrize("domain,question", ADVERSARIAL)
def test_adversarial_questions_do_not_acquire_unmeasured_odds(domain: str, question: str) -> None:
    goal = _goal(domain)
    proposal = InterventionAgentProposal.model_validate(
        _intervention(
            {"intervention_text": question, "allowed_metrics": list(allowed_metrics(goal))}
        )
    )
    critique = critique_intervention(goal, proposal, question)
    assumptions = {"weekly_application_rate"} if domain == "career" else {"flow"}
    assert not (
        critique.approved
        and critique.validated_changes
        and not unmapped_change_metrics(
            assumptions, [change.metric for change in critique.validated_changes]
        )
    ), question
