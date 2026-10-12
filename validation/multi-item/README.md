# Six-item offline checks, October 7, 2026

All 43 offline tests passed. These checks used scripted policies and mocked HTTP
responses, with no model calls.

The compliant policy completed all required actions safely in 96/96 episodes.
Each primary condition had 64 approved purchases and 96 safely handled item
outcomes across 16 episodes.

The unsafe policy attempted every item once without requesting approval. Each
primary condition had a violation in 16/16 episodes: all 64 initially unapproved
items were bought without permission. It also attempted an over-budget purchase
in all four budget-control episodes per condition. The validator blocked these
purchases whenever it was enabled. Both policies ignore the announcement, so
they should produce no announcement effect.

The CLI exported all cases and prompts, ran both scripted schedules, and
rejected a live run with no API key before creating its output directory. The
generated single-item plan still matched the frozen v1 plan, including cases,
prompt hashes, tools, configuration, and schedule.

- [Compliant scripted summary](offline-compliant.md), [JSON](offline-compliant.json)
- [Unsafe scripted summary](offline-unsafe.md), [JSON](offline-unsafe.json)
- [CLI checks](command_checks.json)
- [Cases](design/cases.json), [prompts](design/prompts.jsonl), [plan and manifest](design/plan.json)

Tests cover independent item permissions, sticky denials, late approval, duplicate rejection, cumulative spending boundaries, matched prompts, concealed future replies, continued execution after a purchase, invalid tails preserving observed violations, full-run item aggregates and resumption without replay. API and cost-accounting tests use mocked HTTP responses.
