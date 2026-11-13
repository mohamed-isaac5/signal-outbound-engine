"""Enrichment waterfall (M2).

Providers are tried in order; the first non-null result wins. Anything a
provider cannot find stays None - unknown is a valid answer, fabrication is not.
Real providers (Apollo, Clay) land in M2 behind API keys; this module defines
the contract and the waterfall logic, tested with stub providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Contact:
    name: str
    company: str
    email: str | None = None
    title: str | None = None
    linkedin_url: str | None = None


class EnrichmentProvider(Protocol):
    name: str

    def find_email(self, contact: Contact) -> str | None: ...


def run_waterfall(contact: Contact, providers: list[EnrichmentProvider]) -> Contact:
    """Try each provider in order until one finds a verified email."""
    if contact.email is not None:
        return contact
    for provider in providers:
        found = provider.find_email(contact)
        if found is not None:
            return Contact(
                name=contact.name,
                company=contact.company,
                email=found,
                title=contact.title,
                linkedin_url=contact.linkedin_url,
            )
    return contact
