from pathlib import Path

import pytest

from engine.cli import main
from engine.demo_fixtures import write_all


@pytest.fixture()
def demo_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Fresh, run-relative demo fixtures - immune to fixture rot."""
    write_all(tmp_path)
    return (
        tmp_path / "demo_signals.json",
        tmp_path / "demo_contacts.json",
        tmp_path / "demo_enrichment.json",
    )


def test_version(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.count(".") == 2


def test_score_command_runs_end_to_end(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    signals, _, _ = demo_dir
    assert main(["score", "--source", str(signals)]) == 0
    out = capsys.readouterr().out
    assert "Northwind Traders" in out
    assert "REASONS" in out


def test_score_command_writes_audit(capsys, tmp_path, demo_dir) -> None:  # type: ignore[no-untyped-def]
    signals, _, _ = demo_dir
    db = tmp_path / "audit.db"
    assert main(["score", "--source", str(signals), "--db", str(db)]) == 0
    import sqlite3

    rows = sqlite3.connect(db).execute("SELECT event FROM audit").fetchall()
    assert rows and rows[0][0] == "scoring_run"


def test_enrich_command_runs_end_to_end(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    _, contacts, providers = demo_dir
    assert main(["enrich", "--contacts", str(contacts), "--providers", str(providers)]) == 0
    out = capsys.readouterr().out
    assert "sara.adel@northwind-demo.example" in out
    assert "per found email" in out
    assert "(unknown)" in out  # Karim Nabil honestly not found


def test_draft_command_runs_end_to_end(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    signals, contacts, providers = demo_dir
    rc = main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "OFFLINE DEMO DRAFT" in out
    assert "sara.adel@northwind-demo.example" in out
    # Karim (Initech) is below threshold AND unknown email - never drafted
    assert "Initech" not in out


def test_draft_command_is_idempotent_with_db(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    signals, contacts, providers = demo_dir
    db = tmp_path / "q.db"
    argv = [
        "draft",
        "--signals", str(signals),
        "--contacts", str(contacts),
        "--providers", str(providers),
        "--db", str(db),
    ]
    assert main(argv) == 0
    assert main(argv) == 0  # second run: no IntegrityError
