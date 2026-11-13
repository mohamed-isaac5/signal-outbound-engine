"""Sequencer export.

Approved drafts - and only approved drafts - export to a CSV shaped for
Smartlead / Instantly imports (email, first/last name, company, subject,
body). Each export marks its drafts so a re-run exports only newly approved
work; --all re-exports everything. Every export is audit-logged.

Names come from the queue itself (stored at enqueue), so the CSV is complete
without touching any upstream contact source.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from engine.approve import ensure_queue
from engine.store import log_event

# Column order matches Smartlead/Instantly import conventions.
CSV_COLUMNS = ["email", "first_name", "last_name", "company_name", "subject", "email_body"]


def _safe(cell: str) -> str:
    """Neutralize spreadsheet formula injection: a cell whose first character
    is = + - or @ executes as a formula when the CSV is opened in Excel or
    Google Sheets. Prefixing with a quote makes it inert text."""
    if cell[:1] in ("=", "+", "-", "@"):
        return "'" + cell
    return cell


def _split_name(full_name: str | None) -> tuple[str, str]:
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def export_approved(
    conn: sqlite3.Connection, out_path: Path, include_exported: bool = False
) -> int:
    """Write approved drafts to CSV. Returns the number exported."""
    ensure_queue(conn)
    where = "status = 'approved'"
    if not include_exported:
        where += " AND exported_at IS NULL"
    rows = conn.execute(
        "SELECT id, recipient, recipient_name, company, subject, body"
        f" FROM drafts WHERE {where} ORDER BY id"
    ).fetchall()
    with out_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for _id, recipient, name, company, subject, body in rows:
            first, last = _split_name(name)
            writer.writerow([_safe(v) for v in (recipient, first, last, company, subject, body)])
    for (draft_id, *_rest) in rows:
        conn.execute(
            "UPDATE drafts SET exported_at = datetime('now') WHERE id = ?", (draft_id,)
        )
    log_event(conn, "export", f"{len(rows)} approved draft(s) exported to {out_path}")
    return len(rows)
