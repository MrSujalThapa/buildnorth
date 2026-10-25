from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from personal_markets.integrations.gateway import UnifiedIntegrationGateway
from personal_markets.wiring import get_integration_gateway

router = APIRouter(prefix="/api/v1/plugins", tags=["plugins"])


class ConnectManagedRequest(BaseModel):
    gateway_provider: str = "composio"
    auth_ref: str | None = None


class ConnectCustomMcpRequest(BaseModel):
    endpoint: str
    transport: str = Field(default="stdio", pattern="^(stdio|sse|http)$")


class SourcePreviewRequest(BaseModel):
    resource_id: str = Field(min_length=1, max_length=500)
    resource_title: str = Field(default="", max_length=200)
    resource_type: str = Field(default="", max_length=120)
    arguments: dict[str, str] = Field(default_factory=dict)


@router.get("")
async def plugins(
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
    search: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    browse: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    return await gateway.search_catalog(search=search, cursor=cursor, limit=limit, browse=browse)


@router.get("/connected")
async def connected_plugins(
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> list[dict[str, object]]:
    views = await gateway.connected_views()
    return [view.model_dump(mode="json") for view in views]


@router.post("/{plugin_id}/connect")
async def connect_managed(
    plugin_id: str,
    payload: ConnectManagedRequest,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> dict[str, object]:
    return await gateway.connect_managed(plugin_id, gateway_provider=payload.gateway_provider)


@router.post("/{plugin_id}/connect/refresh")
async def refresh_connection(
    plugin_id: str,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> dict[str, object]:
    return await gateway.refresh_connection(plugin_id)


@router.get("/{plugin_id}/capabilities")
async def plugin_capabilities(
    plugin_id: str,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> list[dict[str, object]]:
    return await gateway.list_capabilities(plugin_id)


@router.post("/{plugin_id}/preview")
async def preview_plugin_source(
    plugin_id: str,
    payload: SourcePreviewRequest,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> dict[str, object]:
    supplied = cast(dict[str, Any], dict(payload.arguments))
    return await gateway.preview_source(
        plugin_id,
        resource_id=payload.resource_id,
        resource_title=payload.resource_title,
        resource_type=payload.resource_type,
        arguments=supplied,
    )


@router.get("/{plugin_id}/access")
async def plugin_access(
    plugin_id: str,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> dict[str, object]:
    return await gateway.source_access(plugin_id)


@router.get("/{plugin_id}/resources")
async def plugin_resources(
    plugin_id: str,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> list[dict[str, object]]:
    return await gateway.list_resources(plugin_id)


@router.post("/{plugin_id}/connect/custom-mcp")
async def connect_custom_mcp(
    plugin_id: str,
    payload: ConnectCustomMcpRequest,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> dict[str, str]:
    return await gateway.connect_custom_mcp(plugin_id, endpoint=payload.endpoint, transport=payload.transport)


@router.post("/{plugin_id}/sync")
async def sync_plugin(
    plugin_id: str,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> dict[str, object]:
    return await gateway.sync(plugin_id)


@router.delete("/{plugin_id}/connect")
async def disconnect_plugin(
    plugin_id: str,
    gateway: Annotated[UnifiedIntegrationGateway, Depends(get_integration_gateway)],
) -> dict[str, str]:
    await gateway.disconnect(plugin_id)
    return {"plugin_id": plugin_id, "status": "disconnected"}
