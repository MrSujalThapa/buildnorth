from dataclasses import dataclass

from personal_markets.core.config import Settings

PREMIUM_MODELS = frozenset({"gpt-5.4", "claude-opus-5-5"})
HIGH_VOLUME_MODELS = frozenset({"gpt-5.4-mini", "gpt-5.4-nano"})

# Conservative estimates used only for budget guards, not billing.
ESTIMATED_USD_PER_MILLION: dict[str, dict[str, float]] = {
    "gpt-5.4-nano": {"input": 0.20, "output": 1.25},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "spur-glm-5-3": {"input": 0.30, "output": 1.00},
    "claude-sonnet-5-5": {"input": 2, "output": 10},
    "claude-opus-5-5": {"input": 4, "output": 20},
}


@dataclass(frozen=True, slots=True)
class ModelLadder:
    primary: str
    fallbacks: tuple[str, ...]
    pool: str
    reasoning_effort: str | None


def pool_for_model(model: str) -> str:
    if model in PREMIUM_MODELS:
        return "premium"
    return "high_volume"


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = ESTIMATED_USD_PER_MILLION.get(model, ESTIMATED_USD_PER_MILLION["gpt-5.4"])
    return (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates[
        "output"
    ]


def ladders(settings: Settings) -> dict[str, ModelLadder]:
    return {
        "goal_architect": ModelLadder(
            settings.openai_goal_model,
            ("gpt-5.4",) if settings.openai_goal_model != "gpt-5.4" else (),
            pool_for_model(settings.openai_goal_model),
            "low",
        ),
        "evidence": ModelLadder(
            settings.openai_evidence_model,
            ("gpt-5.4-mini",) if settings.openai_evidence_model != "gpt-5.4-mini" else (),
            pool_for_model(settings.openai_evidence_model),
            None,
        ),
        "research": ModelLadder(
            settings.openai_research_model,
            ("gpt-5.4",) if settings.openai_research_model != "gpt-5.4" else (),
            pool_for_model(settings.openai_research_model),
            "low",
        ),
        "critic": ModelLadder(settings.openai_critic_model, (), "premium", "medium"),
        "intervention": ModelLadder(
            settings.openai_intervention_model,
            ("gpt-5.4",) if settings.openai_intervention_model != "gpt-5.4" else (),
            pool_for_model(settings.openai_intervention_model),
            "low",
        ),
        "strategy": ModelLadder(
            settings.openai_intervention_model,
            ("gpt-5.4",) if settings.openai_intervention_model != "gpt-5.4" else (),
            pool_for_model(settings.openai_intervention_model),
            "low",
        ),
        "source_planner": ModelLadder(
            settings.openai_source_planner_model,
            ("gpt-5.4-mini",) if settings.openai_source_planner_model != "gpt-5.4-mini" else (),
            pool_for_model(settings.openai_source_planner_model),
            "low",
        ),
        "baseline": ModelLadder(settings.openai_baseline_model, (), "premium", "low"),
    }
