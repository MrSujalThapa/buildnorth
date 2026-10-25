# ruff: noqa: E501
"""Independently conceived consumer questions. Not variants of LeetCode hours."""

from personal_markets.what_if.request_intent import classify_what_if_request

INDEPENDENT = [
    ("what's the smartest move I haven't tried yet?", "opportunity_discovery"),
    ("who could help me reach this goal faster?", "opportunity_discovery"),
    ("is there a way to leverage the people I've already met?", "opportunity_discovery"),
    ("would talking to founders be more useful than sending applications?", "compare_alternatives"),
    ("what's the highest leverage thing I could do this week?", "opportunity_discovery"),
    ("what am I overlooking?", "opportunity_discovery"),
    ("what would you do differently if you were me?", "opportunity_discovery"),
    (
        "should I spend the weekend polishing my portfolio or contacting companies?",
        "compare_alternatives",
    ),
    ("would going to a conference be worth it?", "exploratory_hypothetical"),
    ("should I pursue a smaller startup or a bigger company?", "compare_alternatives"),
    ("what if I delay my launch to focus on getting customers first?", "exploratory_hypothetical"),
    ("should I stop applying to jobs I don't really want?", "strategic_advice"),
    ("does it make sense to drop one goal to focus on another?", "strategic_advice"),
    ("what if the interview goes badly?", "exploratory_hypothetical"),
    ("what if I get an unexpected referral?", "exploratory_hypothetical"),
    ("what if my professor cancels the final?", "exploratory_hypothetical"),
    ("what if I injure myself a month before my race?", "exploratory_hypothetical"),
    ("what if my main customer churns?", "exploratory_hypothetical"),
    ("what if I lose my internship?", "exploratory_hypothetical"),
    ("why am I not making progress?", "diagnostic"),
    ("what is holding me back?", "diagnostic"),
    ("is my current strategy actually working?", "diagnostic"),
    ("why did my odds go down?", "diagnostic"),
    ("I worked harder this week, why didn't my probability change?", "diagnostic"),
    ("which of my assumptions is weakest?", "diagnostic"),
    ("what evidence would change your mind?", "diagnostic"),
    ("what do u think i should do", "strategic_advice"),
    ("am I cooked", "strategic_advice"),
    ("got rejected again what now", "strategic_advice"),
    ("lowkey should I stop applying", "strategic_advice"),
    ("is this even doable anymore", "strategic_advice"),
    ("would a referral actually help", "exploratory_hypothetical"),
    ("what's the play here", "strategic_advice"),
    ("bro what if i just take a week off", "exploratory_hypothetical"),
    ("If I focus on interview prep, what happens to my startup goal?", "strategic_advice"),
    ("Should I sacrifice gym time to study?", "compare_alternatives"),
    ("Could working on my startup improve my job prospects?", "strategic_advice"),
    ("Are these two goals competing for the same time?", "strategic_advice"),
    ("What should I prioritize this month?", "strategic_advice"),
    (
        "I pitched a VC last month. Is there anything useful I can do with that relationship?",
        "strategic_advice",
    ),
    ("I already know someone at a startup. How should that affect my strategy?", "strategic_advice"),
    ("I won a hackathon. How can I use that to get an interview?", "strategic_advice"),
    ("My former manager offered to refer me. What should I do next?", "strategic_advice"),
    ("I have a product demo but no customers. How can I get traction?", "opportunity_discovery"),
    ("I applied to 12 jobs yesterday", "evidence_report"),
    ("I had 2 interviews this week", "evidence_report"),
    ("I finished four practice sessions", "evidence_report"),
    ("I got a rejection email", "evidence_report"),
    ("I ran 8 km today", "evidence_report"),
    ("I actually saved $400 this month", "evidence_report"),
    ("I got introduced to 3 founders", "evidence_report"),
    ("do 10 instead of 2", "follow_up"),
    ("add 5 more each week", "follow_up"),
    ("do twice as many", "follow_up"),
    ("increase it by 20%", "follow_up"),
    ("what if I do that daily instead", "follow_up"),
    ("actually make it 3", "follow_up"),
    ("what if I keep that up for a month", "follow_up"),
    ("what if I apply to 10 jobs a week?", "quantitative_scenario"),
    ("what are my odds rn", "current_odds"),
    ("how could I realistically get my chances above 90%?", "reverse_planning"),
    ("I think I did around 20 applications", "evidence_report"),
    ("I might have passed", "evidence_report"),
    ("I plan to run 10 km tomorrow", "evidence_report"),
    ("I'm pretty sure I practiced more last month", "evidence_report"),
]


def test_independent_corpus_has_enough_cases() -> None:
    assert len(INDEPENDENT) >= 50


def test_independent_questions_route_to_expected_families() -> None:
    mismatches = []
    for question, expected in INDEPENDENT:
        actual = classify_what_if_request(question).kind
        if actual != expected:
            mismatches.append((question, expected, actual))
    assert mismatches == []
