from datetime import datetime, timezone

import pytest

from engine.enrich import Contact
from engine.icp import FitScore, score_signals
from engine.llm import OFFLINE_LABEL, AnthropicProvider, OfflineProvider
from engine.signals import Signal, SignalType


def make_fit(company: str = "Acme") -> FitScore:
    signals = [
        Signal(
            company=company,
            type=SignalType.HIRING,
            observed_at=datetime.now(tz=timezone.utc),
            source="demo",
        ),
        Signal(
            company=company,
            type=SignalType.FUNDING,
            observed_at=datetime.now(tz=timezone.utc),
            source="demo",
        ),
    ]
    return score_signals(company, signals)


def test_offline_draft_cites_real_reasons_and_is_labeled() -> None:
    contact = Contact(name="Sara Adel", company="Acme", email="sara@acme.example")
    fit = make_fit()
    d = OfflineProvider().draft(contact, fit)
    assert d.provider == "offline-template"
    assert OFFLINE_LABEL in d.body
    assert "+30 hiring" in d.body
    assert "+25 funding" in d.body
    assert "Sara" in d.body
    assert str(d.fit.points) in d.subject


def test_offline_draft_is_deterministic() -> None:
    contact = Contact(name="Sara Adel", company="Acme", email="sara@acme.example")
    fit = make_fit()
    provider = OfflineProvider()
    assert provider.draft(contact, fit) == provider.draft(contact, fit)


def test_anthropic_adapter_fails_honestly_without_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    contact = Contact(name="Sara Adel", company="Acme", email="sara@acme.example")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider().draft(contact, make_fit())
