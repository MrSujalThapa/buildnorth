import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from personal_markets.agents.api import router as agents_router
from personal_markets.collections.api import router as collections_router
from personal_markets.core.config import get_settings, safe_database_identity
from personal_markets.core.errors import (
    ConflictError,
    DomainError,
    ForbiddenError,
    PermanentProviderError,
    ProviderBudgetExceededError,
    ProviderNotConfiguredError,
    ResourceNotFoundError,
    TransientProviderError,
    UnauthorizedError,
)
from personal_markets.core.event_loop import configure_windows_selector_event_loop
from personal_markets.core.logging import configure_logging
from personal_markets.core.request_context import health_details_allowed, request_context_middleware
from personal_markets.evidence.source_api import router as evidence_sources_router
from personal_markets.evidence.upload_api import router as upload_router
from personal_markets.goals.api import router as goals_router
from personal_markets.goals.service import GoalService
from personal_markets.identity.api import router as identity_router
from personal_markets.identity.deps import get_invited_principal
from personal_markets.identity.inference_api import router as inference_settings_router
from personal_markets.integrations.api import router as integrations_router
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.persistence.research_store import ResearchStore
from personal_markets.profile.api import router as profile_router
from personal_markets.what_if.api import router as what_if_router
from personal_markets.wiring import (
    InMemoryGithubCursorStore,
    PersistingWorkflow,
    build_inference,
)
from personal_markets.workspace_seed.api import router as workspace_seed_router

configure_windows_selector_event_loop()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    commit: str | None = None


def _deployed_commit() -> str | None:
    value = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("PM_BUILD_COMMIT")
    return value[:12] if value else None


class HealthDetailsResponse(HealthResponse):
    database: str


def _status_for(error: DomainError) -> int:
    if isinstance(error, ResourceNotFoundError):
        return 404
    if isinstance(error, UnauthorizedError):
        return 401
    if isinstance(error, ForbiddenError):
        return 403
    if isinstance(error, ConflictError):
        return 409
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
    settings.assert_safe_startup()
    checkpointer_cm = None
    use_postgres = bool(settings.database_url) and settings.environment not in {"test", "pytest"}
    identity = safe_database_identity(settings.database_url) if use_postgres else "memory"
    application.state.database_identity = identity
    structlog.get_logger("personal_markets").info(
        "api_database",
        identity=identity,
        environment=settings.environment,
        deployed=settings.is_deployed(),
    )
    structlog.get_logger("personal_markets").warning(
        "single_worker_required",
        reason="MCP rate limits and goal write locks are process-local asyncio state",
    )
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
        from personal_markets.wiring import get_goal_repository

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
                    settings.monid_enabled,
                    settings.monid_api_base,
                    settings.monid_client_id,
                    settings=settings,
                ),
            ),
            goals=GoalService(get_goal_repository()),
            evidence=evidence,
            run_store=PostgresAgentRunStore(engine),
            research_store=ResearchStore(engine),
            baseline_forecasts=BaselineForecastService(PostgresBaselineForecastRepository(engine)),
        )
        checkpointer_cm = AsyncPostgresSaver.from_conn_string(settings.database_url)
        checkpointer = await checkpointer_cm.__aenter__()
        await checkpointer.setup()
        inner = LangGraphAgentWorkflow(deps, checkpointer)
        application.state.agent_workflow = PersistingWorkflow(
            inner, PostgresThreadStore(engine), PostgresReviewStore(engine)
        )
        application.state.evidence_service = evidence
        from personal_markets.evidence.uploads import PostgresUploadStore, UploadService

        application.state.upload_service = UploadService(PostgresUploadStore(engine))
        application.state.github_cursor_store = PostgresGithubCursorStore(engine)
        application.state.checkpointer = checkpointer
    else:
        from personal_markets.wiring import build_in_memory_workflow, get_goal_repository

        workflow = build_in_memory_workflow(goal_repository=get_goal_repository())
        application.state.agent_workflow = workflow
        application.state.evidence_service = workflow._inner._deps.evidence
        from personal_markets.evidence.uploads import UploadService, UploadStore

        application.state.upload_service = UploadService(UploadStore())
        application.state.github_cursor_store = InMemoryGithubCursorStore()
    from personal_markets.integrations.goal_sync_worker import goal_sync_worker

    sync_stop = asyncio.Event()
    import os

    sync_worker = (
        None
        if os.getenv("PLAYITOUT_WATCH_RUNNER") == "1"
        else asyncio.create_task(goal_sync_worker(application, sync_stop))
    )
    async with AsyncExitStack() as stack:
        remote = getattr(application.state, "remote_mcp", None)
        if remote is not None:
            await stack.enter_async_context(remote.session_manager.run())
        try:
            yield
        finally:
            sync_stop.set()
            if sync_worker is not None:
                sync_worker.cancel()
                with suppress(asyncio.CancelledError):
                    await sync_worker
    if checkpointer_cm is not None:
        await checkpointer_cm.__aexit__(None, None, None)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.assert_safe_startup()
    application = FastAPI(title="Personal Markets API", version="0.1.0", lifespan=lifespan)
    application.middleware("http")(request_context_middleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "mcp-session-id",
            "mcp-protocol-version",
            "www-authenticate",
            "server-timing",
        ],
    )

    @application.exception_handler(DomainError)
    async def handle_domain_error(request: Request, error: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(error),
            content={"error": {"type": type(error).__name__, "message": str(error)}},
            headers={"x-request-id": request.headers.get("x-request-id", "")},
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's default includes raw submitted values. Credential errors must never echo keys.
        if "/settings/inference/credentials" in request.url.path:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "type": "ValidationError",
                        "message": "Invalid provider or API key format",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                    for item in error.errors()
                ]
            },
        )

    def _database_identity(request: Request) -> str:
        identity = getattr(request.app.state, "database_identity", None)
        if identity is not None:
            return str(identity)
        current = get_settings()
        use_postgres = bool(current.database_url) and current.environment not in {"test", "pytest"}
        return safe_database_identity(current.database_url) if use_postgres else "memory"

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="personal-markets-api",
            version="0.1.0",
            commit=_deployed_commit(),
        )

    @application.get("/health/details", response_model=HealthDetailsResponse, tags=["system"])
    async def health_details(request: Request) -> HealthDetailsResponse:
        current = get_settings()
        if not health_details_allowed(request, current):
            raise HTTPException(status_code=404, detail="Not found")
        return HealthDetailsResponse(
            status="ok",
            service="personal-markets-api",
            version="0.1.0",
            database=_database_identity(request),
        )

    private = [Depends(get_invited_principal)]
    application.include_router(identity_router)
    application.include_router(profile_router, dependencies=private)
    application.include_router(inference_settings_router)
    application.include_router(goals_router, dependencies=private)
    application.include_router(collections_router, dependencies=private)
    application.include_router(agents_router, dependencies=private)
    application.include_router(what_if_router, dependencies=private)
    application.include_router(integrations_router, dependencies=private)
    application.include_router(evidence_sources_router, dependencies=private)
    application.include_router(upload_router, dependencies=private)
    application.include_router(workspace_seed_router)
    if settings.mcp_enabled:
        from personal_markets.remote_mcp.consent_api import router as remote_mcp_router
        from personal_markets.remote_mcp.factory import mount_remote_mcp

        application.include_router(remote_mcp_router)
        mount_remote_mcp(application, settings)
    return application


app = create_app()
