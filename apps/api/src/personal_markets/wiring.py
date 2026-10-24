import asyncio
from functools import lru_cache
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

import structlog
from fastapi import Depends, Request
from langgraph.checkpoint.memory import MemorySaver

from personal_markets.agents.graph import LangGraphAgentWorkflow
from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.agents.source_planner_service import SourcePlannerService
from personal_markets.agents.state import AgentDependencies
from personal_markets.core.config import Settings, get_settings
from personal_markets.core.errors import ConflictError, TransientProviderError
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.repository import (
    InMemoryBaselineForecastRepository,
    PostgresBaselineForecastRepository,
)
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.repository import GoalRepository
from personal_markets.goals.service import GoalService
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.domain import Principal
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.gateway import UnifiedIntegrationGateway
from personal_markets.integrations.goal_sync_service import GoalSyncService
from personal_markets.integrations.mcp_repository import (
    InMemoryIntegrationRepository,
    PostgresIntegrationRepository,
)
from personal_markets.integrations.mcp_service import IntegrationGatewayService
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.persistence.agent_store import (
    InMemoryAgentRunStore,
    InMemoryEvidenceRepository,
    InMemoryThreadStore,
)
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresGoalRepository
from personal_markets.ports import (
    InferenceProvider,
    ResumePayload,
    WorkflowRequest,
    WorkflowSnapshot,
)


class InMemoryGithubCursorStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], str | None] = {}

    async def get(self, user_id: Any, login: str) -> str | None:
        return self._rows.get((str(user_id), login))

    async def put(self, user_id: Any, login: str, cursor: str | None) -> None:
        self._rows[(str(user_id), login)] = cursor


class PersistingWorkflow:
    def __init__(
        self, inner: LangGraphAgentWorkflow, threads: Any, reviews: Any | None = None
    ) -> None:
        self._inner = inner
        self._threads = threads
        self._reviews = reviews
        self._evidence_tasks: set[asyncio.Task[None]] = set()

    def schedule_evidence(self, thread_id: UUID) -> None:
        task = asyncio.create_task(self.continue_evidence_later(thread_id))
        self._evidence_tasks.add(task)
        task.add_done_callback(self._evidence_tasks.discard)

    async def start(self, request: Any) -> Any:
        snapshot = await self._inner.start(request)
        await self._threads.upsert(snapshot)
        await self._maybe_review(snapshot)
        return snapshot

    async def seed_running(self, request: WorkflowRequest) -> WorkflowSnapshot:
        thread_id = request.thread_id or uuid4()
        snapshot = WorkflowSnapshot(
            thread_id=thread_id,
            kind=request.kind,
            status="running",
            current_step="parse_request",
            progress=["Starting the agent workflow"],
            debug={"user_id": str(request.user_id) if request.user_id else "", "async": True},
        )
        await self._threads.upsert(snapshot)
        return snapshot

    async def mark_running(self, thread_id: UUID) -> WorkflowSnapshot:
        stored = await self._threads.get(thread_id)
        if stored is None:
            stored = await self.snapshot(thread_id)
        if stored.status != "needs_input":
            raise ConflictError("This workflow is not awaiting confirmation")
        running = stored.model_copy(
            update={
                "status": "running",
                "interrupt": None,
                "progress": [*list(stored.progress or []), "Continuing the agent workflow"],
            }
        )
        await self._threads.upsert(running)
        return running

    async def start_later(self, request: WorkflowRequest) -> None:
        try:
            await self.start(request)
        except Exception:
            await self._fail(request.thread_id)

    async def resume_later(self, thread_id: UUID, payload: ResumePayload) -> None:
        try:
            snapshot = await self.resume(thread_id, payload)
            if snapshot.status == "evidence_pending":
                await self.continue_evidence_later(thread_id)
        except Exception:
            await self._fail(thread_id)

    async def continue_evidence_later(self, thread_id: UUID) -> None:
        if not await self._threads.claim_evidence(thread_id):
            return
        try:
            snapshot = await self._inner.continue_evidence(thread_id)
            await self._threads.upsert(snapshot)
            await self._maybe_review(snapshot)
        except Exception:
            structlog.get_logger("personal_markets.agents").exception(
                "evidence_continuation_failed", thread_id=str(thread_id)
            )
            stored = await self._threads.get(thread_id)
            if stored is not None:
                await self._persist_failed_snapshot(thread_id, stored, evidence=True)

    async def creation_for_goal(self, goal_id: UUID, owner_id: UUID) -> WorkflowSnapshot | None:
        return cast(
            WorkflowSnapshot | None,
            await self._threads.latest_creation_for_goal(goal_id, owner_id),
        )

    async def creations_for_goals(
        self, goal_ids: list[UUID], owner_id: UUID,
    ) -> dict[UUID, WorkflowSnapshot]:
        return cast(
            dict[UUID, WorkflowSnapshot],
            await self._threads.latest_creations_for_goals(goal_ids, owner_id),
        )

    async def _fail(self, thread_id: UUID | None) -> None:
        structlog.get_logger("personal_markets.agents").exception("agent_workflow_failed")
        if thread_id is None:
            return
        stored = await self._threads.get(thread_id)
        if stored is None or stored.status != "running":
            return
        await self._persist_failed_snapshot(thread_id, stored)

    async def _persist_failed_snapshot(
        self, thread_id: UUID, fallback: WorkflowSnapshot, *, evidence: bool = False
    ) -> WorkflowSnapshot:
        try:
            latest = await self._inner.snapshot(thread_id)
        except Exception:
            latest = fallback
        failed = latest.model_copy(
            update={
                "status": "evidence_failed" if evidence else "failed",
                "current_step": "failed",
                "interrupt": None,
                "progress": [
                    *list(latest.progress or []),
                    (
                        "A provider request failed. Review the saved goal before retrying."
                        if latest.debug.get("goal_committed") is True
                        else "A provider request failed. You can try again."
                    ),
                ],
            }
        )
        await self._threads.upsert(failed)
        return failed

    async def resume(self, thread_id: Any, payload: Any) -> Any:
        try:
            snapshot = await self._inner.resume(thread_id, payload)
        except (TransientProviderError, TimeoutError) as error:
            stored = await self._threads.get(thread_id)
            if stored is None:
                raise
            failed = await self._persist_failed_snapshot(thread_id, stored)
            structlog.get_logger("personal_markets.agents").warning(
                "agent_workflow_resume_provider_failed",
                thread_id=str(thread_id),
                error_type=type(error).__name__,
                goal_committed=failed.debug.get("goal_committed") is True,
            )
            return failed
        await self._threads.upsert(snapshot)
        await self._maybe_review(snapshot)
        return snapshot

    async def snapshot(self, thread_id: Any) -> Any:
        stored = await self._threads.get(thread_id)
        # The background runner owns terminal state. A concurrent poll must not
        # revive a failed run from an older LangGraph checkpoint.
        if stored is not None and stored.status in {
            "failed", "evidence_failed", "evidence_running", "completed", "limited", "withheld"
        }:
            return stored
        try:
            snapshot = await self._inner.snapshot(thread_id)
        except Exception:
            if stored is None:
                raise
            return stored
        # Polling must never overwrite a concurrent continuation claim or its
        # terminal result. Only the runner persists state transitions.
        return snapshot

    async def _maybe_review(self, snapshot: Any) -> None:
        if self._reviews is None or snapshot.goal is None or snapshot.critic is None:
            return

        await self._reviews.append(
            {
                "id": uuid4(),
                "goal_id": snapshot.goal.goal_id,
                "thread_id": snapshot.thread_id,
                "priced": bool(snapshot.pricing.priced) if snapshot.pricing else False,
                "forecast_status": snapshot.pricing.forecast_status
                if snapshot.pricing
                else "EXPLORATORY",
                "critic_decision": snapshot.critic.decision,
                "limitations": snapshot.critic.limitations,
                "receipt": snapshot.pricing.receipt if snapshot.pricing else {},
                "agent_run_ids": snapshot.agent_run_ids,
            }
        )


