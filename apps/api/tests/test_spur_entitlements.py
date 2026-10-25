import asyncio

import pytest

from personal_markets.agents.models import estimate_cost_usd
from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    ForbiddenError,
    ProviderBudgetExceededError,
    SemanticProviderError,
)
from personal_markets.identity.budget import InferenceBudgetService, InMemoryBudgetStore
from personal_markets.identity.clerk_users import VerifiedEmailCache
from personal_markets.identity.domain import UserProfile
from personal_markets.identity.service import IdentityService
from personal_markets.identity.store import InMemoryIdentityRepository
from personal_markets.identity.testing import make_principal
from personal_markets.identity.tokens import TokenClaims
from personal_markets.integrations.inference_catalog import hosted_allowlist


def _settings() -> Settings:
    return Settings(environment="test", admin_emails=["admin@example.test"])


def _claims(user: str, email: str, verified: bool = True) -> TokenClaims:
    return TokenClaims(
        {"sub": user, "iss": "playitout-test", "email": email, "email_verified": verified}
    )


async def test_verified_admin_reconciles_without_resetting_spend() -> None:
    repo = InMemoryIdentityRepository()
    service = IdentityService(repo, _settings())
    budget = InferenceBudgetService(InMemoryBudgetStore(), _settings())
    first = await service.principal_from_claims(_claims("admin-1", "admin@example.test"))
    assert first.trusted_admin and first.hosted_quota_usd == 100
    reservation = await budget.reserve(
        first,
        agent_name="evidence",
        provider="spur",
        model="spur-glm-5-3",
        max_output_tokens=200,
        client_ip=None,
    )
    await budget.settle(
        reservation,
        principal=first,
        agent_name="evidence",
        provider="spur",
        model="spur-glm-5-3",
        input_tokens=512,
        output_tokens=100,
    )
    second = await service.principal_from_claims(_claims("admin-1", "admin@example.test"))
    usage = await budget.usage_for(second)
    assert usage.quota_usd == 100
    assert usage.spent_usd > 0
    assert usage.remaining_usd == pytest.approx(100 - usage.spent_usd)


async def test_unverified_and_username_spoof_cannot_gain_admin_budget() -> None:
    repo = InMemoryIdentityRepository()
    service = IdentityService(repo, _settings())
    unverified = await service.principal_from_claims(
        _claims("spoof", "admin@example.test", verified=False)
    )
    assert unverified.role == "user" and not unverified.hosted_enabled
    assert (
        await service.principal_from_claims(_claims("spoof", "ordinary@example.test"))
    ).role == "user"
    updated = await service.update_profile(unverified, UserProfile(username="sujalthapa242"))
    assert updated.username == "sujalthapa242"
    assert (
        await service.principal_from_claims(_claims("spoof", "ordinary@example.test"))
    ).role == "user"
    with pytest.raises(ForbiddenError):
        await service.create_invitation(unverified, hosted_quota_usd=100)


async def test_invitation_is_capped_and_repeated_redemption_preserves_budget() -> None:
    repo = InMemoryIdentityRepository()
    service = IdentityService(repo, _settings())
    admin = await service.principal_from_claims(_claims("admin", "admin@example.test"))
    user = await service.principal_from_claims(_claims("user", "user@example.test"))
    invite = await service.create_invitation(
        admin, hosted_quota_usd=100, hosted_quota_tokens=100_000_000
    )
    assert invite.hosted_quota_usd == 5
    first = await service.redeem_invitation(user, invite.token or "")
    second = await service.redeem_invitation(first, invite.token or "")
    assert first.hosted_quota_usd == second.hosted_quota_usd == 5
    assert (
        await service.principal_from_claims(_claims("user", "user@example.test"))
    ).hosted_quota_usd == 5


async def test_stale_ordinary_quota_cannot_overspend_under_concurrency() -> None:
    settings = _settings()
    store = InMemoryBudgetStore()
    budget = InferenceBudgetService(store, settings)
    user = make_principal(
        "old-user", invited=True, hosted=True, quota_usd=100, quota_tokens=100_000_000
    )
    assert (await budget.usage_for(user)).quota_usd == 5
    requests = await asyncio.gather(
        *[budget.reserve_research(user, 1.0) for _ in range(10)], return_exceptions=True
    )
    assert sum(not isinstance(item, Exception) for item in requests) == 5
    assert sum(isinstance(item, ProviderBudgetExceededError) for item in requests) == 5
    assert (await budget.usage_for(user)).remaining_usd == 0
    with pytest.raises(ProviderBudgetExceededError, match="Invalid"):
        await budget.reserve_research(user, -1.0)


