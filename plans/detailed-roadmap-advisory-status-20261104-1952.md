# Detailed plan: advisory roadmap registry status

## Task

Implement the 2026-11-04 owner decision for agent-harness#1824: the registry is
the authority. This revision supersedes the earlier heuristic-classification
requirements. Commit locally on the assigned branch; do not push, comment,
dispatch CI or start subagents. Adoption of v12 and SEATS belongs to
agent-harness#1819 and agent-harness#1820; leave those roadmaps and the registry
unchanged.

## Contract

Advisory status requires an entry in specs/roadmap-status.json and this exact,
anchored line-3 banner, after an H1 and blank line, with a valid ISO date:

```markdown
> # ADVISORY — not runner-selected (2026-11-04)
```

Retain roadmap_status_manifest.v1, exact tracked coverage, one active record,
active-only selected_roadmap, and typed registry/banner mismatch refusals.
Registered advisory roadmaps are validated and included in evidence but never
selected or dispatched. Promotion requires a separate coherent owner decision.

Without a registry, refuse only the exact advisory banner on line 3. Other
advisory wording retains legacy behavior: no prose-based or repository-wide
refusals. Existing active/delivered/superseded behavior remains. Remove the shared
marker classifier's body scanning, fence tracking, Unicode normalization,
label-prefix and phrase detection. Ordinary ACTIVE documents with advisory prose
remain valid, including prose in unselected siblings.

validate-roadmap emits a simple non-blocking WARNING for advisory-looking text
outside the exact banner, including near misses and Status: advisory. Warnings
never affect selection or validation's exit status. This is an author hint, not
a complete Markdown classifier. Older runtimes reject unknown registry statuses
but may treat advisory roadmaps without a registry as legacy and run them.

Preserve anchored parsing, typed unreadable-file errors, relative refusal
messages (including broken symlinks outside the repo), and clean CLI exit 2.

## Changes

- phase-loop-runtime/src/phase_loop_runtime/roadmap_lint.py: remove heuristic
  classifier/conflict checking; use exact line-3 detection in the singleton
  fallback; add the non-blocking validator warning. Preserve registry coherence,
  vocabulary, evidence and anchored banner parser.
- phase-loop-runtime/src/phase_loop_runtime/discovery.py: remove shared heuristic
  use; retain existing-status declaration recognition without treating arbitrary
  Status prose as a lifecycle declaration; preserve lexical relative paths for
  unreadable symlinks.
- phase-loop-runtime/tests/test_advisory_roadmap_status.py: replace shape tables
  with focused exact-banner refusal, near-miss legacy/warning, ACTIVE/prose,
  registered advisory, mismatch, unreadable and dispatch controls. Retain evidence,
  source-route and old-reader checks that still apply.
- README.md and CHANGELOG.md: document registry authority, exact-only fallback,
  warnings and older-runtime limitations.
- This plan: record the owner decision and bounded verification.

No skills or generated bundles change. All dirty source paths above are
plan-owned. Private verification, mutation evidence, disposition and mandatory
reflection are execution artifacts outside tracked source.

## Verification

Owner shared-host restrictions override previous full-suite and dependency
refresh requirements. Check uptime and /proc/pressure/io before testing. If
degraded, stop and defer remaining checks to CI.

Use absolute source and tests PYTHONPATH. Run targeted files serially, each under
timeout 900 with -p no:cacheprovider and without xdist:
- tests/test_advisory_roadmap_status.py
- tests/test_roadmap_ownership.py
- tests/test_discovery_hygiene_legacy.py
- any roadmap_status, roadmap_lint or validate_roadmap tests, including
  tests/test_phase_loop_roadmap_validate.py.

Run timeout 120 phase-loop validate-roadmap --repo . --roadmap
specs/phase-plans-v11.md from source, and uv run ruff check . Mutation-check every
guard, one source file at a time, retaining baseline and per-mutation failures
and restoring bytes after each. No full suite, make check, make check-full,
-n auto or hosted dispatch is authorized. Record those as CI deferrals, not local
passes. Append the round-3 repair disposition with mode 0600.

Best-effort plan lifecycle updates may fail if this standalone plan has no
manifest entry; record that warning in the reflection.

## Acceptance criteria

- Advisory is accepted by v1, retained in coverage/evidence, and cannot be
  selected or dispatched; registry/banner mismatches refuse with typed errors.
- Without a registry the exact line-3 advisory banner refuses selection/dispatch;
  near misses otherwise behave as legacy and produce validator warnings.
- ACTIVE plus advisory prose and unselected siblings do not block selection.
- Anchored parsing, relative typed read errors and clean CLI exit 2 remain.
- README, CHANGELOG and this plan describe the same rule; adoption artifacts
  remain unchanged.
- Targeted checks and guard mutations have recorded results or explicit host/CI
  deferrals. Final report gives head, net lines, counts and deferrals.
