# ruff: noqa: E501
import re
from collections.abc import Callable
from typing import Any

from personal_markets.core.errors import (
    PermanentProviderError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.ports import InferenceRequest, InferenceResponse

ScriptFn = Callable[[InferenceRequest], dict[str, Any]]


class ScriptedInferenceProvider:
    """Deterministic provider for tests and local agent evaluation. Never invents probabilities."""

    def __init__(self, script: ScriptFn | None = None) -> None:
        self._script = script or default_agent_script
        self.calls: list[InferenceRequest] = []

    async def complete_text(self, request: InferenceRequest) -> InferenceResponse:
        import json

        response = await self.complete_structured(request)
        response.text = json.dumps(response.structured_output)
        return response

    async def complete_tools(self, request: InferenceRequest) -> InferenceResponse:
        raise SemanticProviderError("Scripted tool calls must be explicitly configured by a test")

    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        self.calls.append(request)
        output = self._script(request)
        if request.agent_name == "evidence":
            from personal_markets.evidence.metrics import observation_kind

            for event in output.get("events", []):
                # Test fixture migration only. Runtime adapters require semantic extraction.
                event.setdefault("observation_kind", observation_kind(
                    event.get("metric", ""), event.get("event_type", "")))
        return InferenceResponse(
            structured_output=output,
            provider="scripted",
            model=request.model or "scripted",
            usage={"input_tokens": 1, "output_tokens": 1},
            request_id=f"scripted-{len(self.calls)}",
            retries=0,
            latency_ms=1,
        )


class FailingInferenceProvider:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        del request
        raise self._error

    async def complete_text(self, request: InferenceRequest) -> InferenceResponse:
        raise self._error

    async def complete_tools(self, request: InferenceRequest) -> InferenceResponse:
        raise self._error


def default_agent_script(request: InferenceRequest) -> dict[str, Any]:
    agent = request.agent_name
    payload = request.input
    if agent == "goal_architect":
        return _architect(payload)
    if agent == "evidence":
        return _evidence(payload)
    if agent == "research":
        if "recommended" in request.output_schema.get("properties", {}):
            return _source_planner(payload)
        return _research(payload)
    if agent == "critic":
        return _critic(payload)
    if agent == "intervention":
        return _intervention(payload)
    if agent == "strategy":
        return _strategy(payload)
    if agent == "source_planner":
        return _source_planner(payload)
    raise SemanticProviderError(f"unsupported scripted agent {agent}")


def _text(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("intent") or ""),
        str(payload.get("evidence_text") or ""),
        " ".join(str(value) for value in (payload.get("user_answers") or {}).values()),
        " ".join(str(item) for item in (payload.get("previous_validation_errors") or [])),
    ]
    return " ".join(parts).lower()


def _clarify(title: str, questions: list[dict[str, str]], *, goal_type: str = "deadline_event") -> dict[str, Any]:
    return {
        "ready_to_commit": False,
        "title": title,
        "goal_type": goal_type,
        "success_metric": "unspecified",
        "success_operator": ">=",
        "success_target": "unspecified",
        "deadline": "2099-01-01",
        "state_dimensions": ["unspecified"],
        "hours_per_week": None,
        "model_family_compatibility": "none",
        "clarifications_required": questions,
        "notes": "Intent is underspecified.",
    }


def _waterloo_is_specific(text: str) -> bool:
    """Commit-ready Waterloo intents name a program and a cycle/deadline."""
    has_program = any(
        token in text
        for token in (
            "mechatronics",
            "software engineering",
            "computer engineering",
            "engineering for fall",
            "engineering admission for",
        )
    )
    has_deadline = any(token in text for token in ("2026", "2027", "2028", "2029", "fall 20"))
    return has_program and has_deadline


