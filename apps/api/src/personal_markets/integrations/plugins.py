from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field


class PluginStatus(StrEnum):
    CONNECTED = "connected"
    NOT_CONNECTED = "not_connected"
    PENDING_AUTH = "pending_auth"
    SYNCING = "syncing"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class ReadCapability(BaseModel):
    id: str
    label: str
    operation: str


class PluginDefinition(BaseModel):
    id: str
    name: str
    description: str
    category: str
    provider_type: str
    logo_url: str | None = None
    capabilities: list[ReadCapability] = Field(default_factory=list)
    used_for: list[str] = Field(default_factory=list)


class PluginConnection(BaseModel):
    plugin_id: str
    status: PluginStatus
    connected_at: str | None = None
    last_sync_at: str | None = None
    permissions: list[str] = Field(default_factory=list)
    account_metadata: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class PluginView(BaseModel):
    definition: PluginDefinition
    connection: PluginConnection


class IntegrationGateway(Protocol):
    async def discover_plugins(self) -> list[PluginDefinition]: ...

    async def connection_status(self, plugin_id: str) -> PluginConnection: ...

    async def discover_read_capabilities(self, plugin_id: str) -> list[ReadCapability]: ...


class ReadCapabilityPolicy:
    """Project-owned enforcement; provider read-only metadata is never trusted alone."""

    _allowed_operations = frozenset(
        {
            "github.events.public.read",
            "gmail.messages.selected.read",
            "calendar.events.selected.read",
            "drive.files.selected.read",
            "strava.activities.read",
            "notion.pages.selected.read",
            "slack.channels.selected.read",
            "sheets.spreadsheets.selected.read",
            "figma.files.selected.read",
        }
    )

    def require_allowed(self, capability: ReadCapability) -> None:
        if capability.operation not in self._allowed_operations:
            raise ValueError(
                f"write or unknown integration capability denied: {capability.operation}"
            )


def _definition(
    plugin_id: str,
    name: str,
    description: str,
    operation: str,
    reads: list[str],
    used_for: list[str],
) -> PluginDefinition:
    return PluginDefinition(
        id=plugin_id,
        name=name,
        description=description,
        category="evidence",
        provider_type="direct" if plugin_id == "github" else "future_gateway",
        capabilities=[
            ReadCapability(id=f"{plugin_id}-read", label=label, operation=operation)
            for label in reads
        ],
        used_for=used_for,
    )


PLUGIN_DEFINITIONS = [
    _definition(
        "manual",
        "Manual",
        "Add evidence by hand from the goal workspace",
        "manual.evidence.write",
        ["Manual observations"],
        ["All goals", "Quick updates"],
    ),
    _definition(
        "csv",
        "CSV Import",
        "Import structured metrics from spreadsheets",
        "csv.import.selected.read",
        ["Selected CSV uploads"],
        ["Finance goals", "Running goals", "Habit tracking"],
    ),
    _definition(
        "github",
        "GitHub",
        "Commits, PRs, issues and engineering activity",
        "github.events.public.read",
        ["Public activity"],
        ["Career goals", "Startup goals", "Project progress"],
    ),
    _definition(
        "gmail",
        "Gmail",
        "Applications, interviews and recruiter messages",
        "gmail.messages.selected.read",
        ["Selected recruiter mail"],
        ["Career goals", "Application progress"],
    ),
    _definition(
        "calendar",
        "Google Calendar",
        "Interviews, habits and scheduled activity",
        "calendar.events.selected.read",
        ["Selected events"],
        ["Career goals", "Habit goals"],
    ),
    _definition(
        "drive",
        "Google Drive",
        "Selected files and documents",
        "drive.files.selected.read",
        ["Selected files"],
        ["Project progress"],
    ),
    _definition(
        "strava",
        "Strava",
        "Runs, workouts and training history",
        "strava.activities.read",
        ["Training activity"],
        ["Fitness goals"],
    ),
    _definition(
        "notion",
        "Notion",
        "Goals, notes and project activity",
        "notion.pages.selected.read",
        ["Selected pages"],
        ["Project progress"],
    ),
    _definition(
        "slack",
        "Slack",
        "Work and team activity",
        "slack.channels.selected.read",
        ["Selected channels"],
        ["Work goals"],
    ),
    _definition(
        "sheets",
        "Google Sheets",
        "Trackers, logs and structured metrics",
        "sheets.spreadsheets.selected.read",
        ["Selected spreadsheets"],
        ["Financial goals", "Habit goals"],
    ),
    _definition(
        "figma",
        "Figma",
        "Design and prototype activity",
        "figma.files.selected.read",
        ["Selected files"],
        ["Project progress", "Portfolio goals"],
    ),
]


class DirectIntegrationGateway:
    def __init__(self, policy: ReadCapabilityPolicy | None = None) -> None:
        self._policy = policy or ReadCapabilityPolicy()
        self._definitions = {item.id: item for item in PLUGIN_DEFINITIONS}

    async def discover_plugins(self) -> list[PluginDefinition]:
        return list(self._definitions.values())

    async def connection_status(self, plugin_id: str) -> PluginConnection:
        if plugin_id not in self._definitions:
            raise KeyError(plugin_id)
        # GitHub public sync exists today, but it is goal-scoped and does not create
        # a durable OAuth connection. Report that honestly as not connected.
        status = PluginStatus.NOT_CONNECTED if plugin_id == "github" else PluginStatus.UNAVAILABLE
        return PluginConnection(plugin_id=plugin_id, status=status)

    async def discover_read_capabilities(self, plugin_id: str) -> list[ReadCapability]:
        definition = self._definitions[plugin_id]
        for capability in definition.capabilities:
            self._policy.require_allowed(capability)
        return definition.capabilities

    async def views(self) -> list[PluginView]:
        return [
            PluginView(definition=item, connection=await self.connection_status(item.id))
            for item in await self.discover_plugins()
        ]
