import re
from pathlib import Path

BASE_REQUIRED_FILES = 22
LEARNING_MIGRATION = "0025_goal_strategy_learning.sql"
REQUIRED = {
    "goals",
    "source_connections",
    "raw_source_events",
    "evidence_events",
    "goal_evidence",
    "state_snapshots",
    "reference_datasets",
    "model_versions",
    "forecasts",
    "forecast_receipts",
    "actions",
    "scenarios",
    "simulation_runs",
    "scenario_outcomes",
    "agent_runs",
    "evaluation_runs",
    "profile_photos",
    "goal_sync_jobs",
    "source_watches",
    "behavior_commitments",
    "behavior_commitment_observations",
    "workspace_seed_records",
    "strategy_recommendations",
    "strategy_outcome_observations",
    "strategy_outcome_evidence",
}


def main() -> int:
    directory = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    migrations = sorted(directory.glob("*.sql"))
    names = [path.name for path in migrations]
    expected = [f"{index:04d}_" for index in range(1, BASE_REQUIRED_FILES + 1)]
    missing_files = [
        prefix for prefix in expected if not any(name.startswith(prefix) for name in names)
    ]
    numbered = [name[:4] for name in names if name[:4].isdigit()]
    duplicate_numbers = sorted({number for number in numbered if numbered.count(number) > 1})
    if missing_files or LEARNING_MIGRATION not in names or duplicate_numbers:
        print(
            f"Expected migrations 0001-{BASE_REQUIRED_FILES:04d} and "
            f"{LEARNING_MIGRATION}; found {len(migrations)}: {', '.join(names)}"
        )
        if missing_files:
            print(f"Missing prefixes: {', '.join(missing_files)}")
        if duplicate_numbers:
            print(f"Duplicate migration numbers: {', '.join(duplicate_numbers)}")
        return 1
    sql = "\n".join(path.read_text(encoding="utf-8").lower() for path in migrations)
    missing = sorted(
        table for table in REQUIRED
        if not re.search(rf"create table (?:if not exists )?{table}\b", sql)
    )
    if missing:
        print(f"Migration is missing tables: {', '.join(missing)}")
        return 1
    invalid = [
        path.name
        for path in migrations
        if not path.read_text(encoding="utf-8").lower().startswith("begin;")
        or not path.read_text(encoding="utf-8").lower().rstrip().endswith("commit;")
    ]
    if invalid:
        print(f"Migrations must be transactional: {', '.join(invalid)}")
        return 1
    for table in ("state_snapshots", "forecasts", "forecast_receipts"):
        if f"create trigger {table}_immutable" not in sql:
            print(f"Missing append-only trigger for {table}")
            return 1
    print(f"Migration sanity passed ({len(REQUIRED)} required tables, {len(migrations)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
