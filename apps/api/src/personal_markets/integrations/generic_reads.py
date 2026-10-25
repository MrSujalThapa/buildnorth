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
_SCOPE_KEYS = frozenset({"range", "ranges", "sheet_range", "fields"})
_READ_WORDS = frozenset({"list", "get", "read", "fetch", "search", "query", "retrieve", "find"})
_CHANGE_FEED_TOKENS = frozenset(
    {"change", "changes", "delta", "watch", "monitor", "checkpoint", "webhook"}
)
_FORMATTED_ENUM_PREFERENCES = {
    "date_time_render_option": "FORMATTED_STRING",
    "dateTimeRenderOption": "FORMATTED_STRING",
    "value_render_option": "FORMATTED_VALUE",
    "valueRenderOption": "FORMATTED_VALUE",
}


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


def is_catalog_read(tool: MCPToolDescriptor) -> bool:
    """Skip change feeds and monitors. Those reads do not list selectable records."""
    tokens = set(re.split(r"[^a-z0-9]+", tool.name.lower()))
    if tokens & _CHANGE_FEED_TOKENS:
        return False
    description = tool.description.lower()
    return "without listing" not in description and "change monitor" not in description


def formatted_value_defaults(tool: MCPToolDescriptor) -> dict[str, str]:
    """Prefer schema enum values that keep dates and numbers readable."""
    defaults: dict[str, str] = {}
    for name, preferred in _FORMATTED_ENUM_PREFERENCES.items():
        spec = schema_properties(tool.input_schema).get(name)
        if not isinstance(spec, dict) or spec.get("type") not in (None, "string"):
            continue
        choices = spec.get("enum")
        if isinstance(choices, list) and preferred not in choices:
            continue
        defaults[name] = preferred
    return defaults


_CONTENT_TOKENS = frozenset(
    {
        "markdown",
        "plaintext",
        "plain",
        "content",
        "contents",
        "body",
        "readme",
        "snippet",
        "transcript",
    }
)
_METADATA_TOKENS = frozenset(
    {
        "metadata",
        "property",
        "properties",
        "info",
        "about",
        "profile",
        "permission",
        "setting",
        "settings",
    }
)
_ACTIVITY_TOKENS = frozenset(
    {"commit", "commits", "issue", "issues", "event", "events", "activity", "activities", "pull"}
)
_SETTINGS_TOKENS = frozenset(
    {
        "setting",
        "settings",
        "filter",
        "filters",
        "forwarding",
        "vacation",
        "imap",
        "pop",
        "language",
        "profile",
        "label",
        "labels",
        "identity",
        "keypair",
        "contact",
        "contacts",
        "people",
        "about",
        "draft",
        "drafts",
        "history",
    }
)
_PRIMARY_TOKENS = frozenset(
    {
        "message",
        "messages",
        "thread",
        "threads",
        "page",
        "pages",
        "document",
        "documents",
        "file",
        "files",
        "spreadsheet",
        "spreadsheets",
        "repository",
        "repositories",
        "repo",
        "issue",
        "issues",
        "record",
        "records",
    }
)
_OWNER_KEYS = frozenset({"owner", "user", "username", "org", "organization", "login"})
_NAME_KEYS = frozenset({"repo", "repository", "name", "project", "slug"})
_TEXT_KEYS = (
    "markdown",
    "plain_text",
    "plaintext",
    "text",
    "body",
    "snippet",
    "subject",
    "paragraph",
    "content",
)
_ID_VALUE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def tool_tokens(tool: MCPToolDescriptor) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", f"{tool.name} {tool.description}".lower()))


def tool_roles(tool: MCPToolDescriptor) -> set[str]:
    """Classify a read by words in its name and description, not by provider."""
    tokens = tool_tokens(tool)
    name_tokens = set(re.split(r"[^a-z0-9]+", tool.name.lower()))
    roles: set[str] = set()
    kind = read_kind(tool)
    if kind == "search":
        roles.add("search")
    if kind == "list":
        roles.add("discover")
    if tokens & _CONTENT_TOKENS:
        roles.add("content")
    if kind == "record" and name_tokens & {
        "message",
        "messages",
        "thread",
        "threads",
        "email",
        "document",
        "page",
        "file",
    }:
        roles.add("content")
    if tokens & _METADATA_TOKENS and "content" not in roles:
        roles.add("metadata")
    if tokens & _ACTIVITY_TOKENS:
        roles.add("activity")
    named_settings = name_tokens & _SETTINGS_TOKENS and not (
        name_tokens & {"message", "thread", "page", "document"}
    )
    described_settings = tokens & _SETTINGS_TOKENS and not (
        tokens & {"message", "thread", "page", "document"}
    )
    if named_settings or described_settings:
        roles.add("settings")
    if any(key in schema_properties(tool.input_schema) for key in ("range", "sheet_range")):
        roles.add("measurement")
    return roles


