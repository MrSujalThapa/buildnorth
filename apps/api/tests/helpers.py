from contextlib import asynccontextmanager

from fastapi import FastAPI

from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.goals.service import GoalService
from personal_markets.main import create_app
from personal_markets.what_if.repository import InMemorySimulationRepository
from personal_markets.what_if.service import WhatIfService
from personal_markets.wiring import (
    InMemoryGithubCursorStore,
    build_in_memory_workflow,
    get_agent_workflow,
    get_evidence_service,
    get_github_cursor_store,
    get_goal_service,
    get_integration_repository,
    get_what_if_service,
)


def isolated_app() -> FastAPI:
    get_integration_repository.cache_clear()
    repository = InMemoryGoalRepository()
    workflow = build_in_memory_workflow(goal_repository=repository)
    app = create_app()

    @asynccontextmanager
    async def test_lifespan(application: FastAPI):
        application.state.agent_workflow = workflow
        application.state.evidence_service = workflow._inner._deps.evidence
        application.state.github_cursor_store = InMemoryGithubCursorStore()
        yield

    app.router.lifespan_context = test_lifespan
    simulation_repository = InMemorySimulationRepository()
    app.dependency_overrides[get_goal_service] = lambda: GoalService(repository)
    app.dependency_overrides[get_what_if_service] = lambda: WhatIfService(
        GoalService(repository), simulation_repository
    )
    app.dependency_overrides[get_agent_workflow] = lambda: workflow
    app.dependency_overrides[get_evidence_service] = lambda: workflow._inner._deps.evidence
    app.dependency_overrides[get_github_cursor_store] = lambda: InMemoryGithubCursorStore()
    app.state.agent_workflow = workflow
    app.state.evidence_service = workflow._inner._deps.evidence
    app.state.github_cursor_store = InMemoryGithubCursorStore()
    return app
