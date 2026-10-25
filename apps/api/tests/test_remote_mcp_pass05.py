"""Pass 05 MCP capability tests: goal creation, as-of history, What If, files, charts."""

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from personal_markets.identity.testing import make_principal
from personal_markets.remote_mcp.charting import is_png
from personal_markets.remote_mcp.odds_app import (
    ODDS_UI_LEGACY_URI,
    ODDS_UI_MIME,
    ODDS_UI_URI,
    UI_EXTENSION_ID,
)
from remote_mcp_support import McpHarness, create_hiring_goal, register, structured

NOW = datetime.now(UTC)
CREATE_SCOPES = "goals:read goals:write evidence:write whatif:simulate inference:use"


def _evidence(goal_id: str, key: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "goal_id": goal_id,
        "metric": "applications",
        "value": 12,
        "unit": "count",
        "observation_kind": "snapshot",
        "observed_at": NOW.isoformat(),
        "idempotency_key": key,
        "source_category": "job_board",
    }
    payload.update(overrides)
    return payload


async def test_create_goal_clarifies_then_confirms_without_phantom() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect(scope=CREATE_SCOPES)
        first = structured(
            await harness.call(
                grant.access_token,
                "create_goal",
                {"intent": "I want to get rich.", "idempotency_key": "create-rich-01"},
            )
        )
        assert first["status"] == "needs_clarification"
        assert first["goal_id"] is None
        assert first["llm_used_for_probability"] is False
        listed = structured(await harness.call(grant.access_token, "list_goals", {}))
        assert listed["total"] == 0

        continued = structured(
            await harness.call(
                grant.access_token,
                "continue_goal_creation",
                {
                    "thread_id": first["thread_id"],
                    "answers": {
                        "rich_definition": "1000000 net worth",
                        "deadline": "2030-12-31",
                    },
                },
            )
        )
        assert continued["status"] == "needs_confirmation"
        assert continued["goal_id"] is None
        listed = structured(await harness.call(grant.access_token, "list_goals", {}))
        assert listed["total"] == 0

        created = structured(
            await harness.call(
                grant.access_token,
                "continue_goal_creation",
                {"thread_id": first["thread_id"], "confirmed": True},
            )
        )
        assert created["status"] == "created"
        assert created["goal_id"]
        assert created["llm_used_for_probability"] is False
        listed = structured(await harness.call(grant.access_token, "list_goals", {}))
        assert listed["total"] == 1


async def test_create_goal_idempotency_replays_thread() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect(scope=CREATE_SCOPES)
        payload = {
            "intent": "I want a software internship by May 2027.",
            "idempotency_key": "create-intern-01",
        }
        first = structured(await harness.call(grant.access_token, "create_goal", payload))
        second = structured(await harness.call(grant.access_token, "create_goal", payload))
        assert first["thread_id"] == second["thread_id"]
        assert second["status"] == "replayed"


async def test_create_goal_requires_write_and_inference_scopes() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        response = await harness.rpc(
            grant.access_token,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "create_goal", "arguments": {"intent": "internship by May"}},
            },
        )
    assert response.status_code == 403
    assert "goals:write" in response.headers["www-authenticate"]


async def test_compare_forecasts_uses_published_receipts_and_percentage_points() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        first = structured(
            await harness.call(
                grant.access_token,
                "submit_structured_evidence",
                _evidence(
                    goal_id,
                    "hist-0001",
                    value=8,
                    observed_at=(NOW - timedelta(days=10)).isoformat(),
                ),
            )
        )
        second = structured(
            await harness.call(
                grant.access_token,
                "submit_structured_evidence",
                _evidence(goal_id, "hist-0002", value=20),
            )
        )
        assert first["publication"]["priced"] and second["publication"]["priced"]
        compared = structured(
            await harness.call(
                grant.access_token,
                "compare_forecasts",
                {"goal_id": goal_id, "relative": "previous"},
            )
        )
        assert compared["status"] == "COMPARED"
        assert compared["delta_pp"] == pytest.approx(
            (compared["latest"]["probability"] - compared["as_of_point"]["probability"]) * 100
        )
        missing = structured(
            await harness.call(
                grant.access_token,
                "compare_forecasts",
                {"goal_id": goal_id, "as_of": "2010-01-01T00:00:00Z"},
            )
        )
        assert missing["status"] == "NO_EARLIER_RECEIPT"
        since_start = structured(
            await harness.call(
                grant.access_token,
                "compare_forecasts",
                {"goal_id": goal_id, "relative": "since_start"},
            )
        )
        assert since_start["status"] == "COMPARED"
        assert since_start["delta_basis"] == "latest_minus_selected_receipt"
        assert since_start["as_of_point"]["published_at"] <= since_start["latest"]["published_at"]
        this_month = structured(
            await harness.call(
                grant.access_token,
                "compare_forecasts",
                {"goal_id": goal_id, "relative": "this_month"},
            )
        )
        assert this_month["status"] == "NO_EARLIER_RECEIPT"
        assert "invent" in this_month["message"].lower()
        move = structured(
            await harness.call(
                grant.access_token,
                "compare_forecasts",
                {"goal_id": goal_id, "relative": "largest_increase"},
            )
        )
        assert move["status"] in {"COMPARED", "NO_EARLIER_RECEIPT"}
        if move["status"] == "COMPARED":
            assert move["delta_basis"] == "largest_consecutive_published_step"
            assert move["extremum"]["direction"] == "increase"
            assert move["extremum"]["delta_pp"] == pytest.approx(move["delta_pp"])
        readiness = structured(
            await harness.call(
                grant.access_token, "get_forecast_readiness", {"goal_id": goal_id}
            )
        )
        assert readiness["priced"] is True
        assert readiness["publication_status"] == "PUBLISHED"
        assert readiness["probability"] == pytest.approx(compared["latest"]["probability"])
        milestones = structured(
            await harness.call(grant.access_token, "list_milestones", {"goal_id": goal_id})
        )
        assert isinstance(milestones["milestones"], list)
        assert "submit_structured_evidence" in milestones["message"]


