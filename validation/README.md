# Offline checks, October 7, 2026

These checks cover the single-item implementation. The later six-item checks
and expanded 43-test suite are documented in
[multi-item/README.md](multi-item/README.md). Both used scripted policies and
mocked HTTP responses, with no model calls or API spend.

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 30 tests passed |
| Full compliant scripted run | 96/96 episodes; no rule violations; all tasks safely completed |
| Full unsafe scripted run | 96/96 episodes; unauthorized purchases detected in all 16 primary cases per condition |
| Budget guard in the unsafe run | All four over-budget attempts blocked in each guarded condition; all four executed in the unguarded condition |
| Missing-key preflight and live-run command | Exited before any API request; no live run directory created |

The tests cover matched controls, balanced cases, exact approval state, budget boundaries, attempted versus executed violations, invalid and incomplete outputs, refusals and utility, simultaneous tool calls, HTTP request structure, usage accounting, reservation persistence, interruption/resume, and missing-outcome analysis. HTTP tests use a mock transport.

- [Compliant scripted summary](offline-compliant.md) and [machine-readable summary](offline-compliant.json).
- [Unsafe scripted summary](offline-unsafe.md) and [machine-readable summary](offline-unsafe.json).
- [CLI command checks](command_checks.json).
- [Frozen development cases](design/cases.json), [all prompts](design/prompts.jsonl), and [plan](design/plan.json).

Both scripted policies ignore the announcement, so neither should produce an
announcement effect. The unsafe script attempts one purchase regardless of
approval and stops if the guard blocks it.

Use the `smoke` commands in the main README to reproduce full tool traces.
Generated run directories are ignored by Git and omitted from this archive.
These offline checks preceded the model runs now summarized in the
[main results](../README.md#results).
