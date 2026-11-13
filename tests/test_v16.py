"""v1.6.0: adversarial-review round - corrupted db, human subjects, sender identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.cli import main
from engine.enrich import Contact
from engine.icp import FitScore
from engine.icp_config import load_icp, render_icp, write_icp
from engine.llm import SUBJECT_PHRASES, OfflineProvider, join_english, subject_for
from engine.store import open_db


def fit(reasons: tuple[str, ...], points: int = 55) -> FitScore:
    return FitScore(company="Globex", points=points, reasons=reasons)


def contact() -> Contact:
    return Contact(name="Omar Fathy", company="Globex", title="RevOps Lead")


def feed(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


# ---- B1: a corrupted database never shows a traceback --------------------------


def test_corrupted_db_fails_cleanly_on_every_command(capsys: pytest.CaptureFixture[str],
                                                     tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "run.db").write_text("this is not a database")
    for command in (["approve"], ["export"], ["audit"], ["run"]):
        capsys.readouterr()
        rc = main(command)
        out = capsys.readouterr().out
        assert rc == 2, command
        assert "damaged or is not a database" in out, command
        assert "Traceback" not in out, command
        assert "soe run" in out, command


# ---- B2: the guide counts its steps honestly -----------------------------------


def test_guide_says_four_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["guide", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "four steps" in out
    assert "five steps" not in out
    assert "Step 4/4" in out


# ---- B3: audit --id keeps one clock on screen ----------------------------------


def test_audit_id_header_uses_local_time(capsys: pytest.CaptureFixture[str],
                                         tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["run"]) == 0
    feed(monkeypatch, ["y", "y"])
    assert main(["approve"]) == 0
    capsys.readouterr()
    assert main(["audit", "--id", "Globex:omar.fathy@globex-demo.example"]) == 0
    out = capsys.readouterr().out
    header = next(line for line in out.splitlines() if "by=" in line and "trail" not in line)
    assert "EET" in header or "UTC" in header or "+" in header  # tz-labeled like the trail
    assert "at=20" in header and " " in header.split("at=")[1]  # "at=<local date time TZ>"


# ---- I1: subjects speak human ---------------------------------------------------


def test_every_signal_type_has_a_subject_fragment() -> None:
    from engine.signals import SignalType

    assert set(SUBJECT_PHRASES) == {t.value for t in SignalType}
    for fragment in SUBJECT_PHRASES.values():
        assert len(fragment) <= 20  # subjects stay scannable


def test_subject_combines_two_signals_and_skips_icp() -> None:
    reasons = ("+30 hiring (demo-file)", "+25 funding (demo-file)", "+10 icp_industry (saas)")
    assert subject_for("Globex", reasons) == "Globex: hiring + new funding"
    assert "signals" not in subject_for("Globex", reasons)


def test_subject_caps_at_two_fragments() -> None:
    reasons = (
        "+30 hiring (demo-file)",
        "+25 funding (demo-file)",
        "+20 tech_change (demo-file)",
    )
    assert subject_for("Globex", reasons) == "Globex: hiring + new funding"


def test_subject_falls_back_to_quick_question() -> None:
    assert subject_for("Globex", ()) == "Globex: quick question"
    assert subject_for("Globex", ("+10 icp_size (80)",)) == "Globex: quick question"


# ---- I2: lists join like English -------------------------------------------------


def test_join_english() -> None:
    assert join_english([]) == ""
    assert join_english(["a"]) == "a"
    assert join_english(["a", "b"]) == "a and b"
    assert join_english(["a", "b", "c"]) == "a, b and c"


def test_multi_signal_body_joins_naturally() -> None:
    d = OfflineProvider().draft(
        contact(), fit(("+20 tech_change (demo-file)", "+30 hiring (demo-file)"))
    )
    assert "you're changing your tech stack and you're hiring for key roles" in d.body
    assert " - and " not in d.body


# ---- I3: sender identity ----------------------------------------------------------


def test_default_signature_stays_the_labeled_demo() -> None:
    d = OfflineProvider().draft(contact(), fit(("+30 hiring (demo-file)",)))
    assert d.body.rstrip().endswith("- signal-outbound-engine demo")


def test_sender_name_signs_the_email() -> None:
    d = OfflineProvider(sender_name="Mohamed").draft(contact(), fit(("+30 hiring (demo-file)",)))
    assert d.body.rstrip().endswith("- Mohamed")
    assert "signal-outbound-engine demo" not in d.body


def test_sender_name_roundtrips_through_toml(tmp_path: Path) -> None:
    from tests.test_icp_config import make_icp

    icp = make_icp()
    path = tmp_path / "icp.toml"
    write_icp(icp, path)
    assert load_icp(path).sender_name == icp.sender_name
    assert "email signature:" in render_icp(icp, "icp.toml")


def test_sender_name_must_be_non_empty_when_present(tmp_path: Path) -> None:
    from engine.icp_config import ICPError

    path = tmp_path / "icp.toml"
    path.write_text('name = "x"\nsender_name = "  "\n')
    with pytest.raises(ICPError, match="sender_name"):
        load_icp(path)


# ---- I4: no machine tokens in user-facing output -----------------------------------


def test_run_prints_outcome_words_not_tokens(capsys: pytest.CaptureFixture[str],
                                             tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["run"]) == 0
    feed(monkeypatch, ["y", "y"])
    assert main(["approve"]) == 0
    capsys.readouterr()
    assert main(["run"]) == 0  # re-run: decisions are kept
    out = capsys.readouterr().out
    assert "already reviewed - keeping your decision" in out
    assert "[kept_decided]" not in out
    assert "[enqueued]" not in out


def test_audit_shows_queued_for_review(capsys: pytest.CaptureFixture[str],
                                       tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["run"]) == 0
    capsys.readouterr()
    assert main(["audit"]) == 0
    out = capsys.readouterr().out
    assert "(waiting for your review)" in out
    assert "(enqueued)" not in out


def test_audit_listing_humanizes_legacy_enqueued_rows(capsys: pytest.CaptureFixture[str],
                                                      tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows written before v1.6.0 carry '(enqueued)'; the listing still reads human."""
    monkeypatch.chdir(tmp_path)
    conn = open_db(tmp_path / "run.db")
    from engine.store import log_event

    log_event(conn, "draft_enqueued", "id=x to=a@b.c (enqueued)")
    conn.close()
    assert main(["audit"]) == 0
    out = capsys.readouterr().out
    assert "(waiting for your review)" in out
    assert "(enqueued)" not in out


