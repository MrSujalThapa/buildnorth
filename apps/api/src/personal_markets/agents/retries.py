from personal_markets.core.errors import (
    PermanentProviderError,
    SemanticProviderError,
    TransientProviderError,
)

TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "429",
    "rate limit",
    "rate_limit",
    "503",
    "502",
    "500",
    "529",
    "overloaded",
    "connection",
    "temporarily",
    "try again",
)
PERMANENT_MARKERS = (
    "invalid api key",
    "incorrect api key",
    "authentication",
    "unauthorized",
    "401",
    "unsupported model",
    "model_not_found",
    "does not exist",
    "permission",
)
SEMANTIC_MARKERS = (
    "json",
    "schema",
    "validation",
    "required property",
    "invalid_json",
    "parse",
)


def classify_provider_error(error: Exception) -> type[Exception]:
    name = type(error).__name__.lower()
    text = str(error).lower()
    combined = f"{name} {text}"
    if any(marker in combined for marker in PERMANENT_MARKERS):
        return PermanentProviderError
    if any(marker in combined for marker in TRANSIENT_MARKERS):
        return TransientProviderError
    if any(marker in combined for marker in SEMANTIC_MARKERS):
        return SemanticProviderError
    status = getattr(error, "status_code", None)
    if status in {408, 409, 429, 500, 502, 503, 504, 529}:
        return TransientProviderError
    if status in {400, 401, 403, 404, 422}:
        return PermanentProviderError if status in {401, 403, 404} else SemanticProviderError
    return TransientProviderError
