from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    ConflictError,
    ForbiddenError,
    ResourceNotFoundError,
    SemanticProviderError,
    UnauthorizedError,
)
from personal_markets.identity.clerk_users import VerifiedEmailCache
from personal_markets.identity.domain import (
    AccountView,
    HostedUsage,
    Invitation,
    Principal,
    UserProfile,
    user_id_for_clerk,
)
from personal_markets.identity.repository import IdentityRepository
from personal_markets.identity.tokens import TokenClaims

_MAX_SHARED_REDEMPTIONS = 20
_USERNAME = re.compile(r"^[a-z0-9_]{3,24}$")


class IdentityService:
    def __init__(
        self,
        repository: IdentityRepository,
        settings: Settings,
        email_cache: VerifiedEmailCache | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._email_cache = email_cache or VerifiedEmailCache()

    async def principal_from_claims(self, claims: TokenClaims) -> Principal:
        claims.pop("role", None)
        email = (claims.email or "").strip().lower() or None
        email_verified = claims.email_verified
        if (
            (not email or not email_verified)
            and self._settings.clerk_secret_key
            and claims.get("iss") != "playitout-test"
        ):
            looked_up, looked_verified = self._email_cache.resolve(
                claims.clerk_user_id, self._settings.clerk_secret_key
            )
            email = email or looked_up
            email_verified = email_verified or looked_verified
        admins = {item.strip().lower() for item in self._settings.admin_emails}
        role = "admin" if email and email_verified and email in admins else "user"
        incoming = Principal(
            user_id=user_id_for_clerk(claims.clerk_user_id),
            clerk_user_id=claims.clerk_user_id,
            email=email,
            email_verified=email_verified,
            role=role,
        )
        stored = await self._repository.upsert_user(incoming)
        if (
            self._settings.dev_bootstrap_test_users
            and not self._settings.is_deployed()
            and claims.get("iss") == "playitout-test"
            and not stored.hosted_enabled
        ):
            await self._repository.grant_entitlement(
                stored.user_id,
                quota_usd=self._settings.hosted_user_quota_usd,
                quota_tokens=self._settings.hosted_user_quota_tokens,
                invitation_id=None,
                now=datetime.now(UTC),
            )
            return await self._repository.get_user(stored.user_id) or stored
        return stored

    async def create_invitation(
        self,
        actor: Principal,
        *,
        email: str | None = None,
        note: str = "",
        hosted_quota_usd: float | None = None,
        hosted_quota_tokens: int | None = None,
        ttl_hours: int | None = None,
        max_redemptions: int | None = None,
    ) -> Invitation:
        if actor.role != "admin":
            raise ForbiddenError("admin invitation access is required")
        bound_email = (email or "").strip().lower() or None
        if bound_email:
            redemptions = 1
        else:
            requested = (
                max_redemptions
                if max_redemptions is not None
                else self._settings.invite_max_redemptions
            )
            redemptions = min(max(int(requested), 1), _MAX_SHARED_REDEMPTIONS)
        token = secrets.token_urlsafe(32)
        invitation = await self._repository.create_invitation(
            token_hash=_hash_token(token),
            email=bound_email,
            note=note,
            max_redemptions=redemptions,
            hosted_quota_usd=hosted_quota_usd
            if hosted_quota_usd is not None
            else self._settings.hosted_user_quota_usd,
            hosted_quota_tokens=hosted_quota_tokens
            if hosted_quota_tokens is not None
            else self._settings.hosted_user_quota_tokens,
            expires_at=datetime.now(UTC)
            + timedelta(hours=ttl_hours or self._settings.invite_ttl_hours),
            created_by=actor.user_id,
        )
        return invitation.model_copy(update={"token": token})

    async def redeem_invitation(self, principal: Principal, token: str) -> Principal:
        invitation = await self._repository.get_invitation_by_hash(_hash_token(token))
        if invitation is None:
            raise ResourceNotFoundError("invitation was not found")
        if invitation.revoked_at is not None:
            raise ForbiddenError("invitation has been revoked")
        now = datetime.now(UTC)
        if invitation.expires_at <= now:
            raise ForbiddenError("invitation has expired")
        if invitation.email and (principal.email or "").lower() != invitation.email:
            raise ForbiddenError("invitation is bound to a different verified email")
        if invitation.email and not principal.email_verified:
            raise ForbiddenError("invitation requires a verified email address")
        if invitation.email and invitation.redeemed_at is not None:
            raise ForbiddenError("invitation has already been redeemed")
        redeemed = await self._repository.redeem_invitation(
            invitation.invitation_id, principal, now
        )
        if redeemed is None:
            raise ForbiddenError("invitation has no remaining redemptions")
        if redeemed.already_redeemed:
            if invitation.email:
                raise ForbiddenError("invitation has already been redeemed")
            stored = await self._repository.get_user(principal.user_id)
            assert stored is not None
            return stored
        await self._repository.grant_entitlement(
            principal.user_id,
            quota_usd=redeemed.invitation.hosted_quota_usd,
            quota_tokens=redeemed.invitation.hosted_quota_tokens,
            invitation_id=redeemed.invitation.invitation_id,
            now=now,
        )
        stored = await self._repository.get_user(principal.user_id)
        assert stored is not None
        return stored

    async def revoke_invitation(self, actor: Principal, invitation_id) -> Invitation:
        if actor.role != "admin":
            raise ForbiddenError("admin invitation access is required")
        revoked = await self._repository.revoke_invitation(invitation_id, datetime.now(UTC))
        if revoked is None:
            raise ResourceNotFoundError("invitation was not found or can no longer be revoked")
        return revoked

    async def list_invitations(self, actor: Principal) -> list[Invitation]:
        if actor.role != "admin":
            raise ForbiddenError("admin invitation access is required")
        return await self._repository.list_invitations()

    async def account_view(self, principal: Principal, usage: HostedUsage) -> AccountView:
        profile = await self._repository.get_profile(principal.user_id)
        return AccountView(
            user_id=principal.user_id,
            clerk_user_id=principal.clerk_user_id,
            email=principal.email,
            email_verified=principal.email_verified,
            role=principal.role,
            invited=principal.invited,
            hosted=usage,
            profile=profile,
        )

    async def update_profile(self, principal: Principal, patch: UserProfile) -> UserProfile:
        current = await self._repository.get_profile(principal.user_id)
        username = patch.username if patch.username is not None else current.username
        if username:
            normalized = username.strip().lower()
            if not _USERNAME.match(normalized):
                raise SemanticProviderError(
                    "username must be 3-24 characters of a-z, 0-9, or underscore"
                )
            if await self._repository.username_taken(normalized, principal.user_id):
                raise ConflictError("that username is already taken")
            username = normalized
        display = patch.display_name if patch.display_name is not None else current.display_name
        bio = patch.bio if patch.bio is not None else current.bio
        avatar = patch.avatar_value if patch.avatar_value is not None else current.avatar_value
        dimensions = (
            patch.dimensions if "dimensions" in patch.model_fields_set else current.dimensions
        )
        parameter_ids = (
            patch.parameter_ids
            if "parameter_ids" in patch.model_fields_set
            else current.parameter_ids
        )
        updated = UserProfile(
            display_name=(display or "").strip() or None,
            username=username or None,
            bio=(bio or "").strip() or None,
            avatar_value=(avatar or "").strip() or None,
            dimensions=dimensions,
            parameter_ids=parameter_ids,
        )
        return await self._repository.upsert_profile(principal.user_id, updated)


def require_authenticated(principal: Principal | None) -> Principal:
    if principal is None:
        raise UnauthorizedError("authentication required")
    return principal


def require_invited(principal: Principal) -> Principal:
    if not principal.invited and principal.role != "admin":
        raise ForbiddenError("an invitation is required to use this application")
    return principal


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
