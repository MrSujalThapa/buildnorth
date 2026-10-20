import argparse
import os
from pathlib import Path

import psycopg

from personal_markets.core.config import get_settings, safe_database_identity
from personal_markets.persistence.migration_target import (
    MigrationTargetError,
    is_hosted_supabase_url,
    is_loopback_url,
    require_migration_url,
)

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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply additive supabase/migrations to PM_DATABASE_URL. "
        "Does not run supabase db push. Does not reset data."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override PM_DATABASE_URL. Never log this value.",
    )
    parser.add_argument(
        "--allow-local",
        action="store_true",
        help="Allow loopback targets even when PM_ENVIRONMENT is not development.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print identity and pending files without applying SQL.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    try:
        url = require_migration_url(
            args.database_url or os.environ.get("PM_DATABASE_URL") or settings.database_url,
            settings.environment,
            allow_local=args.allow_local,
        )
    except MigrationTargetError as error:
        raise SystemExit(str(error)) from error

    identity = safe_database_identity(url)
    print("migration_target", identity)
    print("hosted_supabase", is_hosted_supabase_url(url))
    print("loopback", is_loopback_url(url))
    print("environment", settings.environment)

    root = Path(__file__).resolve().parents[1]
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
        pending = [path for path in files if path.name not in applied]
        print("applied", ",".join(sorted(applied)) or "(none)")
        print("pending", ",".join(path.name for path in pending) or "(none)")
        print("collections_table", "collections" in existing)
        if args.dry_run:
            print("dry_run no SQL applied")
            return
        for migration in pending:
            connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (migration.name,),
            )
            print(f"applied {migration.name}")


if __name__ == "__main__":
    main()
