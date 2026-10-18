import asyncio
import base64
import json
import os
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    ForbiddenError,
    PermanentProviderError,
    ProviderBudgetExceededError,
    ProviderNotConfiguredError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.identity.budget import InferenceBudgetService, InMemoryBudgetStore
from personal_markets.identity.credentials import (
    CredentialCipher,
    InferencePreference,
    InMemoryCredentialStore,
)
from personal_markets.identity.domain import Principal
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.identity.inference_router import InferenceRouter
from personal_markets.identity.testing import make_principal
from personal_markets.integrations.inference_http import NativeInferenceAdapter, anthropic_schema
from personal_markets.ports import InferenceRequest, InferenceResponse, ToolDefinition

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def request(**kwargs: Any) -> InferenceRequest:
    return InferenceRequest(instructions="Return ok", input={}, output_schema=SCHEMA, **kwargs)


@pytest.mark.parametrize(
    "provider,model",
    [("openai", "gpt-5.4-mini"), ("anthropic", "claude-sonnet-5-5"), ("spur", "spur-glm-5-3")],
)
async def test_native_structured_protocols(provider: str, model: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["model"] == model
        if provider == "anthropic":
            assert req.url.path == "/v1/messages"
            assert req.headers["x-api-key"] == "secret"
            assert body["output_config"]["format"]["schema"] == SCHEMA
            assert "response_format" not in body
            return httpx.Response(
                200,
                json={
                    "id": "a",
                    "content": [{"type": "text", "text": '{"ok":true}'}],
                    "usage": {"input_tokens": 12, "output_tokens": 4},
                    "stop_reason": "end_turn",
                },
            )
        if provider == "openai":
            assert req.url.path == "/v1/responses"
            assert body["store"] is False
            assert body["text"]["format"]["schema"] == SCHEMA
            return httpx.Response(
                200,
                json={
                    "id": "o",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": '{"ok":true}'}],
                        }
                    ],
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 4,
                        "output_tokens_details": {"reasoning_tokens": 2},
                    },
                },
            )
        assert req.url.path == "/v1/chat/completions"
        assert body["reasoning_effort"] == "low"
        assert body["thinking"] == {"type": "enabled"}
        assert body["max_tokens"] >= 1024
        return httpx.Response(
            200,
            json={
                "id": "s",
                "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    adapter = NativeInferenceAdapter(provider, "secret", transport=httpx.MockTransport(handler))
    result = await adapter.complete_structured(request(model=model))
    assert result.structured_output == {"ok": True}
    assert result.usage["input_tokens"] == 12
    assert result.estimated_cost_usd is not None and result.estimated_cost_usd > 0


@pytest.mark.parametrize(
    "body",
    [
        {"content": [], "usage": {}},
        {"content": [{"type": "text", "text": '{"ok":"wrong"}'}], "usage": {}},
        {"content": [{"type": "text", "text": '{"ok":true}'}], "stop_reason": "max_tokens"},
    ],
)
async def test_empty_truncated_and_schema_invalid_fail_explicitly(body: dict[str, Any]) -> None:
    adapter = NativeInferenceAdapter(
        "anthropic",
        "secret",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    with pytest.raises(SemanticProviderError):
        await adapter.complete_structured(request(model="claude-sonnet-5-5"))


async def test_provider_error_never_echoes_key_or_body() -> None:
    secret = "sk-very-private-test-key"
    adapter = NativeInferenceAdapter(
        "anthropic",
        secret,
        transport=httpx.MockTransport(lambda _: httpx.Response(401, json={"error": secret})),
    )
    with pytest.raises(PermanentProviderError) as caught:
        await adapter.complete_structured(request(model="claude-sonnet-5-5"))
    assert secret not in str(caught.value)


async def test_anthropic_native_tool_schema_and_validation() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["tools"][0]["input_schema"] == SCHEMA
        return httpx.Response(
            200,
            json={
                "content": [{"type": "tool_use", "id": "t", "name": "test", "input": {"ok": True}}],
                "usage": {},
            },
        )

    adapter = NativeInferenceAdapter("anthropic", "secret", transport=httpx.MockTransport(handler))
    result = await adapter.complete_tools(
        request(
            model="claude-sonnet-5-5",
            tools=[ToolDefinition(name="test", description="test", input_schema=SCHEMA)],
        )
    )
    assert result.tool_calls[0].arguments == {"ok": True}


def setup_router(
    *, hosted: bool = False, failure: Exception | None = None, retries: int = 0
) -> tuple[
    InferenceRouter,
    Principal,
    Settings,
    InMemoryCredentialStore,
    InMemoryBudgetStore,
    list[tuple[str, str, str | None]],
]:
    config: dict[str, Any] = {"_env_file": None}
    settings = Settings(
        **config,
        inference_provider="spur",
        spur_api_key="hosted-key",
        byok_encryption_keys={"v1": base64.urlsafe_b64encode(os.urandom(32)).decode()},
        openai_max_retries=retries,
    )
    user = make_principal(
        "router-test", invited=True, hosted=hosted, quota_usd=100, quota_tokens=100_000
    )
    credentials, store = InMemoryCredentialStore(), InMemoryBudgetStore()
    calls: list[tuple[str, str, str | None]] = []

    class Adapter:
        def __init__(self, provider: str, key: str) -> None:
            self.provider, self.key = provider, key

        async def complete_structured(self, req: InferenceRequest) -> InferenceResponse:
            calls.append((self.provider, self.key, req.model))
            if failure:
                raise failure
            return InferenceResponse(
                structured_output={"ok": True},
                provider=self.provider,
                model=req.model or "",
                usage={"input_tokens": 20, "output_tokens": 10},
            )

    async def lookup(owner: UUID) -> Principal | None:
        return user if owner == user.user_id else None

    budget = InferenceBudgetService(store, settings)
    router = InferenceRouter(settings, credentials, budget, InferenceAudit(store), lookup, Adapter)
    return router, user, settings, credentials, store, calls


@pytest.mark.parametrize(
    "provider,model", [("openai", "gpt-5.4-mini"), ("anthropic", "claude-sonnet-5-5")]
)
async def test_byok_does_not_debit_hosted_and_never_falls_back(provider: Any, model: str) -> None:
    router, user, settings, credentials, store, calls = setup_router()
    cipher = CredentialCipher(settings.byok_encryption_keys, "v1")
    await credentials.put(
        user.user_id, provider, cipher.encrypt(user.user_id, provider, "own-key"), "-key"
    )
    await credentials.set_preference(
        user.user_id, InferencePreference(mode="byok", provider=provider, model=model)
    )
    result = await router.complete_structured(request(user_id=user.user_id, agent_name="evidence"))
    assert result.billing_mode == "byok"
    assert calls == [(provider, "own-key", model)]
    assert (await store.counters("global")).spent_tokens == 0
    assert store.ledger[0]["billing_mode"] == "byok"
    await credentials.delete(user.user_id, provider)
    with pytest.raises(ProviderNotConfiguredError):
        await router.complete_structured(request(user_id=user.user_id))
    assert len(calls) == 1


async def test_hosted_has_entitlement_and_kill_switch_even_for_admin() -> None:
    router, user, _, _, store, calls = setup_router(hosted=False)
    user.role = "admin"
    with pytest.raises(ForbiddenError):
        await router.complete_structured(request(user_id=user.user_id))
    assert calls == []
    user.hosted_enabled = True
    await store.set_hosted_enabled(False)
    with pytest.raises(ProviderNotConfiguredError):
        await router.complete_structured(request(user_id=user.user_id))
    assert calls == []


async def test_failures_account_every_attempt_without_provider_fallback() -> None:
    router, user, _, _, store, calls = setup_router(
        hosted=True, failure=TransientProviderError("outage"), retries=1
    )
    with pytest.raises(TransientProviderError):
        await router.complete_structured(request(user_id=user.user_id))
    assert len(calls) == len(store.ledger) == 2
    assert {call[0] for call in calls} == {"spur"}
    assert (await store.counters("global")).spent_tokens > 0
    assert (await store.counters("global")).reserved_tokens == 0


async def test_unknown_model_and_cross_owner_make_no_calls() -> None:
    router, user, _, _, _, calls = setup_router(hosted=True)
    with pytest.raises(SemanticProviderError):
        await router.complete_structured(request(user_id=user.user_id, model="not-a-real-model"))
    from personal_markets.core.errors import UnauthorizedError

    with pytest.raises(UnauthorizedError):
        await router.complete_structured(request(user_id=uuid4()))
    assert calls == []


async def test_atomic_application_rate_limits() -> None:
    store = InMemoryBudgetStore()
    owner = uuid4()
    results = await asyncio.gather(
        *[store.consume_rate(owner, "ip", 2, 10) for _ in range(12)], return_exceptions=True
    )
    assert sum(result is None for result in results) == 2
    assert sum(isinstance(result, ProviderBudgetExceededError) for result in results) == 10


def test_anthropic_grammar_schema_keeps_original_validation_and_property_names() -> None:
    original: dict[str, Any] = {
        "type": "object",
        "properties": {
            "minimum": {"type": "number", "minimum": 3},
            "title": {"type": "string", "minLength": 3, "maxLength": 200},
        },
        "required": ["minimum", "title"],
        "additionalProperties": False,
    }
    sent = anthropic_schema(original)
    assert "minimum" in sent["properties"]
    assert "minimum" not in sent["properties"]["minimum"]
    assert "Constraints" in sent["properties"]["title"]["description"]
    assert original["properties"]["title"]["minLength"] == 3


async def test_usage_is_retained_when_structured_output_is_invalid() -> None:
    from personal_markets.core.errors import InferenceOutputError

    adapter = NativeInferenceAdapter(
        "anthropic",
        "secret",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "invalid"}],
                    "usage": {"input_tokens": 15, "output_tokens": 8},
                },
            )
        ),
    )
    with pytest.raises(InferenceOutputError) as caught:
        await adapter.complete_structured(request(model="claude-sonnet-5-5"))
    assert caught.value.usage == {"input_tokens": 15, "output_tokens": 8}


