"""Pass 05: published forecast history on real migrated Postgres, not invented series."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from helpers import POSTGRES_MIGRATION_SKIP, isolated_postgres_url
from personal_markets.forecasting.repository import PostgresBaselineForecastRepository
from personal_markets.forecasting.service import BaselineForecastService
from personal_markets.persistence.database import create_engine
from personal_markets.remote_mcp.charting import (
    filter_range,
    is_png,
    render_odds_png,
    series_from_history,
)
from personal_markets.remote_mcp.temporal import delta_pp, select_as_of, sort_history

pytestmark = pytest.mark.integration


async def test_published_receipts_drive_as_of_and_static_chart() -> None:
    url = isolated_postgres_url()
    if not url:
        pytest.skip("Isolated Postgres is not configured")
    engine = create_engine(url)
    user_id = uuid4()
    goal_id = uuid4()
    other_goal = uuid4()
    now = datetime(2026, 10, 18, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            if not await connection.scalar(text("select to_regclass('market_forecast_history')")):
                pytest.skip(POSTGRES_MIGRATION_SKIP)
            await connection.execute(
                text(
                    "insert into app_users (id, clerk_user_id, email) values (:id, :clerk, :email)"
                ),
                {"id": user_id, "clerk": f"pass05-{user_id}", "email": f"{user_id}@example.test"},
            )
            for item in (goal_id, other_goal):
                await connection.execute(
                    text("""
                    insert into goals (
                      id, user_id, title, goal_type, success_definition_json,
                      deadline, forecast_status
                    ) values (
                      :id, :user_id, :title, 'deadline_event',
                      '{"metric":"applications"}'::jsonb, :deadline, 'ANCHORED'
                    )
                    """),
                    {
                        "id": item,
                        "user_id": user_id,
                        "title": "Software internship by May",
                        "deadline": now + timedelta(days=200),
                    },
                )
            rows = [
                (goal_id, 0.22, "a", "m-a", now - timedelta(days=14), "published_forecast"),
                (goal_id, 0.31, "b", "m-b", now - timedelta(hours=2), "published_forecast"),
                (goal_id, 0.99, "demo", "m-demo", now - timedelta(days=7), "synthetic_demo"),
                (other_goal, 0.55, "c", "m-c", now, "published_forecast"),
            ]
            for gid, probability, watermark, material, created, kind in rows:
                await connection.execute(
                    text("""
                    insert into market_forecast_history (
                      goal_id, probability, forecast_status, evidence_watermark,
                      model_family, model_version, assumption_hash, material_hash,
                      simulation_artifact_id, source_kind, receipt_json, created_at
                    ) values (
                      :goal_id, :probability, 'ANCHORED', :watermark,
                      'deadline_event_hazard', '1', 'a', :material,
                      null, :kind, '{}'::jsonb, :created
                    )
                    """),
                    {
                        "goal_id": gid,
                        "probability": probability,
                        "watermark": watermark,
                        "material": material,
                        "kind": kind,
                        "created": created,
                    },
                )
        service = BaselineForecastService(PostgresBaselineForecastRepository(engine))
        history = await service.published_history(goal_id)
        published = [item for item in history if item.source_kind == "published_forecast"]
        assert [item.probability for item in sort_history(published)] == [0.22, 0.31]
        selected, reason = select_as_of(
            published, as_of=None, relative="previous", evidence_observed_at=None, now=now
        )
        assert reason == ""
        assert selected is not None and selected.probability == 0.22
        assert delta_pp(0.31, selected.probability) == pytest.approx(9.0)
        points = series_from_history(history)
        assert [item["probability"] for item in points] == [0.22, 0.31]
        day = filter_range(points, "1D", now=now)
        assert len(day) == 1 and day[0]["probability"] == 0.31
        png = render_odds_png(points, title="Internship")
        assert is_png(png)
        other = await service.published_history(other_goal)
        assert [item.probability for item in other] == [0.55]
    finally:
        await engine.dispose()
