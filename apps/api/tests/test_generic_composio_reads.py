"""An unregistered toolkit follows the same approved source path as known apps."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from personal_markets.agents.source_planner_service import SourcePlannerService
from personal_markets.core.config import Settings
from personal_markets.core.errors import IntegrationProviderError
from personal_markets.integrations.composio_gateway import ComposioIntegrationGateway
from personal_markets.integrations.generic_reads import (
    arguments_for_selection,
    discovery_tool,
    goal_read_tools,
)
from personal_markets.integrations.goal_sync_service import GoalSyncService
from personal_markets.integrations.mcp_domain import (
    ConnectionType,
    MCPToolDescriptor,
    PluginConnectionRecord,
)
from personal_markets.integrations.mcp_repository import InMemoryIntegrationRepository
from personal_markets.integrations.mcp_service import IntegrationGatewayService


@pytest.mark.parametrize(
    ("provider", "listing", "reader", "field", "row"),
    [
        (
            "gmail",
            "GMAIL_LIST_LABELS",
            "GMAIL_GET_MESSAGE",
            "message_id",
            {"id": "mail-1", "subject": "Interview", "date": "2026-10-24"},
        ),
        (
            "googlecalendar",
            "GOOGLECALENDAR_LIST_CALENDARS",
            "GOOGLECALENDAR_LIST_EVENTS",
            "calendarId",
            {"id": "event-1", "summary": "Training", "start": {"dateTime": "2026-10-24T09:00:00Z"}},
        ),
        (
            "strava",
            "STRAVA_LIST_ACTIVITIES",
            "STRAVA_GET_ACTIVITY",
            "activity_id",
            {"id": "run-1", "name": "Morning run", "distance_meters": 5000, "status": "completed"},
        ),
        (
            "slack",
            "SLACK_LIST_CHANNELS",
            "SLACK_GET_CHANNEL_MESSAGES",
            "channel",
            {"id": "post-1", "text": "Project update", "timestamp": "2026-10-24"},
        ),
        (
            "googlesheets",
            "GOOGLESHEETS_LIST_SPREADSHEETS",
            "GOOGLESHEETS_GET_SPREADSHEET",
            "spreadsheet_id",
            {"id": "sheet-1", "title": "Progress"},
        ),
        (
            "new_provider_xyz",
            "NEW_PROVIDER_XYZ_LIST_RESOURCES",
            "NEW_PROVIDER_XYZ_GET_RESOURCE",
            "resource_id",
            {"id": "item-1", "title": "Progress entry"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_unknown_provider_connects_selects_reads_deduplicates_and_reuses_recipe(
    provider: str,
    listing: str,
    reader: str,
    field: str,
    row: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, connection_id = uuid4(), uuid4()
    repository = InMemoryIntegrationRepository()
    connection = PluginConnectionRecord(
        id=connection_id,
        user_id=owner,
        plugin_id=provider,
        connection_type=ConnectionType.MANAGED_GATEWAY,
        gateway_provider="composio",
        status="connected",
        created_at=datetime.now(UTC),
        account_metadata={"connected_account_id": "ca-1"},
    )
    await repository.upsert_connection(connection)
    extras = {"range": "A1:C20"} if provider == "googlesheets" else {}
    tools = [
        MCPToolDescriptor(
            name=listing,
            description="List available resources",
            input_schema={"type": "object", "properties": {"limit": {"type": "integer"}}},
        ),
        MCPToolDescriptor(
            name=reader,
            description="Read selected record",
            input_schema={
                "type": "object",
                "properties": {field: {"type": "string"}, **({"range": {"type": "string"}} if extras else {})},
                "required": [field, *extras],
            },
        ),
        MCPToolDescriptor(
            name=f"{provider.upper()}_DELETE_RECORD",
            description="Delete a record",
            read_only_hint=False,
        ),
    ]
    discovered = discovery_tool(provider, tools)
    assert discovered is not None and discovered.name == listing
    assert [tool.name for tool in goal_read_tools(provider, tools)] == [reader]
    assert arguments_for_selection(tools[1], "chosen-1", extras) == {field: "chosen-1", **extras}

    class Transport:
        calls: list[tuple[str, dict[str, Any]]] = []

        async def list_tools(self) -> list[MCPToolDescriptor]:
            return tools

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            self.calls.append((name, arguments))
            assert name == reader and arguments[field] == "chosen-1"
            if extras:
                assert arguments["range"] == "A1:C20"
            return {"raw": {"items": [row]}}

    transport = Transport()
    gateway = IntegrationGatewayService(
        repository=repository,
        settings=Settings(environment="test"),
        default_user_id=owner,
    )
    monkeypatch.setattr(gateway, "_transport_for", lambda _connection: transport)
    await gateway._discover_and_persist(connection)
    capabilities = await repository.list_capabilities(connection_id)
    assert reader in {cap.tool_name for cap in capabilities}
    assert listing in {cap.tool_name for cap in capabilities}
    assert f"{provider.upper()}_DELETE_RECORD" not in {cap.tool_name for cap in capabilities}
    assert await repository.get_recipe(connection_id) is None
    assert (await gateway.sync(provider, user_id=owner))["status"] == "noop"

    goal_id = uuid4()
    planner = SourcePlannerService(
        Settings(environment="test"),
        cast(Any, SimpleNamespace()),
        cast(
            Any,
            SimpleNamespace(
                get_goal_by_string=AsyncMock(return_value=SimpleNamespace(goal_id=goal_id))
            ),
        ),
        cast(Any, SimpleNamespace()),
        cast(Any, SimpleNamespace()),
        SimpleNamespace(),
        repository,
        owner,
    )
    saved = await planner.save_recipe(
        str(goal_id),
        provider,
        label="Chosen resource",
        resource_ids=["chosen-1"],
        activity_types=[reader],
        read_arguments=extras,
    )
    assert saved.approved and saved.provenance["connected_account_id"] == "ca-1"
    assert (await repository.list_goal_recipes(goal_id))[0].steps == saved.steps
    steps = saved.steps
    assert len(steps) == 1 and steps[0].arguments[field] == "chosen-1"
    workflow = SimpleNamespace(start=AsyncMock(return_value=SimpleNamespace(status="unchanged")))
    goal_sync = GoalSyncService(
        settings=Settings(environment="test"),
        gateway=gateway,
        repository=repository,
        goals=planner._goals,
        workflow=workflow,
        evidence=SimpleNamespace(),
        owner_id=owner,
    )
    assert (await goal_sync.sync_goal_sources(str(goal_id))).status == "unchanged"
    sent = workflow.start.await_args.args[0]
    assert len(sent.mcp_records) == 1
    second = await gateway.sync(provider, user_id=owner, steps=steps)
    assert len(repository.raw_records) == 1 and second["records_new"] == 0
    assert len(transport.calls) == 2
    event = repository.raw_records[0].payload["events"][0]
    assert event["validation_status"] == "unverified"
    assert event["provenance"]["promotes_to_verified_outcome"] is False
    if provider == "strava":
        assert event["metric"] == "distance" and event["unit"] == "m"
    if provider == "googlecalendar":
        assert event["metric"] is None and event["event_type"] == "scheduled_event"
    tools[1] = tools[1].model_copy(update={"read_only_hint": False})
    with pytest.raises(ValueError, match="permission changed"):
        await gateway.sync(provider, user_id=owner, steps=steps)
    assert len(transport.calls) == 2


def test_unsafe_and_ambiguous_tools_are_not_selected() -> None:
    tools = [
        MCPToolDescriptor(name="UNKNOWN_DELETE_ITEMS", read_only_hint=False),
        MCPToolDescriptor(
            name="UNKNOWN_GET_AND_DELETE_RECORD",
            input_schema={
                "type": "object",
                "properties": {"resource_id": {"type": "string"}},
                "required": ["resource_id"],
            },
        ),
        MCPToolDescriptor(
            name="UNKNOWN_LIST_ALL", input_schema={"type": "object", "properties": {}}
        ),
        MCPToolDescriptor(
            name="UNKNOWN_GET_ITEM",
            input_schema={
                "type": "object",
                "properties": {"project_id": {"type": "string"}, "item_id": {"type": "string"}},
                "required": ["project_id", "item_id"],
            },
        ),
    ]
    assert goal_read_tools("unknown", tools) == []


@pytest.mark.asyncio
async def test_unknown_provider_discovers_bounded_resources_without_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = uuid4()
    gateway = ComposioIntegrationGateway(Settings(environment="test"))
    tool = MCPToolDescriptor(
        name="NEW_PROVIDER_XYZ_LIST_RESOURCES",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "maximum": 10},
                "cursor": {"type": "string"},
            },
        },
    )
    calls: list[dict[str, Any]] = []

    async def tools(*_args: Any, **_kwargs: Any) -> list[MCPToolDescriptor]:
        return [tool]

    async def execute(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        arguments = _args[2]
        calls.append(arguments)
        if "cursor" in arguments:
            return {"items": [{"id": "b", "name": "Second"}]}
        return {"items": [{"id": "a", "name": "First"}], "next_cursor": "next"}

    monkeypatch.setattr(gateway, "list_tools", tools)
    monkeypatch.setattr(gateway, "execute_tool", execute)
    resources = await gateway.list_resources(owner, "new_provider_xyz", connected_account_id="ca-1")
    assert [item.name for item in resources] == ["First", "Second"]
    assert calls == [{"limit": 10}, {"limit": 10, "cursor": "next"}]
    assert all(item.metadata["connected_account_id"] == "ca-1" for item in resources)

    async def no_tools(*_args: Any, **_kwargs: Any) -> list[MCPToolDescriptor]:
        return [MCPToolDescriptor(name="NEW_PROVIDER_XYZ_DELETE_ALL")]

    monkeypatch.setattr(gateway, "list_tools", no_tools)
    with pytest.raises(IntegrationProviderError, match="no supported resource discovery"):
        await gateway.list_resources(owner, "new_provider_xyz", connected_account_id="ca-1")
