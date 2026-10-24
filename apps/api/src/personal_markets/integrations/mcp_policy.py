from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from personal_markets.integrations.mcp_domain import MCPToolDescriptor
from personal_markets.integrations.plugins import ReadCapability, ReadCapabilityPolicy

_WRITE_PATTERN = re.compile(
    r"\b("
    r"send|create|update|delete|remove|post|publish|write|edit|modify|"
    r"insert|upsert|patch|put|destroy|archive|invite|assign|close|merge|"
    r"comment|reply|react|upload|share|grant|revoke|subscribe|unsubscribe"
    r")\b",
    re.I,
)
_WRITE_TOKENS = frozenset({
    "send", "create", "update", "delete", "remove", "post", "publish", "write",
    "edit", "modify", "insert", "upsert", "patch", "put", "destroy", "archive",
    "invite", "assign", "close", "merge", "comment", "reply", "react",
    "upload", "share", "grant", "revoke", "subscribe", "unsubscribe",
})


class DiscoveredCapability(BaseModel):
    capability_id: str
    label: str
    operation: str
    tool_name: str | None = None
    resource_uri: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPReadPolicy:
    """Deterministic read-only enforcement; never trust provider hints alone."""

    def __init__(self, allowlist: ReadCapabilityPolicy | None = None) -> None:
        self._allowlist = allowlist or ReadCapabilityPolicy()

    def classify_tool(self, plugin_id: str, tool: MCPToolDescriptor) -> DiscoveredCapability | None:
        name = tool.name.lower()
        description = tool.description.lower()
        blob = f"{name} {description}"
        name_tokens = set(re.split(r"[_\.\-]", name))
        if _WRITE_PATTERN.search(blob) or name_tokens & _WRITE_TOKENS:
            return None
        if tool.read_only_hint is False:
            return None
        if self.reject_malicious_description(tool):
            return None
        read_parts = re.split(r"[_\.\-]", name)
        read_tokens = {"list", "get", "read", "fetch", "search", "query", "retrieve", "find", "show", "describe"}
        looks_read = any(part in read_tokens for part in read_parts)
        allowed_prefixes = ("list_", "get_", "read_", "fetch_", "search_")
        if not looks_read and not (
            name.endswith((".read", "_read", "_list", "_get")) or name.startswith(allowed_prefixes)
        ):
            return None
        operation = f"{plugin_id}.dynamic.{name}.read"
        return DiscoveredCapability(
            capability_id=f"{plugin_id}-{name}",
            label=tool.name,
            operation=operation,
            tool_name=tool.name,
            input_schema=tool.input_schema,
        )

    def reject_malicious_description(self, tool: MCPToolDescriptor) -> bool:
        """Return True when description attempts to bypass policy."""
        blob = tool.description.lower()
        bypass_phrases = (
            "ignore previous",
            "this is read-only even though",
            "safe to execute",
            "does not mutate",
            "actually writes",
        )
        return any(phrase in blob for phrase in bypass_phrases)
