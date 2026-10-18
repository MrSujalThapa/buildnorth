import re
from typing import Any, TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_markets.agents.completion import MAX_SEMANTIC_RETRIES as MAX_SEMANTIC_RETRIES
from personal_markets.agents.completion import complete_validated
from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.models import estimate_cost_usd, ladders
from personal_markets.agents.prompts import load_prompt
from personal_markets.core.config import Settings
from personal_markets.core.request_context import client_ip_var
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.repository import InMemoryBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.domain import GoalContract
from personal_markets.goals.service import GoalService
from personal_markets.persistence.research_store import ResearchStore
from personal_markets.ports import (
    CriticArtifact,
    EvidenceEventProposal,
    InferenceProvider,
    InferenceRequest,
    InterruptPayload,
    PricingResult,
    ResearchArtifact,
    ResearchProvider,
    WorkflowSnapshot,
)

NAMESPACE = NAMESPACE_URL
MAX_CLARIFICATION_ROUNDS = 3

STEP_LABELS = {
    "architect_goal": "Understanding goal",
    "normalize_evidence": "Reading evidence",
    "research_agent": "Researching reference class",
    "compute_forecast": "Pricing market",
    "critique": "Checking forecast",
}


class AgentGraphState(TypedDict, total=False):
    thread_id: str
    user_id: str
    kind: str
    intent: str
    evidence_text: str
    github_login: str
    goal_id: str
    current_step: str
    status: str
    progress: list[str]
    goal_proposal: dict[str, Any]
    evidence_proposal: dict[str, Any]
    research: dict[str, Any]
    pricing: dict[str, Any]
    critic: dict[str, Any]
    agent_run_ids: dict[str, str]
    validation_errors: list[str]
    architect_retries: int
    goal_clarifications: int
    evidence_retries: int
    research_needed: bool
    resume_answers: dict[str, str]
    cancelled: bool
    committed_goal_id: str
    committed_evidence_ids: list[str]
    debug: dict[str, Any]
    github_records: list[dict[str, Any]]
    mcp_records: list[dict[str, Any]]


def stable_goal_id(thread_id: str) -> UUID:
    return uuid5(NAMESPACE, f"personal-markets:goal:{thread_id}")


def stable_run_id(thread_id: str, agent: str, attempt: int) -> UUID:
    return uuid5(NAMESPACE, f"personal-markets:run:{thread_id}:{agent}:{attempt}")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(
                marker in lowered
                for marker in ("api_key", "authorization", "secret", "token", "password")
            ):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?:sk-[A-Za-z0-9_-]+|monid_live_[A-Za-z0-9_-]+)", "[redacted]", value)
    return value


def mark_progress(state: AgentGraphState, step: str) -> list[str]:
    progress = list(state.get("progress") or [])
    label = STEP_LABELS.get(step)
    if label and label not in progress:
        progress.append(label)
    return progress


class AgentDependencies:
    def __init__(
        self,
        settings: Settings,
        inference: InferenceProvider,
        research: ResearchProvider,
        goals: GoalService,
        evidence: EvidenceService,
        run_store: Any,
        baseline_forecasts: BaselineForecastService | None = None,
        research_store: ResearchStore | None = None,
    ) -> None:
        self.settings = settings
        self.inference = inference
        self.research = research
        self.research_store = research_store or ResearchStore()
        self.goals = goals
        self.evidence = evidence
        self.run_store = run_store
        self.baseline_forecasts = baseline_forecasts or BaselineForecastService(
            InMemoryBaselineForecastRepository()
        )
        self.ladders = ladders(settings)


async def complete_agent(
    deps: AgentDependencies,
    state: AgentGraphState,
    agent: str,
    model_cls: type[Any],
    payload: dict[str, Any],
    attempt: int,
) -> tuple[dict[str, Any], str]:
    prompt = load_prompt(agent)
    ladder = deps.ladders[agent]
    run_id = stable_run_id(state["thread_id"], agent, attempt)
    request = InferenceRequest(
        instructions=prompt.text,
        input=redact(payload),
        output_schema=strict_json_schema(model_cls),
        model=None,
        fallback_models=[],
        pool=ladder.pool,  # type: ignore[arg-type]
        agent_name=agent,
        user_id=UUID(state["user_id"]) if state.get("user_id") else None,
        client_ip=client_ip_var.get(),
    )
    async def failed(error: Exception, semantic_attempt: int) -> None:
        usage = getattr(error, "usage", None)
        model = getattr(error, "model", "see_inference_ledger")
        await deps.run_store.record({
            "id": stable_run_id(state["thread_id"], agent, attempt * 10 + semantic_attempt + 1),
            "thread_id": state["thread_id"], "agent_type": agent,
            "agent_version": prompt.version,
            "model_provider": getattr(error, "provider", "resolved_by_router"),
            "model_name": model, "prompt_version": prompt.version,
            "prompt_checksum": prompt.checksum, "input_refs": list(payload), "output": {},
            "validation_status": "rejected", "retry_count": semantic_attempt,
            "duration_ms": 0, "token_usage": usage or {},
            "estimated_cost": estimate_cost_usd(model, usage.get("input_tokens", 0),
                usage.get("output_tokens", 0)) if usage else None,
            "tool_trace": [], "status": "failed",
        })

    parsed, response = await complete_validated(
        deps.inference, request, model_cls, failed,
        timeout_seconds=deps.settings.inference_run_timeout_seconds,
    )
    input_tokens = int(response.usage.get("input_tokens", 0))
    output_tokens = int(response.usage.get("output_tokens", 0))
    await deps.run_store.record(
        {
            "id": run_id,
            "thread_id": state["thread_id"],
            "agent_type": agent,
            "agent_version": prompt.version,
            "model_provider": response.provider,
            "model_name": response.model,
            "prompt_version": prompt.version,
            "prompt_checksum": prompt.checksum,
            "input_refs": list(payload.keys()),
            "output": redact(parsed.model_dump(mode="json")),
            "validation_status": "ok",
            "retry_count": response.retries,
            "duration_ms": response.latency_ms,
            "token_usage": response.usage,
            "estimated_cost": estimate_cost_usd(response.model, input_tokens, output_tokens),
            "tool_trace": [],
            "status": "completed",
        }
    )
    ids = dict(state.get("agent_run_ids") or {})
    ids[agent] = str(run_id)
    return redact(parsed.model_dump(mode="json")), str(run_id)


def snapshot_from_state(
    state: AgentGraphState,
    interrupt: InterruptPayload | None = None,
    goal: GoalContract | None = None,
) -> WorkflowSnapshot:
    evidence = state.get("evidence_proposal") or {}
    research = state.get("research")
    pricing = state.get("pricing")
    critic = state.get("critic")
    status = state.get("status") or "running"
    if interrupt:
        status = "needs_input"
    if state.get("cancelled"):
        status = "cancelled"
    return WorkflowSnapshot(
        thread_id=UUID(state["thread_id"]),
        kind=state.get("kind") or "create_goal",
        status=status,
        current_step=state.get("current_step") or "parse_request",
        progress=list(state.get("progress") or []),
        interrupt=interrupt,
        goal=goal,
        evidence=[
            EvidenceEventProposal.model_validate(item) for item in (evidence.get("events") or [])
        ],
        research=ResearchArtifact.model_validate(research) if research else None,
        pricing=PricingResult.model_validate(pricing) if pricing else None,
        critic=CriticArtifact.model_validate(critic) if critic else None,
        agent_run_ids=dict(state.get("agent_run_ids") or {}),
        debug=redact(dict(state.get("debug") or {"user_id": state.get("user_id")})),
    )
