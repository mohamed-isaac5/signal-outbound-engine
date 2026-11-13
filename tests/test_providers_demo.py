import json
from pathlib import Path

import pytest

from engine.enrich import Contact, EmailStatus
from engine.providers_demo import DemoProvider, load_demo_providers

FIXTURE = Path(__file__).resolve().parent.parent / "data" / "demo_enrichment.json"


def test_demo_providers_load_in_waterfall_order() -> None:
    providers = load_demo_providers(FIXTURE)
    assert [p.name for p in providers] == ["apollo-demo", "clay-demo"]
    assert providers[0].unit_cost_usd < providers[1].unit_cost_usd


def test_demo_lookup_hit_and_miss() -> None:
    providers = load_demo_providers(FIXTURE)
    hit = providers[0].find_email(Contact(name="Sara Adel", company="Northwind Traders"))
    assert hit is not None and hit.status is EmailStatus.VERIFIED
    assert providers[0].find_email(Contact(name="Nobody", company="Nowhere")) is None


def test_negative_unit_cost_rejected() -> None:
    with pytest.raises(ValueError, match="negative unit cost"):
        DemoProvider(name="bad", unit_cost_usd=-0.01, data={})


def test_load_demo_providers_rejects_negative_cost(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"providers": [{"name": "bad", "unit_cost_usd": -5, "data": {}}]}))
    with pytest.raises(ValueError, match="negative unit cost"):
        load_demo_providers(path)
