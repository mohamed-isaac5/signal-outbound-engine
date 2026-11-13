# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.2] - 2026-11-13

### Fixed
- The LLM prompt no longer implies a 100-point cap ("Fit score: 130/100") -
  fit is uncapped and the prompt now says so, pinned by a test with a >100 fit.
- Demo providers reject a negative unit cost with a clear error instead of
  letting the cost ledger go negative.
- `soe draft` now prints a skipped line with a reason for every contact it
  does not draft (below threshold / no fresh signals / no email found) -
  nothing is dropped silently.

## [1.1.1] - 2026-11-13

### Fixed
- `soe draft --provider anthropic` no longer ends with the OFFLINE DEMO DRAFT
  label - that label only prints for the offline provider whose drafts it
  actually describes.
- The "waiting in the approval queue" line now reports the real pending count
  from the queue, not the number of drafts generated in this run.
- A contact with an empty or whitespace-only name fails fast with a clear
  ValueError instead of an IndexError mid-draft.
- README demo output block synced to the real `soe enrich` output (providers
  line and COST column) and pinned to the live output by a test.

## [1.1.0] - 2026-11-13

### Added
- Real Anthropic Messages API adapter behind the optional `anthropic` extra,
  with an inspectable prompt builder (`engine.llm.build_prompt`) and
  `--provider anthropic` on `soe draft`.
- `python -m engine.demo_fixtures`: regenerates the demo dataset with
  run-relative timestamps, so the quickstart never rots.

### Fixed
- `soe draft` re-runs are idempotent: re-enqueueing a pending draft refreshes
  its content; a decided draft is never overwritten (no more IntegrityError).
- Approval decisions and their audit rows now commit in one transaction.
- Demo provider costs are documented as representative demo numbers, not
  vendor pricing.
- Pinned the published scoring table to the weights in a test; cleaned stale
  docstrings and test typing; SPDX license field; tag v1.1.0.

## [1.0.0] - 2026-11-13

### Added
- M5: case-study README - architecture, offline quickstart, labeled demo
  output, measured cost-per-email, published scoring formula, honest drafting
  design, limitations and roadmap.

## [0.5.0] - 2026-11-13

### Added
- M4: approval queue. Drafts land as pending in SQLite; a named reviewer
  approves or rejects (rejections require a reason, double decisions are
  refused), and every enqueue and decision hits the audit log.

## [0.4.0] - 2026-11-13

### Added
- M3: provider-agnostic drafting. The default, documented provider is offline
  and deterministic (template drafts built from real score reasons, labeled
  OFFLINE DEMO DRAFT); an Anthropic adapter keeps the same interface for when
  a key is available and fails honestly without one. `soe draft` runs the full
  chain: signals -> qualified fits -> enriched contacts -> drafts, audit-logged.

## [0.3.0] - 2026-11-13

### Added
- M2: enrichment waterfall with verification states (verified/risky/unknown),
  per-lookup cost tracking, labeled demo providers with realistic unit costs,
  and `soe enrich` end to end with cost-per-found-email reporting.

## [0.2.0] - 2026-11-13

### Added
- M1: connector protocol with a labeled demo JSON source (`data/demo_signals.json`),
  end-to-end scoring runs (`soe score`), ranked fit table with per-signal reasons,
  and audit logging of every run to SQLite.

## [0.1.0] - 2026-11-13

### Added
- M0 scaffold: package layout, CLI entry point (`soe`), module contracts for
  signals, ICP scoring, enrichment waterfall, drafting, store, and approval queue.
- Deterministic test suite (pytest), ruff + mypy (strict) linting, CI on
  Python 3.11 and 3.12.
- MIT license.
