"""ICP fit scoring.

The scoring formula is published in the README - every point is explainable.
Fit is the sum of component scores; each component is a pure function of its
input so results are deterministic and testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.icp_config import ICP, CompanyProfile
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
    exclusion: str | None = None

    @property
    def qualifies(self) -> bool:
        # Over the bar AND inside the ICP: an excluded company never routes,
        # however many signal points it has.
        return self.points >= DRAFT_THRESHOLD and self.exclusion is None


def score_signals(
    company: str,
    signals: list[Signal],
    *,
    icp: ICP | None = None,
    meta: CompanyProfile | None = None,
) -> FitScore:
    """Score a company's fresh signals: published weights, then the ICP layer.

    The ICP can override the signal weights, excludes companies outside it
    (with a stated reason), and adds published closeness points to the rest.
    """
    weights = SIGNAL_WEIGHTS
    if icp is not None and icp.signal_weights is not None:
        weights = {SignalType(k): v for k, v in icp.signal_weights.items()}
    points = 0
    reasons: list[str] = []
    for signal in signals:
        if signal.company != company:
            raise ValueError(f"signal for {signal.company} passed with company {company}")
        weight = weights.get(signal.type, 0)
        points += weight
        reasons.append(f"+{weight} {signal.type.value} ({signal.source})")
    exclusion: str | None = None
    if icp is not None:
        exclusion = icp.exclusion(meta)
        if exclusion is None:
            bonus, bonus_reasons = icp.boost(meta)
            points += bonus
            reasons.extend(bonus_reasons)
    return FitScore(company=company, points=points, reasons=tuple(reasons), exclusion=exclusion)
