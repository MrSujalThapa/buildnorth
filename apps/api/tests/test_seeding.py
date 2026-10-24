import json
from pathlib import Path

import pytest

from personal_markets.behavior.cohort import behavior_cohort_goals
from personal_markets.goals.adapters import InMemoryGoalRepository
from personal_markets.seeding import load_seed, seed_goals

SEED = Path(__file__).resolve().parents[3] / "seeds" / "demo.json"
FORBIDDEN_KEYS = {
    "odds",
    "probability",
    "forecast",
    "forecast_value",
    "project_impact",
    "action_impact",
}


@pytest.mark.asyncio
async def test_seed_is_idempotent() -> None:
    payload = load_seed(SEED)
    repository = InMemoryGoalRepository()
    assert await seed_goals(repository, payload) == (5, 0)
    assert await seed_goals(repository, payload) == (0, 5)
    seeded = await repository.list()
    assert len(seeded) == 5
    assert behavior_cohort_goals(seeded) == []
    assert len(behavior_cohort_goals(seeded, synthetic=True)) == 5


def test_seed_contains_no_forbidden_probability_fields() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert not (set(value) & FORBIDDEN_KEYS)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit({key: value for key, value in payload.items() if key != "market_history"})
    assert len(payload["market_history"]) == 50
