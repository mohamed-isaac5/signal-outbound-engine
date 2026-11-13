"""Scoring runs: source -> fresh signals -> fit scores -> ranked output.

A run is deterministic for a fixed fixture and window: same input, same table.
Every run is logged to the audit store with its inputs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from engine.connectors import SignalSource
from engine.icp import FitScore, score_signals
from engine.signals import fresh


@dataclass(frozen=True)
class RunResult:
    source: str
    window_days: int
    scores: tuple[FitScore, ...]


def run_scoring(source: SignalSource, window_days: int = 30) -> RunResult:
    signals = [s for s in source.fetch() if fresh(s, window_days)]
    companies = sorted({s.company for s in signals})
    scores = [score_signals(c, [s for s in signals if s.company == c]) for c in companies]
    scores.sort(key=lambda f: f.points, reverse=True)
    return RunResult(source=source.name, window_days=window_days, scores=tuple(scores))


def render_table(result: RunResult) -> str:
    lines = [f"source={result.source} window={result.window_days}d", ""]
    lines.append(f"{'COMPANY':<22}{'FIT':>5}  {'ROUTES TO DRAFT':<16}REASONS")
    for fit in result.scores:
        routes = "yes" if fit.qualifies else "no"
        lines.append(f"{fit.company:<22}{fit.points:>5}  {routes:<16}{'; '.join(fit.reasons)}")
    return "\n".join(lines)


def audit_run(conn: sqlite3.Connection, result: RunResult) -> None:
    from engine.store import log_event

    detail = "; ".join(f"{f.company}={f.points}" for f in result.scores) or "no fresh signals"
    log_event(conn, "scoring_run", f"source={result.source} window={result.window_days}d: {detail}")
