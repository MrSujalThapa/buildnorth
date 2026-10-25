from typing import Any

from personal_markets.integrations.mcp_service import IntegrationGatewayService
from personal_markets.integrations.plugins import DirectIntegrationGateway, PluginView


class UnifiedIntegrationGateway:
    """Combines static plugin catalog with generic MCP connection lifecycle."""

    def __init__(
        self,
        catalog: DirectIntegrationGateway | None = None,
        mcp: IntegrationGatewayService | None = None,
        user_id=None,
    ) -> None:
        self._catalog = catalog or DirectIntegrationGateway()
        self._mcp = mcp or IntegrationGatewayService()
        self._user_id = user_id

    async def views(self) -> list[PluginView]:
        return await self._mcp.views(self._user_id)

    async def connected_views(self) -> list[PluginView]:
        return await self._mcp.connected_views(self._user_id)

    async def search_catalog(
        self,
        *,
        search: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
        browse: bool = False,
        reconcile: bool = False,
    ) -> dict[str, object]:
        return await self._mcp.search_catalog(
            search=search,
            cursor=cursor,
            limit=limit,
            browse=browse,
            user_id=self._user_id,
            reconcile=reconcile,
        )

    async def connect_managed(self, plugin_id: str, gateway_provider: str = "composio") -> dict[str, object]:
        return await self._mcp.connect_managed(
            plugin_id, user_id=self._user_id, gateway_provider=gateway_provider
        )

    async def refresh_connection(self, plugin_id: str) -> dict[str, object]:
        return await self._mcp.refresh_connection(plugin_id, user_id=self._user_id)

    async def list_capabilities(self, plugin_id: str) -> list[dict[str, object]]:
        return await self._mcp.list_capabilities(plugin_id, user_id=self._user_id)

    async def list_resources(self, plugin_id: str) -> list[dict[str, object]]:
        return await self._mcp.list_resources(plugin_id, user_id=self._user_id)

    async def preview_source(
        self,
        plugin_id: str,
        *,
        resource_id: str,
        resource_title: str = "",
        resource_type: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        return await self._mcp.preview_source(
            plugin_id,
            resource_id=resource_id,
            resource_title=resource_title,
            resource_type=resource_type,
            arguments=arguments,
            user_id=self._user_id,
        )

    async def list_descendants(self, plugin_id: str, parent_id: str) -> list[str]:
        return await self._mcp.list_descendants(
            plugin_id, parent_id, user_id=self._user_id
        )

    async def connect_custom_mcp(self, plugin_id: str, endpoint: str, transport: str) -> dict[str, str]:
        record = await self._mcp.connect_custom_mcp(
            plugin_id, endpoint=endpoint, transport=transport, user_id=self._user_id
        )
        return {"plugin_id": plugin_id, "connection_id": str(record.id), "status": record.status}

    async def sync(self, plugin_id: str, *, steps=None, goal_sync_job_id=None) -> dict[str, object]:
        return await self._mcp.sync(
            plugin_id, user_id=self._user_id, steps=steps, goal_sync_job_id=goal_sync_job_id
        )

    async def disconnect(self, plugin_id: str) -> None:
        await self._mcp.disconnect(plugin_id, user_id=self._user_id)

    async def discover_read_capabilities(self, plugin_id: str):
        return await self._catalog.discover_read_capabilities(plugin_id)
