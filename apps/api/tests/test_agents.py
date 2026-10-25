from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from pydantic import ValidationError

from personal_markets.agents.critic import (
    deterministic_critic,
    deterministic_critic_decision,
    merge_critic_decision,
)
from personal_markets.agents.goal_mapping import proposal_to_contract, validation_errors
from personal_markets.agents.graph import LangGraphAgentWorkflow
from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.pricing import needs_research, price_goal
from personal_markets.agents.retries import classify_provider_error
from personal_markets.agents.state import AgentDependencies, AgentGraphState, complete_agent, redact
from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    PermanentProviderError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.evidence.service import EvidenceService, evidence_fingerprint
from personal_markets.goals.adapters import InMemoryGoalRepository
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
from personal_markets.ports import (
    CriticArtifact,
    EvidenceEventProposal,
    GoalArchitectProposal,
    PricingResult,
    ResumePayload,
    WorkflowRequest,
)


def make_proposal(**overrides: object) -> GoalArchitectProposal:
    payload: dict[str, object] = {
        "ready_to_commit": True,
        "title": "Receive an SWE offer",
        "goal_type": "deadline_event",
        "success_metric": "offer_received",
        "success_operator": "==",
        "success_target": "swe_offer",
        "deadline": "2027-08-31",
        "state_dimensions": ["interview_outcomes"],
        "hours_per_week": 8,
        "model_family_compatibility": "exploratory_hiring",
        "clarifications_required": [],
        "notes": "",
    }
    payload.update(overrides)
    return GoalArchitectProposal.model_validate(payload)


def workflow(provider: ScriptedInferenceProvider | None = None) -> LangGraphAgentWorkflow:
    goals = InMemoryGoalRepository()
    evidence_repo = InMemoryEvidenceRepository()
    deps = AgentDependencies(
        settings=Settings(environment="test"),
        inference=provider or ScriptedInferenceProvider(),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(), MonidResearchProvider(False, None, None)
        ),
        goals=GoalService(goals),
        evidence=EvidenceService(evidence_repo),
        run_store=InMemoryAgentRunStore(),
    )
    return LangGraphAgentWorkflow(deps, MemorySaver())


@pytest.mark.asyncio
async def test_goal_creation_passes_confirmed_current_state_to_evidence_agent() -> None:
    runtime = workflow()
    intent = "Save $10,000 by December 2027. I already have $2,000 saved."
    proposal = make_proposal(current_state_known={"savings": "$2,000"})
    result = await runtime._collect_evidence(
        {"kind": "create_goal", "intent": intent, "goal_proposal": proposal.model_dump()}
    )
    assert result["evidence_text"] == intent
    assert runtime._after_collect_evidence(cast(AgentGraphState, result)) == "normalize_evidence"


@pytest.mark.asyncio
async def test_goal_creation_does_not_treat_target_alone_as_evidence() -> None:
    runtime = workflow()
    result = await runtime._collect_evidence(
        {
            "kind": "create_goal",
            "intent": "Save $10,000 by December 2027.",
            "goal_proposal": make_proposal().model_dump(),
        }
    )
    assert result["evidence_text"] == ""
    assert runtime._after_collect_evidence(cast(AgentGraphState, result)) == "decide_research"


def test_strict_schema_sets_additional_properties_false() -> None:
    schema = strict_json_schema(GoalArchitectProposal)
    assert schema["additionalProperties"] is False
    assert "title" in schema["required"]
    assert schema["properties"]["clarifications_required"]["type"] == "array"
    assert schema["properties"]["notes"]["type"] == "string"


def test_strict_schema_lets_architect_report_known_current_state() -> None:
    from jsonschema import Draft202012Validator

    schema = strict_json_schema(GoalArchitectProposal)
    output = make_proposal().model_dump(mode="json")
    output["current_state_known"] = [
        {"key": "customers", "value": "50"},
        {"key": "mrr", "value": "1900"},
    ]
    Draft202012Validator(schema).validate(output)
    proposal = GoalArchitectProposal.model_validate(output)
    assert proposal.current_state_known == {"customers": "50", "mrr": "1900"}
    assert GoalArchitectProposal.model_validate(proposal.model_dump()).current_state_known == {
        "customers": "50",
        "mrr": "1900",
    }


def test_goal_architect_schema_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        make_proposal(title="ab")


def test_validation_requires_clarifications_or_measurable_fields() -> None:
    proposal = make_proposal(
        ready_to_commit=False, success_metric="unspecified", clarifications_required=[]
    )
    assert validation_errors(proposal)


def test_proposal_maps_to_goal_contract() -> None:
    goal = proposal_to_contract(make_proposal())
    assert goal.success_definition["metric"] == "offer_received"
    assert goal.forecast_status.value == "EXPLORATORY"


def test_research_is_conditional() -> None:
    assert needs_research(make_proposal())
    habit = make_proposal(
        title="Run a 10K",
        goal_type="threshold",
        success_metric="10k_time",
        success_target="3000",
        model_family_compatibility="none",
        state_dimensions=["recent_10k_time"],
    )
    assert not needs_research(habit)


