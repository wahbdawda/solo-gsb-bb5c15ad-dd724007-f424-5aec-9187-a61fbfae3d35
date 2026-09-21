"""SQLite 持久化层。"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("STRATA_DB", "/data/strata.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT NOT NULL UNIQUE,
    name      TEXT NOT NULL DEFAULT '',
    kind      TEXT NOT NULL DEFAULT 'other',
    note      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS relations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id  INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    target_id  INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    rel_type   TEXT NOT NULL CHECK (rel_type IN ('earlier','later','intersects')),
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI 依赖：提交/回滚并关闭连接。"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


def list_units(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM units ORDER BY id")]


def list_relations(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM relations ORDER BY id")]


def get_unit(conn, unit_id: int):
    row = conn.execute("SELECT * FROM units WHERE id = ?", (unit_id,)).fetchone()
    return dict(row) if row else None


def find_relation(
    conn, source_id: int, target_id: int, rel_type: str
) -> dict | None:
    """归一化查重：A 早于 B 与 B 晚于 A 视为同一条。"""
    rows = conn.execute("SELECT * FROM relations").fetchall()
    from .engine import normalize_edge

    wanted = normalize_edge(
        {"source_id": source_id, "target_id": target_id, "rel_type": rel_type}
    )
    for row in rows:
        r = dict(row)
        if r["rel_type"] == "intersects":
            if rel_type == "intersects" and {
                r["source_id"],
                r["target_id"],
            } == {source_id, target_id}:
                return r
        elif rel_type != "intersects":
            if normalize_edge(r) == wanted:
                return r
    return None