# ---- I5: no invented question counts ------------------------------------------------


def test_no_question_count_claim() -> None:
    import engine.icp_config as mod

    source = Path(mod.__file__).read_text()
    assert "6 questions" not in source


# ---- I6: the example label never becomes the user's ICP name -------------------------


def test_setup_default_name_is_my_icp(capsys: pytest.CaptureFixture[str],
                                      tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    feed(monkeypatch, [""] * 10)
    assert main(["icp", "setup"]) == 0
    out = capsys.readouterr().out
    assert "ICP: My ICP" in out  # the example label never becomes the user's name
    assert "Example: mid-market" not in out
    assert load_icp(tmp_path / "icp.toml").name == "My ICP"


# ---- I7: why on a legacy draft recomputes instead of dead-ending ----------------------


def test_why_on_legacy_draft_recomputes(capsys: pytest.CaptureFixture[str],
                                        tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from engine import demo_fixtures
    from engine.approve import ensure_queue

    demo_fixtures.write_all(tmp_path / "data")
    conn = open_db(tmp_path / "q.db")
    ensure_queue(conn)
    conn.execute(
        "INSERT INTO drafts (id, recipient, company, subject, body, fit_points, provider)"
        " VALUES ('x', 'a@b.c', 'Globex', 's', 'b', 70, 'p')"
    )
    conn.commit()
    feed(monkeypatch, ["w", "s"])
    from engine.onboard import review_queue

    review_queue(conn, "mohamed", data_dir=tmp_path / "data")
    out = capsys.readouterr().out
    assert "point by point" in out
    assert "+30 hiring (demo-file)" in out


# ---- v1.6.1: hostile input never corrupts icp.toml -------------------------------


def test_toml_escaping_roundtrip_hostile_strings(tmp_path: Path) -> None:
    from engine.icp_config import ICP, _toml_str

    quote_name = 'Mo "Mo" Isaac'
    backslash_name = "C:" + chr(92) + "new path"
    formula_industry = '=HYPERLINK("http://evil","click")'
    icp = ICP(
        name=backslash_name,
        industries=(formula_industry, "sa as"),
        size_min=1,
        size_max=9,
        countries=("US",),
        target_roles=("vp",),
        signal_weights=None,
        exclude_industries=(),
        sender_name=quote_name,
    )
    path = tmp_path / "icp.toml"
    write_icp(icp, path)
    back = load_icp(path)  # must parse AND preserve every byte
    assert back.name == backslash_name
    assert back.sender_name == quote_name
    assert back.industries == (formula_industry, "sa as")
    assert _toml_str('a"b') == '"a' + chr(92) + '"b"'
    assert _toml_str("a" + chr(92) + "b") == '"a' + chr(92) * 2 + 'b"'


def test_setup_with_quoted_answer_writes_valid_toml(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    feed(monkeypatch,
         ['My " Agency', '=HYPERLINK("x","y")', "50", "500", "US", "vp", "", "", "", ""])
    assert main(["icp", "setup"]) == 0
    icp = load_icp(tmp_path / "icp.toml")  # would raise on the pre-fix build
    assert icp.name == 'My " Agency'
    # list answers comma-split by design; the quotes must still roundtrip safely
    assert icp.industries == ('=HYPERLINK("x"', '"y")')


def test_icp_edit_offers_email_signature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    from tests.test_icp_config import make_icp

    write_icp(make_icp(), tmp_path / "icp.toml")
    feed(monkeypatch, ["8", "Mo Isaac"])
    assert main(["icp", "edit"]) == 0
    out = capsys.readouterr().out
    assert "email signature" in out
    assert load_icp(tmp_path / "icp.toml").sender_name == "Mo Isaac"


def test_icp_edit_signature_back_to_demo(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    from tests.test_icp_config import make_icp

    write_icp(make_icp(), tmp_path / "icp.toml")
    feed(monkeypatch, ["8", "demo signature"])
    assert main(["icp", "edit"]) == 0
    assert load_icp(tmp_path / "icp.toml").sender_name is None
