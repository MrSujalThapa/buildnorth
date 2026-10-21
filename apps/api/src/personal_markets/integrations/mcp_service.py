from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from personal_markets.core.config import DEFAULT_USER_ID, Settings, get_settings
from personal_markets.core.errors import UnauthorizedError
from personal_markets.integrations.composio_gateway import ComposioIntegrationGateway
from personal_markets.integrations.composio_normalizer import normalize_tool_result
from personal_markets.integrations.composio_transport import ComposioTransport
from personal_markets.integrations.mcp_domain import (
    ConnectionType,
    PluginConnectionRecord,
    RawSourceRecord,
    ReadCapabilityRecord,
    SyncCursorRecord,
    SyncRecipeRecord,
    SyncRecipeStep,
)
from personal_markets.integrations.mcp_policy import MCPReadPolicy
from personal_markets.integrations.mcp_repository import InMemoryIntegrationRepository
from personal_markets.integrations.mcp_transport import MCPTransport, MockMCPTransport
from personal_markets.integrations.plugins import (
    PLUGIN_DEFINITIONS,
    PluginConnection,
    PluginDefinition,
    PluginStatus,
    PluginView,
)

_MCP_DEFAULT_USER_ID = DEFAULT_USER_ID
_SYNC_TOOL_TIMEOUT_SECONDS = 30
_log = logging.getLogger(__name__)


