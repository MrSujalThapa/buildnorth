from typing import Any

import pytest

from personal_markets.agents.budget import InMemoryUsageStore, TokenBudget
from personal_markets.core.config import AUTHENTICATED_SPUR_MODEL, Settings
from personal_markets.core.errors import ProviderNotConfiguredError, SemanticProviderError
from personal_markets.identity.inference_router import InferenceRouter, hosted_provider
from personal_markets.integrations.spur import SpurInferenceProvider
from personal_markets.ports import InferenceRequest
from personal_markets.wiring import build_inference


def test_spur_requires_authenticated_model_id() -> None:
    assert (
        Settings(spur_model=AUTHENTICATED_SPUR_MODEL).resolved_spur_model()
        == AUTHENTICATED_SPUR_MODEL
    )
    assert Settings(spur_model="").resolved_spur_model() == AUTHENTICATED_SPUR_MODEL
    for model in ("glm-5.2", "spur-glm-5-2", "spur-glm-5-3"):
        with pytest.raises(ProviderNotConfiguredError, match=AUTHENTICATED_SPUR_MODEL):
            Settings(spur_model=model).resolved_spur_model()


def test_all_hosted_agents_use_owner_scoped_router() -> None:
    provider = build_inference(_settings( inference_provider="spur",
        spur_api_key="sk-spur-test"), InMemoryUsageStore())
    assert isinstance(provider, InferenceRouter)


def test_auto_prefers_spur_without_cross_provider_fallback() -> None:
    settings = _settings( inference_provider="auto", spur_api_key="spur-key",
                        openai_api_key="openai-key")
    assert hosted_provider(settings) == "spur"
    assert hosted_provider(settings.model_copy(update={"inference_provider": "openai"})) == "openai"
    assert hosted_provider(settings.model_copy(update={"inference_provider": "none"})) == "none"


def test_unknown_provider_is_not_auto_selected() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        hosted_provider(_settings( inference_provider="typo"))


def test_spur_does_not_remap_openai_or_unknown_model_ids() -> None:
    provider = SpurInferenceProvider(api_key="sk-spur-test", base_url="https://ai.spuric.com/v1",
        default_model="spur-glm-5-3", budget=TokenBudget(InMemoryUsageStore(), 10_000, 10_000, 1))
    for model in ("gpt-5.4-mini", "spur-unknown"):
        with pytest.raises(SemanticProviderError):
            provider._resolve_model(InferenceRequest(instructions="x", input={},
                output_schema={"type": "object"}, model=model, agent_name="evidence"))


def _settings(**kwargs: Any) -> Settings:
    config: dict[str, Any] = {"_env_file": None, **kwargs}
    return Settings(**config)