def _inbox_listing(tool: MCPToolDescriptor) -> bool:
    """A message list with an optional query would read an unbounded mailbox."""
    if required_argument_names(tool.input_schema):
        return False
    tokens = tool_tokens(tool)
    has_query = any(key in _QUERY_KEYS for key in schema_properties(tool.input_schema))
    return has_query and bool(tokens & {"message", "messages", "thread", "threads"})


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
    allowed = _RESOURCE_KEYS | _QUERY_KEYS | _PAGE_KEYS | _TIME_KEYS | _SCOPE_KEYS
    for name in required_argument_names(tool.input_schema):
        spec = properties.get(name)
        if not isinstance(spec, dict) or name not in allowed:
            return False
        if name in _SCOPE_KEYS and spec.get("type") not in (None, "string"):
            return False
    return True


def discovery_tool(plugin_id: str, tools: list[MCPToolDescriptor]) -> MCPToolDescriptor | None:
    """Only execute a bounded listing/search that requires no private arguments."""
    candidates = [
        tool
        for tool in tools
        if safe_read_tool(plugin_id, tool)
        and is_catalog_read(tool)
        and read_kind(tool) in {"list", "search"}
        and not required_argument_names(tool.input_schema)
        and not _inbox_listing(tool)
    ]
    specific = [tool for tool in candidates if "settings" not in tool_roles(tool)]
    if specific:
        candidates = specific
    elif any(_inbox_listing(tool) for tool in tools):
        return None
    candidates.sort(key=_discovery_rank)
    return candidates[0] if candidates else None


def _discovery_rank(tool: MCPToolDescriptor) -> tuple[bool, bool, int, str]:
    return (
        read_kind(tool) != "list",
        not bool(tool_tokens(tool) & _PRIMARY_TOKENS),
        len(schema_properties(tool.input_schema)),
        tool.name,
    )


def goal_read_tools(plugin_id: str, tools: list[MCPToolDescriptor]) -> list[MCPToolDescriptor]:
    return [
        tool
        for tool in tools
        if safe_read_tool(plugin_id, tool)
        and is_catalog_read(tool)
        and read_kind(tool) in {"list", "record", "search"}
        and allowed_required(tool)
        and any(key in _RESOURCE_KEYS | _QUERY_KEYS for key in schema_properties(tool.input_schema))
    ]


def bounded_scope_defaults(tool: MCPToolDescriptor) -> dict[str, str]:
    """Fill a required string window, such as a range, with a small preview bound."""
    defaults: dict[str, str] = {}
    properties = schema_properties(tool.input_schema)
    for name in required_argument_names(tool.input_schema):
        if name not in {"range", "sheet_range"}:
            continue
        spec = properties.get(name)
        if not isinstance(spec, dict) or spec.get("type") not in (None, "string"):
            continue
        defaults[name] = "A1:Z8"
    return defaults


def preview_call(
    plugin_id: str,
    tools: list[MCPToolDescriptor],
    target: str,
    extras: dict[str, Any] | None = None,
) -> tuple[MCPToolDescriptor, dict[str, Any]] | None:
    """Pick the first step of a bounded preview plan."""
    plan = preview_plan(plugin_id, tools, target, extras)
    return plan[0] if plan else None


def preview_plan(
    plugin_id: str,
    tools: list[MCPToolDescriptor],
    target: str,
    extras: dict[str, Any] | None = None,
) -> list[tuple[MCPToolDescriptor, dict[str, Any]]]:
    """Order safe reads so content and measurements come before metadata."""
    provided = {key: value for key, value in (extras or {}).items() if value not in ("", None)}
    matches: list[tuple[MCPToolDescriptor, dict[str, Any]]] = []
    for tool in goal_read_tools(plugin_id, tools):
        if "settings" in tool_roles(tool):
            continue
        arguments = arguments_for_selection(
            tool, target, {**bounded_scope_defaults(tool), **_account_defaults(tool), **provided}
        )
        if arguments is None:
            continue
        matches.append((tool, arguments))
    matches.sort(
        key=lambda item: (not _binds_query(item, target, provided),) + _preview_rank(item)
    )
    return matches[:3]


