import json
from datetime import datetime, timezone
from pathlib import Path

from engine.connectors import DemoFileSource
from engine.signals import SignalType


def test_demo_source_parses_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "signals.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "company": "Acme",
                    "type": "hiring",
                    "observed_at": datetime.now(tz=timezone.utc).isoformat(),
                    "detail": "demo",
                }
            ]
        )
    )
    signals = DemoFileSource(fixture).fetch()
    assert len(signals) == 1
    assert signals[0].type is SignalType.HIRING
    assert signals[0].source == "demo-file"
