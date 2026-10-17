"""Spur OpenAI-compatible chat-completions adapter.

Spur documents `https://ai.spuric.com/v1` plus `chat.completions`. Product agents
only need structured JSON; this adapter does not call OpenAI and does not fall back
to `PM_OPENAI_API_KEY`.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import uuid4

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from personal_markets.agents.budget import TokenBudget
from personal_markets.core.errors import (
    PermanentProviderError,
    ProviderBudgetExceededError,
    ProviderNotConfiguredError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.ports import InferenceRequest, InferenceResponse

_FOREIGN_PREFIXES = ("gpt-", "o1", "o3", "o4", "claude", "gemini")


class SpurInferenceProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
        budget: TokenBudget,
        timeout_seconds: float = 45,
        max_retries: int = 3,
        max_concurrency: int = 4,
        max_output_tokens: int = 1200,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError("Spur API key is required")
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )
        self._default_model = default_model
        self._budget = budget
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrency)
        # GLM-class reasoning models spend output tokens on thinking; Spur's FAQ
        # says replies can be empty below ~1000 max_tokens.
        self._max_output_tokens = max(max_output_tokens, 1024)

    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        model = self._resolve_model(request)
        last_error: Exception | None = None
        retries = 0
        for attempt in range(self._max_retries + 1):
            try:
                await self._budget.ensure_allowed(model, projected_tokens=self._max_output_tokens)
                async with self._semaphore:
                    return await self._once(request, model, retries)
            except (
                SemanticProviderError,
                PermanentProviderError,
                ProviderBudgetExceededError,
                ProviderNotConfiguredError,
            ):
                raise
            except Exception as error:
                wrapped = _wrap(error)
                last_error = wrapped
                if isinstance(wrapped, TransientProviderError) and attempt < self._max_retries:
                    retries += 1
                    await asyncio.sleep(0.2 * (2**attempt))
                    continue
                raise wrapped from error
        raise last_error or TransientProviderError("spur request failed")

    def _resolve_model(self, request: InferenceRequest) -> str:
        candidate = request.model or self._default_model
        lowered = candidate.strip().lower()
        if any(lowered.startswith(prefix) for prefix in _FOREIGN_PREFIXES):
            return self._default_model
        return candidate

    async def _once(self, request: InferenceRequest, model: str, retries: int) -> InferenceResponse:
        started = time.perf_counter()
        schema = json.dumps(request.output_schema, sort_keys=True, default=str)
        system = (
            f"{request.instructions}\n\n"
            "Return a single JSON object that matches this JSON Schema. "
            "Do not wrap it in markdown. Do not invent a probability unless the schema requires it.\n"
            f"{schema}"
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(request.input, sort_keys=True, default=str),
                },
            ],
            "max_tokens": self._max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if request.timeout_seconds:
            kwargs["timeout"] = request.timeout_seconds
        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0].message.content if response.choices else None
        if not choice:
            raise SemanticProviderError("model returned empty content")
        try:
            output = json.loads(choice)
        except json.JSONDecodeError as error:
            raise SemanticProviderError("model returned invalid JSON") from error
        if not isinstance(output, dict):
            raise SemanticProviderError("structured output must be an object")
        usage = response.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        await self._budget.record(model, input_tokens, output_tokens)
        return InferenceResponse(
            structured_output=output,
            provider="spur",
            model=model,
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            request_id=getattr(response, "id", None) or str(uuid4()),
            retries=retries,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _wrap(error: Exception) -> Exception:
    if isinstance(
        error,
        TransientProviderError
        | PermanentProviderError
        | SemanticProviderError
        | ProviderBudgetExceededError
        | ProviderNotConfiguredError,
    ):
        return error
    if isinstance(error, AuthenticationError):
        return PermanentProviderError("spur authentication failed")
    if isinstance(error, RateLimitError | APITimeoutError | APIConnectionError):
        return TransientProviderError(str(error) or "spur transient error")
    if isinstance(error, APIStatusError) and error.status_code >= 500:
        return TransientProviderError(str(error) or "spur server error")
    if isinstance(error, APIStatusError) and error.status_code in {400, 404, 422}:
        return SemanticProviderError(str(error) or "spur rejected the request")
    return PermanentProviderError(str(error) or "spur request failed")
