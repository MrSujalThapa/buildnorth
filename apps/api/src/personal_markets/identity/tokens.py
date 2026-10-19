from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

from personal_markets.core.config import Settings
from personal_markets.core.errors import UnauthorizedError
from personal_markets.identity.domain import user_id_for_clerk

_EMAIL_CLAIM_KEYS = (
    "email",
    "primary_email",
    "primary_email_address",
    "email_address",
)


class TokenClaims(dict[str, Any]):
    @property
    def clerk_user_id(self) -> str:
        return str(self["sub"])

    @property
    def email(self) -> str | None:
        for key in _EMAIL_CLAIM_KEYS:
            value = self.get(key)
            if value:
                return str(value)
        user = self.get("user")
        if isinstance(user, dict):
            for key in _EMAIL_CLAIM_KEYS:
                value = user.get(key)
                if value:
                    return str(value)
        return None

    @property
    def email_verified(self) -> bool:
        if self.get("email_verified") or self.get("email_verified_at"):
            return True
        user = self.get("user")
        if isinstance(user, dict):
            return bool(user.get("email_verified") or user.get("primary_email_address_verified"))
        return False


def issue_test_token(
    *,
    secret: str,
    clerk_user_id: str,
    email: str | None = None,
    email_verified: bool = True,
    ttl_seconds: int = 3600,
    extra: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": clerk_user_id,
        "email": email,
        "email_verified": email_verified,
        "iss": "playitout-test",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "user_id": str(user_id_for_clerk(clerk_user_id)),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_bearer_token(token: str, settings: Settings) -> TokenClaims:
    if not token:
        raise UnauthorizedError("missing bearer token")
    if settings.test_auth_secret and not settings.is_deployed():
        try:
            payload = jwt.decode(
                token,
                settings.test_auth_secret,
                algorithms=["HS256"],
                options={"require": ["sub", "exp"]},
            )
            return TokenClaims(payload)
        except jwt.ExpiredSignatureError as error:
            raise UnauthorizedError("token expired") from error
        except jwt.InvalidTokenError:
            jwks_configured = bool(settings.resolved_clerk_jwks_url())
            if settings.environment in {"test", "pytest"} and not jwks_configured:
                raise UnauthorizedError("invalid token") from None
    return _verify_clerk_token(token, settings)


def authorized_origins(settings: Settings) -> list[str]:
    origins = [
        item.strip().rstrip("/")
        for item in settings.clerk_authorized_parties
        if item.strip()
    ]
    expanded: list[str] = []
    for origin in origins:
        expanded.append(origin)
        if "://localhost" in origin:
            expanded.append(origin.replace("://localhost", "://127.0.0.1", 1))
        if "://127.0.0.1" in origin:
            expanded.append(origin.replace("://127.0.0.1", "://localhost", 1))
    return list(dict.fromkeys(expanded))


def _verify_clerk_token(token: str, settings: Settings) -> TokenClaims:
    jwks_url = settings.resolved_clerk_jwks_url()
    if not jwks_url:
        raise UnauthorizedError("authentication is not configured")
    try:
        client = jwt.PyJWKClient(jwks_url)
        signing_key = client.get_signing_key_from_jwt(token)
        decode_kwargs: dict[str, Any] = {
            "algorithms": ["RS256"],
            "options": {"require": ["sub", "exp"], "verify_aud": False},
            "leeway": 5,
        }
        issuer = (settings.clerk_issuer or "").strip().rstrip("/")
        if issuer:
            decode_kwargs["issuer"] = issuer
        # Signature, algorithm, issuer, and expiration are verified here.
        # Do not pass authorized parties as JWT `aud`; Clerk puts the origin in `azp`.
        payload = jwt.decode(token, signing_key.key, **decode_kwargs)
    except jwt.ExpiredSignatureError as error:
        raise UnauthorizedError("token expired") from error
    except jwt.InvalidTokenError as error:
        raise UnauthorizedError("invalid token") from error
    origins = authorized_origins(settings)
    azp = str(payload.get("azp") or "").rstrip("/")
    if origins and azp and azp not in origins:
        raise UnauthorizedError("token azp is not allowed")
    return TokenClaims(payload)


def parse_user_id(value: str) -> UUID:
    return UUID(value)
