from datetime import datetime, timedelta, timezone

import pytest

from engine.signals import Signal, SignalType, fresh


def make_signal(days_ago: float = 1) -> Signal:
    return Signal(
        company="Acme",
        type=SignalType.HIRING,
        observed_at=datetime.now(tz=timezone.utc) - timedelta(days=days_ago),
        source="demo",
    )


def test_signal_requires_company() -> None:
    with pytest.raises(ValueError, match="company"):
        Signal(
            company=" ",
            type=SignalType.HIRING,
            observed_at=datetime.now(tz=timezone.utc),
            source="demo",
        )


def test_signal_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Signal(company="Acme", type=SignalType.HIRING, observed_at=datetime.now(), source="demo")


def test_fresh_within_window() -> None:
    assert fresh(make_signal(days_ago=10), window_days=30)


def test_stale_outside_window() -> None:
    assert not fresh(make_signal(days_ago=45), window_days=30)


def test_future_signal_is_not_fresh() -> None:
    assert not fresh(make_signal(days_ago=-1), window_days=30)
