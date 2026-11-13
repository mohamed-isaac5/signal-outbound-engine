"""Scoring runs: source -> fresh signals -> fit scores -> ranked output.

A run is deterministic for a fixed fixture and window: same input, same table.
Every run is logged to the audit store with its inputs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from engine.connectors import SignalSource
from engine.icp import FitScore, score_signals
from engine.icp_config import ICP, CompanyProfile
from engine.signals import fresh


@dataclass(frozen=True)
class RunResult:
    source: str
    window_days: int
    scores: tuple[FitScore, ...]


def run_scoring(
    source: SignalSource,
    window_days: int = 30,
    icp: ICP | None = None,
    companies: dict[str, CompanyProfile] | None = None,
) -> RunResult:
    signals = [s for s in source.fetch() if fresh(s, window_days)]
    profiles = companies or {}
    names = sorted({s.company for s in signals})
    scores = [
        score_signals(c, [s for s in signals if s.company == c], icp=icp, meta=profiles.get(c))
        for c in names
    ]
    scores.sort(key=lambda f: f.points, reverse=True)
    return RunResult(source=source.name, window_days=window_days, scores=tuple(scores))


def _display_reasons(fit: FitScore, source: str) -> str:
    """Reasons for the table: the shared source name is said once in the header."""
    suffix = f" ({source})"
    shown = [r[: -len(suffix)] if r.endswith(suffix) else r for r in fit.reasons]
    return "; ".join(shown)


def render_table(result: RunResult) -> str:
    lines = [f"source: {result.source}, last {result.window_days} days", ""]
    lines.append(f"{'COMPANY':<22}{'FIT':>5}  {'ROUTES TO DRAFT':<16}REASONS")
    for fit in result.scores:
        routes = "excluded" if fit.exclusion else ("yes" if fit.qualifies else "no")
        lines.append(
            f"{fit.company:<22}{fit.points:>5}  {routes:<16}{_display_reasons(fit, result.source)}"
        )
    excluded = [f"{f.company} ({f.exclusion})" for f in result.scores if f.exclusion]
    if excluded:
        lines.append("")
        lines.append("outside ICP: " + "; ".join(excluded))
    return "\n".join(lines)


def audit_run(conn: sqlite3.Connection, result: RunResult) -> None:
    from engine.store import log_event

    detail = "; ".join(f"{f.company}={f.points}" for f in result.scores) or "no fresh signals"
    log_event(conn, "scoring_run", f"source={result.source} window={result.window_days}d: {detail}")
