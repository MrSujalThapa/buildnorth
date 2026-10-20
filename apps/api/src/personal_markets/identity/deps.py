from typing import Annotated
import time
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Request

from personal_markets.core.config import get_settings
from personal_markets.core.errors import ForbiddenError, UnauthorizedError
from personal_markets.core.request_context import resolved_client_ip
from personal_markets.identity.domain import Principal
from personal_markets.identity.factory import get_identity_service
from personal_markets.identity.service import IdentityService, require_invited
from personal_markets.identity.tokens import verify_bearer_token


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def get_principal(
    request: Request,
    identity: Annotated[IdentityService, Depends(get_identity_service)],
) -> Principal:
    settings = get_settings()
    token = _bearer_token(request)
    if token:
        started = time.perf_counter()
        claims = verify_bearer_token(token, settings)
        verified_ms = round((time.perf_counter() - started) * 1000)
        principal = await identity.principal_from_claims(claims)
        structlog.get_logger(__name__).info(
            "identity_timing", verified_ms=verified_ms,
            principal_ms=round((time.perf_counter() - started) * 1000) - verified_ms,
        )
        return principal
    bypass = getattr(request.app.state, "auth_bypass_principal", None)
    if bypass is not None and settings.environment in {"test", "pytest"}:
        return bypass
    raise UnauthorizedError("authentication required")


async def get_invited_principal(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    return require_invited(principal)


async def get_admin_principal(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    if principal.role != "admin":
        raise ForbiddenError("admin access is required")
    return principal


def client_ip(request: Request) -> str | None:
    return resolved_client_ip(request)


def as_user_id(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
