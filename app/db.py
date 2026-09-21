"""SQLite 持久化层。"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

DB_PATH = os.environ.get("STRATA_DB_PATH", "/data/strata.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    note    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS relations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    kind      TEXT NOT NULL CHECK (kind IN ('earlier_than', 'later_than', 'intersects')),
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    note      TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (source_id) REFERENCES units(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES units(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target_id);
"""


def _connect() -> sqlite3.Connection:
    path = DB_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
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
        conn.executescript(SCHEMA)


def snapshot(conn: sqlite3.Connection) -> dict:
    """读出当前全部数据（供推演逻辑使用）。"""
    units = [dict(r) for r in conn.execute("SELECT id, name, note FROM units ORDER BY id")]
    relations = [
        dict(r)
        for r in conn.execute(
            "SELECT id, kind, source_id, target_id, note FROM relations ORDER BY id"
        )
    ]
    return {"units": units, "relations": relations}
