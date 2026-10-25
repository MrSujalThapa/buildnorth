from datetime import datetime
from typing import Protocol
from uuid import UUID

from personal_markets.identity.domain import Invitation, Principal, RedeemResult, UserProfile


class IdentityRepository(Protocol):
    async def upsert_user(self, principal: Principal) -> Principal: ...

    async def get_user(self, user_id: UUID) -> Principal | None: ...

    async def get_user_by_clerk_id(self, clerk_user_id: str) -> Principal | None: ...

    async def create_invitation(
        self,
        *,
        token_hash: str,
        email: str | None,
        note: str,
        max_redemptions: int,
        hosted_quota_usd: float,
        hosted_quota_tokens: int,
        expires_at: datetime,
        created_by: UUID | None,
    ) -> Invitation: ...

    async def get_invitation_by_hash(self, token_hash: str) -> Invitation | None: ...

    async def redeem_invitation(
        self, invitation_id: UUID, principal: Principal, now: datetime
    ) -> RedeemResult | None: ...

    async def revoke_invitation(self, invitation_id: UUID, now: datetime) -> Invitation | None: ...

    async def list_invitations(self) -> list[Invitation]: ...

    async def get_profile(self, user_id: UUID) -> UserProfile: ...

    async def upsert_profile(self, user_id: UUID, profile: UserProfile) -> UserProfile: ...

    async def username_taken(self, username: str, user_id: UUID) -> bool: ...

    async def get_user_id_by_username(self, username: str) -> UUID | None: ...

    async def grant_entitlement(
        self,
        user_id: UUID,
        *,
        quota_usd: float,
        quota_tokens: int,
        invitation_id: UUID | None,
        now: datetime,
    ) -> bool: ...

    async def has_invitation_redemption(self, user_id: UUID) -> bool: ...

    async def reconcile_entitlement(
        self,
        user_id: UUID,
        *,
        enabled: bool,
        quota_usd: float,
        quota_tokens: int,
    ) -> None: ...
