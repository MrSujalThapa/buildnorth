from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "migrations" / "0010_shared_invitations.sql").read_text(encoding="utf-8")


def _database_url() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("PM_DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def apply(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(SQL)
    print("applied 0010 ->", make_url(dsn).database)


def main() -> None:
    live = _database_url()
    apply(live)
    test = make_url(live).set(database="playitout_phase0_test").render_as_string(hide_password=False)
    apply(test)


if __name__ == "__main__":
    main()
