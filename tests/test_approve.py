from datetime import datetime, timezone

import pytest

from engine.approve import Approval, Decision, decide, enqueue, pending
from engine.draft import Draft
from engine.enrich import Contact
from engine.icp import score_signals
from engine.signals import Signal, SignalType
from engine.store import open_db


def make_draft() -> Draft:
    signal = Signal(
        company="Acme",
        type=SignalType.HIRING,
        observed_at=datetime.now(tz=timezone.utc),
        source="demo",
    )
    fit = score_signals("Acme", [signal])
    return Draft(
        contact=Contact(name="Sara", company="Acme", email="sara@acme.example"),
        subject="s",
        body="b",
        fit=fit,
        provider="offline-template",
    )


def test_rejection_requires_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        Approval(draft_id="d1", decision=Decision.REJECTED, reviewer="mohamed")


def test_approval_requires_reviewer() -> None:
    with pytest.raises(ValueError, match="reviewer"):
        Approval(draft_id="d1", decision=Decision.APPROVED, reviewer=" ")


def test_queue_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_db(tmp_path / "q.db")
    enqueue(conn, "d1", make_draft())
    rows = pending(conn)
    assert len(rows) == 1
    assert rows[0]["recipient"] == "sara@acme.example"
    decide(conn, Approval(draft_id="d1", decision=Decision.APPROVED, reviewer="mohamed"))
    assert pending(conn) == []
    events = [r[0] for r in conn.execute("SELECT event FROM audit").fetchall()]
    assert "draft_enqueued" in events
    assert "draft_decision" in events


def test_double_decision_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_db(tmp_path / "q.db")
    enqueue(conn, "d1", make_draft())
    decide(conn, Approval(draft_id="d1", decision=Decision.APPROVED, reviewer="mohamed"))
    with pytest.raises(ValueError, match="already approved"):
        decide(conn, Approval(draft_id="d1", decision=Decision.APPROVED, reviewer="mohamed"))


def test_unknown_draft_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_db(tmp_path / "q.db")
    with pytest.raises(ValueError, match="no draft"):
        decide(conn, Approval(draft_id="nope", decision=Decision.APPROVED, reviewer="mohamed"))


def test_reenqueue_pending_updates_content_and_stays_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_db(tmp_path / "q.db")
    assert enqueue(conn, "d1", make_draft()) == "enqueued"
    refreshed = make_draft()
    object.__setattr__(refreshed, "subject", "new subject")
    assert enqueue(conn, "d1", refreshed) == "updated"
    rows = pending(conn)
    assert len(rows) == 1  # no duplicate, no IntegrityError
    assert rows[0]["subject"] == "new subject"


def test_reenqueue_decided_draft_keeps_decision(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = open_db(tmp_path / "q.db")
    enqueue(conn, "d1", make_draft())
    decide(conn, Approval(draft_id="d1", decision=Decision.APPROVED, reviewer="mohamed"))
    assert enqueue(conn, "d1", make_draft()) == "kept_decided"
    row = conn.execute("SELECT status, reviewer FROM drafts WHERE id = 'd1'").fetchone()
    assert row == ("approved", "mohamed")
