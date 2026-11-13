"""Signal sources.

A connector turns an external source (job board, funding news, intent feed)
into normalized Signal objects. The demo source reads a labeled JSON fixture
so the whole engine runs offline; live connectors plug into the same protocol.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

from engine.signals import Signal, SignalType


class SignalSource(Protocol):
    name: str

    def fetch(self) -> list[Signal]: ...


class DemoFileSource:
    """Reads labeled demo signals from a JSON fixture. Demo data is demo data."""

    name = "demo-file"

    def __init__(self, path: Path) -> None:
        self.path = path

    def fetch(self) -> list[Signal]:
        rows = json.loads(self.path.read_text())
        signals: list[Signal] = []
        for row in rows:
            signals.append(
                Signal(
                    company=row["company"],
                    type=SignalType(row["type"]),
                    observed_at=datetime.fromisoformat(row["observed_at"]),
                    source=row.get("source", self.name),
                    detail=row.get("detail"),
                )
            )
        return signals
