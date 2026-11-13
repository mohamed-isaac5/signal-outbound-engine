from datetime import datetime, timedelta, timezone

import pytest

from engine.icp import DRAFT_THRESHOLD, SIGNAL_WEIGHTS, FitScore, score_signals
from engine.signals import Signal, SignalType

NOW = datetime.now(tz=timezone.utc)


def sig(company: str, stype: SignalType) -> Signal:
    return Signal(
        company=company,
        type=stype,
        observed_at=NOW - timedelta(days=2),
        source="demo",
    )


def test_weights_match_the_published_readme_table() -> None:
    # Every (signal, points) pair published in README.md#scoring, pinned:
    assert SIGNAL_WEIGHTS == {
        SignalType.HIRING: 30,
        SignalType.FUNDING: 25,
        SignalType.TECH_CHANGE: 20,
        SignalType.INTENT: 15,
        SignalType.LEADERSHIP_CHANGE: 10,
    }


def test_score_accumulates_points_with_reasons() -> None:
    fit = score_signals(
        "Acme",
        [sig("Acme", SignalType.HIRING), sig("Acme", SignalType.FUNDING)],
    )
    assert fit.points == 55
    assert len(fit.reasons) == 2
    assert fit.qualifies


def test_single_weak_signal_does_not_qualify() -> None:
    fit = score_signals("Acme", [sig("Acme", SignalType.INTENT)])
    assert fit.points == 15
    assert not fit.qualifies


def test_threshold_boundary() -> None:
    fit = FitScore(company="Acme", points=DRAFT_THRESHOLD, reasons=())
    assert fit.qualifies
    below = FitScore(company="Acme", points=DRAFT_THRESHOLD - 1, reasons=())
    assert not below.qualifies


def test_mixed_company_signals_rejected() -> None:
    with pytest.raises(ValueError, match="Acme"):
        score_signals("Acme", [sig("OtherCo", SignalType.HIRING)])
