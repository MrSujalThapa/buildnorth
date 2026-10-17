from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ConnectionType(StrEnum):
    MANAGED_GATEWAY = "managed_gateway"
    CUSTOM_MCP = "custom_mcp"


class PluginAvailability(StrEnum):
    AVAILABLE = "available"
    CONNECTED = "connected"
    SOON = "soon"
    UNSUPPORTED = "unsupported"


class MCPConnectionRecord(BaseModel):
    id: UUID
    plugin_connection_id: UUID
    server_label: str
    endpoint: str | None = None
    transport: str
    auth_ref: str | None = None
    status: str
    created_at: datetime
    last_verified_at: datetime | None = None


class PluginConnectionRecord(BaseModel):
    id: UUID
    user_id: UUID
    plugin_id: str
    connection_type: ConnectionType
    gateway_provider: str | None = None
    transport: str = "stdio"
    auth_ref: str | None = None
    status: str
    account_metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    last_verified_at: datetime | None = None
    last_sync_at: datetime | None = None


class ReadCapabilityRecord(BaseModel):
    id: UUID
    plugin_connection_id: UUID
    capability_id: str
    label: str
    operation: str
    tool_name: str | None = None
    resource_uri: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


class SyncRecipeStep(BaseModel):
    capability_id: str
    tool_name: str | None = None
    resource_uri: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


class SyncRecipeRecord(BaseModel):
    id: UUID
    plugin_connection_id: UUID
    recipe_version: int
    steps: list[SyncRecipeStep]


class SyncCursorRecord(BaseModel):
    plugin_connection_id: UUID
    capability_id: str
    cursor_value: str | None = None
    updated_at: datetime


class SyncRunRecord(BaseModel):
    id: UUID
    plugin_connection_id: UUID
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    records_read: int = 0
    records_new: int = 0
    error: str | None = None


class RawSourceRecord(BaseModel):
    id: UUID
    plugin_connection_id: UUID
    external_id: str
    tool_identity: str
    retrieved_at: datetime
    payload: dict[str, Any]
    payload_hash: str
    sync_run_id: UUID
    cursor_context: dict[str, Any] = Field(default_factory=dict)


class GoalSyncRecipeRecord(BaseModel):
    goal_id: UUID
    plugin_connection_id: UUID
    plugin_id: str
    label: str
    steps: list[SyncRecipeStep]
    approved: bool = False
    schema_version: int = 1
    provenance: dict[str, Any] = Field(default_factory=dict)
    status: str = "approved"
    last_successful_sync_at: datetime | None = None
    user_approved_at: datetime | None = None


class MCPToolDescriptor(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    read_only_hint: bool | None = None


class MCPResourceDescriptor(BaseModel):
    uri: str
    name: str
    description: str = ""
    mime_type: str | None = None
    resource_type: str = "resource"
    metadata: dict[str, Any] = Field(default_factory=dict)
