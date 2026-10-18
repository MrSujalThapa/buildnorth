"""Explicit supported models. Prices are estimates, versioned by source below."""

from dataclasses import asdict, dataclass

from personal_markets.core.errors import SemanticProviderError


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

    def estimate(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_usd_per_million + output_tokens * self.output_usd_per_million
        ) / 1_000_000


MODELS = (
    ModelCapability("openai", "gpt-5.4-nano", 0.20, 1.25),
    ModelCapability("openai", "gpt-5.4-mini", 0.75, 4.50),
    ModelCapability("openai", "gpt-5.4", 2.50, 15),
    ModelCapability("anthropic", "claude-sonnet-5-5", 2, 10),
    ModelCapability("anthropic", "claude-opus-5-5", 4, 20),
    ModelCapability(
        "spur",
        "spur-glm-5-3",
        2.50,
        15,
        tools=False,
        minimum_output_tokens=4096,
        pricing_basis="conservative application ceiling; Spur price not verified",
    ),
)


def capability(provider: str, model: str) -> ModelCapability:
    for item in MODELS:
        if item.provider == provider and item.model == model:
            return item
    raise SemanticProviderError("Unsupported provider/model selection; choose a supported model")


def model_catalog() -> list[dict[str, object]]:
    return [asdict(item) for item in MODELS]


def default_model(provider: str) -> str:
    return {"openai": "gpt-5.4-mini", "anthropic": "claude-sonnet-5-5", "spur": "spur-glm-5-3"}[
        provider
    ]
