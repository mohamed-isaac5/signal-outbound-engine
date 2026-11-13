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
    export = sub.add_parser("export", help="export approved drafts to a sequencer CSV")
    export.add_argument("--db", type=Path, required=True, help="queue/audit database path")
    export.add_argument("--out", type=Path, required=True, help="CSV output path")
    export.add_argument(
        "--all",
        action="store_true",
        help="re-export drafts already exported (default: only new approvals)",
    )
    audit = sub.add_parser("audit", help="query the audit trail")
    audit.add_argument("--db", type=Path, required=True, help="queue/audit database path")
    audit.add_argument(
        "--id", dest="draft_id", default=None, help="trace one draft id (default: all events)"
    )
    demo = sub.add_parser("demo", help="run the whole chain offline and narrate each step")
    demo.add_argument(
        "--data-dir", type=Path, default=Path("data"), help="directory with demo_*.json fixtures"
    )
    demo.add_argument(
        "--db", type=Path, default=Path("demo.db"), help="queue/audit database path"
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
    if args.command == "export":
        from engine.export import export_approved

        xconn = open_db(args.db)
        count = export_approved(xconn, args.out, include_exported=args.all)
        if count:
            print(f"exported {count} approved draft(s) to {args.out} (Smartlead/Instantly CSV)")
        else:
            print("no approved drafts waiting for export")
        return 0
    if args.command == "audit":
        aud_conn = open_db(args.db)
        if args.draft_id is None:
            rows = aud_conn.execute(
                "SELECT created_at, event, detail FROM audit ORDER BY id"
            ).fetchall()
            if not rows:
                print("audit log is empty")
            for created_at, event, detail in rows:
                print(f"{created_at}  {event:<16} {detail}")
            return 0
        from engine.approve import ensure_queue

        ensure_queue(aud_conn)
        row = aud_conn.execute(
            "SELECT status, reviewer, reason, decided_at, fit_points, provider, recipient"
            " FROM drafts WHERE id = ?",
            (args.draft_id,),
        ).fetchone()
        if row is None:
            print(f"no draft with id {args.draft_id}")
            return 2
        status, reviewer, reason, decided_at, fit_points, provider, recipient = row
        print(f"draft {args.draft_id}")
        print(f"  to={recipient} fit={fit_points} provider={provider}")
        print(f"  status={status}"
              + (f" by={reviewer} at={decided_at}" if reviewer else ""))
        if reason:
            print(f"  reason={reason}")
        # LIKE metacharacters in ids/emails are data, not patterns.
        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        events = aud_conn.execute(
            "SELECT created_at, event, detail FROM audit"
            " WHERE detail LIKE ? ESCAPE '\\' OR detail LIKE ? ESCAPE '\\' ORDER BY id",
            (f"id={esc(args.draft_id)}%", f"%to={esc(recipient)}%"),
        ).fetchall()
        print("  trail:")
        for created_at, event, detail in events:
            print(f"    {created_at}  {event}: {detail}")
        return 0
    if args.command == "demo":
        return run_demo(args.data_dir, args.db)
    if args.command is None:
        parser.print_help()
    return 0


def run_demo(data_dir: Path, db: Path) -> int:
    """One command, whole chain, narrated. Offline, no keys, no sends."""
    from engine.approve import enqueue, pending

    signals_path = data_dir / "demo_signals.json"
    contacts_path = data_dir / "demo_contacts.json"
    providers_path = data_dir / "demo_enrichment.json"
    for path in (signals_path, contacts_path, providers_path):
        if not path.exists():
            print(f"missing {path} - run: python -m engine.demo_fixtures")
            return 2

    print("SIGNAL-OUTBOUND-ENGINE DEMO - offline, labeled demo data, nothing sends")
    print()
    print("== 1/4 SCORING - fresh buying signals against the published ICP formula")
    run = run_scoring(DemoFileSource(signals_path))
    print(render_table(run))
    qualified = {f.company: f for f in run.scores if f.qualifies}
    print()
    print(f"-> {len(qualified)} account(s) over the 50-point bar route to drafting")
    print()
    print("== 2/4 ENRICHMENT - costed waterfall, unknown stays unknown")
    providers = load_demo_providers(providers_path)
    rows = json.loads(contacts_path.read_text())
    print(f"providers={' -> '.join(pv.name for pv in providers)}")
    contacts = [Contact(name=r["name"], company=r["company"], title=r.get("title")) for r in rows]
    enriched = {c.company: run_waterfall(c, providers) for c in contacts}
    for company, eresult in enriched.items():
        email = eresult.contact.email or "(unknown - no provider found an email)"
        print(f"  {eresult.contact.name} / {company}: {email} (${eresult.cost_usd:.2f})")
    total = sum(r.cost_usd for r in enriched.values())
    found = sum(1 for r in enriched.values() if r.contact.email is not None)
    print(f"-> {found}/{len(rows)} emails found for ${total:.2f} - every lookup billed")
    print()
    print("== 3/4 DRAFTING - offline provider, every draft labeled")
    conn = open_db(db)
    made = 0
    for company, eresult in enriched.items():
        fit = qualified.get(company)
        if fit is None:
            print(f"  skipped {eresult.contact.name} ({company}): below the fit bar")
            continue
        if eresult.contact.email is None:
            print(f"  skipped {eresult.contact.name} ({company}): no email found")
            continue
        drafter = OfflineProvider()
        d = drafter.draft(eresult.contact, fit)
        outcome = enqueue(conn, f"{d.contact.company}:{d.contact.email}", d)
        made += 1
        print(f"  drafted for {d.contact.email} (fit {d.fit.points}) [{outcome}]")
    print(f"-> {made} draft(s), each labeled: {OFFLINE_LABEL}")
    print()
    print("== 4/4 THE HUMAN GATE - nothing sends without a named approver")
    rows_pending = pending(conn)
    for r in rows_pending:
        print(f"  pending: {r['id']} (fit {r['fit_points']})")
    print()
    print("No message was sent. The approval queue is the boundary.")
    print(f"Next: soe approve --db {db} --list   (then approve or reject each)")
    print(f"Then: soe export  --db {db} --out approved.csv   (to Smartlead/Instantly)")
    print(f"Why:  soe audit   --db {db} --id '<draft-id>'   (full trace)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
