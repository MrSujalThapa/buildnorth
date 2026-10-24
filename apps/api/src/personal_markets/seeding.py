import hashlib
import json
from pathlib import Path
from typing import Any

from personal_markets.goals.domain import GoalContract
from personal_markets.goals.repository import GoalRepository


def load_seed(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for goal in payload["goals"]:
        GoalContract.model_validate(goal)
    return payload


def seed_checksum(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def seed_goals(repository: GoalRepository, payload: dict[str, Any]) -> tuple[int, int]:
    created = 0
    for record in payload["goals"]:
        goal = GoalContract.model_validate(record)
        goal = goal.model_copy(
            update={
                "model_requirements": {
                    **goal.model_requirements,
                    "demo_seed": "seeds/demo.json",
                }
            }
        )
        if await repository.upsert_seed(goal):
            created += 1
    return created, len(payload["goals"]) - created
