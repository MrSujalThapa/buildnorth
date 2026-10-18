from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from personal_markets.core.config import Settings

SQL = (Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "0009_identity_invites_budgets.sql").read_text(
    encoding="utf-8"
)


def main() -> None:
    settings = Settings()
    if not settings.database_url:
        raise SystemExit("PM_DATABASE_URL is not configured")
    url = make_url(settings.database_url)
    for database in (url.database, "playitout_phase0_test"):
        dsn = url.set(database=database).render_as_string(hide_password=False)
        with psycopg.connect(dsn, autocommit=True) as connection:
            exists = connection.execute(
                "select exists(select 1 from information_schema.tables where table_name='app_users')"
            ).fetchone()
            if exists and exists[0]:
                print("app_users present in", database)
                continue
            connection.execute(SQL)
            print("applied 0009 to", database)


if __name__ == "__main__":
    main()
