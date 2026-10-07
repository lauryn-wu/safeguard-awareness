# Offline validation — 2026-10-07

**No live language-model calls were made. Model spend: $0.**

The software checks and scripted runs below validate the implementation. They are not empirical results about model behavior or evidence for the research hypothesis.

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

The two scripts have no announcement-dependent policy. Their zero treatment contrasts are intentional software checks, not a model finding. The unsafe script attempts one purchase regardless of approval and stops if the guard blocks it.

To reproduce full tool traces, use the `smoke` commands in the main README. Generated run directories are ignored by Git and omitted from the archive. The live HTTP integration still needs validation with a configured API key and network access before collecting model evidence.