def _architect(payload: dict[str, Any]) -> dict[str, Any]:
    text = _text(payload)
    answers = payload.get("user_answers") or {}
    if "impossible" in text or "yesterday" in text:
        return _clarify(
            "Invalid request",
            [
                {
                    "id": "valid_outcome",
                    "question": "What measurable future outcome should be tracked?",
                    "why_needed": "The request is malformed or already in the past.",
                }
            ],
        )
    vague_markers = (
        "somehow",
        "get a job.",
        "be successful",
        "asdf",
        "advance my career",
        "get more users soon",
        "make my startup successful",
        "build better habits",
        "do better in school",
        "get faster at running",
        "be more fit soon",
        "improve my finances",
        "save more and also",
        "invest better",
        "get promoted somehow",
        "get certified soon",
        "race better somehow",
        "get out of debt somehow",
        "grow my newsletter somehow",
        "get better at piano somehow",
    )
    if any(marker in text for marker in vague_markers) and not answers:
        return _clarify(
            "Needs clarification",
            [
                {
                    "id": "success_metric",
                    "question": "What measurable success metric and target should count as success?",
                    "why_needed": "The intent lacks a concrete, forecastable outcome.",
                },
                {
                    "id": "deadline",
                    "question": "By what date should this be achieved?",
                    "why_needed": "A forecastable goal needs a deadline.",
                },
            ],
        )
    if "rich" in text and not answers:
        return _clarify(
            "Needs clarification",
            [
                {
                    "id": "rich_definition",
                    "question": "What does rich mean — net worth or income, and what amount?",
                    "why_needed": "The success metric is undefined.",
                },
                {
                    "id": "deadline",
                    "question": "By what date should this be achieved?",
                    "why_needed": "A forecastable goal needs a deadline.",
                },
            ],
            goal_type="continuous_target",
        )
    if "waterloo" in text and not answers and not _waterloo_is_specific(text):
        return _clarify(
            "Needs clarification",
            [
                {
                    "id": "program",
                    "question": "Which Waterloo program counts as success?",
                    "why_needed": "Admission rules differ by program.",
                },
                {
                    "id": "deadline",
                    "question": "What application cycle or decision date should be used?",
                    "why_needed": "A deadline is required.",
                },
            ],
        )
    if "rich" in text and answers:
        amount = str(answers.get("rich_definition") or answers.get("amount") or "1000000")
        deadline = str(answers.get("deadline") or "2035-12-31")
        return {
            "ready_to_commit": True,
            "title": "Reach a defined net worth",
            "goal_type": "continuous_target",
            "success_metric": "net_worth_usd",
            "success_operator": ">=",
            "success_target": amount,
            "deadline": deadline[:10],
            "state_dimensions": ["net_worth_usd", "savings_rate"],
            "hours_per_week": None,
            "model_family_compatibility": "anchored_finance",
            "clarifications_required": [],
            "notes": "Formalized after clarification.",
        }
    if "waterloo" in text and answers:
        program = str(answers.get("program") or "Mechatronics Engineering")
        deadline = str(answers.get("deadline") or "2028-05-31")
        return {
            "ready_to_commit": True,
            "title": f"Receive Waterloo {program} admission",
            "goal_type": "deadline_event",
            "success_metric": "admission_offer",
            "success_operator": "==",
            "success_target": f"University of Waterloo:{program}",
            "deadline": deadline[:10],
            "state_dimensions": ["academic_performance", "application_status"],
            "hours_per_week": None,
            "model_family_compatibility": "exploratory_admissions",
            "clarifications_required": [],
            "notes": "Formalized after clarification.",
        }
    if "waterloo" in text and _waterloo_is_specific(text):
        return {
            "ready_to_commit": True,
            "title": "Receive Waterloo program admission",
            "goal_type": "deadline_event",
            "success_metric": "admission_offer",
            "success_operator": "==",
            "success_target": "University of Waterloo:specified_program",
            "deadline": "2027-09-01",
            "state_dimensions": ["academic_performance", "application_status"],
            "hours_per_week": None,
            "model_family_compatibility": "exploratory_admissions",
            "clarifications_required": [],
            "notes": "Measurable admissions goal.",
        }
    deadline = "2027-08-31"
    return {
        "ready_to_commit": True,
        "title": "Receive an SWE/FDE offer from a target company",
        "goal_type": "deadline_event",
        "success_metric": "offer_received",
        "success_operator": "==",
        "success_target": "swe_or_fde_offer",
        "deadline": deadline,
        "state_dimensions": ["interview_outcomes", "practice_volume", "applications_submitted"],
        "hours_per_week": 10,
        "model_family_compatibility": "exploratory_hiring",
        "clarifications_required": [],
        "notes": "Measurable hiring goal.",
    }


