from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.identity.domain import Invitation, Principal, RedeemResult, UserProfile
from personal_markets.persistence.database import transaction


def _kind_for(email: str | None) -> str:
    return "email" if email else "shared"


class InMemoryIdentityRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.users: dict[UUID, Principal] = {}
        self.by_clerk: dict[str, UUID] = {}
        self.invites: dict[UUID, Invitation] = {}
        self.invite_hashes: dict[str, UUID] = {}
        self.redemptions: dict[tuple[UUID, UUID], datetime] = {}
        self.profiles: dict[UUID, UserProfile] = {}

    async def upsert_user(self, principal: Principal) -> Principal:
        existing = self.users.get(principal.user_id)
        if existing is not None:
            updated = existing.model_copy(
                update={
                    "email": principal.email or existing.email,
                    "email_verified": existing.email_verified or principal.email_verified,
                    "role": principal.role,
                }
            )
            self.users[principal.user_id] = updated
            return updated
        self.users[principal.user_id] = principal
        self.by_clerk[principal.clerk_user_id] = principal.user_id
        return principal

    async def get_user(self, user_id: UUID) -> Principal | None:
        return self.users.get(user_id)

    async def get_user_by_clerk_id(self, clerk_user_id: str) -> Principal | None:
        user_id = self.by_clerk.get(clerk_user_id)
        return self.users.get(user_id) if user_id else None

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
    ) -> Invitation:
        invitation = Invitation(
            invitation_id=uuid4(),
            email=email,
            note=note,
            kind=_kind_for(email),
            max_redemptions=max_redemptions,
            hosted_quota_usd=hosted_quota_usd,
            hosted_quota_tokens=hosted_quota_tokens,
            expires_at=expires_at,
            created_by=created_by,
        )
        self.invites[invitation.invitation_id] = invitation
        self.invite_hashes[token_hash] = invitation.invitation_id
        return invitation

    async def get_invitation_by_hash(self, token_hash: str) -> Invitation | None:
        invitation_id = self.invite_hashes.get(token_hash)
        return self.invites.get(invitation_id) if invitation_id else None

    async def redeem_invitation(
        self, invitation_id: UUID, principal: Principal, now: datetime
    ) -> RedeemResult | None:
        async with self._lock:
            invitation = self.invites.get(invitation_id)
            if invitation is None:
                return None
            existing = self.redemptions.get((invitation_id, principal.user_id))
            if existing is not None:
                return RedeemResult(invitation=invitation, already_redeemed=True)
            if invitation.revoked_at is not None or invitation.expires_at <= now:
                return None
            if invitation.redemption_count >= invitation.max_redemptions:
                return None
            self.redemptions[(invitation_id, principal.user_id)] = now
            count = invitation.redemption_count + 1
            updated = invitation.model_copy(
                update={
                    "redemption_count": count,
                    "redeemed_by": invitation.redeemed_by or principal.user_id,
                    "redeemed_at": now if count >= invitation.max_redemptions else invitation.redeemed_at,
                }
            )
            self.invites[invitation_id] = updated
            return RedeemResult(invitation=updated, already_redeemed=False)

    async def revoke_invitation(self, invitation_id: UUID, now: datetime) -> Invitation | None:
        invitation = self.invites.get(invitation_id)
        if invitation is None or invitation.revoked_at is not None:
            return None
        if invitation.max_redemptions == 1 and invitation.redeemed_at is not None:
            return None
        updated = invitation.model_copy(update={"revoked_at": now})
        self.invites[invitation_id] = updated
        return updated

    async def list_invitations(self) -> list[Invitation]:
        return list(self.invites.values())

    async def get_profile(self, user_id: UUID) -> UserProfile:
        return self.profiles.get(user_id) or UserProfile()

    async def upsert_profile(self, user_id: UUID, profile: UserProfile) -> UserProfile:
        self.profiles[user_id] = profile
        return profile

    async def username_taken(self, username: str, user_id: UUID) -> bool:
        needle = username.lower()
        return any(
            (row.username or "").lower() == needle and owner != user_id
            for owner, row in self.profiles.items()
        )

    async def grant_entitlement(
        self,
        user_id: UUID,
        *,
        quota_usd: float,
        quota_tokens: int,
        invitation_id: UUID | None,
        now: datetime,
    ) -> bool:
        del invitation_id, now
        user = self.users.get(user_id)
        if user is None:
            return False
        if user.hosted_enabled:
            return False
        self.users[user_id] = user.model_copy(
            update={
                "invited": True,
                "hosted_enabled": True,
                "hosted_quota_usd": quota_usd,
                "hosted_quota_tokens": quota_tokens,
            }
        )
        return True


class PostgresIdentityRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert_user(self, principal: Principal) -> Principal:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into app_users (id, clerk_user_id, email, email_verified, role)
                values (:id, :clerk_user_id, :email, :email_verified, :role)
                on conflict (clerk_user_id) do update set
                  email = coalesce(excluded.email, app_users.email),
                  email_verified = app_users.email_verified or excluded.email_verified,
                  role = excluded.role
                """),
                {
                    "id": principal.user_id,
                    "clerk_user_id": principal.clerk_user_id,
                    "email": principal.email,
                    "email_verified": principal.email_verified,
                    "role": principal.role,
                },
            )
        stored = await self.get_user_by_clerk_id(principal.clerk_user_id)
        assert stored is not None
        return stored

    async def get_user(self, user_id: UUID) -> Principal | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            select u.*, e.enabled as hosted_enabled, e.quota_usd, e.quota_tokens
                            from app_users u
                            left join hosted_entitlements e on e.user_id = u.id
                            where u.id = :id
                            """
                        ),
                        {"id": user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._to_principal(dict(row)) if row else None

    async def get_user_by_clerk_id(self, clerk_user_id: str) -> Principal | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            select u.*, e.enabled as hosted_enabled, e.quota_usd, e.quota_tokens
                            from app_users u
                            left join hosted_entitlements e on e.user_id = u.id
                            where u.clerk_user_id = :clerk_user_id
                            """
                        ),
                        {"clerk_user_id": clerk_user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._to_principal(dict(row)) if row else None

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
    ) -> Invitation:
        invitation_id = uuid4()
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into invitations (
                  id, token_hash, email, note, max_redemptions, hosted_quota_usd, hosted_quota_tokens,
                  expires_at, created_by
                ) values (
                  :id, :token_hash, :email, :note, :max_redemptions, :hosted_quota_usd, :hosted_quota_tokens,
                  :expires_at, :created_by
                )
                """),
                {
                    "id": invitation_id,
                    "token_hash": token_hash,
                    "email": email,
                    "note": note,
                    "max_redemptions": max_redemptions,
                    "hosted_quota_usd": hosted_quota_usd,
                    "hosted_quota_tokens": hosted_quota_tokens,
                    "expires_at": expires_at,
                    "created_by": created_by,
                },
            )
        stored = await self.get_invitation_by_hash(token_hash)
        assert stored is not None
        return stored

    async def get_invitation_by_hash(self, token_hash: str) -> Invitation | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from invitations where token_hash = :hash"),
                        {"hash": token_hash},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._to_invitation(dict(row)) if row else None

    async def redeem_invitation(
        self, invitation_id: UUID, principal: Principal, now: datetime
    ) -> RedeemResult | None:
        async with transaction(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from invitations where id = :id for update"),
                        {"id": invitation_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            invitation = self._to_invitation(dict(row))
            existing = (
                await connection.execute(
                    text(
                        """
                        select 1 from invitation_redemptions
                        where invitation_id = :id and user_id = :user_id
                        """
                    ),
                    {"id": invitation_id, "user_id": principal.user_id},
                )
            ).one_or_none()
            if existing is not None:
                return RedeemResult(invitation=invitation, already_redeemed=True)
            if invitation.revoked_at is not None or invitation.expires_at <= now:
                return None
            if invitation.redemption_count >= invitation.max_redemptions:
                return None
            await connection.execute(
                text(
                    """
                    insert into invitation_redemptions (
                      invitation_id, user_id, clerk_user_id, redeemed_at
                    ) values (
                      :id, :user_id, :clerk_user_id, :now
                    )
                    """
                ),
                {
                    "id": invitation_id,
                    "user_id": principal.user_id,
                    "clerk_user_id": principal.clerk_user_id,
                    "now": now,
                },
            )
            updated = (
                (
                    await connection.execute(
                        text(
                            """
                            update invitations
                            set redemption_count = redemption_count + 1,
                                redeemed_by = coalesce(redeemed_by, :user_id),
                                redeemed_at = case
                                  when redemption_count + 1 >= max_redemptions then :now
                                  else redeemed_at
                                end
                            where id = :id
                              and revoked_at is null
                              and redemption_count < max_redemptions
                            returning *
                            """
                        ),
                        {"id": invitation_id, "user_id": principal.user_id, "now": now},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if updated is None:
                raise RuntimeError("failed to consume invitation slot")
            return RedeemResult(invitation=self._to_invitation(dict(updated)), already_redeemed=False)

    async def revoke_invitation(self, invitation_id: UUID, now: datetime) -> Invitation | None:
        async with transaction(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                        update invitations
                        set revoked_at = :now
                        where id = :id
                          and revoked_at is null
                          and not (max_redemptions = 1 and redeemed_at is not null)
                        returning *
                        """),
                        {"id": invitation_id, "now": now},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._to_invitation(dict(row)) if row else None

    async def list_invitations(self) -> list[Invitation]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(text("select * from invitations order by created_at desc"))
            ).mappings()
            return [self._to_invitation(dict(row)) for row in rows]

    async def grant_entitlement(
        self,
        user_id: UUID,
        *,
        quota_usd: float,
        quota_tokens: int,
        invitation_id: UUID | None,
        now: datetime,
    ) -> bool:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text("""
                insert into hosted_entitlements (
                  user_id, enabled, quota_usd, quota_tokens, invitation_id, granted_at
                ) values (
                  :user_id, true, :quota_usd, :quota_tokens, :invitation_id, :now
                )
                on conflict (user_id) do update set
                  enabled = true
                where hosted_entitlements.enabled is not true
                """),
                {
                    "user_id": user_id,
                    "quota_usd": quota_usd,
                    "quota_tokens": quota_tokens,
                    "invitation_id": invitation_id,
                    "now": now,
                },
            )
        return bool(result.rowcount)

    async def get_profile(self, user_id: UUID) -> UserProfile:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            """
                            select display_name, username, bio, avatar_value
                            from app_users where id = :id
                            """
                        ),
                        {"id": user_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return UserProfile()
        return UserProfile(
            display_name=row.get("display_name"),
            username=row.get("username"),
            bio=row.get("bio"),
            avatar_value=row.get("avatar_value"),
        )

    async def upsert_profile(self, user_id: UUID, profile: UserProfile) -> UserProfile:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text(
                    """
                    update app_users
                    set display_name = :display_name,
                        username = :username,
                        bio = :bio,
                        avatar_value = :avatar_value
                    where id = :id
                    """
                ),
                {
                    "id": user_id,
                    "display_name": profile.display_name,
                    "username": profile.username,
                    "bio": profile.bio,
                    "avatar_value": profile.avatar_value,
                },
            )
        return await self.get_profile(user_id)

    async def username_taken(self, username: str, user_id: UUID) -> bool:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        select 1 from app_users
                        where lower(username) = lower(:username) and id <> :id
                        limit 1
                        """
                    ),
                    {"username": username, "id": user_id},
                )
            ).first()
        return row is not None

    @staticmethod
    def _to_principal(row: dict[str, Any]) -> Principal:
        enabled = bool(row.get("hosted_enabled"))
        return Principal(
            user_id=row["id"],
            clerk_user_id=row["clerk_user_id"],
            email=row.get("email"),
            email_verified=bool(row.get("email_verified")),
            role=row.get("role") or "user",
            invited=enabled,
            hosted_enabled=enabled,
            hosted_quota_usd=float(row.get("quota_usd") or 0),
            hosted_quota_tokens=int(row.get("quota_tokens") or 0),
        )

    @staticmethod
    def _to_invitation(row: dict[str, Any]) -> Invitation:
        email = row.get("email")
        return Invitation(
            invitation_id=row["id"],
            email=email,
            note=row.get("note") or "",
            kind=_kind_for(email),
            max_redemptions=int(row.get("max_redemptions") or 1),
            redemption_count=int(row.get("redemption_count") or 0),
            hosted_quota_usd=float(row.get("hosted_quota_usd") or 0),
            hosted_quota_tokens=int(row.get("hosted_quota_tokens") or 0),
            expires_at=row["expires_at"],
            created_by=row.get("created_by"),
            revoked_at=row.get("revoked_at"),
            redeemed_at=row.get("redeemed_at"),
            redeemed_by=row.get("redeemed_by"),
        )
