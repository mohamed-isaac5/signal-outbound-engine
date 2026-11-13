"""`soe` command line: the engine's one-entry-point interface."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from engine import __version__
from engine.approve import OUTCOME_WORDS
from engine.connectors import DemoFileSource
from engine.enrich import Contact, run_waterfall
from engine.icp_config import ICP, CompanyProfile
from engine.llm import OFFLINE_LABEL, AnthropicProvider, OfflineProvider
from engine.providers_demo import load_demo_providers
from engine.runner import audit_run, render_table, run_scoring
from engine.store import log_event, open_db


def build_parser() -> argparse.ArgumentParser:
    from engine import onboard

    examples = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(
        prog="soe",
        description="Signal-driven outbound engine: buying signals in, approved outreach out.",
        epilog=(
            "Start here (no flags needed, works on offline demo data):\n"
            "  soe run       the whole pipeline in one shot, with a summary at the end\n"
            "  soe guide     same flow, but it explains every step and walks you through\n"
            "  soe approve   read each drafted email, approve or reject it\n"
            "  soe export    write approved.csv, ready to upload to Smartlead/Instantly\n"
            "\n"
            "Every command runs on the demo data with zero flags; flags override inputs."
        ),
        formatter_class=examples,
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")

    run_cmd = sub.add_parser(
        "run",
        help="DO the work: the whole pipeline in one shot (best first command)",
        epilog=(
            "examples:\n"
            "  soe run                     everything, on the demo data\n"
            "  soe run --db my.db          keep the queue/audit in my.db"
        ),
        formatter_class=examples,
    )
    run_cmd.add_argument("--db", type=Path, default=onboard.DB, help="queue/audit database path")
    run_cmd.add_argument("--out", type=Path, default=onboard.OUT, help="CSV written at export time")
    run_cmd.add_argument(
        "--icp",
        type=Path,
        default=None,
        help="ICP file (default: icp.toml, then the shipped example)",
    )

    guide = sub.add_parser(
        "guide",
        help="LEARN it: guided walkthrough, you approve each draft",
        epilog=(
            "examples:\n"
            "  soe guide                   interactive: pauses, you review each draft\n"
            "  soe guide --yes             no pauses; approves every draft (demo use)"
        ),
        formatter_class=examples,
    )
    guide.add_argument("--db", type=Path, default=onboard.DB, help="queue/audit database path")
    guide.add_argument("--out", type=Path, default=onboard.OUT, help="CSV written at export time")
    guide.add_argument(
        "--yes",
        action="store_true",
        help="no pauses; approve every draft (reviewer still named in the audit log)",
    )
    guide.add_argument(
        "--reviewer", default=None, help="whose name the approvals record (default: $USER)"
    )
    guide.add_argument(
        "--icp",
        type=Path,
        default=None,
        help="ICP file (default: icp.toml, then the shipped example)",
    )

    score = sub.add_parser(
        "score",
        help="score signals against the ICP",
        epilog=(
            "examples:\n"
            "  soe score                           demo signals, 30-day window\n"
            "  soe score --source s.json --window 14"
        ),
        formatter_class=examples,
    )
    score.add_argument(
        "--source", type=Path, default=onboard.SIGNALS, help="JSON fixture of signals"
    )
    score.add_argument("--window", type=int, default=30, help="freshness window in days")
    score.add_argument("--db", type=Path, default=None, help="audit database path")
    score.add_argument(
        "--icp",
        type=Path,
        default=None,
        help="ICP file (default: icp.toml, then the shipped example)",
    )

    enrich = sub.add_parser(
        "enrich",
        help="run the enrichment waterfall",
        epilog="examples:\n  soe enrich\n  soe enrich --contacts c.json --providers p.json",
        formatter_class=examples,
    )
    enrich.add_argument(
        "--contacts", type=Path, default=onboard.CONTACTS, help="JSON list of contacts"
    )
    enrich.add_argument(
        "--providers", type=Path, default=onboard.PROVIDERS, help="JSON fixture of demo providers"
    )
    enrich.add_argument("--db", type=Path, default=None, help="audit database path")
    draft = sub.add_parser(
        "draft",
        help="draft outreach for qualified fits (offline default)",
        epilog=(
            "examples:\n"
            "  soe draft\n"
            "  soe draft --provider anthropic   (needs ANTHROPIC_API_KEY)"
        ),
        formatter_class=examples,
    )
    draft.add_argument(
        "--signals", type=Path, default=onboard.SIGNALS, help="JSON fixture of signals"
    )
    draft.add_argument(
        "--contacts", type=Path, default=onboard.CONTACTS, help="JSON list of contacts"
    )
    draft.add_argument(
        "--providers", type=Path, default=onboard.PROVIDERS, help="JSON fixture of demo providers"
    )
    draft.add_argument("--window", type=int, default=30, help="freshness window in days")
    draft.add_argument("--db", type=Path, default=onboard.DB, help="audit database path")
    draft.add_argument(
        "--icp",
        type=Path,
        default=None,
        help="ICP file (default: icp.toml, then the shipped example)",
    )
    draft.add_argument(
        "--provider",
        choices=["offline", "anthropic"],
        default="offline",
        help="drafting provider (default: offline, no key needed)",
    )
    export = sub.add_parser(
        "export",
        help="export approved drafts to a sequencer CSV",
        epilog="examples:\n  soe export\n  soe export --out leads.csv --all",
        formatter_class=examples,
    )
    export.add_argument("--db", type=Path, default=onboard.DB, help="queue/audit database path")
    export.add_argument("--out", type=Path, default=onboard.OUT, help="CSV output path")
    export.add_argument(
        "--all",
        action="store_true",
        help="re-export drafts already exported (default: only new approvals)",
    )
    audit = sub.add_parser(
        "audit",
        help="query the audit trail",
        epilog="examples:\n  soe audit\n  soe audit --id '<draft-id>'   (one draft's full trace)",
        formatter_class=examples,
    )
    audit.add_argument("--db", type=Path, default=onboard.DB, help="queue/audit database path")
    audit.add_argument(
        "--id", dest="draft_id", default=None, help="trace one draft id (default: all events)"
    )
    demo = sub.add_parser(
        "demo",
        help="WATCH it: the whole chain offline, narrated like a presentation",
    )
    demo.add_argument(
        "--data-dir", type=Path, default=Path("data"), help="directory with demo_*.json fixtures"
    )
    demo.add_argument(
        "--db", type=Path, default=Path("demo.db"), help="queue/audit database path"
    )
    demo.add_argument(
        "--icp",
        type=Path,
        default=None,
        help="ICP file (default: icp.toml, then the shipped example)",
    )
    icp_cmd = sub.add_parser(
        "icp",
        help="your Ideal Customer Profile: show it, set it up, or edit one field",
        epilog=(
            "examples:\n"
            "  soe icp show     the ICP scoring currently uses\n"
            "  soe icp setup    answer a few questions, writes icp.toml\n"
            "  soe icp edit     change one field without redoing setup"
        ),
        formatter_class=examples,
    )
    icp_sub = icp_cmd.add_subparsers(dest="icp_command")
    icp_sub.add_parser("show", help="show the ICP scoring currently uses")
    icp_sub.add_parser("setup", help="guided questions, writes icp.toml")
    icp_sub.add_parser("edit", help="change one field of icp.toml")
    approve = sub.add_parser(
        "approve",
        help="review the approval queue (interactive by default)",
        epilog=(
            "examples:\n"
            "  soe approve                 walk the queue, approve/reject each draft\n"
            "  soe approve --list          just list what is waiting\n"
            "  soe approve --id '<draft-id>' --decision approved --reviewer sara"
        ),
        formatter_class=examples,
    )
    approve.add_argument("--db", type=Path, default=onboard.DB, help="queue/audit database path")
    approve.add_argument("--list", action="store_true", help="list pending drafts")
    approve.add_argument("--id", dest="draft_id", default=None, help="draft id to decide")
    approve.add_argument(
        "--decision", choices=["approved", "rejected"], default=None, help="the decision"
    )
    approve.add_argument(
        "--reviewer", default=None, help="who is deciding (default: $USER)"
    )
    approve.add_argument("--reason", default=None, help="required when rejecting")
    return parser


def _load_icp_or_report(flag_path: Path | None) -> tuple[ICP | None, str] | None:
    """Resolve the ICP; on a config error print it plainly and return None."""
    from engine.icp_config import ICPError, resolve_icp

    try:
        return resolve_icp(flag_path)
    except ICPError as exc:
        print(exc)
        print()
        print("Fix the file, or make a fresh one: soe icp setup")
        return None


def _icp_and_companies(
    flag_path: Path | None, companies_path: Path
) -> tuple[ICP | None, dict[str, CompanyProfile]] | None:
    """ICP plus company metadata for the scoring commands; None = error already printed."""
    from engine.icp_config import load_companies

    resolved = _load_icp_or_report(flag_path)
    if resolved is None:
        return None
    icp, note = resolved
    if note:
        print(note)
        print()
    return (icp, load_companies(companies_path))


# Audit display: raw event names stay in the database; people read labels.
EVENT_LABELS = {
    "scoring_run": "scored",
    "enrichment": "enriched",
    "draft_created": "draft written",
    "draft_enqueued": "draft queued",
    "draft_decision": "decision",
    "export": "exported",
}


def _local_time(utc_text: str) -> str:
    """Audit timestamps are stored in UTC; people read their own clock."""
    from datetime import datetime, timezone

    try:
        moment = datetime.strptime(utc_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return utc_text
    return moment.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _event_label(event: str) -> str:
    return EVENT_LABELS.get(event, event)


def _missing_inputs(paths: list[Path]) -> int:
    """Friendly error when the demo inputs are not on disk yet."""
    for path in paths:
        print(f"missing {path}")
    print()
    print("The demo data files are not here yet. Easiest fix:")
    print("  soe run   (generates the demo data and runs everything)")
    return 2


def _welcome() -> None:
    """What `soe` with no command prints: oriented, not a wall of flags."""
    print("Signal-Outbound Engine - turns buying signals into approved outreach.")
    print("Offline demo by default: no API keys, no spend, nothing sends.")
    print()
    print("Usage: soe <command>")
    print()
    print("New here? Pick one:")
    print("  soe run      DO the work: the whole pipeline, start to finish")
    print("  soe guide    LEARN it: same flow, explains every step")
    print("  soe demo     WATCH it: the whole chain narrated like a presentation")
    print()
    print("Then:")
    print("  soe approve  read each drafted email, approve or reject it")
    print("  soe export   write approved.csv, ready to upload to Smartlead/Instantly")
    print("  soe icp      define who you sell to (industries, size, countries, roles)")
    print()
    print("Every command works with zero flags on the demo data.")
    print("All commands and options: soe --help")
    try:
        from engine.approve import pending
        from engine.onboard import DB

        if DB.exists():
            waiting = len(pending(open_db(DB)))
            if waiting:
                print()
                print(f"Right now: {waiting} draft(s) waiting for your review - soe approve")
    except Exception:  # the welcome screen must never fail on an unreadable db
        pass


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except sqlite3.DatabaseError:
        print("The local database file is damaged or is not a database.")
        print("Move it away (your audit history lives in it), then start fresh: soe run")
        return 2


def _main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command == "run":
        from engine.onboard import run_pipeline

        resolved = _load_icp_or_report(args.icp)
        if resolved is None:
            return 2
        icp, note = resolved
        if note:
            print(note)
            print()
        # companies load inside run_pipeline, after fixtures are generated
        return run_pipeline(args.db, args.out, icp=icp)
    if args.command == "guide":
        from engine.onboard import default_reviewer, run_guide

        resolved = _load_icp_or_report(args.icp)
        if resolved is None:
            return 2
        icp, note = resolved
        if note:
            print(note)
            print()
        # companies load inside run_guide, after fixtures are generated
        return run_guide(args.db, args.out, args.yes, args.reviewer or default_reviewer(), icp=icp)
    if args.command == "score":
        if not args.source.exists():
            return _missing_inputs([args.source])
        from engine.onboard import COMPANIES

        ctx = _icp_and_companies(args.icp, COMPANIES)
        if ctx is None:
            return 2
        print("Scoring: points for fresh buying signals, filtered and boosted by")
        print("your customer profile. 50+ points routes a company to drafting.")
        print()
        result = run_scoring(
            DemoFileSource(args.source), window_days=args.window, icp=ctx[0], companies=ctx[1]
        )
        print(render_table(result))
        if args.db is not None:
            conn = open_db(args.db)
            audit_run(conn, result)
        print()
        print("Next: soe enrich   (find each contact's email)")
        return 0
    if args.command == "enrich":
        if not args.contacts.exists() or not args.providers.exists():
            return _missing_inputs([args.contacts, args.providers])
        print("Enrichment: find each contact's email through the provider waterfall.")
        print("Every lookup is billed; a contact nobody finds stays 'unknown'.")
        print()
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
        print()
        print("Next: soe draft   (write the outreach emails)")
        return 0
    if args.command == "draft":
        from engine.icp import DRAFT_THRESHOLD

        if not args.signals.exists() or not args.contacts.exists() or not args.providers.exists():
            return _missing_inputs([args.signals, args.contacts, args.providers])
        from engine.icp_config import role_matches
        from engine.onboard import COMPANIES

        ctx = _icp_and_companies(args.icp, COMPANIES)
        if ctx is None:
            return 2
        icp, companies = ctx
        print("Drafting: one email per qualified, reachable contact.")
        print("Each draft waits for YOUR approval - nothing sends itself.")
        print()
        run = run_scoring(
            DemoFileSource(args.signals), window_days=args.window, icp=icp, companies=companies
        )
        fits = {f.company: f for f in run.scores}
        providers = load_demo_providers(args.providers)
        rows = json.loads(args.contacts.read_text())
        drafter = (
            OfflineProvider(sender_name=icp.sender_name if icp else None)
            if args.provider == "offline"
            else AnthropicProvider()
        )
        dconn = open_db(args.db) if args.db is not None else None
        made = 0
        for row in rows:
            fit = fits.get(row["company"])
            if fit is None or not fit.qualifies:
                if fit is not None and fit.exclusion:
                    reason = f"outside ICP - {fit.exclusion}"
                else:
                    reason = (
                        f"no qualified fit (below {DRAFT_THRESHOLD} points or no fresh signals)"
                    )
                print(f"skipped {row['name']} ({row['company']}): {reason}")
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
            if icp is not None and not role_matches(contact.title, icp.target_roles):
                print(
                    f"skipped {contact.name} ({contact.company}): "
                    f"title '{contact.title or 'unknown'}' outside ICP target roles"
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
                print(f"Review with: soe approve --db {args.db}")
        return 0
    if args.command == "approve":
        from engine.approve import Approval, Decision, decide, pending
        from engine.onboard import (
            NonInteractive,
            default_reviewer,
            review_queue,
        )

        aconn = open_db(args.db)
        if args.list:
            rows = pending(aconn)
            if not rows:
                print("approval queue is empty")
            for r in rows:
                print(f"{r['id']}  -> {r['recipient']}  ({r['company']}, fit {r['fit_points']})")
                print(f"    {r['subject']}")
            if rows:
                print()
                print("Next: soe approve   (walk them one by one)")
            return 0
        if args.draft_id is None:
            # Interactive review: show each draft, ask approve/reject/skip.
            try:
                a, r, s = review_queue(aconn, args.reviewer or default_reviewer())
            except NonInteractive:
                print("No interactive terminal, so I can't prompt you. Either:")
                print("  soe approve --list")
                print("  soe approve --id '<draft-id>' --decision approved --reviewer <you>")
                return 2
            if a or r or s:
                print()
                print(f"Queue done: {a} approved, {r} rejected, {s} still pending.")
            if a:
                print("Next: soe export   (write approved.csv for Smartlead/Instantly)")
            return 0
        if not (args.decision and args.reviewer):
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
        if args.decision == "approved":
            print("Next: soe export   (when you are done reviewing)")
        return 0
    if args.command == "export":
        from engine.export import export_approved

        xconn = open_db(args.db)
        count = export_approved(xconn, args.out, include_exported=args.all)
        if count:
            print(f"exported {count} approved draft(s) to {args.out} (Smartlead/Instantly CSV)")
            print()
            print(f"Next: upload {args.out} in Smartlead/Instantly (campaign -> Upload CSV).")
            print("Why anything happened: soe audit")
        else:
            print("no approved drafts waiting for export")
            print("Approve some first: soe approve")
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
                detail = detail.replace("(enqueued)", "(waiting for your review)")
                print(f"{_local_time(created_at)}  {_event_label(event):<16} {detail}")
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
              + (f" by={reviewer} at={_local_time(decided_at) if decided_at else '-'}"
                 if reviewer else ""))
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
            detail = detail.replace("(enqueued)", "(waiting for your review)")
            print(f"    {_local_time(created_at)}  {_event_label(event)}: {detail}")
        return 0
    if args.command == "icp":
        from engine.icp_config import ICP_FILE, ICPError, render_icp, resolve_icp

        if args.icp_command in (None, "show"):
            try:
                shown, note = resolve_icp(None)
            except ICPError as exc:
                print(exc)
                return 2
            if shown is None:
                print("No ICP yet - the engine runs without ICP filtering.")
                print("Create one: soe icp setup")
                return 0
            print(render_icp(shown, note or str(ICP_FILE)))
            print()
            print("This profile filters (outside = excluded with a reason) and boosts")
            print("(+points) the scoring in: soe run, score, draft, demo and guide.")
            print("Change it: soe icp edit   Start over: soe icp setup")
            return 0
        if args.icp_command == "setup":
            return _icp_setup(ICP_FILE)
        if args.icp_command == "edit":
            return _icp_edit(ICP_FILE)
    if args.command == "demo":
        return run_demo(args.data_dir, args.db, args.icp)
    if args.command is None:
        _welcome()
    return 0


def run_demo(data_dir: Path, db: Path, icp_flag: Path | None = None) -> int:
    """One command, whole chain, narrated. Offline, no keys, no sends."""
    from engine.approve import enqueue, pending
    from engine.icp_config import role_matches

    signals_path = data_dir / "demo_signals.json"
    contacts_path = data_dir / "demo_contacts.json"
    providers_path = data_dir / "demo_enrichment.json"
    if not all(p.exists() for p in (signals_path, contacts_path, providers_path)):
        print("No demo data found - generating fresh demo data (timestamps relative to now).")
        from engine import demo_fixtures
        for path in demo_fixtures.write_all(data_dir):
            print(f"  wrote {path}")
        print()

    ctx = _icp_and_companies(icp_flag, data_dir / "demo_companies.json")
    if ctx is None:
        return 2
    icp, companies = ctx

    print("SIGNAL-OUTBOUND-ENGINE DEMO - offline, labeled demo data, nothing sends")
    print("(WATCH mode. To DO the work: soe run. To LEARN it step by step: soe guide.)")
    print()
    print("== 1/4 SCORING - fresh buying signals against the published ICP formula")
    run = run_scoring(DemoFileSource(signals_path), icp=icp, companies=companies)
    print(render_table(run))
    fits = {f.company: f for f in run.scores}
    qualified = {c: f for c, f in fits.items() if f.qualifies}
    print()
    if icp is not None:
        print(f"-> {len(qualified)} account(s) qualify (50+ points, inside the ICP)")
    else:
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
        fit = fits.get(company)
        if fit is None or not fit.qualifies:
            if fit is not None and fit.exclusion:
                reason = f"outside ICP - {fit.exclusion}"
            else:
                reason = "below the fit bar"
            print(f"  skipped {eresult.contact.name} ({company}): {reason}")
            continue
        if eresult.contact.email is None:
            print(f"  skipped {eresult.contact.name} ({company}): no email found")
            continue
        if icp is not None and not role_matches(eresult.contact.title, icp.target_roles):
            print(
                f"  skipped {eresult.contact.name} ({company}): "
                f"title '{eresult.contact.title or 'unknown'}' outside ICP target roles"
            )
            continue
        drafter = OfflineProvider(sender_name=icp.sender_name if icp else None)
        d = drafter.draft(eresult.contact, fit)
        outcome = enqueue(conn, f"{d.contact.company}:{d.contact.email}", d)
        made += 1
        print(f"  drafted for {d.contact.email} (fit {d.fit.points}) - {OUTCOME_WORDS[outcome]}")
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


def _ask_with_default(prompt: str, default: str) -> str:
    from engine.onboard import _ask

    answer = _ask(f"{prompt} [{default}]: ").strip()
    return answer or default


def _ask_list(prompt: str, default: tuple[str, ...]) -> tuple[str, ...]:
    shown = ", ".join(default) if default else "none"
    raw = _ask_with_default(f"{prompt} (comma-separated)", shown)
    if raw.strip().lower() in ("none", "-"):
        return ()
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def _ask_int(prompt: str, default: int | None) -> int | None:
    from engine.onboard import _ask

    shown = "none" if default is None else str(default)
    while True:
        raw = _ask(f"{prompt} [{shown}]: ").strip()
        if not raw:
            return default
        if raw.lower() in ("none", "no cap", "-"):
            return None
        try:
            value = int(raw)
        except ValueError:
            print("Please type a whole number.")
            continue
        if value < 0:
            print("Please type zero or more.")
            continue
        return value


def _icp_setup(path: Path) -> int:
    """Guided questions -> icp.toml. Defaults come from the shipped example."""
    from engine import onboard
    from engine.icp import SIGNAL_WEIGHTS
    from engine.icp_config import (
        EXAMPLE_FILE,
        ICP,
        PACKAGE_EXAMPLE,
        ICPError,
        load_icp,
        render_icp,
        write_icp,
    )
    from engine.signals import SignalType

    base: ICP | None = None
    example = EXAMPLE_FILE if EXAMPLE_FILE.exists() else PACKAGE_EXAMPLE
    if example.exists():
        try:
            base = load_icp(example)
        except ICPError:
            base = None
    if base is None:
        base = ICP(
            name="My ICP",
            industries=("saas",),
            size_min=10,
            size_max=1000,
            countries=("US",),
            target_roles=("vp sales",),
            signal_weights=None,
            exclude_industries=(),
        )
    base = replace(base, name="My ICP")
    print("Set up your Ideal Customer Profile. Press Enter to keep the [default].")
    print()
    try:
        name = _ask_with_default("Who is this ICP for? (a short name)", base.name)
        industries = _ask_list(
            "Industries you sell to (others get excluded with a reason)", base.industries
        )
        size_min = _ask_int(
            "Company size - minimum employees (smaller gets excluded)", base.size_min
        )
        size_max = _ask_int(
            "Company size - maximum employees (bigger gets excluded)", base.size_max
        )
        countries = _ask_list("Countries you sell to (2-letter codes)", base.countries)
        roles = _ask_list("Job titles you target (other titles get skipped)", base.target_roles)
        exclude = _ask_list("Industries to never contact", base.exclude_industries)
        sender = _ask_with_default(
            "Your name, to sign the emails", base.sender_name or "demo signature"
        )
        sender_name = None if sender == "demo signature" else sender
        weights = None
        defaults = base.signal_weights or {t.value: SIGNAL_WEIGHTS[t] for t in SignalType}
        tune = _ask_with_default(
            "Tune signal weights (which signals matter most to you)? y/N", "N"
        ).lower()
        if tune in ("y", "yes"):
            weights = {}
            for signal_type in SignalType:
                value = _ask_int(
                    f"  points for {signal_type.value}", defaults[signal_type.value]
                )
                weights[signal_type.value] = value if value is not None else 0
        if size_min is not None and size_max is not None and size_min > size_max:
            print("Minimum size can't be bigger than maximum - nothing written.")
            return 2
        icp = ICP(
            name=name,
            industries=industries,
            size_min=size_min,
            size_max=size_max,
            countries=countries,
            target_roles=roles,
            signal_weights=weights,
            exclude_industries=exclude,
            sender_name=sender_name,
        )
        print()
        print(render_icp(icp, f"{path} (not saved yet)"))
        print()
        save = _ask_with_default("Save this profile? Y/n", "Y").lower()
        if save not in ("y", "yes"):
            print("Nothing written. Re-run any time: soe icp setup")
            return 0
    except onboard.NonInteractive:
        print("The setup questions need a real terminal (input ended early).")
        print("Easiest: run  soe icp setup  again in your terminal and answer the 6 questions.")
        print(f"Or by hand: cp {example} icp.toml  and edit it.")
        return 2
    write_icp(icp, path)
    print()
    print(f"Wrote {path} - this is now your ICP.")
    print("Check it:  soe icp show")
    print("Next:      soe run   (scoring now uses your ICP)")
    return 0


def _icp_edit(path: Path) -> int:
    """Change one field of an existing icp.toml."""

    from engine import onboard
    from engine.icp import SIGNAL_WEIGHTS
    from engine.icp_config import ICPError, load_icp, render_icp, write_icp
    from engine.onboard import _ask
    from engine.signals import SignalType

    if not path.exists():
        print(f"No {path} here yet - create one first: soe icp setup")
        return 2
    try:
        icp = load_icp(path)
    except ICPError as exc:
        print(exc)
        print("Fix the file by hand, or start over: soe icp setup")
        return 2
    print(render_icp(icp, str(path)))
    print()
    fields = [
        "name",
        "industries",
        "company size",
        "countries",
        "target roles",
        "excluded industries",
        "signal weights",
    ]
    for number, field in enumerate(fields, 1):
        print(f"  {number}) {field}")
    print("  0) cancel")
    try:
        choice = (_ask("Change which field? [0]: ").strip() or "0")
        if choice == "0":
            print("Nothing changed.")
            return 0
        if choice == "1":
            icp = replace(icp, name=_ask_with_default("ICP name", icp.name))
        elif choice == "2":
            icp = replace(icp, industries=_ask_list("Industries you sell to", icp.industries))
        elif choice == "3":
            size_min = _ask_int("Minimum employees", icp.size_min)
            size_max = _ask_int("Maximum employees", icp.size_max)
            if size_min is not None and size_max is not None and size_min > size_max:
                print("Minimum can't be bigger than maximum - nothing changed.")
                return 2
            icp = replace(icp, size_min=size_min, size_max=size_max)
        elif choice == "4":
            icp = replace(icp, countries=_ask_list("Countries you sell to", icp.countries))
        elif choice == "5":
            icp = replace(icp, target_roles=_ask_list("Job titles you target", icp.target_roles))
        elif choice == "6":
            icp = replace(
                icp,
                exclude_industries=_ask_list("Industries to never contact", icp.exclude_industries),
            )
        elif choice == "7":
            current = icp.signal_weights or {t.value: SIGNAL_WEIGHTS[t] for t in SignalType}
            weights = {}
            for signal_type in SignalType:
                value = _ask_int(
                    f"points for {signal_type.value}", current[signal_type.value]
                )
                weights[signal_type.value] = value if value is not None else 0
            icp = replace(icp, signal_weights=weights)
        else:
            print("Unknown choice - nothing changed.")
            return 2
    except onboard.NonInteractive:
        print("No interactive terminal - edit icp.toml by hand instead.")
        return 2
    write_icp(icp, path)
    print()
    print(f"Updated {path}:")
    print(render_icp(icp, str(path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
