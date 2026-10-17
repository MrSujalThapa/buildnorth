from fastapi.testclient import TestClient

from helpers import isolated_app


def test_health_endpoint_and_backend_boot() -> None:
    with TestClient(isolated_app()) as client:
        response = client.get("/health", headers={"x-request-id": "test-request"})
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "personal-markets-api",
        "version": "0.1.0",
    }
    assert response.headers["x-request-id"] == "test-request"


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
