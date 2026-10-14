# Reflection filter repair: agent-harness#1370 and agent-harness#1371

Measured 2026-10-14, stacked on agent-harness#1588. The repair retains actionable
recurrence, limits exact/near deduplication to the same recorded skill/repo/branch/run,
and drops repo-specific proposal sections without discarding usable friction.
Unknown legacy source identity is insufficient to deduplicate separate files.

## Regression evidence

Six new cases fail before the implementation: three distinct runs with identical
feedback on one branch; a repeated actionable proposal across branches of one repo;
friction surviving an issue, path or URL in Improvements; and an Improvements-only
reflection remaining structured and becoming empty after that section is dropped.
Same-run copy deduplication, cap behavior, credential redaction, inert bundle structure
and archive containment continue to pass. Archive fixtures now distinguish a dropped
proposal section from an excluded reflection.

Relevant suites: **170 passed, 1 existing skip** (reflection corpus, maintenance,
canonical parity, bundle drift, pinned bundle, registry and seat-reference inventory).

## Frozen-input comparison

Collected once, reconstructed unfiltered sections from that scan's retained raw text,
then ran both filters on independent deep copies. No reflection was written or archived;
only aggregate counts are recorded here.

| Measure | Before | After |
|---|---:|---:|
| Scanned | 542 | 542 |
| Admitted | 358 | 401 |
| Consumable by the existing manifest rule | 399 | 400 |
| Duplicate exclusions | 10 | 0 |
| Whole-reflection repo-specific exclusions | 12 | 0 |
| No-friction/proposal exclusions | 32 | 0 |
| Per-branch cap exclusions | 130 | 141 |
| Boilerplate lines | 23 | 1 |
| Repo-specific proposal sections dropped | 0 | 51 |

The same five skills are ready in both arms: execute-detailed, execute-phase,
phase-roadmap-builder, plan-detailed and plan-phase. The per-branch cap is unchanged.
Distinct runs previously mistaken for copies and recurring lines previously stripped
now remain evidence. This snapshot contains no same-run duplicate copies.

More admitted feedback does not establish better recommendations. Rerun and read the
aggregator after the stacked repairs land, before applying or archiving the backlog.
Behavioral evaluation remains REPORT 2.1; actual skill-read evidence remains
agent-harness#1586.
