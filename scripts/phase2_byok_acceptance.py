"""Bounded, opt-in live BYOK acceptance against the isolated Phase 2 Postgres DB.

Never log provider payloads, headers, keys, or raw exceptions. This is a one-shot
operator test, not a general-purpose load test. The two temporary keys are read
from ignored local .env and are deleted by the operator after the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url

from personal_markets.agents.goal_mapping import proposal_to_contract, validation_errors
from personal_markets.agents.json_schema import strict_json_schema
from personal_markets.agents.prompts import load_prompt
from personal_markets.agents.research_service import validate_research
from personal_markets.core.config import Settings, get_settings
from personal_markets.identity.budget import InferenceBudgetService, PostgresBudgetStore
from personal_markets.identity.credentials import CredentialCipher, PostgresCredentialStore
from personal_markets.identity.factory import get_inference_settings_service
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.identity.inference_router import InferenceRouter
from personal_markets.identity.inference_settings import InferenceSettingsService
from personal_markets.identity.testing import make_principal
from personal_markets.integrations.inference_catalog import capability
from personal_markets.integrations.inference_http import NativeInferenceAdapter
from personal_markets.main import create_app
from personal_markets.persistence.database import create_engine
from personal_markets.ports import (
    EvidenceAgentProposal,
    GoalArchitectProposal,
    InferenceRequest,
    InterventionAgentProposal,
    ResearchArtifact,
    ResearchResult,
    ToolDefinition,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/phase2/byok-live-acceptance.json"
MODELS = {"openai": "gpt-5.4-mini", "anthropic": "claude-sonnet-5-5"}
KEY_NAMES = {
    "openai": "PHASE2_TEST_OPENAI_API_KEY",
    "anthropic": "PHASE2_TEST_ANTHROPIC_API_KEY",
}
MAX_POSTS = 6
MAX_ESTIMATED_USD = 0.35


class StatusTransport(httpx.AsyncBaseTransport):
    def __init__(self, provider: str, events: list[dict]):
        self.provider = provider
        self.events = events
        self.inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        self.events.append(
            {
                "provider": self.provider,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
            }
        )
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


async def main() -> None:
    if os.environ.get("PHASE2_BYOK_LIVE") != "1":
        raise SystemExit("Set PHASE2_BYOK_LIVE=1 to authorize bounded live calls")
    local = dotenv_values(ROOT / ".env")
    keys = {
        provider: os.environ.get(name) or local.get(name) for provider, name in KEY_NAMES.items()
    }
    if not all(keys.values()):
        raise SystemExit("Temporary test keys unavailable; no live acceptance attempted")
    base_settings = Settings()
    if not base_settings.database_url:
        raise SystemExit("Isolated test database unavailable")
    url = make_url(base_settings.database_url)
    if url.database not in {"postgres", "playitout", "playitout_phase2_test"} or url.host not in {
        "localhost",
        "127.0.0.1",
    }:
        raise SystemExit("Refusing nonlocal or unexpected database URL")
    isolated = url.set(database="playitout_phase2_test").render_as_string(hide_password=False)
    settings = base_settings.model_copy(
        update={
            "environment": "test",
            "database_url": isolated,
            "openai_max_retries": 0,
            "openai_max_concurrency": 1,
            "inference_run_timeout_seconds": 90.0,
            "openai_timeout_seconds": 75.0,
            "inference_provider": "none",
            "openai_api_key": None,
            "anthropic_api_key": None,
            "spur_api_key": None,
        }
    )
    if not settings.byok_encryption_keys:
        raise SystemExit("Application BYOK encryption keyring unavailable")
    os.environ["PM_ENVIRONMENT"] = "test"
    get_settings.cache_clear()
    engine = create_engine(isolated)
    store = PostgresCredentialStore(engine)
    budget_store = PostgresBudgetStore(engine)
    budget = InferenceBudgetService(budget_store, settings)
    audit = InferenceAudit(budget_store)
    service = InferenceSettingsService(settings, store, budget, audit)
    owners = {p: make_principal(f"phase2-live-{p}-{uuid4()}", invited=True) for p in MODELS}
    owner_map = {o.user_id: o for o in owners.values()}
    events: list[dict] = []
    results: dict = {
        "run_at": datetime.now(UTC).isoformat(),
        "models": MODELS,
        "requests": [],
        "checks": {},
        "http": events,
    }
    app = create_app()
    app.dependency_overrides[get_inference_settings_service] = lambda: service
    router = InferenceRouter(
        settings,
        store,
        budget,
        audit,
        lambda owner_id: asyncio.sleep(0, result=owner_map.get(owner_id)),
        adapter_factory=lambda p, k: NativeInferenceAdapter(
            p, k, transport=StatusTransport(p, events)
        ),
    )
    counts = {p: 0 for p in MODELS}
    costs = {p: 0.0 for p in MODELS}
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")

    async def call(
        provider: str,
        name: str,
        kind: str,
        *,
        instructions: str,
        input_data: dict,
        schema: dict | None = None,
        tools: list[ToolDefinition] | None = None,
        limit: int = 512,
    ):
        model = MODELS[provider]
        serialized = json.dumps(
            {
                "instructions": instructions,
                "input": input_data,
                "schema": schema or {},
                "tools": [t.model_dump() for t in tools or []],
            }
        )
        projected = capability(provider, model).estimate(len(serialized.encode()) + 1024, limit)
        if counts[provider] >= MAX_POSTS or costs[provider] + projected >= MAX_ESTIMATED_USD:
            results["requests"].append(
                {
                    "provider": provider,
                    "name": name,
                    "result": "NOT VERIFIED",
                    "reason": "spend guard",
                }
            )
            return None
        counts[provider] += 1
        request = InferenceRequest(
            instructions=instructions,
            input=input_data,
            output_schema=schema or {},
            tools=tools or [],
            model=None,
            agent_name=name,
            user_id=owners[provider].user_id,
            max_output_tokens=limit,
            timeout_seconds=75,
        )
        before = len(events)
        try:
            response = await getattr(router, f"complete_{kind}")(request)
            if response.provider != provider or response.model != model or response.retries:
                raise AssertionError("provider/model/retry mismatch")
            if not response.usage_reported:
                raise AssertionError("provider did not report usage")
            costs[provider] += response.estimated_cost_usd or projected
            item = {
                "provider": provider,
                "model": model,
                "name": name,
                "kind": kind,
                "result": "LIVE PASS",
                "usage": response.usage,
                "estimated_cost_usd": response.estimated_cost_usd,
                "request_id_sha256_16": hashlib.sha256(
                    (response.request_id or "").encode()
                ).hexdigest()[:16]
                if response.request_id
                else None,
                "tool_calls": len(response.tool_calls),
                "schema_valid": kind == "structured",
            }
            results["requests"].append(item)
            return response
        except Exception as error:
            # The exception type is safe; raw upstream output and request bodies are not.
            costs[provider] += projected
            results["requests"].append(
                {
                    "provider": provider,
                    "model": model,
                    "name": name,
                    "kind": kind,
                    "result": "FAIL",
                    "error_type": type(error).__name__,
                    "http_status": events[-1]["status"] if len(events) > before else None,
                }
            )
            return None

    try:
        async with engine.begin() as conn:
            if not await conn.scalar(text("select to_regclass('provider_credentials')")):
                raise RuntimeError("Phase 2 migrations missing from isolated DB")
            for owner in owners.values():
                await conn.execute(
                    text("insert into app_users (id, clerk_user_id) values (:id, :clerk)"),
                    {"id": owner.user_id, "clerk": owner.clerk_user_id},
                )
        for provider, owner in owners.items():
            app.state.auth_bypass_principal = owner
            key = keys[provider]
            assert key is not None
            saved = await client.put(
                f"/api/v1/settings/inference/credentials/{provider}", json={"api_key": key}
            )
            results["checks"][f"{provider}_save_status"] = saved.status_code
            if saved.status_code != 200:
                continue
            first_version = saved.json()["version"]
            validated = await client.post(
                f"/api/v1/settings/inference/credentials/{provider}/validate"
            )
            results["checks"][f"{provider}_validate_status"] = validated.status_code
            view = await client.get("/api/v1/settings/inference")
            row = await store.get(owner.user_id, provider)
            assert row and key not in row.ciphertext and key not in view.text
            cipher = CredentialCipher(settings.byok_encryption_keys, settings.byok_active_key_id)
            try:
                cipher.decrypt(
                    next(o.user_id for o in owners.values() if o != owner), provider, row.ciphertext
                )
            except Exception:
                owner_binding = True
            else:
                owner_binding = False
            preference = await client.put(
                "/api/v1/settings/inference",
                json={"mode": "byok", "provider": provider, "model": MODELS[provider]},
            )
            assert preference.status_code == 200
            results["checks"][f"{provider}_encrypted_owner_bound"] = owner_binding
            results["checks"][f"{provider}_settings_secret_absent"] = key not in view.text
            results["checks"][f"{provider}_credential_version"] = first_version
            results["checks"][f"{provider}_other_owner_read_denied"] = (
                await store.get(next(o.user_id for o in owners.values() if o != owner), provider)
            ) is None
            invalid = await client.put(
                "/api/v1/settings/inference",
                json={"mode": "byok", "provider": provider, "model": "unsupported-model"},
            )
            results["checks"][f"{provider}_invalid_model_status"] = invalid.status_code
            # Save again: encrypted credential version must rotate, without a generation call.
            replaced = await client.put(
                f"/api/v1/settings/inference/credentials/{provider}", json={"api_key": key}
            )
            results["checks"][f"{provider}_version_rotated"] = (
                replaced.status_code == 200 and replaced.json()["version"] != first_version
            )

        simple_schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
        for provider in MODELS:
            if await store.get(owners[provider].user_id, provider) is None:
                continue
            await call(
                provider,
                "acceptance_structured",
                "structured",
                instructions="Return answer as a one-word JSON string: ready.",
                input_data={"prompt": "Say ready"},
                schema=simple_schema,
                limit=256,
            )
            await call(
                provider,
                "acceptance_text",
                "text",
                instructions="Reply with exactly READY.",
                input_data={"prompt": "Confirm"},
                limit=192,
            )
            tool = ToolDefinition(
                name="record_progress",
                description="Record the given count",
                input_schema={
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                    "required": ["count"],
                    "additionalProperties": False,
                },
            )
            await call(
                provider,
                "acceptance_tools",
                "tools",
                instructions="Call record_progress with count=2. Do not answer in text.",
                input_data={"count": 2},
                tools=[tool],
                limit=256,
            )

        goal_response = await call(
            "openai",
            "goal_architect",
            "structured",
            instructions=load_prompt("goal_architect").text,
            input_data={
                "user_intent": (
                    "I want a job offer by 2027-04-30. "
                    "I can spend 8 hours weekly and have submitted 12 applications."
                )
            },
            schema=strict_json_schema(GoalArchitectProposal),
            limit=1400,
        )
        if goal_response:
            try:
                proposal = GoalArchitectProposal.model_validate(goal_response.structured_output)
                errors = validation_errors(proposal)
                contract = (
                    proposal_to_contract(proposal)
                    if not errors and proposal.ready_to_commit
                    else None
                )
                results["checks"]["goal_architect_domain"] = "LIVE PASS" if contract else "FAIL"
                results["checks"]["goal_architect_validation_errors"] = errors
                results["checks"]["goal_architect_forecast_spec"] = bool(
                    contract and contract.model_requirements.get("forecast_spec")
                )
            except Exception as error:
                results["checks"]["goal_architect_domain"] = "FAIL:" + type(error).__name__

        evidence_response = await call(
            "anthropic",
            "evidence",
            "structured",
            instructions=load_prompt("evidence").text,
            input_data={
                "text": "I sent five more job applications today; I currently have 17 total.",
                "source_type": "manual",
                "goal": "Receive a job offer",
            },
            schema=strict_json_schema(EvidenceAgentProposal),
            limit=1100,
        )
        if evidence_response:
            try:
                parsed = EvidenceAgentProposal.model_validate(evidence_response.structured_output)
                kinds = {event.observation_kind for event in parsed.events}
                results["checks"]["evidence_observation_kinds"] = sorted(k for k in kinds if k)
                results["checks"]["evidence_typed"] = (
                    "LIVE PASS" if {"increment", "snapshot"} <= kinds else "FAIL"
                )
            except Exception as error:
                results["checks"]["evidence_typed"] = "FAIL:" + type(error).__name__

        reference = {
            "source": "https://example.org/frozen/phase2",
            "source_type": "frozen",
            "claim": "Local illustrative reference; no empirical effect estimate.",
            "retrieved_at": datetime.now(UTC).isoformat(),
        }
        research_response = await call(
            "anthropic",
            "research",
            "structured",
            instructions=(
                "Synthesize only retained reference material. "
                "Make no numeric parameter claim. Add no external sources."
            ),
            input_data={
                "question": "What evidence supports a job-offer prior?",
                "references": [reference],
            },
            schema=strict_json_schema(ResearchArtifact),
            limit=1150,
        )
        if research_response:
            try:
                artifact = ResearchArtifact.model_validate(research_response.structured_output)
                from personal_markets.ports import ResearchClaim

                injected = ResearchClaim(
                    claim="Irrelevant",
                    source="https://unseen.example/false",
                    retrieved_at=reference["retrieved_at"],
                    source_type="web",
                    evidence_class="assumption",
                )
                tested = artifact.model_copy(update={"claims": artifact.claims + [injected]})
                filtered = validate_research(
                    tested,
                    ResearchResult(
                        claims=[reference], retrieved_at=datetime.now(UTC), provenance=[]
                    ),
                    True,
                )
                results["checks"]["research_irrelevant_rejected"] = all(
                    claim.source != injected.source for claim in filtered.claims
                )
                results["checks"]["research_typed"] = "LIVE PASS"
            except Exception as error:
                results["checks"]["research_typed"] = "FAIL:" + type(error).__name__

        intervention_response = await call(
            "openai",
            "intervention",
            "structured",
            instructions=(
                "Map the proposed change to typed state edits. "
                "Never output final probability or invented effect sizes."
            ),
            input_data={
                "action": "I will increase weekly job applications from 5 to 8.",
                "allowed_metrics": ["applications_per_week"],
                "goal_type": "deadline_event",
            },
            schema=strict_json_schema(InterventionAgentProposal),
            limit=1200,
        )
        if intervention_response:
            try:
                proposal = InterventionAgentProposal.model_validate(
                    intervention_response.structured_output
                )
                results["checks"]["intervention_typed"] = "LIVE PASS"
                results["checks"]["intervention_changes"] = len(proposal.changes)
                results["checks"]["intervention_probability_change_blocked"] = all(
                    "probability" not in change.metric.lower() for change in proposal.changes
                )
            except Exception as error:
                results["checks"]["intervention_typed"] = "FAIL:" + type(error).__name__

        for provider, owner in owners.items():
            results["checks"][f"{provider}_ledger"] = await audit.byok_summary(owner.user_id)
            counters = await budget_store.counters(str(owner.user_id))
            results["checks"][f"{provider}_hosted_tokens"] = counters.spent_tokens
            app.state.auth_bypass_principal = owner
            deleted = await client.delete(f"/api/v1/settings/inference/credentials/{provider}")
            results["checks"][f"{provider}_delete_status"] = deleted.status_code
            results["checks"][f"{provider}_deleted"] = (
                await store.get(owner.user_id, provider) is None
            )
            before = len(events)
            await call(
                provider,
                "deleted_credential",
                "text",
                instructions="Say ready",
                input_data={"prompt": "ready"},
                limit=64,
            )
            results["checks"][f"{provider}_deleted_no_http"] = len(events) == before
        results["estimated_totals_usd"] = costs
        results["post_attempts"] = counts
    finally:
        # Always remove test credentials, even if a validation or assertion fails.
        for provider, owner in owners.items():
            for candidate in MODELS:
                await store.delete(owner.user_id, candidate)
            remaining = [await store.get(owner.user_id, candidate) for candidate in MODELS]
            results["checks"][f"{provider}_cleanup_confirmed"] = all(
                item is None for item in remaining
            )
        await client.aclose()
        await engine.dispose()
        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
