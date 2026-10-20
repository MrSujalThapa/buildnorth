"""One owner/mode resolver for all semantic agents. No cross-mode/provider fallback."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    ForbiddenError,
    InferenceOutputError,
    ProviderAuthenticationError,
    ProviderNotConfiguredError,
    SemanticProviderError,
    TransientProviderError,
    UnauthorizedError,
)
from personal_markets.core.request_context import client_ip_var
from personal_markets.identity.budget import InferenceBudgetService
from personal_markets.identity.credentials import CredentialCipher, CredentialStore, UserProvider
from personal_markets.identity.domain import Principal
from personal_markets.identity.inference_audit import InferenceAudit
from personal_markets.integrations.inference_catalog import (
    capability,
    default_model,
    hosted_allowlist,
    resolve_capability,
)
from personal_markets.integrations.inference_http import CompletionKind, NativeInferenceAdapter
from personal_markets.ports import InferenceRequest, InferenceResponse


def hosted_provider(settings: Settings) -> str:
    chosen = settings.inference_provider.lower().strip()
    if chosen == "auto":
        # Hosted inference is Spur-funded. OpenAI/Anthropic keys are BYOK-only and
        # must never become an implicit hosted fallback.
        return "spur" if settings.spur_api_key else "none"
    if chosen not in {"spur", "openai", "anthropic", "none"}:
        raise ProviderNotConfiguredError("Unsupported hosted provider configuration")
    return chosen


class InferenceRouter:
    def __init__(
        self,
        settings: Settings,
        credentials: CredentialStore,
        budget: InferenceBudgetService,
        audit: InferenceAudit,
        principal_lookup: Callable[[UUID], Awaitable[Principal | None]],
        adapter_factory: Callable[..., Any] = NativeInferenceAdapter,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._cipher = CredentialCipher(settings.byok_encryption_keys, settings.byok_active_key_id)
        self._budget = budget
        self._audit = audit
        self._lookup = principal_lookup
        self._adapter_factory = adapter_factory
        self._semaphore = asyncio.Semaphore(max(1, settings.openai_max_concurrency))

    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        return await self._complete(request, "structured")

    async def complete_text(self, request: InferenceRequest) -> InferenceResponse:
        return await self._complete(request, "text")

    async def complete_tools(self, request: InferenceRequest) -> InferenceResponse:
        return await self._complete(request, "tools")

    async def _complete(self, request: InferenceRequest, kind: CompletionKind) -> InferenceResponse:
        if request.user_id is None:
            raise UnauthorizedError("Authenticated inference owner is required")
        principal = await self._lookup(request.user_id)
        if principal is None:
            raise UnauthorizedError("Authenticated inference owner is unavailable")
        if not principal.invited and principal.role != "admin":
            raise ForbiddenError("An application invitation is required")
        try:
            preference = await self._credentials.preference(principal.user_id)
        except Exception:
            raise ProviderNotConfiguredError(
                "Inference preference storage is unavailable"
            ) from None
        mode = preference.mode
        provider = preference.provider if mode == "byok" else hosted_provider(self._settings)
        if provider == "none":
            raise ProviderNotConfiguredError("Hosted inference is not configured")
        override = self._settings.inference_agent_overrides.get(request.agent_name, {})
        if mode == "hosted":
            override_provider = override.get("provider")
            if override_provider and override_provider != provider:
                raise SemanticProviderError(
                    "Hosted inference cannot switch providers per agent; "
                    "use BYOK to choose OpenAI or Anthropic"
                )
            configured_model = (
                self._settings.inference_model
                or (
                    self._settings.resolved_spur_model()
                    if provider == "spur"
                    else None
                )
                or default_model(provider)
            )
            allowlist = hosted_allowlist(provider, configured_model)
            if request.model and request.model not in allowlist:
                raise SemanticProviderError(
                    "Hosted inference can only use the platform-authorized model"
                )
            candidate = preference.model or override.get("model") or configured_model
            model = candidate if candidate in allowlist else configured_model
        else:
            # A user's selected provider/model takes precedence over hosted agent settings.
            model = request.model or preference.model or default_model(provider)
        cap = resolve_capability(provider, model) if mode == "byok" else capability(provider, model)
        if kind == "structured" and not cap.structured:
            raise SemanticProviderError(
                "Selected model does not support structured forecasting output"
            )
        if kind == "tools" and not cap.tools:
            raise SemanticProviderError("Selected model does not support tool calling")
        if request.fallback_models:
            raise SemanticProviderError(
                "Implicit model fallback is disabled; select a model explicitly"
            )
        output_limit = max(
            cap.minimum_output_tokens,
            request.max_output_tokens or self._settings.openai_max_output_tokens,
        )
        serialized = json.dumps(
            {
                "instructions": request.instructions,
                "input": request.input,
                "schema": request.output_schema,
                "tools": [t.model_dump() for t in request.tools],
            },
            default=str,
        )
        input_bytes = len(serialized.encode("utf-8"))
        if input_bytes > self._settings.inference_max_input_bytes:
            raise SemanticProviderError("Inference input exceeds the execution limit")
        # UTF-8 byte count plus framing is a conservative token upper bound for text inputs.
        input_bound = input_bytes + 1024
        scoped = request.model_copy(
            update={
                "model": model,
                "max_output_tokens": output_limit,
                "timeout_seconds": min(
                    request.timeout_seconds or self._settings.openai_timeout_seconds,
                    self._settings.inference_run_timeout_seconds,
                ),
            }
        )
        try:
            async with asyncio.timeout(self._settings.inference_run_timeout_seconds):
                async with self._semaphore:
                    for attempt in range(min(self._settings.openai_max_retries, 3) + 1):
                        try:
                            response = await self._attempt(
                                principal, scoped, mode, provider, input_bound, output_limit, kind
                            )
                            response.retries = attempt
                            return response
                        except TransientProviderError:
                            if attempt >= min(self._settings.openai_max_retries, 3):
                                raise
                            await asyncio.sleep(0.2 * (2**attempt))
        except TimeoutError:
            raise TransientProviderError(
                "Inference execution timed out; no alternate provider was used"
            ) from None
        raise TransientProviderError("Inference failed")

    async def _attempt(
        self,
        principal: Principal,
        request: InferenceRequest,
        mode: Literal["hosted", "byok"],
        provider: str,
        input_bound: int,
        output_limit: int,
        kind: CompletionKind,
    ) -> InferenceResponse:
        version = None
        if mode == "byok":
            await self._budget.enforce_application_limits(
                principal.user_id, request.client_ip or client_ip_var.get()
            )
            try:
                credential = await self._credentials.get(principal.user_id, provider)  # type: ignore[arg-type]
            except Exception:
                raise ProviderNotConfiguredError("BYOK credential storage is unavailable") from None
            if credential is None:
                raise ProviderNotConfiguredError(
                    "Selected BYOK key is missing or deleted. Add a key in Settings."
                )
            key = self._cipher.decrypt(principal.user_id, provider, credential.ciphertext)
            if credential.status == "invalid":
                raise ProviderAuthenticationError(
                    "Selected BYOK key is invalid. Validate or replace it in Settings."
                )
            version = credential.version
        else:
            hosted_key = {
                "spur": self._settings.spur_api_key,
                "openai": self._settings.openai_api_key,
                "anthropic": self._settings.anthropic_api_key,
            }.get(provider)
            if not hosted_key:
                raise ProviderNotConfiguredError("Selected hosted provider is not configured")
            key = hosted_key
        adapter = self._adapter_factory(provider, key)
        reservation = None
        if mode == "hosted":
            reservation = await self._budget.reserve(
                principal,
                agent_name=request.agent_name,
                provider=provider,
                model=request.model or "",
                max_output_tokens=output_limit,
                input_token_bound=input_bound,
                client_ip=request.client_ip or client_ip_var.get(),
            )
        started = time.perf_counter()
        response = None
        known_usage: dict[str, int] | None = None
        outcome = "success"
        try:
            method = getattr(adapter, f"complete_{kind}")
            response = cast(InferenceResponse, await method(request))
            response.billing_mode = mode
            return response
        except BaseException as error:
            outcome = (
                "cancelled" if isinstance(error, asyncio.CancelledError) else type(error).__name__
            )
            if (
                mode == "byok"
                and version is not None
                and isinstance(error, ProviderAuthenticationError)
            ):
                try:
                    await self._credentials.set_status(
                        principal.user_id, cast(UserProvider, provider), version, "invalid"
                    )
                except Exception:
                    raise ProviderNotConfiguredError(
                        "Credential status storage is unavailable"
                    ) from None
            if isinstance(error, InferenceOutputError):
                known_usage = error.usage
            raise
        finally:
            # Unknown upstream usage (including malformed JSON/timeouts) retains the maximum
            # reservation charge. We cannot assume an error means the provider billed nothing.
            usage = response.usage if response and response.usage_reported else known_usage
            used_in = usage.get("input_tokens", 0) if usage is not None else input_bound
            used_out = usage.get("output_tokens", 0) if usage is not None else output_limit
            priced = (
                resolve_capability(provider, request.model or "")
                if mode == "byok"
                else capability(provider, request.model or "")
            )
            cost = priced.estimate(used_in, used_out)
            if response and not response.usage_reported:
                response.usage = {"input_tokens": used_in, "output_tokens": used_out}
                response.estimated_cost_usd = cost
            try:
                if reservation:
                    await self._budget.settle(
                        reservation,
                        principal=principal,
                        agent_name=request.agent_name,
                        provider=provider,
                        model=request.model or "",
                        input_tokens=used_in,
                        output_tokens=used_out,
                    )
                await self._audit.record(
                    {
                        "execution_id": uuid4(),
                        "user_id": principal.user_id,
                        "clerk_user_id": principal.clerk_user_id,
                        "agent_name": request.agent_name,
                        "provider": provider,
                        "model": request.model,
                        "billing_mode": mode,
                        "credential_version": version,
                        "input_tokens": used_in,
                        "output_tokens": used_out,
                        "estimated_cost_usd": cost,
                        "outcome": outcome,
                        "usage_reported": usage is not None,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    },
                    reservation.reservation_id if reservation else None,
                )
            except Exception:
                raise ProviderNotConfiguredError(
                    "Inference usage accounting is unavailable; the request stopped"
                ) from None
