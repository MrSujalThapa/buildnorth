from __future__ import annotations

from typing import Any

from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    DomainError,
    ProviderAuthenticationError,
    ProviderNotConfiguredError,
)
from personal_markets.identity.budget import InferenceBudgetService
from personal_markets.identity.credentials import (
    CredentialCipher,
    CredentialMetadata,
    CredentialStore,
    InferencePreference,
    UserProvider,
)
from personal_markets.identity.domain import Principal
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.identity.inference_router import hosted_provider
from personal_markets.integrations.inference_catalog import capability, default_model, model_catalog
from personal_markets.integrations.inference_http import NativeInferenceAdapter


class InferenceSettingsService:
    def __init__(
        self,
        settings: Settings,
        store: CredentialStore,
        budget: InferenceBudgetService,
        audit: InferenceAudit,
    ) -> None:
        self._settings, self._store, self._budget, self._audit = settings, store, budget, audit
        self._cipher = CredentialCipher(settings.byok_encryption_keys, settings.byok_active_key_id)

    async def view(self, principal: Principal) -> dict[str, Any]:
        try:
            credentials = []
            for provider in ("openai", "anthropic"):
                row = await self._store.get(principal.user_id, provider)
                if row:
                    credentials.append(row.metadata().model_dump(mode="json"))
            provider = hosted_provider(self._settings)
            hosted_configured = bool(
                {
                    "openai": self._settings.openai_api_key,
                    "anthropic": self._settings.anthropic_api_key,
                    "spur": self._settings.spur_api_key,
                }.get(provider)
            )
            return {
                "preference": (await self._store.preference(principal.user_id)).model_dump(),
                "credentials": credentials,
                "models": model_catalog(),
                "hosted_provider": provider,
                "hosted_configured": hosted_configured,
                "hosted_model": self._settings.inference_model
                or (
                    self._settings.resolved_spur_model()
                    if provider == "spur"
                    else self._settings.openai_goal_model
                    if provider == "openai"
                    else default_model(provider)
                    if provider != "none"
                    else None
                ),
                "byok_usage": await self._audit.byok_summary(principal.user_id),
            }
        except DomainError:
            raise
        except Exception:
            raise ProviderNotConfiguredError("Inference settings could not be loaded") from None

    async def save_key(
        self, principal: Principal, provider: UserProvider, key: str, ip: str | None
    ) -> CredentialMetadata:
        await self._budget.enforce_application_limits(principal.user_id, ip)
        # Fail before sending a candidate to a provider if encryption is unavailable.
        ciphertext = self._cipher.encrypt(principal.user_id, provider, key)
        await NativeInferenceAdapter(provider, key).validate_key()
        try:
            await self._store.put_and_activate(principal.user_id, provider, ciphertext, key[-4:])
            row = await self._store.get(principal.user_id, provider)
            if row is None:
                raise ValueError
            return row.metadata()
        except Exception:
            raise ProviderNotConfiguredError(
                "Credential storage could not be confirmed; reload Settings before retrying"
            ) from None

    async def validate_key(
        self, principal: Principal, provider: UserProvider, ip: str | None
    ) -> CredentialMetadata:
        await self._budget.enforce_application_limits(principal.user_id, ip)
        try:
            row = await self._store.get(principal.user_id, provider)
        except Exception:
            raise ProviderNotConfiguredError("Credential storage is unavailable") from None
        if row is None:
            raise ProviderNotConfiguredError("No stored key for this provider")
        key = self._cipher.decrypt(principal.user_id, provider, row.ciphertext)
        try:
            await NativeInferenceAdapter(provider, key).validate_key()
        except ProviderAuthenticationError:
            try:
                await self._store.set_status(principal.user_id, provider, row.version, "invalid")
            except Exception:
                raise ProviderNotConfiguredError(
                    "Credential status storage is unavailable"
                ) from None
            raise
        try:
            await self._store.set_status(principal.user_id, provider, row.version, "validated")
        except Exception:
            raise ProviderNotConfiguredError("Credential status storage is unavailable") from None
        return row.metadata().model_copy(update={"status": "validated"})

    async def delete_key(self, principal: Principal, provider: UserProvider) -> None:
        try:
            await self._store.delete(principal.user_id, provider)
        except Exception:
            raise ProviderNotConfiguredError(
                "Credential deletion failed; retry before continuing"
            ) from None
        # Keep BYOK selected so deleting a key cannot accidentally start hosted billing.

    async def set_preference(
        self, principal: Principal, preference: InferencePreference
    ) -> dict[str, Any]:
        provider = (
            preference.provider if preference.mode == "byok" else hosted_provider(self._settings)
        )
        if provider != "none":
            capability(provider, preference.model or default_model(provider))
        if preference.mode == "byok":
            try:
                row = await self._store.get(principal.user_id, preference.provider)
            except Exception:
                raise ProviderNotConfiguredError("Credential storage is unavailable") from None
            if row is None:
                raise ProviderNotConfiguredError("Add and validate a key before selecting BYOK")
            if row.status == "invalid":
                raise ProviderAuthenticationError(
                    "Validate or replace the provider key before selecting BYOK"
                )
            self._cipher.decrypt(principal.user_id, preference.provider, row.ciphertext)
        try:
            await self._store.set_preference(principal.user_id, preference)
        except Exception:
            raise ProviderNotConfiguredError("Inference preference could not be saved") from None
        return await self.view(principal)
