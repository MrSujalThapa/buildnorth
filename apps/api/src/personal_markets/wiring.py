from functools import lru_cache
from typing import Any

from fastapi import Request
from langgraph.checkpoint.memory import MemorySaver

from personal_markets.agents.budget import TokenBudget
from personal_markets.agents.graph import LangGraphAgentWorkflow
from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.agents.source_planner_service import SourcePlannerService
from personal_markets.agents.state import AgentDependencies
from personal_markets.core.config import Settings, get_settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.integrations.goal_sync_service import GoalSyncService
from personal_markets.forecasting.repository import (
    InMemoryBaselineForecastRepository,
    PostgresBaselineForecastRepository,
)
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.repository import GoalRepository
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.openai import (
    OpenAIInferenceProvider,
    UnconfiguredOpenAIInferenceProvider,
)
from personal_markets.integrations.gateway import UnifiedIntegrationGateway
from personal_markets.integrations.mcp_repository import InMemoryIntegrationRepository, PostgresIntegrationRepository
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
from personal_markets.ports import InferenceProvider


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

    async def start(self, request: Any) -> Any:
        snapshot = await self._inner.start(request)
        await self._threads.upsert(snapshot)
        await self._maybe_review(snapshot)
        return snapshot

    async def resume(self, thread_id: Any, payload: Any) -> Any:
        snapshot = await self._inner.resume(thread_id, payload)
        await self._threads.upsert(snapshot)
        await self._maybe_review(snapshot)
        return snapshot

    async def snapshot(self, thread_id: Any) -> Any:
        stored = await self._threads.get(thread_id)
        try:
            snapshot = await self._inner.snapshot(thread_id)
        except Exception:
            if stored is None:
                raise
            return stored
        await self._threads.upsert(snapshot)
        return snapshot

    async def _maybe_review(self, snapshot: Any) -> None:
        if self._reviews is None or snapshot.goal is None or snapshot.critic is None:
            return
        from uuid import uuid4

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


@lru_cache
def get_goal_repository() -> GoalRepository:
    database_url = get_settings().database_url
    if not database_url:
        return InMemoryGoalRepository()
    return PostgresGoalRepository(create_engine(database_url))


def get_goal_service() -> GoalService:
    return GoalService(get_goal_repository())


def get_what_if_service() -> Any:
    from personal_markets.persistence.agent_store import (
        InMemoryEvidenceRepository,
        PostgresEvidenceRepository,
    )
    from personal_markets.what_if.service import WhatIfService

    database_url = get_settings().database_url
    if database_url:
        evidence_repo = PostgresEvidenceRepository(create_engine(database_url))
    else:
        evidence_repo = InMemoryEvidenceRepository()
    return WhatIfService(
        get_goal_service(),
        get_simulation_repository(),
        evidence=EvidenceService(evidence_repo),
    )


def get_baseline_forecast_service() -> BaselineForecastService:
    return BaselineForecastService(get_baseline_forecast_repository())


def get_baseline_reprice_service() -> Any:
    from personal_markets.forecasting.reprice import BaselineRepriceService

    return BaselineRepriceService(
        get_goal_service(),
        get_evidence_service(),
        get_baseline_forecast_service(),
    )


@lru_cache
def get_baseline_forecast_repository() -> Any:
    database_url = get_settings().database_url
    if not database_url:
        return InMemoryBaselineForecastRepository()
    return PostgresBaselineForecastRepository(create_engine(database_url))


@lru_cache
def get_simulation_repository() -> Any:
    from personal_markets.what_if.repository import (
        InMemorySimulationRepository,
        PostgresSimulationRepository,
    )

    database_url = get_settings().database_url
    if not database_url:
        return InMemorySimulationRepository()
    return PostgresSimulationRepository(create_engine(database_url))


def build_inference(settings: Settings, usage_store: Any) -> InferenceProvider:
    if not settings.openai_api_key:
        return UnconfiguredOpenAIInferenceProvider()
    budget = TokenBudget(
        usage_store,
        settings.openai_daily_token_budget_high_volume,
        settings.openai_daily_token_budget_premium,
        settings.openai_max_cost_usd,
    )
    return OpenAIInferenceProvider(
        api_key=settings.openai_api_key,
        default_model=settings.openai_goal_model,
        budget=budget,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_concurrency=settings.openai_max_concurrency,
        max_output_tokens=settings.openai_max_output_tokens,
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
        inference=inference or ScriptedInferenceProvider(),
        research=CompositeResearchProvider(
            FrozenReferenceProvider(),
            MonidResearchProvider(
                settings.monid_enabled, settings.monid_api_base, settings.monid_client_id
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
    database_url = get_settings().database_url
    if database_url:
        return PostgresIntegrationRepository(create_engine(database_url))
    return InMemoryIntegrationRepository()


def get_integration_gateway() -> UnifiedIntegrationGateway:
    default_user_id = get_settings().default_user_id
    repository = get_integration_repository()
    return UnifiedIntegrationGateway(
        mcp=IntegrationGatewayService(
            repository=repository,
            default_user_id=default_user_id,
            settings=get_settings(),
        ),
        user_id=default_user_id,
    )


def _workflow_deps(request: Request) -> AgentDependencies:
    workflow = request.app.state.agent_workflow
    return workflow._inner._deps


def get_intervention_service(request: Request) -> InterventionAgentService:
    deps = _workflow_deps(request)
    settings = get_settings()
    return InterventionAgentService(
        settings=settings,
        inference=deps.inference,
        research=deps.research,
        goals=deps.goals,
        evidence=deps.evidence,
        run_store=deps.run_store,
    )


def get_source_planner_service(request: Request) -> SourcePlannerService:
    deps = _workflow_deps(request)
    settings = get_settings()
    return SourcePlannerService(
        settings=settings,
        inference=deps.inference,
        goals=deps.goals,
        evidence=deps.evidence,
        gateway=get_integration_gateway(),
        run_store=deps.run_store,
        repository=get_integration_repository(),
    )


def get_goal_sync_service(request: Request) -> GoalSyncService:
    deps = _workflow_deps(request)
    return GoalSyncService(
        settings=get_settings(),
        gateway=get_integration_gateway(),
        repository=get_integration_repository(),
        goals=deps.goals,
        workflow=request.app.state.agent_workflow,
        evidence=deps.evidence,
    )


def get_agent_workflow(request: Request) -> Any:
    return request.app.state.agent_workflow


def get_evidence_service(request: Request) -> EvidenceService:
    service = request.app.state.evidence_service
    assert isinstance(service, EvidenceService)
    return service


def get_github_cursor_store(request: Request) -> Any:
    return request.app.state.github_cursor_store
