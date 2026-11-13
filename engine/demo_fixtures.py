"""Demo fixture generator.

Writes the labeled demo dataset (fictional companies and contacts) with
timestamps RELATIVE TO NOW, so the offline quickstart keeps working no
matter when the repo is cloned. Run `python -m engine.demo_fixtures`
any time to refresh data/demo_*.json. Demo data is demo data.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def signals(now: datetime) -> list[dict[str, str]]:
    def d(days: float) -> str:
        return (now - timedelta(days=days)).isoformat()

    return [
        {"company": "Northwind Traders", "type": "hiring", "observed_at": d(3),
         "source": "demo-file", "detail": "Hiring 2 SDRs (demo)"},
        {"company": "Northwind Traders", "type": "funding", "observed_at": d(9),
         "source": "demo-file", "detail": "Series A announced (demo)"},
        {"company": "Acme Corp", "type": "intent", "observed_at": d(5),
         "source": "demo-file", "detail": "Pricing-page visits spiked (demo)"},
        {"company": "Globex", "type": "tech_change", "observed_at": d(12),
         "source": "demo-file", "detail": "Added a new CRM (demo)"},
        {"company": "Globex", "type": "hiring", "observed_at": d(20),
         "source": "demo-file", "detail": "Hiring a RevOps lead (demo)"},
        {"company": "Initech", "type": "leadership_change", "observed_at": d(7),
         "source": "demo-file", "detail": "New VP Sales (demo)"},
        {"company": "Umbrella Labs", "type": "funding", "observed_at": d(60),
         "source": "demo-file", "detail": "Seed round, stale (demo)"},
    ]


def contacts() -> list[dict[str, str]]:
    return [
        {"name": "Sara Adel", "company": "Northwind Traders", "title": "VP Sales"},
        {"name": "Omar Fathy", "company": "Globex", "title": "RevOps Lead"},
        {"name": "Mona Samir", "company": "Acme Corp", "title": "Head of Growth"},
        {"name": "Karim Nabil", "company": "Initech", "title": "CTO"},
    ]


def providers() -> dict[str, object]:
    return {
        "providers": [
            {
                "name": "apollo-demo",
                "unit_cost_usd": 0.06,
                "data": {
                    "Sara Adel@Northwind Traders": {
                        "email": "sara.adel@northwind-demo.example", "status": "verified"
                    },
                    "Omar Fathy@Globex": {
                        "email": "omar.fathy@globex-demo.example", "status": "risky"
                    },
                },
            },
            {
                "name": "clay-demo",
                "unit_cost_usd": 0.12,
                "data": {
                    "Mona Samir@Acme Corp": {
                        "email": "mona.samir@acme-demo.example", "status": "verified"
                    }
                },
            },
        ]
    }


def write_all(directory: Path = DATA_DIR) -> list[Path]:
    """Write all three demo fixtures with run-relative timestamps."""
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc)
    written = []
    for name, payload in (
        ("demo_signals.json", signals(now)),
        ("demo_contacts.json", contacts()),
        ("demo_enrichment.json", providers()),
    ):
        path = directory / name
        path.write_text(json.dumps(payload, indent=2) + "\n")
        written.append(path)
    return written


def main() -> int:
    for path in write_all():
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