def _evidence(payload: dict[str, Any]) -> dict[str, Any]:
    text = _text(payload)
    events: list[dict[str, Any]] = []
    ambiguities: list[dict[str, str]] = []
    conflicts: list[str] = []
    for record in payload.get("mcp_records") or []:
        if not isinstance(record, dict):
            continue
        body = record.get("payload") or record
        nested = body.get("events") if isinstance(body, dict) else None
        if isinstance(nested, list) and nested:
            for item in nested:
                if isinstance(item, dict):
                    events.append({**item, "source_type": "mcp_sync"})
            continue
        events.append(
            {
                "event_type": "observation",
                "domain": "external",
                "metric": "external_event",
                "categorical_value": str(body.get("summary") or "synced observation")[:120],
                "observed_at": body.get("observed_at") or "unknown",
                "source_type": "mcp_sync",
                "summary": str(body.get("summary") or "Synced provider observation")[:200],
            }
        )

    def add(
        event_type: str,
        domain: str,
        metric: str,
        summary: str,
        *,
        numeric_value: float | None = None,
        categorical_value: str | None = None,
        unit: str | None = None,
        source_type: str = "manual",
    ) -> None:
        events.append(
            {
                "event_type": event_type,
                "domain": domain,
                "metric": metric,
                "numeric_value": numeric_value,
                "categorical_value": categorical_value,
                "unit": unit,
                "observed_at": "unknown",
                "source_type": source_type,
                "summary": summary,
            }
        )

    if "leetcode" in text:
        add(
            "practice",
            "software",
            "leetcode_medium_count",
            "LeetCode medium problems solved",
            numeric_value=14 if "14" in text else 4,
            unit="count",
        )
    if "phone screen" in text or "phonescreen" in text:
        add(
            "interview",
            "career",
            "phone_screen_result",
            "Phone screen unsuccessful",
            categorical_value="unsuccessful",
        )
    if "online assessment" in text or " oa " in f" {text} ":
        add(
            "interview",
            "career",
            "online_assessment_result",
            "Online assessment result",
            categorical_value="unsuccessful" if "fail" in text else "completed",
        )
    if "97" in text and "physics" in text:
        add(
            "assessment",
            "academic",
            "physics_score",
            "Physics test score 97",
            numeric_value=0.97,
            unit="fraction",
        )
    if "61" in text and ("calc" in text or "calculus" in text):
        add(
            "assessment",
            "academic",
            "calculus_score",
            "Calculus score 61",
            numeric_value=0.61,
            unit="fraction",
        )
    if ("github" in text and "commit" in text) or ("pushed" in text and "commit" in text):
        add(
            "repository_activity",
            "software",
            "commits_pushed",
            "GitHub commits observed",
            numeric_value=10 if "10" in text else (3 if "3" in text else 1),
            unit="count",
            source_type="github",
        )
    if "pull request" in text or "merged pull" in text:
        add(
            "repository_activity",
            "software",
            "pull_request_merged",
            "Pull request merged",
            numeric_value=1,
            unit="count",
            source_type="github",
        )
    # Count repeated run clauses for duplicate-noise style inputs.
    run_hits = text.count("ran ") + text.count("tempo run") + text.count("long run")
    if run_hits == 0 and (" km" in text or "km " in text or "miles" in text) and (
        "run" in text or "ran" in text
    ):
        run_hits = 1
    for idx in range(max(run_hits, 0)):
        add(
            "workout",
            "running",
            "distance_km",
            f"Running distance observation {idx + 1}",
            numeric_value=8.0,
            unit="km",
        )
    if "mock interview" in text:
        add(
            "practice",
            "career",
            "mock_interviews",
            "Mock interviews completed",
            numeric_value=2 if "2" in text else 1,
            unit="count",
        )
    if "application" in text and ("sent" in text or "job" in text):
        add(
            "practice",
            "career",
            "applications_submitted",
            "Job applications submitted",
            numeric_value=12 if "12" in text else 1,
            unit="count",
        )
    if "linkedin" in text:
        add(
            "practice",
            "career",
            "linkedin_posts",
            "LinkedIn posts published",
            numeric_value=3 if "3" in text else 1,
            unit="count",
        )
    if "rest day" in text or "no workout" in text:
        add(
            "recovery",
            "running",
            "rest_day",
            "Rest day observed",
            categorical_value="rest",
        )
    if "slept" in text or ("sleep" in text and "hour" in text):
        add(
            "recovery",
            "habits",
            "sleep_hours",
            "Sleep duration logged",
            numeric_value=7.5 if "7.5" in text else 7.0,
            unit="hours",
        )
    if "rent" in text and ("paid" in text or "$" in text):
        add(
            "finance",
            "finance",
            "rent_payment_usd",
            "Rent payment recorded",
            numeric_value=1850.0 if "1850" in text else 500.0,
            unit="usd",
        )
    if "paycheck" in text or "deposit" in text:
        add(
            "finance",
            "finance",
            "income_deposit_usd",
            "Income deposit recorded",
            numeric_value=3200.0 if "3200" in text else 1.0,
            unit="usd",
        )
    if "contribution" in text or "contributed" in text or "brokerage" in text or "savings" in text:
        if "ran" in text or "km" in text:
            add(
                "finance",
                "finance",
                "contribution_usd",
                "Savings contribution recorded",
                numeric_value=500.0 if "500" in text else 1200.0,
                unit="usd",
            )
        elif not any(item["metric"] == "contribution_usd" for item in events):
            add(
                "finance",
                "finance",
                "contribution_usd",
                "Savings contribution recorded",
                numeric_value=1200.0 if "1200" in text else 500.0,
                unit="usd",
            )
    if "gpa" in text:
        add(
            "assessment",
            "academic",
            "gpa",
            "GPA observation",
            numeric_value=3.42 if "3.42" in text else 3.0,
            unit="gpa",
        )
    if "essay" in text:
        add(
            "practice",
            "academic",
            "essay_draft",
            "Essay draft progress",
            categorical_value="draft",
        )
    if "mrr" in text:
        add(
            "finance",
            "startup",
            "mrr_usd",
            "MRR observation",
            numeric_value=4200.0 if "4200" in text else 1.0,
            unit="usd",
        )
    if "user interview" in text:
        add(
            "practice",
            "startup",
            "user_interviews",
            "User interviews completed",
            numeric_value=8 if "8" in text else 1,
            unit="count",
        )
    if "read for" in text or "reading" in text:
        add(
            "habit",
            "habits",
            "reading_minutes",
            "Reading session",
            numeric_value=35.0 if "35" in text else 30.0,
            unit="minutes",
        )
    if "meditat" in text:
        add(
            "habit",
            "habits",
            "meditation_minutes",
            "Meditation session",
            numeric_value=20.0 if "20" in text else 10.0,
            unit="minutes",
        )
    if "gym" in text:
        add(
            "workout",
            "habits",
            "gym_session_minutes",
            "Gym session",
            numeric_value=55.0 if "55" in text else 45.0,
            unit="minutes",
        )
    if "waterloo application" in text or "submitted my waterloo" in text:
        add(
            "application",
            "academic",
            "application_submitted",
            "Admissions application submitted",
            categorical_value="submitted",
        )
    if "maybe" in text or "kind of" in text or "i guess" in text:
        ambiguities.append(
            {
                "id": "ambiguous_evidence",
                "question": "What exact observation should be recorded?",
                "why_needed": "The statement is too vague to normalize.",
            }
        )
        # Ambiguous inputs should not keep guessed events.
        events.clear()
    if "passed" in text and "failed" in text and "same" in text:
        conflicts.append("Conflicting outcomes for the same assessment.")
    if not events and not ambiguities:
        events.append(
            {
                "event_type": "note",
                "domain": "general",
                "metric": "manual_note",
                "numeric_value": None,
                "categorical_value": text[:120] or "note",
                "unit": None,
                "observed_at": "unknown",
                "source_type": "manual",
                "summary": (payload.get("evidence_text") or "manual evidence")[:200],
            }
        )
    return {"events": events, "ambiguities": ambiguities, "conflicts": conflicts}


