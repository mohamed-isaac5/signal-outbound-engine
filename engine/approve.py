"""Human approval queue.

Nothing sends from this engine without an explicit approve decision recorded
against the draft in the queue. Drafts wait as pending; a named reviewer
approves or rejects (rejections require a reason). Every decision is written
to the audit log IN THE SAME TRANSACTION as the state change, so the log can
never disagree with the queue. Re-enqueueing a pending draft refreshes its
content; a decided draft is never touched.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import dataclass
from enum import Enum

from engine.draft import Draft


class Decision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Approval:
    draft_id: str
    decision: Decision
    reviewer: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.reviewer.strip():
            raise ValueError("approval must name a reviewer")
        if self.decision is Decision.REJECTED and not (self.reason or "").strip():
            raise ValueError("rejections must record a reason")


QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    recipient TEXT NOT NULL,
    recipient_name TEXT,
    company TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    fit_points INTEGER NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer TEXT,
    reason TEXT,
    decided_at TEXT,
    exported_at TEXT,
    reasons TEXT
);
"""

# Columns added after the first schema version, for databases created before
# they existed. SQLite has no IF NOT EXISTS for columns, so probe by trying.
_MIGRATIONS = (
    "ALTER TABLE drafts ADD COLUMN recipient_name TEXT",
    "ALTER TABLE drafts ADD COLUMN exported_at TEXT",
    "ALTER TABLE drafts ADD COLUMN reasons TEXT",
)


def ensure_queue(conn: sqlite3.Connection) -> None:
    conn.executescript(QUEUE_SCHEMA)
    for migration in _MIGRATIONS:
        with contextlib.suppress(sqlite3.OperationalError):  # column already present
            conn.execute(migration)
    conn.commit()


OUTCOME_WORDS = {
    "enqueued": "waiting for your review",
    "updated": "updated - waiting for your review",
    "kept_decided": "already reviewed - keeping your decision",
}


def _audit_tx(conn: sqlite3.Connection, event: str, detail: str) -> None:
    """Audit write inside the caller's transaction - never commits on its own."""
    conn.execute("INSERT INTO audit (event, detail) VALUES (?, ?)", (event, detail))


def enqueue(conn: sqlite3.Connection, draft_id: str, draft: Draft) -> str:
    """Queue a draft. Returns 'enqueued', 'updated', or 'kept_decided'.

    A pending draft with the same id gets its content refreshed (re-drafted);
    a decided draft is left untouched, so an approval is never overwritten.
    State change and audit row commit in ONE transaction.
    """
    ensure_queue(conn)
    row = conn.execute("SELECT status FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is not None and row[0] != "pending":
        return "kept_decided"
    if row is None:
        outcome = "enqueued"
        conn.execute(
            "INSERT INTO drafts"
            " (id, recipient, recipient_name, company, subject, body, fit_points, provider,"
            " reasons)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                draft_id,
                draft.contact.email or "(unknown)",
                draft.contact.name,
                draft.contact.company,
                draft.subject,
                draft.body,
                draft.fit.points,
                draft.provider,
                json.dumps(list(draft.fit.reasons)),
            ),
        )
    else:
        outcome = "updated"
        conn.execute(
            "UPDATE drafts SET recipient_name = ?, subject = ?, body = ?, fit_points = ?,"
            " provider = ?, reasons = ? WHERE id = ?",
            (draft.contact.name, draft.subject, draft.body, draft.fit.points, draft.provider,
             json.dumps(list(draft.fit.reasons)), draft_id),
        )
    _audit_tx(
        conn,
        "draft_enqueued",
        f"id={draft_id} to={draft.contact.email} ({OUTCOME_WORDS[outcome]})",
    )
    conn.commit()
    return outcome


def pending(conn: sqlite3.Connection) -> list[dict[str, object]]:
    ensure_queue(conn)
    cur = conn.execute("SELECT * FROM drafts WHERE status = 'pending' ORDER BY id")
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def decide(conn: sqlite3.Connection, approval: Approval) -> None:
    """Record a decision and its audit row in ONE transaction."""
    ensure_queue(conn)
    row = conn.execute("SELECT status FROM drafts WHERE id = ?", (approval.draft_id,)).fetchone()
    if row is None:
        raise ValueError(f"no draft with id {approval.draft_id}")
    if row[0] != "pending":
        raise ValueError(f"draft {approval.draft_id} already {row[0]}")
    conn.execute(
        "UPDATE drafts SET status = ?, reviewer = ?, reason = ?,"
        " decided_at = datetime('now') WHERE id = ?",
        (approval.decision.value, approval.reviewer, approval.reason, approval.draft_id),
    )
    _audit_tx(
        conn,
        "draft_decision",
        f"id={approval.draft_id} {approval.decision.value} by={approval.reviewer}"
        + (f" reason={approval.reason}" if approval.reason else ""),
    )
    conn.commit()