async def test_revoked_byok_key_is_marked_invalid_without_hosted_fallback() -> None:
    from personal_markets.core.errors import ProviderAuthenticationError

    router, user, settings, credentials, store, calls = setup_router(
        failure=ProviderAuthenticationError("Provider authentication failed")
    )
    cipher = CredentialCipher(settings.byok_encryption_keys, "v1")
    await credentials.put(
        user.user_id, "openai", cipher.encrypt(user.user_id, "openai", "own-key"), "-key"
    )
    await credentials.set_preference(
        user.user_id, InferencePreference(mode="byok", provider="openai")
    )
    for _ in range(2):
        with pytest.raises(ProviderAuthenticationError):
            await router.complete_structured(request(user_id=user.user_id))
    assert len(calls) == 1
    row = await credentials.get(user.user_id, "openai")
    assert row and row.status == "invalid"
    assert (await store.counters("global")).spent_tokens == 0


async def test_daily_pool_limit_counts_concurrent_reservations() -> None:
    settings = Settings(openai_daily_token_budget_high_volume=2500)
    store = InMemoryBudgetStore()
    budget = InferenceBudgetService(store, settings)
    user = make_principal(
        "daily-cap", invited=True, hosted=True, quota_usd=10, quota_tokens=100_000
    )
    results = await asyncio.gather(
        *[
            budget.reserve(
                user,
                agent_name="evidence",
                provider="openai",
                model="gpt-5.4-mini",
                max_output_tokens=1200,
                client_ip=None,
            )
            for _ in range(8)
        ],
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1


async def test_cancelled_provider_attempt_settles_conservatively() -> None:
    router, user, _, _, store, _ = setup_router(hosted=True)
    entered = asyncio.Event()

    class Slow:
        def __init__(self, provider: str, key: str) -> None:
            pass

        async def complete_structured(self, req: InferenceRequest) -> InferenceResponse:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("cancelled request must not finish")

    router._adapter_factory = Slow
    running = asyncio.create_task(router.complete_structured(request(user_id=user.user_id)))
    await entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    counters = await store.counters("global")
    assert counters.reserved_tokens == 0 and counters.spent_tokens > 0
    assert store.ledger[0]["outcome"] == "cancelled"
    assert store.ledger[0]["usage_reported"] is False


async def test_semantic_retries_share_one_wall_time_deadline() -> None:
    from typing import cast

    from pydantic import BaseModel

    from personal_markets.agents.completion import complete_validated
    from personal_markets.core.errors import InferenceOutputError
    from personal_markets.ports import InferenceProvider

    class Output(BaseModel):
        ok: bool

    class SlowProvider:
        calls = 0

        async def complete_structured(self, req: InferenceRequest) -> InferenceResponse:
            self.calls += 1
            await asyncio.sleep(0.04)
            raise InferenceOutputError("invalid schema", None, "test", "test")

    provider = SlowProvider()
    with pytest.raises(TransientProviderError, match="wall-time"):
        await complete_validated(
            cast(InferenceProvider, provider), request(), Output, timeout_seconds=0.06
        )
    assert provider.calls == 2


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("invalid_key", "ProviderAuthenticationError"),
        ("rate_limit", "TransientProviderError"),
        ("timeout", "TransientProviderError"),
        ("malformed", "InferenceOutputError"),
        ("unavailable", "TransientProviderError"),
    ],
)
@pytest.mark.parametrize("mode", ["hosted", "byok"])
async def test_fault_injection_keeps_provider_and_accounting(
    failure: str, expected: str, mode: str
) -> None:
    from personal_markets.core.errors import InferenceOutputError, ProviderAuthenticationError

    router, user, settings, credentials, store, _ = setup_router(hosted=True)
    secret = "sk-test-secret-never-log"
    model = "gpt-5.4-mini" if mode == "byok" else "spur-glm-5-3"
    if mode == "byok":
        cipher = CredentialCipher(settings.byok_encryption_keys, "v1")
        await credentials.put(
            user.user_id, "openai", cipher.encrypt(user.user_id, "openai", secret), "-log"
        )
        await credentials.set_preference(
            user.user_id, InferencePreference(mode="byok", provider="openai", model=model)
        )
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=req)
        if failure == "invalid_key":
            return httpx.Response(401, json={"error": secret})
        if failure == "rate_limit":
            return httpx.Response(429, json={"error": secret})
        if failure == "unavailable":
            return httpx.Response(503, json={"error": secret})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}],
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "not json"}]}
                ],
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 5,
                    "prompt_tokens": 11,
                    "completion_tokens": 5,
                },
            },
        )

    router._adapter_factory = lambda selected, key: NativeInferenceAdapter(
        selected, key, transport=httpx.MockTransport(handler)
    )
    error_type = {
        "ProviderAuthenticationError": ProviderAuthenticationError,
        "TransientProviderError": TransientProviderError,
        "InferenceOutputError": InferenceOutputError,
    }[expected]
    with pytest.raises(error_type) as caught:
        await router.complete_structured(request(user_id=user.user_id, agent_name="evidence"))
    assert secret not in str(caught.value)
    assert len(seen) == 1 and seen[0] == (
        "/v1/responses" if mode == "byok" else "/v1/chat/completions"
    )
    assert len(store.ledger) == 1
    assert secret not in str(store.ledger)
    assert store.ledger[0]["outcome"] == expected
    counters = await store.counters("global")
    assert counters.reserved_tokens == 0
    assert (counters.spent_tokens == 0) == (mode == "byok")