async def test_compare_scenarios_does_not_write_history() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        await harness.call(
            grant.access_token, "submit_structured_evidence", _evidence(goal_id, "scen-0001")
        )
        before = structured(
            await harness.call(grant.access_token, "get_forecast_history", {"goal_id": goal_id})
        )
        result = structured(
            await harness.call(
                grant.access_token,
                "compare_scenarios",
                {
                    "goal_id": goal_id,
                    "scenarios": [
                        {
                            "label": "apply 20 more",
                            "changes": [
                                {
                                    "metric": "applications",
                                    "operation": "add",
                                    "value": 20,
                                    "unit": "count",
                                }
                            ],
                        }
                    ],
                },
            )
        )
        assert result["hypothetical"] is True
        assert result["writes_published_history"] is False
        after = structured(
            await harness.call(grant.access_token, "get_forecast_history", {"goal_id": goal_id})
        )
        assert after["total"] == before["total"]
        exam = structured(
            await harness.call(
                grant.access_token,
                "compare_scenarios",
                {
                    "goal_id": goal_id,
                    "scenarios": [
                        {
                            "label": "unmapped exam",
                            "changes": [
                                {
                                    "metric": "final_exam_score",
                                    "operation": "set",
                                    "value": 80,
                                    "unit": "percent",
                                }
                            ],
                        }
                    ],
                    "weighted": {
                        "components": [
                            {"label": "midterm", "score": 50, "weight": 30, "known": True},
                            {"label": "final", "weight": 70, "known": False},
                        ]
                    },
                },
            )
        )
        assert exam["weighted_score"]["status"] == "needs_clarification"
        first_scenario = exam["scenarios"][0]
        assert first_scenario["priced"] is False or first_scenario["status"] == "NOT_PRICED"


async def test_structured_rows_and_table_text_are_idempotent() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        rows = {
            "goal_id": goal_id,
            "idempotency_key": "rows-0001",
            "source_category": "spreadsheet",
            "rows": [
                {
                    "metric": "applications",
                    "value": 4,
                    "unit": "count",
                    "observation_kind": "increment",
                    "observed_at": NOW.isoformat(),
                }
            ],
        }
        first = structured(await harness.call(grant.access_token, "submit_structured_rows", rows))
        second = structured(await harness.call(grant.access_token, "submit_structured_rows", rows))
        assert first["status"] == "committed"
        assert second["status"] == "replayed"
        assert first["evidence"][0]["evidence_id"] == second["evidence"][0]["evidence_id"]

        table = {
            "goal_id": goal_id,
            "filename": "apps.csv",
            "text": "date,apps\n2026-10-01,15\n",
            "mapping": {
                "metric": "applications",
                "value_column": "apps",
                "observed_at_column": "date",
                "unit": "count",
                "observation_kind": "snapshot",
            },
            "idempotency_key": "table-0001",
            "source_category": "csv",
        }
        imported = structured(await harness.call(grant.access_token, "submit_table_text", table))
        replayed = structured(await harness.call(grant.access_token, "submit_table_text", table))
        assert imported["status"] == "committed"
        assert replayed["status"] == "replayed"


