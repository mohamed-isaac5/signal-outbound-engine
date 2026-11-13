"""ICP config: loading, validation, matching, CLI commands, and pipeline wiring."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.cli import main
from engine.icp import DRAFT_THRESHOLD, SIGNAL_WEIGHTS, score_signals
from engine.icp_config import (
    COUNTRY_POINTS,
    ICP,
    INDUSTRY_POINTS,
    SIZE_POINTS,
    CompanyProfile,
    ICPError,
    load_companies,
    load_icp,
    render_icp,
    resolve_icp,
    role_matches,
    write_icp,
)
from engine.signals import Signal, SignalType

NOW = datetime.now(tz=timezone.utc)

FULL_TOML = """
name = "Mid-market SaaS"
industries = ["saas", "software"]
countries = ["US", "EG"]
target_roles = ["vp sales", "revops"]

[company_size]
min = 50
max = 500

[signal_weights]
hiring = 40
funding = 25
tech_change = 20
intent = 15
leadership_change = 10

[exclude]
industries = ["government"]
"""


def make_icp(**overrides: object) -> ICP:
    base: dict[str, object] = {
        "name": "test",
        "industries": ("saas", "software"),
        "size_min": 50,
        "size_max": 500,
        "countries": ("US", "EG"),
        "target_roles": ("vp sales",),
        "signal_weights": None,
        "exclude_industries": (),
    }
    base.update(overrides)
    return ICP(**base)  # type: ignore[arg-type]


def write(tmp_path: Path, text: str, name: str = "icp.toml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def feed(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


# ---- loading and validation -------------------------------------------------


def test_load_full_file(tmp_path: Path) -> None:
    icp = load_icp(write(tmp_path, FULL_TOML))
    assert icp.name == "Mid-market SaaS"
    assert icp.industries == ("saas", "software")
    assert icp.size_min == 50 and icp.size_max == 500
    assert icp.countries == ("US", "EG")
    assert icp.target_roles == ("vp sales", "revops")
    assert icp.signal_weights == {"hiring": 40, "funding": 25, "tech_change": 20,
                                  "intent": 15, "leadership_change": 10}
    assert icp.exclude_industries == ("government",)


def test_load_minimal_file_defaults(tmp_path: Path) -> None:
    icp = load_icp(write(tmp_path, 'name = "bare"\n'))
    assert icp.industries == () and icp.size_min is None and icp.size_max is None
    assert icp.signal_weights is None and icp.exclude_industries == ()


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ICPError, match="file not found"):
        load_icp(tmp_path / "nope.toml")


def test_invalid_toml_raises(tmp_path: Path) -> None:
    with pytest.raises(ICPError, match="not valid TOML"):
        load_icp(write(tmp_path, "name = [unclosed\n"))


@pytest.mark.parametrize(
    ("toml_text", "match"),
    [
        ('name = "x"\nbogus = 1\n', "unknown field"),
        ('industries = []\n', "'name' must be a non-empty string"),
        ('name = "x"\ncompany_size = 5\n', "'company_size' must be a table"),
        ('name = "x"\n[company_size]\nmin = 500\nmax = 50\n', "min must be <= "),
        ('name = "x"\n[company_size]\nmin = -1\n', "non-negative integer"),
        ('name = "x"\n[signal_weights]\nhiring = "lots"\n', "non-negative integer"),
        ('name = "x"\n[signal_weights]\ntelepathy = 10\n', "unknown signal type 'telepathy'"),
        ('name = "x"\nsignal_weights = [1, 2]\n', "'signal_weights' must be a table"),
        ('name = "x"\nexclude = ["government"]\n', "'exclude' must be a table"),
        ('name = "x"\n[exclude]\nsizes = [1]\n', "unknown exclude field"),
        ('name = "x"\nindustries = "saas"\n', "'industries' must be a list of strings"),
        ('name = "x"\nindustries = ["saas", 5]\n', "'industries' must be a list of strings"),
    ],
)
def test_validation_errors(tmp_path: Path, toml_text: str, match: str) -> None:
    with pytest.raises(ICPError, match=match.replace("[", r"\[")):
        load_icp(write(tmp_path, toml_text))


# ---- exclusion and boost ----------------------------------------------------


def test_exclusion_explicit_exclude() -> None:
    icp = make_icp(exclude_industries=("government",))
    meta = CompanyProfile(name="Gov", industry="Government", size=100, country="US")
    assert icp.exclusion(meta) == "industry 'Government' is explicitly excluded"


def test_exclusion_industry_not_in_icp() -> None:
    meta = CompanyProfile(name="Acme", industry="retail", size=100, country="US")
    assert make_icp().exclusion(meta) == "industry 'retail' not in ICP"


def test_exclusion_size_bounds() -> None:
    icp = make_icp()
    small = CompanyProfile(name="Tiny", industry="saas", size=15, country="US")
    big = CompanyProfile(name="Huge", industry="saas", size=5000, country="US")
    assert icp.exclusion(small) == "size 15 below ICP min 50"
    assert icp.exclusion(big) == "size 5000 above ICP max 500"


def test_exclusion_country() -> None:
    meta = CompanyProfile(name="FR", industry="saas", size=100, country="FR")
    assert make_icp().exclusion(meta) == "country 'FR' not in ICP"


def test_unknown_meta_never_excludes() -> None:
    icp = make_icp()
    assert icp.exclusion(None) is None
    unknown = CompanyProfile(name="?")
    assert icp.exclusion(unknown) is None
    in_icp = CompanyProfile(name="N", industry="SaaS", size=100, country="us")
    assert icp.exclusion(in_icp) is None


def test_open_ended_icp_excludes_nothing() -> None:
    icp = make_icp(industries=(), size_min=None, size_max=None, countries=())
    meta = CompanyProfile(name="Any", industry="retail", size=3, country="JP")
    assert icp.exclusion(meta) is None


def test_boost_points_are_exact_and_published() -> None:
    icp = make_icp()
    meta = CompanyProfile(name="N", industry="saas", size=100, country="US")
    points, reasons = icp.boost(meta)
    assert points == 20  # 10 industry + 5 size + 5 country, published and pinned
    assert reasons == ("+10 icp_industry (saas)", "+5 icp_size (100)", "+5 icp_country (US)")
    industry_only = CompanyProfile(name="N", industry="software")
    points, reasons = icp.boost(industry_only)
    assert points == 10
    # a non-matching industry earns nothing
    points, _ = icp.boost(CompanyProfile(name="R", industry="retail", size=100))
    assert points == 5  # size only
    assert icp.boost(None) == (0, ())


def test_no_size_bounds_means_no_size_points() -> None:
    icp = make_icp(size_min=None, size_max=None)
    points, _ = icp.boost(CompanyProfile(name="N", industry="saas", size=100))
    assert points == 10


def test_size_boundaries_are_inclusive() -> None:
    icp = make_icp()
    assert icp.exclusion(CompanyProfile(name="Lo", industry="saas", size=50, country="US")) is None
    assert icp.exclusion(CompanyProfile(name="Hi", industry="saas", size=500, country="US")) is None
    assert icp.exclusion(CompanyProfile(name="Sub", industry="saas", size=49, country="US"))


def test_equal_size_bounds_load(tmp_path: Path) -> None:
    icp = load_icp(write(tmp_path, 'name = "x"\n[company_size]\nmin = 100\nmax = 100\n'))
    assert icp.size_min == icp.size_max == 100


def test_role_matches_token_subset() -> None:
    roles = ("vp sales", "head of growth")
    assert role_matches("VP of Sales", roles)
    assert role_matches("Head Of Growth", roles)
    assert not role_matches("CTO", roles)
    assert role_matches(None, roles)  # unknown title never filters
    assert role_matches("CTO", ())  # no roles configured: everyone passes


# ---- scoring integration ----------------------------------------------------


def hiring_signal(company: str = "Northwind") -> list[Signal]:
    return [Signal(company=company, type=SignalType.HIRING, source="demo", observed_at=NOW)]


def test_weights_override_from_icp() -> None:
    icp = make_icp(signal_weights={"hiring": 99})
    fit = score_signals("Northwind", hiring_signal(), icp=icp)
    assert fit.points == 99
    assert "+99 hiring" in fit.reasons[0]


def test_excluded_company_cannot_qualify() -> None:
    icp = make_icp()
    meta = CompanyProfile(name="Acme", industry="retail", size=100, country="US")
    signals = [
        Signal(company="Acme", type=SignalType.HIRING, source="demo", observed_at=NOW),
        Signal(company="Acme", type=SignalType.FUNDING, source="demo", observed_at=NOW),
    ]
    fit = score_signals("Acme", signals, icp=icp, meta=meta)
    raw = SIGNAL_WEIGHTS[SignalType.HIRING] + SIGNAL_WEIGHTS[SignalType.FUNDING]
    assert fit.points == raw  # excluded companies get no ICP boost
    assert fit.points >= DRAFT_THRESHOLD  # raw signals are strong
    assert fit.exclusion == "industry 'retail' not in ICP"
    assert not fit.qualifies  # but exclusion vetoes drafting


def test_boost_appends_points_and_reasons() -> None:
    icp = make_icp()
    meta = CompanyProfile(name="Northwind", industry="saas", size=220, country="US")
    fit = score_signals("Northwind", hiring_signal(), icp=icp, meta=meta)
    expected = SIGNAL_WEIGHTS[SignalType.HIRING] + INDUSTRY_POINTS + SIZE_POINTS + COUNTRY_POINTS
    assert fit.points == expected
    assert fit.reasons[-1].startswith(f"+{COUNTRY_POINTS} icp_country")


def test_no_icp_keeps_published_baseline() -> None:
    fit = score_signals("Northwind", hiring_signal())
    assert fit.points == SIGNAL_WEIGHTS[SignalType.HIRING]
    assert fit.exclusion is None


# ---- write/read round trip and resolution order ------------------------------


def test_write_then_load_round_trip(tmp_path: Path) -> None:
    icp = make_icp(signal_weights={"hiring": 40, "funding": 25})
    path = tmp_path / "icp.toml"
    write_icp(icp, path)
    assert load_icp(path) == icp


def test_resolve_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # no local file: the packaged example is the always-present fallback
    icp, note = resolve_icp(None)
    assert icp is not None and icp.name.startswith("Example:") and "example" in note
    # ./icp.toml wins over the shipped example
    write(tmp_path, FULL_TOML)
    icp, note = resolve_icp(None)
    assert icp is not None and icp.name == "Mid-market SaaS" and note == ""
    # an explicit flag wins over ./icp.toml
    flag = write(tmp_path, 'name = "flagged"\n', name="other.toml")
    icp, _ = resolve_icp(flag)
    assert icp is not None and icp.name == "flagged"


def test_load_companies_missing_and_present(tmp_path: Path) -> None:
    assert load_companies(tmp_path / "missing.json") == {}
    demo_fixtures_dir = tmp_path / "data"
    from engine import demo_fixtures

    demo_fixtures.write_all(demo_fixtures_dir)
    companies = load_companies(demo_fixtures_dir / "demo_companies.json")
    assert companies["Northwind Traders"] == CompanyProfile(
        name="Northwind Traders", industry="saas", size=220, country="US"
    )
    assert companies["Initech"].size == 15


def test_render_icp_shows_every_field() -> None:
    text = render_icp(make_icp(signal_weights={"hiring": 40}), "icp.toml")
    for needle in ("industries:", "50 - 500", "vp sales", "hiring=40", "icp.toml"):
        assert needle in text
    open_ended = render_icp(
        make_icp(size_min=None, size_max=None, industries=(), countries=(), target_roles=()),
        "icp.toml",
    )
    assert "(any)" in open_ended and "(published defaults)" in open_ended


# ---- CLI: icp show / setup / edit -------------------------------------------


def test_icp_show_uses_shipped_example(capsys: pytest.CaptureFixture[str]) -> None:
    # tests run from the repo root, where data/icp.example.toml ships
    assert main(["icp", "show"]) == 0
    out = capsys.readouterr().out
    assert "Example: mid-market B2B SaaS" in out
    assert "soe icp edit" in out


def test_icp_show_without_any_icp(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    from engine import icp_config

    monkeypatch.setattr(icp_config, "PACKAGE_EXAMPLE", tmp_path / "missing.toml")
    assert main(["icp", "show"]) == 0
    assert "No ICP yet" in capsys.readouterr().out


def test_icp_show_broken_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path, 'name = "x"\nbogus = 1\n')
    assert main(["icp", "show"]) == 2
    assert "unknown field" in capsys.readouterr().out


def test_icp_setup_writes_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    feed(
        monkeypatch,
        [
            "Enterprise fintech",  # name
            "fintech, banking",  # industries
            "200",  # size min
            "5000",  # size max
            "US, GB",  # countries
            "cfo, vp finance",  # roles
            "none",  # excluded industries
            "Mohamed",  # sender name (signs the emails)
            "y",  # tune weights
            "10",  # hiring
            "50",  # funding
            "20",  # tech_change
            "15",  # intent
            "5",  # leadership_change
            "",  # recap: save
        ],
    )
    assert main(["icp", "setup"]) == 0
    out = capsys.readouterr().out
    assert "Wrote icp.toml" in out
    icp = load_icp(tmp_path / "icp.toml")
    assert icp.name == "Enterprise fintech"
    assert icp.industries == ("fintech", "banking")
    assert (icp.size_min, icp.size_max) == (200, 5000)
    assert icp.exclude_industries == ()
    assert icp.sender_name == "Mohamed"
    assert 'sender_name = "Mohamed"' in (tmp_path / "icp.toml").read_text()
    assert icp.signal_weights is not None and icp.signal_weights["funding"] == 50


def test_icp_setup_defaults_on_enter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    feed(monkeypatch, ["", "", "", "", "", "", "", "", "", ""])
    assert main(["icp", "setup"]) == 0
    icp = load_icp(tmp_path / "icp.toml")
    assert icp.industries  # defaults kept (from example or fallback)
    assert icp.signal_weights is None  # "N" to tuning keeps defaults
    assert icp.sender_name is None  # "demo signature" kept


def test_icp_setup_rejects_inverted_size(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    feed(monkeypatch, ["x", "saas", "500", "50", "", "", "", "", ""])
    assert main(["icp", "setup"]) == 2
    assert "Minimum size" in capsys.readouterr().out
    assert not (tmp_path / "icp.toml").exists()


def test_icp_setup_non_interactive(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError()))
    assert main(["icp", "setup"]) == 2
    out = capsys.readouterr().out
    assert "need a real terminal" in out
    assert "soe icp setup" in out  # the friendly re-run hint
    assert not (tmp_path / "icp.toml").exists()


def test_icp_edit_one_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_icp(make_icp(), tmp_path / "icp.toml")
    feed(monkeypatch, ["2", "fintech, insurtech"])  # field 2 = industries
    assert main(["icp", "edit"]) == 0
    assert load_icp(tmp_path / "icp.toml").industries == ("fintech", "insurtech")


def test_icp_edit_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    write_icp(make_icp(), tmp_path / "icp.toml")
    feed(monkeypatch, ["7", "11", "22", "33", "44", "55"])
    assert main(["icp", "edit"]) == 0
    weights = load_icp(tmp_path / "icp.toml").signal_weights
    assert weights == {"hiring": 11, "funding": 22, "tech_change": 33,
                       "intent": 44, "leadership_change": 55}


def test_icp_edit_cancel_and_missing_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["icp", "edit"]) == 2  # no file yet
    assert "soe icp setup" in capsys.readouterr().out
    write_icp(make_icp(), tmp_path / "icp.toml")
    feed(monkeypatch, ["0"])
    assert main(["icp", "edit"]) == 0
    assert "Nothing changed" in capsys.readouterr().out
    feed(monkeypatch, ["9"])
    assert main(["icp", "edit"]) == 2
    assert "Unknown choice" in capsys.readouterr().out


def test_icp_edit_inverted_size_changes_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write_icp(make_icp(), tmp_path / "icp.toml")
    feed(monkeypatch, ["3", "500", "50"])
    assert main(["icp", "edit"]) == 2
    assert load_icp(tmp_path / "icp.toml").size_min == 50  # unchanged


# ---- pipeline wiring ---------------------------------------------------------


def test_run_uses_icp_and_reports_exclusions(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path, FULL_TOML)  # ./icp.toml: saas/software, 50-500, US/EG
    assert main(["run", "--db", str(tmp_path / "r.db")]) == 0
    out = capsys.readouterr().out
    assert "outside ICP" in out
    assert "excluded" in out
    assert "inside the ICP" in out


def test_run_without_icp_says_so(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    from engine import icp_config

    monkeypatch.setattr(icp_config, "PACKAGE_EXAMPLE", tmp_path / "missing.toml")
    assert main(["run", "--db", str(tmp_path / "r.db")]) == 0
    out = capsys.readouterr().out
    assert "who you sell to is not set up yet" in out
    assert "over the 50-point bar" in out  # pre-ICP wording


def test_persona_filter_skips_off_role_titles(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write(
        tmp_path,
        'name = "x"\nindustries = ["saas", "software"]\n'
        'target_roles = ["ceo"]\n[company_size]\nmin = 1\n',
    )
    assert main(["run", "--db", str(tmp_path / "r.db")]) == 0
    out = capsys.readouterr().out
    assert "outside ICP target roles" in out
    assert "0 draft(s)" in out


def test_score_with_bad_icp_flag(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    from engine import demo_fixtures

    demo_fixtures.write_all(tmp_path / "data")
    bad = write(tmp_path, 'name = "x"\nbogus = 1\n', name="bad.toml")
    assert main(["score", "--icp", str(bad)]) == 2
    assert "unknown field" in capsys.readouterr().out


def test_draft_reports_exclusion_reason(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    from engine import demo_fixtures

    demo_fixtures.write_all(tmp_path / "data")
    write(tmp_path, FULL_TOML)
    assert main(["draft", "--db", str(tmp_path / "d.db")]) == 0
    out = capsys.readouterr().out
    assert "outside ICP - industry 'retail' not in ICP" in out
    assert "outside ICP - size 15 below ICP min 50" in out


# ---- uncovered-branch hardening ----------------------------------------------


def test_ask_int_reprompts_until_valid(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    feed(
        monkeypatch,
        ["x", "saas", "abc", "-3", "20", "300", "EG", "vp sales", "none", "", "n", ""],
    )
    assert main(["icp", "setup"]) == 0
    out = capsys.readouterr().out
    assert "Please type a whole number." in out
    assert "Please type zero or more." in out
    icp = load_icp(tmp_path / "icp.toml")
    assert (icp.size_min, icp.size_max) == (20, 300)


def test_icp_edit_each_simple_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    cases: list[tuple[list[str], Callable[[ICP], bool]]] = [
        (["1", "Renamed ICP"], lambda i: i.name == "Renamed ICP"),
        (["3", "100", "200"], lambda i: (i.size_min, i.size_max) == (100, 200)),
        (["4", "GB"], lambda i: i.countries == ("GB",)),
        (["5", "cro"], lambda i: i.target_roles == ("cro",)),
        (["6", "education"], lambda i: i.exclude_industries == ("education",)),
    ]
    for answers, check in cases:
        write_icp(make_icp(), tmp_path / "icp.toml")
        feed(monkeypatch, answers)
        assert main(["icp", "edit"]) == 0
        assert check(load_icp(tmp_path / "icp.toml"))


def test_icp_edit_broken_file_and_non_interactive(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path, 'name = "x"\nbogus = 1\n')
    assert main(["icp", "edit"]) == 2
    assert "unknown field" in capsys.readouterr().out
    (tmp_path / "icp.toml").unlink()
    write_icp(make_icp(), tmp_path / "icp.toml")
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError()))
    assert main(["icp", "edit"]) == 2
    assert "No interactive terminal" in capsys.readouterr().out


def _demo_data(tmp_path: Path) -> Path:
    from engine import demo_fixtures

    data_dir = tmp_path / "data"
    demo_fixtures.write_all(data_dir)
    return data_dir


def test_demo_bad_icp_flag_fails_cleanly(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = _demo_data(tmp_path)
    bad = write(tmp_path, 'name = "x"\nbogus = 1\n', name="bad.toml")
    rc = main(["demo", "--data-dir", str(data_dir), "--db", str(tmp_path / "d.db"),
               "--icp", str(bad)])
    assert rc == 2
    assert "unknown field" in capsys.readouterr().out


def test_demo_without_icp_keeps_pre_icp_wording(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no icp.toml here
    from engine import icp_config

    monkeypatch.setattr(icp_config, "PACKAGE_EXAMPLE", tmp_path / "missing.toml")
    data_dir = _demo_data(tmp_path)
    rc = main(["demo", "--data-dir", str(data_dir), "--db", str(tmp_path / "d.db")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "who you sell to is not set up yet" in out
    assert "over the 50-point bar route to drafting" in out
    assert "below the fit bar" in out


def test_demo_persona_skip(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    data_dir = _demo_data(tmp_path)
    write(tmp_path, 'name = "x"\ntarget_roles = ["ceo"]\n')
    rc = main(["demo", "--data-dir", str(data_dir), "--db", str(tmp_path / "d.db")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "outside ICP target roles" in out
    assert "-> 0 draft(s)" in out
