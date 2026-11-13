"""`soe` command line: the engine's one-entry-point interface."""

from __future__ import annotations

import argparse
import json as _json
import sqlite3
from pathlib import Path

from engine import __version__
from engine.connectors import DemoFileSource
from engine.enrich import Contact, run_waterfall
from engine.providers_demo import load_demo_providers
from engine.runner import audit_run, render_table, run_scoring
from engine.store import log_event, open_db


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

    enrich = sub.add_parser("enrich", help="run the enrichment waterfall")
    enrich.add_argument("--contacts", type=Path, required=True, help="JSON list of contacts")
    enrich.add_argument(
        "--providers", type=Path, required=True, help="JSON fixture of demo providers"
    )
    enrich.add_argument("--db", type=Path, default=None, help="audit database path")
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
    if args.command == "enrich":
        providers = load_demo_providers(args.providers)
        rows = _json.loads(args.contacts.read_text())
        print(f"providers={' -> '.join(pv.name for pv in providers)}")
        print()
        print(f"{'CONTACT':<32}{'EMAIL':<36}{'STATUS':<10}{'FOUND BY':<14}{'COST':>7}")
        total = 0.0
        found = 0
        econn = open_db(args.db) if args.db is not None else None
        for row in rows:
            contact = Contact(
                name=row["name"], company=row["company"], title=row.get("title")
            )
            eresult = run_waterfall(contact, providers)
            total += eresult.cost_usd
            found += eresult.contact.email is not None
            email = eresult.contact.email or "(unknown)"
            print(
                f"{contact.name + ' / ' + contact.company:<32}"
                f"{email:<36}{eresult.contact.email_status.value:<10}"
                f"{eresult.found_by or '-':<14}${eresult.cost_usd:>6.2f}"
            )
            if econn is not None:
                log_event(
                    econn,
                    "enrichment",
                    f"{contact.name}@{contact.company}: "
                    f"{eresult.contact.email_status.value} "
                    f"by={eresult.found_by or 'none'} cost=${eresult.cost_usd:.2f}",
                )
        print()
        label = f"enriched {found}/{len(rows)} for ${total:.2f}"
        if found:
            label += f" (${total / found:.2f} per found email)"
        print(label)
        return 0
    if args.command is None:
        parser.print_help()
        return 0
    print(f"`soe {args.command}` lands in a later milestone - see README roadmap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
