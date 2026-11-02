"""Apply the versioned SQL migrations in backend/migrations to the Postgres at DATABASE_URL.

    cd backend; $env:DATABASE_URL = "<session pooler string, port 5432>"; python scripts/migrate.py

Each file runs once, in name order, inside one transaction, and is recorded in schema_migrations.
Prints file names only: never the connection string. With no DATABASE_URL it does nothing (the
local SQLite file creates its own tables).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def pending(applied: set[str]) -> list[Path]:
    return [p for p in sorted(MIGRATIONS.glob("*.sql")) if p.name not in applied]


def main() -> int:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL is not set: nothing to do (local dev uses the SQLite file).")
        return 0
    if ":6543" in url:
        print("That looks like the transaction pooler (port 6543). Use the session pooler (port 5432).")
        return 2
    import psycopg

    with psycopg.connect(url, connect_timeout=15) as con:
        con.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                    "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        con.execute("ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY")
        con.commit()
        applied = {r[0] for r in con.execute("SELECT name FROM schema_migrations").fetchall()}
        todo = pending(applied)
        if not todo:
            print(f"Up to date ({len(applied)} applied).")
            return 0
        for p in todo:
            with con.transaction():
                con.execute(p.read_text(encoding="utf-8"))
                con.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (p.name,))
            print(f"applied {p.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
