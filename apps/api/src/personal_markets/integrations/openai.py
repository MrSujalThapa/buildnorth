import asyncio
import json
import random
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
from personal_markets.agents.retries import classify_provider_error
from personal_markets.core.errors import (
    PermanentProviderError,
    ProviderBudgetExceededError,
    ProviderNotConfiguredError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.ports import InferenceRequest, InferenceResponse


class UnconfiguredOpenAIInferenceProvider:
    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        del request
        raise ProviderNotConfiguredError(
            "OpenAI inference is not configured; set PM_OPENAI_API_KEY to enable product agents"
        )


class OpenAIInferenceProvider:
    """Structured-output adapter. Domain modules must not import this class."""

    def __init__(
        self,
        api_key: str,
        default_model: str,
        budget: TokenBudget,
        timeout_seconds: float = 45,
        max_retries: int = 3,
        max_concurrency: int = 4,
        max_output_tokens: int = 1200,
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError("OpenAI API key is required")
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._default_model = default_model
        self._budget = budget
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_output_tokens = max_output_tokens

    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        models = [request.model or self._default_model, *request.fallback_models]
        last_error: Exception | None = None
        retries = 0
        for index, model in enumerate(models):
            try:
                return await self._complete_with_retries(request, model, retries)
            except SemanticProviderError as error:
                last_error = error
                if index == len(models) - 1:
                    raise
            except (TransientProviderError, ProviderBudgetExceededError, PermanentProviderError):
                raise
        raise last_error or SemanticProviderError("structured completion failed")

    async def _complete_with_retries(
        self, request: InferenceRequest, model: str, prior_retries: int
    ) -> InferenceResponse:
        retries = prior_retries
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                await self._budget.ensure_allowed(model, projected_tokens=self._max_output_tokens)
                async with self._semaphore:
                    return await self._once(request, model, retries)
            except SemanticProviderError:
                raise
            except PermanentProviderError:
                raise
            except ProviderBudgetExceededError:
                raise
            except Exception as error:
                wrapped = _wrap(error)
                last_error = wrapped
                if isinstance(wrapped, TransientProviderError) and attempt < self._max_retries:
                    retries += 1
                    await asyncio.sleep(_backoff(attempt))
                    continue
                raise wrapped from error
        raise last_error or TransientProviderError("openai request failed")

    async def _once(self, request: InferenceRequest, model: str, retries: int) -> InferenceResponse:
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": request.instructions,
            "input": json.dumps(request.input, sort_keys=True, default=str),
            "max_output_tokens": self._max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": f"{request.agent_name}_output",
                    "strict": True,
                    "schema": request.output_schema,
                }
            },
        }
        if request.timeout_seconds:
            kwargs["timeout"] = request.timeout_seconds
        response = await self._client.responses.create(**kwargs)
        raw = response.output_text
        try:
            output = json.loads(raw)
        except json.JSONDecodeError as error:
            raise SemanticProviderError("model returned invalid JSON") from error
        if not isinstance(output, dict):
            raise SemanticProviderError("structured output must be an object")
        usage = response.usage
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        await self._budget.record(model, input_tokens, output_tokens)
        return InferenceResponse(
            structured_output=output,
            provider="openai",
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
        return PermanentProviderError("OpenAI authentication failed")
    if isinstance(error, RateLimitError | APITimeoutError | APIConnectionError):
        return TransientProviderError(str(error))
    if isinstance(error, APIStatusError):
        classified = classify_provider_error(error)
        return classified(str(error))
    classified = classify_provider_error(error)
    return classified(str(error))


def _backoff(attempt: int) -> float:
    return float(min(8.0, (2**attempt) * 0.25) + random.uniform(0, 0.25))
