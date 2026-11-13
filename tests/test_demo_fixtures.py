from pathlib import Path

from engine.connectors import DemoFileSource
from engine.demo_fixtures import write_all
from engine.signals import fresh


def test_generated_fixtures_are_fresh(tmp_path: Path) -> None:
    write_all(tmp_path)
    signals = DemoFileSource(tmp_path / "demo_signals.json").fetch()
    assert len(signals) == 7
    assert all(s.observed_at.tzinfo is not None for s in signals)
    # 6 of 7 fresh today (Umbrella Labs is intentionally stale); the key
    # property: regeneration at ANY date restores the same demo behavior.
    assert sum(1 for s in signals if fresh(s)) == 6


def test_all_fixture_files_written(tmp_path: Path) -> None:
    written = write_all(tmp_path)
    assert {p.name for p in written} == {
        "demo_signals.json",
        "demo_contacts.json",
        "demo_enrichment.json",
        "demo_companies.json",
    }


def test_main_prints_written_paths(capsys, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import engine.demo_fixtures as df

    monkeypatch.setattr(df, "DATA_DIR", tmp_path)
    assert df.main() == 0
    out = capsys.readouterr().out
    assert "demo_signals.json" in out
    assert (tmp_path / "demo_signals.json").exists()
