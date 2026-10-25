# ruff: noqa: E501
"""Layer C: unseen strategic prompts. Scripted provider is not live intelligence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.domain import GoalContract, GoalType
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.persistence.agent_store import (
    InMemoryAgentRunStore,
    InMemoryEvidenceRepository,
)
from personal_markets.ports import EvidenceEventProposal
from personal_markets.what_if.strategy_insights import STRATEGY_KINDS

UNSEEN: list[tuple[str, str, list[str], GoalType, str]] = [
    ("Land a staff-engineer offer", "My old intern manager said they'd refer me. What now?", ["Former intern manager offered a referral for infra roles."], GoalType.DEADLINE_EVENT, "refer"),
    ("Land a staff-engineer offer", "I have no network but I shipped a distributed queue used by 40 companies. Help.", ["Open-source queue has 40 downstream companies."], GoalType.DEADLINE_EVENT, "open-source"),
    ("Ship a B2B analytics product", "We have no paying users. Should I keep building features?", ["Zero paying customers. Feature board has 18 items."], GoalType.DEADLINE_EVENT, "paying"),
    ("Ship a B2B analytics product", "Distribution is fine, people churn in week two. What should I change?", ["10k signups. Retention collapses in week two."], GoalType.DEADLINE_EVENT, "retention"),
    ("Pass organic chemistry", "Homework is 94, exams are 61. What do I actually do?", ["Homework average 94. Midterm 61."], GoalType.DEADLINE_EVENT, "exam"),
    ("Run a sub-20 5k", "Mileage is up and workouts feel worse. What's the play?", ["Ran 70 km last week. Missed two rest days. Splits got slower."], GoalType.CONTINUOUS_TARGET, "recover"),
    ("Save $40k this year", "I already skip coffee. Income is $3.1k and expenses $3.05k. Now what?", ["Monthly income 3100. Monthly expenses 3050. Coffee spend already cut."], GoalType.CONTINUOUS_TARGET, "income"),
    ("Play Wonderwall all the way through", "I've practiced 20 minutes a day for months and still stall at the bridge.", ["Daily 20-minute practice for 4 months. Bridge still breaks."], GoalType.THRESHOLD, "bar"),
    ("Get into a research lab", "I cold-emailed 12 profs. Silence. Smarter than another blast?", ["12 unanswered faculty emails."], GoalType.DEADLINE_EVENT, "email"),
    ("Close a seed round", "A partner said 'keep in touch' after demo day. Is that useful?", ["Demo-day partner said keep in touch. No term sheet."], GoalType.DEADLINE_EVENT, "partner"),
    ("Switch into product design", "I have a CS job. Weekend case studies or informational chats?", ["Employed as backend engineer. Three unfinished case studies."], GoalType.DEADLINE_EVENT, "case"),
    ("Publish a paper", "Advisor is slow and conference deadline is in 19 days. What should I prioritize?", ["Advisor review pending 6 weeks. Conference deadline in 19 days."], GoalType.DEADLINE_EVENT, "deadline"),
    ("Quit smoking", "I keep failing week two. Don't tell me to try harder.", ["Relapsed on day 12 twice. Stress at work named as trigger."], GoalType.THRESHOLD, "week"),
    ("Get a theatre callback", "I book first rounds then freeze in callbacks.", ["Four first-round bookings. Zero callbacks converted."], GoalType.DEADLINE_EVENT, "callback"),
    ("Learn Mandarin enough for a trip", "Anki streak is 200 and I still can't order food.", ["Anki streak 200. Cannot complete a restaurant order."], GoalType.THRESHOLD, "order"),
    ("Hire first engineer", "Candidates ghost after the take-home. What now?", ["8 take-homes sent. 7 unanswered."], GoalType.DEADLINE_EVENT, "take-home"),
    ("Defend my thesis", "Committee wants more experiments and my funding ends in 8 weeks.", ["Funding ends in 8 weeks. Committee asked for more experiments."], GoalType.DEADLINE_EVENT, "funding"),
    ("Keep a weekly writing habit", "I have 40 drafts and zero published posts.", ["40 drafts. Zero published posts."], GoalType.THRESHOLD, "publish"),
    ("Get off academic probation", "I understand lectures and bomb the timed quizzes.", ["Lecture notes complete. Timed quiz average 54."], GoalType.DEADLINE_EVENT, "quiz"),
    ("Find a co-founder", "I posted on Twitter. Crickets. Other ideas?", ["One Twitter hiring post. No replies."], GoalType.DEADLINE_EVENT, "twitter"),
    ("Reduce anxiety before talks", "I over-rehearse and still blank the opener.", ["Rehearsed 12 times. Blanked the opener at the last meetup."], GoalType.THRESHOLD, "opener"),
    ("Get a visa appointment", "Slots vanish in seconds. I have a lawyer friend. Use them?", ["Lawyer friend offered to look at the packet. No appointment yet."], GoalType.DEADLINE_EVENT, "lawyer"),
    ("Rebuild after a layoff", "Severance is 8 weeks. I want a better role not a panic apply-fest.", ["Laid off. 8 weeks of severance remaining."], GoalType.DEADLINE_EVENT, "severance"),
    ("Launch on Product Hunt", "I could delay two weeks for polish or ship broken. Thoughts?", ["Landing page is live. Onboarding still drops 70%."], GoalType.DEADLINE_EVENT, "ship"),
    ("Get my band a first paid gig", "We practice a lot and have never asked a venue.", ["Weekly rehearsals. Zero venue emails."], GoalType.DEADLINE_EVENT, "venue"),
    ("Finish a novel draft", "I rewrite chapter one every weekend.", ["Chapter one rewritten 11 times. Later chapters untouched."], GoalType.THRESHOLD, "chapter"),
    ("Pass the bar exam", "Practice scores are high in torts and terrible in civ pro. Hours left: 12/week.", ["Torts practice 80. Civ pro 48. Twelve hours a week available."], GoalType.DEADLINE_EVENT, "civ"),
    ("Get a design internship", "Portfolio is 3 case studies nobody has seen.", ["Three case studies unpublished. No informational chats logged."], GoalType.DEADLINE_EVENT, "portfolio"),
    ("Stop overtraining", "I added miles after a bad race. Legs feel dead. Not asking for a diagnosis.", ["Added 20 km after a slow race. Two missed recoveries."], GoalType.CONTINUOUS_TARGET, "dead"),
    ("Make the side project pay rent", "Friends like it. Strangers will not pay. What experiment?", ["12 friend users. Zero stranger payments."], GoalType.DEADLINE_EVENT, "stranger"),
    ("I dunno maybe something with intros?", "kinda stuck lol", [], GoalType.DEADLINE_EVENT, "clarify"),
]


def _goal(title: str, goal_type: GoalType) -> GoalContract:
    return GoalContract(
        goal_id=uuid4(),
        title=title,
        goal_type=goal_type,
        success_definition={"metric": "success"},
        deadline=datetime.now(UTC) + timedelta(days=120),
        state_dimensions=["progress"],
    )


async def _service(goal: GoalContract, summaries: list[str]) -> InterventionAgentService:
    repo = InMemoryGoalRepository()
    user_id = uuid4()
    await repo.create(goal, user_id)
    evidence = EvidenceService(InMemoryEvidenceRepository({goal.goal_id: True}))
    for summary in summaries:
        await evidence.commit(
            user_id,
            goal.goal_id,
            [
                EvidenceEventProposal.model_validate(
                    {
                        "source_type": "manual",
                        "event_type": "observation",
                        "domain": "user_state",
                        "metric": "manual_note",
                        "categorical_value": summary,
                        "observed_at": datetime.now(UTC).isoformat(),
                        "summary": summary,
                    }
                )
            ],
            None,
            [],
        )
    return InterventionAgentService(
        settings=Settings(environment="test", intervention_agent_enabled=True),
        inference=ScriptedInferenceProvider(),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(), MonidResearchProvider(False, None, None)
        ),
        goals=GoalService(repo),
        evidence=evidence,
        run_store=InMemoryAgentRunStore(),
    )


def test_unseen_eval_has_thirty_cases() -> None:
    assert len(UNSEEN) >= 30


@pytest.mark.asyncio
async def test_unseen_prompts_stay_grounded_and_question_specific() -> None:
    generic_hits = 0
    hallucinations = 0
    numeric_claims = 0
    titles: list[str] = []
    for title, question, evidence, goal_type, _tag in UNSEEN:
        goal = _goal(title, goal_type)
        parsed = await (await _service(goal, evidence)).parse(str(goal.goal_id), question)
        if parsed.request_kind not in STRATEGY_KINDS:
            # Incomplete jokes should ask for information rather than invent a plan.
            assert parsed.insights == []
            continue
        assert parsed.insights, question
        blob = " ".join(
            [
                parsed.insights[0].title,
                parsed.insights[0].description,
                parsed.insights[0].why_this_fits,
                parsed.insights[0].next_step,
            ]
        ).lower()
        titles.append(parsed.insights[0].title)
        if "generic career" in blob or "apply to 10 jobs" in blob:
            generic_hits += 1
        if "cousin at google" in blob or (
            "seed vc" in blob and "vc" not in " ".join(evidence).lower()
        ):
            hallucinations += 1
        if any(token in blob for token in ("percentage point", "probability +", "odds to")):
            numeric_claims += 1
        if evidence:
            # At least one evidence token should appear, or the fit line should admit sparsity.
            tokens = [word for word in evidence[0].lower().split() if len(word) > 4][:3]
            grounded = any(token in blob for token in tokens) or "not recorded" in blob or "sparse" in blob or "hypothesis" in blob
            assert grounded, (question, blob)
        assert parsed.insights[0].model_status != "MODELED" or "applications" in blob
    assert generic_hits == 0
    assert hallucinations == 0
    assert numeric_claims == 0
    assert len(set(titles)) >= 12


@pytest.mark.asyncio
async def test_similar_language_across_goals_is_not_a_single_template() -> None:
    question = "What's the highest-leverage next move?"
    career_goal = _goal("Land an FDE offer", GoalType.DEADLINE_EVENT)
    guitar_goal = _goal("Play a full song", GoalType.THRESHOLD)
    career = await (await _service(
        career_goal, ["Submitted 50 applications. Zero interviews."]
    )).parse(str(career_goal.goal_id), question)
    guitar = await (await _service(
        guitar_goal, ["Practiced 20 minutes daily. Still cannot play the chorus."]
    )).parse(str(guitar_goal.goal_id), question)
    assert career.insights[0].title != guitar.insights[0].title