def _binds_query(
    item: tuple[MCPToolDescriptor, dict[str, Any]],
    target: str,
    supplied: dict[str, Any],
) -> bool:
    """Prefer a search only for an explicit query or a message listing."""
    tool, arguments = item
    bound = [key for key in arguments if key in _QUERY_KEYS and arguments.get(key) == target]
    if not bound:
        return False
    if tool_tokens(tool) & {"message", "messages", "thread", "threads"}:
        return True
    return any(key in supplied for key in bound)


def accepts_preview(
    tool: MCPToolDescriptor,
    payloads: list[dict[str, Any]],
    supplied: dict[str, Any] | None = None,
) -> bool:
    """A discovery response is not a content preview, even when it contains text."""
    if not any(has_reader_content(item) for item in payloads):
        return False
    roles = tool_roles(tool)
    if roles & {"content", "measurement", "activity"}:
        return True
    if tool_tokens(tool) & {"message", "messages", "thread", "threads"}:
        return True
    return "search" in roles and any(key in (supplied or {}) for key in _QUERY_KEYS)


def _preview_rank(
    item: tuple[MCPToolDescriptor, dict[str, Any]],
) -> tuple[bool, bool, bool, bool, bool, bool, int, str]:
    tool = item[0]
    roles = tool_roles(tool)
    tokens = tool_tokens(tool)
    required = required_argument_names(tool.input_schema)
    strong_content = bool(tokens & {"markdown", "plaintext", "readme"})
    return (
        "settings" in roles,
        "metadata" in roles and "content" not in roles,
        "content" not in roles and "measurement" not in roles,
        not strong_content,
        read_kind(tool) == "search",
        not any(name in _SCOPE_KEYS for name in required),
        len(schema_properties(tool.input_schema)),
        tool.name,
    )