async def test_downward_reconciliation_preserves_historical_spend() -> None:
    repo = InMemoryIdentityRepository()
    service = IdentityService(repo, _settings())
    store = InMemoryBudgetStore()
    budget = InferenceBudgetService(store, _settings())
    user = await service.principal_from_claims(_claims("legacy", "legacy@example.test"))
    admin = await service.principal_from_claims(_claims("admin", "admin@example.test"))
    invite = await service.create_invitation(admin)
    invited = await service.redeem_invitation(user, invite.token or "")
    await repo.reconcile_entitlement(
        invited.user_id,
        enabled=True,
        quota_usd=100,
        quota_tokens=5_000_000,
    )
    historical = await store.reserve(
        user_id=invited.user_id,
        clerk_user_id=invited.clerk_user_id,
        agent_name="research",
        provider="monid",
        model="approved_research_tool",
        amount_usd=6.0,
        tokens=0,
        user_cap_usd=100,
        user_cap_tokens=5_000_000,
        global_cap_usd=250,
        global_cap_tokens=250_000_000,
    )
    assert historical is not None
    await store.settle(
        historical,
        clerk_user_id=invited.clerk_user_id,
        agent_name="research",
        provider="monid",
        model="approved_research_tool",
        input_tokens=0,
        output_tokens=0,
        cost=6.0,
    )
    reconciled = await service.principal_from_claims(_claims("legacy", "legacy@example.test"))
    usage = await budget.usage_for(reconciled)
    assert usage.quota_usd == 5
    assert usage.spent_usd == 6
    assert usage.remaining_usd == 0
    assert len(store.ledger) == 1


async def test_stale_verified_admin_claim_is_rejected_by_current_clerk_record() -> None:
    settings = Settings(
        environment="production",
        admin_emails=["admin@example.test"],
        admin_clerk_user_ids=["trusted-id"],
        clerk_secret_key="test-secret",
    )
    repo = InMemoryIdentityRepository()
    cache = VerifiedEmailCache(lookup=lambda _id, _secret: ("other@example.test", True))
    service = IdentityService(repo, settings, cache)
    principal = await service.principal_from_claims(
        TokenClaims(
            {
                "sub": "stale",
                "iss": "https://clerk.example",
                "email": "admin@example.test",
                "email_verified": True,
            }
        )
    )
    assert principal.role == "user"
    assert not principal.trusted_admin
    assert not principal.hosted_enabled


async def test_deployed_admin_requires_both_immutable_id_and_verified_email() -> None:
    settings = Settings(
        environment="production",
        admin_emails=["admin@example.test"],
        admin_clerk_user_ids=["trusted-id"],
        clerk_secret_key="test-secret",
    )
    repo = InMemoryIdentityRepository()
    cache = VerifiedEmailCache(lookup=lambda _id, _secret: ("admin@example.test", True))
    service = IdentityService(repo, settings, cache)
    trusted = await service.principal_from_claims(
        TokenClaims(
            {
                "sub": "trusted-id",
                "iss": "https://clerk.example",
            }
        )
    )
    other = await service.principal_from_claims(
        TokenClaims(
            {
                "sub": "different-id",
                "iss": "https://clerk.example",
            }
        )
    )
    assert trusted.role == "admin" and trusted.hosted_quota_usd == 100
    assert other.role == "user" and not other.hosted_enabled


def test_invalid_hosted_model_fails_before_a_provider_call() -> None:
    with pytest.raises(SemanticProviderError, match="unsupported"):
        hosted_allowlist("spur", "unknown-spur-model")


def test_spur_glm_estimate_matches_published_token_rate() -> None:
    assert estimate_cost_usd("spur-glm-5-3", 1_000_000, 1_000_000) == pytest.approx(1.30)


def test_render_admin_id_list_parses_without_email_fallback() -> None:
    settings = Settings(admin_clerk_user_ids='["trusted-id"]')  # type: ignore[arg-type]
    assert settings.admin_clerk_user_ids == ["trusted-id"]
