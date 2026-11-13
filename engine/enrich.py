"""Enrichment waterfall.

Providers are tried in order; the first non-null result wins. Anything a
provider cannot find stays None - unknown is a valid answer, fabrication is
not. Every lookup is recorded (provider, hit/miss, unit cost) so cost per
enriched lead is a measured number, never a guess.

Real providers (Apollo, Clay) plug into the EnrichmentProvider protocol behind
API keys; this module owns the waterfall logic, tested with stub providers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Protocol


class EmailStatus(str, Enum):
    VERIFIED = "verified"
    RISKY = "risky"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Contact:
    name: str
    company: str
    email: str | None = None
    title: str | None = None
    linkedin_url: str | None = None
    email_status: EmailStatus = EmailStatus.UNKNOWN


@dataclass(frozen=True)
class LookupHit:
    email: str
    status: EmailStatus


class EnrichmentProvider(Protocol):
    name: str
    unit_cost_usd: float  # cost of ONE lookup, hit or miss - published per provider

    def find_email(self, contact: Contact) -> LookupHit | None: ...


@dataclass(frozen=True)
class Attempt:
    provider: str
    hit: bool
    cost_usd: float


@dataclass(frozen=True)
class EnrichmentResult:
    contact: Contact
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)

    @property
    def found_by(self) -> str | None:
        for attempt in self.attempts:
            if attempt.hit:
                return attempt.provider
        return None

    @property
    def cost_usd(self) -> float:
        return round(sum(a.cost_usd for a in self.attempts), 4)


def run_waterfall(contact: Contact, providers: Sequence[EnrichmentProvider]) -> EnrichmentResult:
    """Try each provider in order until one finds an email."""
    if contact.email is not None:
        return EnrichmentResult(contact=contact)
    attempts: list[Attempt] = []
    for provider in providers:
        hit = provider.find_email(contact)
        attempts.append(
            Attempt(provider=provider.name, hit=hit is not None, cost_usd=provider.unit_cost_usd)
        )
        if hit is not None:
            return EnrichmentResult(
                contact=replace(contact, email=hit.email, email_status=hit.status),
                attempts=tuple(attempts),
            )
    return EnrichmentResult(contact=contact, attempts=tuple(attempts))
