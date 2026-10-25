import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request

from personal_markets.collections.repository import InMemoryCollectionRepository
from personal_markets.collections.service import CollectionService
from personal_markets.evidence.uploads import UploadService, UploadStore
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.service import GoalService
from personal_markets.identity.factory import (
    get_identity_repository,
    get_identity_service,
    reset_identity_state,
)
from personal_markets.identity.testing import invited_principal
from personal_markets.main import create_app
from personal_markets.profile.photo_store import get_photo_store
from personal_markets.social.adapters import InMemorySocialRepository
from personal_markets.social.service import SocialService
from personal_markets.what_if.repository import InMemorySimulationRepository
from personal_markets.what_if.service import WhatIfService
from personal_markets.wiring import (
    InMemoryGithubCursorStore,
    build_in_memory_workflow,
    get_agent_workflow,
    get_collection_repository,
    get_collection_service,
    get_evidence_service,
    get_github_cursor_store,
    get_goal_service,
    get_integration_repository,
    get_social_repository,
    get_social_service,
    get_what_if_service,
)

POSTGRES_MIGRATION_SKIP = (
    "Isolated Postgres is missing required tables. Apply supabase/migrations 0001-0016 "
    "with scripts/db_migrate.py to PM_TEST_DATABASE_URL. The default playitout_phase0_test "
    "database is not auto-migrated."
)


def isolated_postgres_url() -> str | None:
    explicit = os.environ.get("PM_TEST_DATABASE_URL") or os.environ.get("PM_PHASE0_DATABASE_URL")
    if explicit:
        return explicit
    from sqlalchemy.engine import make_url

    from personal_markets.core.config import Settings

    raw = Settings().database_url
    if not raw:
        return None
    return make_url(raw).set(database="playitout_phase0_test").render_as_string(hide_password=False)


def isolated_app(*, inference: Any | None = None) -> FastAPI:
    reset_identity_state()
    get_integration_repository.cache_clear()
    get_collection_repository.cache_clear()
    get_social_repository.cache_clear()
    repository = InMemoryGoalRepository()
    workflow = build_in_memory_workflow(inference=inference, goal_repository=repository)
    app = create_app()

    @asynccontextmanager
    async def test_lifespan(application: FastAPI):
        application.state.agent_workflow = workflow
        application.state.evidence_service = workflow._inner._deps.evidence
        application.state.upload_service = UploadService(UploadStore())
        application.state.github_cursor_store = InMemoryGithubCursorStore()
        remote = getattr(application.state, "remote_mcp", None)
        if remote is None or getattr(remote, "_test_started", False):
            yield
            return
        remote._test_started = True
        async with remote.session_manager.run():
            yield

    app.router.lifespan_context = test_lifespan
    simulation_repository = InMemorySimulationRepository()
    app.dependency_overrides[get_goal_service] = lambda: GoalService(repository)
    social_repository = InMemorySocialRepository(repository)
    app.dependency_overrides[get_social_service] = lambda: SocialService(
        social_repository, GoalService(repository), get_identity_service(), photos=get_photo_store()
    )
    app.state.social_repository = social_repository
    collection_repository = InMemoryCollectionRepository()
    app.dependency_overrides[get_collection_service] = lambda: CollectionService(
        collection_repository, GoalService(repository)
    )
    app.state.collection_repository = collection_repository

    async def _what_if(request: Request):
        from personal_markets.identity.deps import get_principal
        from personal_markets.identity.factory import get_identity_service

        principal = await get_principal(request, get_identity_service())
        return WhatIfService(
            GoalService(repository),
            simulation_repository,
            owner_id=principal.user_id,
        )

    app.dependency_overrides[get_what_if_service] = _what_if
    app.dependency_overrides[get_agent_workflow] = lambda: workflow
    app.dependency_overrides[get_evidence_service] = lambda: workflow._inner._deps.evidence
    app.dependency_overrides[get_github_cursor_store] = lambda: InMemoryGithubCursorStore()
    app.state.agent_workflow = workflow
    app.state.evidence_service = workflow._inner._deps.evidence
    app.state.upload_service = UploadService(UploadStore())
    app.state.github_cursor_store = InMemoryGithubCursorStore()
    app.state.goal_repository = repository
    principal = invited_principal()
    get_identity_repository().users[principal.user_id] = principal
    get_identity_repository().by_clerk[principal.clerk_user_id] = principal.user_id
    app.state.auth_bypass_principal = principal
    return app
