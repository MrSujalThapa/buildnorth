import os
from pathlib import Path

import psycopg


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    url = os.environ.get(
        "PM_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    )
    with psycopg.connect(url, autocommit=True) as connection:
        for migration in sorted((root / "supabase" / "migrations").glob("*.sql")):
            connection.execute(migration.read_text(encoding="utf-8"))
            print(f"applied {migration.name}")


if __name__ == "__main__":
    main()
