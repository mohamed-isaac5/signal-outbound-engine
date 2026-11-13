"""Drafting providers.

Drafting is provider-agnostic: any LLM backend plugs into DraftingProvider.
The DEFAULT, documented path is the OfflineProvider - deterministic drafts
built from the actual score reasons. It needs no API key and no spend, and
every draft it produces is labeled as an offline demo draft. The Anthropic
provider is a real adapter (optional `anthropic` extra): same interface,
live Messages API call once ANTHROPIC_API_KEY is set; without a key it
fails loudly, never silently falls back.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from engine.draft import Draft
from engine.enrich import Contact
from engine.icp import FitScore

OFFLINE_LABEL = "OFFLINE DEMO DRAFT - template-generated, not LLM output"

# Buyer-facing phrases per signal type. The score table keeps the point math;
# the email a human receives must read like a human wrote it (ADR-0007).
SIGNAL_PHRASES = {
    "hiring": "you're hiring for key roles",
    "funding": "you just raised a new round",
    "tech_change": "you're changing your tech stack",
    "intent": "your team is actively researching this space",
    "leadership_change": "new leadership is coming in",
}


SUBJECT_PHRASES = {
    "hiring": "hiring",
    "funding": "new funding",
    "tech_change": "tech change",
    "intent": "active research",
    "leadership_change": "new leadership",
}


def _signal_kinds(reasons: tuple[str, ...]) -> list[str]:
    """Signal kinds from score reasons, deduped, icp_* boost reasons excluded."""
    kinds: list[str] = []
    for reason in reasons:
        parts = reason.split()
        if len(parts) < 2:
            continue
        kind = parts[1]
        if kind.startswith("icp_"):
            continue
        if kind not in kinds:
            kinds.append(kind)
    return kinds


def subject_for(company: str, reasons: tuple[str, ...]) -> str:
    """Buyer-facing subject: short human fragments, never system vocabulary.

    At most two fragments so the subject stays scannable in an inbox list.
    """
    fragments = [SUBJECT_PHRASES.get(k, k.replace("_", " ")) for k in _signal_kinds(reasons)]
    if not fragments:
        return f"{company}: quick question"
    return f"{company}: {' + '.join(fragments[:2])}"


def join_english(items: list[str]) -> str:
    """'a' / 'a and b' / 'a, b and c' - the way a person writes a list."""
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def human_signal_phrases(reasons: tuple[str, ...]) -> list[str]:
    """Score reasons -> buyer-facing phrases (deduped, order kept).

    ICP boost reasons (icp_industry/icp_size/icp_country) are about OUR fit,
    not THEIR movement, so they never appear in the email.
    """
    phrases: list[str] = []
    for reason in reasons:
        parts = reason.split()
        if len(parts) < 2:
            continue
        kind = parts[1]
        if kind.startswith("icp_"):
            continue
        phrase = SIGNAL_PHRASES.get(kind, f"we noticed {kind.replace('_', ' ')}")
        if phrase not in phrases:
            phrases.append(phrase)
    return phrases

PROMPT_TEMPLATE = """Write a short B2B cold email.

Recipient: {name} ({title}) at {company}
Why now (scored buying signals): {reasons}
Fit score: {points} points (uncapped - more fresh signals, more points)

Rules: 3 short paragraphs max, plain text, reference ONE specific signal,
no hype, no emojis, end with one low-friction question.
First line must be exactly: Subject: <subject line>"""


class DraftingProvider(Protocol):
    name: str

    def draft(self, contact: Contact, fit: FitScore) -> Draft: ...


def build_prompt(contact: Contact, fit: FitScore) -> str:
    """The exact prompt every LLM provider sends - inspectable and testable."""
    return PROMPT_TEMPLATE.format(
        name=contact.name,
        title=contact.title or "unknown title",
        company=contact.company,
        reasons="; ".join(fit.reasons),
        points=fit.points,
    )


def split_subject_body(text: str) -> tuple[str, str]:
    """Split an LLM reply into (subject, body) using the 'Subject:' first line."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("Subject:"):
        return lines[0][len("Subject:") :].strip(), "\n".join(lines[1:]).strip()
    raise ValueError("LLM reply missing 'Subject:' first line")


class OfflineProvider:
    """Deterministic template drafts from real score reasons. No key needed."""

    name = "offline-template"

    def __init__(self, sender_name: str | None = None) -> None:
        self._signature = sender_name or "signal-outbound-engine demo"

    def draft(self, contact: Contact, fit: FitScore) -> Draft:
        first = contact.name.split()[0]
        phrases = human_signal_phrases(fit.reasons)
        why = join_english(phrases) if phrases else "your team is showing movement we track"
        subject = subject_for(contact.company, fit.reasons)
        body = (
            f"[{OFFLINE_LABEL}]\n\n"
            f"Hi {first},\n\n"
            f"Reaching out because at {contact.company} {why}.\n\n"
            f"Teams in this position usually lose weeks stitching signals, enrichment "
            f"and sequencing by hand. We turn those signals into approved, audited "
            f"outreach the same day.\n\n"
            f"Worth 15 minutes this week?\n\n"
            f"- {self._signature}"
        )
        return Draft(contact=contact, subject=subject, body=body, fit=fit, provider=self.name)


class AnthropicProvider:
    """Real Anthropic Messages API adapter. Same interface as offline.

    Activate with `pip install -e ".[anthropic]"` and ANTHROPIC_API_KEY set.
    Without a key it fails loudly - the engine never pretends a template
    draft is LLM output.
    """

    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-20250514", client: Any = None) -> None:
        self.model = model
        self._key = os.environ.get("ANTHROPIC_API_KEY")
        self._client = client

    def draft(self, contact: Contact, fit: FitScore) -> Draft:
        if self._client is None and not self._key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Use the offline provider "
                "(default) or export a key to enable LLM drafting."
            )
        client = self._client or self._make_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=600,
            messages=[{"role": "user", "content": build_prompt(contact, fit)}],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        subject, body = split_subject_body(text)
        return Draft(contact=contact, subject=subject, body=body, fit=fit, provider=self.name)

    def _make_client(self) -> Any:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Install the optional extra first: pip install -e \".[anthropic]\""
            ) from exc
        return anthropic.Anthropic()
