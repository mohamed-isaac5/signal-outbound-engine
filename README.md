# signal-outbound-engine

> Signal-driven outbound: capture buying signals, score them against an ICP,
> enrich contacts through a waterfall, draft outreach, and send only what a
> human approves - every step audited.

**Status: private, under active construction.** Built in public milestones;
this README becomes the full case study at M5.

## Scoring

The ICP fit formula is published, not hidden:

| Signal | Points |
| --- | --- |
| Hiring (relevant role) | 30 |
| Funding round | 25 |
| Tech-stack change | 20 |
| Intent spike | 15 |
| Leadership change | 10 |

A combined fit of **50+** routes the account to drafting. Every draft keeps its
score breakdown (`reasons`) so any outbound message traces back to the exact
signals and points that produced it.

## Principles

- **Deterministic core.** Scoring, waterfall order, and approval rules are pure
  functions with tests; CI runs ruff, mypy (strict), and pytest on 3.11/3.12.
- **Honesty over coverage.** A field the providers cannot find stays `null`.
  The engine never invents data to fill a gap.
- **Human gate.** Nothing sends without an approval recorded against the draft.

## Roadmap

- [x] M0 - scaffold, contracts, tests, CI
- [ ] M1 - signal connectors + scoring runs
- [ ] M2 - enrichment waterfall (real providers)
- [ ] M3 - LLM drafting (Anthropic)
- [ ] M4 - approval queue + audit trail UI
- [ ] M5 - case-study README + public release

## License

MIT - see [LICENSE](LICENSE).
