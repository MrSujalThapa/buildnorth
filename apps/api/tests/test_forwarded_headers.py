from fastapi.testclient import TestClient
from starlette.requests import Request

from helpers import isolated_app
from personal_markets.core.config import Settings
from personal_markets.core.request_context import health_details_allowed, resolved_client_ip


def _request(*, peer: str, forwarded: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": (peer, 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_forwarded_for_ignored_unless_trusted_proxy() -> None:
    untrusted = Settings(_env_file=None, trust_forwarded_headers=False)
    trusted = Settings(
        _env_file=None,
        trust_forwarded_headers=True,
        trusted_proxies=["127.0.0.1"],
    )
    spoofed = _request(peer="203.0.113.9", forwarded="198.51.100.1")
    proxied = _request(peer="127.0.0.1", forwarded="198.51.100.1")
    assert resolved_client_ip(spoofed, untrusted) == "203.0.113.9"
    assert resolved_client_ip(spoofed, trusted) == "203.0.113.9"
    assert resolved_client_ip(proxied, trusted) == "198.51.100.1"
    assert resolved_client_ip(proxied, untrusted) == "127.0.0.1"


def test_spoofed_forwarded_for_cannot_open_health_details() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        public_api_url="http://127.0.0.1:8000",
    )
    public_peer = _request(peer="203.0.113.9", forwarded="127.0.0.1")
    assert health_details_allowed(public_peer, settings) is False
    loopback = _request(peer="127.0.0.1")
    assert health_details_allowed(loopback, settings) is True


def test_http_spoofed_forwarded_for_does_not_change_health_details() -> None:
    app = isolated_app()
    app.state.database_identity = "memory"
    with TestClient(app) as client:
        ok = client.get("/health/details")
        spoofed = client.get("/health/details", headers={"X-Forwarded-For": "8.8.8.8"})
    assert ok.status_code == 200
    assert spoofed.status_code == 200
