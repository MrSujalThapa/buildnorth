import os
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from personal_markets.agents.graph import LangGraphAgentWorkflow
from personal_markets.agents.state import AgentDependencies
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.goals.service import GoalService
from personal_markets.integrations.fake_inference import ScriptedInferenceProvider
from personal_markets.integrations.research import (
    CompositeResearchProvider,
    FrozenReferenceProvider,
    MonidResearchProvider,
)
from personal_markets.persistence.agent_store import (
    InMemoryAgentRunStore,
    PostgresEvidenceRepository,
)
from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresGoalRepository
from personal_markets.ports import ResumePayload, WorkflowRequest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_checkpointer_survives_new_workflow_instance() -> None:
    url = os.environ.get("PM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PM_TEST_DATABASE_URL is not configured")
    thread_id = uuid4()
    engine = create_engine(url)
    goal_id = None
    try:
        async with AsyncPostgresSaver.from_conn_string(url) as checkpointer:
            await checkpointer.setup()
            deps = AgentDependencies(
                settings=Settings(environment="test", database_url=url),
                inference=ScriptedInferenceProvider(),
                research=CompositeResearchProvider(
                    FrozenReferenceProvider(), MonidResearchProvider(False, None, None)
                ),
                goals=GoalService(PostgresGoalRepository(engine)),
                evidence=EvidenceService(PostgresEvidenceRepository(engine)),
                run_store=InMemoryAgentRunStore(),
            )
            first = LangGraphAgentWorkflow(deps, checkpointer)
            snapshot = await first.start(
                WorkflowRequest(
                    kind="create_goal",
                    intent="Receive an SWE offer by August 2027",
                    thread_id=thread_id,
                )
            )
            assert snapshot.status == "needs_input"
            second = LangGraphAgentWorkflow(deps, checkpointer)
            resumed = await second.resume(thread_id, ResumePayload(confirmed=True))
            assert resumed.goal is not None
            goal_id = resumed.goal.goal_id
            assert resumed.status in {"limited", "completed", "withheld"}
    finally:
        if goal_id is not None:
            async with engine.begin() as connection:
                await connection.execute(
                    text("delete from forecast_reviews where goal_id = :gid"), {"gid": goal_id}
                )
                await connection.execute(
                    text("delete from csv_import_jobs where goal_id = :gid"), {"gid": goal_id}
                )
                await connection.execute(
                    text("delete from workflow_threads where id = :tid"), {"tid": thread_id}
                )
                await connection.execute(
                    text("delete from goal_evidence where goal_id = :gid"), {"gid": goal_id}
                )
                await connection.execute(
                    text("delete from goals where id = :gid"), {"gid": goal_id}
                )
        await engine.dispose()
