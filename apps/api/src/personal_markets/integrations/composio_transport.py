from __future__ import annotations

from typing import Any
from uuid import UUID

from personal_markets.core.config import Settings
from personal_markets.integrations.composio_gateway import ComposioIntegrationGateway
from personal_markets.integrations.mcp_domain import MCPResourceDescriptor, MCPToolDescriptor
from personal_markets.integrations.mcp_transport import MockMCPTransport


class ComposioTransport:
    """MCPTransport backed by Composio tool discovery and execution."""

    def __init__(
        self,
        settings: Settings,
        *,
        plugin_id: str,
        user_id: UUID,
        connected_account_id: str | None,
    ) -> None:
        self._settings = settings
        self._plugin_id = plugin_id
        self._user_id = user_id
        self._connected_account_id = connected_account_id
        self._gateway = ComposioIntegrationGateway(settings)
        self._fallback = MockMCPTransport(plugin_id)

    async def list_tools(self) -> list[MCPToolDescriptor]:
        if not self._gateway.available:
            return await self._fallback.list_tools()
        return await self._gateway.list_tools(self._user_id, self._plugin_id, limit=500)

    async def list_resources(self) -> list[MCPResourceDescriptor]:
        if not self._gateway.available:
            return await self._fallback.list_resources()
        return await self._gateway.list_resources(
            self._user_id,
            self._plugin_id,
            connected_account_id=self._connected_account_id,
        )

    async def list_descendants(self, parent_id: str) -> list[str]:
        from personal_markets.integrations.provider_contract import get_adapter

        if not get_adapter(self._plugin_id).supports_parent_watch or not self._gateway.available:
            return []
        return await self._gateway.list_notion_child_pages(
            self._user_id,
            parent_id,
            connected_account_id=self._connected_account_id,
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._gateway.available:
            return await self._fallback.call_tool(name, arguments)
        payload = await self._gateway.execute_tool(
            self._user_id,
            name,
            arguments,
            connected_account_id=self._connected_account_id,
        )
        records = (
            payload.get("records")
            or payload.get("items")
            or payload.get("data")
            or payload.get("commits")
            or payload.get("repositories")
            or []
        )
        return {"records": records, "raw": payload}

    async def read_resource(self, uri: str) -> dict[str, Any]:
        if not self._gateway.available:
            return await self._fallback.read_resource(uri)
        return {"uri": uri, "records": []}
