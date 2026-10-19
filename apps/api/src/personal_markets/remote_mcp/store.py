"""Persistence for remote MCP authorization, connections, idempotency and audit.

Bearer tokens, refresh tokens and authorization codes are stored only as SHA-256
digests. Raw values exist in memory for the single response that issues them.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.persistence.database import transaction

TokenKind = Literal["access", "refresh"]
SubmissionStatus = Literal["pending", "committed", "failed"]
# A pending claim older than this is treated as abandoned (for example the process
# died mid-commit) and may be retried with the same idempotency key.
STALE_PENDING = timedelta(minutes=5)
_CLIENT_SECRET_NAMESPACE = UUID("6f1d3c52-61a4-4d55-9d0b-1f2e7a3c9b10")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(UTC)


class ClientRecord(BaseModel):
    client_id: str
    info: dict[str, Any]
    client_secret: str | None = Field(default=None, repr=False)
    registration_ip_hash: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


class AuthorizationRequestRecord(BaseModel):
    id: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    scopes: list[str]
    code_challenge: str
    state: str | None = None
    resource: str | None = None
    expires_at: datetime
    decided_at: datetime | None = None
    decided_by: UUID | None = None
    decision: Literal["approved", "denied"] | None = None


class ConnectionRecord(BaseModel):
    id: UUID
    user_id: UUID
    client_id: str
    client_name: str | None = None
    scopes: list[str]
    resource: str
    created_at: datetime = Field(default_factory=now_utc)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class CodeRecord(BaseModel):
    code_hash: str
    client_id: str
    user_id: UUID
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    scopes: list[str]
    code_challenge: str
    resource: str
    expires_at: datetime
    consumed_at: datetime | None = None
    connection_id: UUID | None = None


class TokenRecord(BaseModel):
    token_hash: str
    kind: TokenKind
    connection_id: UUID
    client_id: str
    user_id: UUID
    scopes: list[str]
    resource: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)


class SubmissionRecord(BaseModel):
    user_id: UUID
    idempotency_key: str
    goal_id: UUID
    connection_id: UUID | None = None
    payload_hash: str
    status: SubmissionStatus = "pending"
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class AuditRecord(BaseModel):
    event: str
    outcome: str
    user_id: UUID | None = None
    connection_id: UUID | None = None
    client_id: str | None = None
    tool_name: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now_utc)


class RemoteMcpStore(Protocol):
    async def save_client(self, record: ClientRecord) -> None: ...
    async def get_client(self, client_id: str) -> ClientRecord | None: ...
    async def count_registrations(self, ip_hash: str, since: datetime) -> int: ...

    async def save_request(self, record: AuthorizationRequestRecord) -> None: ...
    async def get_request(self, request_id: str) -> AuthorizationRequestRecord | None: ...
    async def decide_request(
        self, request_id: str, user_id: UUID, decision: str, now: datetime
    ) -> AuthorizationRequestRecord | None: ...

    async def save_code(self, record: CodeRecord) -> None: ...
    async def get_code(self, code_hash: str) -> CodeRecord | None: ...
    async def consume_code(self, code_hash: str, connection_id: UUID, now: datetime) -> bool: ...

    async def create_connection(self, record: ConnectionRecord) -> None: ...
    async def get_connection(self, connection_id: UUID) -> ConnectionRecord | None: ...
    async def list_connections(self, user_id: UUID) -> list[ConnectionRecord]: ...
    async def revoke_connection(
        self, connection_id: UUID, user_id: UUID | None, now: datetime
    ) -> ConnectionRecord | None: ...
    async def touch_connection(self, connection_id: UUID, now: datetime) -> None: ...

    async def save_token(self, record: TokenRecord) -> None: ...
    async def get_token(self, token_hash: str) -> TokenRecord | None: ...
    async def revoke_token(self, token_hash: str, now: datetime) -> bool: ...

    async def claim_submission(self, record: SubmissionRecord) -> tuple[SubmissionRecord, bool]: ...
    async def finish_submission(
        self, user_id: UUID, key: str, status: SubmissionStatus, result: dict[str, Any]
    ) -> None: ...

    async def audit(self, record: AuditRecord) -> None: ...


class InMemoryRemoteMcpStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.clients: dict[str, ClientRecord] = {}
        self.requests: dict[str, AuthorizationRequestRecord] = {}
        self.codes: dict[str, CodeRecord] = {}
        self.connections: dict[UUID, ConnectionRecord] = {}
        self.tokens: dict[str, TokenRecord] = {}
        self.submissions: dict[tuple[UUID, str], SubmissionRecord] = {}
        self.audit_log: list[AuditRecord] = []

    async def save_client(self, record: ClientRecord) -> None:
        self.clients[record.client_id] = record

    async def get_client(self, client_id: str) -> ClientRecord | None:
        return self.clients.get(client_id)

    async def count_registrations(self, ip_hash: str, since: datetime) -> int:
        return sum(
            1
            for item in self.clients.values()
            if item.registration_ip_hash == ip_hash and item.created_at >= since
        )

    async def save_request(self, record: AuthorizationRequestRecord) -> None:
        self.requests[record.id] = record

    async def get_request(self, request_id: str) -> AuthorizationRequestRecord | None:
        return self.requests.get(request_id)

    async def decide_request(
        self, request_id: str, user_id: UUID, decision: str, now: datetime
    ) -> AuthorizationRequestRecord | None:
        async with self._lock:
            record = self.requests.get(request_id)
            if record is None or record.decided_at is not None or record.expires_at <= now:
                return None
            updated = record.model_copy(
                update={"decided_at": now, "decided_by": user_id, "decision": decision}
            )
            self.requests[request_id] = updated
            return updated

    async def save_code(self, record: CodeRecord) -> None:
        self.codes[record.code_hash] = record

    async def get_code(self, code_hash: str) -> CodeRecord | None:
        return self.codes.get(code_hash)

    async def consume_code(self, code_hash: str, connection_id: UUID, now: datetime) -> bool:
        async with self._lock:
            record = self.codes.get(code_hash)
            if record is None or record.consumed_at is not None:
                return False
            self.codes[code_hash] = record.model_copy(
                update={"consumed_at": now, "connection_id": connection_id}
            )
            return True

    async def create_connection(self, record: ConnectionRecord) -> None:
        self.connections[record.id] = record

    async def get_connection(self, connection_id: UUID) -> ConnectionRecord | None:
        return self.connections.get(connection_id)

    async def list_connections(self, user_id: UUID) -> list[ConnectionRecord]:
        rows = [item for item in self.connections.values() if item.user_id == user_id]
        return sorted(rows, key=lambda item: item.created_at, reverse=True)

    async def revoke_connection(
        self, connection_id: UUID, user_id: UUID | None, now: datetime
    ) -> ConnectionRecord | None:
        async with self._lock:
            record = self.connections.get(connection_id)
            if record is None or (user_id is not None and record.user_id != user_id):
                return None
            if record.revoked_at is None:
                record = record.model_copy(update={"revoked_at": now})
                self.connections[connection_id] = record
            for key, token in list(self.tokens.items()):
                if token.connection_id == connection_id and token.revoked_at is None:
                    self.tokens[key] = token.model_copy(update={"revoked_at": now})
            return record

    async def touch_connection(self, connection_id: UUID, now: datetime) -> None:
        record = self.connections.get(connection_id)
        if record is not None:
            self.connections[connection_id] = record.model_copy(update={"last_used_at": now})

    async def save_token(self, record: TokenRecord) -> None:
        self.tokens[record.token_hash] = record

    async def get_token(self, token_hash: str) -> TokenRecord | None:
        return self.tokens.get(token_hash)

    async def revoke_token(self, token_hash: str, now: datetime) -> bool:
        async with self._lock:
            record = self.tokens.get(token_hash)
            if record is None or record.revoked_at is not None:
                return False
            self.tokens[token_hash] = record.model_copy(update={"revoked_at": now})
            return True

    async def claim_submission(self, record: SubmissionRecord) -> tuple[SubmissionRecord, bool]:
        async with self._lock:
            key = (record.user_id, record.idempotency_key)
            existing = self.submissions.get(key)
            if existing is not None and not _reclaimable(existing, record.payload_hash):
                return existing, False
            self.submissions[key] = record
            return record, True

    async def finish_submission(
        self, user_id: UUID, key: str, status: SubmissionStatus, result: dict[str, Any]
    ) -> None:
        existing = self.submissions.get((user_id, key))
        if existing is not None:
            self.submissions[(user_id, key)] = existing.model_copy(
                update={"status": status, "result": result, "updated_at": now_utc()}
            )

    async def audit(self, record: AuditRecord) -> None:
        self.audit_log.append(record)


def _reclaimable(existing: SubmissionRecord, payload_hash: str) -> bool:
    if existing.payload_hash != payload_hash:
        return False
    if existing.status == "failed":
        return True
    return existing.status == "pending" and existing.updated_at < now_utc() - STALE_PENDING


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


class PostgresRemoteMcpStore:
    def __init__(self, engine: AsyncEngine, cipher: Any | None = None) -> None:
        self._engine = engine
        self._cipher = cipher

    def _secret_owner(self, client_id: str) -> UUID:
        return uuid5(_CLIENT_SECRET_NAMESPACE, client_id)

    async def save_client(self, record: ClientRecord) -> None:
        ciphertext = None
        if record.client_secret:
            if self._cipher is None:
                raise RuntimeError("client secret storage requires an encryption key")
            ciphertext = self._cipher.encrypt(
                self._secret_owner(record.client_id), "mcp_oauth_client", record.client_secret
            )
        info = record.info
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into remote_mcp_oauth_clients (
                  client_id, client_name, client_uri, redirect_uris, token_endpoint_auth_method,
                  client_secret_ciphertext, metadata_json, registration_ip_hash, created_at
                ) values (
                  :client_id, :client_name, :client_uri, cast(:redirect_uris as jsonb), :method,
                  :ciphertext, cast(:info as jsonb), :ip_hash, :created_at
                )
                """),
                {
                    "client_id": record.client_id,
                    "client_name": info.get("client_name"),
                    "client_uri": info.get("client_uri"),
                    "redirect_uris": _json(info.get("redirect_uris") or []),
                    "method": info.get("token_endpoint_auth_method") or "none",
                    "ciphertext": ciphertext,
                    "info": _json(info),
                    "ip_hash": record.registration_ip_hash,
                    "created_at": record.created_at,
                },
            )

    async def get_client(self, client_id: str) -> ClientRecord | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from remote_mcp_oauth_clients where client_id = :id"),
                        {"id": client_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        secret = None
        if row["client_secret_ciphertext"] and self._cipher is not None:
            secret = self._cipher.decrypt(
                self._secret_owner(client_id), "mcp_oauth_client", row["client_secret_ciphertext"]
            )
        return ClientRecord(
            client_id=row["client_id"],
            info=dict(row["metadata_json"] or {}),
            client_secret=secret,
            registration_ip_hash=row["registration_ip_hash"],
            created_at=row["created_at"],
        )

    async def count_registrations(self, ip_hash: str, since: datetime) -> int:
        async with self._engine.connect() as connection:
            value = await connection.scalar(
                text(
                    "select count(*) from remote_mcp_oauth_clients "
                    "where registration_ip_hash = :ip and created_at >= :since"
                ),
                {"ip": ip_hash, "since": since},
            )
        return int(value or 0)

    async def save_request(self, record: AuthorizationRequestRecord) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into remote_mcp_authorization_requests (
                  id, client_id, redirect_uri, redirect_uri_provided_explicitly, scopes,
                  code_challenge, state, resource, expires_at
                ) values (
                  :id, :client_id, :redirect_uri, :explicit, cast(:scopes as jsonb),
                  :challenge, :state, :resource, :expires_at
                )
                """),
                {
                    "id": record.id,
                    "client_id": record.client_id,
                    "redirect_uri": record.redirect_uri,
                    "explicit": record.redirect_uri_provided_explicitly,
                    "scopes": _json(record.scopes),
                    "challenge": record.code_challenge,
                    "state": record.state,
                    "resource": record.resource,
                    "expires_at": record.expires_at,
                },
            )

    @staticmethod
    def _request(row: Any) -> AuthorizationRequestRecord:
        return AuthorizationRequestRecord(
            id=row["id"],
            client_id=row["client_id"],
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=row["redirect_uri_provided_explicitly"],
            scopes=list(row["scopes"] or []),
            code_challenge=row["code_challenge"],
            state=row["state"],
            resource=row["resource"],
            expires_at=row["expires_at"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            decision=row["decision"],
        )

    async def get_request(self, request_id: str) -> AuthorizationRequestRecord | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from remote_mcp_authorization_requests where id = :id"),
                        {"id": request_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._request(row) if row else None

    async def decide_request(
        self, request_id: str, user_id: UUID, decision: str, now: datetime
    ) -> AuthorizationRequestRecord | None:
        async with transaction(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                    update remote_mcp_authorization_requests
                    set decided_at = :now, decided_by = :user_id, decision = :decision
                    where id = :id and decided_at is null and expires_at > :now
                    returning *
                    """),
                        {"id": request_id, "user_id": user_id, "decision": decision, "now": now},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._request(row) if row else None

    async def save_code(self, record: CodeRecord) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into remote_mcp_authorization_codes (
                  code_hash, client_id, user_id, redirect_uri, redirect_uri_provided_explicitly,
                  scopes, code_challenge, resource, expires_at
                ) values (
                  :code_hash, :client_id, :user_id, :redirect_uri, :explicit,
                  cast(:scopes as jsonb), :challenge, :resource, :expires_at
                )
                """),
                {
                    "code_hash": record.code_hash,
                    "client_id": record.client_id,
                    "user_id": record.user_id,
                    "redirect_uri": record.redirect_uri,
                    "explicit": record.redirect_uri_provided_explicitly,
                    "scopes": _json(record.scopes),
                    "challenge": record.code_challenge,
                    "resource": record.resource,
                    "expires_at": record.expires_at,
                },
            )

    async def get_code(self, code_hash: str) -> CodeRecord | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "select * from remote_mcp_authorization_codes where code_hash = :hash"
                        ),
                        {"hash": code_hash},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return CodeRecord(
            code_hash=row["code_hash"],
            client_id=row["client_id"],
            user_id=row["user_id"],
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=row["redirect_uri_provided_explicitly"],
            scopes=list(row["scopes"] or []),
            code_challenge=row["code_challenge"],
            resource=row["resource"],
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            connection_id=row["connection_id"],
        )

    async def consume_code(self, code_hash: str, connection_id: UUID, now: datetime) -> bool:
        async with transaction(self._engine) as connection:
            row = (
                await connection.execute(
                    text("""
                    update remote_mcp_authorization_codes
                    set consumed_at = :now, connection_id = :connection_id
                    where code_hash = :hash and consumed_at is null
                    returning code_hash
                    """),
                    {"hash": code_hash, "now": now, "connection_id": connection_id},
                )
            ).one_or_none()
        return row is not None

    async def create_connection(self, record: ConnectionRecord) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into remote_mcp_connections (
                  id, user_id, client_id, client_name, scopes, resource, created_at
                ) values (
                  :id, :user_id, :client_id, :client_name, cast(:scopes as jsonb), :resource,
                  :created_at
                )
                """),
                {
                    "id": record.id,
                    "user_id": record.user_id,
                    "client_id": record.client_id,
                    "client_name": record.client_name,
                    "scopes": _json(record.scopes),
                    "resource": record.resource,
                    "created_at": record.created_at,
                },
            )

    @staticmethod
    def _connection(row: Any) -> ConnectionRecord:
        return ConnectionRecord(
            id=row["id"],
            user_id=row["user_id"],
            client_id=row["client_id"],
            client_name=row["client_name"],
            scopes=list(row["scopes"] or []),
            resource=row["resource"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            revoked_at=row["revoked_at"],
        )

    async def get_connection(self, connection_id: UUID) -> ConnectionRecord | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from remote_mcp_connections where id = :id"),
                        {"id": connection_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._connection(row) if row else None

    async def list_connections(self, user_id: UUID) -> list[ConnectionRecord]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "select * from remote_mcp_connections where user_id = :user_id "
                        "order by created_at desc limit 100"
                    ),
                    {"user_id": user_id},
                )
            ).mappings()
            return [self._connection(row) for row in rows]

    async def revoke_connection(
        self, connection_id: UUID, user_id: UUID | None, now: datetime
    ) -> ConnectionRecord | None:
        async with transaction(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                    update remote_mcp_connections
                    set revoked_at = coalesce(revoked_at, :now)
                    where id = :id and (cast(:user_id as uuid) is null or user_id = :user_id)
                    returning *
                    """),
                        {"id": connection_id, "user_id": user_id, "now": now},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            await connection.execute(
                text(
                    "update remote_mcp_tokens set revoked_at = :now "
                    "where connection_id = :id and revoked_at is null"
                ),
                {"id": connection_id, "now": now},
            )
        return self._connection(row)

    async def touch_connection(self, connection_id: UUID, now: datetime) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("update remote_mcp_connections set last_used_at = :now where id = :id"),
                {"id": connection_id, "now": now},
            )

    async def save_token(self, record: TokenRecord) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into remote_mcp_tokens (
                  token_hash, kind, connection_id, client_id, user_id, scopes, resource,
                  expires_at, created_at
                ) values (
                  :hash, :kind, :connection_id, :client_id, :user_id, cast(:scopes as jsonb),
                  :resource, :expires_at, :created_at
                )
                """),
                {
                    "hash": record.token_hash,
                    "kind": record.kind,
                    "connection_id": record.connection_id,
                    "client_id": record.client_id,
                    "user_id": record.user_id,
                    "scopes": _json(record.scopes),
                    "resource": record.resource,
                    "expires_at": record.expires_at,
                    "created_at": record.created_at,
                },
            )

    async def get_token(self, token_hash: str) -> TokenRecord | None:
        async with self._engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text("select * from remote_mcp_tokens where token_hash = :hash"),
                        {"hash": token_hash},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return TokenRecord(
            token_hash=row["token_hash"],
            kind=row["kind"],
            connection_id=row["connection_id"],
            client_id=row["client_id"],
            user_id=row["user_id"],
            scopes=list(row["scopes"] or []),
            resource=row["resource"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
            created_at=row["created_at"],
        )

    async def revoke_token(self, token_hash: str, now: datetime) -> bool:
        async with transaction(self._engine) as connection:
            row = (
                await connection.execute(
                    text(
                        "update remote_mcp_tokens set revoked_at = :now "
                        "where token_hash = :hash and revoked_at is null returning token_hash"
                    ),
                    {"hash": token_hash, "now": now},
                )
            ).one_or_none()
        return row is not None

    @staticmethod
    def _submission(row: Any) -> SubmissionRecord:
        return SubmissionRecord(
            user_id=row["user_id"],
            idempotency_key=row["idempotency_key"],
            goal_id=row["goal_id"],
            connection_id=row["connection_id"],
            payload_hash=row["payload_hash"],
            status=row["status"],
            result=dict(row["result_json"] or {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def claim_submission(self, record: SubmissionRecord) -> tuple[SubmissionRecord, bool]:
        params = {
            "user_id": record.user_id,
            "key": record.idempotency_key,
            "goal_id": record.goal_id,
            "connection_id": record.connection_id,
            "payload_hash": record.payload_hash,
            "stale": now_utc() - STALE_PENDING,
        }
        async with transaction(self._engine) as connection:
            inserted = (
                (
                    await connection.execute(
                        text("""
                    insert into remote_mcp_evidence_submissions (
                      user_id, idempotency_key, goal_id, connection_id, payload_hash, status
                    ) values (
                      :user_id, :key, :goal_id, :connection_id, :payload_hash, 'pending'
                    )
                    on conflict (user_id, idempotency_key) do update
                      set status = 'pending', updated_at = now(), result_json = '{}'::jsonb
                      where remote_mcp_evidence_submissions.payload_hash = excluded.payload_hash
                        and (
                          remote_mcp_evidence_submissions.status = 'failed'
                          or (
                            remote_mcp_evidence_submissions.status = 'pending'
                            and remote_mcp_evidence_submissions.updated_at < :stale
                          )
                        )
                    returning *
                    """),
                        params,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if inserted is not None:
                return self._submission(inserted), True
            existing = (
                (
                    await connection.execute(
                        text(
                            "select * from remote_mcp_evidence_submissions "
                            "where user_id = :user_id and idempotency_key = :key"
                        ),
                        params,
                    )
                )
                .mappings()
                .one()
            )
        return self._submission(existing), False

    async def finish_submission(
        self, user_id: UUID, key: str, status: SubmissionStatus, result: dict[str, Any]
    ) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                update remote_mcp_evidence_submissions
                set status = :status, result_json = cast(:result as jsonb), updated_at = now()
                where user_id = :user_id and idempotency_key = :key
                """),
                {"user_id": user_id, "key": key, "status": status, "result": _json(result)},
            )

    async def audit(self, record: AuditRecord) -> None:
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("""
                insert into remote_mcp_audit_log (
                  user_id, connection_id, client_id, event, tool_name, outcome, detail_json,
                  created_at
                ) values (
                  :user_id, :connection_id, :client_id, :event, :tool_name, :outcome,
                  cast(:detail as jsonb), :created_at
                )
                """),
                {
                    "user_id": record.user_id,
                    "connection_id": record.connection_id,
                    "client_id": record.client_id,
                    "event": record.event,
                    "tool_name": record.tool_name,
                    "outcome": record.outcome,
                    "detail": _json(record.detail),
                    "created_at": record.created_at,
                },
            )
