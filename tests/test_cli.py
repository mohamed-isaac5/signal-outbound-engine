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


def test_draft_command_runs_end_to_end(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    signals, contacts, providers = demo_dir
    rc = main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--db", str(tmp_path / "draft.db"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "OFFLINE DEMO DRAFT" in out
    assert "sara.adel@northwind-demo.example" in out
    # Karim (Initech) is below threshold: skipped with a reason, never drafted
    assert "skipped Karim Nabil (Initech)" in out
    assert not any(
        line.startswith("TO:") and "initech" in line.lower() for line in out.splitlines()
    )
    # every skip is explained - nothing is silently dropped
    assert "skipped Mona Samir (Acme Corp)" in out


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


def test_anthropic_summary_is_not_labeled_offline(capsys, demo_dir, monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
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
            "--db", str(tmp_path / "anthropic.db"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    summary = [line for line in out.splitlines() if "draft(s) created" in line]
    assert summary and "provider 'anthropic'" in summary[0]
    assert OFFLINE_LABEL not in summary[0]


def test_offline_summary_carries_the_offline_label(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.llm import OFFLINE_LABEL

    signals, contacts, providers = demo_dir
    main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--db", str(tmp_path / "offline.db"),
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


def test_skipped_contact_without_email_reports_reason(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    """A qualified contact with no found email is skipped with a reason, not silently."""
    import json

    signals, contacts, providers = demo_dir
    rows = json.loads(contacts.read_text())
    # Northwind qualifies (55) - give Sara no provider data so no email is found
    contacts.write_text(json.dumps([r for r in rows if r["company"] == "Northwind Traders"]))
    empty_providers = providers.with_name("empty_providers.json")
    empty_providers.write_text(
        json.dumps({"providers": [{"name": "p", "unit_cost_usd": 0.01, "data": {}}]})
    )
    rc = main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(empty_providers),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped Sara Adel (Northwind Traders): no email found" in out
    assert "0 draft(s) created" in out


def test_readme_demo_output_matches_real_enrich_run(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    """Pin the README demo block to what `soe enrich` actually prints."""
    _, contacts, providers = demo_dir
    main(["enrich", "--contacts", str(contacts), "--providers", str(providers)])
    out = capsys.readouterr().out
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    for line in out.splitlines():
        if line.strip():
            assert line in readme, f"README demo output drifted from real output: {line!r}"


def test_enrich_command_writes_audit(capsys, tmp_path, demo_dir) -> None:  # type: ignore[no-untyped-def]
    import sqlite3

    _, contacts, providers = demo_dir
    db = tmp_path / "e.db"
    rc = main(
        ["enrich", "--contacts", str(contacts), "--providers", str(providers), "--db", str(db)]
    )
    assert rc == 0
    rows = sqlite3.connect(db).execute("SELECT event FROM audit").fetchall()
    assert len(rows) == 4 and all(r[0] == "enrichment" for r in rows)


def test_enrich_zero_found_omits_per_email_cost(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    import json

    _, contacts, providers = demo_dir
    empty = providers.with_name("empty_providers.json")
    empty.write_text(json.dumps({"providers": [{"name": "p", "unit_cost_usd": 0.01, "data": {}}]}))
    rc = main(["enrich", "--contacts", str(contacts), "--providers", str(empty)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "enriched 0/4" in out
    assert "per found email" not in out  # no division by zero, no fake precision


def test_draft_with_db_and_nothing_pending_prints_no_waiting(capsys, demo_dir) -> None:  # type: ignore[no-untyped-def]
    import json

    signals, contacts, providers = demo_dir
    rows = json.loads(contacts.read_text())
    contacts.write_text(json.dumps([r for r in rows if r["company"] == "Acme Corp"]))  # unqualified
    rc = main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--db", str(contacts.with_name("q.db")),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "0 draft(s) created" in out
    assert "waiting in the approval queue" not in out


def test_approve_list_prints_pending_rows(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    signals, contacts, providers = demo_dir
    db = tmp_path / "q.db"
    main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--db", str(db),
        ]
    )
    capsys.readouterr()
    assert main(["approve", "--db", str(db), "--list"]) == 0
    out = capsys.readouterr().out
    assert "Northwind Traders:sara.adel@northwind-demo.example" in out
    assert "-> sara.adel@northwind-demo.example" in out


def test_approve_without_args_on_empty_queue_is_a_noop(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    rc = main(["approve", "--db", str(tmp_path / "q.db")])
    assert rc == 0
    assert "queue is empty" in capsys.readouterr().out


def test_no_command_prints_help(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_approve_list_empty_queue_message(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert main(["approve", "--db", str(tmp_path / "fresh.db"), "--list"]) == 0
    assert "approval queue is empty" in capsys.readouterr().out


def test_demo_runs_the_whole_chain(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    signals, _, _ = demo_dir
    data_dir = signals.parent
    db = tmp_path / "demo.db"
    rc = main(["demo", "--data-dir", str(data_dir), "--db", str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    for section in ("1/4 SCORING", "2/4 ENRICHMENT", "3/4 DRAFTING", "4/4 THE HUMAN GATE"):
        assert section in out
    assert "No message was sent" in out
    assert "skipped Mona Samir (Acme Corp): outside ICP - industry 'retail' not in ICP" in out
    assert "skipped Karim Nabil (Initech): outside ICP - size 15 below ICP min 50" in out
    import sqlite3

    pending = sqlite3.connect(db).execute("SELECT count(*) FROM drafts WHERE status='pending'")
    assert pending.fetchone()[0] == 2
    # the demo is idempotent: a second run updates, never duplicates
    assert main(["demo", "--data-dir", str(data_dir), "--db", str(db)]) == 0
    assert (
        sqlite3.connect(db).execute("SELECT count(*) FROM drafts").fetchone()[0] == 2
    )


def test_demo_missing_fixtures_generates_them(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    rc = main(["demo", "--data-dir", str(tmp_path), "--db", str(tmp_path / "d.db")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No demo data found - generating fresh demo data" in out
    assert (tmp_path / "demo_signals.json").exists()


def test_audit_empty_log(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert main(["audit", "--db", str(tmp_path / "a.db")]) == 0
    assert "audit log is empty" in capsys.readouterr().out


def test_audit_unknown_draft_id_returns_2(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    rc = main(["audit", "--db", str(tmp_path / "a.db"), "--id", "nope"])
    assert rc == 2
    assert "no draft with id nope" in capsys.readouterr().out


def test_audit_traces_one_draft(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    signals, contacts, providers = demo_dir
    db = tmp_path / "q.db"
    main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--db", str(db),
        ]
    )
    main(
        [
            "approve",
            "--db", str(db),
            "--id", "Globex:omar.fathy@globex-demo.example",
            "--decision", "rejected",
            "--reviewer", "mohamed",
            "--reason", "risky email",
        ]
    )
    capsys.readouterr()
    rc = main(["audit", "--db", str(db), "--id", "Globex:omar.fathy@globex-demo.example"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "status=rejected by=mohamed" in out
    assert "reason=risky email" in out
    assert "draft queued" in out and "decision" in out  # friendly labels
    # the other draft's trail must not leak into this trace
    assert "Northwind" not in out


def test_export_without_approved_drafts(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    signals, contacts, providers = demo_dir
    db = tmp_path / "q.db"
    main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--db", str(db),
        ]
    )
    capsys.readouterr()
    rc = main(["export", "--db", str(db), "--out", str(tmp_path / "x.csv")])
    assert rc == 0
    assert "no approved drafts waiting" in capsys.readouterr().out


def test_export_success_message(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    signals, contacts, providers = demo_dir
    db = tmp_path / "q.db"
    main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--db", str(db),
        ]
    )
    main(
        [
            "approve",
            "--db", str(db),
            "--id", "Globex:omar.fathy@globex-demo.example",
            "--decision", "approved",
            "--reviewer", "mohamed",
        ]
    )
    capsys.readouterr()
    rc = main(["export", "--db", str(db), "--out", str(tmp_path / "x.csv")])
    assert rc == 0
    assert "exported 1 approved draft(s)" in capsys.readouterr().out


def test_audit_lists_events(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from engine.store import log_event, open_db

    db = tmp_path / "a.db"
    conn = open_db(db)
    log_event(conn, "scoring_run", "source=demo window=30d: Acme=55")
    assert main(["audit", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "scored" in out and "Acme=55" in out  # friendly label, raw detail


def test_audit_approved_without_reason_has_no_reason_line(capsys, demo_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    signals, contacts, providers = demo_dir
    db = tmp_path / "q.db"
    main(
        [
            "draft",
            "--signals", str(signals),
            "--contacts", str(contacts),
            "--providers", str(providers),
            "--db", str(db),
        ]
    )
    main(
        [
            "approve",
            "--db", str(db),
            "--id", "Globex:omar.fathy@globex-demo.example",
            "--decision", "approved",
            "--reviewer", "mohamed",
        ]
    )
    capsys.readouterr()
    assert main(["audit", "--db", str(db), "--id", "Globex:omar.fathy@globex-demo.example"]) == 0
    out = capsys.readouterr().out
    assert "status=approved by=mohamed" in out
    assert "  reason=" not in out


def test_demo_skips_qualified_contact_without_email(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import json

    from engine.demo_fixtures import write_all

    write_all(tmp_path)
    providers = tmp_path / "demo_enrichment.json"
    providers.write_text(
        json.dumps({"providers": [{"name": "p", "unit_cost_usd": 0.01, "data": {}}]})
    )
    rc = main(["demo", "--data-dir", str(tmp_path), "--db", str(tmp_path / "d.db")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped Sara Adel (Northwind Traders): no email found" in out
