import os

import pytest

from personal_markets.agents.budget import InMemoryUsageStore, TokenBudget
from personal_markets.agents.retries import classify_provider_error
from personal_markets.core.errors import (
    PermanentProviderError,
    ProviderBudgetExceededError,
    TransientProviderError,
)
from personal_markets.integrations.fake_inference import (
    FailingInferenceProvider,
    ScriptedInferenceProvider,
)
from personal_markets.ports import InferenceRequest


def _request() -> InferenceRequest:
    return InferenceRequest(
        instructions="return json",
        input={"intent": "x"},
        output_schema={"type": "object", "properties": {}, "additionalProperties": False},
        agent_name="goal_architect",
    )


@pytest.mark.asyncio
async def test_scripted_provider_returns_structured_output() -> None:
    provider = ScriptedInferenceProvider()
    response = await provider.complete_structured(_request())
    assert "title" in response.structured_output
    assert "probability" not in response.structured_output


@pytest.mark.asyncio
async def test_failing_provider_surfaces_permanent_auth_error() -> None:
    provider = FailingInferenceProvider(PermanentProviderError("invalid api key"))
    with pytest.raises(PermanentProviderError):
        await provider.complete_structured(_request())


def test_timeout_is_transient() -> None:
    assert classify_provider_error(TimeoutError("timed out")) is TransientProviderError


@pytest.mark.asyncio
async def test_budget_fails_closed() -> None:
    budget = TokenBudget(
        InMemoryUsageStore(), high_volume_limit=10, premium_limit=10, max_cost_usd=0.0000001
    )
    await budget.record("gpt-5.4", 1000, 1000)
    with pytest.raises(ProviderBudgetExceededError):
        await budget.ensure_allowed("gpt-5.4")


@pytest.mark.asyncio
async def test_live_openai_structured_smoke() -> None:
    if os.environ.get("PM_OPENAI_SMOKE") != "1":
        pytest.skip("set PM_OPENAI_SMOKE=1 to run the live OpenAI smoke")
    from personal_markets.core.config import Settings
    from personal_markets.integrations.openai import OpenAIInferenceProvider

    settings = Settings()
    if not settings.openai_api_key:
        pytest.skip("PM_OPENAI_API_KEY is not configured")
    provider = OpenAIInferenceProvider(
        api_key=settings.openai_api_key,
        default_model=settings.openai_evidence_model,
        budget=TokenBudget(
            InMemoryUsageStore(), high_volume_limit=10_000, premium_limit=10_000, max_cost_usd=0.25
        ),
        max_concurrency=1,
        max_output_tokens=32,
    )
    response = await provider.complete_structured(
        InferenceRequest(
            instructions=(
                "Return JSON matching the schema. Set ok to true. "
                "Do not estimate or return a probability."
            ),
            input={"ping": "pong"},
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
            model=settings.openai_evidence_model,
            pool="high_volume",
            agent_name="smoke",
        )
    )
    assert response.structured_output.get("ok") is True
    assert "probability" not in response.structured_output
    assert response.provider == "openai"


@pytest.mark.asyncio
async def test_authenticated_spur_model_is_in_catalog() -> None:
    from personal_markets.core.config import AUTHENTICATED_SPUR_MODEL, Settings

    settings = Settings()
    if not settings.spur_api_key:
        pytest.skip("SPUR_API_KEY is not configured")
    import httpx

    async with httpx.AsyncClient(base_url=settings.spur_base_url, timeout=20.0) as client:
        response = await client.get(
            "/models",
            headers={"Authorization": f"Bearer {settings.spur_api_key}"},
        )
    assert response.status_code == 200
    ids = [item.get("id") for item in response.json().get("data", [])]
    assert AUTHENTICATED_SPUR_MODEL in ids
    assert "glm-5.2" not in ids


@pytest.mark.asyncio
async def test_live_spur_structured_smoke() -> None:
    if os.environ.get("PM_SPUR_SMOKE") != "1":
        pytest.skip("set PM_SPUR_SMOKE=1 to run the live Spur smoke")
    from personal_markets.core.config import Settings
    from personal_markets.integrations.spur import SpurInferenceProvider

    settings = Settings()
    if not settings.spur_api_key:
        pytest.skip("SPUR_API_KEY is not configured")
    provider = SpurInferenceProvider(
        api_key=settings.spur_api_key,
        base_url=settings.spur_base_url,
        default_model=settings.resolved_spur_model(),
        budget=TokenBudget(
            InMemoryUsageStore(), high_volume_limit=10_000, premium_limit=10_000, max_cost_usd=0.25
        ),
        max_concurrency=1,
        max_output_tokens=1024,
    )
    response = await provider.complete_structured(
        InferenceRequest(
            instructions=(
                "Return JSON matching the schema. Set ok to true. "
                "Do not estimate or return a probability."
            ),
            input={"ping": "pong"},
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
            model=settings.resolved_spur_model(),
            pool="high_volume",
            agent_name="smoke",
        )
    )
    assert response.structured_output.get("ok") is True
    assert "probability" not in response.structured_output
    assert response.provider == "spur"
