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


def test_brand_new_signal_is_fresh() -> None:
    """A signal observed right now (age ~0) counts for outreach."""
    assert fresh(make_signal(days_ago=0), window_days=30)


def test_freshness_window_boundary_is_inclusive(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Pin exact boundary semantics with a frozen clock: a signal exactly
    window_days old still counts; one second past it does not."""
    import engine.signals as sig_mod

    frozen_now = datetime.now(tz=timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return frozen_now

    monkeypatch.setattr(sig_mod, "datetime", FrozenDatetime)
    at_edge = Signal(
        company="Acme",
        type=SignalType.HIRING,
        observed_at=frozen_now - timedelta(days=30),
        source="x",
    )
    just_past = Signal(
        company="Acme",
        type=SignalType.HIRING,
        observed_at=frozen_now - timedelta(days=30, seconds=1),
        source="x",
    )
    assert fresh(at_edge, window_days=30)
    assert not fresh(just_past, window_days=30)
