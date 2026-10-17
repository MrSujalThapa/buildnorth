from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from personal_markets.agents.api import router as agents_router
from personal_markets.core.config import get_settings
from personal_markets.core.errors import (
    DomainError,
    PermanentProviderError,
    ProviderBudgetExceededError,
    ProviderNotConfiguredError,
    ResourceNotFoundError,
    TransientProviderError,
)
from personal_markets.core.event_loop import configure_windows_selector_event_loop
from personal_markets.core.logging import configure_logging
from personal_markets.core.request_context import request_context_middleware
from personal_markets.goals.api import router as goals_router
from personal_markets.goals.service import GoalService
from personal_markets.integrations.api import router as integrations_router
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.evidence.source_api import router as evidence_sources_router
from personal_markets.what_if.api import router as what_if_router
from personal_markets.wiring import (
    InMemoryGithubCursorStore,
    PersistingWorkflow,
    build_inference,
    get_goal_repository,
)

configure_windows_selector_event_loop()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


def _status_for(error: DomainError) -> int:
    if isinstance(error, ResourceNotFoundError):
        return 404
    if isinstance(error, ProviderNotConfiguredError):
        return 503
    if isinstance(error, ProviderBudgetExceededError):
        return 429
    if isinstance(error, TransientProviderError):
        return 503
    if isinstance(error, PermanentProviderError):
        return 502
    return 422


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    settings = get_settings()
    checkpointer_cm = None
    use_postgres = bool(settings.database_url) and settings.environment not in {"test", "pytest"}
    if use_postgres:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        from personal_markets.agents.graph import LangGraphAgentWorkflow
        from personal_markets.agents.state import AgentDependencies
        from personal_markets.evidence.service import EvidenceService
        from personal_markets.forecasting.repository import PostgresBaselineForecastRepository
        from personal_markets.forecasting.service import BaselineForecastService
        from personal_markets.persistence.agent_store import (
            PostgresAgentRunStore,
            PostgresEvidenceRepository,
            PostgresGithubCursorStore,
            PostgresReviewStore,
            PostgresThreadStore,
            PostgresUsageStore,
        )
        from personal_markets.persistence.database import create_engine

        assert settings.database_url is not None
        engine = create_engine(settings.database_url)
        usage = PostgresUsageStore(engine)
        inference = build_inference(settings, usage)
        evidence_repo = PostgresEvidenceRepository(engine)
        evidence = EvidenceService(evidence_repo)
        deps = AgentDependencies(
            settings=settings,
            inference=inference,
            research=CompositeResearchProvider(
                FrozenReferenceProvider(),
                MonidResearchProvider(
                    settings.monid_enabled, settings.monid_api_base, settings.monid_client_id
                ),
            ),
            goals=GoalService(get_goal_repository()),
            evidence=evidence,
            run_store=PostgresAgentRunStore(engine),
            baseline_forecasts=BaselineForecastService(
                PostgresBaselineForecastRepository(engine)
            ),
        )
        checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
        checkpointer = await checkpointer_cm.__aenter__()
        await checkpointer.setup()
        inner = LangGraphAgentWorkflow(deps, checkpointer)
        application.state.agent_workflow = PersistingWorkflow(
            inner, PostgresThreadStore(engine), PostgresReviewStore(engine)
        )
        application.state.evidence_service = evidence
        application.state.github_cursor_store = PostgresGithubCursorStore(engine)
        application.state.checkpointer = checkpointer
    else:
        from personal_markets.wiring import build_in_memory_workflow

        workflow = build_in_memory_workflow()
        application.state.agent_workflow = workflow
        application.state.evidence_service = workflow._inner._deps.evidence
        application.state.github_cursor_store = InMemoryGithubCursorStore()
    yield
    if checkpointer_cm is not None:
        await checkpointer_cm.__aexit__(None, None, None)


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="Personal Markets API", version="0.1.0", lifespan=lifespan)
    application.middleware("http")(request_context_middleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @application.exception_handler(DomainError)
    async def handle_domain_error(request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(error),
            content={"error": {"type": type(error).__name__, "message": str(error)}},
            headers={"x-request-id": request.headers.get("x-request-id", "")},
        )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="personal-markets-api", version="0.1.0")

    application.include_router(goals_router)
    application.include_router(agents_router)
    application.include_router(what_if_router)
    application.include_router(integrations_router)
    application.include_router(evidence_sources_router)
    return application


app = create_app()
