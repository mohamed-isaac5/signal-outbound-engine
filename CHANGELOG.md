# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-11-13

### Added
- ICP as a business config file (`icp.toml`): `soe icp setup` asks guided
  questions and writes it, `soe icp show` displays what scoring uses, and
  `soe icp edit` changes one field. A shipped `data/icp.example.toml`
  (mid-market B2B SaaS) keeps a cold clone runnable, with a printed note.
- Scoring uses the ICP two published ways: companies outside it are excluded
  with the stated reason (industry, size, country) and cannot route to
  drafting; companies inside it earn closeness points (+10 industry, +5 size,
  +5 country) itemized in the score breakdown. Optional per-ICP signal-weight
  overrides. Unknown attributes never exclude and never boost.
- Persona filtering: contacts whose title doesn't match the ICP target roles
  are skipped with the stated reason (token-subset matching; unknown titles
  pass).
- `--icp PATH` flag on run/guide/score/draft/demo; company metadata fixture
  `data/demo_companies.json`; the score table shows `excluded` routes and a
  summary line naming each excluded company and why. ADR-0006.
- Conditional `tomli` dependency for Python < 3.11 (stdlib tomllib on 3.11+).

## [1.3.0] - 2026-11-13

### Added
- `soe run`: the whole pipeline in one zero-flag command, narrated in plain
  language (scoring, enrichment, drafting), ending with the exact next step.
  Generates the demo data itself when it is missing.
- `soe guide`: an interactive walkthrough of the same flow - explains each
  step before running it, pauses for Enter, walks the review draft by draft,
  exports, and closes with a summary naming the file and how to upload it to
  Smartlead/Instantly. `--yes` runs it without pauses (approves every draft).
- Interactive `soe approve` (no flags): read each pending email and answer
  y/n/skip; rejections ask for a reason in a loop (the audit log keeps it).
  Without a terminal it exits 2 pointing at the flag form.
- `soe` with no command prints a welcome screen (what this is, where to
  start) instead of raw argparse help.
- Zero-flag defaults on every command (demo data in `data/`, `run.db`,
  `approved.csv`), so the happy path never needs a flag; flags still override.
- Next-step hints after every command, and examples in every `--help`.
- Friendly "missing demo data" error (rc 2) naming the fix: `soe run`.

### Fixed
- Re-running `soe guide` after a successful one no longer ends with the
  misleading "no approved drafts" summary; it reports the already-exported
  file instead (detected via the queue, not the CSV's mere existence - a
  header-only export would have fooled that).

## [1.2.0] - 2026-11-13

### Added
- `soe export`: approved drafts - and only approved drafts - export to a
  Smartlead/Instantly-shaped CSV (email, first/last name, company, subject,
  body). Each export marks its drafts (`--all` re-exports) and is
  audit-logged. The queue schema gains `recipient_name` and `exported_at`
  with guarded migrations for existing databases.
- `soe demo`: one command runs the whole chain offline and narrates each
  stage - scoring, enrichment, drafting, and the human gate.
- `soe audit`: query the audit trail; `--id` traces one draft from creation
  to decision with its score, provider, reviewer and reason.
- ARCHITECTURE.md: module map and ADRs (offline-first, human gate, SQLite,
  protocols over frameworks, published scoring formula).

## [1.1.3] - 2026-11-13

### Added
- Test-suite audit (QA round): branch coverage measured at 99% (was 93%) -
  the only uncovered lines are the `__main__` guards. Mutation testing: 17
  deliberate code breaks, all caught by the suite.
- Tests pinning the published threshold VALUE (50), case-strict `Subject:`
  parsing, the freshness window's inclusive boundary and age-~0 freshness
  (frozen clock), enrich audit logging, zero-found cost label, approve
  list/empty/missing-args paths, no-command help, fixture generator `main()`,
  and both Anthropic `_make_client` paths.

### Fixed
- `demo_fixtures.write_all` resolves its default output directory at call
  time instead of binding it at import (the constant is now patchable).
- Removed unreachable milestone-era fallback line in the CLI.

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
