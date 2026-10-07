# Multi-item offline validation — 2026-10-07

**43 offline tests passed. No live model requests were made for this follow-up.**

The compliant scripted policy completed 96/96 episodes with full useful safe completion and no violations. Each primary condition had 64 approved purchases and 96 safely handled item outcomes across 16 episodes.

The unsafe policy attempted every item once without requesting approval. Each primary condition had 16/16 episodes with a violation and 64/64 initially unapproved items purchased without permission. All four over-budget diagnostic episodes had an attempted budget violation in each condition; only the unguarded condition executed violations. Both scripts ignore the announcement; their zero announcement contrasts are software validation only.

The CLI exported all cases and prompts, ran both complete scripted schedules, and rejected a missing-key live run before creating its output directory. The original single-item generated plan, including cases, prompts' hashes, tools, configuration and schedule, exactly matches the frozen v1 plan.

- [Compliant scripted summary](offline-compliant.md), [JSON](offline-compliant.json)
- [Unsafe scripted summary](offline-unsafe.md), [JSON](offline-unsafe.json)
- [CLI checks](command_checks.json)
- [Cases](design/cases.json), [prompts](design/prompts.jsonl), [plan and manifest](design/plan.json)

Tests cover independent item permissions, sticky denials, late approval, duplicate rejection, cumulative spending boundaries, matched prompts, concealed future replies, continued execution after a purchase, invalid tails preserving observed violations, full-run item aggregates and resumption without replay. API and cost-accounting tests use mocked HTTP responses.
