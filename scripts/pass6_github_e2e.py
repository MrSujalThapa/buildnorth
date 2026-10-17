"""Pass 6 GitHub evidence sync verification — run twice and report dedupe."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from personal_markets.main import app
from personal_markets.persistence.database import create_engine
from personal_markets.core.config import get_settings

GOAL_ID = "20000000-0000-0000-0000-000000000002"
USER_ID = "10000000-0000-0000-0000-000000000001"


GOAL_UUID = UUID(GOAL_ID)
USER_UUID = UUID(USER_ID)


async def counts(engine) -> dict[str, int]:
    async with engine.connect() as conn:
        raw = await conn.execute(
            text("SELECT COUNT(*) FROM raw_source_events WHERE user_id = :user_id"),
            {"user_id": USER_UUID},
        )
        raw_total = int(raw.scalar_one())
        dupes = await conn.execute(
            text(
                """
                SELECT COUNT(*) FROM (
                  SELECT external_event_id, COUNT(*) c
                  FROM raw_source_events
                  WHERE user_id = :user_id AND external_event_id IS NOT NULL
                  GROUP BY external_event_id
                  HAVING COUNT(*) > 1
                ) d
                """
            ),
            {"user_id": USER_UUID},
        )
        events = await conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM goal_evidence ge
                JOIN evidence_events ee ON ee.id = ge.evidence_id
                WHERE ge.goal_id = :goal_id
                """
            ),
            {"goal_id": GOAL_UUID},
        )
        history = await conn.execute(
            text(
                """
                SELECT probability, source_kind, created_at
                FROM market_forecast_history
                WHERE goal_id = :goal_id
                ORDER BY created_at DESC
                LIMIT 3
                """
            ),
            {"goal_id": GOAL_UUID},
        )
        return {
            "raw_source_events": raw_total,
            "duplicate_external_ids": int(dupes.scalar_one()),
            "evidence_events": int(events.scalar_one()),
            "recent_history": [dict(row._mapping) for row in history],
        }


async def sync_once(client: AsyncClient) -> dict:
    response = await client.post(f"/api/v1/goals/{GOAL_ID}/evidence/sources/sync", timeout=300)
    try:
        body = response.json()
    except Exception:
        body = {"raw": response.text}
    return {"status_code": response.status_code, "body": body}


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    before = await counts(engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=300) as client:
        async with app.router.lifespan_context(app):
            first = await sync_once(client)
            mid = await counts(engine)
            second = await sync_once(client)
            after = await counts(engine)
    report = {
        "before": before,
        "first_sync": first,
        "after_first": mid,
        "second_sync": second,
        "after_second": after,
        "raw_delta_first": mid["raw_source_events"] - before["raw_source_events"],
        "raw_delta_second": after["raw_source_events"] - mid["raw_source_events"],
        "events_delta_first": mid["evidence_events"] - before["evidence_events"],
        "events_delta_second": after["evidence_events"] - mid["evidence_events"],
    }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
