import re
from pathlib import Path

REQUIRED_FILES = 24
RESERVED_GAPS: set[str] = set()
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
    "market_stars",
    "user_follows",
    "profile_activity_events",
}


def main() -> int:
    directory = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    migrations = sorted(directory.glob("*.sql"))
    names = [path.name for path in migrations]
    expected = [f"{index:04d}_" for index in range(1, REQUIRED_FILES + 1)]
    occupied_reserved = [
        name for name in names if any(name.startswith(gap) for gap in RESERVED_GAPS)
    ]
    if occupied_reserved:
        print(
            "Migration 0023 is reserved for PR #33 social marketplace; "
            f"found {', '.join(occupied_reserved)}. Fingerprint uniqueness belongs in 0024."
        )
        return 1
    missing_files = [
        prefix
        for prefix in expected
        if prefix not in RESERVED_GAPS
        and not any(name.startswith(prefix) for name in names)
    ]
    expected_count = REQUIRED_FILES - len(RESERVED_GAPS)
    if missing_files or len(migrations) != expected_count:
        print(
            f"Expected migrations 0001-{REQUIRED_FILES:04d} "
            f"({REQUIRED_FILES} files); found {len(migrations)}: {', '.join(names)}"
        )
        if missing_files:
            print(f"Missing prefixes: {', '.join(missing_files)}")
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
