"""OAuth 2.1 authorization server for remote MCP clients.

PlayItOut is the authorization server for its own MCP resource. The MCP SDK's
maintained handlers implement the protocol (metadata, PKCE S256 verification, dynamic
registration, token and revocation endpoints); this module supplies storage, consent and
policy. The resource owner is authenticated by the existing Clerk session on the consent
page, so a Clerk session JWT is never itself accepted as an MCP access token.
"""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import structlog
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl, BaseModel

from personal_markets.core.config import Settings
from personal_markets.core.errors import (
    ForbiddenError,
    ProviderNotConfiguredError,
    ResourceNotFoundError,
)
from personal_markets.core.request_context import client_ip_var
from personal_markets.identity.domain import Principal
from personal_markets.remote_mcp.scopes import ALL_SCOPES, SCOPE_INFO, normalize_scopes
from personal_markets.remote_mcp.store import (
    AuditRecord,
    AuthorizationRequestRecord,
    ClientRecord,
    CodeRecord,
    ConnectionRecord,
    RemoteMcpStore,
    TokenKind,
    TokenRecord,
    digest,
    now_utc,
)

ACCESS_PREFIX = "pio_at_"
REFRESH_PREFIX = "pio_rt_"
# ChatGPT and Grok register several HTTPS callbacks via DCR. Still reject
# non-https (except loopback) URIs one-by-one; this only raises the count cap.
_MAX_REDIRECT_URIS = 16
_TOUCH_INTERVAL = timedelta(seconds=60)
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_FORBIDDEN_SCHEMES = {"javascript", "data", "file", "vbscript", "about", "blob"}
# Native-app callbacks observed from Cursor/Grok Bot DCR. Still reject
# javascript/data/file and non-loopback http.
_NATIVE_APP_SCHEMES = {"cursor"}

log = structlog.get_logger("personal_markets.remote_mcp")

UserLookup = Callable[[UUID], Awaitable[Principal | None]]


def _has_access(principal: Principal | None) -> bool:
    return principal is not None and (principal.invited or principal.role == "admin")


def validate_redirect_uri(uri: str) -> None:
    """https anywhere, http only on loopback, or a reverse-DNS private scheme (RFC 8252)."""
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if parts.fragment:
        raise RegistrationError("invalid_redirect_uri", "redirect URIs must not contain fragments")
    if scheme == "https" and parts.hostname:
        return
    if scheme == "http":
        host = (parts.hostname or "").lower()
        if host in _LOOPBACK_HOSTS:
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise RegistrationError("invalid_redirect_uri", "http redirect URIs must be loopback")
    if scheme and scheme not in _FORBIDDEN_SCHEMES and "." in scheme:
        return
    if (
        scheme in _NATIVE_APP_SCHEMES
        and scheme not in _FORBIDDEN_SCHEMES
        and (parts.netloc or parts.path.strip("/"))
    ):
        return
    raise RegistrationError(
        "invalid_redirect_uri", f"redirect URI scheme {scheme!r} is not allowed"
    )


class ScopeView(BaseModel):
    scope: str
    label: str
    description: str
    writes: bool
    spends_credits: bool


class AuthorizationRequestView(BaseModel):
    request_id: str
    client_id: str
    client_name: str
    client_uri: str | None
    redirect_host: str
    redirect_scheme: str
    scopes: list[ScopeView]
    resource: str
    expires_at: datetime
    verified_client: bool
    warnings: list[str]


class ConnectionView(BaseModel):
    connection_id: UUID
    client_id: str
    client_name: str
    scopes: list[ScopeView]
    status: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


def scope_views(scopes: list[str]) -> list[ScopeView]:
    views = []
    for scope in scopes:
        info = SCOPE_INFO.get(scope)
        if info is None:
            continue
        views.append(
            ScopeView(
                scope=info.scope,
                label=info.label,
                description=info.description,
                writes=info.writes,
                spends_credits=info.spends_credits,
            )
        )
    return views


