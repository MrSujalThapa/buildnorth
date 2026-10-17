"""Full Pass 6 GitHub evidence → forecast E2E capture."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from personal_markets.main import app
from personal_markets.persistence.database import create_engine
from personal_markets.core.config import get_settings

GOAL_ID = "20000000-0000-0000-0000-000000000002"
USER_ID = UUID("10000000-0000-0000-0000-000000000001")
GOAL_UUID = UUID(GOAL_ID)


async def snapshot(engine, label: str) -> dict:
    async with engine.connect() as conn:
        raw = int(
            (
                await conn.execute(
                    text("SELECT COUNT(*) FROM raw_source_events WHERE user_id = :user_id"),
                    {"user_id": USER_ID},
                )
            ).scalar_one()
        )
        dupes = int(
            (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM (
                          SELECT external_event_id, COUNT(*) c
                          FROM raw_source_events
                          WHERE user_id = :user_id AND external_event_id IS NOT NULL
                          GROUP BY external_event_id HAVING COUNT(*) > 1
                        ) d
                        """
                    ),
                    {"user_id": USER_ID},
                )
            ).scalar_one()
        )
        events = int(
            (
                await conn.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM goal_evidence ge
                        JOIN evidence_events ee ON ee.id = ge.evidence_id
                        WHERE ge.goal_id = :goal_id
                        """
                    ),
                    {"goal_id": GOAL_UUID},
                )
            ).scalar_one()
        )
        history = int(
            (
                await conn.execute(
                    text("SELECT COUNT(*) FROM market_forecast_history WHERE goal_id = :goal_id"),
                    {"goal_id": GOAL_UUID},
                )
            ).scalar_one()
        )
        latest = (
            await conn.execute(
                text(
                    """
                    SELECT probability, source_kind, created_at
                    FROM market_forecast_history
                    WHERE goal_id = :goal_id
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"goal_id": GOAL_UUID},
            )
        ).mappings().first()
    return {
        "label": label,
        "raw_source_events": raw,
        "duplicate_external_ids": dupes,
        "goal_evidence_events": events,
        "history_count": history,
        "latest_history": dict(latest) if latest else None,
    }


async def sync_once(client: AsyncClient) -> dict:
    response = await client.post(f"/api/v1/goals/{GOAL_ID}/evidence/sources/sync", timeout=600)
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text[:2000]}
    return {"status_code": response.status_code, "body": body}


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    before = await snapshot(engine, "before")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=600) as client:
        async with app.router.lifespan_context(app):
            first = await sync_once(client)
            mid = await snapshot(engine, "after_first_sync")
            second = await sync_once(client)
            after = await snapshot(engine, "after_second_sync")
    report = {
        "before": before,
        "first_sync": first,
        "after_first": mid,
        "second_sync": second,
        "after_second": after,
        "raw_delta_first": mid["raw_source_events"] - before["raw_source_events"],
        "raw_delta_second": after["raw_source_events"] - mid["raw_source_events"],
        "events_delta_first": mid["goal_evidence_events"] - before["goal_evidence_events"],
        "events_delta_second": after["goal_evidence_events"] - mid["goal_evidence_events"],
        "history_delta_first": mid["history_count"] - before["history_count"],
        "history_delta_second": after["history_count"] - mid["history_count"],
    }
    out = Path(__file__).resolve().parents[1] / "benchmarks" / "pass6_eval_v1" / "github_e2e.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