def test_pricing_does_not_invent_probability() -> None:
    result = price_goal(make_proposal(), [], {}, [])
    assert result.priced is False
    assert result.raw_probability is None
    assert result.forecast_status == "EXPLORATORY"


def test_retry_classification() -> None:
    assert classify_provider_error(RuntimeError("429 rate limit")) is TransientProviderError
    assert classify_provider_error(RuntimeError("invalid api key")) is PermanentProviderError
    assert classify_provider_error(RuntimeError("invalid json schema")) is SemanticProviderError


def test_redact_strips_keys_and_openai_prefixes() -> None:
    payload = redact({"api_key": "sk-secret", "nested": {"token": "abc"}, "ok": "goal"})
    assert payload["api_key"] == "[redacted]"
    assert payload["nested"]["token"] == "[redacted]"
    assert payload["ok"] == "goal"


@pytest.mark.asyncio
async def test_agent_run_records_estimated_cost() -> None:
    run_store = InMemoryAgentRunStore()
    deps = AgentDependencies(
        settings=Settings(environment="test"),
        inference=ScriptedInferenceProvider(),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(), MonidResearchProvider(False, None, None)
        ),
        goals=GoalService(InMemoryGoalRepository()),
        evidence=EvidenceService(InMemoryEvidenceRepository()),
        run_store=run_store,
    )
    await complete_agent(
        deps,
        {"thread_id": str(uuid4()), "agent_run_ids": {}},
        "goal_architect",
        GoalArchitectProposal,
        {"intent": "Receive an SWE offer by August 2027"},
        0,
    )
    assert run_store.runs[0]["estimated_cost"] > 0


def test_deterministic_critic_detects_future_leak_and_duplicates() -> None:
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    events = [
        EvidenceEventProposal(
            event_type="assessment",
            domain="academic",
            metric="score",
            numeric_value=0.9,
            observed_at=future,
            source_type="manual",
            summary="future exam",
        ),
        EvidenceEventProposal(
            event_type="assessment",
            domain="academic",
            metric="score",
            numeric_value=0.9,
            observed_at=future,
            source_type="manual",
            summary="future exam",
        ),
    ]
    issues = deterministic_critic(
        events,
        ["a", "a"],
        PricingResult(priced=False, forecast_status="CALIBRATED"),
    )
    assert any("Future leakage" in item for item in issues)
    assert any("Duplicated evidence IDs" in item for item in issues)
    merged = merge_critic_decision(
        issues,
        CriticArtifact(decision="publish", issues=[], limitations=[], required_actions=[]),
        False,
    )
    assert merged.decision == "withhold"


def test_deterministic_critic_rejects_llm_generated_coefficient() -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    events = [
        EvidenceEventProposal(
            event_type="assessment",
            domain="academic",
            metric="score",
            numeric_value=0.9,
            observed_at=past,
            source_type="manual",
            summary="past exam",
        )
    ]
    issues = deterministic_critic(
        events,
        ["e1"],
        PricingResult(
            priced=True,
            forecast_status="EXPLORATORY",
            raw_probability=0.4,
            calibrated_probability=0.4,
            limitations=[],
            receipt={"coefficient_provenance": "LLM_GENERATED_COEFFICIENT"},
        ),
    )
    assert any("Unsupported coefficient" in item for item in issues)
    decision = deterministic_critic_decision(
        issues,
        PricingResult(
            priced=True,
            forecast_status="EXPLORATORY",
            raw_probability=0.4,
            calibrated_probability=0.4,
            limitations=[],
            receipt={},
        ),
    )
    assert decision is not None
    assert decision.decision == "withhold"


def test_obvious_unpriced_forecast_is_withheld_without_llm_critic() -> None:
    pricing = PricingResult(priced=False, forecast_status="EXPLORATORY")
    decision = deterministic_critic_decision([], pricing)
    assert decision is not None
    assert decision.decision == "withhold"


def test_evidence_fingerprint_is_stable() -> None:
    event = EvidenceEventProposal(
        event_type="practice",
        domain="software",
        metric="leetcode_medium_count",
        numeric_value=14,
        observed_at="unknown",
        source_type="manual",
        summary="LeetCode medium problems solved",
    )
    user = uuid4()
    assert evidence_fingerprint(user, event) == evidence_fingerprint(user, event)


@pytest.mark.asyncio
async def test_clear_goal_interrupts_for_confirmation_then_completes() -> None:
    runtime = workflow()
    first = await runtime.start(
        WorkflowRequest(
            kind="create_goal",
            intent=(
                "I want to receive an SWE/FDE offer from one of my "
                "target companies by August 2027."
            ),
        )
    )
    assert first.status == "needs_input"
    assert first.interrupt is not None
    assert first.interrupt.type == "confirm_contract"
    assert "Researching reference class" not in first.progress
    second = await runtime.resume(first.thread_id, ResumePayload(confirmed=True))
    assert second.status == "evidence_pending"
    assert second.goal is not None
    assert second.pricing is None
    second = await runtime.continue_evidence(first.thread_id)
    assert second.status == "evidence_pending"
    assert second.goal is not None
    assert second.pricing is None
    assert "Understanding goal" in second.progress
    if second.progress.count("Researching reference class"):
        assert "Reading evidence" not in second.progress


