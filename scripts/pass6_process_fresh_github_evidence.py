"""Process already-ingested MCP raw records through Evidence Agent → forecast."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from personal_markets.core.config import get_settings
from personal_markets.main import app
from personal_markets.persistence.database import create_engine

GOAL = "20000000-0000-0000-0000-000000000002"
SHA = "289316f2367f2a68901aedbc0361c49534572a77"


async def main() -> None:
    os.environ["PM_OPENAI_DAILY_TOKEN_BUDGET_HIGH_VOLUME"] = "15000000"
    os.environ["PM_OPENAI_MAX_COST_USD"] = "25"
    get_settings.cache_clear()

    settings = get_settings()
    engine = create_engine(settings.database_url)
    async with engine.connect() as conn:
        before_ev = int(
            (
                await conn.execute(
                    text(
                        """
                        select count(*) from goal_evidence ge
                        join evidence_events ee on ee.id = ge.evidence_id
                        where ge.goal_id = :g
                        """
                    ),
                    {"g": UUID(GOAL)},
                )
            ).scalar_one()
        )
        before_hist = int(
            (
                await conn.execute(
                    text("select count(*) from market_forecast_history where goal_id = :g"),
                    {"g": UUID(GOAL)},
                )
            ).scalar_one()
        )
        row = (
            await conn.execute(
                text(
                    """
                    select id, external_event_id, source_type, raw_payload_json, content_fingerprint
                    from raw_source_events
                    where external_event_id = :sha
                    """
                ),
                {"sha": SHA},
            )
        ).mappings().one()

    mcp_record = {
        "id": str(row["id"]),
        "plugin_connection_id": "c2bc832e-315f-49a1-abb0-1628ec21aa5e",
        "external_id": row["external_event_id"],
        "tool_identity": "GITHUB_LIST_COMMITS",
        "retrieved_at": "2026-08-30T17:42:04Z",
        "payload": row["raw_payload_json"],
        "payload_hash": row["content_fingerprint"],
        "sync_run_id": "00000000-0000-0000-0000-000000000001",
        "cursor_context": {"user_id": str(settings.default_user_id), "source_type": "github"},
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=600) as client:
        async with app.router.lifespan_context(app):
            response = await client.post(
                "/api/v1/agent/threads",
                json={
                    "kind": "add_evidence",
                    "goal_id": GOAL,
                    "evidence_text": (
                        "GitHub commit synced from MrSujalThapa/playitout "
                        f"sha={SHA}: Add unique Pass 6 sync marker for fresh GitHub evidence ingest."
                    ),
                    "mcp_records": [mcp_record],
                },
                timeout=600,
            )
            body: dict = response.json() if response.status_code < 500 else {"raw": response.text[:3000]}
            if response.status_code == 200 and body.get("status") == "needs_input":
                thread_id = body.get("thread_id")
                resume = await client.post(
                    f"/api/v1/agent/threads/{thread_id}/resume",
                    json={"confirmed": True},
                    timeout=600,
                )
                body = {
                    "start": body,
                    "resume_status": resume.status_code,
                    "resume": resume.json() if resume.status_code < 500 else resume.text[:2000],
                }

    async with engine.connect() as conn:
        after_ev = int(
            (
                await conn.execute(
                    text(
                        """
                        select count(*) from goal_evidence ge
                        join evidence_events ee on ee.id = ge.evidence_id
                        where ge.goal_id = :g
                        """
                    ),
                    {"g": UUID(GOAL)},
                )
            ).scalar_one()
        )
        after_hist = int(
            (
                await conn.execute(
                    text("select count(*) from market_forecast_history where goal_id = :g"),
                    {"g": UUID(GOAL)},
                )
            ).scalar_one()
        )
        latest = (
            await conn.execute(
                text(
                    """
                    select probability, source_kind, created_at
                    from market_forecast_history where goal_id = :g
                    order by created_at desc limit 1
                    """
                ),
                {"g": UUID(GOAL)},
            )
        ).mappings().first()

    out = {
        "sha": SHA,
        "http_status": response.status_code,
        "workflow": body,
        "evidence_before": before_ev,
        "evidence_after": after_ev,
        "evidence_delta": after_ev - before_ev,
        "history_before": before_hist,
        "history_after": after_hist,
        "history_delta": after_hist - before_hist,
        "latest_history": dict(latest) if latest else None,
    }
    path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks"
        / "pass6_eval_v1"
        / "github_evidence_forecast.json"
    )
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
