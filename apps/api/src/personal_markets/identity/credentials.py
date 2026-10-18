"""Owner-bound AEAD credentials. No plaintext cache, provider keys or HTTP objects in DTOs."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.core.errors import ProviderNotConfiguredError
from personal_markets.persistence.database import transaction

UserProvider = Literal["openai", "anthropic"]


class InferencePreference(BaseModel):
    mode: Literal["hosted", "byok"] = "hosted"
    provider: UserProvider = "openai"
    model: str | None = None


class CredentialMetadata(BaseModel):
    provider: UserProvider
    status: Literal["validated", "invalid"] = "validated"
    masked_suffix: str
    version: UUID
    validated_at: datetime


@dataclass(frozen=True)
class StoredCredential:
    provider: UserProvider
    ciphertext: str = field(repr=False)
    suffix: str
    version: UUID
    validated_at: datetime
    status: Literal["validated", "invalid"] = "validated"

    def metadata(self) -> CredentialMetadata:
        return CredentialMetadata(
            provider=self.provider,
            masked_suffix=f"••••{self.suffix}",
            version=self.version,
            validated_at=self.validated_at,
            status=self.status,
        )


class CredentialCipher:
    def __init__(self, keys: dict[str, str], active_key_id: str) -> None:
        self._keys = keys
        self._active = active_key_id

    def _key(self, key_id: str) -> bytes:
        try:
            key = base64.b64decode(self._keys[key_id], altchars=b"-_", validate=True)
            if len(key) != 32:
                raise ValueError
            return key
        except (KeyError, ValueError):
            raise ProviderNotConfiguredError(
                "BYOK encryption key is unavailable or invalid"
            ) from None

    @staticmethod
    def _aad(owner: UUID, provider: str) -> bytes:
        return f"playitout:credential:v1:{owner}:{provider}".encode()

    def encrypt(self, owner: UUID, provider: str, secret: str) -> str:
        key = self._key(self._active)
        nonce = os.urandom(12)
        encrypted = AESGCM(key).encrypt(nonce, secret.encode(), self._aad(owner, provider))
        return f"{self._active}:{base64.urlsafe_b64encode(nonce + encrypted).decode()}"

    def decrypt(self, owner: UUID, provider: str, ciphertext: str) -> str:
        try:
            key_id, encoded = ciphertext.split(":", 1)
            data = base64.b64decode(encoded, altchars=b"-_", validate=True)
            return (
                AESGCM(self._key(key_id))
                .decrypt(data[:12], data[12:], self._aad(owner, provider))
                .decode()
            )
        except Exception:
            raise ProviderNotConfiguredError("BYOK credential could not be decrypted") from None


class CredentialStore(Protocol):
    async def get(self, owner: UUID, provider: UserProvider) -> StoredCredential | None: ...
    async def put(
        self, owner: UUID, provider: UserProvider, ciphertext: str, suffix: str
    ) -> None: ...
    async def delete(self, owner: UUID, provider: UserProvider) -> None: ...
    async def preference(self, owner: UUID) -> InferencePreference: ...
    async def set_preference(self, owner: UUID, preference: InferencePreference) -> None: ...
    async def set_status(
        self,
        owner: UUID,
        provider: UserProvider,
        version: UUID,
        status: Literal["validated", "invalid"],
    ) -> None: ...


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._credentials: dict[tuple[UUID, str], StoredCredential] = {}
        self._preferences: dict[UUID, InferencePreference] = {}

    async def get(self, owner: UUID, provider: UserProvider) -> StoredCredential | None:
        return self._credentials.get((owner, provider))

    async def put(self, owner: UUID, provider: UserProvider, ciphertext: str, suffix: str) -> None:
        self._credentials[owner, provider] = StoredCredential(
            provider, ciphertext, suffix, uuid4(), datetime.now(UTC)
        )

    async def delete(self, owner: UUID, provider: UserProvider) -> None:
        self._credentials.pop((owner, provider), None)

    async def preference(self, owner: UUID) -> InferencePreference:
        return self._preferences.get(owner, InferencePreference()).model_copy()

    async def set_preference(self, owner: UUID, preference: InferencePreference) -> None:
        self._preferences[owner] = preference.model_copy()

    async def set_status(
        self,
        owner: UUID,
        provider: UserProvider,
        version: UUID,
        status: Literal["validated", "invalid"],
    ) -> None:
        row = self._credentials.get((owner, provider))
        if row and row.version == version:
            self._credentials[owner, provider] = replace(row, status=status)


class PostgresCredentialStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, owner: UUID, provider: UserProvider) -> StoredCredential | None:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("""
                select provider, ciphertext, suffix, version, validated_at, status
                from provider_credentials where user_id=:owner and provider=:provider
            """),
                        {"owner": owner, "provider": provider},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return StoredCredential(**row) if row else None

    async def put(self, owner: UUID, provider: UserProvider, ciphertext: str, suffix: str) -> None:
        async with transaction(self._engine) as conn:
            await conn.execute(
                text("""
                insert into provider_credentials
                  (user_id, provider, ciphertext, suffix, version, validated_at)
                values (:owner, :provider, :ciphertext, :suffix, :version, now())
                on conflict (user_id, provider) do update set
                  ciphertext=excluded.ciphertext, suffix=excluded.suffix,
                  version=excluded.version, validated_at=excluded.validated_at, status='validated'
            """),
                {
                    "owner": owner,
                    "provider": provider,
                    "ciphertext": ciphertext,
                    "suffix": suffix,
                    "version": uuid4(),
                },
            )

    async def delete(self, owner: UUID, provider: UserProvider) -> None:
        async with transaction(self._engine) as conn:
            await conn.execute(
                text("""
                delete from provider_credentials where user_id=:owner and provider=:provider
            """),
                {"owner": owner, "provider": provider},
            )

    async def preference(self, owner: UUID) -> InferencePreference:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("""
                select mode, provider, model from inference_preferences where user_id=:owner
            """),
                        {"owner": owner},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return InferencePreference.model_validate(dict(row)) if row else InferencePreference()

    async def set_preference(self, owner: UUID, preference: InferencePreference) -> None:
        async with transaction(self._engine) as conn:
            await conn.execute(
                text("""
                insert into inference_preferences (user_id, mode, provider, model)
                values (:owner, :mode, :provider, :model)
                on conflict (user_id) do update set
                  mode=excluded.mode, provider=excluded.provider, model=excluded.model
            """),
                {"owner": owner, **preference.model_dump()},
            )

    async def set_status(
        self,
        owner: UUID,
        provider: UserProvider,
        version: UUID,
        status: Literal["validated", "invalid"],
    ) -> None:
        async with transaction(self._engine) as conn:
            await conn.execute(
                text("""
                update provider_credentials set status=:status
                where user_id=:owner and provider=:provider and version=:version
            """),
                {"owner": owner, "provider": provider, "version": version, "status": status},
            )
