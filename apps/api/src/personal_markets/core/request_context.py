from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

import structlog
from fastapi import Request, Response

client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    forwarded = request.headers.get("x-forwarded-for")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else None
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    token = client_ip_var.set(client_ip)
    try:
        response = await call_next(request)
    finally:
        client_ip_var.reset(token)
    response.headers["x-request-id"] = request_id
    return response
