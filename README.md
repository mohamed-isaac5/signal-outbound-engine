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
signals ──> ICP score ──> enrichment waterfall ──> draft ──> approval queue ──> send
 (demo)     (published      (verified/risky/       (offline   (approve/reject,   (never
             formula)        unknown, costed)       default)   audit-logged)      without
                                                                                 approval)
```

## Quickstart (offline, no keys, no spend)

```bash
pip install -e .
soe score   --source data/demo_signals.json
soe enrich  --contacts data/demo_contacts.json --providers data/demo_enrichment.json
soe draft   --signals data/demo_signals.json --contacts data/demo_contacts.json \
            --providers data/demo_enrichment.json --db run.db
soe approve --db run.db --list
```

Everything runs offline against labeled demo fixtures (fictional companies and
contacts). Live providers plug into the same protocols.

## Demo output (from the labeled fixtures)

```
CONTACT                         EMAIL                               STATUS    FOUND BY
Sara Adel / Northwind Traders   sara.adel@northwind-demo.example    verified  apollo-demo
Omar Fathy / Globex             omar.fathy@globex-demo.example      risky     apollo-demo
Mona Samir / Acme Corp          mona.samir@acme-demo.example        verified  clay-demo
Karim Nabil / Initech           (unknown)                           unknown   -

enriched 3/4 for $0.48 ($0.16 per found email)
```

These numbers come from the demo run, not real sends. The cost math is real:
every provider lookup is billed to the ledger, hit or miss, so cost per
enriched lead is measured, not estimated.

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
key, no spend, every draft labeled `OFFLINE DEMO DRAFT`. An Anthropic adapter
implements the same interface and activates the day `ANTHROPIC_API_KEY` is
set; without a key it fails loudly, never silently falls back.

## Principles

- **Deterministic core.** Scoring, waterfall order, queue rules: pure functions
  with tests. CI runs ruff, mypy --strict and pytest (36 tests) on 3.11/3.12.
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
- Next: live connectors, n8n/MCP exposure, sequence export.

- [x] M0 - scaffold, contracts, tests, CI
- [x] M1 - signal connectors + scoring runs
- [x] M2 - enrichment waterfall (costed, verification states)
- [x] M3 - drafting (offline provider default; Anthropic adapter ready)
- [x] M4 - approval queue + audit trail
- [x] M5 - this case study

## License

MIT - see [LICENSE](LICENSE).