class IntegrationGatewayService:
    """Generic MCP/plugin gateway supporting managed and custom MCP transports."""

    def __init__(
        self,
        repository: InMemoryIntegrationRepository | None = None,
        policy: MCPReadPolicy | None = None,
        default_user_id: UUID | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository or InMemoryIntegrationRepository()
        self._policy = policy or MCPReadPolicy()
        self._default_user_id = default_user_id or _MCP_DEFAULT_USER_ID
        self._settings = settings or get_settings()
        self._composio = ComposioIntegrationGateway(self._settings)
        self._definitions = {item.id: item for item in PLUGIN_DEFINITIONS}

    def _owner(self, user_id: UUID | None) -> UUID:
        if user_id is not None:
            return user_id
        if self._settings.environment in {"test", "pytest"}:
            return self._default_user_id
        raise UnauthorizedError("authenticated user required")

    def _transport_for(self, connection: PluginConnectionRecord) -> MCPTransport:
        if (
            connection.connection_type == ConnectionType.MANAGED_GATEWAY
            and self._composio.available
            and connection.status == "connected"
        ):
            return ComposioTransport(
                self._settings,
                plugin_id=connection.plugin_id,
                user_id=connection.user_id,
                connected_account_id=connection.account_metadata.get("connected_account_id"),
            )
        if connection.connection_type == ConnectionType.CUSTOM_MCP:
            endpoint = connection.account_metadata.get("endpoint", "")
            if not endpoint:
                raise ValueError("custom MCP endpoint is required")
            return MockMCPTransport(connection.plugin_id)
        return MockMCPTransport(connection.plugin_id)

    async def _reconcile_connections(self, user_id: UUID) -> None:
        if not self._composio.available:
            return
        active_by_toolkit = await self._composio.list_active_connected_accounts(user_id)
        local_connections = {
            item.plugin_id: item for item in await self._repository.list_connections(user_id)
        }
        now = datetime.now(UTC)

        for toolkit_slug, accounts in active_by_toolkit.items():
            existing = local_connections.get(toolkit_slug)
            selected = self._composio._select_active_account(
                accounts,
                preferred_connected_account_id=(
                    existing.account_metadata.get("connected_account_id") if existing else None
                ),
            )
            metadata: dict[str, str] = {
                "gateway": "composio",
                "connected_account_id": selected.connected_account_id,
            }
            if selected.account_label:
                metadata["account_label"] = selected.account_label
            if len(accounts) > 1:
                metadata["alternate_connected_account_ids"] = ",".join(
                    account.connected_account_id
                    for account in accounts
                    if account.connected_account_id != selected.connected_account_id
                )

            previous_account_id = (
                existing.account_metadata.get("connected_account_id") if existing else None
            )
            became_connected = existing is None or existing.status != "connected"
            account_changed = previous_account_id != selected.connected_account_id

            if existing is None:
                record = PluginConnectionRecord(
                    id=uuid4(),
                    user_id=user_id,
                    plugin_id=toolkit_slug,
                    connection_type=ConnectionType.MANAGED_GATEWAY,
                    gateway_provider="composio",
                    transport="http",
                    auth_ref=selected.connected_account_id,
                    status="connected",
                    account_metadata=metadata,
                    created_at=now,
                    last_verified_at=now,
                )
                await self._repository.upsert_connection(record)
                stored = await self._repository.get_connection(user_id, toolkit_slug)
                assert stored is not None
                if became_connected or account_changed:
                    await self._discover_and_persist(stored)
                continue

            updated = existing.model_copy(
                update={
                    "status": "connected",
                    "gateway_provider": existing.gateway_provider or "composio",
                    "auth_ref": selected.connected_account_id,
                    "account_metadata": {**existing.account_metadata, **metadata},
                    "last_verified_at": now,
                }
            )
            await self._repository.upsert_connection(updated)
            if became_connected or account_changed:
                await self._discover_and_persist(updated)

        for plugin_id, connection in local_connections.items():
            if connection.connection_type != ConnectionType.MANAGED_GATEWAY:
                continue
            if plugin_id in active_by_toolkit:
                continue
            # A newly authorized account can take time to appear in Composio's
            # account listing. Keep the request pending until refresh confirms
            # its outcome; demoting it here stops the client's pending poll.
            if connection.status == "connected":
                await self._repository.update_connection(connection.id, status="not_connected")

    async def search_catalog(
        self,
        *,
        search: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
        user_id: UUID | None = None,
        reconcile: bool = False,
    ) -> dict[str, object]:
        owner = self._owner(user_id)
        if reconcile:
            await self._reconcile_connections(owner)
        stored_connections = await self._repository.list_connections(owner)
        connections = {item.plugin_id: item for item in stored_connections}
        local_views = await self._local_plugin_views(connections)
        provider_status = "available" if self._composio.available else "unavailable"
        provider_message = None
        if not self._composio.available:
            provider_message = (
                "Connected-app catalog is unavailable. Manual and CSV evidence still work."
            )
            filtered = [
                view
                for view in local_views
                if not search
                or search.lower() in f"{view.definition.name} {view.definition.description}".lower()
            ]
            return {
                "items": [item.model_dump(mode="json") for item in filtered[:limit]],
                "next_cursor": None,
                "total_items": len(filtered),
                "provider_status": provider_status,
                "provider_message": provider_message,
            }
        if not search and not cursor:
            return {
                "items": [item.model_dump(mode="json") for item in local_views[:limit]],
                "next_cursor": None,
                "total_items": len(local_views),
                "provider_status": provider_status,
                "provider_message": provider_message,
            }
        try:
            page = await self._composio.search_toolkits(search=search, cursor=cursor, limit=limit)
        except Exception:
            provider_status = "error"
            provider_message = (
                "The integration catalog could not be loaded. Retry, or use Manual / CSV evidence."
            )
            return {
                "items": [item.model_dump(mode="json") for item in local_views],
                "next_cursor": None,
                "total_items": len(local_views),
                "provider_status": provider_status,
                "provider_message": provider_message,
            }
        items: list[PluginView] = []
        for row in page.items:
            view = self._toolkit_view(row, connections)
            if view is not None:
                items.append(view)
        if not search and not cursor:
            remote = [item for item in items if item.definition.id not in {"manual", "csv"}]
            local_ids = {item.definition.id for item in local_views}
            items = [*local_views, *(item for item in remote if item.definition.id not in local_ids)]
        elif search:
            extra = [
                view
                for view in local_views
                if search.lower() in f"{view.definition.name} {view.definition.description}".lower()
                and view.definition.id not in {item.definition.id for item in items}
            ]
            items = [*extra, *items]
        return {
            "items": [item.model_dump(mode="json") for item in items],
            "next_cursor": page.next_cursor,
            "total_items": page.total_items if page.total_items is not None else len(items),
            "provider_status": provider_status,
            "provider_message": provider_message,
        }

    def _connection_view(
        self,
        stored: PluginConnectionRecord,
        *,
        permissions: list[str] | None = None,
    ) -> PluginConnection:
        status_map = {
            "connected": PluginStatus.CONNECTED,
            "pending_auth": PluginStatus.PENDING_AUTH,
            "error": PluginStatus.ERROR,
            "syncing": PluginStatus.SYNCING,
        }
        return PluginConnection(
            plugin_id=stored.plugin_id,
            status=status_map.get(stored.status, PluginStatus.NOT_CONNECTED),
            connected_at=stored.created_at.isoformat(),
            last_sync_at=stored.last_sync_at.isoformat() if stored.last_sync_at else None,
            permissions=permissions or [],
            account_metadata=stored.account_metadata,
            error=None if stored.status == "connected" else stored.status,
        )

    async def views(
        self, user_id: UUID | None = None, *, reconcile: bool = False
    ) -> list[PluginView]:
        catalog = await self.search_catalog(limit=50, user_id=user_id, reconcile=reconcile)
        return [PluginView.model_validate(item) for item in catalog["items"]]

    async def connected_views(self, user_id: UUID | None = None) -> list[PluginView]:
        """Return stored connections without waiting for the remote toolkit catalog."""
        owner = self._owner(user_id)
        connections = {
            item.plugin_id: item for item in await self._repository.list_connections(owner)
        }
        return [
            view for view in await self._local_plugin_views(connections)
            if view.definition.id in connections
        ]

    async def _local_plugin_views(
        self, connections: dict[str, PluginConnectionRecord]
    ) -> list[PluginView]:
        views: list[PluginView] = []
        for definition in PLUGIN_DEFINITIONS:
            stored = connections.get(definition.id)
            if stored is None:
                connection = PluginConnection(
                    plugin_id=definition.id, status=PluginStatus.NOT_CONNECTED
                )
            else:
                connection = self._connection_view(stored)
            views.append(PluginView(definition=definition, connection=connection))
        known = {item.definition.id for item in views}
        for plugin_id, stored in connections.items():
            if plugin_id in known:
                continue
            views.append(PluginView(
                definition=PluginDefinition(
                    id=plugin_id, name=plugin_id.replace("_", " ").title(),
                    description="Connected source", category="integration",
                    provider_type="composio",
                ),
                connection=self._connection_view(stored),
            ))
        return views

    def _toolkit_view(
        self, row: dict[str, Any], connections: dict[str, PluginConnectionRecord]
    ) -> PluginView | None:
        plugin_id = str(row.get("slug") or "")
        if not plugin_id or plugin_id in {"manual", "csv"}:
            return None
        stored = connections.get(plugin_id)
        if stored is None:
            connection = PluginConnection(plugin_id=plugin_id, status=PluginStatus.NOT_CONNECTED)
        else:
            connection = self._connection_view(stored)
        categories = row.get("categories") or [{"name": "integration"}]
        category = "integration"
        if isinstance(categories, list) and categories:
            first = categories[0]
            if isinstance(first, dict):
                category = str(first.get("name") or "integration")
            elif isinstance(first, str):
                category = first
        definition = PluginDefinition(
            id=plugin_id,
            name=str(row.get("name") or plugin_id),
            description=str(row.get("description") or ""),
            category=category,
            provider_type="composio",
            logo_url=str(row.get("logo") or "") or None,
            used_for=(
                [f"{row.get('tools_count')} tools available"] if row.get("tools_count") else []
            ),
        )
        return PluginView(definition=definition, connection=connection)

    async def connect_managed(
        self,
        plugin_id: str,
        *,
        user_id: UUID | None = None,
        gateway_provider: str = "composio",
        auth_ref: str | None = None,
    ) -> dict[str, object]:
        owner = self._owner(user_id)
        now = datetime.now(UTC)
        if not self._composio.available:
            if self._settings.environment in {"test", "pytest"}:
                record = PluginConnectionRecord(
                    id=uuid4(),
                    user_id=owner,
                    plugin_id=plugin_id,
                    connection_type=ConnectionType.MANAGED_GATEWAY,
                    gateway_provider=gateway_provider,
                    transport="http",
                    auth_ref=auth_ref or f"mock:{plugin_id}:{owner}",
                    status="connected",
                    account_metadata={"gateway": "mock"},
                    created_at=now,
                    last_verified_at=now,
                )
                await self._repository.upsert_connection(record)
                stored = await self._repository.get_connection(owner, plugin_id)
                assert stored is not None
                await self._discover_and_persist(stored)
                return {
                    "plugin_id": plugin_id,
                    "connection_id": str(stored.id),
                    "status": stored.status,
                }
            raise RuntimeError("Composio integration is not configured")

        await self._reconcile_connections(owner)
        existing = await self._repository.get_connection(owner, plugin_id)
        if existing is not None and existing.status == "connected":
            return {
                "plugin_id": plugin_id,
                "connection_id": str(existing.id),
                "status": "connected",
                "connected_account_id": existing.account_metadata.get("connected_account_id"),
                "account_label": existing.account_metadata.get("account_label"),
            }
        if existing is not None and existing.status == "pending_auth":
            auth_url = existing.account_metadata.get("auth_url")
            created_at = existing.account_metadata.get("auth_url_created_at")
            try:
                issued = datetime.fromisoformat(created_at) if created_at else None
                age = (now - issued).total_seconds() if issued and issued.tzinfo else None
                fresh = age is not None and 0 <= age < 300
            except ValueError:
                fresh = False
            if auth_url and fresh:
                return {
                    "plugin_id": plugin_id,
                    "connection_id": str(existing.id),
                    "status": "pending_auth",
                    "auth_url": auth_url,
                }

        init = await self._composio.initiate_connection(owner, plugin_id)
        record = PluginConnectionRecord(
            id=existing.id if existing is not None else uuid4(),
            user_id=owner,
            plugin_id=plugin_id,
            connection_type=ConnectionType.MANAGED_GATEWAY,
            gateway_provider=gateway_provider,
            transport="http",
            auth_ref=init.connection_request_id,
            status="pending_auth",
            account_metadata={
                "gateway": gateway_provider,
                "auth_config_id": init.auth_config_id,
                "connection_request_id": init.connection_request_id,
                "auth_url": init.redirect_url,
                "auth_url_created_at": now.isoformat(),
            },
            created_at=existing.created_at if existing is not None else now,
            last_verified_at=now,
            last_sync_at=existing.last_sync_at if existing is not None else None,
        )
        await self._repository.upsert_connection(record)
        return {
            "plugin_id": plugin_id,
            "connection_id": str(record.id),
            "status": record.status,
            "auth_url": init.redirect_url,
        }

    async def list_capabilities(self, plugin_id: str, *, user_id: UUID | None = None) -> list[dict[str, object]]:
        owner = self._owner(user_id)
        connection = await self._repository.get_connection(owner, plugin_id)
        if connection is None:
            return []
        rows = await self._repository.list_capabilities(connection.id)
        return [row.model_dump(mode="json") for row in rows]

    async def list_resources(self, plugin_id: str, *, user_id: UUID | None = None) -> list[dict[str, object]]:
        owner = self._owner(user_id)
        connection = await self._repository.get_connection(owner, plugin_id)
        if connection is None:
            return []
        transport = self._transport_for(connection)
        resources = await transport.list_resources()
        return [item.model_dump(mode="json") for item in resources]

    async def refresh_connection(self, plugin_id: str, *, user_id: UUID | None = None) -> dict[str, object]:
        owner = self._owner(user_id)
        await self._reconcile_connections(owner)
        connection = await self._repository.get_connection(owner, plugin_id)
        if connection is None:
            raise KeyError(f"no connection for plugin {plugin_id}")
        if not self._composio.available:
            return {"plugin_id": plugin_id, "status": connection.status}
        status = await self._composio.connected_account_status(
            owner,
            plugin_id,
            connection_request_id=connection.account_metadata.get("connection_request_id"),
            preferred_connected_account_id=connection.account_metadata.get("connected_account_id"),
        )
        metadata = dict(connection.account_metadata)
        if status.connected_account_id:
            metadata["connected_account_id"] = status.connected_account_id
        if status.account_label:
            metadata["account_label"] = status.account_label
        next_status = "connected" if status.status == "connected" else connection.status
        if status.connected_account_id and next_status == "connected":
            updated = connection.model_copy(
                update={
                    "status": next_status,
                    "account_metadata": metadata,
                    "last_verified_at": datetime.now(UTC),
                }
            )
            await self._repository.upsert_connection(updated)
            await self._discover_and_persist(updated)
            return {
                "plugin_id": plugin_id,
                "status": next_status,
                "connected_account_id": status.connected_account_id,
                "account_label": status.account_label,
            }
        return {"plugin_id": plugin_id, "status": connection.status, "auth_url": metadata.get("auth_url")}

    async def connect_custom_mcp(
        self,
        plugin_id: str,
        *,
        endpoint: str,
        transport: str,
        user_id: UUID | None = None,
    ) -> PluginConnectionRecord:
        supported = {"stdio", "sse", "http"}
        if transport not in supported:
            raise ValueError(f"unsupported MCP transport: {transport}")
        owner = self._owner(user_id)
        now = datetime.now(UTC)
        record = PluginConnectionRecord(
            id=uuid4(),
            user_id=owner,
            plugin_id=plugin_id,
            connection_type=ConnectionType.CUSTOM_MCP,
            gateway_provider=None,
            transport=transport,
            auth_ref=None,
            status="connected",
            account_metadata={"endpoint": endpoint},
            created_at=now,
            last_verified_at=now,
        )
        await self._repository.upsert_connection(record)
        stored = await self._repository.get_connection(owner, plugin_id)
        assert stored is not None
        await self._discover_and_persist(stored)
        return stored

    async def _discover_and_persist(self, connection: PluginConnectionRecord) -> None:
        transport = self._transport_for(connection)
        tools = await transport.list_tools()
        capabilities: list[ReadCapabilityRecord] = []
        for tool in tools:
            if self._policy.reject_malicious_description(tool):
                continue
            discovered = self._policy.classify_tool(connection.plugin_id, tool)
            if discovered is None:
                continue
            capabilities.append(
                ReadCapabilityRecord(
                    id=uuid4(),
                    plugin_connection_id=connection.id,
                    capability_id=discovered.capability_id,
                    label=discovered.label,
                    operation=discovered.operation,
                    tool_name=discovered.tool_name,
                    resource_uri=discovered.resource_uri,
                    input_schema=discovered.input_schema,
                    approved=True,
                )
            )
        await self._repository.save_capabilities(connection.id, capabilities)
        steps = [
            SyncRecipeStep(
                capability_id=cap.capability_id,
                tool_name=cap.tool_name,
                arguments={"since": None},
            )
            for cap in capabilities
            if cap.tool_name
        ]
        if steps:
            await self._repository.save_recipe(
                SyncRecipeRecord(
                    id=uuid4(),
                    plugin_connection_id=connection.id,
                    recipe_version=1,
                    steps=steps,
                )
            )

    async def sync(
        self,
        plugin_id: str,
        *,
        user_id: UUID | None = None,
        steps: list[SyncRecipeStep] | None = None,
        goal_sync_job_id: UUID | None = None,
    ) -> dict[str, Any]:
        owner = self._owner(user_id)
        await self._reconcile_connections(owner)
        connection = await self._repository.get_connection(owner, plugin_id)
        if connection is None:
            raise KeyError(f"no connection for plugin {plugin_id}")
        if (
            connection.connection_type == ConnectionType.MANAGED_GATEWAY
            and self._composio.available
            and connection.status != "connected"
            and connection.account_metadata.get("connected_account_id")
        ):
            await self._reconcile_connections(owner)
            refreshed = await self._repository.get_connection(owner, plugin_id)
            if refreshed is not None:
                connection = refreshed
        recipe = await self._repository.get_recipe(connection.id)
        steps_to_run = steps or (recipe.steps if recipe else [])
        if not steps_to_run:
            return {"status": "noop", "records_new": 0, "message": "No approved read recipe"}
        transport = self._transport_for(connection)
        run = await self._repository.start_run(connection.id)
        records_read = 0
        raw_rows: list[RawSourceRecord] = []
        try:
            for step in steps_to_run:
                cursor = await self._repository.get_cursor(connection.id, step.capability_id)
                arguments = {
                    key: value
                    for key, value in dict(step.arguments).items()
                    if key not in {"resource_id", "label"}
                }
                if cursor and cursor.cursor_value:
                    arguments["since"] = cursor.cursor_value
                if not step.tool_name:
                    raise ValueError("Saved source has no supported read action. Select a source again.")
                started = time.perf_counter()
                try:
                    payload = await asyncio.wait_for(
                        transport.call_tool(step.tool_name, arguments),
                        timeout=_SYNC_TOOL_TIMEOUT_SECONDS,
                    )
                finally:
                    _log.info(
                        "source_sync_provider_call",
                        extra={
                            "sync_run_id": str(run.id),
                            "provider": plugin_id,
                            "tool": step.tool_name,
                            "duration_ms": round((time.perf_counter() - started) * 1000),
                        },
                    )
                raw_payload = payload.get("raw") or payload
                if isinstance(raw_payload, dict) and (
                    int(raw_payload.get("status_code") or 0) >= 400
                    or raw_payload.get("successful") is False
                    or raw_payload.get("success") is False
                    or raw_payload.get("isError") is True
                    or (raw_payload.get("error") and not raw_payload.get("results"))
                ):
                    raise RuntimeError(
                        f"{plugin_id} read failed: "
                        f"{raw_payload.get('message') or raw_payload.get('error') or 'permission or provider error'}"
                    )
                tool_rows = payload.get("records")
                if tool_rows is None:
                    tool_rows = payload.get("items")
                if tool_rows is None:
                    tool_rows = payload.get("data")
                if isinstance(tool_rows, list) and len(tool_rows) == 0:
                    continue
                normalized = normalize_tool_result(
                    plugin_id=plugin_id,
                    plugin_connection_id=connection.id,
                    sync_run_id=run.id,
                    tool_name=step.tool_name,
                    payload=raw_payload if isinstance(raw_payload, dict) else payload,
                    user_id=str(owner),
                    recipe_step=step,
                )
                rows = [
                    row.model_copy(
                        update={
                            "cursor_context": {
                                **row.cursor_context,
                                **({"goal_sync_job_id": str(goal_sync_job_id)} if goal_sync_job_id else {}),
                            }
                        }
                    )
                    for row in normalized
                ]
                records_read += len(rows)
                raw_rows.extend(rows)
                next_cursor = payload.get("next_cursor")
                if next_cursor:
                    await self._repository.put_cursor(
                        SyncCursorRecord(
                            plugin_connection_id=connection.id,
                            capability_id=step.capability_id,
                            cursor_value=str(next_cursor),
                            updated_at=datetime.now(UTC),
                        )
                    )
            inserted_rows = await self._repository.append_raw_records(raw_rows)
            records_new = len(inserted_rows)
            await self._repository.finish_run(
                run.id,
                status="completed",
                records_read=records_read,
                records_new=records_new,
            )
            await self._repository.update_connection(
                connection.id,
                last_sync_at=datetime.now(UTC),
                status="connected",
            )
            return {
                "status": "completed",
                "sync_run_id": str(run.id),
                "records_read": records_read,
                "records_new": records_new,
                "new_records": [item.model_dump(mode="json") for item in inserted_rows],
            }
        except Exception as exc:  # noqa: BLE001
            await self._repository.finish_run(
                run.id,
                status="failed",
                records_read=records_read,
                records_new=0,
                error=str(exc),
            )
            await self._repository.update_connection(connection.id, status="error")
            raise

    async def disconnect(self, plugin_id: str, *, user_id: UUID | None = None) -> None:
        owner = self._owner(user_id)
        connection = await self._repository.get_connection(owner, plugin_id)
        if connection is None:
            return
        await self._repository.delete_connection(connection.id)
