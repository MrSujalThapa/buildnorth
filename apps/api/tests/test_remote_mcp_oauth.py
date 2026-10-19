"""OAuth 2.1 + PKCE lifecycle for remote MCP connections."""

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from personal_markets.identity.testing import admin_principal, make_principal
from personal_markets.remote_mcp.store import digest, now_utc
from remote_mcp_support import MCP_URL, REDIRECT, McpHarness, pkce, register

LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


async def _request_id(harness: McpHarness, client_id: str, challenge: str, **kw: Any) -> str:
    started = await harness.start_authorization(client_id, challenge=challenge, **kw)
    assert started.status_code == 302, started.text
    return parse_qs(urlsplit(started.headers["location"]).query)["request"][0]


def _code(response: httpx.Response) -> str:
    code: str = parse_qs(urlsplit(response.json()["redirect_url"]).query)["code"][0]
    return code


async def test_full_flow_issues_user_bound_expiring_tokens() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        assert grant.access_token.startswith("pio_at_")
        assert grant.refresh_token.startswith("pio_rt_")
        store = harness.app.state.remote_mcp.authorization._store
        record = await store.get_token(digest(grant.access_token))
        assert record.user_id == harness.owner.user_id
        assert record.resource == MCP_URL
        assert record.expires_at - now_utc() <= timedelta(seconds=3601)
        # Only hashes are stored.
        assert grant.access_token not in str(store.__dict__)
        assert (await harness.rpc(grant.access_token, LIST)).status_code == 200


async def test_wrong_pkce_verifier_is_rejected() -> None:
    async with McpHarness() as harness:
        client_id = await harness.register_client()
        _, challenge = pkce()
        request_id = await _request_id(harness, client_id, challenge)
        code = _code(await harness.approve(request_id))
        response = await harness.exchange(client_id, code, "x" * 64)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


async def test_code_replay_fails_and_revokes_the_connection() -> None:
    async with McpHarness() as harness:
        client_id = await harness.register_client()
        verifier, challenge = pkce()
        code = _code(await harness.approve(await _request_id(harness, client_id, challenge)))
        first = await harness.exchange(client_id, code, verifier)
        assert first.status_code == 200
        replay = await harness.exchange(client_id, code, verifier)
        assert replay.status_code == 400
        token = first.json()["access_token"]
        assert (await harness.rpc(token, LIST)).status_code == 401


async def test_consent_request_cannot_be_decided_twice() -> None:
    async with McpHarness() as harness:
        client_id = await harness.register_client()
        _, challenge = pkce()
        request_id = await _request_id(harness, client_id, challenge)
        assert (await harness.approve(request_id)).status_code == 200
        assert (await harness.approve(request_id)).status_code == 404


async def test_expired_code_is_rejected() -> None:
    async with McpHarness() as harness:
        client_id = await harness.register_client()
        verifier, challenge = pkce()
        code = _code(await harness.approve(await _request_id(harness, client_id, challenge)))
        store = harness.app.state.remote_mcp.authorization._store
        stored = store.codes[digest(code)]
        store.codes[digest(code)] = stored.model_copy(
            update={"expires_at": now_utc() - timedelta(seconds=1)}
        )
        response = await harness.exchange(client_id, code, verifier)
    assert response.status_code == 400


async def test_expired_access_token_is_rejected() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        store = harness.app.state.remote_mcp.authorization._store
        key = digest(grant.access_token)
        store.tokens[key] = store.tokens[key].model_copy(
            update={"expires_at": now_utc() - timedelta(seconds=1)}
        )
        assert (await harness.rpc(grant.access_token, LIST)).status_code == 401


async def test_refresh_rotates_and_reuse_revokes_connection() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        refreshed = await harness.http.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": grant.refresh_token,
                "client_id": grant.client_id,
                "resource": MCP_URL,
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        new = refreshed.json()
        assert new["refresh_token"] != grant.refresh_token
        assert (await harness.rpc(new["access_token"], LIST)).status_code == 200
        reuse = await harness.http.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": grant.refresh_token,
                "client_id": grant.client_id,
            },
        )
        assert reuse.status_code == 400
        assert (await harness.rpc(new["access_token"], LIST)).status_code == 401


async def test_revocation_endpoint() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect()
        response = await harness.http.post(
            "/revoke", data={"token": grant.refresh_token, "client_id": grant.client_id}
        )
        assert response.status_code == 200
        assert (await harness.rpc(grant.access_token, LIST)).status_code == 401


