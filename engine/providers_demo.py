"""Demo enrichment providers: labeled, offline, deterministic.

Unit costs mirror published per-lookup pricing of the real tools they stand in
for, so the cost-per-lead math in the demo is realistic. Data comes from a
labeled demo fixture - fictional contacts, never real people.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.enrich import Contact, EmailStatus, LookupHit


class DemoProvider:
    def __init__(self, name: str, unit_cost_usd: float, data: dict[str, dict[str, str]]) -> None:
        self.name = name
        self.unit_cost_usd = unit_cost_usd
        self._data = data

    def find_email(self, contact: Contact) -> LookupHit | None:
        row = self._data.get(f"{contact.name}@{contact.company}")
        if row is None:
            return None
        return LookupHit(email=row["email"], status=EmailStatus(row["status"]))


def load_demo_providers(path: Path) -> list[DemoProvider]:
    """Build the waterfall order from a labeled demo fixture."""
    fixture = json.loads(path.read_text())
    return [
        DemoProvider(
            name=p["name"],
            unit_cost_usd=p["unit_cost_usd"],
            data=p["data"],
        )
        for p in fixture["providers"]
    ]
