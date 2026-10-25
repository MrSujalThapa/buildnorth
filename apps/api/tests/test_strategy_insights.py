# ruff: noqa: E501
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


def test_modeled_requires_named_metric_on_the_intervention() -> None:
    kept, _issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Raise applications_per_week",
                description="A measured weekly application rate change.",
                why_it_might_help="This is a modeled lever for this goal family.",
                why_this_fits="The question asked for a volume change.",
                next_step="Set applications_per_week to 8.",
                evidence_to_collect="Applications actually submitted that week.",
                model_status="MODELED",
                modeled_metric="applications_per_week",
            )
        ),
        goal=_goal(),
        question="what if I apply more?",
        evidence_summaries=[],
        allowed_metrics={"applications_per_week"},
    )
    assert kept[0].model_status == "MODELED"


def test_prose_mention_of_a_metric_is_not_enough_to_mark_modeled() -> None:
    kept, _issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Network harder",
                description="Mentions applications_per_week in passing.",
                why_it_might_help="Access",
                why_this_fits="Hypothesis",
                next_step="Ask strangers for intros.",
                evidence_to_collect="Intros",
                model_status="MODELED",
                modeled_metric="applications_per_week",
            )
        ),
        goal=_goal(),
        question="what's a smarter path?",
        evidence_summaries=[],
        allowed_metrics={"applications_per_week"},
    )
    assert kept[0].model_status == "UNPRICED"


def test_invented_citation_strings_are_stripped() -> None:
    kept, issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Try office hours",
                description="A specific experiment.",
                why_it_might_help="Talking to people who already hire.",
                why_this_fits="Hypothesis about access.",
                next_step="Book two conversations.",
                evidence_to_collect="Conversations booked.",
                sources=["Harvard Business Review, 2019", "a blog I remember"],
            )
        ),
        goal=_goal(),
        question="what am I overlooking?",
        evidence_summaries=[],
        research_sources=["frozen:hiring.json"],
    )
    assert kept[0].sources == []
    assert any("invented sources" in item.lower() for item in issues)


def test_personal_claim_in_prose_is_qualified_not_treated_as_observed() -> None:
    kept, _issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Use the warm path",
                description="You have a former manager waiting to refer you.",
                why_it_might_help="A named referrer can open a thread.",
                why_this_fits="Your former manager already offered.",
                next_step="Send a two-sentence ask.",
                evidence_to_collect="Whether a referral was submitted.",
            )
        ),
        goal=_goal(),
        question="what's the play?",
        evidence_summaries=["Submitted 8 applications this month."],
    )
    blob = f"{kept[0].description} {kept[0].why_this_fits}".lower()
    assert "former manager waiting" not in blob
    assert any("Unverified" in item for item in kept[0].assumptions)


def test_creative_unpriced_recommendation_survives() -> None:
    kept, issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Interview buyers of the substitute product",
                description="Demand is unknown; unpaid building is not proof.",
                why_it_might_help="Switching customers reveal the job to be done.",
                why_this_fits="Authorized evidence is sparse, so this stays a hypothesis.",
                next_step="Book three conversations with buyers of a substitute this week.",
                evidence_to_collect="Interview notes and any paid commitment.",
                model_status="UNPRICED",
            )
        ),
        goal=_goal(),
        question="We have no paying users. Should I keep building features?",
        evidence_summaries=["Zero paying customers."],
    )
    assert len(kept) == 1
    assert kept[0].model_status == "UNPRICED"
    assert not any("Dropped" in item for item in issues)


def test_disclaimer_mentioning_odds_is_not_dropped() -> None:
    kept, issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Rewrite the close of every onsite",
                description="This stays unpriced; PlayItOut will not invent odds from the suggestion.",
                why_it_might_help="Final-round misses often sit in the close, not in volume.",
                why_this_fits="Fit this into your week after the next onsite.",
                next_step="After the next final round, write a one-page close review before applying more.",
                evidence_to_collect="Whether a later onsite converted.",
                model_status="UNPRICED",
            )
        ),
        goal=_goal(),
        question="I keep reaching final rounds with no offers. What should I change?",
        evidence_summaries=["Reached three final interviews with zero offers."],
    )
    assert len(kept) == 1
    assert kept[0].model_status == "UNPRICED"
    assert not any("Dropped" in item for item in issues)


def test_modeled_without_numeric_contract_is_unpriced() -> None:
    kept, issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Increase applications_per_week",
                description="Volume is a supported lever for this family.",
                why_it_might_help="The model already prices this metric.",
                why_this_fits="The question asked for a volume change.",
                next_step="Raise applications_per_week.",
                evidence_to_collect="Applications submitted.",
                model_status="MODELED",
                modeled_metric="applications_per_week",
            )
        ),
        goal=_goal(),
        question="what if I apply more?",
        evidence_summaries=[],
        allowed_metrics={"applications_per_week"},
    )
    assert kept[0].model_status == "UNPRICED"
    assert any("numeric contract" in item.lower() for item in issues)


def test_invented_probability_equation_is_dropped() -> None:
    kept, issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Secret formula",
                description="This raises your chance by 12% overnight.",
                why_it_might_help="P(offer)=0.81 after one email.",
                why_this_fits="Hypothesis",
                next_step="Send the email.",
                evidence_to_collect="An offer.",
            )
        ),
        goal=_goal(),
        question="how do I get an offer?",
        evidence_summaries=[],
    )
    assert kept == []
    assert issues


def test_unsupported_internship_claim_in_help_text_is_qualified() -> None:
    kept, _issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="Ask the intern manager",
                description="A specific path through someone who already knows the bar.",
                why_it_might_help="You interned on their team last summer.",
                why_this_fits="Hypothesis about access.",
                next_step="Send a two-sentence ask.",
                evidence_to_collect="Whether a conversation happened.",
            )
        ),
        goal=_goal(),
        question="what's the play?",
        evidence_summaries=["Submitted 8 applications this month."],
    )
    assert "interned on their team" not in kept[0].why_it_might_help.lower()
    assert any("Unverified" in item for item in kept[0].assumptions)


def test_guaranteed_causal_claim_is_rejected() -> None:
    kept, issues = validate_strategy_proposal(
        _proposal(
            StrategyInsight(
                title="This guarantees an offer",
                description="The move will definitely work.",
                why_it_might_help="It guarantees results.",
                why_this_fits="Hypothesis",
                next_step="Do it.",
                evidence_to_collect="An offer.",
            )
        ),
        goal=_goal(),
        question="how do I get an offer?",
        evidence_summaries=[],
    )
    assert kept == []
    assert issues
