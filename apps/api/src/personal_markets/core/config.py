from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    clerk_jwks_url: str | None = None
    clerk_issuer: str | None = None
    clerk_authorized_parties: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    clerk_secret_key: str | None = Field(default=None, validation_alias="CLERK_SECRET_KEY")
    admin_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    test_auth_secret: str | None = None
    hosted_inference_enabled: bool = True
    hosted_user_quota_usd: float = 2.0
    hosted_user_quota_tokens: int = 100_000
    hosted_global_quota_usd: float = 25.0
    hosted_global_quota_tokens: int = 1_000_000
    hosted_user_rpm: int = 20
    hosted_ip_rpm: int = 60
    invite_ttl_hours: int = 72
    invite_max_redemptions: int = 20
    dev_bootstrap_test_users: bool = False

    def resolved_clerk_jwks_url(self) -> str | None:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url.strip() or None
        issuer = (self.clerk_issuer or "").strip().rstrip("/")
        if issuer:
            return f"{issuer}/.well-known/jwks.json"
        return None

    @field_validator(
        "composio_enabled",
        "hosted_inference_enabled",
        "dev_bootstrap_test_users",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return value

    @field_validator("admin_emails", "clerk_authorized_parties", mode="before")
    @classmethod
    def _coerce_str_list(cls, value: object, info: ValidationInfo) -> object:
        items: list[str]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                import json

                parsed = json.loads(stripped)
                items = [str(item).strip() for item in parsed if str(item).strip()]
            else:
                items = [item.strip() for item in stripped.split(",") if item.strip()]
        elif isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
        else:
            return value
        if info.field_name == "admin_emails":
            return [item.lower() for item in items]
        return items

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
