"""In-process harness that drives /mcp through the real SDK client and OAuth endpoints."""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import httpx2
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from helpers import isolated_app
from personal_markets.core.config import get_settings
from personal_markets.identity.domain import Principal
from personal_markets.identity.factory import get_identity_repository
from personal_markets.identity.testing import bearer_for

API = "http://127.0.0.1:8000"
MCP_URL = f"{API}/mcp"
REDIRECT = "http://127.0.0.1:9999/callback"
FULL_SCOPES = "goals:read evidence:write whatif:simulate"


@dataclass
class Grant:
    client_id: str
    access_token: str
    refresh_token: str
    scope: str


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def register(principal: Principal) -> Principal:
    repo = get_identity_repository()
    repo.users[principal.user_id] = principal
    repo.by_clerk[principal.clerk_user_id] = principal.user_id
    return principal


class McpHarness:
    def __init__(self, app: FastAPI | None = None, **app_kwargs: Any) -> None:
        self.app = app or isolated_app(**app_kwargs)
        self._lifespan: Any = None
        self.http: httpx.AsyncClient

    async def __aenter__(self) -> "McpHarness":
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url=API, timeout=30
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.http.aclose()
        await self._lifespan.__aexit__(*exc)

    @property
    def owner(self) -> Principal:
        principal: Principal = self.app.state.auth_bypass_principal
        return principal

    def user_headers(self, principal: Principal | None) -> dict[str, str]:
        if principal is None or principal.user_id == self.owner.user_id:
            return {}
        secret = get_settings().test_auth_secret
        assert secret
        return {"Authorization": f"Bearer {bearer_for(principal, secret)}"}

    async def register_client(self, name: str = "Test Agent") -> str:
        response = await self.http.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": name,
            },
        )
        assert response.status_code == 201, response.text
        client_id: str = response.json()["client_id"]
        return client_id

    async def start_authorization(
        self, client_id: str, scope: str = FULL_SCOPES, *, challenge: str, resource: str = MCP_URL
    ) -> httpx.Response:
        return await self.http.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "state-123",
                "scope": scope,
                "resource": resource,
            },
        )

    async def approve(
        self,
        request_id: str,
        principal: Principal | None = None,
        *,
        approve: bool = True,
        scopes: list[str] | None = None,
    ) -> httpx.Response:
        return await self.http.post(
            f"/api/v1/mcp/authorization-requests/{request_id}/decision",
            json={"approve": approve, "scopes": scopes},
            headers=self.user_headers(principal),
        )

    async def exchange(self, client_id: str, code: str, verifier: str) -> httpx.Response:
        return await self.http.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": MCP_URL,
            },
        )

    async def connect(
        self,
        principal: Principal | None = None,
        scope: str = FULL_SCOPES,
        *,
        granted: list[str] | None = None,
        name: str = "Test Agent",
    ) -> Grant:
        client_id = await self.register_client(name)
        verifier, challenge = pkce()
        started = await self.start_authorization(client_id, scope, challenge=challenge)
        assert started.status_code == 302, started.text
        query = parse_qs(urlsplit(started.headers["location"]).query)
        assert "request" in query, started.headers["location"]
        request_id = query["request"][0]
        decided = await self.approve(request_id, principal, scopes=granted)
        assert decided.status_code == 200, decided.text
        code = parse_qs(urlsplit(decided.json()["redirect_url"]).query)["code"][0]
        token = await self.exchange(client_id, code, verifier)
        assert token.status_code == 200, token.text
        body = token.json()
        return Grant(client_id, body["access_token"], body["refresh_token"], body["scope"])

    def client(self, token: str | None) -> Client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), headers=headers, timeout=30
        )
        return Client(streamable_http_client(MCP_URL, http_client=http))

    async def call(self, token: str, tool: str, arguments: dict[str, Any]) -> Any:
        async with self.client(token) as client:
            return await client.call_tool(tool, arguments)

    async def rpc(
        self, token: str | None, payload: Any, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        merged = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if token:
            merged["Authorization"] = f"Bearer {token}"
        merged.update(headers or {})
        body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        return await self.http.post("/mcp", content=body, headers=merged)


def structured(result: Any) -> dict[str, Any]:
    if result.structured_content is not None:
        return dict(result.structured_content)
    payload: dict[str, Any] = json.loads(result.content[0].text)
    return payload


async def create_audience_goal(harness: McpHarness, owner: Principal | None = None) -> str:
    from datetime import UTC, datetime, timedelta

    from personal_markets.agents.goal_mapping import proposal_to_contract
    from personal_markets.agents.model_planner import refine_architect_proposal
    from personal_markets.ports import GoalArchitectProposal

    proposal = refine_architect_proposal(
        GoalArchitectProposal.model_validate(
            {
                "ready_to_commit": True,
                "title": "Reach 10000 subscribers",
                "goal_type": "threshold",
                "success_metric": "subscribers",
                "success_operator": ">=",
                "success_target": "10000",
                "success_unit": "subscribers",
                "deadline": (datetime.now(UTC) + timedelta(days=365)).date().isoformat(),
                "primitive_kind": "growth",
                "state_dimensions": ["subscribers"],
                "current_state_known": {"subscribers": "1200"},
                "model_family_compatibility": "deadline_event_hazard",
            }
        )
    )
    goal = proposal_to_contract(proposal)
    goals = harness.app.state.agent_workflow._inner._deps.goals
    created = await goals.create_goal(goal, (owner or harness.owner).user_id)
    return str(created.goal_id)


async def create_hiring_goal(harness: McpHarness) -> str:
    response = await harness.http.post(
        "/api/v1/agent/threads",
        json={
            "kind": "create_goal",
            "intent": "I want to receive an SWE/FDE offer from one of my target companies by "
            "August 2027.",
        },
    )
    assert response.status_code == 200, response.text
    thread_id = response.json()["thread_id"]
    resumed = await harness.http.post(
        f"/api/v1/agent/threads/{thread_id}/resume", json={"confirmed": True}
    )
    assert resumed.status_code == 200, resumed.text
    return str(resumed.json()["goal"]["goal_id"])
