"""שכבת גישה ל-SQLite: חיבור לכל בקשה, סכימה, ועזרי שאילתה."""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Optional

from . import config

_local = threading.local()
_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


def get_conn() -> sqlite3.Connection:
    """חיבור פר-thread. שרת ה-HTTP מטפל בכל בקשה ב-thread נפרד."""
    conn = getattr(_local, "conn", None)
    path = config.DB_PATH
    if conn is None or getattr(_local, "path", None) != path:
        if conn is not None:
            conn.close()
        conn = connect(path)
        _local.conn = conn
        _local.path = path
    return conn


def close_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


# עמודות שנוספו אחרי גרסאות קודמות. SQLite לא תומך ב-IF NOT EXISTS ל-ALTER,
# ולכן משווים מול PRAGMA table_info לפני כל הוספה.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("users", "role", "TEXT NOT NULL DEFAULT 'client'"),
    ("users", "blocked", "INTEGER NOT NULL DEFAULT 0"),
    ("professionals", "photo", "TEXT NOT NULL DEFAULT ''"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, definition in _MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:          # הטבלה עדיין לא קיימת - הסכימה תיצור אותה מלאה
            continue
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _backfill_roles(conn: sqlite3.Connection) -> None:
    """משתמשים ותיקים שיש להם פרופיל מקצועי מסומנים כאנשי מקצוע."""
    conn.execute(
        "UPDATE users SET role='pro' WHERE role='client' "
        "AND id IN (SELECT user_id FROM professionals)"
    )


def init_db(path: Optional[str] = None) -> None:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        sql = fh.read()
    conn = connect(path) if path else get_conn()
    try:
        # קודם השלמת עמודות חסרות במסד ותיק - אחרת אינדקסים שבסכימה
        # מפנים לעמודות שעדיין לא קיימות; אחר כך יצירת מה שחסר לגמרי.
        _migrate(conn)
        conn.executescript(sql)
        _backfill_roles(conn)
    finally:
        if path:
            conn.close()


@contextmanager
def transaction():
    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return get_conn().execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    return get_conn().execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return get_conn().execute(sql, tuple(params))


def insert(sql: str, params: Iterable[Any] = ()) -> int:
    return int(get_conn().execute(sql, tuple(params)).lastrowid)


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None
