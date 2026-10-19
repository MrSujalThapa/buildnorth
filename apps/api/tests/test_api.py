import pytest
from fastapi.testclient import TestClient

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
