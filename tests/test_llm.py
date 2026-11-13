from datetime import datetime, timezone

import pytest

from engine.enrich import Contact
from engine.icp import FitScore, score_signals
from engine.llm import (
    OFFLINE_LABEL,
    AnthropicProvider,
    OfflineProvider,
    build_prompt,
    split_subject_body,
)
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


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeMessages:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> object:
        self.last_kwargs = kwargs

        class _Resp:
            content = [_Block(self.reply)]

        return _Resp()


class _FakeClient:
    def __init__(self, reply: str) -> None:
        self.messages = _FakeMessages(reply)


def test_anthropic_adapter_calls_messages_api() -> None:
    client = _FakeClient("Subject: quick question\n\nHi Sara, saw the SDR posts.")
    contact = Contact(name="Sara Adel", company="Acme", email="sara@acme.example")
    d = AnthropicProvider(client=client).draft(contact, make_fit())
    assert d.provider == "anthropic"
    assert d.subject == "quick question"
    assert "Hi Sara" in d.body
    messages = client.messages.last_kwargs["messages"]
    sent = messages[0]["content"]  # type: ignore[index]
    assert "+30 hiring" in sent
    assert "55" in sent


def test_split_subject_body_requires_subject_line() -> None:
    with pytest.raises(ValueError, match="Subject"):
        split_subject_body("no subject here")
    assert split_subject_body("Subject: hi\n\nbody")[0] == "hi"


def test_build_prompt_contains_real_reasons() -> None:
    contact = Contact(name="Sara Adel", company="Acme", title="VP Sales")
    prompt = build_prompt(contact, make_fit())
    assert "Sara Adel" in prompt
    assert "VP Sales" in prompt
    assert "+25 funding" in prompt