async def test_user_revokes_connection_from_settings() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect(name="Grok")
        listed = (await harness.http.get("/api/v1/mcp/connections")).json()
        assert len(listed) == 1 and listed[0]["client_name"] == "Grok"
        assert listed[0]["status"] == "active"
        assert "pio_" not in str(listed)
        connection_id = listed[0]["connection_id"]
        revoked = await harness.http.delete(f"/api/v1/mcp/connections/{connection_id}")
        assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
        assert (await harness.rpc(grant.access_token, LIST)).status_code == 401
        refresh = await harness.http.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": grant.refresh_token,
                "client_id": grant.client_id,
            },
        )
        assert refresh.status_code == 400


async def test_user_can_only_narrow_requested_scopes() -> None:
    async with McpHarness() as harness:
        grant = await harness.connect(
            scope="goals:read evidence:write", granted=["goals:read", "inference:use"]
        )
    assert grant.scope == "goals:read"


async def test_denial_redirects_with_access_denied() -> None:
    async with McpHarness() as harness:
        client_id = await harness.register_client()
        _, challenge = pkce()
        request_id = await _request_id(harness, client_id, challenge)
        response = await harness.approve(request_id, approve=False)
    query = parse_qs(urlsplit(response.json()["redirect_url"]).query)
    assert query["error"] == ["access_denied"] and query["state"] == ["state-123"]
    assert "code" not in query


async def test_resource_must_be_this_server() -> None:
    async with McpHarness() as harness:
        client_id = await harness.register_client()
        _, challenge = pkce()
        response = await harness.start_authorization(
            client_id, challenge=challenge, resource="https://other.example/mcp"
        )
    location = response.headers.get("location", "")
    assert "invalid_target" in location or response.status_code == 400


async def test_unknown_scope_is_rejected() -> None:
    async with McpHarness() as harness:
        client_id = await harness.register_client()
        _, challenge = pkce()
        response = await harness.start_authorization(
            client_id, "goals:read admin:all", challenge=challenge
        )
    assert "invalid_scope" in response.headers.get("location", response.text)


async def test_uninvited_user_cannot_consent() -> None:
    async with McpHarness() as harness:
        outsider = register(make_principal("outsider", invited=False))
        client_id = await harness.register_client()
        _, challenge = pkce()
        request_id = await _request_id(harness, client_id, challenge)
        response = await harness.approve(request_id, outsider)
    assert response.status_code == 403


async def test_token_stops_working_when_invitation_is_withdrawn() -> None:
    async with McpHarness() as harness:
        member = register(make_principal("member", invited=True))
        grant = await harness.connect(member)
        assert (await harness.rpc(grant.access_token, LIST)).status_code == 200
        register(member.model_copy(update={"invited": False, "hosted_enabled": False}))
        assert (await harness.rpc(grant.access_token, LIST)).status_code == 401


@pytest.mark.parametrize(
    "uri",
    [
        "http://evil.example/callback",
        "javascript:alert(1)",
        "https://ok.example/cb#frag",
        "file:///etc/passwd",
    ],
)
async def test_unsafe_redirect_uris_are_refused(uri: str) -> None:
    async with McpHarness() as harness:
        response = await harness.http.post(
            "/register",
            json={"redirect_uris": [uri], "token_endpoint_auth_method": "none"},
        )
    assert response.status_code == 400


async def test_registration_is_rate_limited() -> None:
    async with McpHarness() as harness:
        statuses = []
        for _ in range(22):
            response = await harness.http.post(
                "/register",
                json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none"},
            )
            statuses.append(response.status_code)
    assert statuses[:20] == [201] * 20
    assert statuses[-1] == 400


async def test_admin_connections_are_their_own() -> None:
    async with McpHarness() as harness:
        admin = register(admin_principal())
        await harness.connect()
        response = await harness.http.get(
            "/api/v1/mcp/connections", headers=harness.user_headers(admin)
        )
    assert response.status_code == 200
    assert response.json() == []


async def test_other_users_connection_cannot_be_revoked() -> None:
    async with McpHarness() as harness:
        other = register(make_principal("other", invited=True))
        await harness.connect()
        connection_id = (await harness.http.get("/api/v1/mcp/connections")).json()[0][
            "connection_id"
        ]
        response = await harness.http.delete(
            f"/api/v1/mcp/connections/{connection_id}", headers=harness.user_headers(other)
        )
    assert response.status_code == 404


async def test_consent_view_never_claims_verified_client() -> None:
    async with McpHarness() as harness:
        client_id = await harness.register_client("Totally Official PlayItOut")
        _, challenge = pkce()
        request_id = await _request_id(harness, client_id, challenge)
        view = (await harness.http.get(f"/api/v1/mcp/authorization-requests/{request_id}")).json()
    assert view["verified_client"] is False
    assert view["redirect_host"] == "127.0.0.1:9999"
    assert any("not verified" in warning for warning in view["warnings"])