def _research(payload: dict[str, Any]) -> dict[str, Any]:
    snippets = payload.get("snippets") or []
    claims = []
    for snippet in snippets:
        claims.append(
            {
                "claim": snippet.get("text", "")[:400],
                "source": snippet.get("source", "frozen"),
                "retrieved_at": snippet.get("retrieved_at", "2026-08-29T00:00:00+00:00"),
                "source_type": snippet.get("source_type", "frozen"),
                "evidence_class": snippet.get("evidence_class", "reference_rule"),
            }
        )
    return {
        "claims": claims,
        "reference_class_candidates": payload.get("reference_class_candidates") or [],
        "limitations": payload.get("limitations") or ["Research used frozen artifacts only."],
    }


def _insight(
    *,
    title: str,
    description: str,
    why_it_might_help: str,
    why_this_fits: str,
    next_step: str,
    evidence_to_collect: str,
    constraints: str = "Costs time that cannot be spent on other work this week.",
    grounded_facts: list[str] | None = None,
    assumptions: list[str] | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "why_it_might_help": why_it_might_help,
        "why_this_fits": why_this_fits,
        "next_step": next_step,
        "evidence_to_collect": evidence_to_collect,
        "constraints": constraints,
        "model_status": "UNPRICED",
        "grounded_facts": grounded_facts or [],
        "assumptions": assumptions or [],
        "sources": sources or [],
    }


