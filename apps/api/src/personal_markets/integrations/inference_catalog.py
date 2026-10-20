"""Explicit supported models. Prices are estimates, versioned by source below."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from personal_markets.core.errors import SemanticProviderError

COMPAT_STRUCTURED = "structured"
COMPAT_TEXT = "text"
COMPAT_INCOMPATIBLE = "incompatible"
COMPAT_UNVERIFIED = "unverified"

_OPENAI_STRUCTURED_PREFIXES = ("gpt-4", "gpt-5", "gpt-6", "chatgpt-4", "o1", "o3", "o4")
_OPENAI_INCOMPATIBLE_MARKERS = (
    "embed",
    "whisper",
    "tts",
    "dall-e",
    "dall_e",
    "moderation",
    "sora",
    "transcribe",
    "realtime",
    "image",
    "audio",
    "computer-use",
)
_OPENAI_REASONING_PREFIXES = ("o1", "o3", "o4")


@dataclass(frozen=True)
class ModelCapability:
    provider: str
    model: str
    input_usd_per_million: float
    output_usd_per_million: float
    structured: bool = True
    tools: bool = True
    minimum_output_tokens: int = 32
    pricing_basis: str = "published standard rates, checked 2026-10-17"
    display_name: str | None = None
    pricing_available: bool = True
    compatibility: str = COMPAT_STRUCTURED
    source: str = "catalog"

    def estimate(self, input_tokens: int, output_tokens: int) -> float:
        if not self.pricing_available:
            return 0.0
        return (
            input_tokens * self.input_usd_per_million + output_tokens * self.output_usd_per_million
        ) / 1_000_000


MODELS = (
    ModelCapability("openai", "gpt-5.4-nano", 0.20, 1.25, display_name="GPT-5.4 nano"),
    ModelCapability("openai", "gpt-5.4-mini", 0.75, 4.50, display_name="GPT-5.4 mini"),
    ModelCapability("openai", "gpt-5.4", 2.50, 15, display_name="GPT-5.4"),
    ModelCapability("anthropic", "claude-sonnet-5-5", 2, 10, display_name="Claude Sonnet 5.5"),
    ModelCapability("anthropic", "claude-opus-5-5", 4, 20, display_name="Claude Opus 5.5"),
    ModelCapability(
        "spur",
        "spur-glm-5-3",
        2.50,
        15,
        tools=False,
        minimum_output_tokens=4096,
        pricing_basis="conservative application ceiling; Spur price not verified",
        display_name="Spur GLM 5.3",
        pricing_available=True,
    ),
)


def catalog_get(provider: str, model: str) -> ModelCapability | None:
    for item in MODELS:
        if item.provider == provider and item.model == model:
            return item
    return None


def capability(provider: str, model: str) -> ModelCapability:
    found = catalog_get(provider, model)
    if found is None:
        raise SemanticProviderError(
            "Unsupported provider/model selection; choose a supported model"
        )
    return found


def model_catalog() -> list[dict[str, object]]:
    return [asdict(item) for item in MODELS]


def hosted_model_catalog(provider: str, configured_model: str | None) -> list[dict[str, object]]:
    allowed = hosted_allowlist(provider, configured_model)
    return [asdict(item) for item in MODELS if item.provider == provider and item.model in allowed]


def hosted_allowlist(provider: str, configured_model: str | None) -> set[str]:
    cataloged = {item.model for item in MODELS if item.provider == provider}
    if configured_model and configured_model in cataloged:
        return {configured_model}
    return cataloged


def default_model(provider: str) -> str:
    return {"openai": "gpt-5.4-mini", "anthropic": "claude-sonnet-5-5", "spur": "spur-glm-5-3"}[
        provider
    ]


def classify_discovered(
    provider: str, model: str, *, display_name: str | None = None
) -> ModelCapability:
    """Classify a provider-listed model ID. Does not invent IDs."""
    known = catalog_get(provider, model)
    if known is not None:
        return replace(known, display_name=display_name or known.display_name, source="catalog")
    if provider == "openai":
        return _classify_openai(model, display_name)
    if provider == "anthropic":
        return _classify_anthropic(model, display_name)
    if provider == "spur":
        return ModelCapability(
            "spur",
            model,
            0.0,
            0.0,
            structured=False,
            tools=False,
            pricing_basis="unavailable",
            display_name=display_name,
            pricing_available=False,
            compatibility=COMPAT_INCOMPATIBLE,
            source="discovered",
        )
    raise SemanticProviderError(
        "Unsupported provider/model selection; choose a supported model"
    )


def resolve_capability(provider: str, model: str) -> ModelCapability:
    known = catalog_get(provider, model)
    if known is not None:
        return known
    classified = classify_discovered(provider, model)
    if not classified.structured:
        raise SemanticProviderError(
            "This model is listed by the provider but is not compatible "
            "with structured forecasting. "
            "Choose a model marked compatible."
        )
    return classified


def _classify_openai(model: str, display_name: str | None) -> ModelCapability:
    lowered = model.lower()
    if any(marker in lowered for marker in _OPENAI_INCOMPATIBLE_MARKERS):
        return ModelCapability(
            "openai",
            model,
            0.0,
            0.0,
            structured=False,
            tools=False,
            pricing_basis="unavailable",
            display_name=display_name,
            pricing_available=False,
            compatibility=COMPAT_INCOMPATIBLE,
            source="discovered",
        )
    if any(lowered.startswith(prefix) for prefix in _OPENAI_STRUCTURED_PREFIXES):
        reasoning = any(lowered.startswith(prefix) for prefix in _OPENAI_REASONING_PREFIXES)
        return ModelCapability(
            "openai",
            model,
            0.0,
            0.0,
            structured=True,
            tools=not reasoning,
            pricing_basis="unavailable",
            display_name=display_name or model,
            pricing_available=False,
            compatibility=COMPAT_STRUCTURED,
            source="discovered",
        )
    return ModelCapability(
        "openai",
        model,
        0.0,
        0.0,
        structured=False,
        tools=False,
        pricing_basis="unavailable",
        display_name=display_name or model,
        pricing_available=False,
        compatibility=COMPAT_UNVERIFIED,
        source="discovered",
    )


def _classify_anthropic(model: str, display_name: str | None) -> ModelCapability:
    lowered = model.lower()
    if lowered.startswith("claude-"):
        return ModelCapability(
            "anthropic",
            model,
            0.0,
            0.0,
            structured=True,
            tools=True,
            pricing_basis="unavailable",
            display_name=display_name or model,
            pricing_available=False,
            compatibility=COMPAT_STRUCTURED,
            source="discovered",
        )
    return ModelCapability(
        "anthropic",
        model,
        0.0,
        0.0,
        structured=False,
        tools=False,
        pricing_basis="unavailable",
        display_name=display_name or model,
        pricing_available=False,
        compatibility=COMPAT_UNVERIFIED,
        source="discovered",
    )
