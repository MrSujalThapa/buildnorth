from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from personal_markets.core.errors import ProviderNotConfiguredError

DEFAULT_USER_ID = UUID("10000000-0000-0000-0000-000000000001")
AUTHENTICATED_SPUR_MODEL = "spur-glm-5-3"
_REPO_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PM_",
        env_file=str(_REPO_ROOT / ".env"),
        extra="ignore",
        populate_by_name=True,
    )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    cors_origin_regex: str | None = r"^http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+$"
    openai_api_key: str | None = None
    openai_model: str | None = None
    inference_provider: str = "auto"
    spur_api_key: str | None = Field(default=None, validation_alias="SPUR_API_KEY")
    spur_base_url: str = Field(
        default="https://ai.spuric.com/v1", validation_alias="SPUR_BASE_URL"
    )
    spur_model: str | None = None
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

    def resolved_spur_model(self) -> str:
        requested = (self.spur_model or "").strip() or AUTHENTICATED_SPUR_MODEL
        if requested == AUTHENTICATED_SPUR_MODEL:
            return requested
        raise ProviderNotConfiguredError(
            f"PM_SPUR_MODEL={requested} is not the authenticated Spur model "
            f"{AUTHENTICATED_SPUR_MODEL}. Set PM_SPUR_MODEL={AUTHENTICATED_SPUR_MODEL}."
        )


def safe_database_identity(database_url: str | None) -> str:
    """Host/port/name only. Never include credentials."""
    if not database_url:
        return "memory"
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    host = url.host or "localhost"
    port = f":{url.port}" if url.port else ""
    name = url.database or ""
    return f"{host}{port}/{name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
