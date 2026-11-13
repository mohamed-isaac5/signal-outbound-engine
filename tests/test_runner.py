from datetime import datetime, timedelta, timezone

from engine.runner import audit_run, render_table, run_scoring
from engine.signals import Signal, SignalType
from engine.store import open_db

NOW = datetime.now(tz=timezone.utc)


class StaticSource:
    name = "static"

    def __init__(self, signals: list[Signal]) -> None:
        self._signals = signals

    def fetch(self) -> list[Signal]:
        return self._signals


def sig(company: str, stype: SignalType, days_ago: float) -> Signal:
    return Signal(
        company=company,
        type=stype,
        observed_at=NOW - timedelta(days=days_ago),
        source="static",
    )


def test_run_groups_fresh_signals_and_ranks() -> None:
    source = StaticSource(
        [
            sig("Acme", SignalType.HIRING, 2),
            sig("Acme", SignalType.FUNDING, 5),
            sig("Globex", SignalType.INTENT, 1),
            sig("Stale", SignalType.FUNDING, 90),
        ]
    )
    result = run_scoring(source, window_days=30)
    assert [f.company for f in result.scores] == ["Acme", "Globex"]
    assert result.scores[0].points == 55
    assert result.scores[0].qualifies
    assert not result.scores[1].qualifies


def test_table_shows_reasons_and_routing() -> None:
    source = StaticSource([sig("Acme", SignalType.HIRING, 2)])
    table = render_table(run_scoring(source))
    assert "Acme" in table
    assert "30" in table
    assert "+30 hiring" in table


def test_audit_run_logs_scores(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = StaticSource([sig("Acme", SignalType.HIRING, 2)])
    result = run_scoring(source)
    conn = open_db(tmp_path / "run.db")
    audit_run(conn, result)
    rows = conn.execute("SELECT event, detail FROM audit").fetchall()
    assert rows[0][0] == "scoring_run"
    assert "Acme=30" in rows[0][1]