def arguments_for_selection(
    tool: MCPToolDescriptor, target: str, extras: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Bind one explicit resource/query to one schema-declared required input."""
    properties = schema_properties(tool.input_schema)
    required = required_argument_names(tool.input_schema)
    provided = {key: value for key, value in (extras or {}).items() if value not in ("", None)}
    if any(key not in properties for key in provided):
        return None
    binding = [
        key
        for key in required
        if key in _RESOURCE_KEYS | _QUERY_KEYS and key not in provided
    ]
    if not binding:
        optional = [
            key for key in properties if key in _RESOURCE_KEYS | _QUERY_KEYS and key not in provided
        ]
        if len(optional) == 1:
            binding = optional
    paired = _paired_arguments(binding, target) if len(binding) > 1 else None
    if paired is not None:
        binding = []
    elif len(binding) > 1 or any(key not in properties for key in required):
        return None
    defaults = {**formatted_value_defaults(tool), **_account_defaults(tool)}
    if paired is not None:
        if any(
            name not in provided and name not in paired and name not in _PAGE_KEYS | _SCOPE_KEYS
            for name in required
        ):
            return None
        if any(properties.get(key, {}).get("type") not in (None, "string") for key in paired):
            return None
        return {**defaults, **provided, **paired}
    if not binding:
        if not all(key in provided for key in required):
            return None
        return {**defaults, **provided}
    key = binding[0]
    if not target or len(target) > 500 or properties[key].get("type") not in (None, "string"):
        return None
    if any(name not in provided and name != key and name not in _PAGE_KEYS for name in required):
        return None
    return {**defaults, **provided, key: target}


def _paired_arguments(keys: list[str], target: str) -> dict[str, str] | None:
    """Bind owner/name pairs when the selected resource is a single slash-separated id."""
    left = [key for key in keys if key in _OWNER_KEYS]
    right = [key for key in keys if key in _NAME_KEYS]
    if len(left) != 1 or len(right) != 1 or target.count("/") != 1:
        return None
    owner, name = target.split("/", 1)
    if not owner or not name:
        return None
    return {left[0]: owner, right[0]: name}


def _account_defaults(tool: MCPToolDescriptor) -> dict[str, str]:
    spec = schema_properties(tool.input_schema).get("user_id")
    if not isinstance(spec, dict):
        return {}
    default = spec.get("default")
    if isinstance(default, str) and default.strip():
        return {"user_id": default.strip()}
    description = str(spec.get("description") or "")
    if re.search(r"\bme\b", description, re.IGNORECASE):
        return {"user_id": "me"}
    return {}


def access_model(plugin_id: str, tools: list[MCPToolDescriptor]) -> dict[str, Any]:
    """Which source shapes a connection can offer without reading private content."""
    models: list[str] = []
    discovered = discovery_tool(plugin_id, tools)
    if discovered is not None:
        models.append("resource")
    query_tool = _query_tool(plugin_id, tools)
    query_argument = ""
    query_label = "Search"
    if query_tool is not None and (discovered is None or _inbox_listing(query_tool)):
        models.append("query")
        query_argument = next(
            key for key in schema_properties(query_tool.input_schema) if key in _QUERY_KEYS
        )
        spec = schema_properties(query_tool.input_schema).get(query_argument) or {}
        description = str(spec.get("description") or "").strip()
        if description:
            query_label = description.split(".")[0][:80]
    if not models:
        models.append("unsupported")
    return {"models": models, "query_argument": query_argument, "query_label": query_label}


def _query_tool(plugin_id: str, tools: list[MCPToolDescriptor]) -> MCPToolDescriptor | None:
    candidates = [
        tool
        for tool in tools
        if safe_read_tool(plugin_id, tool)
        and is_catalog_read(tool)
        and "settings" not in tool_roles(tool)
        and any(key in _QUERY_KEYS for key in schema_properties(tool.input_schema))
        and _query_is_bindable(tool)
    ]
    candidates.sort(key=lambda tool: (not _inbox_listing(tool), tool.name))
    return candidates[0] if candidates else None


def _query_is_bindable(tool: MCPToolDescriptor) -> bool:
    required = required_argument_names(tool.input_schema)
    return all(
        name in _QUERY_KEYS | _PAGE_KEYS | _TIME_KEYS | _SCOPE_KEYS or name == "user_id"
        for name in required
    )


def has_reader_content(payload: dict[str, Any]) -> bool:
    """Identifiers and timestamps alone are not a preview."""
    if not isinstance(payload, dict):
        return False
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and _readable_text(value):
            return True
    if isinstance(payload.get("values"), list) and any(
        cell not in (None, "", [], {}) for cell in payload["values"]
    ):
        return True
    events = payload.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and (
                _readable_text(str(event.get("summary") or ""))
                or isinstance(event.get("numeric_value"), (int, float))
            ):
                return True
    return False


def _readable_text(value: str) -> bool:
    text = value.strip()
    synthetic = re.match(
        r"^[a-z0-9_]+ (?:row|record|observation|resource)\b",
        text,
        re.IGNORECASE,
    )
    return (
        len(text) >= 2
        and not _ID_VALUE.match(text)
        and not synthetic
        and not _encoded_blob(text)
    )


def _encoded_blob(value: str) -> bool:
    compact = "".join(value.split())
    return len(compact) >= 40 and bool(re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact))


def content_follow_ups(
    plugin_id: str,
    tools: list[MCPToolDescriptor],
    origin: str,
    payloads: list[dict[str, Any]],
) -> list[tuple[MCPToolDescriptor, dict[str, Any]]]:
    """Use identifiers from a metadata response to request one bounded content sample."""
    identifiers = _result_identifiers(payloads) or ([origin] if origin else [])
    if not identifiers:
        return []
    content_tools = [
        tool
        for tool in goal_read_tools(plugin_id, tools)
        if "content" in tool_roles(tool) or "activity" in tool_roles(tool)
    ]
    content_tools.sort(key=lambda tool: _preview_rank((tool, {})))
    for tool in content_tools:
        calls: list[tuple[MCPToolDescriptor, dict[str, Any]]] = []
        for identifier in identifiers[:3]:
            arguments = arguments_for_selection(
                tool,
                identifier,
                {**bounded_scope_defaults(tool), **_account_defaults(tool)},
            )
            if arguments is None:
                calls = []
                break
            calls.append((tool, arguments))
        if calls:
            return calls
    return []


def _result_identifiers(payloads: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for payload in payloads:
        for key in ("id", "message_id", "thread_id", "page_id", "document_id", "file_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip() and value not in found:
                found.append(value.strip())
    return found


def public_provider_error(error: BaseException) -> str:
    text = re.sub(r"\b[A-Z][A-Z0-9_]{6,}\b", "the provider", str(error))
    text = " ".join(text.split())[:240]
    lowered = text.lower()
    if any(word in lowered for word in ("permission", "unauthorized", "forbidden", "insufficient")):
        return "This account is not allowed to read that source."
    if any(word in lowered for word in ("required", "missing", "invalid")):
        return f"The read is missing a required input. {text}".strip()
    if not text:
        return "The provider could not return this source."
    return f"The provider could not return this source. {text}"


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
