import os
from pathlib import Path

import psycopg

# Files that existed before this script started recording applications.
# Local databases that already have `goals` are treated as having these applied
# so restarts do not re-run CREATE TABLE. Newer files still run.
_LEGACY_APPLIED = (
    "0001_initial_schema.sql",
    "0002_persistence_contracts.sql",
    "0003_agent_runtime.sql",
    "0004_pass4_simulation_history.sql",
    "0005_market_history_provenance.sql",
    "0006_mcp_integrations.sql",
    "0007_goal_sync_recipes.sql",
    "0008_published_forecast_receipt.sql",
    "0009_identity_invites_budgets.sql",
    "0010_shared_invitations.sql",
    "0011_byok_inference.sql",
    "0012_research_artifacts.sql",
    "0013_goal_uploads.sql",
    "0014_goal_upload_blobs.sql",
    "0015_mcp_oauth.sql",
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    url = os.environ.get(
        "PM_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    )
    files = sorted((root / "supabase" / "migrations").glob("*.sql"))
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              filename text PRIMARY KEY,
              applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
        applied = {
            row[0] for row in connection.execute("SELECT filename FROM schema_migrations")
        }
        if not applied and "goals" in existing:
            for name in _LEGACY_APPLIED:
                connection.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
                    (name,),
                )
            applied = {
                row[0] for row in connection.execute("SELECT filename FROM schema_migrations")
            }
            print("recorded previously applied migrations")
        for migration in files:
            if migration.name in applied:
                print(f"skip {migration.name}")
                continue
            connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (migration.name,),
            )
            print(f"applied {migration.name}")


if __name__ == "__main__":
    main()
