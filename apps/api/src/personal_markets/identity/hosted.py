from __future__ import annotations

from personal_markets.identity.budget import InferenceBudgetService
from personal_markets.identity.domain import Principal
from personal_markets.ports import InferenceProvider, InferenceRequest, InferenceResponse


class HostedInferenceGateway:
    def __init__(
        self,
        inner: InferenceProvider,
        budget: InferenceBudgetService,
        *,
        provider_name: str,
        max_output_tokens: int,
        principal_lookup,
    ) -> None:
        self._inner = inner
        self._budget = budget
        self._provider_name = provider_name
        self._max_output_tokens = max_output_tokens
        self._principal_lookup = principal_lookup

    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        user_id = getattr(request, "user_id", None)
        if user_id is None:
            debug = request.input.get("user_id") if isinstance(request.input, dict) else None
            user_id = debug
        principal: Principal | None = None
        if user_id is not None:
            principal = await self._principal_lookup(user_id)
        if principal is None:
            from personal_markets.core.errors import UnauthorizedError

            raise UnauthorizedError("hosted inference requires an authenticated user")
        from personal_markets.core.request_context import client_ip_var

        reservation = await self._budget.reserve(
            principal,
            agent_name=request.agent_name,
            provider=self._provider_name,
            model=request.model or "unknown",
            max_output_tokens=self._max_output_tokens,
            client_ip=getattr(request, "client_ip", None) or client_ip_var.get(),
        )
        try:
            response = await self._inner.complete_structured(request)
        except Exception:
            await self._budget.release(reservation)
            raise
        await self._budget.settle(
            reservation,
            principal=principal,
            agent_name=request.agent_name,
            provider=response.provider,
            model=response.model,
            input_tokens=int(response.usage.get("input_tokens", 0)),
            output_tokens=int(response.usage.get("output_tokens", 0)),
        )
        return response
