"""Drafting providers.

Drafting is provider-agnostic: any LLM backend plugs into DraftingProvider.
The DEFAULT, documented path is the OfflineProvider - deterministic drafts
built from the actual score reasons. It needs no API key and no spend, and
every draft it produces is labeled as an offline demo draft. An Anthropic
adapter is included for when a key is available: same interface, real LLM.
"""

from __future__ import annotations

import os
from typing import Protocol

from engine.draft import Draft
from engine.enrich import Contact
from engine.icp import FitScore

OFFLINE_LABEL = "OFFLINE DEMO DRAFT - template-generated, not LLM output"


class DraftingProvider(Protocol):
    name: str

    def draft(self, contact: Contact, fit: FitScore) -> Draft: ...


class OfflineProvider:
    """Deterministic template drafts from real score reasons. No key needed."""

    name = "offline-template"

    def draft(self, contact: Contact, fit: FitScore) -> Draft:
        first = contact.name.split()[0]
        reasons = "; ".join(fit.reasons)
        subject = f"{contact.company}: your signals say now ({fit.points} pts)"
        body = (
            f"[{OFFLINE_LABEL}]\n\n"
            f"Hi {first},\n\n"
            f"Reaching out because {contact.company} is showing movement we track: "
            f"{reasons}.\n\n"
            f"Teams in this position usually lose weeks stitching signals, enrichment "
            f"and sequencing by hand. We turn those signals into approved, audited "
            f"outreach the same day.\n\n"
            f"Worth 15 minutes this week?\n\n"
            f"- signal-outbound-engine demo"
        )
        return Draft(contact=contact, subject=subject, body=body, fit=fit, provider=self.name)


class AnthropicProvider:
    """Anthropic adapter. Same interface as the offline provider.

    Needs ANTHROPIC_API_KEY in the environment. Raises honestly when it is
    missing - the engine never pretends a template draft is LLM output.
    """

    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-20250514") -> None:
        self.model = model
        self._key = os.environ.get("ANTHROPIC_API_KEY")

    def draft(self, contact: Contact, fit: FitScore) -> Draft:
        if not self._key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Use the offline provider "
                "(default) or export a key to enable LLM drafting."
            )
        raise NotImplementedError(
            "Anthropic adapter: wire the Messages API here when a key is available. "
            "Interface and prompt inputs (contact, fit.reasons) are already defined."
        )
