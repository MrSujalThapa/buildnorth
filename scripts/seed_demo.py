import asyncio
import json
import os
from pathlib import Path
from typing import Any

from personal_markets.persistence.database import create_engine
from personal_markets.persistence.repositories import PostgresSeedRepository
from personal_markets.seeding import load_seed, seed_checksum


async def seed(payload: dict[str, Any], url: str) -> dict[str, object]:
    engine = create_engine(url)
    try:
        repository = PostgresSeedRepository(engine)
        first = await repository.seed(payload)
        second = await repository.seed(payload)
    finally:
        await engine.dispose()
    return {
        "seed_version": payload["version"],
        "checksum": seed_checksum(payload),
        "goal_count": len(payload["goals"]),
        "raw_event_count": len(payload["raw_source_events"]),
        "first_run": first,
        "second_run": second,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = load_seed(root / "seeds" / "demo.json")
    url = os.environ.get(
        "PM_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    )
    artifact = asyncio.run(seed(payload, url))
    output = root / ".artifacts" / "seed-demo.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print("Demo goal IDs:")
    for goal in payload["goals"]:
        print(f"  {goal['goal_id']}  {goal['title']}")
    print(json.dumps(artifact, indent=2))


if __name__ == "__main__":
    main()
