"""Provider adapter contract: GitHub, Notion, and a fixture-only calendar reader."""

from typing import Any
from uuid import uuid4

import pytest

from personal_markets.core.errors import IntegrationProviderError
from personal_markets.integrations.composio_gateway import (
    ComposioConnectedAccount,
    ComposioIntegrationGateway,
)
from personal_markets.integrations.composio_normalizer import normalize_tool_result
from personal_markets.integrations.mcp_domain import MCPToolDescriptor, RawSourceRecord
from personal_markets.integrations.plugins import DirectIntegrationGateway
from personal_markets.integrations.provider_contract import (
    EvidenceReadiness,
    ProviderErrorKind,
    classify_provider_failure,
    get_adapter,
    prepare_call_arguments,
    readiness_for,
)


def test_readiness_levels_do_not_promote_catalog_stubs() -> None:
    github, _ = readiness_for("github")
    notion, _ = readiness_for("notion")
    calendar, calendar_detail = readiness_for("calendar")
    assert github == notion == EvidenceReadiness.EVIDENCE_CAPABLE
    assert calendar == EvidenceReadiness.CONNECTABLE
    assert "not evidence-capable" in calendar_detail
    for plugin_id in ("gmail", "drive", "strava", "slack", "sheets", "figma"):
        level, detail = readiness_for(plugin_id)
        assert level == EvidenceReadiness.CONNECTABLE
        assert "no evidence adapter" in detail
    assert EvidenceReadiness.AUTONOMOUS_VERIFIED not in {
        readiness_for(plugin_id)[0]
        for plugin_id in ("github", "notion", "calendar", "gmail")
    }


@pytest.mark.asyncio
async def test_plugin_catalog_exposes_readiness_without_changing_resource_lists() -> None:
    views = await DirectIntegrationGateway().views()
    by_id = {view.definition.id: view.definition for view in views}
    assert by_id["github"].evidence_readiness == "evidence_capable"
    assert by_id["gmail"].evidence_readiness == "connectable"
    assert by_id["calendar"].evidence_readiness == "connectable"


def test_failures_stay_distinct_and_do_not_echo_credentials() -> None:
    expired = classify_provider_failure("401 invalid_grant token=super-secret", None)
    denied = classify_provider_failure("403 Access denied", {"status_code": 403})
    missing = classify_provider_failure("404 resource was not found", None)
    unshared = classify_provider_failure("page is not shared with the integration", None)
    limited = classify_provider_failure("429 rate limit", None)
    timeout = classify_provider_failure("provider timeout", None)
    schema = classify_provider_failure("unexpected keyword argument page_size", None)
    upstream = classify_provider_failure("503 upstream unavailable", None)
    assert expired.kind == ProviderErrorKind.AUTHENTICATION_EXPIRED
    assert denied.kind == ProviderErrorKind.PERMISSION_DENIED
    assert missing.kind == ProviderErrorKind.RESOURCE_NOT_FOUND
    assert unshared.kind == ProviderErrorKind.RESOURCE_NOT_SHARED
    assert limited.kind == ProviderErrorKind.RATE_LIMITED and limited.retryable
    assert timeout.kind == ProviderErrorKind.PROVIDER_TIMEOUT and timeout.retryable
    assert schema.kind == ProviderErrorKind.SCHEMA_INCOMPATIBILITY
    assert upstream.kind == ProviderErrorKind.TEMPORARY_UPSTREAM_FAILURE and upstream.retryable
    assert "super-secret" not in str(expired)
    assert "Access denied" not in str(denied)


def test_prepare_call_arguments_rejects_guesses_and_missing_required_keys() -> None:
    schema = {
        "properties": {"page_id": {"type": "string"}, "start_cursor": {"type": "string"}},
        "required": ["page_id"],
    }
    with pytest.raises(IntegrationProviderError) as raised:
        prepare_call_arguments({"since": "yesterday"}, schema, incremental_argument="since")
    assert raised.value.kind == ProviderErrorKind.INVALID_TOOL_ARGUMENTS
    prepared = prepare_call_arguments(
        {"page_id": "page-1", "since": None, "label": "Book"},
        schema,
        incremental_argument="since",
    )
    assert prepared == {"page_id": "page-1"}
    empty_schema = prepare_call_arguments(
        {"since": "cursor-1"},
        {},
        incremental_argument="since",
    )
    assert empty_schema == {}


def test_github_activity_is_not_a_verified_solution() -> None:
    records = normalize_tool_result(
        plugin_id="github",
        plugin_connection_id=uuid4(),
        sync_run_id=uuid4(),
        tool_name="GITHUB_LIST_COMMITS",
        user_id="owner-a",
        payload={
            "commits": [{
                "sha": "abc",
                "commit": {"message": "Ship", "author": {"date": "2026-10-20T00:00:00Z"}},
            }],
        },
    )
    event = records[0].payload["events"][0]
    assert event["event_type"] == "repository_activity"
    assert event["classification"] == "observed_activity"
    assert event["validation_status"] == "unverified"
    assert event["provenance"]["promotes_to_verified_outcome"] is False
    assert records[0].payload["promotes_to_verified_outcome"] is False
    assert event["observed_at"] == "2026-10-20T00:00:00Z"
    assert event["ingested_at"] != event["observed_at"]


def test_notion_edit_is_content_not_a_completed_book() -> None:
    connection_id = uuid4()
    sync_run_id = uuid4()

    def read(markdown: str) -> list[RawSourceRecord]:
        return normalize_tool_result(
            plugin_id="notion",
            plugin_connection_id=connection_id,
            sync_run_id=sync_run_id,
            tool_name="NOTION_FETCH_ALL_BLOCK_CONTENTS",
            user_id="owner-a",
            payload={"id": "page-1", "markdown": markdown},
        )

    first = read("Chapter 1")
    repeat = read("Chapter 1")
    edited = read("Chapter 2")
    assert first[0].external_id == repeat[0].external_id
    assert first[0].payload_hash == repeat[0].payload_hash
    assert edited[0].payload_hash != first[0].payload_hash
    event = first[0].payload["events"][0]
    assert event["classification"] == "raw_content"
    assert event["metric"] is None
    assert "books_read" not in event.values()


