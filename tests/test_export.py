import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from engine.approve import Approval, Decision, decide, enqueue
from engine.draft import Draft
from engine.enrich import Contact
from engine.export import _safe, _split_name, export_approved
from engine.icp import score_signals
from engine.signals import Signal, SignalType
from engine.store import open_db


def make_draft(name: str = "Sara Adel", email: str = "sara@acme.example") -> Draft:
    signal = Signal(
        company="Acme",
        type=SignalType.HIRING,
        observed_at=datetime.now(tz=timezone.utc),
        source="demo",
    )
    return Draft(
        contact=Contact(name=name, company="Acme", email=email),
        subject="s",
        body="line one\nline two",  # multiline body must survive CSV quoting
        fit=score_signals("Acme", [signal]),
        provider="offline-template",
    )


def approve(conn: sqlite3.Connection, draft_id: str) -> None:
    decide(conn, Approval(draft_id=draft_id, decision=Decision.APPROVED, reviewer="mohamed"))


def test_export_writes_only_approved(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "q.db")
    enqueue(conn, "d1", make_draft())
    enqueue(conn, "d2", make_draft(email="omar@acme.example"))
    enqueue(conn, "d3", make_draft(email="mona@acme.example"))
    approve(conn, "d1")
    decide(
        conn,
        Approval(
            draft_id="d2", decision=Decision.REJECTED, reviewer="mohamed", reason="no"
        ),
    )
    # d3 stays pending
    out = tmp_path / "export.csv"
    assert export_approved(conn, out) == 1
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["email", "first_name", "last_name", "company_name", "subject", "email_body"]
    assert [r[0] for r in rows[1:]] == ["sara@acme.example"]
    # name split for the sequencer
    assert rows[1][1:3] == ["Sara", "Adel"]
    # multiline body survives round-trip
    assert rows[1][5] == "line one\nline two"


def test_export_marks_exported_and_all_flag_recovers(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "q.db")
    enqueue(conn, "d1", make_draft())
    approve(conn, "d1")
    assert export_approved(conn, tmp_path / "a.csv") == 1
    assert export_approved(conn, tmp_path / "b.csv") == 0  # nothing new
    assert export_approved(conn, tmp_path / "c.csv", include_exported=True) == 1
    # the export itself is audit-logged
    events = [r[0] for r in conn.execute("SELECT event FROM audit").fetchall()]
    assert "export" in events


def test_export_works_on_a_pre_migration_database(tmp_path: Path) -> None:
    """A queue created before recipient_name/exported_at existed still exports."""
    db = tmp_path / "old.db"
    conn = open_db(db)  # every real database has the audit table; drafts predate the new columns
    conn.executescript(
        """
        CREATE TABLE drafts (
            id TEXT PRIMARY KEY,
            recipient TEXT NOT NULL,
            company TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            fit_points INTEGER NOT NULL,
            provider TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewer TEXT,
            reason TEXT,
            decided_at TEXT
        );
        INSERT INTO drafts (id, recipient, company, subject, body, fit_points, provider, status)
        VALUES ('d1', 'sara@acme.example', 'Acme', 's', 'b', 55, 'offline-template', 'approved');
        """
    )
    conn.commit()
    assert export_approved(conn, tmp_path / "old.csv") == 1
    rows = list(csv.reader((tmp_path / "old.csv").open()))
    assert rows[1][0] == "sara@acme.example"
    assert rows[1][1] == ""  # no name stored pre-migration - empty, not invented


def test_split_name_edge_cases() -> None:
    assert _split_name(None) == ("", "")
    assert _split_name("  ") == ("", "")
    assert _split_name("Sara") == ("Sara", "")
    assert _split_name("Sara Adel Gamal") == ("Sara", "Adel Gamal")


def test_export_neutralizes_spreadsheet_formula_injection(tmp_path: Path) -> None:
    """A company named '=HYPERLINK(...)' must export as inert text, not a formula."""
    conn = open_db(tmp_path / "q.db")
    evil = '=HYPERLINK("http://evil.example")'
    signal = Signal(
        company=evil,
        type=SignalType.HIRING,
        observed_at=datetime.now(tz=timezone.utc),
        source="demo",
    )
    draft = Draft(
        contact=Contact(name="Sara Evil", company=evil, email="s@e.example"),
        subject=f"{evil}: subject",
        body="body",
        fit=score_signals(evil, [signal]),
        provider="offline-template",
    )
    enqueue(conn, "d1", draft)
    approve(conn, "d1")
    assert export_approved(conn, tmp_path / "x.csv") == 1
    rows = list(csv.reader((tmp_path / "x.csv").open()))
    for cell in rows[1]:
        assert cell[:1] not in ("=", "+", "-", "@"), f"formula-injectable cell: {cell!r}"
    assert rows[1][3] == "'" + evil  # value preserved, prefixed


def test_safe_cell_rules() -> None:
    assert _safe("=1+1") == "'=1+1"
    assert _safe("+43") == "'+43"
    assert _safe("-x") == "'-x"
    assert _safe("@x") == "'@x"
    assert _safe("sara@acme.example") == "sara@acme.example"
    assert _safe("") == ""
