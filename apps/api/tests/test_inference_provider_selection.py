import pytest

from personal_markets.agents.budget import InMemoryUsageStore, TokenBudget
from personal_markets.core.config import AUTHENTICATED_SPUR_MODEL, Settings
from personal_markets.core.errors import ProviderNotConfiguredError
from personal_markets.integrations.openai import (
    OpenAIInferenceProvider,
    UnconfiguredOpenAIInferenceProvider,
)
from personal_markets.integrations.spur import SpurInferenceProvider
from personal_markets.identity.hosted import HostedInferenceGateway
from personal_markets.ports import InferenceRequest
from personal_markets.wiring import build_inference


def _inner(provider: object) -> object:
    if isinstance(provider, HostedInferenceGateway):
        return provider._inner
    return provider


def test_spur_requires_authenticated_model_id() -> None:
    assert Settings(spur_model="spur-glm-5-3").resolved_spur_model() == AUTHENTICATED_SPUR_MODEL
    assert Settings(spur_model="").resolved_spur_model() == AUTHENTICATED_SPUR_MODEL
    with pytest.raises(ProviderNotConfiguredError, match="spur-glm-5-3"):
        Settings(spur_model="glm-5.2").resolved_spur_model()
    with pytest.raises(ProviderNotConfiguredError, match="spur-glm-5-3"):
        Settings(spur_model="spur-glm-5-2").resolved_spur_model()


def test_auto_prefers_spur_when_spur_key_present() -> None:
    settings = Settings(
        inference_provider="auto",
        spur_api_key="sk-spur-test",
        openai_api_key="sk-openai-test",
        spur_model="spur-glm-5-3",
    )
    provider = build_inference(settings, InMemoryUsageStore())
    assert isinstance(provider, HostedInferenceGateway)
    assert isinstance(provider._inner, SpurInferenceProvider)


def test_retired_spur_model_id_does_not_silently_remap() -> None:
    settings = Settings(
        inference_provider="spur",
        spur_api_key="sk-spur-test",
        openai_api_key="sk-openai-test",
        spur_model="glm-5.2",
    )
    provider = _inner(build_inference(settings, InMemoryUsageStore()))
    assert isinstance(provider, UnconfiguredOpenAIInferenceProvider)


def test_spur_selection_does_not_fall_back_to_openai_when_unconfigured() -> None:
    settings = Settings(
        inference_provider="spur",
        spur_api_key=None,
        openai_api_key="sk-openai-test",
    )
    provider = _inner(build_inference(settings, InMemoryUsageStore()))
    assert isinstance(provider, UnconfiguredOpenAIInferenceProvider)


def test_spur_selection_does_not_use_openai_key() -> None:
    settings = Settings(
        inference_provider="spur",
        spur_api_key="sk-spur-test",
        openai_api_key="sk-openai-test",
        spur_model="spur-glm-5-3",
    )
    provider = _inner(build_inference(settings, InMemoryUsageStore()))
    assert isinstance(provider, SpurInferenceProvider)
    assert provider._default_model == AUTHENTICATED_SPUR_MODEL


def test_openai_selection_requires_openai_key() -> None:
    settings = Settings(
        inference_provider="openai",
        spur_api_key="sk-spur-test",
        openai_api_key=None,
    )
    provider = _inner(build_inference(settings, InMemoryUsageStore()))
    assert isinstance(provider, UnconfiguredOpenAIInferenceProvider)


def test_openai_selection_uses_openai_when_configured() -> None:
    settings = Settings(
        inference_provider="openai",
        openai_api_key="sk-openai-test",
        openai_goal_model="gpt-5.4-mini",
    )
    provider = build_inference(settings, InMemoryUsageStore())
    assert isinstance(provider, HostedInferenceGateway)
    assert isinstance(provider._inner, OpenAIInferenceProvider)


def test_spur_remaps_openai_model_ids() -> None:
    provider = SpurInferenceProvider(
        api_key="sk-spur-test",
        base_url="https://ai.spuric.com/v1",
        default_model="spur-glm-5-3",
        budget=TokenBudget(
            InMemoryUsageStore(),
            high_volume_limit=10_000,
            premium_limit=10_000,
            max_cost_usd=1.0,
        ),
    )
    request = InferenceRequest(
        instructions="x",
        input={},
        output_schema={"type": "object"},
        model="gpt-5.4-mini",
        fallback_models=["gpt-5.4"],
        agent_name="evidence",
    )
    assert provider._resolve_model(request) == "spur-glm-5-3"
