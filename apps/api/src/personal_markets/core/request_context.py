from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import Request, Response

from personal_markets.core.config import Settings
from personal_markets.persistence.query_stats import track_queries

client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "testclient", "localhost"})


def peer_host(request: Request) -> str | None:
    """TCP peer. Never read X-Forwarded-For here."""
    return request.client.host if request.client else None


def resolved_client_ip(request: Request, settings: Settings | None = None) -> str | None:
    """Client identity for rate limits.

    X-Forwarded-For is used only when trust_forwarded_headers is on and the
    immediate peer is in trusted_proxies. Otherwise the TCP peer is used.
    """
    peer = peer_host(request)
    current = settings
    if current is None:
        from personal_markets.core.config import get_settings

        current = get_settings()
    if not current.trust_forwarded_headers:
        return peer
    trusted = {item.strip() for item in current.trusted_proxies if item.strip()}
    if peer not in trusted:
        return peer
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or peer
    return peer


def health_details_allowed(request: Request, settings: Settings) -> bool:
    """Local loopback diagnostics only. Forwarded headers cannot open this."""
    if settings.is_publicly_reachable() or not settings.is_local_environment():
        return False
    return (peer_host(request) or "") in LOOPBACK_HOSTS


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    client_ip = resolved_client_ip(request)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    token = client_ip_var.set(client_ip)
    started = perf_counter()
    with track_queries() as db:
        try:
            response = await call_next(request)
        except Exception:
            if request.url.path.startswith("/api/v1/"):
                structlog.get_logger(__name__).error(
                    "api_request_timing",
                    method=request.method,
                    path=request.url.path,
                    status=500,
                    duration_ms=round((perf_counter() - started) * 1000),
                    db_queries=db.queries,
                    db_checkouts=db.checkouts,
                    db_ms=round(db.query_ms),
                    db_connection_ms=round(db.connection_ms),
                )
            raise
        finally:
            client_ip_var.reset(token)
    if request.url.path.startswith("/api/v1/"):
        structlog.get_logger(__name__).info(
            "api_request_timing",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000),
            db_queries=db.queries,
            db_checkouts=db.checkouts,
            db_ms=round(db.query_ms),
            db_connection_ms=round(db.connection_ms),
        )
        response.headers["server-timing"] = db.server_timing()
    response.headers["x-request-id"] = request_id
    return response
