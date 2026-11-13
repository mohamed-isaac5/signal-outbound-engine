"""Buying-signal model and normalization.

A Signal is one observed buying event tied to a company: a hiring post, a funding
round, a tech-stack change, an intent spike. Signals are the input to ICP scoring.
Unknown fields stay None - the engine never fabricates data it did not observe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SignalType(str, Enum):
    HIRING = "hiring"
    FUNDING = "funding"
    TECH_CHANGE = "tech_change"
    INTENT = "intent"
    LEADERSHIP_CHANGE = "leadership_change"


@dataclass(frozen=True)
class Signal:
    """One observed buying signal for a company."""

    company: str
    type: SignalType
    observed_at: datetime
    source: str
    detail: str | None = None
    meta: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.company.strip():
            raise ValueError("signal must name a company")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")

    @property
    def age_days(self) -> float:
        """Days since the signal was observed, against UTC now."""
        delta = datetime.now(tz=timezone.utc) - self.observed_at
        return delta.total_seconds() / 86400


def fresh(signal: Signal, window_days: int = 30) -> bool:
    """A signal counts for outreach only while it is still fresh."""
    return 0 <= signal.age_days <= window_days
