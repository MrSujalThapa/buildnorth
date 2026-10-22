import pytest
from fastapi.testclient import TestClient
from httpx import Response

from helpers import isolated_app
from personal_markets.core.config import Settings


def test_health_endpoint_and_backend_boot() -> None:
    with TestClient(isolated_app()) as client:
        response = client.get("/health", headers={"x-request-id": "test-request"})
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "personal-markets-api",
        "version": "0.1.0",
    }
    assert "database" not in response.json()
    assert response.headers["x-request-id"] == "test-request"


def test_health_details_are_available_outside_production() -> None:
    app = isolated_app()
    app.state.database_identity = "memory"
    with TestClient(app) as client:
        response = client.get("/health/details")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "memory"


def _deployed_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "environment": "staging",
        "public_api_url": "https://api.example.com",
        "test_auth_secret": None,
        "dev_bootstrap_test_users": False,
        "clerk_jwks_url": "https://clerk.example/.well-known/jwks.json",
        "clerk_issuer": "https://clerk.example",
        "database_url": None,
        "mcp_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_health_details_are_hidden_in_production(monkeypatch) -> None:
    settings = _deployed_settings(environment="production")
    monkeypatch.setattr("personal_markets.main.get_settings", lambda: settings)
    with TestClient(isolated_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health/details").status_code == 404
        assert "database" not in client.get("/health").json()


def test_health_details_hidden_when_https_public_url_even_if_development(monkeypatch) -> None:
    settings = _deployed_settings(environment="development")
    monkeypatch.setattr("personal_markets.main.get_settings", lambda: settings)
    with TestClient(isolated_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health/details").status_code == 404


def test_startup_refuses_bootstrap_and_test_auth_when_deployed() -> None:
    with pytest.raises(RuntimeError, match="PM_DEV_BOOTSTRAP_TEST_USERS"):
        _deployed_settings(dev_bootstrap_test_users=True).assert_safe_startup()
    with pytest.raises(RuntimeError, match="PM_TEST_AUTH_SECRET"):
        _deployed_settings(test_auth_secret="x" * 32).assert_safe_startup()
    with pytest.raises(RuntimeError, match="PM_CLERK_JWKS_URL"):
        _deployed_settings(clerk_jwks_url=None, clerk_issuer=None).assert_safe_startup()
    _deployed_settings().assert_safe_startup()


def test_empty_cors_origin_regex_is_disabled() -> None:
    settings = _deployed_settings(cors_origin_regex="  ")
    assert settings.cors_origin_regex is None


def test_local_loopback_https_is_not_treated_as_deployed() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        public_api_url="https://127.0.0.1:8000",
        test_auth_secret="local-secret-for-tests-only-32b!!",
        dev_bootstrap_test_users=True,
        clerk_jwks_url=None,
    )
    assert not settings.is_publicly_reachable()
    assert not settings.is_deployed()
    settings.assert_safe_startup()


PRODUCTION_WEB_ORIGIN = "https://buildnorth-delta.vercel.app"
PREVIEW_GIT_ORIGIN = (
    "https://buildnorth-git-ux-consumer-c0fb66-sujalthapa242-3741s-projects.vercel.app"
)
PREVIEW_UNIQUE_ORIGIN = (
    "https://buildnorth-9ajkuwxtx-sujalthapa242-3741s-projects.vercel.app"
)
LOCALHOST_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
ALLOWED_WEB_ORIGINS = (
    PRODUCTION_WEB_ORIGIN,
    PREVIEW_GIT_ORIGIN,
    PREVIEW_UNIQUE_ORIGIN,
    *LOCALHOST_ORIGINS,
)
ARBITRARY_ORIGIN = "https://evil.example"


def _production_cors_settings(**overrides: object) -> Settings:
    return _deployed_settings(
        environment="production",
        cors_origins=list(ALLOWED_WEB_ORIGINS),
        cors_origin_regex=r"^http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+):\d+$",
        clerk_authorized_parties=list(ALLOWED_WEB_ORIGINS),
        **overrides,
    )


def _preflight(client: TestClient, origin: str) -> Any:
    return client.options(
        "/api/v1/me",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_deployed_cors_allows_production_preview_and_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("personal_markets.main.get_settings", lambda: _production_cors_settings())
    with TestClient(isolated_app()) as client:
        for origin in ALLOWED_WEB_ORIGINS:
            response = _preflight(client, origin)
            assert response.status_code == 200, origin
            assert response.headers["access-control-allow-origin"] == origin
            assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_deployed_cors_rejects_arbitrary_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("personal_markets.main.get_settings", lambda: _production_cors_settings())
    with TestClient(isolated_app()) as client:
        response = _preflight(client, ARBITRARY_ORIGIN)
    assert response.status_code == 400
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}


def test_anonymous_me_is_401_and_still_allows_preview_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("personal_markets.main.get_settings", lambda: _production_cors_settings())
    app = isolated_app()
    app.state.auth_bypass_principal = None
    with TestClient(app) as client:
        response = client.get("/api/v1/me", headers={"Origin": PREVIEW_GIT_ORIGIN})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == PREVIEW_GIT_ORIGIN
    assert response.json()["error"]["type"] == "UnauthorizedError"


def test_development_cors_accepts_alternate_local_vite_port() -> None:
    with TestClient(isolated_app()) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://127.0.0.1:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


def test_unknown_goal_maps_domain_error() -> None:
    with TestClient(isolated_app()) as client:
        response = client.get("/api/v1/goals/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "ResourceNotFoundError"
