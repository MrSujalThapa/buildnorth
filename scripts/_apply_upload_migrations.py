from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

from personal_markets.core.config import get_settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
FILES = ("0013_goal_uploads.sql", "0014_goal_upload_blobs.sql")


def apply(dsn: str, label: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        exists = connection.execute("select to_regclass('goal_uploads')").fetchone()[0]
        if exists is None:
            connection.execute((MIGRATIONS / "0013_goal_uploads.sql").read_text(encoding="utf-8"))
            print("applied 0013_goal_uploads.sql ->", label)
        else:
            print("0013 already present ->", label)
        connection.execute((MIGRATIONS / "0014_goal_upload_blobs.sql").read_text(encoding="utf-8"))
        print("applied 0014_goal_upload_blobs.sql ->", label)
        row = connection.execute(
            """
            select to_regclass('goal_uploads'),
              exists (
                select 1 from information_schema.columns
                where table_name = 'goal_uploads' and column_name = 'content'
              )
            """
        ).fetchone()
        print(label, "goal_uploads", row[0], "content", row[1])


def main() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("PM_DATABASE_URL is not configured")
    url = make_url(settings.database_url)
    apply(url.render_as_string(hide_password=False), url.database)
    test = url.set(database="playitout_phase0_test")
    try:
        apply(test.render_as_string(hide_password=False), "playitout_phase0_test")
    except Exception as error:
        print("isolated test db skipped:", type(error).__name__, error)


if __name__ == "__main__":
    main()
