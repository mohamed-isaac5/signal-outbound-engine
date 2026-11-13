from datetime import datetime, timezone

import pytest

from engine.draft import Draft
from engine.enrich import Contact
from engine.icp import FitScore, score_signals
from engine.signals import Signal, SignalType


def fit() -> FitScore:
    signal = Signal(
        company="Acme",
        type=SignalType.HIRING,
        observed_at=datetime.now(tz=timezone.utc),
        source="demo",
    )
    return score_signals("Acme", [signal])


def test_draft_requires_subject_and_body() -> None:
    contact = Contact(name="A", company="Acme", email="a@acme.com")
    with pytest.raises(ValueError):
        Draft(contact=contact, subject=" ", body="hello", fit=fit())
