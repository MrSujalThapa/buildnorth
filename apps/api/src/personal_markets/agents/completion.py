"""Shared typed completion policy for the four logical agents and their helpers."""

import asyncio
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ValidationError

from personal_markets.core.errors import (
    InferenceOutputError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.ports import InferenceProvider, InferenceRequest, InferenceResponse

MAX_SEMANTIC_RETRIES = 2


async def complete_validated[T: BaseModel](
    inference: InferenceProvider,
    request: InferenceRequest,
    model_cls: type[T],
    on_failure: Callable[[Exception, int], Awaitable[None]] | None = None,
    *,
    timeout_seconds: float = 90,
) -> tuple[T, InferenceResponse]:
    try:
        async with asyncio.timeout(timeout_seconds):
            return await _complete_validated(inference, request, model_cls, on_failure)
    except TimeoutError:
        raise TransientProviderError("Agent execution exceeded its wall-time limit") from None


async def _complete_validated[T: BaseModel](
    inference: InferenceProvider,
    request: InferenceRequest,
    model_cls: type[T],
    on_failure: Callable[[Exception, int], Awaitable[None]] | None,
) -> tuple[T, InferenceResponse]:
    for attempt in range(MAX_SEMANTIC_RETRIES):
        try:
            response = await inference.complete_structured(request)
            parsed = model_cls.model_validate(response.structured_output)
            response.retries += attempt
            return parsed, response
        except (InferenceOutputError, ValidationError) as error:
            # Native output errors contain only schema paths/stop reasons, never output values.
            reason = (
                str(error)
                if isinstance(error, InferenceOutputError)
                else "Typed output validation failed"
            )
            if on_failure:
                await on_failure(error, attempt)
            if attempt + 1 == MAX_SEMANTIC_RETRIES:
                raise SemanticProviderError(
                    "Agent output failed validation after bounded retries: " + reason
                ) from None
            request = request.model_copy(
                update={
                    "instructions": request.instructions
                    + "\nPrevious output failed validation: "
                    + reason
                    + ". Include all required properties; return only the requested schema."
                }
            )
    raise SemanticProviderError("Agent completion failed")
