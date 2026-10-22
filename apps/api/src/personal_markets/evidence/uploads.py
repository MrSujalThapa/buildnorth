"""Owner-scoped upload ingestion. Blobs live with the tenant's durable store."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from personal_markets.core.errors import (
    ForbiddenError,
    ResourceNotFoundError,
    SemanticProviderError,
)
from personal_markets.evidence.parsers import (
    ALLOWED_EXTENSIONS,
    ParseError,
    parse_upload,
    rows_from_table,
)
from personal_markets.persistence.database import autocommit_connection, transaction
from personal_markets.ports import EvidenceEventProposal

MAX_UPLOAD_BYTES = 5_000_000
MAX_OWNER_UPLOAD_BYTES = 50_000_000
POSTGRES_STORAGE = "postgres://goal_uploads"


@dataclass
class UploadRecord:
    upload_id: UUID
    owner_id: UUID
    goal_id: UUID
    filename: str
    content_type: str
    byte_size: int
    sha256: str
    status: str
    preview: dict[str, Any]
    mapping: dict[str, str] | None
    created_at: str
    lineage: dict[str, Any]
    deleted_at: str | None = None


class UploadBackend(Protocol):
    async def insert(self, record: UploadRecord, content: bytes) -> UploadRecord: ...
    async def get(self, owner: UUID, upload_id: UUID) -> UploadRecord: ...
    async def list_for_goal(self, owner: UUID, goal_id: UUID) -> list[UploadRecord]: ...
    async def find_hash(self, owner: UUID, goal_id: UUID, digest: str) -> UploadRecord | None: ...
    async def update(self, record: UploadRecord) -> UploadRecord: ...
    async def load_blob(self, owner: UUID, record: UploadRecord) -> bytes: ...
    async def owner_bytes(self, owner: UUID) -> int: ...
    async def delete(self, owner: UUID, upload_id: UUID) -> None: ...


class UploadStore:
    """In-memory backend for tests. Not durable across process restart."""

    def __init__(self) -> None:
        self._rows: dict[UUID, UploadRecord] = {}
        self._blobs: dict[UUID, bytes] = {}

    async def insert(self, record: UploadRecord, content: bytes) -> UploadRecord:
        stored = replace(
            record, lineage={**record.lineage, "storage_path": f"memory://{record.upload_id}"}
        )
        self._rows[stored.upload_id] = stored
        self._blobs[stored.upload_id] = content
        return stored

    async def get(self, owner: UUID, upload_id: UUID) -> UploadRecord:
        record = self._rows.get(upload_id)
        if record is None or record.owner_id != owner or record.deleted_at:
            raise ResourceNotFoundError("Upload was not found")
        return record

    async def list_for_goal(self, owner: UUID, goal_id: UUID) -> list[UploadRecord]:
        return [
            row
            for row in self._rows.values()
            if row.owner_id == owner and row.goal_id == goal_id and not row.deleted_at
        ]

    async def find_hash(self, owner: UUID, goal_id: UUID, digest: str) -> UploadRecord | None:
        for row in self._rows.values():
            if (
                row.owner_id == owner
                and row.goal_id == goal_id
                and row.sha256 == digest
                and not row.deleted_at
            ):
                return row
        return None

    async def update(self, record: UploadRecord) -> UploadRecord:
        self._rows[record.upload_id] = record
        return record

    async def load_blob(self, owner: UUID, record: UploadRecord) -> bytes:
        if record.owner_id != owner or record.deleted_at:
            raise ForbiddenError("Upload does not belong to this user")
        blob = self._blobs.get(record.upload_id)
        if blob is None:
            raise ResourceNotFoundError("Upload was not found")
        return blob

    async def owner_bytes(self, owner: UUID) -> int:
        return sum(
            row.byte_size
            for row in self._rows.values()
            if row.owner_id == owner and not row.deleted_at
        )

    async def delete(self, owner: UUID, upload_id: UUID) -> None:
        record = await self.get(owner, upload_id)
        record.deleted_at = datetime.now(UTC).isoformat()
        record.status = "deleted"
        self._blobs.pop(record.upload_id, None)
        self._rows[record.upload_id] = record


class PostgresUploadStore:
    """Durable owner-scoped blobs in Postgres. Survives API restart."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def insert(self, record: UploadRecord, content: bytes) -> UploadRecord:
        lineage = {
            **record.lineage,
            "storage_path": f"{POSTGRES_STORAGE}/{record.upload_id}",
        }
        stored = replace(record, lineage=lineage)
        async with transaction(self._engine) as connection:
            await connection.execute(
                text("select pg_advisory_xact_lock(hashtextextended(:lock, 0))"),
                {"lock": f"upload:{stored.owner_id}:{stored.goal_id}:{stored.sha256}"},
            )
            existing = await self._find_hash(
                connection, stored.owner_id, stored.goal_id, stored.sha256
            )
            if existing is not None:
                return existing
            await connection.execute(
                text("""
                insert into goal_uploads (
                  id, user_id, goal_id, filename, content_type, byte_size, sha256,
                  storage_path, status, preview_json, mapping_json, lineage_json,
                  created_at, content, deleted_at
                ) values (
                  :id, :user_id, :goal_id, :filename, :content_type, :byte_size, :sha256,
                  :storage_path, :status, cast(:preview as jsonb), cast(:mapping as jsonb),
                  cast(:lineage as jsonb), :created_at, :content, null
                )
                """),
                self._params(stored, content),
            )
        return stored

    async def get(self, owner: UUID, upload_id: UUID) -> UploadRecord:
        async with autocommit_connection(self._engine) as connection:
            row = (
                (
                    await connection.execute(
                        text("""
                        select * from goal_uploads
                        where id=:id and user_id=:owner and deleted_at is null
                        """),
                        {"id": upload_id, "owner": owner},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ResourceNotFoundError("Upload was not found")
        return self._to_record(dict(row))

    async def list_for_goal(self, owner: UUID, goal_id: UUID) -> list[UploadRecord]:
        async with autocommit_connection(self._engine) as connection:
            rows = (
                await connection.execute(
                    text("""
                    select * from goal_uploads
                    where user_id=:owner and goal_id=:goal_id and deleted_at is null
                    order by created_at
                    """),
                    {"owner": owner, "goal_id": goal_id},
                )
            ).mappings()
        return [self._to_record(dict(row)) for row in rows]

    async def find_hash(self, owner: UUID, goal_id: UUID, digest: str) -> UploadRecord | None:
        async with autocommit_connection(self._engine) as connection:
            return await self._find_hash(connection, owner, goal_id, digest)

    async def _find_hash(
        self, connection: Any, owner: UUID, goal_id: UUID, digest: str
    ) -> UploadRecord | None:
        row = (
            (
                await connection.execute(
                    text("""
                    select * from goal_uploads
                    where user_id=:owner and goal_id=:goal_id and sha256=:digest
                      and deleted_at is null
                    limit 1
                    """),
                    {"owner": owner, "goal_id": goal_id, "digest": digest},
                )
            )
            .mappings()
            .one_or_none()
        )
        return self._to_record(dict(row)) if row else None

    async def update(self, record: UploadRecord) -> UploadRecord:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text("""
                update goal_uploads
                set status=:status,
                    mapping_json=cast(:mapping as jsonb),
                    lineage_json=cast(:lineage as jsonb)
                where id=:id and user_id=:owner and deleted_at is null
                """),
                {
                    "status": record.status,
                    "mapping": json.dumps(record.mapping) if record.mapping else None,
                    "lineage": json.dumps(record.lineage, default=str),
                    "id": record.upload_id,
                    "owner": record.owner_id,
                },
            )
            if result.rowcount == 0:
                raise ResourceNotFoundError("Upload was not found")
        return record

    async def load_blob(self, owner: UUID, record: UploadRecord) -> bytes:
        if record.owner_id != owner:
            raise ForbiddenError("Upload does not belong to this user")
        async with autocommit_connection(self._engine) as connection:
            value = await connection.scalar(
                text("""
                select content from goal_uploads
                where id=:id and user_id=:owner and deleted_at is null
                """),
                {"id": record.upload_id, "owner": owner},
            )
        if value is None:
            raise ResourceNotFoundError("Upload was not found")
        return bytes(value)

    async def owner_bytes(self, owner: UUID) -> int:
        async with autocommit_connection(self._engine) as connection:
            value = await connection.scalar(
                text("""
                select coalesce(sum(byte_size), 0) from goal_uploads
                where user_id=:owner and deleted_at is null
                """),
                {"owner": owner},
            )
        return int(value or 0)

    async def delete(self, owner: UUID, upload_id: UUID) -> None:
        async with transaction(self._engine) as connection:
            result = await connection.execute(
                text("""
                update goal_uploads
                set deleted_at=now(), status='deleted', content=null, byte_size=0
                where id=:id and user_id=:owner and deleted_at is null
                """),
                {"id": upload_id, "owner": owner},
            )
            if result.rowcount == 0:
                raise ResourceNotFoundError("Upload was not found")

    def _params(self, record: UploadRecord, content: bytes) -> dict[str, Any]:
        created = datetime.fromisoformat(record.created_at)
        return {
            "id": record.upload_id,
            "user_id": record.owner_id,
            "goal_id": record.goal_id,
            "filename": record.filename,
            "content_type": record.content_type,
            "byte_size": record.byte_size,
            "sha256": record.sha256,
            "storage_path": record.lineage.get("storage_path")
            or f"{POSTGRES_STORAGE}/{record.upload_id}",
            "status": record.status,
            "preview": json.dumps(record.preview, default=str),
            "mapping": json.dumps(record.mapping) if record.mapping else None,
            "lineage": json.dumps(record.lineage, default=str),
            "created_at": created,
            "content": content,
        }

    def _to_record(self, row: dict[str, Any]) -> UploadRecord:
        created = row["created_at"]
        deleted = row.get("deleted_at")
        return UploadRecord(
            upload_id=row["id"],
            owner_id=row["user_id"],
            goal_id=row["goal_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            byte_size=int(row["byte_size"]),
            sha256=row["sha256"],
            status=row["status"],
            preview=row.get("preview_json") or {},
            mapping=row.get("mapping_json"),
            created_at=created.isoformat() if hasattr(created, "isoformat") else str(created),
            lineage=row.get("lineage_json") or {},
            deleted_at=deleted.isoformat()
            if deleted is not None and hasattr(deleted, "isoformat")
            else deleted,
        )


class UploadService:
    def __init__(
        self,
        store: UploadBackend,
        *,
        max_file_bytes: int = MAX_UPLOAD_BYTES,
        max_owner_bytes: int = MAX_OWNER_UPLOAD_BYTES,
    ) -> None:
        self._store = store
        self._max_file_bytes = max_file_bytes
        self._max_owner_bytes = max_owner_bytes
        self._locks: dict[tuple[UUID, UUID, str], asyncio.Lock] = {}

    def _lock(self, owner: UUID, goal: UUID, digest: str) -> asyncio.Lock:
        key = (owner, goal, digest)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def ingest(
        self,
        owner_id: UUID,
        goal_id: UUID,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> UploadRecord:
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise SemanticProviderError("Unsupported file type")
        if len(content) > self._max_file_bytes:
            raise SemanticProviderError("File exceeds the 5 MB upload limit")
        if len(content) == 0:
            raise SemanticProviderError("File is empty")
        digest = hashlib.sha256(content).hexdigest()
        async with self._lock(owner_id, goal_id, digest):
            existing = await self._store.find_hash(owner_id, goal_id, digest)
            if existing is not None:
                return existing
            used = await self._store.owner_bytes(owner_id)
            if used + len(content) > self._max_owner_bytes:
                raise SemanticProviderError("Account upload quota would be exceeded")
            try:
                preview = parse_upload(filename, content)
            except ParseError as error:
                raise SemanticProviderError(str(error)) from error
            record = UploadRecord(
                upload_id=uuid4(),
                owner_id=owner_id,
                goal_id=goal_id,
                filename=Path(filename).name,
                content_type=content_type or "application/octet-stream",
                byte_size=len(content),
                sha256=digest,
                status="extracted",
                preview=preview,
                mapping=None,
                created_at=datetime.now(UTC).isoformat(),
                lineage={
                    "source": "user_upload",
                    "filename": Path(filename).name,
                    "sha256": digest,
                    "untrusted_content": True,
                },
            )
            return await self._store.insert(record, content)

    async def list_for_goal(self, owner_id: UUID, goal_id: UUID) -> list[UploadRecord]:
        return await self._store.list_for_goal(owner_id, goal_id)

    async def get(self, owner_id: UUID, upload_id: UUID) -> UploadRecord:
        return await self._store.get(owner_id, upload_id)

    async def delete(self, owner_id: UUID, upload_id: UUID) -> None:
        await self._store.delete(owner_id, upload_id)

    async def approve_mapping(
        self, owner_id: UUID, upload_id: UUID, mapping: dict[str, str]
    ) -> tuple[UploadRecord, list[EvidenceEventProposal]]:
        record = await self._store.get(owner_id, upload_id)
        if record.preview.get("kind") not in {"csv", "xlsx"}:
            raise SemanticProviderError("Only CSV and Excel tables can be mapped into measurements")
        content = await self._store.load_blob(owner_id, record)
        try:
            rows = rows_from_table(content, record.filename, mapping)
        except ParseError as error:
            raise SemanticProviderError(str(error)) from error
        events = [EvidenceEventProposal.model_validate(row) for row in rows]
        record.mapping = mapping
        record.status = "mapped"
        record.lineage = {
            **record.lineage,
            "mapping": mapping,
            "row_count": len(events),
        }
        await self._store.update(record)
        return record, events
