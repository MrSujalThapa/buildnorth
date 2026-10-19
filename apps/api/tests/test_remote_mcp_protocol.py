"""Scenario A: protocol, discovery and transport security over real Streamable HTTP."""

import pytest

from remote_mcp_support import API, MCP_URL, McpHarness, structured

EXPECTED_TOOLS = {
    "list_goals",
    "get_goal",
    "get_forecast",
    "get_forecast_history",
    "get_evidence_summary",
    "get_observation_policy",
    "get_best_interventions",
    "submit_structured_evidence",
    "submit_observation",
    "simulate_intervention",
}


async def test_unauthenticated_request_gets_spec_challenge() -> None:
    async with McpHarness() as harness:
        response = await harness.rpc(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert f'resource_metadata="{API}/.well-known/oauth-protected-resource/mcp"' in challenge
    assert 'scope="goals:read evidence:write whatif:simulate"' in challenge


async def test_metadata_discovery() -> None:
    async with McpHarness() as harness:
        prm = (await harness.http.get("/.well-known/oauth-protected-resource/mcp")).json()
        asm = (await harness.http.get("/.well-known/oauth-authorization-server")).json()
    assert prm["resource"] == MCP_URL
    assert prm["authorization_servers"] == [f"{API}/"]
    assert set(prm["scopes_supported"]) == {
        "goals:read",
        "evidence:write",
        "whatif:simulate",
        "inference:use",
    }
    assert asm["issuer"] == f"{API}/"
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["registration_endpoint"].endswith("/register")
    assert asm["revocation_endpoint"].endswith("/revoke")
    assert "authorization_code" in asm["grant_types_supported"]


async def test_sdk_client_discovers_and_calls_tools() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        async with harness.client(grant.access_token) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == EXPECTED_TOOLS
            by_name = {tool.name: tool for tool in listed.tools}
            read = by_name["get_forecast"].annotations
            write = by_name["submit_structured_evidence"].annotations
            assert read is not None and read.read_only_hint is True
            assert write is not None and write.read_only_hint is False
            assert by_name["simulate_intervention"].output_schema is not None
            schema = by_name["submit_structured_evidence"].input_schema
            assert "idempotency_key" in schema["required"]
            result = await client.call_tool("list_goals", {})
    assert result.is_error is False
    body = structured(result)
    assert body["goals"] == [] and body["total"] == 0


async def test_legacy_initialize_handshake_is_served() -> None:
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
                    "capabilities": {},
                    "clientInfo": {"name": "raw", "version": "1"},
                },
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["serverInfo"]["name"] == "PlayItOut"
        assert "tools" in result["capabilities"]
        notified = await harness.rpc(
            grant.access_token, {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert notified.status_code == 202


async def test_invalid_argument_is_a_tool_error_not_transport_failure() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        result = await harness.call(grant.access_token, "get_goal", {"goal_id": "not-a-uuid"})
    assert result.is_error is True
    assert structured(result)["error"]["code"] == "invalid_argument"


async def test_schema_violation_is_rejected() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        result = await harness.call(grant.access_token, "list_goals", {"limit": 5000})
    assert result.is_error is True


async def test_unknown_method_is_json_rpc_error() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        response = await harness.rpc(
            grant.access_token, {"jsonrpc": "2.0", "id": 9, "method": "shell/exec"}
        )
    assert response.status_code in {200, 400, 404}
    assert "error" in response.json()


async def test_foreign_origin_is_rejected() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        response = await harness.rpc(
            grant.access_token,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Origin": "https://evil.example"},
        )
    assert response.status_code == 403


async def test_rebinding_host_is_rejected() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        response = await harness.rpc(
            grant.access_token,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Host": "attacker.example"},
        )
    assert response.status_code in {400, 421}


async def test_oversized_body_is_rejected() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        response = await harness.rpc(grant.access_token, b"{" + b" " * 70_000 + b"}")
    assert response.status_code == 413


async def test_missing_tool_scope_triggers_step_up_challenge() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect(scope="goals:read")
        response = await harness.rpc(
            grant.access_token,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "submit_observation", "arguments": {}},
            },
        )
    assert response.status_code == 403
    challenge = response.headers["www-authenticate"]
    assert 'error="insufficient_scope"' in challenge
    assert "evidence:write" in challenge and "inference:use" in challenge


@pytest.mark.parametrize("token", ["pio_at_forged", "garbage", "pio_rt_notaccess"])
async def test_invalid_tokens_are_rejected(token: str) -> None:
    async with McpHarness() as harness:
        response = await harness.rpc(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401


async def test_clerk_session_token_is_not_an_mcp_token() -> None:
    from personal_markets.core.config import get_settings
    from personal_markets.identity.testing import bearer_for

    async with McpHarness() as harness:
        session_jwt = bearer_for(harness.owner, get_settings().test_auth_secret or "")
        response = await harness.rpc(
            session_jwt, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
    assert response.status_code == 401


async def test_mcp_token_is_not_a_rest_credential() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        response = await harness.http.get(
            "/api/v1/goals", headers={"Authorization": f"Bearer {grant.access_token}"}
        )
    assert response.status_code == 401
