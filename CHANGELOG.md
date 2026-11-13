# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
