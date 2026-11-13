"""Human approval queue (M4).

Nothing sends from this engine without an explicit approve decision recorded
against the draft. Rejections keep their reason for the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Approval:
    draft_id: str
    decision: Decision
    reviewer: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.reviewer.strip():
            raise ValueError("approval must name a reviewer")
        if self.decision is Decision.REJECTED and not (self.reason or "").strip():
            raise ValueError("rejections must record a reason")
