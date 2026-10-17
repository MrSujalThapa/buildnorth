"""Fresh GitHub evidence E2E after unique branch commit."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from personal_markets.core.config import get_settings
from personal_markets.main import app
from personal_markets.persistence.database import create_engine

GOAL = "20000000-0000-0000-0000-000000000002"
USER = UUID("10000000-0000-0000-0000-000000000001")
SHA = "289316f2367f2a68901aedbc0361c49534572a77"
SHORT = "289316f"


async def snap(engine, label: str) -> dict:
    async with engine.connect() as conn:
        raw = int(
            (
                await conn.execute(
                    text("select count(*) from raw_source_events where user_id = :u"),
                    {"u": USER},
                )
            ).scalar_one()
        )
        sha_exact = int(
            (
                await conn.execute(
                    text("select count(*) from raw_source_events where external_event_id = :s"),
                    {"s": SHA},
                )
            ).scalar_one()
        )
        sha_soft = int(
            (
                await conn.execute(
                    text(
                        "select count(*) from raw_source_events "
                        "where cast(raw_payload_json as text) like :p"
                    ),
                    {"p": f"%{SHORT}%"},
                )
            ).scalar_one()
        )
        evidence = int(
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
        history = int(
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
                    from market_forecast_history
                    where goal_id = :g
                    order by created_at desc limit 1
                    """
                ),
                {"g": UUID(GOAL)},
            )
        ).mappings().first()
    return {
        "label": label,
        "raw": raw,
        "sha_exact": sha_exact,
        "sha_soft": sha_soft,
        "evidence": evidence,
        "history": history,
        "latest": dict(latest) if latest else None,
    }


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    before = await snap(engine, "before")
    payload = {
        "label": "MrSujalThapa/playitout",
        "resource_ids": ["MrSujalThapa/playitout"],
        "approved": True,
        "steps": [
            {
                "capability_id": "github.dynamic.github_list_commits.read",
                "tool_name": "GITHUB_LIST_COMMITS",
                "resource_uri": "composio://github/MrSujalThapa/playitout",
                "arguments": {
                    "owner": "MrSujalThapa",
                    "repo": "playitout",
                    "sha": "codex/pass-6-end-to-end-product",
                },
            }
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=600) as client:
        async with app.router.lifespan_context(app):
            recipe = await client.post(
                f"/api/v1/goals/{GOAL}/evidence/sources/github/recipe",
                json=payload,
            )
            sync1 = await client.post(f"/api/v1/goals/{GOAL}/evidence/sources/sync", timeout=600)
            mid = await snap(engine, "after1")
            sync2 = await client.post(f"/api/v1/goals/{GOAL}/evidence/sources/sync", timeout=600)
            after = await snap(engine, "after2")
    out = {
        "target_sha": SHA,
        "before": before,
        "recipe_status": recipe.status_code,
        "sync1": {"code": sync1.status_code, "body": sync1.json()},
        "after1": mid,
        "sync2": {"code": sync2.status_code, "body": sync2.json()},
        "after2": after,
        "raw_delta1": mid["raw"] - before["raw"],
        "raw_delta2": after["raw"] - mid["raw"],
        "evidence_delta1": mid["evidence"] - before["evidence"],
        "history_delta1": mid["history"] - before["history"],
    }
    path = Path(__file__).resolve().parents[1] / "benchmarks" / "pass6_eval_v1" / "github_fresh_e2e.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
