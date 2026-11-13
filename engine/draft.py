"""The draft contract.

A Draft is generated from a scored fit and an enriched contact by a
DraftingProvider (see engine.llm). No draft ever sends without a human
approval in the queue (see engine.approve).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.enrich import Contact
from engine.icp import FitScore


@dataclass(frozen=True)
class Draft:
    contact: Contact
    subject: str
    body: str
    fit: FitScore
    provider: str = "unknown"

    def __post_init__(self) -> None:
        if not self.subject.strip() or not self.body.strip():
            raise ValueError("draft needs a non-empty subject and body")
