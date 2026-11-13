"""`soe` command line: the engine's one-entry-point interface."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from engine import __version__
from engine.connectors import DemoFileSource
from engine.runner import audit_run, render_table, run_scoring
from engine.store import open_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="soe",
        description="Signal-driven outbound engine.",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")

    score = sub.add_parser("score", help="score signals against the ICP")
    score.add_argument("--source", type=Path, required=True, help="JSON fixture of signals")
    score.add_argument("--window", type=int, default=30, help="freshness window in days")
    score.add_argument("--db", type=Path, default=None, help="audit database path")

    sub.add_parser("enrich", help="run the enrichment waterfall (M2)")
    sub.add_parser("draft", help="draft outreach from approved fits (M3)")
    sub.add_parser("approve", help="review the approval queue (M4)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command == "score":
        result = run_scoring(DemoFileSource(args.source), window_days=args.window)
        print(render_table(result))
        if args.db is not None:
            conn: sqlite3.Connection = open_db(args.db)
            audit_run(conn, result)
        return 0
    if args.command is None:
        parser.print_help()
        return 0
    print(f"`soe {args.command}` lands in a later milestone - see README roadmap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
