"""Bounded live BYOK graph acceptance in the isolated Phase 2 database.

Run explicitly with PHASE2_BYOK_WORKFLOW_LIVE=1. Never emit keys, payloads, or
upstream bodies. The local .env is read, not changed; DB credential copies are
removed in finally. This is not proof of a genuine Clerk browser session.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from dotenv import dotenv_values
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import text
from sqlalchemy.engine import make_url

from personal_markets.agents.graph import LangGraphAgentWorkflow
from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.agents.state import AgentDependencies
from personal_markets.core.config import Settings, get_settings
from personal_markets.evidence.service import EvidenceService
from personal_markets.forecasting.hiring import aggregate_funnel_from_evidence
from personal_markets.forecasting.repository import PostgresBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.goals.service import GoalService
from personal_markets.identity.budget import InferenceBudgetService, PostgresBudgetStore
from personal_markets.identity.credentials import PostgresCredentialStore
from personal_markets.identity.factory import get_inference_settings_service
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.identity.inference_router import InferenceRouter
from personal_markets.identity.inference_settings import InferenceSettingsService
from personal_markets.identity.testing import make_principal
from personal_markets.integrations.inference_catalog import capability
from personal_markets.integrations.inference_http import NativeInferenceAdapter
from personal_markets.integrations.research import FrozenReferenceProvider
from personal_markets.main import create_app
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

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/phase2/byok-graph-live.json"
MODELS = {"openai": "gpt-5.4-mini", "anthropic": "claude-sonnet-5-5"}
KEY_NAMES = {
    "openai": "PHASE2_TEST_OPENAI_API_KEY",
    "anthropic": "PHASE2_TEST_ANTHROPIC_API_KEY",
}
MAX_POSTS = 6
MAX_PROJECTED_USD = 0.45


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, provider: str, budget: dict, events: list[dict]):
        self.provider = provider
        self.budget = budget
        self.events = events
        self.inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            # Bound each real dispatch using our known model rates and the provider's
            # max-output parameter. This is only an estimate, never a billing cap.
            body = json.loads(request.content)
            limit = int(body.get("max_output_tokens") or body.get("max_tokens") or 0)
            projected = capability(self.provider, MODELS[self.provider]).estimate(
                len(request.content) + 1024, limit
            )
            if (
                self.budget["posts"] >= MAX_POSTS
                or self.budget["projected_usd"] + projected > MAX_PROJECTED_USD
            ):
                raise RuntimeError("Live workflow spending guard stopped a provider POST")
            self.budget["posts"] += 1
            self.budget["projected_usd"] += projected
        response = await self.inner.handle_async_request(request)
        self.events.append(
            {"method": request.method, "path": request.url.path, "status": response.status_code}
        )
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


async def run_provider(provider: str, key: str, isolated_url: str, keyring: dict) -> dict:
    model = MODELS[provider]
    settings = Settings().model_copy(
        update={
            "environment": "test",
            "database_url": isolated_url,
            "inference_provider": "none",
            "openai_api_key": None,
            "anthropic_api_key": None,
            "spur_api_key": None,
            "openai_max_retries": 0,
            "openai_max_output_tokens": 1600,
            "openai_timeout_seconds": 75,
            "inference_run_timeout_seconds": 100,
            "intervention_regex_fallback": False,
            "byok_encryption_keys": keyring,
        }
    )
    engine = create_engine(isolated_url)
    owner = make_principal(f"phase2-graph-{provider}-{uuid4()}", invited=True)
    store = PostgresCredentialStore(engine)
    budget_store = PostgresBudgetStore(engine)
    budget = InferenceBudgetService(budget_store, settings)
    audit = InferenceAudit(budget_store)
    service = InferenceSettingsService(settings, store, budget, audit)
    events: list[dict] = []
    guard = {"posts": 0, "projected_usd": 0.0}
    result: dict = {
        "provider": provider,
        "model": model,
        "owner_id": str(owner.user_id),
        "started_at": datetime.now(UTC).isoformat(),
        "http": events,
        "status": "NOT VERIFIED",
    }
    app = create_app()
    app.state.auth_bypass_principal = owner
    app.dependency_overrides[get_inference_settings_service] = lambda: service
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('provider_credentials')")):
                raise RuntimeError("Phase 2 migrations missing from isolated database")
            await conn.execute(
                text("insert into app_users (id, clerk_user_id) values (:id,:clerk)"),
                {"id": owner.user_id, "clerk": owner.clerk_user_id},
            )
        saved = await client.put(
            f"/api/v1/settings/inference/credentials/{provider}", json={"api_key": key}
        )
        result["save_status"] = saved.status_code
        if saved.status_code != 200:
            return result
        chosen = await client.put(
            "/api/v1/settings/inference",
            json={"mode": "byok", "provider": provider, "model": model},
        )
        result["preference_status"] = chosen.status_code
        if chosen.status_code != 200:
            return result

        async def lookup(user_id: UUID):
            return owner if user_id == owner.user_id else None

        router = InferenceRouter(
            settings,
            store,
            budget,
            audit,
            lookup,
            adapter_factory=lambda p, k: NativeInferenceAdapter(
                p, k, transport=BoundedTransport(p, guard, events)
            ),
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
        graph = LangGraphAgentWorkflow(deps, MemorySaver())
        draft = await graph.start(
            WorkflowRequest(
                kind="create_goal",
                user_id=owner.user_id,
                intent=(
                    "Receive at least one software engineering internship offer by "
                    "2027-08-31. Success means an actual written offer, not an "
                    "interview. Track applications and hiring stages."
                ),
            )
        )
        result["architect_confirm_required"] = bool(
            draft.interrupt and draft.interrupt.type == "confirm_contract"
        )
        if not result["architect_confirm_required"]:
            result["status"] = "FAIL"
            return result
        created = await graph.resume(draft.thread_id, ResumePayload(confirmed=True))
        if not created.goal:
            result["status"] = "FAIL"
            return result
        goal_id = created.goal.goal_id
        result["goal_id"] = str(goal_id)
        result["forecast_spec_family"] = (
            created.goal.model_requirements.get("forecast_spec") or {}
        ).get("family")

        first = await graph.start(
            WorkflowRequest(
                kind="add_evidence",
                goal_id=goal_id,
                user_id=owner.user_id,
                evidence_text="I currently have 18 applications submitted.",
            )
        )
        second = await graph.start(
            WorkflowRequest(
                kind="add_evidence",
                goal_id=goal_id,
                user_id=owner.user_id,
                evidence_text="I sent five more applications today.",
            )
        )
        result["evidence_statuses"] = [first.status, second.status]
        rows = await deps.evidence.list_for_goal(goal_id)
        result["evidence_kinds"] = [e.provenance.observation_kind for e in rows]
        result["aggregate_applications"] = aggregate_funnel_from_evidence(rows).applications
        before = await PostgresBaselineForecastRepository(engine).load_history(goal_id)
        result["published_history_count"] = len(before)
        result["published_probabilities"] = [p.probability for p in before]
        result["receipt_has_lineage"] = bool(
            before
            and all(
                p.receipt.get("forecast_spec")
                and p.receipt.get("llm_used_for_probability") is False
                for p in before
            )
        )

        parsed = await InterventionAgentService(
            settings,
            router,
            FrozenReferenceProvider(),
            deps.goals,
            deps.evidence,
            deps.run_store,
            owner.user_id,
        ).parse(str(goal_id), "What if I submit 5 additional applications each week?")
        result["intervention_status"] = parsed.pricing_status
        result["intervention_changes"] = [
            {"metric": c.metric, "operation": c.operation, "value": c.value, "unit": c.unit}
            for c in parsed.changes
        ]
        simulations = WhatIfService(
            deps.goals,
            PostgresSimulationRepository(engine),
            evidence=deps.evidence,
            owner_id=owner.user_id,
        )
        state = await simulations.baseline_state(str(goal_id))
        result["baseline_state_priced"] = state.priced
        if not state.priced or not parsed.changes:
            result["status"] = "FAIL"
            return result
        scenario_request = WhatIfRequest(
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
        scenario = await simulations.simulate(scenario_request)
        replay = await simulations.fast_reprice(scenario_request)
        result["simulation"] = {
            "priced": scenario.priced,
            "persisted": scenario.persisted,
            "baseline_probability": scenario.baseline_probability,
            "full_execution_probability": scenario.conditional_on_execution_probability,
            "adjusted_probability": scenario.scenario_probability,
            "execution_probability": scenario.execution_probability,
            "uplift_pp": scenario.expected_uplift_pp,
            "replay_delta": abs(scenario.scenario_probability - replay.scenario_probability),
        }
        after = await PostgresBaselineForecastRepository(engine).load_history(goal_id)
        result["published_history_immutable"] = before == after
        result["research_artifacts"] = len(
            await ResearchStore(engine).list_for_goal(owner.user_id, goal_id)
        )
        result["ledger"] = await audit.byok_summary(owner.user_id)
        result["hosted_tokens"] = (await budget_store.counters(str(owner.user_id))).spent_tokens
        result["status"] = (
            "INTEGRATION PASS"
            if all(
                (
                    result["forecast_spec_family"] == "deadline_event_hazard",
                    result["aggregate_applications"] == 23,
                    result["evidence_kinds"] == ["snapshot", "increment"],
                    len(before) == 2 and before[0].probability != before[1].probability,
                    result["receipt_has_lineage"],
                    scenario.priced
                    and scenario.persisted
                    and result["published_history_immutable"],
                    result["simulation"]["replay_delta"] < 1e-5,
                    abs(
                        scenario.expected_uplift_pp
                        - 100 * (scenario.scenario_probability - scenario.baseline_probability)
                    )
                    < 1e-8,
                    result["hosted_tokens"] == 0,
                    all(
                        e["path"] == ("/v1/responses" if provider == "openai" else "/v1/messages")
                        and e["status"] == 200
                        for e in events
                        if e["method"] == "POST"
                    ),
                )
            )
            else "FAIL"
        )
        return result
    except Exception as error:
        result["status"] = "FAIL"
        result["error_type"] = type(error).__name__
        # Never emit provider error strings, raw responses, or agent payloads.
        return result
    finally:
        result["post_attempts"] = guard["posts"]
        result["projected_guard_usd"] = guard["projected_usd"]
        await store.delete(owner.user_id, provider)
        result["credential_deleted"] = await store.get(owner.user_id, provider) is None
        await client.aclose()
        await engine.dispose()


async def main() -> None:
    if os.environ.get("PHASE2_BYOK_WORKFLOW_LIVE") != "1":
        raise SystemExit("Set PHASE2_BYOK_WORKFLOW_LIVE=1 for bounded provider calls")
    values = dotenv_values(ROOT / ".env")
    keys = {p: os.environ.get(n) or values.get(n) for p, n in KEY_NAMES.items()}
    if not all(keys.values()):
        raise SystemExit("Temporary BYOK test keys unavailable")
    original = Settings()
    if not original.database_url or not original.byok_encryption_keys:
        raise SystemExit("Database or encryption keyring unavailable")
    url = make_url(original.database_url)
    if url.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Refusing nonlocal database")
    isolated = url.set(database="playitout_phase2_test").render_as_string(hide_password=False)
    os.environ["PM_ENVIRONMENT"] = "test"
    get_settings.cache_clear()
    results = []
    for provider in MODELS:
        key = keys[provider]
        assert key is not None
        result = await run_provider(provider, key, isolated, original.byok_encryption_keys)
        results.append(result)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(
            json.dumps(
                {
                    "provider": provider,
                    "status": result["status"],
                    "post_attempts": result["post_attempts"],
                    "credential_deleted": result["credential_deleted"],
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