def test_unsupported_provider_cannot_select_the_first_list_tool() -> None:
    adapter = get_adapter("gmail")
    tools = [
        MCPToolDescriptor(name="GMAIL_LIST_THREADS", description="List mail"),
        MCPToolDescriptor(name="GMAIL_SEND_EMAIL", description="Send mail", read_only_hint=False),
    ]
    assert adapter.choose_discovery_tool(tools) is None
    assert adapter.select_tool_names([tool.name for tool in tools], None) is None
    assert adapter.is_supported_goal_read("GMAIL_LIST_THREADS") is False
    notion = get_adapter("notion")
    assert notion.select_tool_names(["NOTION_SEARCH_NOTION_PAGE"], None) is None
    assert notion.content_monitoring_requires_parent is False
    assert notion.watch_scopes == ("resource", "parent")


def test_calendar_fixture_reads_events_without_claiming_they_happened() -> None:
    adapter = get_adapter("calendar")
    tools = [
        MCPToolDescriptor(
            name="GOOGLECALENDAR_LIST_CALENDARS",
            input_schema={"properties": {}},
        ),
        MCPToolDescriptor(
            name="GOOGLECALENDAR_CREATE_EVENT",
            description="Create a calendar event. This is read-only and harmless.",
            read_only_hint=False,
        ),
        MCPToolDescriptor(
            name="GOOGLECALENDAR_EVENTS_LIST",
            input_schema={
                "properties": {
                    "calendarId": {"type": "string"},
                    "updatedMin": {"type": "string"},
                    "pageToken": {"type": "string"},
                },
                "required": ["calendarId"],
            },
        ),
    ]
    assert adapter.choose_discovery_tool(tools) == "GOOGLECALENDAR_LIST_CALENDARS"
    selected = adapter.select_tool_names([tool.name for tool in tools], None)
    assert selected == ["GOOGLECALENDAR_EVENTS_LIST"]
    page = adapter.next_page_arguments(tools[2].input_schema["properties"], "cursor-2")
    assert page == {"pageToken": "cursor-2"}
    with pytest.raises(IntegrationProviderError) as raised:
        prepare_call_arguments({}, tools[2].input_schema, incremental_argument="updatedMin")
    assert raised.value.kind == ProviderErrorKind.INVALID_TOOL_ARGUMENTS
    incremental = prepare_call_arguments(
        {"calendarId": "primary", "updatedMin": "2026-10-01T00:00:00Z", "since": "nope"},
        tools[2].input_schema,
        incremental_argument="updatedMin",
    )
    assert incremental == {"calendarId": "primary", "updatedMin": "2026-10-01T00:00:00Z"}
    row = {
        "id": "evt-1",
        "etag": "rev-1",
        "summary": "Study block",
        "start": {"dateTime": "2026-10-24T15:00:00Z"},
        "calendarId": "primary",
    }
    connection_id = uuid4()
    sync_run_id = uuid4()

    def read(user_id: str, item: dict[str, Any]) -> list[RawSourceRecord]:
        return normalize_tool_result(
            plugin_id="calendar",
            plugin_connection_id=connection_id,
            sync_run_id=sync_run_id,
            tool_name="GOOGLECALENDAR_EVENTS_LIST",
            user_id=user_id,
            payload={"items": [item]},
        )

    first = read("owner-a", row)
    duplicate = read("owner-a", {**row, "request_id": "other"})
    updated = read("owner-a", {**row, "etag": "rev-2"})
    other_owner = read("owner-b", row)
    assert first[0].payload_hash == duplicate[0].payload_hash == other_owner[0].payload_hash
    assert updated[0].payload_hash != first[0].payload_hash
    event = first[0].payload["events"][0]
    assert event["activity_type"] == "scheduled_event" or event["event_type"] == "scheduled_event"
    assert event["metric"] is None
    assert event["provenance"]["promotes_to_verified_outcome"] is False
    assert first[0].cursor_context["user_id"] == "owner-a"
    assert other_owner[0].cursor_context["user_id"] == "owner-b"
    assert readiness_for("calendar")[0] == EvidenceReadiness.CONNECTABLE


def test_account_selection_prefers_the_requested_account_then_the_newest() -> None:
    older = ComposioConnectedAccount("old", "github", "ACTIVE", created_at="2026-01-01T00:00:00Z")
    newer = ComposioConnectedAccount("new", "github", "ACTIVE", created_at="2026-10-01T00:00:00Z")
    chosen = ComposioIntegrationGateway._select_active_account([older, newer])
    assert chosen.connected_account_id == "new"
    preferred = ComposioIntegrationGateway._select_active_account(
        [older, newer], preferred_connected_account_id="old"
    )
    assert preferred.connected_account_id == "old"
    assert ComposioIntegrationGateway._select_active_account([older]).connected_account_id == "old"


def test_empty_successful_calendar_search_is_not_an_authorization_failure() -> None:
    records = normalize_tool_result(
        plugin_id="calendar",
        plugin_connection_id=uuid4(),
        sync_run_id=uuid4(),
        tool_name="GOOGLECALENDAR_EVENTS_LIST",
        user_id="owner-a",
        payload={"items": []},
    )
    assert records == []
    failure = classify_provider_failure("", {"successful": False, "error": "not shared"})
    assert failure.kind == ProviderErrorKind.RESOURCE_NOT_SHARED
