"""`soe` command line: the engine's one-entry-point interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine import __version__
from engine.connectors import DemoFileSource
from engine.enrich import Contact, run_waterfall
from engine.llm import OFFLINE_LABEL, AnthropicProvider, OfflineProvider
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
    draft = sub.add_parser("draft", help="draft outreach for qualified fits (offline default)")
    draft.add_argument("--signals", type=Path, required=True, help="JSON fixture of signals")
    draft.add_argument("--contacts", type=Path, required=True, help="JSON list of contacts")
    draft.add_argument(
        "--providers", type=Path, required=True, help="JSON fixture of demo providers"
    )
    draft.add_argument("--window", type=int, default=30, help="freshness window in days")
    draft.add_argument("--db", type=Path, default=None, help="audit database path")
    draft.add_argument(
        "--provider",
        choices=["offline", "anthropic"],
        default="offline",
        help="drafting provider (default: offline, no key needed)",
    )
    approve = sub.add_parser("approve", help="review the approval queue")
    approve.add_argument("--db", type=Path, required=True, help="queue/audit database path")
    approve.add_argument("--list", action="store_true", help="list pending drafts")
    approve.add_argument("--id", dest="draft_id", default=None, help="draft id to decide")
    approve.add_argument(
        "--decision", choices=["approved", "rejected"], default=None, help="the decision"
    )
    approve.add_argument("--reviewer", default=None, help="who is deciding (required)")
    approve.add_argument("--reason", default=None, help="required when rejecting")
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
            conn = open_db(args.db)
            audit_run(conn, result)
        return 0
    if args.command == "enrich":
        providers = load_demo_providers(args.providers)
        rows = json.loads(args.contacts.read_text())
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
    if args.command == "draft":
        from engine.icp import DRAFT_THRESHOLD

        run = run_scoring(DemoFileSource(args.signals), window_days=args.window)
        qualified = {f.company: f for f in run.scores if f.points >= DRAFT_THRESHOLD}
        providers = load_demo_providers(args.providers)
        rows = json.loads(args.contacts.read_text())
        drafter = (
            OfflineProvider() if args.provider == "offline" else AnthropicProvider()
        )
        dconn = open_db(args.db) if args.db is not None else None
        made = 0
        for row in rows:
            fit = qualified.get(row["company"])
            if fit is None:
                print(
                    f"skipped {row['name']} ({row['company']}): "
                    f"no qualified fit (below {DRAFT_THRESHOLD} points or no fresh signals)"
                )
                continue
            contact = Contact(
                name=row["name"], company=row["company"], title=row.get("title")
            )
            eresult = run_waterfall(contact, providers)
            if eresult.contact.email is None:
                print(
                    f"skipped {contact.name} ({contact.company}): "
                    "no email found by any provider - unknown stays unknown"
                )
                continue
            d = drafter.draft(eresult.contact, fit)
            made += 1
            print("=" * 72)
            print(f"TO: {d.contact.email}  (fit {d.fit.points}, provider: {d.provider})")
            print(f"SUBJECT: {d.subject}")
            print()
            print(d.body)
            if dconn is not None:
                from engine.approve import enqueue

                outcome = enqueue(dconn, f"{d.contact.company}:{d.contact.email}", d)
                if outcome != "kept_decided":
                    log_event(
                        dconn,
                        "draft_created",
                        f"to={d.contact.email} fit={d.fit.points} provider={d.provider}",
                    )
        print("=" * 72)
        # The offline label belongs to the offline provider only - an LLM
        # provider's drafts must never be labeled as template output.
        label = f" - {OFFLINE_LABEL}" if isinstance(drafter, OfflineProvider) else ""
        print(f"{made} draft(s) created with provider '{drafter.name}'{label}")
        if dconn is not None:
            from engine.approve import pending

            waiting = len(pending(dconn))
            if waiting:
                print(f"{waiting} draft(s) waiting in the approval queue.")
                print(f"Review with: soe approve --db {args.db} --list")
        return 0
    if args.command == "approve":
        from engine.approve import Approval, Decision, decide, pending

        aconn = open_db(args.db)
        if args.list:
            rows = pending(aconn)
            if not rows:
                print("approval queue is empty")
            for r in rows:
                print(f"{r['id']}  -> {r['recipient']}  ({r['company']}, fit {r['fit_points']})")
                print(f"    {r['subject']}")
            return 0
        if not (args.draft_id and args.decision and args.reviewer):
            print("approve needs --id, --decision and --reviewer (see --help)")
            return 2
        decide(
            aconn,
            Approval(
                draft_id=args.draft_id,
                decision=Decision(args.decision),
                reviewer=args.reviewer,
                reason=args.reason,
            ),
        )
        print(f"{args.draft_id}: {args.decision} by {args.reviewer} - audit-logged")
        return 0
    if args.command is None:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