def _strategy(payload: dict[str, Any]) -> dict[str, Any]:
    """Test double: vary with the actual question and authorized evidence, not domain templates."""

    question = str(payload.get("question") or payload.get("intervention_text") or "").strip()
    evidence = [str(item) for item in (payload.get("authorized_evidence_summaries") or []) if str(item).strip()]
    raw_goal = payload.get("goal")
    goal: dict[str, Any] = raw_goal if isinstance(raw_goal, dict) else {}
    title = str(goal.get("title") or "this goal")
    q = question.lower()
    ev = " ".join(evidence).lower()
    insights: list[dict[str, Any]] = []

    def evidence_mention(needles: tuple[str, ...]) -> str | None:
        for item in evidence:
            blob = item.lower()
            if any(needle in blob for needle in needles):
                return item
        return None

    apps = evidence_mention(("application", "applied", "submitted"))
    interviews = evidence_mention(("interview", "screen", "onsite", "loop"))
    interview_fail = evidence_mention(("fail", "rejected", "onsite", "technical", "loop", "system design"))

    if interview_fail and "highest" in q or interview_fail and "leverage" in q:
        insights.append(
            _insight(
                title="The recorded miss is the interview, not sourcing volume",
                description=f"Authorized notes already show interview trouble: {interview_fail}.",
                why_it_might_help="A later-stage miss is not fixed by sending more packets into the same funnel.",
                why_this_fits=interview_fail or evidence[0],
                next_step="Reproduce the last failed round in a timed mock and write the exact miss.",
                evidence_to_collect="Mock notes plus the next live round result.",
                grounded_facts=[interview_fail] if interview_fail else evidence[:1],
            )
        )
    elif apps and not interviews and ("highest" in q or "leverage" in q or "next move" in q):
        insights.append(
            _insight(
                title="Conversion is the bottleneck, not another application wave",
                description=f"Recorded progress includes applications ({apps}) without interviews.",
                why_it_might_help="More of a packet that is not converting will not create screens.",
                why_this_fits=apps,
                next_step="Rewrite one application around a team’s current problem and send it to a named person.",
                evidence_to_collect="Screens that follow from that targeted send.",
                grounded_facts=[apps],
            )
        )
    elif "hiring manager" in q or "access to hiring" in q:
        insights.append(
            _insight(
                title=f"Get in front of hiring managers for {title}",
                description=(
                    "The question is about access, not practice volume. "
                    "A manager conversation beats another anonymous application."
                ),
                why_it_might_help="Decision-makers can skip resume filters when someone they trust puts you in the thread.",
                why_this_fits=evidence[0] if evidence else "No named contact is on file; this stays conditional.",
                next_step="Name one person who can intro you to a hiring manager this week, or say you have none.",
                evidence_to_collect="Intros sent and whether a hiring-manager conversation happened.",
                grounded_facts=evidence[:1],
                assumptions=[] if evidence else ["You may have a path to a manager; none is recorded."],
            )
        )
    elif "technical interview" in q or "onsite" in q or "leetcode" in q or "prepare for" in q:
        fail = evidence_mention(("fail", "rejected", "onsite", "technical", "loop"))
        insights.append(
            _insight(
                title="Train the interview format that is actually blocking you",
                description=(
                    f"“{question}” is about execution in the room, not more applications."
                ),
                why_it_might_help="If screens happen and offers do not, volume is not the bottleneck.",
                why_this_fits=fail or "No interview-failure evidence is on file; this is a hypothesis about prep.",
                next_step="Run one timed mock in the same format as the last round and write down the miss.",
                evidence_to_collect="Mock notes and the next live round outcome. Do not invent a numeric effect.",
                grounded_facts=[fail] if fail else [],
                assumptions=[] if fail else ["Interview format is the constraint; confirm with the last round."],
            )
        )
    elif "cold" in q or "application" in q and "interview" in q:
        apps = evidence_mention(("application", "applied", "submitted"))
        interviews = evidence_mention(("interview", "screen"))
        if apps and not interviews:
            insights.append(
                _insight(
                    title="Fix conversion before adding another application wave",
                    description=f"Recorded progress includes applications ({apps}) without interviews.",
                    why_it_might_help="More of a packet that is not converting will not create screens.",
                    why_this_fits=apps,
                    next_step="Rewrite one application around a team’s current problem and send it to a named person.",
                    evidence_to_collect="Screens that follow from that targeted send.",
                    grounded_facts=[apps],
                )
            )
        else:
            insights.append(
                _insight(
                    title="Do not treat cold volume as the only channel",
                    description=f"The user asked: {question}",
                    why_it_might_help="Warm or targeted paths can reach a decision-maker without a calibrated coefficient.",
                    why_this_fits=evidence[0] if evidence else "No conversion evidence is on file.",
                    next_step="Pick one non-cold channel you actually have, or say you have none.",
                    evidence_to_collect="Conversations booked outside the job-board blast.",
                    grounded_facts=evidence[:1],
                    assumptions=[] if evidence else ["A warmer channel may exist; it is not recorded."],
                )
            )
    elif evidence_mention(("vc", "investor", "venture")) and (
        "smarter" in q or "intro" in q or "founder" in q or "cold" in q
    ):
        fact = evidence_mention(("vc", "investor", "venture")) or evidence[0]
        insights.append(
            _insight(
                title="Use the recorded investor conversation as a distribution path",
                description=(
                    "Authorized notes already mention an investor relationship. "
                    "Asking for a few relevant intros is a concrete next move, not a priced lever."
                ),
                why_it_might_help="An investor can open a founder conversation you cannot buy with extra applications.",
                why_this_fits=fact,
                next_step="Send a three-sentence ask naming two roles and one artifact they can forward.",
                evidence_to_collect="Intros made and resulting conversations.",
                grounded_facts=[fact],
            )
        )
    elif evidence_mention(("manager", "refer")):
        fact = evidence_mention(("manager", "refer")) or evidence[0]
        insights.append(
            _insight(
                title="Take the existing referral offer before starting another blast",
                description=f"Authorized evidence includes: {fact}",
                why_it_might_help="A named referrer is a specific channel, unlike generic networking advice.",
                why_this_fits=fact,
                next_step="Reply with the target role, two companies, and a packet they can forward this week.",
                evidence_to_collect="Whether the referral was submitted and if a screen followed.",
                grounded_facts=[fact],
            )
        )
    elif "paying" in ev or "customer" in q or "distribution" in q or "retention" in ev:
        if "retention" in ev or "churn" in ev:
            insights.append(
                _insight(
                    title="Diagnose why people leave before buying more top-of-funnel",
                    description="Authorized notes mention retention trouble. More acquisition would feed a leaky bucket.",
                    why_it_might_help="Keeping a user who already showed up is usually cheaper than finding a new one.",
                    why_this_fits=evidence_mention(("retention", "churn")) or evidence[0],
                    next_step="Interview two people who left and write the reason in one sentence each.",
                    evidence_to_collect="Churn reasons and any change in repeat use.",
                    grounded_facts=[evidence_mention(("retention", "churn")) or evidence[0]],
                )
            )
        else:
            insights.append(
                _insight(
                    title="Talk to people who already pay for the alternative",
                    description=f"For “{title}”, unpaid building is not the same as demand.",
                    why_it_might_help="Switching customers reveal the job to be done without inventing a conversion rate.",
                    why_this_fits=evidence[0] if evidence else "No paying-user evidence is on file.",
                    next_step="Book three conversations with buyers of a substitute this week.",
                    evidence_to_collect="Interview notes and any paid commitment.",
                    grounded_facts=evidence[:1],
                    assumptions=[] if evidence else ["A substitute product exists in the category."],
                )
            )
    elif "exam" in q or "homework" in ev or "study" in q:
        insights.append(
            _insight(
                title="Practice the assessment format that is actually scoring you down",
                description=f"The question was “{question}”, not a request for more undifferentiated hours.",
                why_it_might_help="Homework strength does not automatically transfer to exam retrieval.",
                why_this_fits=evidence[0] if evidence else "No grade breakdown is on file.",
                next_step="Do one closed-book retrieval session on the last missed exam topic.",
                evidence_to_collect="Scores on the next assessment. Hypothetical scores are not evidence.",
                grounded_facts=evidence[:1],
            )
        )
    elif "recover" in q or "tired" in ev or "mileage" in q or "run" in q:
        insights.append(
            _insight(
                title="Check recovery before adding load",
                description="More mileage is the default fitness slogan and may be the wrong lever.",
                why_it_might_help="Missed recovery can erase the value of extra sessions. This is not a medical claim.",
                why_this_fits=evidence[0] if evidence else "No training log is on file.",
                next_step="Write planned vs completed sessions for two weeks and mark rest days.",
                evidence_to_collect="Completed sessions and how you felt, without inventing a finish-time delta.",
                grounded_facts=evidence[:1],
                assumptions=["I am not making a diagnosis; this is a planning question."],
            )
        )
    elif "guitar" in q or "song" in q or "practice" in q and "habit" in title.lower():
        insights.append(
            _insight(
                title="Isolate the bar of the song that actually breaks down",
                description=f"The user asked: {question}. More minutes of the same loop may not be the skill.",
                why_it_might_help="Performance of a whole piece fails at a specific transition more often than at total time.",
                why_this_fits=evidence[0] if evidence else "No practice log details are on file.",
                next_step="Record one pass, mark the first bar that falls apart, and drill only that bar slowly.",
                evidence_to_collect="A recording of that bar before and after two sessions.",
                grounded_facts=evidence[:1],
            )
        )
    else:
        insights.append(
            _insight(
                title=f"Answer “{question[:72]}” from the actual bottleneck on {title}",
                description=(
                    "No canned playbook is attached. The next move should follow this question "
                    "and the authorized notes, not a generic domain template."
                ),
                why_it_might_help="A recommendation that ignores the question is not useful even if it is true in general.",
                why_this_fits=evidence[0] if evidence else "Authorized evidence is sparse, so this stays a hypothesis.",
                next_step="State the single constraint that most recently blocked progress on this goal.",
                evidence_to_collect="That constraint, dated, so the next answer can be specific.",
                grounded_facts=evidence[:2],
                assumptions=[] if evidence else ["The bottleneck is not yet recorded."],
            )
        )

    claims = []
    raw_research = payload.get("research")
    research: dict[str, Any] = raw_research if isinstance(raw_research, dict) else {}
    for claim in research.get("claims") or []:
        source = str(claim.get("source") or "")
        text = str(claim.get("claim") or "")
        if text and "placeholder" not in text.lower():
            claims.append(f"{text} ({source})" if source else text)
    return {
        "understood_question": question,
        "insights": insights[:3],
        "limitations": [],
        "research_claims": claims[:4],
    }


