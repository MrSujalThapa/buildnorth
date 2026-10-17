import pytest

from personal_markets.integrations.csv_import import (
    CsvColumnMapping,
    CsvImportRequest,
    parse_csv,
    preview_csv,
)
from personal_markets.integrations.github import _normalize_event
from personal_markets.integrations.plugins import (
    DirectIntegrationGateway,
    PluginStatus,
    ReadCapability,
    ReadCapabilityPolicy,
)


def test_csv_preview_and_mapping() -> None:
    raw = "date,score,note\n2026-01-01,0.97,physics\n2026-01-08,0.61,calc\n"
    preview = preview_csv(raw)
    assert preview.columns == ["date", "score", "note"]
    assert preview.row_count == 2
    records = parse_csv(
        raw,
        CsvImportRequest(
            mapping=CsvColumnMapping(metric="note", numeric_value="score", observed_at="date"),
            default_domain="academic",
        ),
    )
    assert records[0]["numeric_value"] == 0.97
    assert records[0]["source_type"] == "csv"


def test_malformed_csv_is_rejected() -> None:
    with pytest.raises(ValueError):
        preview_csv("")
    with pytest.raises(ValueError):
        parse_csv(
            "date,score\n2026-01-01,bad\n",
            CsvImportRequest(mapping=CsvColumnMapping(metric="date", numeric_value="score")),
        )


def test_github_events_are_activity_not_skill() -> None:
    record = _normalize_event(
        {
            "id": "1",
            "type": "PushEvent",
            "created_at": "2026-08-01T00:00:00Z",
            "repo": {"name": "user/repo"},
            "actor": {"login": "user"},
            "payload": {"commits": [{}, {}]},
        }
    )
    assert record["source_type"] == "github"
    assert record["commit_count"] == 2
    assert "skill" not in record


@pytest.mark.asyncio
async def test_plugin_catalog_reports_real_availability_without_fake_connections() -> None:
    views = await DirectIntegrationGateway().views()
    statuses = {item.definition.id: item.connection.status for item in views}
    assert statuses["github"] == PluginStatus.NOT_CONNECTED
    assert statuses["gmail"] == PluginStatus.UNAVAILABLE
    assert all(item.connection.connected_at is None for item in views)


def test_read_policy_rejects_write_capabilities() -> None:
    policy = ReadCapabilityPolicy()
    with pytest.raises(ValueError, match="capability denied"):
        policy.require_allowed(
            ReadCapability(id="send", label="Send email", operation="gmail.messages.send")
        )
