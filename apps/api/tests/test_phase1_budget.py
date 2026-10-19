import asyncio

import pytest

from helpers import isolated_app
from personal_markets.core.errors import (
    ForbiddenError,
    ProviderBudgetExceededError,
    ProviderNotConfiguredError,
)
from personal_markets.identity.budget import InferenceBudgetService, InMemoryBudgetStore
from personal_markets.identity.domain import Principal
from personal_markets.identity.factory import get_budget_store, get_inference_budget_service
from personal_markets.identity.hosted import HostedInferenceGateway
from personal_markets.identity.testing import make_principal
from personal_markets.ports import InferenceRequest, InferenceResponse


def _settings():
    from personal_markets.core.config import get_settings

    return get_settings()


def _hosted(clerk_id: str, *, quota_usd: float = 100.0, quota_tokens: int = 2500) -> Principal:
    return make_principal(
        clerk_id,
        invited=True,
        hosted=True,
        quota_usd=quota_usd,
        quota_tokens=quota_tokens,
    )


async def test_accounts_without_hosted_entitlement_are_rejected() -> None:
    isolated_app()
    budget = get_inference_budget_service()
    user = make_principal("no-hosted", invited=True, hosted=False)
    with pytest.raises(ForbiddenError):
        await budget.reserve(
            user,
            agent_name="goal_architect",
            provider="spur",
            model="spur-glm-5-3",
            max_output_tokens=200,
            client_ip="127.0.0.1",
        )


async def test_kill_switch_disables_hosted_inference() -> None:
    isolated_app()
    budget = get_inference_budget_service()
    user = _hosted("kill-switch-user")
    await budget.set_kill_switch(False)
    with pytest.raises(ProviderNotConfiguredError):
        await budget.reserve(
            user,
            agent_name="goal_architect",
            provider="spur",
            model="spur-glm-5-3",
            max_output_tokens=200,
            client_ip="127.0.0.1",
        )


async def test_parallel_reservations_cannot_overspend() -> None:
    isolated_app()
    store = get_budget_store()
    budget = InferenceBudgetService(store, _settings())
    user = _hosted("race-budget", quota_usd=100.0, quota_tokens=2500)
    results = await asyncio.gather(
        *[
            budget.reserve(
                user,
                agent_name="goal_architect",
                provider="spur",
                model="spur-glm-5-3",
                max_output_tokens=1200,
                client_ip="10.0.0.8",
            )
            for _ in range(12)
        ],
        return_exceptions=True,
    )
    successes = [item for item in results if not isinstance(item, Exception)]
    failures = [item for item in results if isinstance(item, ProviderBudgetExceededError)]
    assert len(successes) == 1
    assert len(failures) == 11
    counters = await store.counters(str(user.user_id))
    assert counters.reserved_tokens <= user.hosted_quota_tokens


async def test_judge_dollar_allowances_are_independent_and_share_global_cap() -> None:
    store = InMemoryBudgetStore()
    first = _hosted("judge-first", quota_usd=5, quota_tokens=5_000_000)
    second = _hosted("judge-second", quota_usd=5, quota_tokens=5_000_000)

    async def reserve(user: Principal, amount: float):
        return await store.reserve(
            user_id=user.user_id,
            clerk_user_id=user.clerk_user_id,
            agent_name="goal_architect",
            provider="openai",
            model="gpt-5.4-mini",
            amount_usd=amount,
            tokens=100,
            user_cap_usd=user.hosted_quota_usd,
            user_cap_tokens=user.hosted_quota_tokens,
            global_cap_usd=100,
            global_cap_tokens=100_000_000,
        )

    assert await reserve(first, 4.99) is not None
    assert await reserve(first, 0.02) is None
    assert await reserve(second, 5.0) is not None
    assert await reserve(second, 0.01) is None
    assert (await store.counters("global")).reserved_usd == 9.99


