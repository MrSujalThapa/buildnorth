from fastapi.testclient import TestClient

from helpers import isolated_app


def test_api_request_timing_keeps_correlation_id(monkeypatch) -> None:
    events = []

    class Logger:
        def info(self, event, **fields):
            if event == "api_request_timing":
                events.append(fields)

        def warning(self, *_args, **_fields):
            pass

        def error(self, *_args, **_fields):
            pass

    monkeypatch.setattr(
        "personal_markets.core.request_context.structlog.get_logger",
        lambda *_args: Logger(),
    )
    with TestClient(isolated_app()) as client:
        response = client.get("/api/v1/me", headers={"x-request-id": "timing-test"})
    assert response.headers["x-request-id"] == "timing-test"
    assert events == [
        {
            "method": "GET", "path": "/api/v1/me",
            "status": response.status_code,
            "duration_ms": events[0]["duration_ms"],
            "db_queries": 0,
            "db_checkouts": 0,
            "db_ms": 0,
            "db_connection_ms": 0,
        }
    ]
    assert events[0]["duration_ms"] >= 0
    assert response.headers["server-timing"] == (
        'db;dur=0.0;desc="0 queries, 0 checkouts", db-acquire;dur=0.0'
    )
