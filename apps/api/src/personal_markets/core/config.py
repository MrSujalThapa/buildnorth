from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_USER_ID = UUID("10000000-0000-0000-0000-000000000001")
_REPO_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PM_",
        env_file=str(_REPO_ROOT / ".env"),
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    cors_origin_regex: str | None = r"^http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+$"
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_goal_model: str = "gpt-5.4-mini"
    openai_evidence_model: str = "gpt-5.4-nano"
    openai_research_model: str = "gpt-5.4-mini"
    openai_critic_model: str = "gpt-5.4"
    openai_intervention_model: str = "gpt-5.4-mini"
    openai_source_planner_model: str = "gpt-5.4-mini"
    openai_baseline_model: str = "gpt-5.4"
    intervention_agent_enabled: bool = True
    intervention_regex_fallback: bool = True
    openai_timeout_seconds: float = 45
    openai_max_retries: int = 3
    openai_max_concurrency: int = 4
    openai_max_output_tokens: int = 1200
    openai_daily_token_budget_high_volume: int = 2_500_000
    openai_daily_token_budget_premium: int = 250_000
    openai_max_cost_usd: float = 5.0
    github_token: str | None = None
    monid_enabled: bool = False
    monid_api_base: str | None = None
    monid_client_id: str | None = None
    default_user_id: UUID = DEFAULT_USER_ID
    dev_demo_fixtures: bool = False
    integration_provider: str = "composio"
    composio_enabled: bool = False
    composio_mcp: bool = True
    composio_api_key: str | None = Field(default=None, validation_alias="COMPOSIO_API_KEY")
    composio_base_url: str = "https://backend.composio.dev/api/v3.1"
    composio_connect_callback_url: str | None = None

    @field_validator("composio_enabled", mode="before")
    @classmethod
    def _coerce_bool(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
