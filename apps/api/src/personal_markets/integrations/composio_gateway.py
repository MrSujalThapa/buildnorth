from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from typing import Any
from uuid import UUID

from personal_markets.core.config import Settings
from personal_markets.integrations.mcp_domain import MCPResourceDescriptor, MCPToolDescriptor

_TOOLKIT_CACHE_TTL_SECONDS = 600.0
_RESOURCE_DISCOVERY_PAGE_LIMIT = 5
_RESOURCE_DISCOVERY_RESULT_LIMIT = 100


def _resource_rows(payload: dict[str, Any]) -> list[Any]:
    rows = (
        payload.get("records") or payload.get("items") or payload.get("results")
        or payload.get("repositories") or payload.get("pages")
        or payload.get("data") or []
    )
    if isinstance(rows, dict):
        rows = (
            rows.get("items") or rows.get("repositories") or rows.get("results")
            or rows.get("pages") or rows.get("data") or []
        )
    return rows if isinstance(rows, list) else []
_toolkit_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _resource_title_part(part: dict[str, Any], toolkit_slug: str) -> str:
    """Render a date mention as a readable title without changing ordinary text."""
    mention = part.get("mention")
    if (
        toolkit_slug == "notion"
        and part.get("type") == "mention"
        and isinstance(mention, dict)
        and mention.get("type") == "date"
    ):
        date = mention.get("date")
        start = date.get("start") if isinstance(date, dict) else None
        if isinstance(date, dict) and isinstance(start, str) and date.get("end") is None:
            try:
                value = datetime.fromisoformat(start)
            except ValueError:
                pass
            else:
                label = f"@{value.strftime('%B')} {value.day}, {value.year}"
                if "T" in start:
                    label += f" {value.strftime('%I:%M %p').lstrip('0')}"
                return label
    return str(part.get("plain_text") or (part.get("text") or {}).get("content") or "")


@dataclass(frozen=True)
class CatalogPage:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total_items: int | None


@dataclass(frozen=True)
class ConnectInitResult:
    auth_config_id: str
    connection_request_id: str
    redirect_url: str
    status: str = "pending_auth"


@dataclass(frozen=True)
class ConnectedAccountStatus:
    connected_account_id: str | None
    status: str
    account_label: str | None = None


@dataclass(frozen=True)
class ComposioConnectedAccount:
    connected_account_id: str
    toolkit_slug: str
    status: str
    account_label: str | None = None
    created_at: str | None = None


