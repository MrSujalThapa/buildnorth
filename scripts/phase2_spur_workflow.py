"""Opt-in live Spur semantics + isolated Postgres + deterministic counterfactual proof."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import text
from sqlalchemy.engine import make_url

from personal_markets.agents.graph import LangGraphAgentWorkflow
from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.agents.state import AgentDependencies
from personal_markets.core.config import Settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.hiring import aggregate_funnel_from_evidence
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
from personal_markets.ports import ResumePayload, WorkflowRequest
from personal_markets.what_if.domain import InterventionChangeInput, WhatIfRequest
from personal_markets.what_if.repository import PostgresSimulationRepository
from personal_markets.what_if.service import WhatIfService


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--intervention-only", action="store_true", help="Continue the latest persisted test goal"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize the bounded calls")
    settings = Settings().model_copy(
        update={
            "inference_provider": "spur",
            "inference_model": "spur-glm-5-3",
            "openai_max_retries": 0,
            "openai_max_output_tokens": 4096,
            "openai_timeout_seconds": 90,
            "intervention_regex_fallback": False,
        }
    )
    if not settings.database_url or not settings.spur_api_key:
        raise RuntimeError("NOT VERIFIED: configure the test database and Spur credential")
    url = (
        make_url(settings.database_url)
        .set(database="playitout_phase2_test")
        .render_as_string(hide_password=False)
    )
    engine = create_engine(url)
    owner = make_principal(
        f"phase2-live-flow-{uuid4()}",
        invited=True,
        hosted=True,
        quota_usd=0.30,
        quota_tokens=60_000,
    )
    result: dict[str, object] = {
        "live_provider": "spur",
        "model": "spur-glm-5-3",
        "database": "isolated playitout_phase2_test",
        "identity": "isolated test principal; not a live Clerk login",
    }
    prior = (
        json.loads(await asyncio.to_thread(Path("artifacts/phase2/spur-workflow.json").read_text))
        if args.intervention_only
        else None
    )
    goal_id: UUID
    if prior:
        result.update(prior)
        result.pop("error_type", None)
        result.pop("message", None)
        result["continuation"] = "Intervention only, using the existing isolated persisted goal"
        owner.user_id = UUID(prior["evidence_increment"]["debug"]["user_id"])
        goal_id = UUID(prior["evidence_increment"]["goal"]["goal_id"])
    try:
        async with engine.begin() as conn:
            if prior:
                clerk = await conn.scalar(
                    text("select clerk_user_id from app_users where id=:id"), {"id": owner.user_id}
                )
                if not clerk or not str(clerk).startswith("phase2-live-flow-"):
                    raise ValueError("Continuation requires an isolated Phase 2 proof identity")
                owner.clerk_user_id = str(clerk)
            else:
                await conn.execute(
                    text("insert into app_users (id, clerk_user_id) values (:id,:clerk)"),
                    {"id": owner.user_id, "clerk": owner.clerk_user_id},
                )

        async def lookup(user: UUID) -> Principal | None:
            return owner if user == owner.user_id else None

        ledger = InMemoryBudgetStore()
        router = InferenceRouter(
            settings,
            InMemoryCredentialStore(),
            InferenceBudgetService(ledger, settings),
            InferenceAudit(ledger),
            lookup,
        )
        deps = AgentDependencies(
            settings,
            router,
            FrozenReferenceProvider(),
            GoalService(PostgresGoalRepository(engine)),
            EvidenceService(PostgresEvidenceRepository(engine)),
            PostgresAgentRunStore(engine),
            BaselineForecastService(PostgresBaselineForecastRepository(engine)),
            ResearchStore(engine),
        )
        if not prior:
            workflow = LangGraphAgentWorkflow(deps, MemorySaver())
            draft = await workflow.start(
                WorkflowRequest(
                    kind="create_goal",
                    user_id=owner.user_id,
                    intent=("Receive at least one software engineering internship offer "
                            "by 2027-08-31. Success means an actual written offer, not an "
                            "interview. Track applications and hiring stages."),
                )
            )
            result["architect"] = draft.model_dump(mode="json")
            if not draft.interrupt or draft.interrupt.type != "confirm_contract":
                raise ValueError("Goal requires further clarification; no contract auto-approved")
            created = await workflow.resume(draft.thread_id, ResumePayload(confirmed=True))
            if created.goal is None:
                raise ValueError("Goal was not committed")
            goal_id = created.goal.goal_id
            first = await workflow.start(
                WorkflowRequest(
                    kind="add_evidence",
                    goal_id=created.goal.goal_id,
                    user_id=owner.user_id,
                    evidence_text="I currently have 18 applications submitted.",
                )
            )
            result["evidence_snapshot"] = first.model_dump(mode="json")
            second = await workflow.start(
                WorkflowRequest(
                    kind="add_evidence",
                    goal_id=created.goal.goal_id,
                    user_id=owner.user_id,
                    evidence_text="I sent five more applications today.",
                )
            )
            result["evidence_increment"] = second.model_dump(mode="json")
        rows = await deps.evidence.list_for_goal(goal_id)
        result["aggregated_applications"] = aggregate_funnel_from_evidence(rows).applications
        history = await PostgresBaselineForecastRepository(engine).load_history(goal_id)
        result["published_history_count"] = len(history)
        result["publication_survives_reload"] = len(history) == 2
        # One additional semantic call; simulation itself remains deterministic.
        intervention = InterventionAgentService(
            settings,
            router,
            FrozenReferenceProvider(),
            deps.goals,
            deps.evidence,
            deps.run_store,
            owner.user_id,
        )
        parsed = await intervention.parse(
            str(goal_id),
            "What if I submit 5 additional applications each week until the deadline?",
        )
        result["intervention"] = parsed.model_dump(mode="json")
        simulations = WhatIfService(
            deps.goals,
            PostgresSimulationRepository(engine),
            evidence=deps.evidence,
            owner_id=owner.user_id,
        )
        state = await simulations.baseline_state(str(goal_id))
        result["what_if_persisted_baseline"] = state.current_probability
        if parsed.changes:
            simulation = await simulations.simulate(
                WhatIfRequest(
                    goal_id=str(goal_id),
                    current_value=state.current_value or 0,
                    target_value=state.target_value or 1,
                    periods=state.periods or 1,
                    assumptions=state.assumptions,
                    parsed_changes=[
                        InterventionChangeInput.model_validate(change.model_dump())
                        for change in parsed.changes
                    ],
                )
            )
            result["simulation"] = simulation.model_dump(mode="json")
        after = await PostgresBaselineForecastRepository(engine).load_history(goal_id)
        result["baseline_history_unchanged_after_what_if"] = len(after) == len(history)
        result["estimated_spend_usd"] = sum(
            float(str(row["estimated_cost_usd"])) for row in ledger.ledger
        )
        result["status"] = (
            "PASS"
            if len(history) == 2 and aggregate_funnel_from_evidence(rows).applications == 23
            else "FAIL"
        )
    except Exception as error:
        result.update({"status": "FAIL", "error_type": type(error).__name__, "message": str(error)})
    finally:
        await engine.dispose()
    path = Path("artifacts/phase2/spur-workflow.json")
    path.parent.mkdir(exist_ok=True, parents=True)
    await asyncio.to_thread(path.write_text, json.dumps(result, indent=2, default=str),
                           encoding="utf-8")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key
                not in {
                    "architect",
                    "evidence_snapshot",
                    "evidence_increment",
                    "intervention",
                    "simulation",
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
