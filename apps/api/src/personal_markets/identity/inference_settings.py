from __future__ import annotations

import time
from typing import Any

from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    DomainError,
    ProviderAuthenticationError,
    ProviderNotConfiguredError,
    SemanticProviderError,
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
from personal_markets.integrations.inference_catalog import (
    default_model,
    hosted_model_catalog,
    resolve_capability,
)
from personal_markets.integrations.inference_discovery import (
    parse_provider_models,
    recommended_model,
)
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
        self._discovered: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}

    async def view(self, principal: Principal, *, refresh_models: bool = False) -> dict[str, Any]:
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
            hosted_model = (
                self._settings.inference_model
                or (
                    self._settings.resolved_spur_model()
                    if provider == "spur"
                    else default_model(provider)
                    if provider not in {"none", ""}
                    else None
                )
            )
            discovered: dict[str, list[dict[str, Any]]] = {}
            for item in credentials:
                listed = await self.discover_models(
                    principal, item["provider"], refresh=refresh_models
                )
                if listed:
                    discovered[item["provider"]] = listed
            preference = await self._store.preference(principal.user_id)
            byok_models = (
                discovered.get(preference.provider, []) if preference.mode == "byok" else []
            )
            fallback_provider = (
                preference.provider if preference.mode == "byok" else (provider or "openai")
            )
            return {
                "preference": preference.model_dump(),
                "credentials": credentials,
                "models": hosted_model_catalog(provider, hosted_model)
                if preference.mode == "hosted" and provider != "none"
                else byok_models or hosted_model_catalog(preference.provider, None),
                "discovered_models": discovered,
                "recommended_model": recommended_model(
                    preference.provider if preference.mode == "byok" else provider or "spur",
                    byok_models,
                    hosted_model or default_model(fallback_provider),
                )
                if (preference.mode == "byok" and byok_models) or provider != "none"
                else None,
                "hosted_provider": provider,
                "hosted_configured": hosted_configured,
                "hosted_model": hosted_model,
                "byok_usage": await self._audit.byok_summary(principal.user_id),
            }
        except DomainError:
            raise
        except Exception:
            raise ProviderNotConfiguredError("Inference settings could not be loaded") from None

    async def discover_models(
        self, principal: Principal, provider: UserProvider, *, refresh: bool = False
    ) -> list[dict[str, Any]]:
        cache_key = (str(principal.user_id), provider)
        cached = self._discovered.get(cache_key)
        if cached and not refresh and cached[0] > time.monotonic():
            return cached[1]
        try:
            row = await self._store.get(principal.user_id, provider)
        except Exception:
            return []
        if row is None or row.status == "invalid":
            return []
        try:
            key = self._cipher.decrypt(principal.user_id, provider, row.ciphertext)
            payload = await NativeInferenceAdapter(provider, key).list_models()
            models = parse_provider_models(provider, payload)
        except DomainError:
            return []
        except Exception:
            return []
        self._discovered[cache_key] = (time.monotonic() + 300, models)
        return models

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
            await self.discover_models(principal, provider, refresh=True)
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
        if preference.mode == "hosted":
            hosted = hosted_provider(self._settings)
            if hosted != "none" and preference.model:
                allowed = {
                    item["model"]
                    for item in hosted_model_catalog(hosted, self._settings.inference_model)
                }
                if preference.model not in allowed:
                    raise SemanticProviderError(
                        "Hosted inference can only use the platform-authorized model"
                    )
        elif provider != "none":
            resolve_capability(provider, preference.model or default_model(provider))
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
