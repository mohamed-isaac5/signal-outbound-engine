"""SQLite-backed run store and audit log (M4).

Every run, score, draft and approval decision is persisted so any outbound
message can be traced back to the signals and score that produced it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def log_event(conn: sqlite3.Connection, event: str, detail: str) -> None:
    if not event.strip():
        raise ValueError("event name required")
    conn.execute("INSERT INTO audit (event, detail) VALUES (?, ?)", (event, detail))
    conn.commit()
