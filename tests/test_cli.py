from pathlib import Path

from engine.cli import main

FIXTURE = Path(__file__).resolve().parent.parent / "data" / "demo_signals.json"
CONTACTS = Path(__file__).resolve().parent.parent / "data" / "demo_contacts.json"
PROVIDERS = Path(__file__).resolve().parent.parent / "data" / "demo_enrichment.json"


def test_version(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.count(".") == 2


def test_score_command_runs_end_to_end(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["score", "--source", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "Northwind Traders" in out
    assert "REASONS" in out


def test_score_command_writes_audit(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = tmp_path / "audit.db"
    assert main(["score", "--source", str(FIXTURE), "--db", str(db)]) == 0
    import sqlite3

    rows = sqlite3.connect(db).execute("SELECT event FROM audit").fetchall()
    assert rows and rows[0][0] == "scoring_run"


def test_enrich_command_runs_end_to_end(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["enrich", "--contacts", str(CONTACTS), "--providers", str(PROVIDERS)]) == 0
    out = capsys.readouterr().out
    assert "sara.adel@northwind-demo.example" in out
    assert "per found email" in out
    assert "(unknown)" in out  # Karim Nabil honestly not found


def test_placeholder_subcommand(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["draft"]) == 0
    assert "milestone" in capsys.readouterr().out
