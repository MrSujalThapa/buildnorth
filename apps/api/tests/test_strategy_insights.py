from datetime import UTC, datetime, timedelta
from uuid import uuid4

from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.what_if.strategy_insights import (
    StrategyInsight,
    StrategyProposal,
    validate_strategy_proposal,
)


def _goal() -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title="Land an FDE offer",
        goal_type=GoalType.DEADLINE_EVENT,
        success_definition={"metric": "offer_received"},
        deadline=datetime.now(UTC) + timedelta(days=180),
        state_dimensions=["applications_submitted"],
    )


def _proposal(*insights: StrategyInsight) -> StrategyProposal:
    return StrategyProposal(understood_question="test", insights=list(insights))


def test_validator_drops_probability_language() -> None:
    kept, issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Boost odds",
                description="This adds 8 percentage points.",
                why_it_might_help="Uplift",
                why_this_fits="Guess",
                next_step="Apply more",
                evidence_to_collect="Odds",
            )
        ),
        goal=_goal(),
        question="what should I do?",
        evidence_summaries=[],
    )
    assert kept == []
    assert any("probability" in item.lower() or "numerical" in item.lower() for item in issues)


def test_validator_moves_unsupported_facts_to_assumptions() -> None:
    kept, issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Ask your cousin at Google",
                description="Use a family referral.",
                why_it_might_help="Warm intro",
                why_this_fits="You have a cousin at Google",
                next_step="Text them",
                evidence_to_collect="Whether they referred you",
                grounded_facts=["Your cousin works at Google as a staff engineer"],
            )
        ),
        goal=_goal(),
        question="what's the smartest next move?",
        evidence_summaries=["Submitted 8 applications this month."],
    )
    assert kept
    assert kept[0].grounded_facts == []
    assert any("Unverified" in item for item in kept[0].assumptions)
    assert issues


def test_validator_strips_invented_urls() -> None:
    kept, _issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Read this blog",
                description="A public post about referrals.",
                why_it_might_help="Context",
                why_this_fits="Hypothesis",
                next_step="Read it",
                evidence_to_collect="Notes",
                sources=["https://totally-invented.example/secret"],
            )
        ),
        goal=_goal(),
        question="how do I get referred?",
        evidence_summaries=[],
        research_sources=["frozen:hiring.json"],
    )
    assert kept
    assert kept[0].sources == []


def test_modeled_status_requires_an_allowed_metric() -> None:
    kept, _issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Ask for intros",
                description="Warm introductions, not more volume.",
                why_it_might_help="Access",
                why_this_fits="Hypothesis",
                next_step="Ask",
                evidence_to_collect="Intros",
                model_status="MODELED",
            )
        ),
        goal=_goal(),
        question="what if I asked for introductions?",
        evidence_summaries=[],
        allowed_metrics={"applications_per_week"},
    )
    assert kept[0].model_status == "UNPRICED"
