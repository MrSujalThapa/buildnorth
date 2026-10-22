from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid5

from personal_markets.agents.state import NAMESPACE

DEMO_PORTFOLIO_NAMESPACE = uuid5(NAMESPACE, "playitout:demo-portfolio")


def _goal_id(slug: str) -> str:
    return str(uuid5(DEMO_PORTFOLIO_NAMESPACE, slug))


def _stamp(as_of: datetime, weeks_ago: int) -> str:
    return (as_of - timedelta(weeks=weeks_ago)).isoformat()


def _history(
    slug: str,
    *,
    start: float,
    dip: float,
    recover: float,
    as_of: datetime,
    n: int = 24,
) -> list[dict[str, object]]:
    rng = random.Random(slug)
    points: list[dict[str, object]] = []
    for index in range(n):
        t = index / (n - 1)
        curve = (
            start
            + (dip - start) * math.sin(math.pi * t) * 0.55
            + (recover - start) * (t**1.35)
        )
        value = max(0.04, min(0.92, curve + rng.uniform(-0.025, 0.025)))
        weeks_ago = n - 1 - index
        points.append(
            {
                "id": f"demo-{slug}-{index}",
                "probability": round(value, 4),
                "forecast_status": "EXPLORATORY",
                "evidence_watermark": f"demo:{slug}:{index}",
                "model_family": "continuous_target_transition",
                "model_version": "1.0.0",
                "assumption_hash": f"demo-{slug}",
                "simulation_run_id": None,
                "source_kind": "synthetic_demo",
                "created_at": _stamp(as_of, weeks_ago),
            }
        )
    return points


def _goal(
    slug: str,
    title: str,
    *,
    goal_type: str,
    dimensions: list[str],
    as_of: datetime,
) -> dict[str, object]:
    return {
        "goal_id": _goal_id(slug),
        "title": title,
        "goal_type": goal_type,
        "deadline": (as_of + timedelta(days=400)).isoformat(),
        "forecast_status": "EXPLORATORY",
        "state_dimensions": dimensions,
        "success_definition": {"metric": dimensions[0], "operator": ">=", "amount": 1},
    }


def demo_portfolio(*, as_of: datetime | None = None) -> dict[str, object]:
    stamp = as_of or datetime(2026, 10, 21, tzinfo=UTC)
    specs = [
        (
            "net-worth",
            "Reach $1M net worth",
            "continuous_target",
            ["liquid_assets"],
            0.22,
            0.16,
            0.31,
        ),
        (
            "offer",
            "Land a software offer",
            "deadline_event",
            ["applications"],
            0.18,
            0.11,
            0.41,
        ),
        (
            "startup",
            "Raise a seed round",
            "multi_outcome",
            ["mrr", "runway"],
            0.12,
            0.07,
            0.24,
        ),
        (
            "running",
            "Run a sub-20 5K",
            "continuous_target",
            ["weekly_distance_km"],
            0.34,
            0.21,
            0.58,
        ),
    ]
    goals = [
        _goal(slug, title, goal_type=goal_type, dimensions=dimensions, as_of=stamp)
        for slug, title, goal_type, dimensions, *_rest in specs
    ]
    histories = {
        _goal_id(slug): _history(slug, start=start, dip=dip, recover=recover, as_of=stamp)
        for slug, _title, _type, _dims, start, dip, recover in specs
    }
    career_ids = [_goal_id("offer"), _goal_id("startup")]
    collection_id = str(uuid5(DEMO_PORTFOLIO_NAMESPACE, "career-collection"))
    series = [
        {
            "goal_id": goal_id,
            "title": next(item["title"] for item in goals if item["goal_id"] == goal_id),
            "color": "#1f8f86" if goal_id == career_ids[0] else "#b56a52",
            "points": [
                {"timestamp": point["created_at"], "value": point["probability"]}
                for point in histories[goal_id]
            ],
            "withheld": False,
        }
        for goal_id in career_ids
    ]
    collections = [
        {
            "collection": {
                "collection_id": collection_id,
                "owner_id": str(DEMO_PORTFOLIO_NAMESPACE),
                "name": "Career bets",
                "description": "Isolated demonstration collection. Not your data.",
                "icon": None,
                "color": None,
                "position": 0,
                "goal_ids": career_ids,
            },
            "progress": {
                "label": "progress",
                "value": 0.325,
                "available": 2,
                "total": 2,
                "incomplete": False,
                "methodology": "Demonstration equal-weight blend. Not a live forecast.",
                "notes": ["Isolated demonstration data."],
            },
            "series": series,
            "portfolio_odds": 0.325,
            "change_pp": 4.2,
            "priced_goals": 2,
            "total_goals": 2,
            "portfolio_methodology": "Demonstration equal-weight blend. Not a live forecast.",
        }
    ]
    return {
        "demo": True,
        "message": (
            "Isolated demonstration markets and collection histories. "
            "These rows are not written to your account."
        ),
        "goals": goals,
        "histories": histories,
        "collections": collections,
    }
