import asyncio
import base64
import json
import os
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.config import Settings
from personal_markets.agents.intervention_service import InterventionAgentService
from personal_markets.identity.budget import InferenceBudgetService, InMemoryBudgetStore
from personal_markets.identity.credentials import (
    CredentialCipher,
    InferencePreference,
    InMemoryCredentialStore,
    UserProvider,
)
from personal_markets.identity.domain import Principal
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.identity.inference_router import InferenceRouter
from personal_markets.integrations.fake_inference import default_agent_script
from personal_markets.integrations.inference_http import NativeInferenceAdapter
from personal_markets.integrations.research import FrozenReferenceProvider
from personal_markets.ports import (
    EvidenceAgentProposal,
    EvidenceEventProposal,
    GoalArchitectProposal,
    InferenceRequest,
    InterventionAgentProposal,
)
from personal_markets.what_if.domain import InterventionChangeInput, WhatIfRequest
from personal_markets.what_if.repository import InMemorySimulationRepository
from personal_markets.what_if.service import WhatIfService


@pytest.mark.parametrize(
    "mode,provider,model",
    [
        ("hosted", "spur", "spur-deepseek-v4-flash"),
        ("byok", "openai", "gpt-5.4-mini"),
        ("byok", "anthropic", "claude-sonnet-5-5"),
    ],
)
def test_scenarios_a_b_c_native_protocol_to_persisted_forecast(
    mode: str, provider: str, model: str
) -> None:
    app = isolated_app()
    principal = app.state.auth_bypass_principal
    settings = Settings(
        inference_provider="spur",
        inference_model="spur-deepseek-v4-flash",
        spur_api_key="platform-key",
        openai_max_retries=0,
        byok_encryption_keys={"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()},
    )
    credentials, budget_store = InMemoryCredentialStore(), InMemoryBudgetStore()
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(str(req.url.host))
        if provider == "openai":
            schema, payload = body["text"]["format"]["schema"], json.loads(body["input"])
        else:
            payload = json.loads(body["messages"][-1]["content"])
            schema = body.get("output_config", {}).get("format", {}).get("schema")
            if provider == "spur":
                schema = json.loads(body["messages"][0]["content"].split("schema:\n")[-1])
        if "goal_type" in schema["properties"]:
            output = GoalArchitectProposal.model_validate(
                default_agent_script(
                    InferenceRequest(
                        instructions="test",
                        input=payload,
                        output_schema={},
                        agent_name="goal_architect",
                    )
                )
            ).model_dump()
            output["current_state_known"] = [
                {"key": key, "value": value}
                for key, value in output["current_state_known"].items()
            ]
        elif "pricing_status" in schema["properties"]:
            output = InterventionAgentProposal.model_validate(
                default_agent_script(
                    InferenceRequest(
                        instructions="test",
                        input=payload,
                        output_schema={},
                        agent_name="intervention",
                    )
                )
            ).model_dump()
        else:
            more = "five more" in payload["evidence_text"]
            event = EvidenceEventProposal(
                event_type="observation",
                domain="career",
                metric="applications",
                numeric_value=5 if more else 18,
                unit="count",
                observed_at=datetime.now(UTC).isoformat(),
                source_type="manual",
                summary=payload["evidence_text"],
                observation_kind="increment" if more else "snapshot",
            )
            output = EvidenceAgentProposal(events=[event]).model_dump()
        raw = json.dumps(output)
        if provider == "openai":
            return httpx.Response(
                200,
                json={
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": raw}]}
                    ],
                    "usage": {"input_tokens": 20, "output_tokens": 10},
                },
            )
        if provider == "anthropic":
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": raw}],
                    "usage": {"input_tokens": 20, "output_tokens": 10},
                    "stop_reason": "end_turn",
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": raw}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            },
        )

    async def lookup(owner: UUID) -> Principal | None:
        return principal if principal.user_id == owner else None

    if mode == "byok":

        async def configure() -> None:
            encrypted = CredentialCipher(settings.byok_encryption_keys, "v1").encrypt(
                principal.user_id, provider, "owned-key"
            )
            await credentials.put(
                principal.user_id, cast(UserProvider, provider), encrypted, "-key"
            )
            await credentials.set_preference(
                principal.user_id,
                InferencePreference(
                    mode="byok", provider=cast(UserProvider, provider), model=model
                ),
            )

        asyncio.run(configure())
    router = InferenceRouter(
        settings,
        credentials,
        InferenceBudgetService(budget_store, settings),
        InferenceAudit(budget_store),
        lookup,
        lambda provider, key: NativeInferenceAdapter(
            provider, key, transport=httpx.MockTransport(handler)
        ),
    )
    deps = app.state.agent_workflow._inner._deps
    deps.inference = router
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/agent/threads",
            json={"kind": "create_goal", "intent": "Receive an SWE offer by August 2027"},
        )
        assert created.status_code == 200, created.text
        resumed = client.post(
            f"/api/v1/agent/threads/{created.json()['thread_id']}/resume", json={"confirmed": True}
        )
        assert resumed.status_code == 200, resumed.text
        goal_id = resumed.json()["goal"]["goal_id"]
        assert (
            resumed.json()["goal"]["model_requirements"]["forecast_spec"]["family"]
            == "deadline_event_hazard"
        )
        first = client.post(
            f"/api/v1/goals/{goal_id}/evidence",
            json={"evidence_text": "I currently have 18 applications submitted"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["pricing"]["priced"]
        probability = first.json()["pricing"]["raw_probability"]
        receipt = first.json()["pricing"]["receipt"]
        assert receipt["llm_used_for_probability"] is False
        assert receipt["forecast_spec"]["status"] == "READY"
        second = client.post(
            f"/api/v1/goals/{goal_id}/evidence",
            json={"evidence_text": "I sent five more applications today"},
        )
        assert second.status_code == 200, second.text
        assert second.json()["pricing"]["raw_probability"] != probability
        before = len(calls)
        manual = client.post(
            f"/api/v1/goals/{goal_id}/evidence/manual",
            json={
                "entries": [
                    {"key": "applications", "label": "Applications", "value": 30, "unit": "count"}
                ]
            },
        )
        assert manual.status_code == 200
        assert len(calls) == before
        rows = client.get(f"/api/v1/goals/{goal_id}/evidence").json()
        assert [r["provenance"]["observation_kind"] for r in rows] == [
            "snapshot",
            "increment",
            "snapshot",
        ]
        # The publication repository is the same one read after the graph completes.
        history = asyncio.run(
            deps.baseline_forecasts.published_history(__import__("uuid").UUID(goal_id))
        )
        assert len(history) == 3
        assert history[-1].receipt["final_probability"] is not None
        intervention = asyncio.run(
            InterventionAgentService(
                settings,
                router,
                FrozenReferenceProvider(),
                deps.goals,
                deps.evidence,
                deps.run_store,
                principal.user_id,
            ).parse(
                goal_id,
                "What if I submit 5 additional applications each week until the deadline?",
            )
        )
        assert intervention.changes
        assert intervention.agent_run_id is None
        simulations = WhatIfService(
            deps.goals,
            InMemorySimulationRepository(),
            evidence=deps.evidence,
            owner_id=principal.user_id,
        )
        state = asyncio.run(simulations.baseline_state(goal_id))
        assert state.priced and state.current_probability is not None
        request = WhatIfRequest(
            goal_id=goal_id,
            current_value=state.current_value or 0,
            target_value=state.target_value or 1,
            periods=state.periods or 1,
            assumptions=state.assumptions,
            parsed_changes=[
                InterventionChangeInput.model_validate(change.model_dump())
                for change in intervention.changes
            ],
        )
        simulation = asyncio.run(simulations.simulate(request))
        replay = asyncio.run(simulations.fast_reprice(request))
        assert simulation.priced and simulation.persisted
        assert simulation.baseline_probability == pytest.approx(state.current_probability)
        assert simulation.scenario_probability == pytest.approx(replay.scenario_probability)
        assert simulation.conditional_on_execution_probability == pytest.approx(
            replay.conditional_on_execution_probability
        )
        assert simulation.expected_uplift_pp == pytest.approx(
            100 * (simulation.scenario_probability - simulation.baseline_probability)
        )
        assert 0 <= simulation.execution_probability <= 1
        assert len(asyncio.run(deps.baseline_forecasts.published_history(UUID(goal_id)))) == 3
    # Architect and two evidence calls; the stated weekly quantity is parsed without inference.
    assert len(budget_store.ledger) == 3
    assert {r["billing_mode"] for r in budget_store.ledger} == {mode}
    assert (asyncio.run(budget_store.counters("global"))).spent_tokens == (
        90 if mode == "hosted" else 0
    )
    assert len(set(calls)) == 1