def _intervention(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("intervention_text") or "").lower()
    allowed = set(payload.get("allowed_metrics") or [])
    mechanism: list[dict[str, str]] = []
    changes: list[dict[str, Any]] = []
    unsupported: list[str] = []
    limitations: list[str] = []
    pricing_status = "NOT_PRICED"

    def add_change(metric: str, value: float, unit: str, *, operation: str = "set", frequency: str | None = None) -> None:
        if metric not in allowed:
            unsupported.append(f"Metric `{metric}` is not modeled for this goal.")
            return
        changes.append(
            {
                "metric": metric,
                "operation": operation,
                "value": value,
                "unit": unit,
                "frequency": frequency,
                "scope": "goal_state",
                "provenance": "EXPLORATION_ASSUMPTION",
                "strength": "EXPLORATORY",
            }
        )

    if "linkedin" in text:
        mechanism = [
            {"variable": "visibility", "description": "More public professional signal"},
            {"variable": "recruiter_inbound", "description": "Higher inbound recruiter interest"},
            {"variable": "qualified_opportunities", "description": "More interview funnel entries"},
        ]
        add_change("linkedin_posts_per_week", 4.0, "posts/week", frequency="weekly")
        pricing_status = "ASSUMPTION_REQUIRED"
    elif "mock interview" in text:
        mechanism = [
            {"variable": "interview_execution", "description": "Practice improves interview execution"},
            {"variable": "funnel_conversion", "description": "Better funnel conversion via execution quality"},
        ]
        add_change("mock_interviews_per_week", 3.0, "sessions/week", frequency="weekly")
        pricing_status = "PRICED"
    elif "sleep" in text and "hour" in text:
        mechanism = [
            {"variable": "recovery", "description": "More sleep supports recovery and consistency"},
            {"variable": "execution_rate", "description": "Better adherence to plan"},
        ]
        add_change("sleep_hours_per_night", 2.0, "hours/night", operation="add")
        pricing_status = "ASSUMPTION_REQUIRED"
    elif "application" in text or re.search(r"\bappl(?:y|ying|ied)\b", text):
        mechanism = [
            {"variable": "applications_submitted", "description": "Higher application throughput"},
            {"variable": "interview_funnel", "description": "More opportunities enter the funnel"},
        ]
        from personal_markets.agents.intervention_critic import parse_weekly_application_intent

        intent = parse_weekly_application_intent(text)
        if intent is not None:
            add_change(
                "applications_per_week",
                intent.value,
                "applications/week",
                operation=intent.operation,
                frequency="weekly",
            )
            pricing_status = "PRICED"
        else:
            unsupported.append("State a numeric application count per week to model this change.")
    elif "user" in text and "week" in text:
        mechanism = [
            {"variable": "customer_discovery", "description": "More user conversations"},
            {"variable": "problem_validation", "description": "Clearer product-market signal"},
        ]
        add_change("user_conversations_per_week", 10.0, "conversations/week", frequency="weekly")
        pricing_status = "ASSUMPTION_REQUIRED"
    elif "full time" in text or "full-time" in text:
        mechanism = [
            {"variable": "founder_hours", "description": "More dedicated startup time"},
            {"variable": "execution_rate", "description": "Higher plan execution"},
        ]
        add_change("hours_on_startup_per_week", 40.0, "hours/week", frequency="weekly")
        pricing_status = "ASSUMPTION_REQUIRED"
    elif "salesperson" in text or "sales" in text:
        mechanism = [
            {"variable": "outbound_pipeline", "description": "Dedicated sales capacity"},
            {"variable": "qualified_leads", "description": "More sales conversations"},
        ]
        add_change("sales_calls_per_week", 20.0, "calls/week", frequency="weekly")
        pricing_status = "NOT_PRICED"
        limitations.append("Sales hiring effect requires revenue model assumptions.")
    elif "run" in text and ("day" in text or "days" in text):
        mechanism = [
            {"variable": "training_load", "description": "More running sessions per week"},
            {"variable": "race_readiness", "description": "Improved aerobic base"},
        ]
        add_change("running_days_per_week", 4.0, "days/week", frequency="weekly")
        pricing_status = "PRICED"
    elif "km" in text or "kilometer" in text:
        mechanism = [
            {"variable": "weekly_volume", "description": "Higher weekly distance"},
            {"variable": "race_readiness", "description": "Volume-driven performance adaptation"},
        ]
        add_change("weekly_running_km", 40.0, "km/week", frequency="weekly")
        pricing_status = "PRICED"
    elif "invest" in text or "contribution" in text:
        mechanism = [
            {"variable": "monthly_savings", "description": "Higher monthly investment flow"},
            {"variable": "net_worth_trajectory", "description": "Compounding wealth path"},
        ]
        add_change("monthly_contribution", 1500.0, "usd/month", frequency="monthly")
        pricing_status = "PRICED"
    elif "rent" in text:
        mechanism = [
            {"variable": "monthly_expenses", "description": "Lower fixed housing cost"},
            {"variable": "runway", "description": "Improved cash retention"},
        ]
        add_change("burn_monthly", 500.0, "usd/month", operation="subtract", frequency="monthly")
        pricing_status = "ASSUMPTION_REQUIRED"
    else:
        unsupported.append("Intervention could not be mapped to a defensible mechanism chain.")

    if not changes and pricing_status != "NOT_PRICED":
        pricing_status = "NOT_PRICED"

    return {
        "understood_action": payload.get("intervention_text") or text,
        "mechanism": mechanism,
        "changes": changes,
        "pricing_status": pricing_status,
        "unsupported": unsupported,
        "research_claims": ["Scripted research placeholder; mechanism only."],
        "limitations": limitations,
        "notes": "Semantic intervention mapping only.",
    }


