# signal-outbound-engine

![CI](https://github.com/mohamed-isaac5/signal-outbound-engine/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**Signal-driven outbound, end to end, with a human gate.** Capture buying
signals, score them against a published ICP formula, enrich contacts through a
costed waterfall, draft outreach, and let a named human approve or reject every
message - each step audit-logged.

Outbound teams stitch this together by hand across five tools. This engine is
the whole loop in one deterministic, testable core:

```
signals ──> ICP score ──> enrichment waterfall ──> draft ──> approval queue ──> export
 (demo)     (published      (verified/risky/       (offline   (approve/reject,   (Smartlead/
             formula)        unknown, costed)       default)   audit-logged)      Instantly
                                                                                 CSV)
```

## Setup

**Prerequisites:** Python **3.11 or newer** and git. Nothing else - no API
keys, no accounts, no services.

```bash
git clone https://github.com/mohamed-isaac5/signal-outbound-engine.git
cd signal-outbound-engine
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"        # engine + test/lint tooling
# optional, for the real Anthropic drafting adapter:
# pip install -e ".[anthropic]"
```

**Verify the install** (about a second):

```bash
pytest -q     # 83 tests, all offline
soe demo      # the whole chain, narrated, on labeled demo data
```

If both run clean, everything is set up.

**First run, step by step:**

```bash
python -m engine.demo_fixtures   # fresh demo data (timestamps relative to now)
soe score   --source data/demo_signals.json
soe enrich  --contacts data/demo_contacts.json --providers data/demo_enrichment.json
soe draft   --signals data/demo_signals.json --contacts data/demo_contacts.json \
            --providers data/demo_enrichment.json --db run.db
soe approve --db run.db --list
soe approve --db run.db --id '<draft-id>' --decision approved --reviewer <you>
soe export  --db run.db --out approved.csv   # Smartlead/Instantly-ready CSV
soe audit   --db run.db --id '<draft-id>'    # the full trace for one draft
```

**Troubleshooting:**

- `ERROR: Package ... requires a different Python: 3.10.x not in '>=3.11'` -
  your Python is too old. Install 3.11+ (pyenv, uv, or your package manager)
  and recreate the venv.
- `soe: command not found` - the venv is not activated:
  `source .venv/bin/activate`.
- `RuntimeError: ANTHROPIC_API_KEY is not set` - expected if you passed
  `--provider anthropic` without a key. The default provider needs no key;
  drop the flag, or export a key.
- Every account scores 0 / no fresh signals - the demo data predates your
  clone: run `python -m engine.demo_fixtures` to regenerate it.
- `sqlite3.OperationalError: database is locked` - another process has the
  run database open. One process at a time per `.db` file.

## Quickstart (offline, no keys, no spend)

```bash
pip install -e .
python -m engine.demo_fixtures   # refresh demo data (timestamps relative to now)
soe score   --source data/demo_signals.json
soe enrich  --contacts data/demo_contacts.json --providers data/demo_enrichment.json
soe draft   --signals data/demo_signals.json --contacts data/demo_contacts.json \
            --providers data/demo_enrichment.json --db run.db
soe approve --db run.db --list
```

Or watch the whole chain narrated end to end in one command:

```bash
soe demo
```

Everything runs offline against labeled demo fixtures (fictional companies and
contacts). Live providers plug into the same protocols. Demo timestamps are
generated relative to when you run the generator, so the quickstart behaves
identically no matter when you clone the repo.

## Demo output (from the labeled fixtures)

```
providers=apollo-demo -> clay-demo

CONTACT                         EMAIL                               STATUS    FOUND BY         COST
Sara Adel / Northwind Traders   sara.adel@northwind-demo.example    verified  apollo-demo   $  0.06
Omar Fathy / Globex             omar.fathy@globex-demo.example      risky     apollo-demo   $  0.06
Mona Samir / Acme Corp          mona.samir@acme-demo.example        verified  clay-demo     $  0.18
Karim Nabil / Initech           (unknown)                           unknown   -             $  0.18

enriched 3/4 for $0.48 ($0.16 per found email)
```

These numbers come from the demo run, not real sends. The per-lookup costs
are representative demo numbers (the real tools sell subscriptions and
credits); the cost ledger is the point - every provider lookup is billed to
it, hit or miss, so cost per enriched lead is measured, not estimated.

## Scoring

The ICP fit formula is published, not hidden:

| Signal | Points |
| --- | --- |
| Hiring (relevant role) | 30 |
| Funding round | 25 |
| Tech-stack change | 20 |
| Intent spike | 15 |
| Leadership change | 10 |

A combined fit of **50+** routes the account to drafting. Signals older than
the freshness window (default 30 days) stop counting. Every draft keeps its
score breakdown (`reasons`), so any message traces back to the exact signals
and points that produced it.

## Drafting: honest by default

Drafting is provider-agnostic. The default provider is **offline and
deterministic** - template drafts assembled from the real score reasons, no API
key, no spend, every draft labeled `OFFLINE DEMO DRAFT`. A real Anthropic
adapter (Messages API) implements the same interface:

```bash
pip install -e ".[anthropic]"
export ANTHROPIC_API_KEY=...
soe draft --signals data/demo_signals.json --contacts data/demo_contacts.json \
          --providers data/demo_enrichment.json --provider anthropic
```

The exact prompt is inspectable (`engine.llm.build_prompt`). Without a key the
adapter fails loudly, never silently falls back.

## After approval: export and trace

Approved drafts - and only approved drafts - export to a CSV shaped for
Smartlead/Instantly import. Each export is audit-logged and exports only newly
approved work (`--all` re-exports everything):

```bash
soe export --db run.db --out approved.csv
```

Every draft carries its full trace: the signals and score that produced it,
who approved or rejected it, when and why.

```bash
soe audit --db run.db                                    # every event
soe audit --db run.db --id 'Northwind Traders:sara.adel@northwind-demo.example'
```

The design decisions (why offline-first, why the human gate, why SQLite) are
recorded as ADRs in [ARCHITECTURE.md](ARCHITECTURE.md).

## Principles

- **Deterministic core.** Scoring, waterfall order, queue rules: pure functions
  with tests. CI runs ruff, mypy --strict and pytest (83 tests) on 3.11/3.12.
- **Honesty over coverage.** A field the providers cannot find stays `null`.
  The engine never invents data to fill a gap - see Karim above.
- **Human gate.** Drafts wait in an approval queue. A named reviewer approves
  or rejects (rejections need a reason; double decisions are refused). Every
  enqueue and decision is audit-logged in SQLite.

## Limitations and roadmap

- Signal sources and enrichment providers here are labeled demo fixtures;
  live connectors (job boards, funding news, Apollo/Clay) implement the same
  `SignalSource` / `EnrichmentProvider` protocols.
- No sending integration yet by design: the approval queue is the boundary.
- Next: live connectors, n8n/MCP exposure.

- [x] M0 - scaffold, contracts, tests, CI
- [x] M1 - signal connectors + scoring runs
- [x] M2 - enrichment waterfall (costed, verification states)
- [x] M3 - drafting (offline provider default; Anthropic adapter ready)
- [x] M4 - approval queue + audit trail
- [x] M5 - this case study
- [x] M6 - sequencer export (Smartlead/Instantly CSV), one-command `soe demo`,
  audit-trail query (`soe audit`), architecture ADRs

## License

MIT - see [LICENSE](LICENSE).