class ComposioIntegrationGateway:
    """Generic Composio Platform gateway — no provider-specific business logic."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @cached_property
    def _client(self) -> Any | None:
        api_key = self._settings.composio_api_key
        if not self.available or not api_key:
            return None
        from composio import Composio

        return Composio(api_key=api_key)

    @property
    def available(self) -> bool:
        injected = self.__dict__.get("_client")
        return injected is not None or bool(
            self._settings.composio_enabled and self._settings.composio_api_key
        )

    async def search_toolkits(
        self,
        *,
        search: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CatalogPage:
        if self._client is None:
            return CatalogPage(items=[], next_cursor=None, total_items=0)

        catalog = await self._cached_toolkits()
        needle = (search or "").strip().lower()
        if needle:
            catalog = [
                item
                for item in catalog
                if needle
                in " ".join(
                    str(item.get(key) or "") for key in ("slug", "name", "description")
                ).lower()
            ]
        start = 0
        if cursor:
            try:
                start = max(0, int(cursor))
            except ValueError:
                start = 0
        page = catalog[start : start + limit]
        next_cursor = str(start + limit) if start + limit < len(catalog) else None
        return CatalogPage(items=page, next_cursor=next_cursor, total_items=len(catalog))

    async def _cached_toolkits(self) -> list[dict[str, Any]]:
        cache_key = "composio:toolkits"
        cached = _toolkit_cache.get(cache_key)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        items = await asyncio.to_thread(self._fetch_toolkits)
        _toolkit_cache[cache_key] = (now + _TOOLKIT_CACHE_TTL_SECONDS, items)
        return items

    def _fetch_toolkits(self) -> list[dict[str, Any]]:
        assert self._client is not None
        collected: list[dict[str, Any]] = []
        cursor = None
        for _ in range(8):
            params: dict[str, Any] = {"limit": 50}
            if cursor:
                params["cursor"] = cursor
            try:
                response = self._client.toolkits.list(**params)
            except TypeError:
                response = self._client.toolkits.list(limit=50)
            for item in getattr(response, "items", []) or []:
                meta = getattr(item, "meta", None) or {}
                collected.append(
                    {
                        "slug": getattr(item, "slug", ""),
                        "name": getattr(item, "name", ""),
                        "description": meta.get("description")
                        if isinstance(meta, dict)
                        else getattr(meta, "description", ""),
                        "logo": meta.get("logo")
                        if isinstance(meta, dict)
                        else getattr(meta, "logo", None),
                        "categories": meta.get("categories") if isinstance(meta, dict) else [],
                        "tools_count": meta.get("tools_count")
                        if isinstance(meta, dict)
                        else None,
                        "auth_schemes": list(getattr(item, "auth_schemes", []) or []),
                    }
                )
            cursor = getattr(response, "next_cursor", None)
            if not cursor:
                break
        return collected

    def invalidate_toolkit_cache(self) -> None:
        _toolkit_cache.clear()

    async def ensure_auth_config(self, toolkit_slug: str) -> str:
        assert self._client is not None

        def _call() -> str:
            existing = self._client.auth_configs.list(search=toolkit_slug)
            for item in getattr(existing, "items", []) or []:
                slug = getattr(getattr(item, "toolkit", None), "slug", None)
                if slug == toolkit_slug:
                    return str(item.id)
            created = self._client.auth_configs.create(
                toolkit=toolkit_slug,
                options={"type": "use_composio_managed_auth", "name": f"PlayItOut {toolkit_slug}"},
            )
            return str(created.id)

        return await asyncio.to_thread(_call)

    async def initiate_connection(self, user_id: UUID, toolkit_slug: str) -> ConnectInitResult:
        auth_config_id = await self.ensure_auth_config(toolkit_slug)

        def _call() -> ConnectInitResult:
            assert self._client is not None
            link = self._client.connected_accounts.link(
                user_id=str(user_id),
                auth_config_id=auth_config_id,
            )
            return ConnectInitResult(
                auth_config_id=auth_config_id,
                connection_request_id=str(link.id),
                redirect_url=str(link.redirect_url),
                status="pending_auth",
            )

        return await asyncio.to_thread(_call)

    @staticmethod
    def _toolkit_slug(item: Any) -> str | None:
        toolkit = getattr(item, "toolkit", None)
        slug = getattr(toolkit, "slug", None) if toolkit is not None else None
        if slug:
            return str(slug)
        return str(getattr(item, "toolkit_slug", "") or "") or None

    @staticmethod
    def _account_label(item: Any) -> str | None:
        return (
            getattr(item, "account_name", None)
            or getattr(item, "app_name", None)
            or getattr(item, "account_id", None)
        )

    @staticmethod
    def _created_at(item: Any) -> str | None:
        created = getattr(item, "created_at", None)
        return str(created) if created is not None else None

    @staticmethod
    def _is_active_status(status: str) -> bool:
        return status.upper() == "ACTIVE"

    def _to_connected_account(self, item: Any) -> ComposioConnectedAccount | None:
        status = str(getattr(item, "status", "")).upper()
        if not self._is_active_status(status):
            return None
        toolkit_slug = self._toolkit_slug(item)
        if not toolkit_slug:
            return None
        return ComposioConnectedAccount(
            connected_account_id=str(item.id),
            toolkit_slug=toolkit_slug,
            status=status,
            account_label=self._account_label(item),
            created_at=self._created_at(item),
        )

    async def list_active_connected_accounts(self, user_id: UUID) -> dict[str, list[ComposioConnectedAccount]]:
        if self._client is None:
            return {}

        def _call() -> dict[str, list[ComposioConnectedAccount]]:
            assert self._client is not None
            grouped: dict[str, list[ComposioConnectedAccount]] = {}
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {"user_ids": [str(user_id)], "limit": 50}
                if cursor:
                    params["cursor"] = cursor
                accounts = self._client.connected_accounts.list(**params)
                for item in getattr(accounts, "items", []) or []:
                    account = self._to_connected_account(item)
                    if account is None:
                        continue
                    grouped.setdefault(account.toolkit_slug, []).append(account)
                cursor = getattr(accounts, "next_cursor", None)
                if not cursor:
                    break
            return grouped

        return await asyncio.to_thread(_call)

    async def connected_account_status(
        self,
        user_id: UUID,
        toolkit_slug: str,
        *,
        connection_request_id: str | None = None,
        preferred_connected_account_id: str | None = None,
    ) -> ConnectedAccountStatus:
        if self._client is None:
            return ConnectedAccountStatus(connected_account_id=None, status="unavailable")

        def _call() -> ConnectedAccountStatus:
            assert self._client is not None
            if connection_request_id:
                try:
                    request = self._client.connected_accounts.wait_for_connection(
                        connection_request_id,
                        timeout=0.1,
                    )
                    if request is not None:
                        account = self._to_connected_account(request)
                        if account is not None:
                            return ConnectedAccountStatus(
                                connected_account_id=account.connected_account_id,
                                status="connected",
                                account_label=account.account_label,
                            )
                except Exception:
                    pass
            accounts = self._client.connected_accounts.list(
                user_ids=[str(user_id)],
                toolkit_slugs=[toolkit_slug],
            )
            active: list[ComposioConnectedAccount] = []
            for item in getattr(accounts, "items", []) or []:
                account = self._to_connected_account(item)
                if account is not None:
                    active.append(account)
            if not active:
                return ConnectedAccountStatus(connected_account_id=None, status="pending_auth")
            selected = self._select_active_account(
                active,
                preferred_connected_account_id=preferred_connected_account_id,
            )
            return ConnectedAccountStatus(
                connected_account_id=selected.connected_account_id,
                status="connected",
                account_label=selected.account_label,
            )

        return await asyncio.to_thread(_call)

    @staticmethod
    def _select_active_account(
        accounts: list[ComposioConnectedAccount],
        *,
        preferred_connected_account_id: str | None = None,
    ) -> ComposioConnectedAccount:
        if preferred_connected_account_id:
            for account in accounts:
                if account.connected_account_id == preferred_connected_account_id:
                    return account
        if len(accounts) == 1:
            return accounts[0]
        return sorted(
            accounts,
            key=lambda item: item.created_at or "",
            reverse=True,
        )[0]

    async def list_tools(self, user_id: UUID, toolkit_slug: str, *, limit: int = 200) -> list[MCPToolDescriptor]:
        if self._client is None:
            return []

        def _call() -> list[MCPToolDescriptor]:
            assert self._client is not None
            tools = self._client.tools.get(str(user_id), toolkits=[toolkit_slug], limit=limit)
            rows: list[MCPToolDescriptor] = []
            for item in tools:
                if isinstance(item, dict):
                    fn = item.get("function") or {}
                    name = str(fn.get("name") or "")
                    description = str(fn.get("description") or "")
                    schema = fn.get("parameters") or {}
                else:
                    name = str(getattr(item, "slug", getattr(item, "name", "")))
                    description = str(getattr(item, "description", ""))
                    schema = getattr(item, "input_parameters", {}) or {}
                rows.append(
                    MCPToolDescriptor(
                        name=name,
                        description=description,
                        input_schema=schema if isinstance(schema, dict) else {},
                        read_only_hint=None,
                    )
                )
            return rows

        return await asyncio.to_thread(_call)

    async def list_resources(
        self,
        user_id: UUID,
        toolkit_slug: str,
        *,
        connected_account_id: str | None,
    ) -> list[MCPResourceDescriptor]:
        """Discover selectable resources via approved read tools where available."""
        preferred = {
            "github": "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER",
            "notion": "NOTION_SEARCH_NOTION_PAGE",
        }.get(toolkit_slug)
        if preferred:
            tool_name = preferred
        else:
            tools = await self.list_tools(user_id, toolkit_slug)
            resource_tools = [
                tool for tool in tools
                if any(token in tool.name.lower() for token in (
                    "list_repositories", "list_repos", "list_pages", "list_databases",
                    "list_spreadsheets", "list_sheets", "list_calendars", "list_files",
                    "list_folders", "list_labels", "list_threads",
                ))
            ]
            if not resource_tools:
                return []
            tool_name = resource_tools[0].name
        payload = await self.execute_tool(
            user_id,
            tool_name,
            {},
            connected_account_id=connected_account_id,
        )
        pages = [payload]
        # Notion search commonly returns a short first page. Consult the actual
        # action schema before passing a cursor; never guess provider arguments.
        if toolkit_slug == "notion" and payload.get("next_cursor"):
            tools = await self.list_tools(user_id, toolkit_slug, limit=100)
            tool = next((item for item in tools if item.name == tool_name), None)
            schema = tool.input_schema if tool else {}
            if isinstance(schema.get("parameters"), dict):
                schema = schema["parameters"]
            properties = schema.get("properties") or {}
            if isinstance(properties, dict) and "start_cursor" in properties:
                cursor = str(payload["next_cursor"])
                seen_cursors: set[str] = set()
                for _ in range(_RESOURCE_DISCOVERY_PAGE_LIMIT - 1):
                    if cursor in seen_cursors:
                        break
                    seen_cursors.add(cursor)
                    arguments: dict[str, Any] = {"start_cursor": cursor}
                    if "page_size" in properties:
                        arguments["page_size"] = 100
                    page = await self.execute_tool(
                        user_id, tool_name, arguments,
                        connected_account_id=connected_account_id,
                    )
                    pages.append(page)
                    discovered_count = sum(len(_resource_rows(item)) for item in pages)
                    if discovered_count >= _RESOURCE_DISCOVERY_RESULT_LIMIT:
                        break
                    cursor = str(page.get("next_cursor") or "")
                    if not cursor:
                        break
        resources: list[MCPResourceDescriptor] = []
        seen_resource_ids: set[str] = set()
        result_limit = _RESOURCE_DISCOVERY_RESULT_LIMIT if toolkit_slug == "notion" else 50
        rows: list[Any] = []
        for page in pages:
            rows.extend(_resource_rows(page))
            if len(rows) >= result_limit:
                break
        for row in rows[:result_limit]:
            if not isinstance(row, dict):
                continue
            title = row.get("title")
            if isinstance(title, list):
                title = "".join(
                    _resource_title_part(part, toolkit_slug)
                    for part in title if isinstance(part, dict)
                )
            if not title and isinstance(row.get("properties"), dict):
                for prop in row["properties"].values():
                    if isinstance(prop, dict) and prop.get("type") == "title":
                        title = "".join(
                            _resource_title_part(part, toolkit_slug)
                            for part in prop.get("title", []) if isinstance(part, dict)
                        )
                        break
            candidate_title = str(title or row.get("name") or "").strip()
            try:
                opaque_title = UUID(candidate_title)
            except ValueError:
                opaque_title = None
            if toolkit_slug == "notion" and (not candidate_title or opaque_title is not None):
                # Notion search can return untitled blocks. An opaque page ID is
                # not a usable selection label for a consumer evidence source.
                continue
            resource_id = str(
                row.get("full_name")
                or row.get("id")
                or row.get("name")
                or row.get("slug")
                or row.get("url")
                or title
            )
            label = str(title or row.get("full_name") or row.get("name") or "").strip()
            if not label:
                continue
            if resource_id in seen_resource_ids:
                continue
            seen_resource_ids.add(resource_id)
            resource_type = str(
                ("private" if row["private"] else "public")
                if isinstance(row.get("private"), bool)
                else row.get("object")
                or row.get("type")
                or row.get("kind")
                or row.get("mimeType")
                or "resource"
            )
            description = str(
                row.get("description")
                or row.get("about")
                or row.get("subtitle")
                or row.get("query")
                or ""
            )
            metadata = {
                key: value
                for key, value in row.items()
                if key in {"full_name", "default_branch", "parent", "database_id", "spreadsheet_id"}
                and value is not None
            }
            raw_url = row.get("url") or row.get("public_url") or row.get("href")
            if isinstance(raw_url, str) and raw_url.startswith(("http://", "https://")):
                metadata["url"] = raw_url
            provider_id = row.get("id")
            if provider_id is not None:
                metadata["provider_id"] = str(provider_id)
            if connected_account_id:
                metadata["connected_account_id"] = connected_account_id
            if toolkit_slug == "notion" and "url" not in metadata and provider_id is not None:
                compact = str(provider_id).replace("-", "")
                if len(compact) == 32 and all(char in "0123456789abcdefABCDEF" for char in compact):
                    metadata["url"] = f"https://www.notion.so/{compact}"
            resources.append(
                MCPResourceDescriptor(
                    uri=f"composio://{toolkit_slug}/{resource_id}",
                    name=label,
                    description=description,
                    mime_type=str(row.get("mimeType") or ""),
                    resource_type=resource_type,
                    metadata=metadata,
                )
            )
        return resources

    async def list_notion_child_pages(
        self,
        user_id: UUID,
        parent_id: str,
        *,
        connected_account_id: str | None,
    ) -> list[str]:
        """Traverse only children exposed through a selected, accessible parent."""
        from personal_markets.integrations.notion_scope import discover_child_page_ids

        tool_name = "NOTION_FETCH_BLOCK_CONTENTS"
        tools = await self.list_tools(user_id, "notion", limit=500)
        tool = next((item for item in tools if item.name == tool_name), None)
        schema = tool.input_schema if tool else {}
        if isinstance(schema.get("parameters"), dict):
            schema = schema["parameters"]
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict) or "block_id" not in properties:
            raise RuntimeError("Notion child-page discovery is unavailable for this connection")

        async def fetch(block_id: str, cursor: str | None) -> dict[str, Any]:
            arguments: dict[str, Any] = {"block_id": block_id}
            if "page_size" in properties:
                arguments["page_size"] = 100
            if cursor:
                if "start_cursor" not in properties:
                    raise RuntimeError("Notion child-page pagination is unavailable")
                arguments["start_cursor"] = cursor
            return await self.execute_tool(
                user_id, tool_name, arguments,
                connected_account_id=connected_account_id,
            )

        return await discover_child_page_ids(parent_id, fetch)

    async def execute_tool(
        self,
        user_id: UUID,
        tool_slug: str,
        arguments: dict[str, Any],
        *,
        connected_account_id: str | None,
    ) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("Composio is not configured")

        def _call() -> dict[str, Any]:
            assert self._client is not None
            kwargs: dict[str, Any] = {"arguments": arguments, "dangerously_skip_version_check": True}
            if connected_account_id:
                kwargs["connected_account_id"] = connected_account_id
            result = self._client.tools.execute(tool_slug, user_id=str(user_id), **kwargs)
            if isinstance(result, dict):
                if result.get("successful") is False or result.get("success") is False or result.get("isError") is True:
                    raise RuntimeError(str(result.get("error") or result.get("message") or "Provider read failed"))
                data = result.get("data") or result.get("response_data") or result
                if isinstance(data, dict):
                    return data
                return {"records": data}
            data = getattr(result, "data", result)
            if getattr(result, "successful", True) is False:
                raise RuntimeError(str(getattr(result, "error", None) or "Provider read failed"))
            if isinstance(data, dict):
                return data
            return {"records": data}

        return await asyncio.to_thread(_call)
