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


class _FakeMessages:
    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        class _Resp:
            content = [
                type("B", (), {"type": "text", "text": "Subject: quick question\n\nBody."})()
            ]

        return _Resp()


class _FakeAnthropicClient:
    messages = _FakeMessages()


def test_anthropic_summary_is_not_labeled_offline(capsys, demo_dir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The OFFLINE label must never appear on a real LLM provider's summary."""
    import engine.cli as cli
    from engine.llm import OFFLINE_LABEL, AnthropicProvider

    monkeypatch.setattr(
        cli, "AnthropicProvider", lambda: AnthropicProvider(client=_FakeAnthropicClient())
    )
    signals, contacts, providers = demo_dir
    rc = cli.main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--provider", "anthropic",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    summary = [line for line in out.splitlines() if "draft(s) created" in line]
    assert summary and "provider 'anthropic'" in summary[0]
    assert OFFLINE_LABEL not in summary[0]


def test_offline_summary_carries_the_offline_label(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    from engine.llm import OFFLINE_LABEL

    signals, contacts, providers = demo_dir
    main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
        ]
    )
    out = capsys.readouterr().out
    summary = [line for line in out.splitlines() if "draft(s) created" in line]
    assert summary and OFFLINE_LABEL in summary[0]


def test_waiting_count_reflects_the_actual_queue(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """After one draft is decided, a re-run must report the real pending count."""
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
    out = capsys.readouterr().out
    assert "2 draft(s) waiting in the approval queue." in out
    assert (
        main(
            [
                "approve",
                "--db", str(db),
                "--id", "Northwind Traders:sara.adel@northwind-demo.example",
                "--decision", "approved",
                "--reviewer", "mohamed",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(argv) == 0  # re-run: decided draft kept, pending one updated
    out = capsys.readouterr().out
    assert "1 draft(s) waiting in the approval queue." in out


def test_readme_demo_output_matches_real_enrich_run(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    """Pin the README demo block to what `soe enrich` actually prints."""
    _, contacts, providers = demo_dir
    main(["enrich", "--contacts", str(contacts), "--providers", str(providers)])
    out = capsys.readouterr().out
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    for line in out.splitlines():
        if line.strip():
            assert line in readme, f"README demo output drifted from real output: {line!r}"
