# ruff: noqa: E501
"""Opt-in paid Spur acceptance. Ordinary CI must skip this module."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import text
from sqlalchemy.engine import make_url

from helpers import isolated_postgres_url
from personal_markets.agents.graph import LangGraphAgentWorkflow
from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.agents.models import estimate_cost_usd
from personal_markets.agents.state import AgentDependencies
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.repository import PostgresBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.service import GoalService
from personal_markets.identity.budget import InferenceBudgetService, InMemoryBudgetStore
from personal_markets.identity.credentials import InMemoryCredentialStore
from personal_markets.identity.domain import Principal
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.identity.inference_router import InferenceRouter
from personal_markets.identity.testing import make_principal
from personal_markets.integrations.research import FrozenReferenceProvider
from personal_markets.persistence.agent_store import (
    PostgresAgentRunStore,
    PostgresEvidenceRepository,
)
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresGoalRepository
from personal_markets.persistence.research_store import ResearchStore
from personal_markets.ports import (
    InferenceRequest,
    InferenceResponse,
    ResumePayload,
    WorkflowRequest,
)
from personal_markets.what_if.domain import InterventionChangeInput, WhatIfRequest
from personal_markets.what_if.last_scenario import LastInterventionStore
from personal_markets.what_if.repository import PostgresSimulationRepository
from personal_markets.what_if.service import WhatIfService

pytestmark = pytest.mark.live_spur

MAX_CALLS = 12
MAX_USD = 5.0
EVAL_PATH = Path("docs/live_spur_eval.json")


def _require_live() -> None:
    if os.environ.get("PM_LIVE_SPUR") != "1":
        pytest.skip("PM_LIVE_SPUR=1 is required for paid Spur acceptance")


class CappedInference:
    def __init__(self, inner: InferenceRouter) -> None:
        self._inner = inner
        self.calls = 0
        self.cost = 0.0
        self.records: list[dict[str, Any]] = []

    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        return await self._run("structured", request)

    async def complete_text(self, request: InferenceRequest) -> InferenceResponse:
        return await self._run("text", request)

    async def complete_tools(self, request: InferenceRequest) -> InferenceResponse:
        return await self._run("tools", request)

    async def _run(self, kind: str, request: InferenceRequest) -> InferenceResponse:
        if self.calls >= MAX_CALLS:
            raise RuntimeError(f"Reached the authorized {MAX_CALLS} inference-call cap")
        if self.cost >= MAX_USD:
            raise RuntimeError(f"Reached the authorized ${MAX_USD} inference-cost cap")
        self.calls += 1
        method = {
            "structured": self._inner.complete_structured,
            "text": self._inner.complete_text,
            "tools": self._inner.complete_tools,
        }[kind]
        response = await method(request)
        if response.provider == "scripted":
            raise RuntimeError("Scripted inference participated in the live Spur pass")
        cost = estimate_cost_usd(
            response.model,
            int(response.usage.get("input_tokens", 0)),
            int(response.usage.get("output_tokens", 0)),
        )
        self.cost += cost
        if self.cost > MAX_USD:
            raise RuntimeError(f"Live Spur estimated cost {self.cost:.4f} exceeded ${MAX_USD}")
        self.records.append(
            {
                "agent": request.agent_name,
                "kind": kind,
                "provider": response.provider,
                "model": response.model,
                "request_id": response.request_id,
                "usage": response.usage,
                "estimated_cost_usd": cost,
                "latency_ms": response.latency_ms,
                "structured_output": response.structured_output,
            }
        )
        return response


async def _complete_interrupt(
    workflow: LangGraphAgentWorkflow,
    snapshot: Any,
    *,
    evidence_answer: str | None = None,
) -> Any:
    original_goal = snapshot.goal.goal_id if snapshot.goal else None
    seen = 0
    while snapshot.status == "needs_input" and snapshot.interrupt:
        seen += 1
        if seen > 6:
            pytest.fail(f"interrupt loop stuck at {snapshot.interrupt.type}")
        itype = snapshot.interrupt.type
        if itype == "clarification":
            answers = {
                question.id: (
                    "FDE internship at a Series B+ software company by 2027-08-31. "
                    "Success is a written offer. TEST observations only."
                )
                for question in (snapshot.interrupt.questions or [])
            } or {
                "deadline": "2027-08-31",
                "success": "written FDE internship offer",
            }
            snapshot = await workflow.resume(snapshot.thread_id, ResumePayload(answers=answers))
        elif itype == "confirm_contract":
            snapshot = await workflow.resume(snapshot.thread_id, ResumePayload(confirmed=True))
        elif itype == "confirm_evidence":
            answers = {
                question.id: evidence_answer
                or (
                    "Distinct observed events. Recruiter replies, completed interviews, "
                    "and rejections are not applications. A founder introduction is not "
                    "an application."
                )
                for question in (snapshot.interrupt.questions or [])
            }
            snapshot = await workflow.resume(
                snapshot.thread_id,
                ResumePayload(confirmed=True, answers=answers),
            )
        else:
            pytest.fail(f"unexpected interrupt type {itype}")
        if original_goal and snapshot.goal:
            assert snapshot.goal.goal_id == original_goal, "evidence confirmation created a new goal"
    return snapshot


@pytest.mark.asyncio
async def test_complete_live_consumer_journey() -> None:
    _require_live()
    base = Settings()
    settings = base.model_copy(
        update={
            "environment": "development",
            "scripted_inference": False,
            "inference_provider": "spur",
            "inference_model": "spur-glm-5-3",
            "spur_model": "spur-glm-5-3",
            "openai_max_retries": 1,
            "openai_max_output_tokens": 4096,
            "openai_timeout_seconds": 90,
            "intervention_regex_fallback": False,
            "intervention_agent_enabled": True,
        }
    )
    if not settings.spur_api_key:
        pytest.fail("PM_SPUR_API_KEY is missing; do not fall back to scripted inference")
    url = isolated_postgres_url()
    if not url:
        pytest.fail("Isolated Postgres URL is required for live Spur persistence")
    if make_url(url).database in {None, "postgres"}:
        pytest.fail("Refusing to run live evidence writes against an unnamed/postgres database")
    engine = create_engine(url)
    owner = make_principal(
        f"live-spur-{uuid4()}",
        invited=True,
        hosted=True,
        quota_usd=5.0,
        quota_tokens=400_000,
    )
    ledger = InMemoryBudgetStore()

    async def lookup(user: UUID) -> Principal | None:
        return owner if user == owner.user_id else None

    router = InferenceRouter(
        settings,
        InMemoryCredentialStore(),
        InferenceBudgetService(ledger, settings),
        InferenceAudit(ledger),
        lookup,
    )
    capped = CappedInference(router)
    eval_rows: list[dict[str, Any]] = []
    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('goals')")):
                pytest.fail("Isolated Postgres is missing migrations")
            await conn.execute(
                text("insert into app_users (id, clerk_user_id) values (:id, :clerk)"),
                {"id": owner.user_id, "clerk": owner.clerk_user_id},
            )
        deps = AgentDependencies(
            settings,
            capped,
            FrozenReferenceProvider(),
            GoalService(PostgresGoalRepository(engine)),
            EvidenceService(PostgresEvidenceRepository(engine)),
            PostgresAgentRunStore(engine),
            BaselineForecastService(PostgresBaselineForecastRepository(engine)),
            ResearchStore(),
        )
        workflow = LangGraphAgentWorkflow(deps, MemorySaver())
        career = await _career_journey(
            workflow, deps, capped, owner, settings, engine, eval_rows
        )
        assert career["goal_id"]
        assert career["initial_receipt_id"]
        assert career["updated_receipt_id"]
        assert career["initial_receipt_id"] != career["updated_receipt_id"]
        assert career["additional_evidence_ids"]
        assert career["scenario_probability"] is not None
        assert all(item["provider"] == "spur" for item in capped.records)
        assert not any(item["provider"] == "scripted" for item in capped.records)
    finally:
        await asyncio.to_thread(
            EVAL_PATH.write_text,
            json.dumps(
                {
                    "calls": capped.calls,
                    "estimated_cost_usd": capped.cost,
                    "records": eval_rows,
                    "provider_calls": [
                        {
                            key: row[key]
                            for key in (
                                "agent",
                                "provider",
                                "model",
                                "request_id",
                                "usage",
                                "estimated_cost_usd",
                                "latency_ms",
                            )
                        }
                        for row in capped.records
                    ],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        await engine.dispose()


async def _career_journey(
    workflow: LangGraphAgentWorkflow,
    deps: AgentDependencies,
    capped: CappedInference,
    owner: Principal,
    settings: Settings,
    engine: Any,
    eval_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    draft = await workflow.start(
        WorkflowRequest(
            kind="create_goal",
            user_id=owner.user_id,
            intent=(
                "I want to land a forward-deployed engineer internship at a high-growth "
                "technology company by next summer."
            ),
        )
    )
    created = await _complete_interrupt(workflow, draft)
    eval_rows.append(
        {
            "goal_family": "career",
            "question": "goal architect",
            "status": created.status,
            "interrupt": created.interrupt.model_dump() if created.interrupt else None,
            "inference": dict(deps.last_inference),
            "proposal": created.goal.model_dump() if created.goal else None,
        }
    )
    assert deps.last_inference.get("provider") == "spur", "goal creation must use hosted Spur"
    assert created.goal is not None, created.model_dump()
    goal_id = created.goal.goal_id
    first = await workflow.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=goal_id,
            user_id=owner.user_id,
            evidence_text=(
                "TEST: I have already submitted 12 applications. I currently send about 8 "
                "applications per week. Two recruiters replied. I completed one phone screen. "
                "A former manager knows founders at two startups."
            ),
        )
    )
    first = await _complete_interrupt(
        workflow,
        first,
        evidence_answer=(
            "12 applications is a current total. 8 applications per week is a period rate. "
            "Recruiter replies and the phone screen are distinct events. Knowing founders "
            "is not an application."
        ),
    )
    assert first.status in {"completed", "limited", "withheld"}, (
        f"initial evidence stopped at {first.status} {first.interrupt}"
    )
    initial_ids = [str(item.evidence_id) for item in await deps.evidence.list_for_goal(goal_id)]
    assert initial_ids, "validated initial evidence must be committed"
    forecasts = PostgresBaselineForecastRepository(engine)
    initial_history = list(await forecasts.load_history(goal_id))
    assert initial_history, "initial evidence must publish a forecast receipt"
    initial_receipt = initial_history[-1]
    eval_rows.append(
        {
            "goal_family": "career",
            "question": "initial evidence",
            "status": first.status,
            "committed_evidence_ids": initial_ids,
            "probability": initial_receipt.probability,
            "receipt_id": initial_receipt.material_hash,
            "inference": dict(deps.last_inference),
        }
    )
    intervention = InterventionAgentService(
        settings,
        capped,
        FrozenReferenceProvider(),
        deps.goals,
        deps.evidence,
        deps.run_store,
        owner.user_id,
        forecasts=deps.baseline_forecasts,
        last_store=LastInterventionStore(),
    )
    modeled = await intervention.parse(
        str(goal_id),
        "What if I increase my applications from 8 per week to 15 per week for the next two months?",
    )
    eval_rows.append(
        {
            "goal_family": "career",
            "question": "8 to 15 applications / week",
            "validated": modeled.model_dump(mode="json"),
            "inference_provider": modeled.inference_provider,
            "inference_model": modeled.inference_model,
        }
    )
    assert modeled.inference_provider == "spur", modeled.inference_provider
    assert modeled.changes, (
        f"supported 8→15 application-rate intervention was dropped: {modeled.model_dump()}"
    )
    assert any(
        item.metric in {"applications_per_week", "weekly_application_rate"}
        and item.operation == "set"
        and abs(item.value - 15) < 1e-9
        for item in modeled.changes
    ), modeled.changes
    simulations = WhatIfService(
        deps.goals,
        PostgresSimulationRepository(engine),
        evidence=deps.evidence,
        owner_id=owner.user_id,
        forecasts=deps.baseline_forecasts,
    )
    state = await simulations.baseline_state(str(goal_id))
    simulation = await simulations.simulate(
        WhatIfRequest(
            goal_id=str(goal_id),
            current_value=state.current_value or 0,
            target_value=state.target_value or 1,
            periods=state.periods or 1,
            assumptions=state.assumptions,
            parsed_changes=[
                InterventionChangeInput.model_validate(change.model_dump())
                for change in modeled.changes
            ],
        )
    )
    assert simulation.scenario_probability is not None, simulation
    after_sim = list(await forecasts.load_history(goal_id))
    assert len(after_sim) == len(initial_history), "hypothetical simulation mutated published history"
    eval_rows.append(
        {
            "goal_family": "career",
            "question": "numerical simulation",
            "scenario_probability": simulation.scenario_probability,
            "receipts_unchanged": True,
        }
    )
    more = await workflow.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=goal_id,
            user_id=owner.user_id,
            evidence_text=(
                "TEST: A recruiter responded yesterday. I completed one interview. "
                "One application was rejected. The former manager introduced me to a founder. "
                "I also submitted 3 additional applications this week. This is not a hypothetical."
            ),
        )
    )
    more = await _complete_interrupt(workflow, more)
    assert more.status in {"completed", "limited", "withheld"}, (
        f"additional evidence stopped at {more.status} {more.interrupt}"
    )
    after_ids = [str(item.evidence_id) for item in await deps.evidence.list_for_goal(goal_id)]
    additional_ids = [item for item in after_ids if item not in set(initial_ids)]
    assert additional_ids, (
        f"additional evidence was not committed; persisted={after_ids} initial={initial_ids} "
        f"status={more.status}"
    )
    updated_history = list(await forecasts.load_history(goal_id))
    assert len(updated_history) > len(initial_history), (
        "new committed evidence did not publish a subsequent forecast receipt"
    )
    updated_receipt = updated_history[-1]
    retry_commit = await deps.evidence.commit(
        user_id=owner.user_id,
        goal_id=goal_id,
        events=list(more.evidence),
        agent_run_id=None,
        conflicts=[],
    )
    retry_ids = [str(item.evidence_id) for item in retry_commit.events if item.evidence_id]
    assert set(retry_ids) <= set(after_ids), "duplicate evidence was counted twice"
    from personal_markets.forecasting.reprice import BaselineRepriceService

    repriced = await BaselineRepriceService(
        deps.goals,
        deps.evidence,
        deps.baseline_forecasts,
        owner.user_id,
    ).publish_if_priceable(goal_id)
    assert repriced.status in {"unchanged", "not_priced", "withheld"}
    retry_history = list(await forecasts.load_history(goal_id))
    assert len(retry_history) == len(updated_history), "identical retry published a duplicate forecast"
    next_move = await intervention.parse(
        str(goal_id),
        "Given the recruiter response, completed interview, rejection, and founder "
        "introduction, what's my highest-leverage next move?",
    )
    assert next_move.inference_provider == "spur"
    eval_rows.append(
        {
            "goal_family": "career",
            "question": "highest-leverage next move after new evidence",
            "validated": next_move.model_dump(mode="json"),
            "additional_evidence_ids": additional_ids,
            "history_before": len(initial_history),
            "history_after": len(updated_history),
            "initial_probability": initial_receipt.probability,
            "updated_probability": updated_receipt.probability,
            "initial_receipt_id": initial_receipt.material_hash,
            "updated_receipt_id": updated_receipt.material_hash,
        }
    )
    return {
        "goal_id": str(goal_id),
        "history": updated_history,
        "calls": capped.calls,
        "additional_evidence_ids": additional_ids,
        "initial_receipt_id": initial_receipt.material_hash,
        "updated_receipt_id": updated_receipt.material_hash,
        "scenario_probability": simulation.scenario_probability,
    }


async def _savings_journey(
    workflow: LangGraphAgentWorkflow,
    deps: AgentDependencies,
    capped: CappedInference,
    owner: Principal,
    settings: Settings,
    eval_rows: list[dict[str, Any]],
) -> None:
    draft = await workflow.start(
        WorkflowRequest(
            kind="create_goal",
            user_id=owner.user_id,
            intent="I want to save $25,000 by September 2027, but my income varies each month.",
        )
    )
    if draft.status == "needs_input" and draft.interrupt and draft.interrupt.type == "clarification":
        answers = {
            question.id: "TEST: CAD 25000 liquid savings by 2027-09-01. Income varies 3-6k/month."
            for question in (draft.interrupt.questions or [])
        }
        draft = await workflow.resume(draft.thread_id, ResumePayload(answers=answers))
    if draft.status == "needs_input" and draft.interrupt and draft.interrupt.type == "confirm_contract":
        created = await workflow.resume(draft.thread_id, ResumePayload(confirmed=True))
    else:
        created = draft
    eval_rows.append(
        {
            "goal_family": "savings",
            "question": "goal architect",
            "status": created.status,
            "priceable": created.pricing is not None if created.goal else False,
            "goal": created.goal.model_dump() if created.goal else None,
            "inference": dict(deps.last_inference),
        }
    )
    if created.goal is None:
        return
    await workflow.start(
        WorkflowRequest(
            kind="add_evidence",
            goal_id=created.goal.goal_id,
            user_id=owner.user_id,
            evidence_text="TEST: Current savings are 8200 CAD. I contributed 900 CAD last month.",
        )
    )
    intervention = InterventionAgentService(
        settings,
        capped,
        FrozenReferenceProvider(),
        deps.goals,
        deps.evidence,
        deps.run_store,
        owner.user_id,
        forecasts=deps.baseline_forecasts,
        last_store=LastInterventionStore(),
    )
    parsed = await intervention.parse(
        str(created.goal.goal_id),
        "What if I saved 1200 a month instead of 900?",
    )
    eval_rows.append(
        {
            "goal_family": "savings",
            "question": "save 1200 instead of 900",
            "validated": parsed.model_dump(mode="json"),
        }
    )
    strategy = await intervention.parse(
        str(created.goal.goal_id),
        "Income is lumpy. What am I overlooking?",
    )
    eval_rows.append(
        {
            "goal_family": "savings",
            "question": "What am I overlooking?",
            "validated": strategy.model_dump(mode="json"),
        }
    )