async def test_file_over_limit_is_rejected_without_url_fetch() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        # 40,001 decoded bytes is over the 40 KB product limit while remaining
        # under the 56k-char schema cap and 64 KB JSON request cap.
        huge = base64.b64encode(b"\x00" * 40_001).decode("ascii")
        result = await harness.call(
            grant.access_token,
            "submit_file_bytes",
            {
                "goal_id": goal_id,
                "filename": "too-big.csv",
                "content_base64": huge,
                "mapping": {"metric": "applications", "value_column": "apps", "unit": "count"},
                "idempotency_key": "file-too-big",
                "source_category": "email",
            },
        )
        body = structured(result)
        assert result.is_error is True
        assert body["error"]["code"] == "invalid_argument"
        assert "Gmail" in body["error"]["message"] or "64" in body["error"]["message"]


async def test_chart_tools_resource_and_static_png() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        await harness.call(
            grant.access_token, "submit_structured_evidence", _evidence(goal_id, "chart-0001")
        )
        async with harness.client(grant.access_token) as client:
            listed = await client.list_tools()
            chart = next(item for item in listed.tools if item.name == "show_odds_chart")
            meta = chart.meta or {}
            assert meta.get("ui", {}).get("resourceUri") == ODDS_UI_URI
            assert meta.get("ui/resourceUri") == ODDS_UI_URI
            resources = await client.list_resources()
            listed_resources = {str(item.uri): item for item in resources.resources}
            assert ODDS_UI_URI in listed_resources
            assert ODDS_UI_LEGACY_URI in listed_resources
            listed_mime = getattr(listed_resources[ODDS_UI_URI], "mimeType", None) or getattr(
                listed_resources[ODDS_UI_URI], "mime_type", None
            )
            assert listed_mime == ODDS_UI_MIME
            resource = await client.read_resource(ODDS_UI_URI)
            first = resource.contents[0]
            text = getattr(first, "text", None)
            assert isinstance(text, str)
            assert "PlayItOut Odds Explorer" in text
            assert "ui/initialize" in text
            assert "appInfo" in text
            assert "ui/notifications/tool-result" in text
            assert "ui/notifications/initialized" in text
            assert "pio_at_" not in text
            assert "Bearer" not in text
            mime = getattr(first, "mimeType", None) or getattr(first, "mime_type", None)
            assert mime == ODDS_UI_MIME
            content_meta = getattr(first, "meta", None) or {}
            assert content_meta.get("ui", {}).get("csp", {}).get("connectDomains") == []

        view = structured(
            await harness.call(
                grant.access_token, "show_odds_chart", {"goal_id": goal_id, "range": "ALL"}
            )
        )
        assert view["status"] == "PUBLISHED"
        assert view["points"]
        assert view["ui_resource"] == ODDS_UI_URI
        result = await harness.call(
            grant.access_token, "show_odds_chart", {"goal_id": goal_id, "range": "ALL"}
        )
        assert result.structured_content is not None
        assert result.structured_content["points"] == view["points"]
        image = await harness.call(
            grant.access_token, "get_odds_chart_image", {"goal_id": goal_id, "range": "1D"}
        )
        assert image.is_error is False
        png_parts = [item for item in image.content if getattr(item, "type", None) == "image"]
        assert png_parts
        import base64

        raw = base64.b64decode(png_parts[0].data)
        assert is_png(raw)
        assert structured(image)["public_url"] is None
        assert structured(image)["static"] is True


async def test_mcp_apps_extension_is_advertised_on_initialize() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        response = await harness.rpc(
            grant.access_token,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"extensions": {UI_EXTENSION_ID: {}}},
                    "clientInfo": {"name": "apps-harness", "version": "1"},
                },
            },
        )
        assert response.status_code == 200, response.text
        capabilities = response.json()["result"]["capabilities"]
        advertised = {
            **(capabilities.get("experimental") or {}),
            **(capabilities.get("extensions") or {}),
        }
        assert UI_EXTENSION_ID in advertised
        assert isinstance(advertised[UI_EXTENSION_ID], dict)


async def test_chart_and_goal_are_owner_scoped() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        other = register(make_principal("other-pass05", invited=True, hosted=True))
        grant = await harness.connect(principal=other)
        missing = await harness.call(grant.access_token, "show_odds_chart", {"goal_id": goal_id})
        body = structured(missing)
        assert missing.is_error is True
        assert body["error"]["code"] == "not_found"
        writer = await harness.connect(principal=other, scope=CREATE_SCOPES)
        create = await harness.call(
            writer.access_token,
            "continue_goal_creation",
            {"thread_id": str(UUID(int=1)), "confirmed": True},
        )
        assert create.is_error is True
        assert structured(create)["error"]["code"] == "not_found"


async def test_revoked_token_cannot_read_chart_image() -> None:
    async with McpHarness() as harness:
        goal_id = await create_hiring_goal(harness)
        grant = await harness.connect()
        await harness.http.post(
            "/revoke", data={"token": grant.refresh_token, "client_id": grant.client_id}
        )
        response = await harness.rpc(
            grant.access_token,
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "get_odds_chart_image", "arguments": {"goal_id": goal_id}},
            },
        )
    assert response.status_code == 401
