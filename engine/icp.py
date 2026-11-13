"""ICP fit scoring.

The scoring formula is published in the README - every point is explainable.
Fit is the sum of component scores; each component is a pure function of its
input so results are deterministic and testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.signals import Signal, SignalType

# Points awarded per signal type. Published in README.md#scoring.
SIGNAL_WEIGHTS: dict[SignalType, int] = {
    SignalType.HIRING: 30,
    SignalType.FUNDING: 25,
    SignalType.TECH_CHANGE: 20,
    SignalType.INTENT: 15,
    SignalType.LEADERSHIP_CHANGE: 10,
}

# A combined fit at or above this threshold routes to drafting.
DRAFT_THRESHOLD = 50


@dataclass(frozen=True)
class FitScore:
    company: str
    points: int
    reasons: tuple[str, ...]

    @property
    def qualifies(self) -> bool:
        return self.points >= DRAFT_THRESHOLD


def score_signals(company: str, signals: list[Signal]) -> FitScore:
    """Score a company's fresh signals against the published weights."""
    points = 0
    reasons: list[str] = []
    for signal in signals:
        if signal.company != company:
            raise ValueError(f"signal for {signal.company} passed with company {company}")
        weight = SIGNAL_WEIGHTS[signal.type]
        points += weight
        reasons.append(f"+{weight} {signal.type.value} ({signal.source})")
    return FitScore(company=company, points=points, reasons=tuple(reasons))
