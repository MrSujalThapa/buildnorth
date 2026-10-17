from fastapi.testclient import TestClient

from helpers import isolated_app
from personal_markets.core.config import get_settings


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


def test_health_details_are_hidden_in_production(monkeypatch) -> None:
    monkeypatch.setenv("PM_ENVIRONMENT", "production")
    get_settings.cache_clear()
    try:
        with TestClient(isolated_app()) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/health/details").status_code == 404
            assert "database" not in client.get("/health").json()
    finally:
        get_settings.cache_clear()


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
