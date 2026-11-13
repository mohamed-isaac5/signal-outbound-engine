"""First-run UX: `soe run` and `soe guide`.

The engine's commands are verbs; this module is the sentence. It takes a
non-engineer from zero to an exported CSV: what each step is about to do,
what just happened, and exactly which file they got and what to do with it.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from engine import demo_fixtures
from engine.approve import Approval, Decision, decide, enqueue, pending
from engine.connectors import DemoFileSource
from engine.enrich import Contact, run_waterfall
from engine.export import export_approved
from engine.icp import DRAFT_THRESHOLD
from engine.icp_config import ICP, CompanyProfile, load_companies, role_matches
from engine.llm import OFFLINE_LABEL, OfflineProvider
from engine.providers_demo import load_demo_providers
from engine.runner import audit_run, render_table, run_scoring
from engine.store import log_event, open_db

DATA_DIR = Path("data")
SIGNALS = DATA_DIR / "demo_signals.json"
CONTACTS = DATA_DIR / "demo_contacts.json"
PROVIDERS = DATA_DIR / "demo_enrichment.json"
COMPANIES = DATA_DIR / "demo_companies.json"
DB = Path("run.db")
OUT = Path("approved.csv")


class NonInteractive(Exception):
    """No terminal to answer prompts (piped stdin, CI, tests)."""


def default_reviewer() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "me"


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, OSError) as exc:
        raise NonInteractive from exc


def ensure_fixtures() -> bool:
    """Generate demo fixtures when missing. Returns True when it generated."""
    if all(p.exists() for p in (SIGNALS, CONTACTS, PROVIDERS, COMPANIES)):
        return False
    print("No demo data found - generating fresh demo data (timestamps relative to now).")
    for path in demo_fixtures.write_all(DATA_DIR):
        print(f"  wrote {path}")
    print()
    return True


def missing_inputs() -> list[Path]:
    return [p for p in (SIGNALS, CONTACTS, PROVIDERS, COMPANIES) if not p.exists()]


def _score_step(
    conn: sqlite3.Connection | None = None,
    icp: ICP | None = None,
    companies: dict[str, CompanyProfile] | None = None,
) -> int:
    """Score and narrate. Returns the number of qualified companies."""
    run = run_scoring(DemoFileSource(SIGNALS), icp=icp, companies=companies)
    print(render_table(run))
    qualified = sum(1 for f in run.scores if f.qualifies)
    if icp is not None:
        print(
            f"-> {qualified} of {len(run.scores)} companies qualify "
            f"({DRAFT_THRESHOLD}+ points, inside the ICP)."
        )
    else:
        print(
            f"-> {qualified} of {len(run.scores)} companies are over the "
            f"{DRAFT_THRESHOLD}-point bar and route to drafting."
        )
    if conn is not None:
        audit_run(conn, run)
    return qualified


def _enrich_step(conn: sqlite3.Connection | None = None) -> tuple[int, int, float]:
    """Enrich and narrate. Returns (found, total, cost)."""
    providers = load_demo_providers(PROVIDERS)
    rows = json.loads(CONTACTS.read_text())
    print(f"providers={' -> '.join(pv.name for pv in providers)}")
    print()
    print(f"{'CONTACT':<32}{'EMAIL':<36}{'STATUS':<10}{'FOUND BY':<14}{'COST':>7}")
    total = 0.0
    found = 0
    for row in rows:
        contact = Contact(name=row["name"], company=row["company"], title=row.get("title"))
        eresult = run_waterfall(contact, providers)
        total += eresult.cost_usd
        found += eresult.contact.email is not None
        email = eresult.contact.email or "(unknown)"
        print(
            f"{contact.name + ' / ' + contact.company:<32}"
            f"{email:<36}{eresult.contact.email_status.value:<10}"
            f"{eresult.found_by or '-':<14}${eresult.cost_usd:>6.2f}"
        )
        if conn is not None:
            log_event(
                conn,
                "enrichment",
                f"{contact.name}@{contact.company}: {eresult.contact.email_status.value} "
                f"by={eresult.found_by or 'none'} cost=${eresult.cost_usd:.2f}",
            )
    print()
    label = f"-> found {found}/{len(rows)} emails for ${total:.2f}"
    if found:
        label += f" (${total / found:.2f} per found email)"
    print(label + " - every lookup billed, unknown stays unknown.")
    return found, len(rows), total


def _draft_step(
    conn: sqlite3.Connection,
    icp: ICP | None = None,
    companies: dict[str, CompanyProfile] | None = None,
) -> int:
    """Draft for qualified fits and enqueue. Returns drafts written."""
    run = run_scoring(DemoFileSource(SIGNALS), icp=icp, companies=companies)
    fits = {f.company: f for f in run.scores}
    providers = load_demo_providers(PROVIDERS)
    rows = json.loads(CONTACTS.read_text())
    drafter = OfflineProvider()
    made = 0
    for row in rows:
        fit = fits.get(row["company"])
        if fit is None or not fit.qualifies:
            if fit is not None and fit.exclusion:
                reason = f"outside ICP - {fit.exclusion}"
            else:
                reason = "below the fit bar"
            print(f"  skipped {row['name']} ({row['company']}): {reason}")
            continue
        contact = Contact(name=row["name"], company=row["company"], title=row.get("title"))
        eresult = run_waterfall(contact, providers)
        if eresult.contact.email is None:
            print(f"  skipped {contact.name} ({contact.company}): no email found")
            continue
        if icp is not None and not role_matches(contact.title, icp.target_roles):
            print(
                f"  skipped {contact.name} ({contact.company}): "
                f"title '{contact.title or 'unknown'}' outside ICP target roles"
            )
            continue
        draft = drafter.draft(eresult.contact, fit)
        outcome = enqueue(conn, f"{draft.contact.company}:{draft.contact.email}", draft)
        if outcome != "kept_decided":
            log_event(
                conn,
                "draft_created",
                f"to={draft.contact.email} fit={draft.fit.points} provider={draft.provider}",
            )
        made += 1
        print(f"  drafted for {draft.contact.email} (fit {draft.fit.points}) [{outcome}]")
    print(f"-> {made} draft(s) written, each labeled: {OFFLINE_LABEL}")
    return made


def review_queue(
    conn: sqlite3.Connection, reviewer: str, assume_yes: bool = False
) -> tuple[int, int, int]:
    """Walk the pending queue draft by draft. Returns (approved, rejected, skipped)."""
    rows = pending(conn)
    if not rows:
        print("Your review queue is empty - nothing is waiting for a decision.")
        return (0, 0, 0)
    approved = rejected = skipped = 0
    for i, row in enumerate(rows, 1):
        print()
        print(f"--- Draft {i} of {len(rows)} " + "-" * 52)
        print(f"TO: {row['recipient']}  ({row['company']}, fit {row['fit_points']})")
        print(f"SUBJECT: {row['subject']}")
        print()
        print(row["body"])
        print()
        if assume_yes:
            decide(
                conn,
                Approval(
                    draft_id=str(row["id"]),
                    decision=Decision.APPROVED,
                    reviewer=reviewer,
                ),
            )
            print(f"-> approved by {reviewer} (--yes) - audit-logged")
            approved += 1
            continue
        while True:
            answer = _ask("Approve this draft? [y]es / [n]o / [s]kip: ").strip().lower()
            if answer in ("y", "yes"):
                decide(
                    conn,
                    Approval(
                        draft_id=str(row["id"]),
                        decision=Decision.APPROVED,
                        reviewer=reviewer,
                    ),
                )
                print(f"-> approved by {reviewer} - audit-logged")
                approved += 1
                break
            if answer in ("n", "no"):
                while True:
                    reason = _ask(
                        "Reason for rejecting (required, goes in the audit log): "
                    ).strip()
                    if reason:
                        break
                    print("A rejection needs a reason - the audit log keeps it.")
                decide(
                    conn,
                    Approval(
                        draft_id=str(row["id"]),
                        decision=Decision.REJECTED,
                        reviewer=reviewer,
                        reason=reason,
                    ),
                )
                print(f"-> rejected by {reviewer} - audit-logged")
                rejected += 1
                break
            if answer in ("s", "skip"):
                print("-> left pending (still in your queue)")
                skipped += 1
                break
            print("Please answer y, n or s.")
    return approved, rejected, skipped


def print_summary(out: Path, count: int, db: Path, already_exported: bool = False) -> None:
    """The last thing a user reads: what they got and what to do with it."""
    print()
    print("=" * 72)
    print("DONE - here is exactly what you got")
    print("=" * 72)
    if count:
        print(f"File: {out}  ({count} approved email(s), Smartlead/Instantly CSV)")
        print()
        print("What to do with it:")
        print("  1. Open Smartlead or Instantly and create a campaign.")
        print("  2. Choose 'Upload CSV' for the lead list.")
        print(f"  3. Upload {out} - columns map to: email, first_name, last_name,")
        print("     company_name, subject, email_body.")
    elif already_exported:
        print(f"File: {out}  (already holds your exported approved emails)")
        print("Nothing new to export since then. What to do with the file:")
        print("  upload it in Smartlead/Instantly (campaign -> Upload CSV).")
    else:
        print("No approved drafts to export yet - approve some first: soe approve")
    print()
    print(f"Why anything happened: soe audit   (every decision and event, in {db})")


def run_pipeline(
    db: Path,
    out: Path,
    icp: ICP | None = None,
    companies: dict[str, CompanyProfile] | None = None,
) -> int:
    """`soe run`: the whole happy path, zero flags, narrated. Non-interactive."""
    print("SOE RUN - the whole pipeline start to finish. Offline, no keys, nothing sends.")
    print()
    ensure_fixtures()
    if companies is None:
        companies = load_companies(COMPANIES)
    conn = open_db(db)

    print("Step 1/3 - SCORING: which companies show fresh buying signals right now?")
    _score_step(conn, icp=icp, companies=companies)
    print()

    print("Step 2/3 - ENRICHMENT: find each contact's email.")
    _enrich_step(conn)
    print()

    print("Step 3/3 - DRAFTING: write the emails. Each one waits for YOUR approval.")
    _draft_step(conn, icp=icp, companies=companies)
    print()

    waiting = len(pending(conn))
    print("=" * 72)
    print(f"RUN COMPLETE - {waiting} draft(s) waiting for your review.")
    print("Nothing sends without your approval - that is the point of the gate.")
    print("=" * 72)
    print()
    print("Next step:  soe approve   (read each email, approve or reject)")
    print("Then:       soe export    (writes approved.csv for Smartlead/Instantly)")
    print("New here?   soe guide     (same flow, with explanations at every step)")
    return 0


def run_guide(
    db: Path,
    out: Path,
    assume_yes: bool,
    reviewer: str,
    icp: ICP | None = None,
    companies: dict[str, CompanyProfile] | None = None,
) -> int:
    """`soe guide`: the interactive walkthrough, plain language at every step."""
    print("Welcome to the guided run. About two minutes, five steps.")
    print("Everything here is offline demo data: no API keys, no spend,")
    print("and nothing ever sends - drafts wait for your explicit approval.")
    try:
        if not assume_yes:
            _ask("\nPress Enter to start...")
        print()
        if ensure_fixtures():
            print("That was the demo data - fictional companies, labeled everywhere.")
            print()
        if companies is None:
            companies = load_companies(COMPANIES)

        print("Step 1/4 - SCORING")
        print("We look for fresh buying signals (hiring, funding, tech changes) and")
        print("score each company against a published formula. 50+ points means the")
        print("account is worth an email. Here is the scoreboard:")
        if icp is not None:
            print("Your ICP also boosts accounts that fit and filters out ones that don't.")
        print()
        qualified = _score_step(icp=icp, companies=companies)
        print()
        print(f"So {qualified} companies qualified. Next we need their emails.")
        if not assume_yes:
            _ask("\nPress Enter for step 2 (enrichment)...")
        print()

        print("Step 2/4 - ENRICHMENT")
        print("Each contact goes through a paid-provider waterfall: the first provider")
        print("that finds the email wins, every lookup is billed and shown, and a")
        print("contact nobody could find stays honestly 'unknown'. Watch:")
        print()
        found, total_rows, cost = _enrich_step()
        print()
        print(f"That cost ${cost:.2f} in demo money for {found}/{total_rows} emails.")
        if not assume_yes:
            _ask("\nPress Enter for step 3 (drafting)...")
        print()

        print("Step 3/4 - DRAFTING")
        print("Now the engine writes one email per qualified, reachable contact.")
        print("Drafts are template-generated here (clearly labeled), and each one")
        print("goes into YOUR review queue - it cannot send itself. Writing:")
        print()
        conn = open_db(db)
        _draft_step(conn, icp=icp, companies=companies)
        print()
        print("Step 4/4 - YOUR REVIEW (the human gate)")
        print("Read each email below and approve or reject it. Rejections ask for a")
        print("reason so the audit trail explains the decision.")
        approved, rejected, skipped = review_queue(conn, reviewer, assume_yes)
        print()
        print(f"Review done: {approved} approved, {rejected} rejected, {skipped} pending.")
        print()

        print("Exporting your approved drafts now...")
        count = export_approved(conn, out)
        approved_ever = conn.execute(
            "SELECT count(*) FROM drafts WHERE status = 'approved'"
        ).fetchone()[0]
        print_summary(out, count, db, already_exported=bool(approved_ever))
        print()
        print("That is the whole system. Any time you want this again: soe guide")
        return 0
    except NonInteractive:
        print()
        print("No interactive terminal found, so I can't walk you through prompts.")
        print("Options:")
        print("  soe guide --yes   run the guide without pauses (approves every draft)")
        print("  soe run           the whole pipeline in one shot, review after with: soe approve")
        return 2