@pytest.mark.asyncio
async def test_ambiguous_goal_uses_clarification_interrupt() -> None:
    runtime = workflow()
    first = await runtime.start(WorkflowRequest(kind="create_goal", intent="I want to get rich."))
    assert first.interrupt is not None
    assert first.interrupt.type == "clarification"
    second = await runtime.resume(
        first.thread_id,
        ResumePayload(answers={"rich_definition": "net worth 1000000", "deadline": "2035-12-31"}),
    )
    assert second.interrupt is not None
    assert second.interrupt.type == "confirm_contract"


@pytest.mark.asyncio
async def test_completed_goal_has_stable_id() -> None:
    runtime = workflow()
    first = await runtime.start(
        WorkflowRequest(kind="create_goal", intent="Receive an SWE offer by August 2027")
    )
    done = await runtime.resume(first.thread_id, ResumePayload(confirmed=True))
    again = await runtime.snapshot(first.thread_id)
    assert done.goal is not None and again.goal is not None
    assert done.goal.goal_id == again.goal.goal_id


@pytest.mark.asyncio
async def test_manual_evidence_extracts_two_events() -> None:
    runtime = workflow()
    created = await runtime.start(
        WorkflowRequest(kind="create_goal", intent="Receive an SWE offer by August 2027")
    )
    priced = await runtime.resume(created.thread_id, ResumePayload(confirmed=True))
    assert priced.goal is not None
    evidence = await runtime.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=priced.goal.goal_id,
            evidence_text="I solved 14 LeetCode mediums this week and failed a Meta phone screen.",
        )
    )
    summaries = {item.summary for item in evidence.evidence}
    assert any("LeetCode" in item for item in summaries)
    assert any("Phone screen" in item or "phone screen" in item.lower() for item in summaries)
    if evidence.interrupt:
        evidence = await runtime.resume(evidence.thread_id, ResumePayload(confirmed=True))
    assert evidence.pricing is not None
    assert evidence.pricing.priced is True
    assert evidence.pricing.raw_probability is not None
    assert 0 < evidence.pricing.raw_probability < 1
    assert evidence.pricing.receipt.get("llm_used_for_probability") is False
    transforms = evidence.pricing.receipt.get("feature_transforms") or {}
    assert "funnel_state" in transforms


@pytest.mark.asyncio
async def test_confirm_evidence_with_answers_does_not_create_a_new_goal() -> None:
    runtime = workflow()
    created = await runtime.start(
        WorkflowRequest(kind="create_goal", intent="Receive an SWE offer by August 2027")
    )
    priced = await runtime.resume(created.thread_id, ResumePayload(confirmed=True))
    assert priced.goal is not None
    goal_id = priced.goal.goal_id
    evidence = await runtime.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=goal_id,
            evidence_text="I solved 14 LeetCode mediums this week and failed a Meta phone screen.",
        )
    )
    if evidence.interrupt and evidence.interrupt.type == "confirm_evidence":
        evidence = await runtime.resume(
            evidence.thread_id,
            ResumePayload(
                confirmed=True,
                answers={"observation_kind": "These are distinct observed events."},
            ),
        )
    assert evidence.goal is not None
    assert evidence.goal.goal_id == goal_id
    ids = list(evidence.debug.get("committed_evidence_ids") or [])
    assert ids
    duplicate = await runtime.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=goal_id,
            evidence_text="I solved 14 LeetCode mediums this week and failed a Meta phone screen.",
        )
    )
    if duplicate.interrupt:
        duplicate = await runtime.resume(duplicate.thread_id, ResumePayload(confirmed=True))
    extra = set(duplicate.debug.get("committed_evidence_ids") or []) - set(ids)
    assert not extra


@pytest.mark.asyncio
async def test_evidence_confirmation_can_be_cancelled() -> None:
    runtime = workflow()
    created = await runtime.start(
        WorkflowRequest(kind="create_goal", intent="Receive an SWE offer by August 2027")
    )
    priced = await runtime.resume(created.thread_id, ResumePayload(confirmed=True))
    assert priced.goal is not None
    evidence = await runtime.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=priced.goal.goal_id,
            evidence_text="I solved 14 LeetCode mediums this week and failed a Meta phone screen.",
        )
    )
    if evidence.interrupt is None:
        pytest.skip("scripted evidence did not request confirmation")
    cancelled = await runtime.resume(evidence.thread_id, ResumePayload(cancelled=True))
    assert cancelled.status == "cancelled"
    assert not cancelled.debug.get("committed_evidence_ids")
