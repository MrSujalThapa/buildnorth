"""Provider adapters sit between Composio execution and PlayItOut evidence semantics.

OAuth, recipes, watches, and forecast publication stay in the existing services.
An adapter only says which tools are meaningful and how a payload becomes an
observation. Unknown providers stay connectable and fail closed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from personal_markets.core.errors import IntegrationProviderError
from personal_markets.integrations.mcp_domain import MCPToolDescriptor, SyncRecipeStep


class EvidenceReadiness(StrEnum):
    CONNECTABLE = "connectable"
    EVIDENCE_CAPABLE = "evidence_capable"
    AUTONOMOUS_VERIFIED = "autonomous_verified"


class ProviderErrorKind(StrEnum):
    AUTHENTICATION_EXPIRED = "authentication_expired"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_NOT_SHARED = "resource_not_shared"
    RESOURCE_NOT_FOUND = "resource_not_found"
    EMPTY_RESULT = "empty_result"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INVALID_TOOL_ARGUMENTS = "invalid_tool_arguments"
    RATE_LIMITED = "rate_limited"
    PROVIDER_TIMEOUT = "provider_timeout"
    TEMPORARY_UPSTREAM_FAILURE = "temporary_upstream_failure"
    SCHEMA_INCOMPATIBILITY = "schema_incompatibility"


def schema_body(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    parameters = schema.get("parameters")
    if isinstance(parameters, dict):
        return parameters
    return schema


def schema_properties(schema: dict[str, Any] | None) -> dict[str, Any]:
    properties = schema_body(schema).get("properties") or {}
    return properties if isinstance(properties, dict) else {}


def required_argument_names(schema: dict[str, Any] | None) -> list[str]:
    required = schema_body(schema).get("required") or []
    if not isinstance(required, list):
        return []
    return [str(item) for item in required]


def classify_provider_failure(
    message: str,
    payload: dict[str, Any] | None = None,
) -> IntegrationProviderError:
    """Map a provider failure to a safe, typed error. Raw payloads are not returned."""
    status = 0
    blob = (message or "").lower()
    if isinstance(payload, dict):
        try:
            status = int(payload.get("status_code") or 0)
        except (TypeError, ValueError):
            status = 0
        blob = f"{blob} {payload.get('error') or ''} {payload.get('message') or ''}".lower()
    if (
        status == 401
        or "unauthorized" in blob
        or "token expired" in blob
        or "invalid_grant" in blob
    ):
        return IntegrationProviderError(
            ProviderErrorKind.AUTHENTICATION_EXPIRED,
            "Reconnect this account. The provider session is no longer valid.",
            retryable=False,
        )
    if "not shared" in blob or "hasn't been shared" in blob or "has not been shared" in blob:
        return IntegrationProviderError(
            ProviderErrorKind.RESOURCE_NOT_SHARED,
            "This resource is not shared with the connected account.",
            retryable=False,
        )
    if status == 403 or "permission" in blob or "forbidden" in blob or "access denied" in blob:
        return IntegrationProviderError(
            ProviderErrorKind.PERMISSION_DENIED,
            "The connected account is not allowed to read this resource.",
            retryable=False,
        )
    if status == 404 or "not found" in blob:
        return IntegrationProviderError(
            ProviderErrorKind.RESOURCE_NOT_FOUND,
            "The provider could not find that resource.",
            retryable=False,
        )
    if status == 429 or "rate limit" in blob or "too many requests" in blob:
        return IntegrationProviderError(
            ProviderErrorKind.RATE_LIMITED,
            "The provider rate limit was reached. Try again later.",
            retryable=True,
        )
    if status == 408 or "timeout" in blob or "timed out" in blob:
        return IntegrationProviderError(
            ProviderErrorKind.PROVIDER_TIMEOUT,
            "The provider timed out. Try again later.",
            retryable=True,
        )
    if "schema" in blob or "unexpected keyword" in blob or "invalid argument" in blob:
        return IntegrationProviderError(
            ProviderErrorKind.SCHEMA_INCOMPATIBILITY,
            "The saved read does not match the provider tool schema. Select the source again.",
            retryable=False,
        )
    if status == 400:
        return IntegrationProviderError(
            ProviderErrorKind.INVALID_TOOL_ARGUMENTS,
            "The provider rejected the read arguments. Select the source again.",
            retryable=False,
        )
    if status >= 500:
        return IntegrationProviderError(
            ProviderErrorKind.TEMPORARY_UPSTREAM_FAILURE,
            "The provider is temporarily unavailable.",
            retryable=True,
        )
    return IntegrationProviderError(
        ProviderErrorKind.TEMPORARY_UPSTREAM_FAILURE,
        "The provider read failed.",
        retryable=True,
    )


def payload_indicates_failure(payload: dict[str, Any]) -> bool:
    if int(payload.get("status_code") or 0) >= 400:
        return True
    if payload.get("successful") is False or payload.get("success") is False:
        return True
    if payload.get("isError") is True:
        return True
    return bool(payload.get("error")) and not payload.get("results")


def prepare_call_arguments(
    arguments: dict[str, Any],
    schema: dict[str, Any] | None,
    *,
    incremental_argument: str | None,
) -> dict[str, Any]:
    """Keep only arguments the live schema declares. Do not invent keys."""
    properties = schema_properties(schema)
    cleaned = {
        key: value
        for key, value in arguments.items()
        if key not in {"resource_id", "label"} and value is not None
    }
    if properties:
        cleaned = {key: value for key, value in cleaned.items() if key in properties}
        if incremental_argument and incremental_argument not in properties:
            cleaned.pop(incremental_argument, None)
            cleaned.pop("since", None)
    else:
        cleaned.pop("since", None)
        if incremental_argument:
            cleaned.pop(incremental_argument, None)
    missing = [
        name
        for name in required_argument_names(schema)
        if name not in cleaned or cleaned[name] in ("", None)
    ]
    if missing:
        raise IntegrationProviderError(
            ProviderErrorKind.INVALID_TOOL_ARGUMENTS,
            "The saved read is missing arguments required by the current tool schema.",
            retryable=False,
        )
    return cleaned


def _tool_is_read(tool: MCPToolDescriptor) -> bool:
    name = tool.name.lower()
    if tool.read_only_hint is False:
        return False
    write_tokens = ("create", "update", "delete", "send", "insert", "patch", "post")
    return not any(token in name for token in write_tokens)


class ProviderAdapter:
    plugin_id = ""
    readiness = EvidenceReadiness.CONNECTABLE
    readiness_detail = (
        "Composio can connect this app. PlayItOut has no evidence adapter for it."
    )
    discovery_tool: str | None = None
    incremental_argument: str | None = None
    supports_parent_watch = False
    content_monitoring_requires_parent = False
    watch_scopes: tuple[str, ...] = ("resource",)
    requires_resource = False

    def choose_discovery_tool(self, tools: list[MCPToolDescriptor]) -> str | None:
        return None

    def select_tool_names(
        self,
        tool_names: list[str],
        activity_types: list[str] | None,
    ) -> list[str] | None:
        """Return tool names to save, or None when no supported read exists."""
        return None

    def is_supported_goal_read(self, tool_name: str | None) -> bool:
        return False

    def next_page_arguments(
        self, properties: dict[str, Any], cursor: str
    ) -> dict[str, Any] | None:
        return None

    def include_untitled(self, title: str) -> bool:
        return bool(title)

    def fingerprint(
        self,
        tool_name: str,
        row: dict[str, Any],
        recipe_step: SyncRecipeStep | None,
    ) -> dict[str, Any] | None:
        return None

    def observations(
        self,
        tool_name: str,
        row: dict[str, Any],
        recipe_step: SyncRecipeStep | None,
    ) -> list[dict[str, Any]]:
        return []


def _observation(
    *,
    provider: str,
    tool_name: str,
    row: dict[str, Any],
    source_event_id: str,
    activity_type: str,
    classification: str,
    summary: str,
    observed_at: str = "",
    metric: str | None = None,
    numeric_value: float | None = None,
    unit: str | None = None,
    resource_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_type": activity_type,
        "domain": provider,
        "metric": metric,
        "numeric_value": numeric_value,
        "unit": unit,
        "categorical_value": classification,
        "observed_at": observed_at,
        "summary": summary,
        "provider": provider,
        "resource_id": resource_id,
        "source_event_id": source_event_id,
        "activity_type": activity_type,
        "classification": classification,
        "validation_status": "unverified",
        "ingested_at": datetime.now(UTC).isoformat(),
        "provenance": {
            "tool": tool_name,
            "promotes_to_verified_outcome": False,
            "raw_id": row.get("id") or row.get("sha"),
        },
    }


class GitHubAdapter(ProviderAdapter):
    plugin_id = "github"
    readiness = EvidenceReadiness.EVIDENCE_CAPABLE
    readiness_detail = (
        "Repository commits, pull requests, and issues can be read and deduplicated. "
        "A commit is activity, not proof a problem was solved. "
        "Scheduled detection of newly arriving commits is not acceptance-verified."
    )
    discovery_tool = "GITHUB_LIST_REPOSITORIES_FOR_THE_AUTHENTICATED_USER"
    incremental_argument = "since"
    requires_resource = True
    _activities = {
        "commits": ("GITHUB_LIST_COMMITS",),
        "pull_requests": ("GITHUB_GET_PULL_REQUESTS", "GITHUB_LIST_PULL_REQUESTS"),
        "issues": ("GITHUB_LIST_ISSUES_FOR_A_REPOSITORY", "GITHUB_LIST_REPOSITORY_ISSUES"),
    }

    def select_tool_names(
        self, tool_names: list[str], activity_types: list[str] | None
    ) -> list[str] | None:
        if not activity_types:
            return None
        selected: list[str] = []
        for activity in activity_types:
            candidates = self._activities.get(activity, ())
            match = next((name for name in candidates if name in tool_names), None)
            if match is None:
                return None
            selected.append(match)
        return selected

    def is_supported_goal_read(self, tool_name: str | None) -> bool:
        if not tool_name:
            return False
        return any(tool_name in names for names in self._activities.values())

    def fingerprint(
        self, tool_name: str, row: dict[str, Any], recipe_step: SyncRecipeStep | None
    ) -> dict[str, Any] | None:
        if row.get("sha"):
            return {"sha": row["sha"]}
        return None

    def observations(
        self, tool_name: str, row: dict[str, Any], recipe_step: SyncRecipeStep | None
    ) -> list[dict[str, Any]]:
        observed = ""
        commit = row.get("commit")
        message = row.get("message")
        if isinstance(commit, dict):
            message = commit.get("message") or message
            author = commit.get("author") or {}
            if isinstance(author, dict) and author.get("date"):
                observed = str(author["date"])
        if not observed:
            for key in ("updated_at", "created_at", "committed_date"):
                if row.get(key):
                    observed = str(row[key])
                    break
        lowered = tool_name.lower()
        if "commit" in lowered or "commit" in row or isinstance(commit, dict):
            return [
                _observation(
                    provider="github",
                    tool_name=tool_name,
                    row=row,
                    source_event_id=str(row.get("sha") or row.get("id") or "commit"),
                    activity_type="repository_activity",
                    classification="observed_activity",
                    summary=f"Commit: {str(message or row.get('sha') or 'activity')[:160]}",
                    observed_at=observed,
                    metric="commits_pushed",
                    numeric_value=1,
                    unit="count",
                    resource_id=str(row.get("repository") or row.get("repo") or "") or None,
                )
            ]
        is_issue = "issue" in lowered or "pull_request" in lowered
        if row.get("state") and row.get("title") and is_issue:
            is_pr = "pull_request" in lowered
            return [
                _observation(
                    provider="github",
                    tool_name=tool_name,
                    row=row,
                    source_event_id=str(row.get("id") or row.get("number") or "item"),
                    activity_type="pull_request_activity" if is_pr else "issue_activity",
                    classification="observed_activity",
                    summary=f"{'Pull request' if is_pr else 'Issue'}: {row.get('title')}",
                    observed_at=observed,
                    metric="pull_request_update" if is_pr else "issue_update",
                    resource_id=None,
                )
            ]
        return []


class NotionAdapter(ProviderAdapter):
    plugin_id = "notion"
    readiness = EvidenceReadiness.EVIDENCE_CAPABLE
    readiness_detail = (
        "Shared pages can be listed and their content monitored without a parent. "
        "Parent scope only discovers new child pages under an already shared page. "
        "A page edit is not proof a book was finished. "
        "Scheduled new-content acceptance is not verified."
    )
    discovery_tool = "NOTION_SEARCH_NOTION_PAGE"
    supports_parent_watch = True
    content_monitoring_requires_parent = False
    watch_scopes = ("resource", "parent")
    requires_resource = True
    _content_tools = (
        "NOTION_GET_PAGE_MARKDOWN",
        "NOTION_FETCH_ALL_BLOCK_CONTENTS",
        "NOTION_FETCH_BLOCK_CONTENTS",
    )

    def select_tool_names(
        self, tool_names: list[str], activity_types: list[str] | None
    ) -> list[str] | None:
        for name in self._content_tools:
            if name in tool_names:
                return [name]
        return None

    def is_supported_goal_read(self, tool_name: str | None) -> bool:
        return tool_name in self._content_tools

    def next_page_arguments(
        self, properties: dict[str, Any], cursor: str
    ) -> dict[str, Any] | None:
        if "start_cursor" not in properties:
            return None
        arguments: dict[str, Any] = {"start_cursor": cursor}
        if "page_size" in properties:
            arguments["page_size"] = 100
        return arguments

    def include_untitled(self, title: str) -> bool:
        from uuid import UUID

        if not title:
            return False
        try:
            UUID(title)
        except ValueError:
            return True
        return False

    def fingerprint(
        self, tool_name: str, row: dict[str, Any], recipe_step: SyncRecipeStep | None
    ) -> dict[str, Any] | None:
        if isinstance(row.get("markdown"), str):
            page_id = row.get("id") or (
                recipe_step.arguments.get("page_id") if recipe_step else None
            )
            return {"id": page_id, "markdown": row["markdown"]}
        return None

    def observations(
        self, tool_name: str, row: dict[str, Any], recipe_step: SyncRecipeStep | None
    ) -> list[dict[str, Any]]:
        if not isinstance(row.get("markdown"), str) and "paragraph" not in row:
            return []
        text = str(row.get("markdown") or row.get("paragraph") or "")
        return [
            _observation(
                provider="notion",
                tool_name=tool_name,
                row=row,
                source_event_id=str(row.get("id") or "page"),
                activity_type="document_content",
                classification="raw_content",
                summary=text[:160] or "Notion page content",
                observed_at=str(row.get("updated_at") or row.get("last_edited_time") or ""),
                metric=None,
                resource_id=str(row.get("id") or "") or None,
            )
        ]


_CALENDAR_DISCOVERY = (
    "GOOGLECALENDAR_LIST_CALENDARS",
    "GOOGLE_CALENDAR_LIST_CALENDARS",
)
_CALENDAR_EVENTS = (
    "GOOGLECALENDAR_EVENTS_LIST",
    "GOOGLECALENDAR_LIST_EVENTS",
    "GOOGLE_CALENDAR_LIST_EVENTS",
)


class CalendarAdapter(ProviderAdapter):
    """Read-only calendar contract. Not live-accepted, so readiness stays connectable."""

    plugin_id = "calendar"
    readiness = EvidenceReadiness.CONNECTABLE
    readiness_detail = (
        "Calendar event reads are implemented against mocked Composio schemas only. "
        "A scheduled event is not proof it occurred. "
        "This provider is not evidence-capable until an authorized account is acceptance-tested."
    )
    requires_resource = True
    incremental_argument = "updatedMin"

    def choose_discovery_tool(self, tools: list[MCPToolDescriptor]) -> str | None:
        names = {tool.name: tool for tool in tools if _tool_is_read(tool)}
        for name in _CALENDAR_DISCOVERY:
            if name in names:
                return name
        for tool in tools:
            upper = tool.name.upper()
            if (
                "CALENDAR" in upper
                and "LIST" in upper
                and "EVENT" not in upper
                and _tool_is_read(tool)
            ):
                return tool.name
        return None

    def select_tool_names(
        self, tool_names: list[str], activity_types: list[str] | None
    ) -> list[str] | None:
        for name in _CALENDAR_EVENTS:
            if name in tool_names:
                return [name]
        for name in tool_names:
            upper = name.upper()
            if "EVENT" in upper and "LIST" in upper and "CREATE" not in upper:
                return [name]
        return None

    def is_supported_goal_read(self, tool_name: str | None) -> bool:
        if not tool_name:
            return False
        return self.select_tool_names([tool_name], None) == [tool_name]

    def next_page_arguments(
        self, properties: dict[str, Any], cursor: str
    ) -> dict[str, Any] | None:
        for key in ("pageToken", "page_token", "start_cursor"):
            if key in properties:
                return {key: cursor}
        return None

    def fingerprint(
        self, tool_name: str, row: dict[str, Any], recipe_step: SyncRecipeStep | None
    ) -> dict[str, Any] | None:
        event_id = row.get("id")
        if not event_id:
            return None
        revision = row.get("etag") or row.get("updated") or row.get("updated_at")
        return {"id": event_id, "revision": revision}

    def observations(
        self, tool_name: str, row: dict[str, Any], recipe_step: SyncRecipeStep | None
    ) -> list[dict[str, Any]]:
        if not row.get("id"):
            return []
        start = row.get("start")
        observed = ""
        if isinstance(start, dict):
            observed = str(start.get("dateTime") or start.get("date") or "")
        elif row.get("start"):
            observed = str(row["start"])
        return [
            _observation(
                provider="calendar",
                tool_name=tool_name,
                row=row,
                source_event_id=str(row["id"]),
                activity_type="scheduled_event",
                classification="observed_activity",
                summary=f"Scheduled: {row.get('summary') or row.get('title') or row['id']}",
                observed_at=observed,
                metric=None,
                resource_id=str(row.get("calendarId") or row.get("calendar_id") or "") or None,
            )
        ]


class ConnectableAdapter(ProviderAdapter):
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id


_ADAPTERS: dict[str, ProviderAdapter] = {
    "github": GitHubAdapter(),
    "notion": NotionAdapter(),
    "calendar": CalendarAdapter(),
}


def get_adapter(plugin_id: str) -> ProviderAdapter:
    return _ADAPTERS.get(plugin_id) or ConnectableAdapter(plugin_id)


def readiness_for(plugin_id: str) -> tuple[str, str]:
    adapter = get_adapter(plugin_id)
    if plugin_id in {"manual", "csv"}:
        return EvidenceReadiness.CONNECTABLE.value, "In-app evidence, not a Composio provider."
    return adapter.readiness.value, adapter.readiness_detail


def adapter_for_tool_names(tool_names: list[str]) -> ProviderAdapter:
    if any(name.startswith("GITHUB_") for name in tool_names):
        return get_adapter("github")
    if any(name.startswith("NOTION_") for name in tool_names):
        return get_adapter("notion")
    if any("CALENDAR" in name.upper() for name in tool_names):
        return get_adapter("calendar")
    return ConnectableAdapter("unknown")
