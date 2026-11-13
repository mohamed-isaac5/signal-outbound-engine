from pathlib import Path

import pytest

from engine.store import log_event, open_db


def test_log_event_persists(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "run.db")
    log_event(conn, "scored", "Acme +30 hiring")
    rows = conn.execute("SELECT event, detail FROM audit").fetchall()
    assert rows == [("scored", "Acme +30 hiring")]


def test_empty_event_rejected(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "run.db")
    with pytest.raises(ValueError):
        log_event(conn, " ", "detail")
