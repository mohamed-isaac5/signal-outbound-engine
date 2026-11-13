"""v1.5.0 UX layer: human-language drafts, friendly audit, guided flows."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.approve import enqueue
from engine.cli import EVENT_LABELS, _local_time, main
from engine.enrich import Contact
from engine.icp import FitScore
from engine.llm import SIGNAL_PHRASES, OfflineProvider, human_signal_phrases
from engine.runner import RunResult, _display_reasons, render_table
from engine.store import log_event, open_db

NOW = datetime.now(tz=timezone.utc)


def fit(reasons: tuple[str, ...], points: int = 55) -> FitScore:
    return FitScore(company="Globex", points=points, reasons=reasons)


def contact() -> Contact:
    return Contact(name="Omar Fathy", company="Globex", title="RevOps Lead")


# ---- human-language drafts ---------------------------------------------------


def test_every_signal_type_has_a_human_phrase() -> None:
    from engine.signals import SignalType

    assert set(SIGNAL_PHRASES) == {t.value for t in SignalType}
    for phrase in SIGNAL_PHRASES.values():
        assert phrase.islower() or phrase[0].islower()  # slots mid-sentence


def test_phrases_dedupe_and_skip_icp_boosts() -> None:
    reasons = (
        "+30 hiring (demo-file)",
        "+30 hiring (demo-file)",
        "+10 icp_industry (saas)",
        "+5 icp_size (80)",
    )
    assert human_signal_phrases(reasons) == ["you're hiring for key roles"]


def test_phrases_unknown_kind_falls_back() -> None:
    assert human_signal_phrases(("+9 press_mention (demo-file)",)) == ["we noticed press mention"]
    assert human_signal_phrases(("",)) == []


def test_offline_draft_reads_like_a_human_email() -> None:
    d = OfflineProvider().draft(
        contact(), fit(("+30 hiring (demo-file)", "+10 icp_industry (saas)"))
    )
    assert d.subject == "Globex: hiring"
    assert "at Globex you're hiring for key roles" in d.body
    assert "icp_industry" not in d.body
    assert "+" not in d.body.split("\n")[2] or "OFFLINE" in d.body.split("\n")[0]


def test_offline_draft_without_signals_still_reads() -> None:
    d = OfflineProvider().draft(contact(), fit(()))
    assert "showing movement we track" in d.body


# ---- score table cleanup ------------------------------------------------------


def test_table_says_source_once_and_strips_it_from_reasons() -> None:
    result = RunResult(
        source="demo-file",
        window_days=30,
        scores=(fit(("+30 hiring (demo-file)", "+10 icp_industry (saas)")),),
    )
    table = render_table(result)
    assert "source: demo-file, last 30 days" in table
    assert "+30 hiring" in table  # the point reason survives
    assert "(demo-file)" not in table  # but the repeated source is gone
    assert "+10 icp_industry (saas)" in table  # icp parenthetical is NOT stripped


def test_display_reasons_only_strips_exact_source() -> None:
    f = fit(("+30 hiring (other-source)",))
    assert _display_reasons(f, "demo-file") == "+30 hiring (other-source)"


# ---- friendly audit ------------------------------------------------------------


def test_local_time_converts_utc() -> None:
    shown = _local_time("2026-11-13 14:30:00")
    assert re.match(r"^2026-11-13 \d{2}:\d{2} \S+$", shown)
    assert _local_time("garbage") == "garbage"


def test_event_labels_cover_known_events() -> None:
    assert EVENT_LABELS["scoring_run"] == "scored"
    assert EVENT_LABELS["draft_decision"] == "decision"


def test_audit_listing_shows_labels_and_local_time(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    db = tmp_path / "a.db"
    conn = open_db(db)
    log_event(conn, "scoring_run", "source=demo window=30d: Acme=55")
    assert main(["audit", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "scored" in out and "scoring_run" not in out
    assert re.search(r"\d{2}:\d{2} \S+\s", out)


# ---- welcome screen ------------------------------------------------------------


def test_welcome_is_quiet_without_state(capsys: pytest.CaptureFixture[str], tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "soe run" in out and "waiting for your review" not in out


def test_welcome_surfaces_waiting_drafts(capsys: pytest.CaptureFixture[str], tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--db", "run.db"]) == 0
    capsys.readouterr()
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "2 draft(s) waiting for your review - soe approve" in out


# ---- review: the why option ------------------------------------------------------


def test_review_why_prints_point_breakdown(capsys: pytest.CaptureFixture[str],
                                           tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = open_db(tmp_path / "q.db")
    from engine.draft import Draft

    f = fit(("+20 tech_change (demo-file)", "+30 hiring (demo-file)"), points=50)
    enqueue(conn, "Globex:omar@globex.example", Draft(contact=contact(), subject="s",
                                                      body="b", fit=f, provider="offline-template"))
    it = iter(["w", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    from engine.onboard import review_queue

    approved, _, _ = review_queue(conn, "mohamed")
    assert approved == 1
    out = capsys.readouterr().out
    assert "Why Globex scored 50, point by point:" in out
    assert "+30 hiring (demo-file)" in out  # the audit-grade breakdown, on demand


def test_review_why_without_stored_reasons(capsys: pytest.CaptureFixture[str],
                                           tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    conn = open_db(tmp_path / "q.db")
    from engine.approve import ensure_queue

    ensure_queue(conn)
    conn.execute(
        "INSERT INTO drafts (id, recipient, company, subject, body, fit_points, provider)"
        " VALUES ('x', 'a@b.c', 'Acme', 's', 'b', 55, 'p')"
    )
    conn.commit()
    it = iter(["w", "s"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    from engine.onboard import review_queue

    review_queue(conn, "mohamed")
    assert "No point-by-point breakdown available" in capsys.readouterr().out


def test_piped_answers_are_echoed(capsys: pytest.CaptureFixture[str],
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "my-answer")
    from engine.onboard import _ask

    assert _ask("Q: ") == "my-answer"
    assert "my-answer" in capsys.readouterr().out  # transcripts stay readable


# ---- setup recap and icp show ---------------------------------------------------


def feed(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def test_setup_recap_can_abort(capsys: pytest.CaptureFixture[str], tmp_path: Path,
                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    feed(monkeypatch, ["", "", "", "", "", "", "", "", "", "n"])
    assert main(["icp", "setup"]) == 0
    out = capsys.readouterr().out
    assert "(not saved yet)" in out
    assert "Nothing written" in out
    assert not (tmp_path / "icp.toml").exists()


def test_icp_show_explains_what_the_profile_does(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["icp", "show"]) == 0
    out = capsys.readouterr().out
    assert "This profile filters" in out and "soe run" in out


# ---- command headers and demo positioning ---------------------------------------


def test_score_and_draft_print_plain_headers(capsys: pytest.CaptureFixture[str],
                                             tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from engine import demo_fixtures

    demo_fixtures.write_all(tmp_path / "data")
    assert main(["score"]) == 0
    assert "Scoring: points for fresh buying signals" in capsys.readouterr().out
    assert main(["draft", "--db", str(tmp_path / "d.db")]) == 0
    out = capsys.readouterr().out
    assert "Drafting: one email per qualified, reachable contact" in out


def test_demo_positions_itself(capsys: pytest.CaptureFixture[str], tmp_path: Path,
                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from engine import demo_fixtures

    demo_fixtures.write_all(tmp_path / "data")
    assert main(["demo", "--data-dir", str(tmp_path / "data"),
                 "--db", str(tmp_path / "d.db")]) == 0
    out = capsys.readouterr().out
    assert "WATCH mode" in out and "soe guide" in out


def test_no_developer_speak_in_user_paths(capsys, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A non-engineer must never be told to run python -m anything."""
    main(["demo", "--data-dir", str(tmp_path), "--db", str(tmp_path / "d.db")])
    out = capsys.readouterr().out
    assert "python -m" not in out
    assert "demo_fixtures" not in out
