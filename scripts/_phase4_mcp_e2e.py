"""Scenario G: an external MCP client against a running PlayItOut API over real HTTP.

The client uses the official SDK's OAuthClientProvider: protected-resource discovery,
authorization-server metadata, dynamic registration, PKCE S256 and the resource
parameter. The consent click is performed by the dev test identity through the same
consent API the web page calls. Tokens are never printed.

Usage (server must already be running):
  PM_E2E_API=http://127.0.0.1:8020 uv run python scripts/_phase4_mcp_e2e.py
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import anyio
import httpx
import httpx2
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from pydantic import AnyUrl

from personal_markets.identity.domain import user_id_for_clerk
from personal_markets.identity.tokens import issue_test_token

API = os.environ.get("PM_E2E_API", "http://127.0.0.1:8020").rstrip("/")
SECRET = os.environ["PM_TEST_AUTH_SECRET"]
CLERK_ID = os.environ.get("PM_E2E_USER", "mcp-e2e-user")
REDIRECT = "http://127.0.0.1:8765/callback"
OUT = Path(os.environ.get("PM_E2E_OUT", ".artifacts/phase4_mcp_e2e.json"))


class MemoryStorage:
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client = client_info


def user_headers() -> dict[str, str]:
    token = issue_test_token(
        secret=SECRET,
        clerk_user_id=CLERK_ID,
        email=f"{CLERK_ID}@example.test",
        email_verified=True,
    )
    return {"Authorization": f"Bearer {token}"}


async def seed_goal() -> str:
    """Fixture: one audience goal for the dev user, created without any model call."""
    from personal_markets.agents.goal_mapping import proposal_to_contract
    from personal_markets.agents.model_planner import refine_architect_proposal
    from personal_markets.core.config import get_settings
    from personal_markets.goals.service import GoalService
    from personal_markets.persistence.database import create_engine
    from personal_markets.persistence.repositories import PostgresGoalRepository
    from personal_markets.ports import GoalArchitectProposal

    async with httpx.AsyncClient(base_url=API, timeout=30) as http:
        me = await http.get("/api/v1/me", headers=user_headers())
        me.raise_for_status()
    proposal = refine_architect_proposal(
        GoalArchitectProposal.model_validate(
            {
                "ready_to_commit": True,
                "title": "Reach 10000 newsletter subscribers",
                "goal_type": "threshold",
                "success_metric": "subscribers",
                "success_operator": ">=",
                "success_target": "10000",
                "deadline": (datetime.now(UTC) + timedelta(days=365)).date().isoformat(),
                "primitive_kind": "growth",
                "state_dimensions": ["subscribers"],
                "current_state_known": {"subscribers": "1200"},
                "model_family_compatibility": "deadline_event_hazard",
            }
        )
    )
    engine = create_engine(get_settings().database_url or "")
    try:
        goal = await GoalService(PostgresGoalRepository(engine)).create_goal(
            proposal_to_contract(proposal), user_id_for_clerk(CLERK_ID)
        )
    finally:
        await engine.dispose()
    return str(goal.goal_id)


def summary(result: Any) -> dict[str, Any]:
    body = result.structured_content or json.loads(result.content[0].text)
    return {"is_error": result.is_error, "body": body}


async def main() -> int:
    transcript: dict[str, Any] = {"api": API, "started_at": datetime.now(UTC).isoformat()}
    goal_id = await seed_goal()
    transcript["seeded_goal_id"] = goal_id
    pending: dict[str, str] = {}
    consent_log: list[dict[str, Any]] = []

    async def redirect_handler(authorization_url: str) -> None:
        parts = urlsplit(authorization_url)
        query = parse_qs(parts.query)
        consent_log.append(
            {
                "authorize_endpoint": f"{parts.scheme}://{parts.netloc}{parts.path}",
                "code_challenge_method": query.get("code_challenge_method"),
                "resource": query.get("resource"),
                "scope": query.get("scope"),
            }
        )
        async with httpx.AsyncClient(timeout=30) as http:
            started = await http.get(authorization_url, follow_redirects=False)
            assert started.status_code == 302, started.text
            consent_url = started.headers["location"]
            request_id = parse_qs(urlsplit(consent_url).query)["request"][0]
            view = await http.get(
                f"{API}/api/v1/mcp/authorization-requests/{request_id}", headers=user_headers()
            )
            view.raise_for_status()
            consent_log.append({"consent_page": consent_url.split("?")[0], "view": view.json()})
            decision = await http.post(
                f"{API}/api/v1/mcp/authorization-requests/{request_id}/decision",
                json={"approve": True},
                headers=user_headers(),
            )
            decision.raise_for_status()
        redirect = parse_qs(urlsplit(decision.json()["redirect_url"]).query)
        pending["code"] = redirect["code"][0]
        pending["state"] = redirect.get("state", [""])[0]

    async def callback_handler() -> AuthorizationCodeResult:
        return AuthorizationCodeResult(code=pending["code"], state=pending["state"] or None)

    storage = MemoryStorage()
    provider = OAuthClientProvider(
        server_url=f"{API}/mcp",
        client_metadata=OAuthClientMetadata(
            client_name="PlayItOut Phase 4 external E2E client",
            redirect_uris=[AnyUrl(REDIRECT)],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
            scope="goals:read evidence:write whatif:simulate",
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    steps: list[dict[str, Any]] = []
    async with (
        httpx2.AsyncClient(auth=provider, timeout=60) as http,
        Client(streamable_http_client(f"{API}/mcp", http_client=http)) as client,
    ):
        tools = await client.list_tools()
        steps.append({"step": "tools/list", "tools": sorted(t.name for t in tools.tools)})
        listed = summary(await client.call_tool("list_goals", {}))
        steps.append({"step": "list_goals", **listed})
        policy = summary(await client.call_tool("get_observation_policy", {"goal_id": goal_id}))
        steps.append({"step": "get_observation_policy", **policy})
        now = datetime.now(UTC)
        for index, (days, value) in enumerate([(90, 800), (60, 950), (30, 1100), (0, 1200)]):
            args = {
                "goal_id": goal_id,
                "metric": "subscribers",
                "value": value,
                "unit": "subscribers",
                "observation_kind": "snapshot",
                "observed_at": (now - timedelta(days=days)).isoformat(),
                "idempotency_key": f"e2e-{goal_id[:8]}-{index}",
                "source_category": "newsletter_platform",
                "source_identifier": "e2e-fixture",
            }
            steps.append(
                {
                    "step": f"submit_structured_evidence[{index}]",
                    **summary(await client.call_tool("submit_structured_evidence", args)),
                }
            )
        retry = summary(await client.call_tool("submit_structured_evidence", args))
        steps.append({"step": "submit_structured_evidence[retry]", **retry})
        forecast = summary(await client.call_tool("get_forecast", {"goal_id": goal_id}))
        steps.append({"step": "get_forecast", **forecast})
        mapped = summary(
            await client.call_tool(
                "simulate_intervention",
                {
                    "goal_id": goal_id,
                    "changes": [
                        {
                            "metric": "primary.mu",
                            "operation": "set",
                            "value": 0.2,
                            "unit": "log/month",
                        }
                    ],
                },
            )
        )
        steps.append({"step": "simulate_intervention[mapped]", **mapped})
        unmapped = summary(
            await client.call_tool(
                "simulate_intervention",
                {
                    "goal_id": goal_id,
                    "changes": [
                        {
                            "metric": "videos_per_week",
                            "operation": "set",
                            "value": 2,
                            "unit": "videos/week",
                        }
                    ],
                },
            )
        )
        steps.append({"step": "simulate_intervention[unmapped]", **unmapped})
        after = summary(await client.call_tool("get_forecast", {"goal_id": goal_id}))
        steps.append({"step": "get_forecast[after_simulation]", **after})

    async with httpx.AsyncClient(base_url=API, timeout=30) as rest:
        rest_evidence = (
            await rest.get(f"/api/v1/goals/{goal_id}/evidence", headers=user_headers())
        ).json()
        connections = (await rest.get("/api/v1/mcp/connections", headers=user_headers())).json()
        client_id = storage.client.client_id if storage.client else None
        mine = [
            c for c in connections if c["client_id"] == client_id and c["status"] == "active"
        ]
        assert len(mine) == 1, f"expected one active E2E connection, found {len(mine)}"
        revoked = await rest.delete(
            f"/api/v1/mcp/connections/{mine[0]['connection_id']}", headers=user_headers()
        )
        token = storage.tokens.access_token if storage.tokens else ""
        after_revoke = await rest.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
        )
    checks = {
        "oauth_discovery_and_pkce": consent_log[0]["code_challenge_method"] == ["S256"]
        and consent_log[0]["resource"] == [f"{API}/mcp"],
        "goal_listed": any(g["goal_id"] == goal_id for g in listed["body"]["goals"]),
        "policy_composed_growth": policy["body"]["model_family"] == "composed_growth",
        "published_after_evidence": forecast["body"]["status"] == "PUBLISHED",
        "retry_replayed": retry["body"]["status"] == "replayed",
        "agent_reported_provenance": all(
            row["provenance"].get("verification_status") == "agent_reported"
            and row["provenance"].get("submission", {}).get("channel") == "remote_mcp"
            for row in rest_evidence
        ),
        "evidence_count": len(rest_evidence) == 4,
        "mapped_simulation_priced": mapped["body"]["priced"] is True,
        "unmapped_not_priced": unmapped["body"]["causal_status"] == "unmapped_intervention",
        "simulation_did_not_publish": after["body"]["published_points"]
        == forecast["body"]["published_points"]
        and after["body"]["probability"] == forecast["body"]["probability"],
        "revocation_ok": revoked.status_code == 200,
        "revoked_token_rejected": after_revoke.status_code == 401,
    }
    transcript.update(
        {
            "consent": consent_log,
            "steps": steps,
            "rest_evidence_count": len(rest_evidence),
            "revoked_status": revoked.status_code,
            "after_revoke_status": after_revoke.status_code,
            "checks": checks,
            "finished_at": datetime.now(UTC).isoformat(),
        }
    )
    rendered = json.dumps(transcript, indent=1, default=str)
    assert "pio_at_" not in rendered and "pio_rt_" not in rendered
    out = anyio.Path(OUT)
    await out.parent.mkdir(parents=True, exist_ok=True)
    await out.write_text(rendered, encoding="utf-8")
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    probability = forecast["body"].get("probability")
    print(f"forecast={probability} mapped_delta_pp={mapped['body'].get('delta_pp')}")
    print(f"transcript -> {OUT}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
