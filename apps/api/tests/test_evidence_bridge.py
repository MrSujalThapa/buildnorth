from datetime import UTC, datetime
from uuid import uuid4

from personal_markets.integrations.evidence_bridge import raw_records_to_proposals
from personal_markets.integrations.mcp_domain import RawSourceRecord


def test_raw_record_expands_nested_events() -> None:
    record = RawSourceRecord(
        id=uuid4(),
        plugin_connection_id=uuid4(),
        external_id="evt-1",
        tool_identity="notion.pages.selected.read",
        retrieved_at=datetime.now(UTC),
        payload={
            "events": [
                {
                    "event_type": "interview",
                    "domain": "career",
                    "metric": "phone_screen_result",
                    "categorical_value": "unsuccessful",
                    "summary": "Meta phone screen unsuccessful",
                },
                {
                    "event_type": "practice",
                    "domain": "software",
                    "metric": "leetcode_hours",
                    "numeric_value": 3,
                    "unit": "hours",
                    "summary": "Studied LeetCode for 3 hours",
                },
            ]
        },
        payload_hash="abc",
        sync_run_id=uuid4(),
    )
    proposals = raw_records_to_proposals([record])
    assert len(proposals) == 2
    assert proposals[0].source_type == "mcp_sync"
    assert proposals[1].numeric_value == 3.0
