"""One small database layer for the whole server.

DATABASE_URL set   -> Postgres (Supabase's session pooler, port 5432; see docs/DEPLOY.md).
DATABASE_URL unset -> the SQLite file (DERMOS_DB, default backend/dermos.db), so tests and local
                      dev stay offline.

Both take the same SQL: write `?` placeholders and portable statements (INSERT ... ON CONFLICT).
On Postgres the tables come from the versioned migration (backend/migrations, applied with
`python -m scripts.migrate`); on SQLite they are created here, from the same column list.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BACKEND_DIR = Path(__file__).resolve().parents[1]

# The guest / demo tables (one JSON body per row) and the judge unit counter, unchanged.
LEGACY_KINDS = ("history", "shelf", "captures", "trials", "outcomes", "baskets", "chips")

# Account tables. No column holds image bytes or an image URL: face photos are never stored,
# only results (tests/test_accounts.py checks every column here and in the migration).
SQLITE_DDL = [
    *[f"CREATE TABLE IF NOT EXISTS {k} (id TEXT PRIMARY KEY, body TEXT, created TEXT)" for k in LEGACY_KINDS],
    "CREATE TABLE IF NOT EXISTS spend (id TEXT PRIMARY KEY, day TEXT, units REAL, state TEXT, at TEXT)",
    """CREATE TABLE IF NOT EXISTS profiles (
        user_id TEXT PRIMARY KEY, display_name TEXT, finish_goal TEXT, budget TEXT,
        beginner INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS scans (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
        zone_types TEXT NOT NULL, concern_values TEXT NOT NULL, undertone TEXT,
        undertone_method TEXT, engine_versions TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS user_history (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL,
        clinician_confirmed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS user_shelf (
        user_id TEXT PRIMARY KEY, product_ids TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS user_baskets (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL, demo INTEGER NOT NULL DEFAULT 0,
        basket TEXT NOT NULL, start_plan TEXT, engine_versions TEXT NOT NULL)""",
]
USER_TABLES = ("profiles", "scans", "user_history", "user_shelf", "user_baskets")


def database_url() -> str:
    return (os.environ.get("DATABASE_URL") or "").strip()


def is_postgres() -> bool:
    return bool(database_url())


def sqlite_path() -> Path:
    return Path(os.environ.get("DERMOS_DB", BACKEND_DIR / "dermos.db"))


class Conn:
    """The two drivers behind one `execute(sql, params)`; `?` becomes `%s` on Postgres."""

    def __init__(self, raw: Any, pg: bool):
        self.raw, self.pg = raw, pg

    def execute(self, sql: str, params: tuple | list = ()):
        if self.pg:
            sql = sql.replace("?", "%s")
        return self.raw.execute(sql, tuple(params))


_POOL = None
_POOL_LOCK = threading.Lock()


def _pool():
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            from psycopg_pool import ConnectionPool  # only needed when DATABASE_URL is set
            # Small on purpose: the free session pooler allows few clients. Opened lazily, so a
            # cold start doesn't block on the database.
            _POOL = ConnectionPool(database_url(), min_size=0, max_size=4, open=True,
                                   kwargs={"connect_timeout": 10})
        return _POOL


@contextmanager
def connect(path: Path | None = None) -> Iterator[Conn]:
    """A connection that commits on success and rolls back on error."""
    if is_postgres():
        with _pool().connection() as raw:  # commits / rolls back, then returns it to the pool
            yield Conn(raw, True)
        return
    p = Path(path or sqlite_path())
    raw = sqlite3.connect(p)
    try:
        for ddl in SQLITE_DDL:  # cheap, and the same as the server always did
            raw.execute(ddl)
        with raw:
            yield Conn(raw, False)
    finally:
        raw.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(v: Any) -> str:
    return json.dumps(v)


def loads(v: Any) -> Any:
    """jsonb comes back parsed from Postgres; TEXT comes back as a string from SQLite."""
    if v is None or isinstance(v, (dict, list)):
        return v
    return json.loads(v)


def ts(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else v
