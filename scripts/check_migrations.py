from pathlib import Path

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
}


def main() -> int:
    directory = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    migrations = sorted(directory.glob("*.sql"))
    sql = "\n".join(path.read_text(encoding="utf-8").lower() for path in migrations)
    missing = sorted(table for table in REQUIRED if f"create table {table}" not in sql)
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
