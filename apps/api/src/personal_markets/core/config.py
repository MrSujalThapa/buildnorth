from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import EnvSettingsSource

from personal_markets.core.errors import ProviderNotConfiguredError

_LOCAL_ENVIRONMENTS = frozenset({"development", "test", "pytest"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

DEFAULT_USER_ID = UUID("10000000-0000-0000-0000-000000000001")
AUTHENTICATED_SPUR_MODEL = "spur-deepseek-v4-flash"
HOSTED_USER_QUOTA_USD = 10.0
_REPO_ROOT = Path(__file__).resolve().parents[5]


def cap_invited_quota_usd(requested: float | None = None) -> float:
    """Each invited user receives $10 of hosted Spur credit and cannot be granted more."""
    value = HOSTED_USER_QUOTA_USD if requested is None else requested
    return min(max(0.0, float(value)), HOSTED_USER_QUOTA_USD)


class _IgnoreBlankEnvSettingsSource(EnvSettingsSource):
    """Treat empty process env values as unset so `.env` can still supply secrets."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        value, key, is_complex = super().get_field_value(field, field_name)
        if isinstance(value, str) and not value.strip():
            return None, key, is_complex
        return value, key, is_complex


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PM_",
        env_file=str(_REPO_ROOT / ".env"),
        extra="ignore",
        populate_by_name=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _IgnoreBlankEnvSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    cors_origin_regex: str | None = r"^http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+$"
    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str | None = None
    inference_provider: str = "spur"
    inference_model: str | None = None
    inference_agent_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    inference_max_input_bytes: int = Field(default=48_000, ge=1024, le=100_000)
    inference_run_timeout_seconds: float = Field(default=120, gt=0, le=300)
    byok_encryption_keys: dict[str, str] = Field(default_factory=dict, repr=False)
    byok_active_key_id: str = "v1"
    anthropic_api_key: str | None = Field(default=None, repr=False)
    spur_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("PM_SPUR_API_KEY", "SPUR_API_KEY"), repr=False
    )
    spur_base_url: str = Field(
        default="https://ai.spuric.com/v1",
        validation_alias=AliasChoices("PM_SPUR_BASE_URL", "SPUR_BASE_URL"),
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
    intervention_max_output_tokens: int = 4096
    openai_timeout_seconds: float = 45
    openai_max_retries: int = 3
    openai_max_concurrency: int = 4
    openai_max_output_tokens: int = 1200
    openai_daily_token_budget_high_volume: int = 100_000_000
    openai_daily_token_budget_premium: int = 100_000_000
    openai_max_cost_usd: float = 100.0
    github_token: str | None = None
    monid_enabled: bool = False
    monid_api_base: str | None = None
    monid_client_id: str | None = None
    monid_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("PM_MONID_API_KEY", "MONID_API_KEY"), repr=False
    )
    monid_tool_provider: str | None = None
    monid_tool_endpoint: str | None = None
    monid_tool_input_template: dict[str, Any] = Field(default_factory=dict)
    monid_max_calls: int = Field(default=5, ge=3, le=10)
    monid_timeout_seconds: float = Field(default=25, gt=0, le=60)
    monid_max_cost_usd: float = Field(default=0.02, ge=0, le=1)
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
    admin_clerk_user_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    test_auth_secret: str | None = None
    scripted_inference: bool = False
    hosted_inference_enabled: bool = True
    hosted_user_quota_usd: float = Field(
        default=HOSTED_USER_QUOTA_USD, ge=0, le=HOSTED_USER_QUOTA_USD
    )
    hosted_user_quota_tokens: int = 5_000_000
    hosted_admin_quota_usd: float = Field(default=100.0, ge=0, le=100.0)
    hosted_admin_quota_tokens: int = 100_000_000
    hosted_global_quota_usd: float = 250.0
    hosted_global_quota_tokens: int = 250_000_000
    hosted_user_rpm: int = 20
    hosted_ip_rpm: int = 60
    invite_ttl_hours: int = 72
    invite_max_redemptions: int = 20
    dev_bootstrap_test_users: bool = False
    # Honor X-Forwarded-For only when the peer is in trusted_proxies. Default off so
    # a client cannot spoof rate-limit identity. Staging behind nginx/Caddy must set
    # PM_TRUST_FORWARDED_HEADERS=true and list the proxy addresses.
    trust_forwarded_headers: bool = False
    trusted_proxies: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"]
    )
    # Inbound remote MCP server. Public URLs are what external clients see; a hosted
    # assistant cannot reach loopback, so deployments must set HTTPS values.
    mcp_enabled: bool = True
    public_api_url: str = "http://127.0.0.1:8000"
    public_web_url: str = "http://localhost:5173"
    mcp_access_token_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    mcp_refresh_token_ttl_seconds: int = Field(default=30 * 86_400, ge=3600, le=90 * 86_400)
    mcp_auth_code_ttl_seconds: int = Field(default=300, ge=30, le=600)
    mcp_authorization_request_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    mcp_dynamic_client_registration: bool = True
    mcp_registrations_per_ip_hour: int = Field(default=20, ge=1, le=1000)
    mcp_max_request_bytes: int = Field(default=64_000, ge=4096, le=1_000_000)
    mcp_tool_calls_per_minute: int = Field(default=60, ge=1, le=1000)
    mcp_writes_per_minute: int = Field(default=20, ge=1, le=500)
    mcp_inference_calls_per_minute: int = Field(default=4, ge=1, le=60)
    mcp_inference_calls_per_day: int = Field(default=40, ge=1, le=1000)

    def resolved_clerk_jwks_url(self) -> str | None:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url.strip() or None
        issuer = (self.clerk_issuer or "").strip().rstrip("/")
        if issuer:
            return f"{issuer}/.well-known/jwks.json"
        return None

    def is_local_environment(self) -> bool:
        return self.environment.strip().lower() in _LOCAL_ENVIRONMENTS

    def is_publicly_reachable(self) -> bool:
        """True when public_api_url is HTTPS on a non-loopback host.

        Accidental `PM_ENVIRONMENT=development` on a shared staging hostname still
        counts as publicly reachable. Local https://127.0.0.1 does not.
        """
        raw = (self.public_api_url or "").strip()
        if not raw.lower().startswith("https://"):
            return False
        host = (urlparse(raw).hostname or "").lower()
        return bool(host) and host not in _LOOPBACK_HOSTS

    def is_deployed(self) -> bool:
        return (not self.is_local_environment()) or self.is_publicly_reachable()

    def assert_safe_startup(self) -> None:
        """Refuse test auth/bootstrap outside a local process.

        Staging and production must start with Clerk JWKS configured, no test
        HS256 secret, and bootstrap off. A mislabelled development env that
        advertises a public HTTPS API URL is treated as deployed.
        """
        if not self.is_deployed():
            return
        problems: list[str] = []
        if self.dev_bootstrap_test_users:
            problems.append("PM_DEV_BOOTSTRAP_TEST_USERS must be false")
        if self.test_auth_secret:
            problems.append("PM_TEST_AUTH_SECRET must be empty")
        if self.scripted_inference:
            problems.append("PM_SCRIPTED_INFERENCE must be false")
        if not self.resolved_clerk_jwks_url():
            problems.append("PM_CLERK_JWKS_URL is required")
        if problems:
            raise RuntimeError(
                "Refusing to start in a deployed environment: " + "; ".join(problems)
            )

    @field_validator("cors_origin_regex", mode="before")
    @classmethod
    def _empty_cors_regex(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "spur_api_key",
        "openai_api_key",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def _blank_secret_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "composio_enabled",
        "hosted_inference_enabled",
        "dev_bootstrap_test_users",
        "trust_forwarded_headers",
        "mcp_enabled",
        "mcp_dynamic_client_registration",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return value

    @field_validator(
        "admin_emails",
        "admin_clerk_user_ids",
        "clerk_authorized_parties",
        "trusted_proxies",
        mode="before",
    )
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
