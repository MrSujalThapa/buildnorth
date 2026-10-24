"""Conservative, schema-driven Composio reads for connected toolkits.

No provider name is trusted as evidence of a read. A tool must have a read
verb, a usable object schema, and no mutation language before it is offered.
"""

from __future__ import annotations

import re
from typing import Any

from personal_markets.integrations.mcp_domain import MCPToolDescriptor
from personal_markets.integrations.mcp_policy import MCPReadPolicy
from personal_markets.integrations.provider_contract import (
    required_argument_names,
    schema_properties,
)

_RESOURCE_KEYS = frozenset(
    {
        "id",
        "resource_id",
        "file_id",
        "folder_id",
        "page_id",
        "block_id",
        "calendar_id",
        "calendarId",
        "channel",
        "channel_id",
        "spreadsheet_id",
        "spreadsheetId",
        "activity_id",
        "message_id",
        "thread_id",
        "repository",
        "repo",
        "owner",
        "document_id",
        "database_id",
        "sheet_id",
        "list_id",
    }
)
_QUERY_KEYS = frozenset({"q", "query", "search_query", "search_term"})
_PAGE_KEYS = frozenset(
    {
        "page",
        "page_size",
        "per_page",
        "limit",
        "max_results",
        "maxResults",
        "pageToken",
        "page_token",
        "start_cursor",
        "cursor",
        "offset",
    }
)
_TIME_KEYS = frozenset({"since", "updatedMin", "updated_min", "after", "from_date", "start_date"})
_SCOPE_KEYS = frozenset({"range", "sheet_range", "fields"})
_READ_WORDS = frozenset({"list", "get", "read", "fetch", "search", "query", "retrieve", "find"})


def safe_read_tool(plugin_id: str, tool: MCPToolDescriptor) -> bool:
    if not MCPReadPolicy().classify_tool(plugin_id, tool):
        return False
    body = tool.input_schema.get("parameters", tool.input_schema)
    if not isinstance(body, dict) or body.get("type", "object") != "object":
        return False
    properties = schema_properties(tool.input_schema)
    if not properties and required_argument_names(tool.input_schema):
        return False
    return all(isinstance(value, dict) for value in properties.values())


def read_kind(tool: MCPToolDescriptor) -> str:
    tokens = set(re.split(r"[^a-z0-9]+", tool.name.lower()))
    if tokens & {"search", "query", "find"}:
        return "search"
    if tokens & {"list"}:
        return "list"
    if tokens & {"get", "fetch", "read", "retrieve"}:
        return "record"
    return "unknown"


def allowed_required(tool: MCPToolDescriptor) -> bool:
    properties = schema_properties(tool.input_schema)
    return all(
        name in properties
        and name in _RESOURCE_KEYS | _QUERY_KEYS | _PAGE_KEYS | _TIME_KEYS | _SCOPE_KEYS
        for name in required_argument_names(tool.input_schema)
    )


def discovery_tool(plugin_id: str, tools: list[MCPToolDescriptor]) -> MCPToolDescriptor | None:
    """Only execute a bounded listing/search that requires no private arguments."""
    candidates = [
        tool
        for tool in tools
        if safe_read_tool(plugin_id, tool)
        and read_kind(tool) in {"list", "search"}
        and not required_argument_names(tool.input_schema)
    ]
    candidates.sort(
        key=lambda tool: (
            read_kind(tool) != "list",
            len(schema_properties(tool.input_schema)),
            tool.name,
        )
    )
    return candidates[0] if candidates else None


def goal_read_tools(plugin_id: str, tools: list[MCPToolDescriptor]) -> list[MCPToolDescriptor]:
    return [
        tool
        for tool in tools
        if safe_read_tool(plugin_id, tool)
        and read_kind(tool) in {"list", "record", "search"}
        and allowed_required(tool)
        and any(key in _RESOURCE_KEYS | _QUERY_KEYS for key in schema_properties(tool.input_schema))
    ]


def arguments_for_selection(
    tool: MCPToolDescriptor, target: str, extras: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Bind one explicit resource/query to one schema-declared required input."""
    properties = schema_properties(tool.input_schema)
    required = required_argument_names(tool.input_schema)
    provided = {key: value for key, value in (extras or {}).items() if value not in ("", None)}
    if any(key not in properties for key in provided):
        return None
    binding = [key for key in required if key in _RESOURCE_KEYS | _QUERY_KEYS and key not in provided]
    if not binding:
        optional = [
            key for key in properties if key in _RESOURCE_KEYS | _QUERY_KEYS and key not in provided
        ]
        if len(optional) == 1:
            binding = optional
    if len(binding) > 1 or any(key not in properties for key in required):
        return None
    if not binding:
        return provided if all(key in provided for key in required) else None
    key = binding[0]
    if not target or len(target) > 500 or properties[key].get("type") not in (None, "string"):
        return None
    if any(name not in provided and name != key and name not in _PAGE_KEYS for name in required):
        return None
    return {**provided, key: target}


def bound_page_arguments(
    tool: MCPToolDescriptor, arguments: dict[str, Any], *, cursor: str | None = None
) -> dict[str, Any]:
    properties = schema_properties(tool.input_schema)
    bounded = dict(arguments)
    for key in ("limit", "page_size", "per_page", "max_results", "maxResults"):
        if key in properties and key not in bounded:
            maximum = properties[key].get("maximum")
            bounded[key] = min(25, int(maximum)) if isinstance(maximum, (int, float)) else 25
            break
    if "page" in properties and "page" not in bounded:
        bounded["page"] = 1
    if cursor:
        for key in ("pageToken", "page_token", "start_cursor", "cursor"):
            if key in properties:
                bounded[key] = cursor
                break
    return bounded


def incremental_key(tool: MCPToolDescriptor) -> str | None:
    return next(
        (
            key
            for key in ("since", "updatedMin", "updated_min", "after")
            if key in schema_properties(tool.input_schema)
        ),
        None,
    )