def _use_postgres() -> bool:
    settings = get_settings()
    return bool(settings.database_url) and settings.environment not in {"test", "pytest"}


@lru_cache
def get_goal_repository() -> GoalRepository:
    if not _use_postgres():
        return InMemoryGoalRepository()
    return PostgresGoalRepository(create_engine(get_settings().database_url or ""))


def get_goal_service() -> GoalService:
    return GoalService(get_goal_repository())


@lru_cache
def get_collection_repository():
    from personal_markets.collections.repository import (
        InMemoryCollectionRepository,
        PostgresCollectionRepository,
    )

    if not _use_postgres():
        return InMemoryCollectionRepository()
    return PostgresCollectionRepository(create_engine(get_settings().database_url or ""))


def get_collection_service():
    from personal_markets.collections.service import CollectionService

    return CollectionService(get_collection_repository(), get_goal_service())


@lru_cache
def get_evidence_repository() -> Any:
    from personal_markets.persistence.agent_store import (
        InMemoryEvidenceRepository,
        PostgresEvidenceRepository,
    )

    if not _use_postgres():
        return InMemoryEvidenceRepository()
    return PostgresEvidenceRepository(create_engine(get_settings().database_url or ""))


def get_what_if_service(
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> Any:
    from personal_markets.what_if.service import WhatIfService

    return WhatIfService(
        get_goal_service(),
        get_simulation_repository(),
        evidence=EvidenceService(get_evidence_repository()),
        owner_id=principal.user_id,
    )


def get_baseline_forecast_service() -> BaselineForecastService:
    return BaselineForecastService(get_baseline_forecast_repository())


def get_baseline_reprice_service(
    request: Request,
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> Any:
    from personal_markets.forecasting.reprice import BaselineRepriceService

    deps = _workflow_deps(request)
    return BaselineRepriceService(
        deps.goals,
        deps.evidence,
        deps.baseline_forecasts,
        owner_id=principal.user_id,
    )


@lru_cache
def get_baseline_forecast_repository() -> Any:
    if not _use_postgres():
        return InMemoryBaselineForecastRepository()
    return PostgresBaselineForecastRepository(create_engine(get_settings().database_url or ""))


@lru_cache
def get_simulation_repository() -> Any:
    from personal_markets.what_if.repository import (
        InMemorySimulationRepository,
        PostgresSimulationRepository,
    )

    if not _use_postgres():
        return InMemorySimulationRepository()
    return PostgresSimulationRepository(create_engine(get_settings().database_url or ""))


def build_inference(settings: Settings, usage_store: Any) -> InferenceProvider:
    from personal_markets.identity.factory import (
        get_budget_store,
        get_credential_store,
        get_identity_repository,
        get_inference_budget_service,
    )
    from personal_markets.identity.inference_audit import InferenceAudit
    from personal_markets.identity.inference_router import InferenceRouter

    # usage_store is retained for callers from Phase 0/1; the canonical ledger now
    # accounts every provider attempt in hosted or BYOK mode.
    del usage_store
    return InferenceRouter(
        settings, get_credential_store(), get_inference_budget_service(),
        InferenceAudit(get_budget_store()), get_identity_repository().get_user,
    )


def build_in_memory_workflow(
    inference: InferenceProvider | None = None,
    goal_repository: GoalRepository | None = None,
) -> PersistingWorkflow:
    settings = get_settings()
    goals_repo = goal_repository or InMemoryGoalRepository()
    evidence_repo = InMemoryEvidenceRepository()
    runs = InMemoryAgentRunStore()
    threads = InMemoryThreadStore()
    deps = AgentDependencies(
        settings=settings,
        inference=inference or (
            ScriptedInferenceProvider() if settings.environment in {"test", "pytest"}
            else build_inference(settings, None)
        ),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(),
            MonidResearchProvider(
                settings.monid_enabled, settings.monid_api_base, settings.monid_client_id,
                    settings=settings
            ),
        ),
        goals=GoalService(goals_repo),
        evidence=EvidenceService(evidence_repo),
        run_store=runs,
        baseline_forecasts=BaselineForecastService(InMemoryBaselineForecastRepository()),
    )
    inner = LangGraphAgentWorkflow(deps, MemorySaver())
    return PersistingWorkflow(inner, threads)


@lru_cache
def get_integration_repository() -> InMemoryIntegrationRepository | PostgresIntegrationRepository:
    if not _use_postgres():
        return InMemoryIntegrationRepository()
    return PostgresIntegrationRepository(create_engine(get_settings().database_url or ""))


def integration_gateway_for(user_id) -> UnifiedIntegrationGateway:
    repository = get_integration_repository()
    return UnifiedIntegrationGateway(
        mcp=IntegrationGatewayService(
            repository=repository,
            default_user_id=user_id,
            settings=get_settings(),
        ),
        user_id=user_id,
    )


def get_integration_gateway(
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> UnifiedIntegrationGateway:
    return integration_gateway_for(principal.user_id)


def _workflow_deps(request: Request) -> AgentDependencies:
    workflow = request.app.state.agent_workflow
    return workflow._inner._deps


def get_intervention_service(
    request: Request,
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> InterventionAgentService:
    deps = _workflow_deps(request)
    settings = get_settings()
    return InterventionAgentService(
        settings=settings,
        inference=deps.inference,
        research=deps.research,
        goals=deps.goals,
        evidence=deps.evidence,
        run_store=deps.run_store,
        owner_id=principal.user_id,
    )


def get_source_planner_service(
    request: Request,
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> SourcePlannerService:
    deps = _workflow_deps(request)
    settings = get_settings()
    return SourcePlannerService(
        settings=settings,
        inference=deps.inference,
        goals=deps.goals,
        evidence=deps.evidence,
        gateway=integration_gateway_for(principal.user_id),
        run_store=deps.run_store,
        repository=get_integration_repository(),
        owner_id=principal.user_id,
    )


def get_goal_sync_service(
    request: Request,
    principal: Annotated[Principal, Depends(get_invited_principal)],
) -> GoalSyncService:
    deps = _workflow_deps(request)
    return GoalSyncService(
        settings=get_settings(),
        gateway=integration_gateway_for(principal.user_id),
        repository=get_integration_repository(),
        goals=deps.goals,
        workflow=request.app.state.agent_workflow,
        evidence=deps.evidence,
        owner_id=principal.user_id,
    )


def get_agent_workflow(request: Request) -> Any:
    return request.app.state.agent_workflow


def get_evidence_service(request: Request) -> EvidenceService:
    service = request.app.state.evidence_service
    assert isinstance(service, EvidenceService)
    return service


def get_github_cursor_store(request: Request) -> Any:
    return request.app.state.github_cursor_store


def get_upload_service(request: Request) -> Any:
    service = request.app.state.upload_service
    from personal_markets.evidence.uploads import UploadService

    assert isinstance(service, UploadService)
    return service