def _scripted_gloss(text: str) -> str:
    """LLM stand-in only: expand labels with common-language neighbors so scripted ranking can run without live GPT."""
    blob = text.lower()
    extra: list[str] = []
    pairs = (
        (("leetcode", "dsa", "algorithm"), "software interview practice coding offer"),
        (("interview", "oa", "recruiter"), "career offer application"),
        (("application", "pipeline", "tracker"), "career offer job"),
        (("running", "run", "mileage", "race", "interval", "pace", "strava", "marathon", "10k", "5k"), "training fitness workout"),
        (("github", "repo", "commit"), "engineering software project"),
        (("grocery", "meal", "game jam", "old-game"), "unrelated personal notes"),
        (("perf", "okr", "1:1", "1on1", "promotion", "staff"), "career engineering review"),
        (("budget", "cashflow", "loan", "debt", "net worth"), "finance money savings"),
        (("piano", "reading", "habit"), "practice streak habit"),
    )
    for keys, gloss in pairs:
        if any(key in blob for key in keys):
            extra.append(gloss)
    return " ".join(extra)


def _source_planner(payload: dict[str, Any]) -> dict[str, Any]:
    from personal_markets.integrations.resource_ranker import rank_resources

    goal = payload.get("goal") or {}
    plugins = payload.get("plugins") or []
    plugin_ids = {
        str(item.get("plugin_id") or item.get("id") or "")
        for item in plugins
        if isinstance(item, dict)
    }
    plugin_ids.discard("")
    available = payload.get("available_resources") or []

    def rec(plugin_id: str, rationale: str, resources: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "plugin_id": plugin_id,
            "relevance": "recommended",
            "rationale": rationale,
            "resources": resources,
        }

    def irr(plugin_id: str, rationale: str, resources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "plugin_id": plugin_id,
            "relevance": "irrelevant",
            "rationale": rationale,
            "resources": resources or [],
        }

    recommended: list[dict[str, Any]] = []
    irrelevant: list[dict[str, Any]] = []

    resource_by_plugin: dict[str, list[dict[str, Any]]] = {}
    if isinstance(available, list) and available:
        enriched = []
        for item in available:
            if not isinstance(item, dict):
                continue
            copy = dict(item)
            copy["description"] = " ".join(
                part
                for part in (str(item.get("description") or ""), _scripted_gloss(str(item.get("label") or item.get("id") or "")))
                if part
            )
            enriched.append(copy)
        ranked_resources = rank_resources(
            enriched,
            {**goal, "title": f"{goal.get('title') or ''} {_scripted_gloss(str(goal.get('title') or ''))}"},
        )
        for item in ranked_resources:
            plugin_id = str(item.get("plugin_id") or "")
            if not plugin_id:
                continue
            resource_by_plugin.setdefault(plugin_id, []).append(
                {
                    "resource_id": item["resource_id"],
                    "label": item["label"],
                    "rationale": item["why"],
                    "resource_type": item["resource_type"],
                    "why": item["why"],
                    "goal_relevance": item["goal_relevance"],
                    "state_variables": item["state_variables"],
                    "recommended": item["recommended"],
                }
            )

    catalog_resources = []
    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue
        plugin_id = str(plugin.get("plugin_id") or plugin.get("id") or "")
        if not plugin_id:
            continue
        catalog_resources.append(
            {
                "plugin_id": plugin_id,
                "id": plugin_id,
                "label": str(plugin.get("name") or plugin_id),
                "description": " ".join(
                    part
                    for part in [
                        str(plugin.get("description") or ""),
                        " ".join(str(value) for value in (plugin.get("used_for") or [])),
                        _scripted_gloss(str(plugin.get("description") or plugin_id)),
                    ]
                    if part
                ),
                "resource_type": "plugin",
            }
        )
    ranked = rank_resources(
        catalog_resources,
        {**goal, "title": f"{goal.get('title') or ''} {_scripted_gloss(str(goal.get('title') or ''))}"},
    )
    for item in ranked:
        plugin_id = str(item.get("plugin_id") or "")
        resources = resource_by_plugin.get(plugin_id) or [
            {
                "resource_id": item["resource_id"],
                "label": item["label"],
                "rationale": item["why"],
                "resource_type": item["resource_type"],
                "why": item["why"],
                "goal_relevance": item["goal_relevance"],
                "state_variables": item["state_variables"],
                "recommended": item["recommended"],
            }
        ]
        if float(item.get("score") or 0) >= 0.05 or any(row.get("recommended") for row in resources):
            recommended.append(rec(plugin_id, item["why"], resources))
        else:
            irrelevant.append(irr(plugin_id, item["why"], resources))

    return {
        "goal_title": str(goal.get("title") or "Goal"),
        "goal_type": str(goal.get("goal_type") or "deadline_event"),
        "state_dimensions": list(goal.get("state_dimensions") or []),
        "recommended": recommended,
        "irrelevant": irrelevant,
        "manual_fallback_note": "Manual evidence remains available when a source is not connected.",
    }