async def test_parallel_judges_cannot_cross_global_dollar_limit() -> None:
    store = InMemoryBudgetStore()
    judges = [_hosted(f"global-judge-{i}", quota_usd=5, quota_tokens=5_000_000) for i in range(21)]
    results = await asyncio.gather(
        *[
            store.reserve(
                user_id=user.user_id,
                clerk_user_id=user.clerk_user_id,
                agent_name="goal_architect",
                provider="openai",
                model="gpt-5.4-mini",
                amount_usd=5,
                tokens=100,
                user_cap_usd=5,
                user_cap_tokens=5_000_000,
                global_cap_usd=100,
                global_cap_tokens=100_000_000,
            )
            for user in judges
        ]
    )
    assert sum(result is not None for result in results) == 20
    assert (await store.counters("global")).reserved_usd == 100


def test_judge_hosted_allowance_defaults() -> None:
    settings = _settings()
    assert settings.hosted_global_quota_usd == 100.0
    assert settings.hosted_user_quota_usd == 5.0


async def test_global_budget_exhaustion() -> None:
    store = InMemoryBudgetStore()
    settings = _settings()
    budget = InferenceBudgetService(
        store, settings.model_copy(update={"hosted_global_quota_tokens": 1800})
    )
    first = _hosted("global-a", quota_tokens=100_000)
    second = _hosted("global-b", quota_tokens=100_000)
    await budget.reserve(
        first,
        agent_name="goal_architect",
        provider="spur",
        model="spur-glm-5-3",
        max_output_tokens=1200,
        client_ip="10.0.0.1",
    )
    with pytest.raises(ProviderBudgetExceededError):
        await budget.reserve(
            second,
            agent_name="evidence",
            provider="spur",
            model="spur-glm-5-3",
            max_output_tokens=1200,
            client_ip="10.0.0.2",
        )


async def test_provider_failure_releases_reservation() -> None:
    isolated_app()
    store = get_budget_store()
    budget = InferenceBudgetService(store, _settings())
    user = _hosted("provider-fail", quota_tokens=100_000)

    class Boom:
        async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
            del request
            raise RuntimeError("upstream provider failed")

    async def lookup(_user_id):
        return user

    gateway = HostedInferenceGateway(
        Boom(),
        budget,
        provider_name="spur",
        max_output_tokens=200,
        principal_lookup=lookup,
    )
    with pytest.raises(RuntimeError, match="upstream provider failed"):
        await gateway.complete_structured(
            InferenceRequest(
                instructions="test",
                input={},
                output_schema={"type": "object"},
                agent_name="goal_architect",
                model="spur-glm-5-3",
                user_id=user.user_id,
            )
        )
    counters = await store.counters(str(user.user_id))
    assert counters.reserved_usd == 0
    assert counters.reserved_tokens == 0
    assert counters.spent_usd == 0


async def test_successful_inference_settles_usage() -> None:
    isolated_app()
    store = get_budget_store()
    budget = InferenceBudgetService(store, _settings())
    user = _hosted("settle-ok", quota_tokens=100_000)

    class Ok:
        async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
            del request
            return InferenceResponse(
                structured_output={"ok": True},
                provider="spur",
                model="spur-glm-5-3",
                usage={"input_tokens": 20, "output_tokens": 10},
            )

    async def lookup(_user_id):
        return user

    gateway = HostedInferenceGateway(
        Ok(),
        budget,
        provider_name="spur",
        max_output_tokens=200,
        principal_lookup=lookup,
    )
    await gateway.complete_structured(
        InferenceRequest(
            instructions="test",
            input={},
            output_schema={"type": "object"},
            agent_name="goal_architect",
            model="spur-glm-5-3",
            user_id=user.user_id,
        )
    )
    counters = await store.counters(str(user.user_id))
    assert counters.reserved_tokens == 0
    assert counters.spent_tokens == 30
    assert counters.spent_usd > 0
    assert isinstance(store, InMemoryBudgetStore)
    assert store.ledger[0]["clerk_user_id"] == user.clerk_user_id
    assert store.ledger[0]["provider"] == "spur"
