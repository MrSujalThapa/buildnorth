from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

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
    Role,
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

    async def principal_for_user_id(self, user_id: UUID) -> Principal | None:
        stored = await self._repository.get_user(user_id)
        if stored is None:
            return None
        # Background/MCP inference must recheck the current Clerk identity instead
        # of trusting a possibly stale persisted admin role or entitlement.
        if self._settings.environment in {"test", "pytest"}:
            return await self.principal_from_claims(
                TokenClaims(
                    {
                        "sub": stored.clerk_user_id,
                        "iss": "playitout-test",
                        "email": stored.email,
                        "email_verified": stored.email_verified,
                    }
                )
            )
        if not self._settings.clerk_secret_key:
            raise ForbiddenError("Current account verification is unavailable")
        email, verified = self._email_cache.resolve(
            stored.clerk_user_id, self._settings.clerk_secret_key, fresh=True
        )
        if not email or not verified:
            raise ForbiddenError("Current account verification failed")
        return await self.principal_from_claims(
            TokenClaims(
                {
                    "sub": stored.clerk_user_id,
                    "iss": "playitout-internal",
                    "email": email,
                    "email_verified": True,
                }
            ),
            clerk_verified=True,
        )

    async def principal_from_claims(
        self, claims: TokenClaims, *, clerk_verified: bool = False
    ) -> Principal:
        claims.pop("role", None)
        email = (claims.email or "").strip().lower() or None
        email_verified = claims.email_verified
        admins = {item.strip().lower() for item in self._settings.admin_emails}
        if (
            (not email or email in admins)
            and self._settings.clerk_secret_key
            and claims.get("iss") != "playitout-test"
            and not clerk_verified
        ):
            looked_up, looked_verified = self._email_cache.resolve(
                claims.clerk_user_id,
                self._settings.clerk_secret_key,
                fresh=email in admins,
            )
            # Clerk's current primary verified email is authoritative for privileges.
            email, email_verified = looked_up, looked_verified
        trusted_ids = set(self._settings.admin_clerk_user_ids)
        trusted_id = claims.clerk_user_id in trusted_ids or (
            not trusted_ids and not self._settings.is_deployed()
        )
        role: Role = (
            "admin" if email and email_verified and email in admins and trusted_id else "user"
        )
        incoming = Principal(
            user_id=user_id_for_clerk(claims.clerk_user_id),
            clerk_user_id=claims.clerk_user_id,
            email=email,
            email_verified=email_verified,
            role=role,
            trusted_admin=role == "admin",
        )
        stored = await self._repository.upsert_user(incoming)
        is_admin = role == "admin"
        redeemed = (
            False if is_admin else await self._repository.has_invitation_redemption(stored.user_id)
        )
        if is_admin or redeemed:
            quota_usd = (
                self._settings.hosted_admin_quota_usd
                if is_admin
                else min(self._settings.hosted_user_quota_usd, 5.0)
            )
            quota_tokens = (
                self._settings.hosted_admin_quota_tokens
                if is_admin
                else self._settings.hosted_user_quota_tokens
            )
            if (
                stored.hosted_enabled
                and stored.hosted_quota_usd == quota_usd
                and stored.hosted_quota_tokens == quota_tokens
            ):
                return stored.model_copy(update={"trusted_admin": is_admin})
            await self._repository.reconcile_entitlement(
                stored.user_id,
                enabled=True,
                quota_usd=quota_usd,
                quota_tokens=quota_tokens,
            )
            refreshed = await self._repository.get_user(stored.user_id)
            return (refreshed or stored).model_copy(update={"trusted_admin": is_admin})
        if (
            stored.hosted_enabled
            and not (self._settings.environment in {"test", "pytest"} and stored.invited)
            and not (
                self._settings.dev_bootstrap_test_users
                and not self._settings.is_deployed()
                and claims.get("iss") == "playitout-test"
            )
        ):
            await self._repository.reconcile_entitlement(
                stored.user_id,
                enabled=False,
                quota_usd=0,
                quota_tokens=0,
            )
            stored = await self._repository.get_user(stored.user_id) or stored
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
        return stored.model_copy(update={"trusted_admin": False})

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
        if actor.role != "admin" or not actor.trusted_admin:
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
            hosted_quota_usd=min(
                max(
                    0.0,
                    hosted_quota_usd
                    if hosted_quota_usd is not None
                    else self._settings.hosted_user_quota_usd,
                ),
                5.0,
            ),
            hosted_quota_tokens=min(
                max(
                    0,
                    hosted_quota_tokens
                    if hosted_quota_tokens is not None
                    else self._settings.hosted_user_quota_tokens,
                ),
                self._settings.hosted_user_quota_tokens,
            ),
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
            await self._repository.reconcile_entitlement(
                principal.user_id,
                enabled=True,
                quota_usd=min(
                    invitation.hosted_quota_usd, self._settings.hosted_user_quota_usd, 5.0
                ),
                quota_tokens=min(
                    invitation.hosted_quota_tokens, self._settings.hosted_user_quota_tokens
                ),
            )
            stored = await self._repository.get_user(principal.user_id)
            assert stored is not None
            return stored
        await self._repository.reconcile_entitlement(
            principal.user_id,
            enabled=True,
            quota_usd=min(
                redeemed.invitation.hosted_quota_usd, self._settings.hosted_user_quota_usd, 5.0
            ),
            quota_tokens=min(
                redeemed.invitation.hosted_quota_tokens, self._settings.hosted_user_quota_tokens
            ),
        )
        stored = await self._repository.get_user(principal.user_id)
        assert stored is not None
        return stored

    async def revoke_invitation(self, actor: Principal, invitation_id: UUID) -> Invitation:
        if actor.role != "admin" or not actor.trusted_admin:
            raise ForbiddenError("admin invitation access is required")
        revoked = await self._repository.revoke_invitation(invitation_id, datetime.now(UTC))
        if revoked is None:
            raise ResourceNotFoundError("invitation was not found or can no longer be revoked")
        return revoked

    async def list_invitations(self, actor: Principal) -> list[Invitation]:
        if actor.role != "admin" or not actor.trusted_admin:
            raise ForbiddenError("admin invitation access is required")
        return await self._repository.list_invitations()

    async def profile_for(self, principal: Principal) -> UserProfile:
        return await self._repository.get_profile(principal.user_id)

    async def profile_for_user(self, user_id: UUID) -> UserProfile:
        return await self._repository.get_profile(user_id)

    async def user_id_for_handle(self, handle: str) -> UUID | None:
        found = await self._repository.get_user_id_by_username(handle)
        if found is not None:
            return found
        try:
            return UUID(handle)
        except ValueError:
            return None

    async def account_view(
        self, principal: Principal, usage: HostedUsage, profile: UserProfile | None = None
    ) -> AccountView:
        if profile is None:
            profile = await self.profile_for(principal)
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
        custom_parameters = (
            patch.custom_parameters
            if "custom_parameters" in patch.model_fields_set
            else current.custom_parameters
        )
        updated = UserProfile(
            display_name=(display or "").strip() or None,
            username=username or None,
            bio=(bio or "").strip() or None,
            avatar_value=(avatar or "").strip() or None,
            dimensions=dimensions,
            parameter_ids=parameter_ids,
            custom_parameters=custom_parameters,
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
