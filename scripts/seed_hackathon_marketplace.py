"""Populate Discover with real demo-owned public markets. Repeat-safe.

Usage (from repo root, with PM_DATABASE_URL pointing at the target Postgres):

  python scripts/seed_hackathon_marketplace.py

Does not call hosted Spur. Forecast history comes from the deterministic
baseline engine replaying stored observations.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from personal_markets.behavior.commitments import get_commitment_store  # noqa: E402
from personal_markets.collections.service import CollectionService  # noqa: E402
from personal_markets.evidence.service import EvidenceService  # noqa: E402
from personal_markets.forecasting.service import BaselineForecastService  # noqa: E402
from personal_markets.identity.factory import get_identity_repository, get_identity_service  # noqa: E402
from personal_markets.wiring import (  # noqa: E402
    get_collection_repository,
    get_evidence_repository,
    get_baseline_forecast_repository,
    get_goal_service,
    get_social_service,
)
from personal_markets.workspace_seed.marketplace import seed_marketplace  # noqa: E402
from personal_markets.workspace_seed.registry import PostgresSeedRegistry  # noqa: E402
from personal_markets.workspace_seed.service import WorkspaceSeedService  # noqa: E402
from personal_markets.core.config import get_settings  # noqa: E402
from personal_markets.persistence.database import create_engine  # noqa: E402


def _seeder() -> WorkspaceSeedService:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("PM_DATABASE_URL is required")
    return WorkspaceSeedService(
        goals=get_goal_service(),
        evidence=EvidenceService(get_evidence_repository()),
        forecasts=BaselineForecastService(get_baseline_forecast_repository()),
        collections=CollectionService(get_collection_repository(), get_goal_service()),
        commitments=get_commitment_store(),
        registry=PostgresSeedRegistry(create_engine(settings.database_url)),
    )


async def main() -> None:
    result = await seed_marketplace(
        identity=get_identity_repository(),
        seeder=_seeder(),
        social=get_social_service(),
        goals=get_goal_service(),
    )
    print(json.dumps(result, indent=2, default=str))
    _ = get_identity_service()


if __name__ == "__main__":
    asyncio.run(main())
