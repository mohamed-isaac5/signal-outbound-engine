"""UX layer: soe run / soe guide / interactive approve / welcome / defaults / hints."""

import sqlite3
from pathlib import Path

import pytest

from engine.cli import build_parser, main
from engine.demo_fixtures import write_all


@pytest.fixture()
def workdir(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """A cold directory, like a fresh clone: no data/, no run.db."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def datadir(workdir):  # type: ignore[no-untyped-def]
    """A workdir with the demo data already generated."""
    write_all(Path("data"))
    return workdir


def _answers(monkeypatch, answers: list[str]) -> None:  # type: ignore[no-untyped-def]
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def _rows(db: Path) -> dict[str, tuple]:  # type: ignore[type-arg]
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT id, status, reviewer, reason FROM drafts").fetchall()
    conn.close()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


GLOBEX = "Globex:omar.fathy@globex-demo.example"
NORTHWIND = "Northwind Traders:sara.adel@northwind-demo.example"


# ---- welcome and help ----


def test_welcome_on_no_args(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Usage" in out
    assert "soe run" in out
    assert "soe guide" in out
    assert "soe --help" in out


def test_help_shows_the_start_here_section(capsys) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Start here" in out
    assert "soe guide" in out


def test_subcommand_help_carries_examples(capsys) -> None:  # type: ignore[no-untyped-def]
    for cmd in ("run", "guide", "score", "enrich", "draft", "approve", "export", "audit"):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args([cmd, "--help"])
        assert exc.value.code == 0
        assert "examples:" in capsys.readouterr().out


# ---- soe run ----


def test_run_end_to_end_cold(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    """Zero flags, empty directory: run does everything and says what's next."""
    assert main(["run"]) == 0
    out = capsys.readouterr().out
    assert "SOE RUN" in out
    assert "No demo data found - generating fresh demo data" in out
    for step in ("Step 1/3 - SCORING", "Step 2/3 - ENRICHMENT", "Step 3/3 - DRAFTING"):
        assert step in out
    assert "RUN COMPLETE - 2 draft(s) waiting for your review." in out
    assert "Next step:  soe approve" in out
    assert (workdir / "data" / "demo_signals.json").exists()
    conn = sqlite3.connect(workdir / "run.db")
    assert conn.execute("SELECT count(*) FROM drafts WHERE status='pending'").fetchone()[0] == 2
    events = {r[0] for r in conn.execute("SELECT DISTINCT event FROM audit")}
    conn.close()
    assert {"scoring_run", "enrichment", "draft_created", "draft_enqueued"} <= events


def test_run_twice_reports_real_pending_count(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    assert main(["run"]) == 0
    capsys.readouterr()
    assert main(["approve", "--id", GLOBEX, "--decision", "approved", "--reviewer", "mohamed"]) == 0
    capsys.readouterr()
    assert main(["run"]) == 0
    out = capsys.readouterr().out
    assert "RUN COMPLETE - 1 draft(s) waiting" in out


# ---- soe guide ----


def test_guide_yes_end_to_end(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    rc = main(["guide", "--yes", "--reviewer", "mohamed"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Welcome to the guided run" in out
    for step in ("Step 1/4 - SCORING", "Step 2/4 - ENRICHMENT", "Step 3/4 - DRAFTING",
                 "Step 4/4 - YOUR REVIEW"):
        assert step in out
    assert "approved by mohamed (--yes) - audit-logged" in out
    assert "Review done: 2 approved, 0 rejected, 0 pending." in out
    assert "DONE - here is exactly what you got" in out
    assert "approved.csv" in out
    assert "Smartlead" in out
    csv_text = (workdir / "approved.csv").read_text()
    assert csv_text.count("\n") >= 2  # header + rows (body newlines are quoted)
    rows = _rows(workdir / "run.db")
    assert rows[GLOBEX][0] == "approved" and rows[GLOBEX][1] == "mohamed"
    assert rows[NORTHWIND][0] == "approved"


def test_guide_interactive_approve_and_reject(capsys, workdir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Full walkthrough with a human answering: approve one, reject one with a reason."""
    _answers(monkeypatch, ["", "", "", "y", "n", "weak fit"])
    rc = main(["guide", "--reviewer", "mohamed"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Draft 1 of 2" in out
    assert "Review done: 1 approved, 1 rejected, 0 pending." in out
    rows = _rows(workdir / "run.db")
    # queue order is alphabetical by id: Globex first, then Northwind
    assert rows[GLOBEX] == ("approved", "mohamed", None)
    assert rows[NORTHWIND] == ("rejected", "mohamed", "weak fit")
    csv_text = (workdir / "approved.csv").read_text()
    assert "omar.fathy@globex-demo.example" in csv_text
    assert "sara.adel@northwind-demo.example" not in csv_text


def test_guide_reject_all_shows_the_no_export_summary(capsys, workdir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _answers(monkeypatch, ["", "", "", "n", "off ICP", "n", "bad timing"])
    rc = main(["guide", "--reviewer", "mohamed"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Review done: 0 approved, 2 rejected, 0 pending." in out
    assert "No approved drafts to export yet - approve some first: soe approve" in out


def test_guide_non_interactive_without_yes(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    """Piped stdin (no terminal): refuse politely with the two ways forward."""
    rc = main(["guide"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "soe guide --yes" in out
    assert "soe run" in out


# ---- interactive approve ----


def test_interactive_approve_approve_and_skip(capsys, workdir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert main(["run"]) == 0
    capsys.readouterr()
    _answers(monkeypatch, ["y", "s"])
    assert main(["approve", "--reviewer", "mohamed"]) == 0
    out = capsys.readouterr().out
    assert "Draft 1 of 2" in out
    assert "-> left pending (still in your queue)" in out
    assert "Queue done: 1 approved, 0 rejected, 1 still pending." in out
    assert "Next: soe export" in out
    rows = _rows(workdir / "run.db")
    assert rows[GLOBEX] == ("approved", "mohamed", None)
    assert rows[NORTHWIND][0] == "pending"


def test_interactive_approve_reject_requires_a_reason(capsys, workdir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert main(["run"]) == 0
    capsys.readouterr()
    # empty reason -> re-asked; second draft approved
    _answers(monkeypatch, ["n", "", "not a fit", "y"])
    assert main(["approve", "--reviewer", "mohamed"]) == 0
    out = capsys.readouterr().out
    assert "A rejection needs a reason" in out
    rows = _rows(workdir / "run.db")
    assert rows[GLOBEX] == ("rejected", "mohamed", "not a fit")
    assert rows[NORTHWIND][0] == "approved"


def test_interactive_approve_reprompts_on_bad_answer(capsys, workdir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert main(["run"]) == 0
    capsys.readouterr()
    _answers(monkeypatch, ["maybe", "y", "s"])
    assert main(["approve", "--reviewer", "mohamed"]) == 0
    out = capsys.readouterr().out
    assert "Please answer y, n or s." in out


def test_interactive_approve_empty_queue(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    assert main(["approve"]) == 0
    out = capsys.readouterr().out
    assert "Your review queue is empty" in out


def test_approve_non_interactive_points_to_flags(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    """No terminal and no --id: explain the flag path (rc 2)."""
    assert main(["run"]) == 0
    capsys.readouterr()
    rc = main(["approve"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "--id" in out
    assert "--decision" in out


# ---- zero-flag defaults and next-step hints ----


def test_score_zero_flags_and_hint(capsys, datadir) -> None:  # type: ignore[no-untyped-def]
    assert main(["score"]) == 0
    out = capsys.readouterr().out
    assert "Northwind Traders" in out
    assert "Next: soe enrich" in out


def test_score_missing_inputs_is_friendly(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    rc = main(["score"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "missing data/demo_signals.json" in out
    assert "soe run" in out


def test_enrich_zero_flags_and_hint(capsys, datadir) -> None:  # type: ignore[no-untyped-def]
    assert main(["enrich"]) == 0
    out = capsys.readouterr().out
    assert "per found email" in out
    assert "Next: soe draft" in out


def test_draft_zero_flags_fills_run_db(capsys, datadir) -> None:  # type: ignore[no-untyped-def]
    assert main(["draft"]) == 0
    out = capsys.readouterr().out
    assert "2 draft(s) waiting in the approval queue." in out
    assert "Review with: soe approve --db run.db" in out
    conn = sqlite3.connect(datadir / "run.db")
    assert conn.execute("SELECT count(*) FROM drafts WHERE status='pending'").fetchone()[0] == 2
    conn.close()


def test_export_zero_flags_and_next_step(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    assert main(["run"]) == 0
    capsys.readouterr()
    assert main(["approve", "--id", GLOBEX, "--decision", "approved", "--reviewer", "mohamed"]) == 0
    capsys.readouterr()
    assert main(["export"]) == 0
    out = capsys.readouterr().out
    assert "exported 1 approved draft(s) to approved.csv" in out
    assert "Next: upload approved.csv in Smartlead/Instantly" in out
    assert (workdir / "approved.csv").exists()


def test_export_empty_queue_guides_to_approve(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    assert main(["run"]) == 0
    capsys.readouterr()
    assert main(["export"]) == 0
    out = capsys.readouterr().out
    assert "no approved drafts waiting for export" in out
    assert "Approve some first: soe approve" in out


def test_approve_decision_hint_points_to_export(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    assert main(["run"]) == 0
    capsys.readouterr()
    assert main(["approve", "--id", GLOBEX, "--decision", "approved", "--reviewer", "mohamed"]) == 0
    out = capsys.readouterr().out
    assert "Next: soe export" in out


def test_default_reviewer_falls_back(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from engine.onboard import default_reviewer

    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    assert default_reviewer() == "me"
    monkeypatch.setenv("USERNAME", "winuser")
    assert default_reviewer() == "winuser"
    monkeypatch.setenv("USER", "unixuser")
    assert default_reviewer() == "unixuser"


def test_guide_yes_twice_second_run_says_already_exported(capsys, workdir) -> None:  # type: ignore[no-untyped-def]
    assert main(["guide", "--yes", "--reviewer", "mohamed"]) == 0
    capsys.readouterr()
    assert main(["guide", "--yes", "--reviewer", "mohamed"]) == 0
    out = capsys.readouterr().out
    assert "already holds your exported approved emails" in out
    assert "No approved drafts to export yet" not in out