class RemoteMcpAuthorization:
    """Implements the SDK's OAuthAuthorizationServerProvider protocol plus consent."""

    def __init__(self, store: RemoteMcpStore, settings: Settings, users: UserLookup) -> None:
        self._store = store
        self._settings = settings
        self._users = users

    @property
    def issuer(self) -> str:
        return self._settings.public_api_url.rstrip("/")

    @property
    def resource(self) -> str:
        return f"{self.issuer}/mcp"

    async def _audit(self, event: str, outcome: str, **fields: Any) -> None:
        try:
            await self._store.audit(AuditRecord(event=event, outcome=outcome, **fields))
        except Exception:  # audit must never break authorization
            log.warning("mcp_audit_failed", event_name=event)

    # --- client registration -------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        record = await self._store.get_client(client_id)
        if record is None:
            return None
        return OAuthClientInformationFull.model_validate(
            {**record.info, "client_secret": record.client_secret}
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(item) for item in client_info.redirect_uris or []]
        if not uris or len(uris) > _MAX_REDIRECT_URIS:
            raise RegistrationError(
                "invalid_redirect_uri", f"register between 1 and {_MAX_REDIRECT_URIS} redirect URIs"
            )
        for uri in uris:
            validate_redirect_uri(uri)
        if client_info.client_name and len(client_info.client_name) > 120:
            raise RegistrationError("invalid_client_metadata", "client_name is too long")
        ip_hash = digest(client_ip_var.get() or "unknown")
        since = now_utc() - timedelta(hours=1)
        if await self._store.count_registrations(ip_hash, since) >= (
            self._settings.mcp_registrations_per_ip_hour
        ):
            await self._audit("client.registered", "rate_limited")
            raise RegistrationError("invalid_client_metadata", "registration rate limit exceeded")
        info = client_info.model_dump(mode="json", exclude={"client_secret"}, exclude_none=True)
        try:
            await self._store.save_client(
                ClientRecord(
                    client_id=str(client_info.client_id),
                    info=info,
                    client_secret=client_info.client_secret,
                    registration_ip_hash=ip_hash,
                )
            )
        except (RuntimeError, ProviderNotConfiguredError):
            raise RegistrationError(
                "invalid_client_metadata",
                "confidential clients are not supported here; register with "
                "token_endpoint_auth_method=none and use PKCE",
            ) from None
        await self._audit("client.registered", "ok", client_id=str(client_info.client_id))

    # --- authorization ----------------------------------------------------------

    def _same_resource(self, resource: str | None) -> bool:
        if resource is None:
            return True
        return resource.rstrip("/") == self.resource.rstrip("/")

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if not self._same_resource(params.resource):
            raise AuthorizeError("invalid_target", "resource must be this MCP server")
        requested = params.scopes
        unknown = [scope for scope in requested or [] if scope not in ALL_SCOPES]
        if unknown:
            raise AuthorizeError("invalid_scope", f"unknown scope: {unknown[0]}")
        scopes = normalize_scopes(requested)
        if not scopes:
            raise AuthorizeError("invalid_scope", "no supported scope was requested")
        request_id = secrets.token_urlsafe(24)
        await self._store.save_request(
            AuthorizationRequestRecord(
                id=request_id,
                client_id=str(client.client_id),
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                scopes=scopes,
                code_challenge=params.code_challenge,
                state=params.state,
                resource=params.resource or self.resource,
                expires_at=now_utc()
                + timedelta(seconds=self._settings.mcp_authorization_request_ttl_seconds),
            )
        )
        await self._audit("oauth.authorize_requested", "pending", client_id=str(client.client_id))
        base = self._settings.public_web_url.rstrip("/")
        return f"{base}/connect/authorize?request={request_id}"

    async def describe_request(
        self, request_id: str, principal: Principal
    ) -> AuthorizationRequestView:
        if not _has_access(principal):
            raise ForbiddenError("an invitation is required to connect agents")
        record = await self._pending(request_id)
        client = await self._store.get_client(record.client_id)
        info = client.info if client else {}
        redirect = urlsplit(record.redirect_uri)
        warnings = [
            "This client registered itself automatically. PlayItOut has not verified who "
            "operates it.",
            f"After you approve, access is sent to {redirect.scheme}://{redirect.netloc or ''}"
            f"{redirect.path}. Only continue if you started this connection.",
        ]
        if any(SCOPE_INFO[scope].spends_credits for scope in record.scopes if scope in SCOPE_INFO):
            warnings.append("This client is asking to spend your model credits.")
        return AuthorizationRequestView(
            request_id=record.id,
            client_id=record.client_id,
            client_name=str(info.get("client_name") or "Unnamed client"),
            client_uri=info.get("client_uri"),
            redirect_host=redirect.netloc or redirect.scheme,
            redirect_scheme=redirect.scheme,
            scopes=scope_views(record.scopes),
            resource=record.resource or self.resource,
            expires_at=record.expires_at,
            verified_client=False,
            warnings=warnings,
        )

    async def _pending(self, request_id: str) -> AuthorizationRequestRecord:
        record = await self._store.get_request(request_id)
        if record is None or record.decided_at is not None or record.expires_at <= now_utc():
            raise ResourceNotFoundError("This connection request has expired or was already used")
        return record

    async def decide(
        self,
        request_id: str,
        principal: Principal,
        *,
        approve: bool,
        scopes: list[str] | None = None,
    ) -> str:
        if not _has_access(principal):
            raise ForbiddenError("an invitation is required to connect agents")
        pending = await self._pending(request_id)
        granted = pending.scopes if scopes is None else [s for s in pending.scopes if s in scopes]
        if approve and not granted:
            raise ForbiddenError("Select at least one permission to approve")
        decided = await self._store.decide_request(
            request_id, principal.user_id, "approved" if approve else "denied", now_utc()
        )
        if decided is None:
            raise ResourceNotFoundError("This connection request has expired or was already used")
        if not approve:
            await self._audit(
                "oauth.consent", "denied", user_id=principal.user_id, client_id=decided.client_id
            )
            return construct_redirect_uri(
                decided.redirect_uri, error="access_denied", state=decided.state
            )
        code = secrets.token_urlsafe(32)
        await self._store.save_code(
            CodeRecord(
                code_hash=digest(code),
                client_id=decided.client_id,
                user_id=principal.user_id,
                redirect_uri=decided.redirect_uri,
                redirect_uri_provided_explicitly=decided.redirect_uri_provided_explicitly,
                scopes=granted,
                code_challenge=decided.code_challenge,
                resource=decided.resource or self.resource,
                expires_at=now_utc() + timedelta(seconds=self._settings.mcp_auth_code_ttl_seconds),
            )
        )
        await self._audit(
            "oauth.consent",
            "approved",
            user_id=principal.user_id,
            client_id=decided.client_id,
            detail={"scopes": granted},
        )
        return construct_redirect_uri(decided.redirect_uri, code=code, state=decided.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        record = await self._store.get_code(digest(authorization_code))
        if record is None or record.client_id != client.client_id:
            return None
        if record.consumed_at is not None:
            # A replayed code means it leaked. Revoke whatever it already produced.
            if record.connection_id is not None:
                await self._store.revoke_connection(record.connection_id, None, now_utc())
            await self._audit(
                "oauth.code_replay", "revoked", user_id=record.user_id, client_id=record.client_id
            )
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=record.scopes,
            expires_at=record.expires_at.timestamp(),
            client_id=record.client_id,
            code_challenge=record.code_challenge,
            redirect_uri=AnyUrl(record.redirect_uri),
            redirect_uri_provided_explicitly=record.redirect_uri_provided_explicitly,
            resource=record.resource,
            subject=str(record.user_id),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        user_id = UUID(str(authorization_code.subject))
        if not _has_access(await self._users(user_id)):
            raise TokenError("invalid_grant", "the account no longer has access")
        connection = ConnectionRecord(
            id=uuid4(),
            user_id=user_id,
            client_id=str(client.client_id),
            client_name=client.client_name,
            scopes=list(authorization_code.scopes),
            resource=authorization_code.resource or self.resource,
        )
        await self._store.create_connection(connection)
        if not await self._store.consume_code(
            digest(authorization_code.code), connection.id, now_utc()
        ):
            await self._store.revoke_connection(connection.id, None, now_utc())
            raise TokenError("invalid_grant", "authorization code was already used")
        tokens = await self._issue(connection, list(authorization_code.scopes))
        await self._audit(
            "oauth.token_issued",
            "ok",
            user_id=user_id,
            connection_id=connection.id,
            client_id=connection.client_id,
        )
        return tokens

    async def _issue(self, connection: ConnectionRecord, scopes: list[str]) -> OAuthToken:
        access = ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
        now = now_utc()
        issued: tuple[tuple[str, TokenKind, int], ...] = (
            (access, "access", self._settings.mcp_access_token_ttl_seconds),
            (refresh, "refresh", self._settings.mcp_refresh_token_ttl_seconds),
        )
        for token, kind, ttl in issued:
            await self._store.save_token(
                TokenRecord(
                    token_hash=digest(token),
                    kind=kind,
                    expires_at=now + timedelta(seconds=ttl),
                    connection_id=connection.id,
                    client_id=connection.client_id,
                    user_id=connection.user_id,
                    scopes=scopes,
                    resource=connection.resource,
                )
            )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self._settings.mcp_access_token_ttl_seconds,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    # --- refresh and revocation ------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        if not refresh_token.startswith(REFRESH_PREFIX):
            return None
        record = await self._store.get_token(digest(refresh_token))
        if record is None or record.kind != "refresh" or record.client_id != client.client_id:
            return None
        if record.revoked_at is not None:
            # Rotated refresh tokens are single use; reuse indicates theft.
            await self._store.revoke_connection(record.connection_id, None, now_utc())
            await self._audit(
                "oauth.refresh_reuse",
                "revoked",
                user_id=record.user_id,
                connection_id=record.connection_id,
            )
            return None
        connection = await self._store.get_connection(record.connection_id)
        if connection is None or connection.revoked_at is not None:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=record.client_id,
            scopes=record.scopes,
            expires_at=int(record.expires_at.timestamp()),
            resource=record.resource,
            subject=str(record.user_id),
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        record = await self._store.get_token(digest(refresh_token.token))
        if record is None:
            raise TokenError("invalid_grant", "refresh token does not exist")
        if not _has_access(await self._users(record.user_id)):
            raise TokenError("invalid_grant", "the account no longer has access")
        if not await self._store.revoke_token(record.token_hash, now_utc()):
            raise TokenError("invalid_grant", "refresh token was already used")
        connection = await self._store.get_connection(record.connection_id)
        if connection is None or connection.revoked_at is not None:
            raise TokenError("invalid_grant", "connection was revoked")
        return await self._issue(connection, scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        if not token.startswith(ACCESS_PREFIX):
            return None
        record = await self._store.get_token(digest(token))
        now = now_utc()
        if (
            record is None
            or record.kind != "access"
            or record.revoked_at is not None
            or record.expires_at <= now
        ):
            return None
        connection = await self._store.get_connection(record.connection_id)
        if connection is None or connection.revoked_at is not None:
            return None
        if not _has_access(await self._users(record.user_id)):
            return None
        if connection.last_used_at is None or now - connection.last_used_at > _TOUCH_INTERVAL:
            await self._store.touch_connection(connection.id, now)
        return AccessToken(
            token=token,
            client_id=record.client_id,
            scopes=record.scopes,
            expires_at=int(record.expires_at.timestamp()),
            resource=record.resource,
            subject=str(record.user_id),
            claims={"connection_id": str(record.connection_id), "iss": self.issuer},
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.load_access_token(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        record = await self._store.get_token(digest(token.token))
        if record is None:
            return
        if record.kind == "refresh":
            await self._store.revoke_connection(record.connection_id, None, now_utc())
        else:
            await self._store.revoke_token(record.token_hash, now_utc())
        await self._audit(
            "oauth.revoked",
            record.kind,
            user_id=record.user_id,
            connection_id=record.connection_id,
        )

    async def exchange_identity_assertion(self, client: Any, params: Any) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "identity assertions are not supported")

    # --- connection management (Settings) ---------------------------------------

    async def list_connections(self, principal: Principal) -> list[ConnectionView]:
        rows = await self._store.list_connections(principal.user_id)
        return [
            ConnectionView(
                connection_id=row.id,
                client_id=row.client_id,
                client_name=row.client_name or "Unnamed client",
                scopes=scope_views(row.scopes),
                status="revoked" if row.revoked_at else "active",
                created_at=row.created_at,
                last_used_at=row.last_used_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]

    async def revoke_connection(self, principal: Principal, connection_id: UUID) -> ConnectionView:
        row = await self._store.revoke_connection(connection_id, principal.user_id, now_utc())
        if row is None:
            raise ResourceNotFoundError("connection was not found")
        await self._audit(
            "connection.revoked", "ok", user_id=principal.user_id, connection_id=connection_id
        )
        return ConnectionView(
            connection_id=row.id,
            client_id=row.client_id,
            client_name=row.client_name or "Unnamed client",
            scopes=scope_views(row.scopes),
            status="revoked",
            created_at=row.created_at,
            last_used_at=row.last_used_at,
            revoked_at=row.revoked_at,
        )
