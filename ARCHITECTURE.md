# Architecture

One loop, five stages, one boundary:

```
signals ──> ICP score ──> enrichment waterfall ──> draft ──> approval queue ──> export
 (demo)     (published      (verified/risky/       (offline   (approve/reject,   (Smartlead/
             formula)        unknown, costed)       default)   audit-logged)      Instantly CSV)
```

Each stage is a small module behind a protocol; the CLI (`soe`) is the only
entry point; SQLite is the only state. The pieces compose in one direction
and never call back up the chain.

| Module | Owns | Key contract |
| --- | --- | --- |
| `engine/signals.py` | The Signal model, freshness | Unknown fields stay `None`; timestamps must be timezone-aware |
| `engine/connectors.py` | `SignalSource` protocol, demo file source | Any source yields normalized `Signal`s |
| `engine/icp.py` | The published scoring formula | Pure function: same signals, same score |
| `engine/enrich.py` | `EnrichmentProvider` protocol, the waterfall | First hit wins; every lookup is billed |
| `engine/llm.py` | `DraftingProvider` protocol, offline + Anthropic | The prompt is inspectable; no silent fallback |
| `engine/approve.py` | The queue and decisions | Decision + audit row commit in one transaction |
| `engine/export.py` | Sequencer CSV (Smartlead/Instantly) | Only approved drafts leave the building |
| `engine/store.py` | The audit log | Every event is a row; nothing is ephemeral |
| `engine/runner.py`, `engine/cli.py` | Composition and the `soe` surface | Thin; logic lives in the modules |

# Architecture decision records

## ADR-0001: Offline-first, honest by default

**Decision.** The default path runs fully offline against labeled demo
fixtures. The drafting default is a deterministic template provider, and
every draft it produces is labeled `OFFLINE DEMO DRAFT`. The Anthropic
adapter is real but optional; without a key it fails loudly.

**Why.** Anyone - a hiring manager, a future teammate, me in six months -
can clone and run the whole engine in two minutes with no keys and no
spend. The alternative (a README full of setup steps and a demo that
needs three API keys) means most people never see the system work.

**Cost.** The demo data is fictional and labeled as such. The engine never
pretends template output is LLM output, and never invents a field it did
not observe (unknown stays `null`). Honesty is a feature, not a gap.

## ADR-0002: A named human approves every message

**Decision.** No draft sends from this engine. Drafts wait in a queue; a
named reviewer approves or rejects (rejections require a reason); only
approved drafts export. Double decisions are refused; a decided draft is
never overwritten by a re-run.

**Why.** The failure mode of automated outbound is not a bad email, it is a
thousand bad emails with your name on them. The queue makes the human gate
structural - a property of the system, not a promise in the README - and
the audit trail makes every send traceable to the signals, score, provider
and approver that produced it.

**Cost.** Throughput is bounded by review time. That is the point.

## ADR-0003: SQLite as the only state

**Decision.** Queue and audit log live in one SQLite file, written in the
same transactions as the state they record.

**Why.** Zero infrastructure: the audit trail ships inside the repo's
quickstart with nothing to install. One file you can open, query and hand
to anyone. Single-file durability beats a service dependency for a tool
whose whole point is running anywhere.

**Cost.** Single-writer. If this ever serves concurrent approvers, the
decide path needs a conditional `UPDATE ... WHERE status='pending'` and a
moved-to-Postgres conversation. Noted, not needed today.

## ADR-0004: Protocols over frameworks

**Decision.** Sources, enrichment providers and drafting providers are
Python protocols (`SignalSource`, `EnrichmentProvider`,
`DraftingProvider`). The engine core has zero third-party dependencies;
the Anthropic SDK is an optional extra.

**Why.** A protocol is the smallest contract that lets a live Apollo
connector, a Clay provider or a different LLM plug in without touching the
core. Tests run against stub and demo implementations, so the suite is
fast, deterministic and offline - 81 tests in under a second.

**Cost.** No framework magic: no dependency injection, no plugin
discovery. Wiring is explicit in `cli.py`. For a system this size,
explicit is cheaper than magic.

## ADR-0005: The scoring formula is published, not tuned in secret

**Decision.** The ICP weights and the draft threshold (50) live in
`engine/icp.py`, in the README, and are pinned to each other by tests.
Every score keeps its reasons, and every draft keeps its score breakdown.

**Why.** A score you cannot explain is a score you cannot defend - in a
pipeline review or an interview. Publishing the formula invites the right
question ("why is hiring worth 30?") and the answer is a conversation,
not a shrug. Weights are meant to be debated and changed; the tests make
changing them a deliberate act.

**Cost.** The formula is simple and linear by design. Sophisticated
scoring would buy marginal accuracy and cost explainability.