def _critic(payload: dict[str, Any]) -> dict[str, Any]:
    issues = list(payload.get("deterministic_issues") or [])
    priced = bool((payload.get("pricing") or {}).get("priced"))
    if any("future leakage" in issue.lower() or "duplicate" in issue.lower() for issue in issues):
        return {
            "decision": "withhold",
            "issues": issues,
            "limitations": [],
            "required_actions": ["Repair evidence or model inputs before publishing."],
        }
    if not priced:
        return {
            "decision": "publish_with_limitations",
            "issues": issues,
            "limitations": ["No calibrated model applies; probability withheld."],
            "required_actions": [],
        }
    return {"decision": "publish", "issues": issues, "limitations": [], "required_actions": []}


def transient_then_success(success: ScriptFn, failures: int = 1) -> ScriptFn:
    remaining = {"n": failures}

    def inner(request: InferenceRequest) -> dict[str, Any]:
        if remaining["n"] > 0:
            remaining["n"] -= 1
            raise TransientProviderError("simulated timeout")
        return success(request)

    return inner


def always_invalid_json(request: InferenceRequest) -> dict[str, Any]:
    del request
    raise SemanticProviderError("invalid json")


def auth_failure(request: InferenceRequest) -> dict[str, Any]:
    del request
    raise PermanentProviderError("invalid api key")
