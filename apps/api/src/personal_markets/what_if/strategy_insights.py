# ruff: noqa: E501
"""Grounded, unpriced strategy suggestions. Never invents probability effects."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

from personal_markets.goals.domain import GoalContract
from personal_markets.what_if.intervention_registry import goal_domain

ModelStatus = Literal["MODELED", "UNPRICED", "NEEDS_DATA"]


class StrategyInsight(BaseModel):
    title: str
    description: str
    why_it_might_help: str
    why_this_fits: str
    next_step: str
    evidence_to_collect: str
    model_status: ModelStatus = "UNPRICED"
    grounded_facts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


def _blob(parts: Iterable[str]) -> str:
    return " ".join(part.strip().lower() for part in parts if part.strip())


def _facts_from_text(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    checks = (
        ("vc", r"\b(vc|venture capitalist|investor|partner at)\b"),
        ("founder", r"\b(founder|portfolio compan(?:y|ies))\b"),
        ("manager", r"\b(former manager|ex[- ]manager|my manager|offered to refer)\b"),
        ("demo", r"\b(demo|prototype|hackathon|proof of work|portfolio)\b"),
        ("customer", r"\b(customer|paying user|churn)\b"),
        ("professor", r"\b(professor|office hours|midterm|exam)\b"),
        ("coach", r"\b(coach|running club|pt\b|physical therapist)\b"),
        ("employer_match", r"\b(401k|employer match|rsu)\b"),
    )
    for key, pattern in checks:
        match = re.search(pattern, text, re.I)
        if match:
            found[key] = match.group(0)
    return found


def compose_strategy_insights(
    goal: GoalContract,
    *,
    question: str,
    evidence_summaries: list[str] | None = None,
    research_claims: list[str] | None = None,
) -> list[StrategyInsight]:
    """Return at most three suggestions. Private facts appear only if evidence contains them."""

    authorized = _blob([goal.title, *(evidence_summaries or [])])
    facts = _facts_from_text(authorized)
    domain = goal_domain(goal)
    sources = [claim for claim in (research_claims or []) if claim.strip()][:4]
    insights: list[StrategyInsight] = []

    if domain == "career":
        if "vc" in facts:
            insights.append(
                StrategyInsight(
                    title="Ask that investor for a few targeted introductions",
                    description=(
                        "You already have a relationship with someone who sits next to hiring founders. "
                        "A warm introduction to a portfolio company beats another round of cold applications."
                    ),
                    why_it_might_help=(
                        "Founders take intros from investors they already trust. That path reaches a "
                        "decision-maker without pretending the model has a calibrated referral coefficient."
                    ),
                    why_this_fits=f"Authorized context mentions {facts['vc']}.",
                    next_step=(
                        "Write a three-sentence ask: the roles you want, two portfolio companies that "
                        "fit, and one artifact they can forward."
                    ),
                    evidence_to_collect="Record introductions, conversations, and any resulting interviews—not a guessed odds boost.",
                    grounded_facts=[facts["vc"]],
                    sources=sources,
                )
            )
        else:
            insights.append(
                StrategyInsight(
                    title="Use existing relationships before more cold volume",
                    description=(
                        "If you have already pitched an investor, professor, or founder, that person may "
                        "be a better distribution channel than another dozen applications."
                    ),
                    why_it_might_help="Warm paths compress time-to-conversation when they exist.",
                    why_this_fits="No authorized evidence names a specific contact, so this stays conditional.",
                    next_step="List people who have already seen your work. If none, say so and we stay on modeled application volume.",
                    evidence_to_collect="Names/roles of people who could intro you, plus any reply.",
                    assumptions=[
                        "You may have unused professional relationships; that is not assumed as fact."
                    ],
                    sources=sources,
                )
            )
        if "demo" in facts:
            insights.append(
                StrategyInsight(
                    title="Turn the existing demo into a hiring artifact",
                    description="A working project is evidence of execution. Send it to a specific team with a note about their current problem, not as a generic portfolio link.",
                    why_it_might_help="Proof-of-work lets a hiring manager skip resume theater.",
                    why_this_fits=f"Authorized context mentions {facts['demo']}.",
                    next_step="Pick one team whose product overlaps the demo and send a 6-sentence note plus a 2-minute walkthrough.",
                    evidence_to_collect="Replies, screens, and interviews that follow from that send.",
                    grounded_facts=[facts["demo"]],
                    sources=sources,
                )
            )
        else:
            insights.append(
                StrategyInsight(
                    title="Target teams whose current problem matches work you can show",
                    description="Volume helps only after the packet is specific. One tailored proof-of-work note can outperform a generic blast.",
                    why_it_might_help="Relevance raises interview conversion; the numerical model only prices application count when you state a weekly rate.",
                    why_this_fits="No demo is on file, so this is a packet-quality suggestion rather than a claimed conversion rate.",
                    next_step="Choose one company and write what operational problem you would attack in the first 30 days.",
                    evidence_to_collect="That note, and whether it produced a conversation.",
                    assumptions=["You can point to some piece of real work."],
                    sources=sources,
                )
            )
        insights.append(
            StrategyInsight(
                title="Keep a measured application cadence only where it is the bottleneck",
                description="If you already have conversations queued, more applications are not automatically the highest-leverage move.",
                why_it_might_help="The hiring model can price weekly applications when you state a number. Other moves stay unpriced.",
                why_this_fits="Career goals in this app have an applications-per-week lever; use it when volume is actually the constraint.",
                next_step="If volume is the constraint, state a weekly application rate. If conversations exist, convert those first.",
                evidence_to_collect="Weekly application counts, screens, and offers—kept as evidence, not What If guesses.",
                model_status="NEEDS_DATA",
                sources=sources,
            )
        )
    elif domain == "startup":
        if "customer" in facts:
            insights.append(
                StrategyInsight(
                    title="Interview people who already pay for the competing solution",
                    description="Switching customers reveal the job-to-be-done more honestly than another month of features.",
                    why_it_might_help="Distribution and willingness-to-pay show up in those conversations before the model can price them.",
                    why_this_fits=f"Authorized context mentions {facts['customer']}.",
                    next_step="Ask three current buyers of the substitute why they stay, and what would make them move.",
                    evidence_to_collect="Interview notes and any paid commitment. Do not map this to an invented conversion probability.",
                    grounded_facts=[facts["customer"]],
                    sources=sources,
                )
            )
        insights.append(
            StrategyInsight(
                title="Find a distribution partner who already talks to your buyer",
                description="An established provider serving the same buyer can move faster than building another feature.",
                why_it_might_help="Access compounds; features do not automatically create demand.",
                why_this_fits="Startup goals here do not have a calibrated partner-effect coefficient, so this stays qualitative.",
                next_step="Name two firms whose customer list overlaps yours and draft a one-page co-sell or embed offer.",
                evidence_to_collect="Meetings booked and any shared pipeline, not a guessed odds change.",
                assumptions=["A plausible partner exists in the category."]
                if "customer" not in facts
                else [],
                sources=sources,
            )
        )
        insights.append(
            StrategyInsight(
                title="Use existing relationships as the first acquisition channel",
                description="People who already trust you are a cheaper test of messaging than ads or cold volume.",
                why_it_might_help="You learn whether anyone will pay before you scale outreach.",
                why_this_fits="No numeric acquisition model is attached unless a modeled rate is stated.",
                next_step="List ten people who already know the problem and ask for a paid pilot, not feedback.",
                evidence_to_collect="Pilot yes/no and revenue, recorded as evidence.",
                sources=sources,
            )
        )
    elif domain == "running":
        insights.append(
            StrategyInsight(
                title="Check recovery and consistency before adding sessions",
                description="Missed sessions and poor recovery often dominate extra mileage.",
                why_it_might_help="A training suggestion is not a calibrated race-time effect in this model.",
                why_this_fits="Fitness goals here do not silently convert kilometres into probability points.",
                next_step="Write down sessions completed versus planned for the last two weeks.",
                evidence_to_collect="Completed sessions, distance, and how you felt—without inventing a finish-time delta.",
                sources=sources,
            )
        )
        if "coach" in facts:
            insights.append(
                StrategyInsight(
                    title="Use the existing coach or club for accountability, not extra hero workouts",
                    description="Someone already in the loop can catch the real bottleneck.",
                    why_it_might_help="Accountability raises completion more reliably than an unmeasured intensity spike.",
                    why_this_fits=f"Authorized context mentions {facts['coach']}.",
                    next_step="Ask them which session you should protect this week if you can only keep one.",
                    evidence_to_collect="Adherence to that protected session.",
                    grounded_facts=[facts["coach"]],
                    sources=sources,
                )
            )
    elif domain == "finance":
        insights.append(
            StrategyInsight(
                title="Inspect fixed costs and employer matching before tightening discretionary spend",
                description="Structural cash flows usually dwarf a slightly stricter weekly budget.",
                why_it_might_help="The wealth model prices contribution flow when you state a monthly amount; matching and rent are strategy until measured.",
                why_this_fits="Finance goals expose a contribution lever, not an automatic lifestyle multiplier.",
                next_step="List recurring bills and any employer match you are leaving on the table.",
                evidence_to_collect="Match captured and recurring bills changed, then a stated monthly contribution if you want it priced.",
                sources=sources,
            )
        )
    else:
        insights.append(
            StrategyInsight(
                title="Change the environment that makes the habit fail",
                description="Missed practice is often access, scheduling, or friction—not effort slogans.",
                why_it_might_help="A bottleneck you can remove is higher leverage than 'try harder', and it stays unpriced until a modeled metric exists.",
                why_this_fits=f"Goal: {goal.title}.",
                next_step="Name the last two times you skipped and what made skipping easier than doing it.",
                evidence_to_collect="Completed sessions with dates, not intentions.",
                sources=sources,
            )
        )

    if "professor" in facts:
        insights.insert(
            0,
            StrategyInsight(
                title="Take targeted office-hours questions from graded mistakes",
                description="Hours of undifferentiated study are weaker than questions built from what you already missed.",
                why_it_might_help="Remaining assessments with the largest weight move the outcome more than extra generic hours.",
                why_this_fits=f"Authorized context mentions {facts['professor']}.",
                next_step="Bring one graded error and one syllabus item whose weight you still do not understand.",
                evidence_to_collect="Scores on remaining assessments. Hypothetical scores are not evidence.",
                grounded_facts=[facts["professor"]],
                sources=sources,
            ),
        )

    # Keep a short list. Never pad with generic résumé advice.
    unique: list[StrategyInsight] = []
    seen: set[str] = set()
    for item in insights:
        if item.title in seen:
            continue
        seen.add(item.title)
        unique.append(item)
        if len(unique) == 3:
            break
    return unique


def consumer_summary(
    *,
    kind: str,
    published_odds: float | None,
    comparison_odds: float | None,
    scenario_odds: float | None,
    improvement_pp: float | None,
    question: str,
) -> str:
    asked = question.strip() or "this change"
    if kind == "current_odds":
        if published_odds is None:
            return "There is no published forecast to report yet."
        return (
            f"Your latest published odds are {published_odds:.2f}%. "
            "That is the market number, not a What If scenario."
        )
    if kind == "evidence_report":
        return (
            f"That sounds like something that already happened, not a hypothetical. "
            f"Confirm the date and metric if you want it stored as evidence for “{asked}”."
        )
    if scenario_odds is None:
        return (
            "This is a strategy question. PlayItOut can reason about the idea without inventing "
            "a probability change."
        )
    published = f"{published_odds:.0f}%" if published_odds is not None else "unpublished"
    baseline = f"{comparison_odds:.0f}%" if comparison_odds is not None else "—"
    scenario = f"{scenario_odds:.0f}%"
    delta = (
        f"{improvement_pp:+.1f} percentage points"
        if improvement_pp is not None
        else "an unquantified shift"
    )
    return (
        f"You currently have published odds of {published}. Under the model's latest recalculated "
        f"assumptions, “{asked}” changes the comparison from {baseline} to {scenario}, {delta}. "
        "This is a modeled scenario, not a new published forecast."
    )
