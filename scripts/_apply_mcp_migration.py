"""Apply 0015_mcp_oauth.sql additively to the local dev and isolated test databases."""

from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from personal_markets.core.config import get_settings

MIGRATION = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "0015_mcp_oauth.sql"
TABLES = (
    "remote_mcp_oauth_clients",
    "remote_mcp_authorization_requests",
    "remote_mcp_connections",
    "remote_mcp_authorization_codes",
    "remote_mcp_tokens",
    "remote_mcp_evidence_submissions",
    "remote_mcp_audit_log",
)


def apply(dsn: str, label: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        row = connection.execute("select to_regclass('remote_mcp_oauth_clients')").fetchone()
        if row is None or row[0] is None:
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
            print("applied 0015_mcp_oauth.sql ->", label)
        else:
            print("0015 already present ->", label)
        for table in TABLES:
            found = connection.execute("select to_regclass(%s)", (table,)).fetchone()
            print(label, table, "ok" if found and found[0] else "MISSING")


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("PM_DATABASE_URL is not configured")
    url = make_url(settings.database_url)
    apply(url.render_as_string(hide_password=False), url.database or "default")
    test = url.set(database="playitout_phase0_test")
    try:
        apply(test.render_as_string(hide_password=False), "playitout_phase0_test")
    except Exception as error:
        print("isolated test db skipped:", type(error).__name__, error)


if __name__ == "__main__":
    main()
