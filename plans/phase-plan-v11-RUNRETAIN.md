---
phase_loop_plan_version: 1
phase: RUNRETAIN
roadmap: specs/phase-plans-v11.md
roadmap_sha256: be453ea57c7fe77c0f16f2af0e47158440cb2b0241fa65794292464556a8fa3c
---

# RUNRETAIN: Bounded Run Bundles and Per-Run Scratch

## Context

agent-harness#1592: phase-loop run bundles and per-run caches grow without bound (76–117 GB
per worktree on dev0). RUNRETAIN is a standalone issue phase. It is **not** a declared v11
phase and declares no `EC-` goal IDs; the roadmap frontmatter only binds the validator's
input. Its acceptance items are local `AC-N`.

Research, file pointers and the ownership split are frozen in
`plans/evidence/run-retention-1592-investigation-20261014.md`. Findings that shape this
plan:

- The runtime writes launch runs (`<UTC>-<NN>-<phase>-<action>/`) whose bulk is logs,
  bundles and panel streams. The multi-GB dev0 folders are **unmanaged**: detailed-execute
  agents chose the run-id directories themselves, with no `launch.json` or
  `terminal-summary.json`.
- No run-level "settled" state exists. Nothing reports run size. Nothing ever removes
  anything under `.phase-loop/runs/`.
- Tracked files cite run files by relative path, by glob (`…/<run>/**`) and by absolute
  `/mnt/workspace/...` path. Several validators read those files.
- `recur-falsifiers-*` and `.phase-loop/jev-scratch` are created by Consiliency/jev-assembler
  scripts, not this repository.

**Ownership.** Asks 1–4 are runtime work in this repository. These items belong to other
repositories and are follow-ups, not lanes here:

- Consiliency/jev-assembler: Consiliency/jev-assembler#37 makes the falsifier runners remove
  their mutant copies in `finally` and use the SL-1 scratch root when it is set (D-4). Still
  open there: a one-off cleanup of existing directories, and citing promoted paths.
- Consiliency/dotfiles#107: guardrail report can call `phase-loop runs footprint --json`.
- Consiliency/dotfiles#108: the reaper consults `phase-loop runs refs --json` before
  removing a worktree.

**Not in scope.** Worktree, branch and seat lifecycle stay with agent-harness#627,
agent-harness#1354 and agent-harness#1462. RUNRETAIN never removes a worktree or branch. Its
"quiet" test reuses the recency signal agent-harness#1354 adopts.

**Order: cheapest relief first.** SL-0 (visibility) and SL-1 (scratch cleanup) need no owner
decision and ship first. SL-2 (reference safety and promotion) must land before SL-3, the
only lane that deletes run content.

**Safety invariants (all lanes).**
- No path cited from a tracked file is removed unless a promoted copy with a matching
  sha256 already exists.
- Every destructive command is dry-run by default and needs `--apply`.
- Each applied action writes a receipt.
- No lane deletes anything automatically at run end except the scratch directory SL-1
  itself created.

### Decisions

The repository owner (Jenner Torrence) decided OQ-1 to OQ-5 on 2026-10-14. They are
binding on the lanes named.

- **D-1 (OQ-1 + OQ-4; SL-3): when a run may be compacted.** Only when it has a terminal
  `terminal-summary.json` and has had no writes for 7 days. Compaction is manual
  (`--apply`). Automatic compaction is a later config key, off by default, and is not part
  of this phase. Unmanaged (agent-made) run directories are report-only unless
  `--include-unmanaged` is passed. The 7-day quiet window and the SL-2 protected set still
  apply to them.
- **D-2 (OQ-2; SL-2): where promoted artifacts live.** Tracked in git under
  `evidence/phase-loop-runs/<run>/<relpath>`, capped at 256 KiB per file and 2 MiB per run.
  A cited file over either cap goes to an ignored sidecar archive
  (`PHASE_LOOP_RUN_ARCHIVE_DEST`), and a tracked index records its sha256 and location.
- **D-3 (OQ-3; SL-3): what compaction does to bulky files.** Logs and transcripts are
  gzipped. Regenerable bundles (`claude-bundle/plugin`, `implementation-panel-stream/`) are
  removed once their digests are recorded. Deleting a log that cannot be regenerated
  requires `--purge`.
- **D-4 (OQ-5; SL-1): the runtime does not sweep `.cache/` paths it did not create.** It
  cleans only the scratch root it hands out. The jev-assembler leak is fixed in that repo by
  Consiliency/jev-assembler#37 (open, not merged by this phase). There, the falsifier
  runners remove their mutant copies in `finally` and honour `PHASE_LOOP_RUN_SCRATCH`.
  Existing directories are removed by a one-off cleanup that the owner runs.

## Interface Freeze Gates

- [ ] IF-0-RUNRETAIN-1 — `phase-loop runs <footprint|refs|promote|compact> [--repo P] [--json]`
  is the single CLI group. `footprint` is read-only and reports, per run directory:
  `run_id`, `managed`, `terminal_status|null`, `bytes`, `files`, `newest_mtime`,
  `largest[≤3]`. It also reports totals for `.phase-loop/runs` and top-level sizes of other
  ignored roots (`.cache/`, other `.phase-loop/*`). It is bounded by a time and entry
  budget, and a result cut short by the budget is marked `partial: true`. Subcommands whose
  lane has not landed exit 2 with `not_available`.
- [ ] IF-0-RUNRETAIN-2 — `run_scratch.run_scratch_dir(run_root) -> Path` (`<run>/scratch/`)
  is exported to launched agents as `PHASE_LOOP_RUN_SCRATCH` and `TMPDIR`. It is removed
  when the run's terminal summary is written, unless `PHASE_LOOP_KEEP_RUN_SCRATCH=1`.
  It is the only path the runtime removes outside compaction (D-4).
- [ ] IF-0-RUNRETAIN-3 — `run_references.collect(repo) -> ProtectedSet` covers relative,
  glob and absolute citations of `.phase-loop/runs/` in tracked files. An unresolvable
  citation fails closed. `run_references.resolve_run_artifact(repo, cited) -> Path | None`
  tries the run directory, then the promoted location.

## Lane Index & Dependencies

SL-0 — Run footprint reporting and the runs CLI group
  Depends on: (none)
  Blocks: SL-3, SL-4
  Parallel-safe: yes
SL-1 — Run-scoped scratch root removed at run end
  Depends on: (none)
  Blocks: SL-4
  Parallel-safe: yes
SL-2 — Cited-artifact protection, promotion and resolver
  Depends on: SL-0
  Blocks: SL-3, SL-4
  Parallel-safe: yes
SL-3 — Dry-run-first compaction of settled runs
  Depends on: SL-0, SL-2
  Blocks: SL-4
  Parallel-safe: no
SL-4 — Operator docs, skill guidance and phase verification reducer
  Depends on: SL-0, SL-1, SL-2, SL-3
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Run Footprint Reporting And The Runs CLI Group

- **Scope**: Ask 4. Make large runs visible in `status`, `state` and `runs footprint` without mutating anything.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/run_footprint.py`, `phase-loop-runtime/src/phase_loop_runtime/runs_cli.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/render.py`, `phase-loop-runtime/src/phase_loop_runtime/state_ops.py`, `phase-loop-runtime/tests/test_run_footprint.py`
- **Interfaces provided**: IF-0-RUNRETAIN-1
- **Interfaces consumed**: `phase_loop_runs_dirs` (pre-existing), `terminal-summary.json` schema (pre-existing)
- **Parallel-safe**: yes; owns the CLI surface and read-only scanner only.
- **Tasks**:
  - test: Fixture repo with managed, unmanaged and legacy-path runs. Assert per-run bytes and file counts, managed classification, top-3 largest files and `.cache/` totals. The scan budget yields `partial: true`. A symlink loop or a symlink out of the repo is neither followed nor counted twice. The tree is byte-identical after the scan.
  - test: `status` and `state` text show the runs total and the top 5 runs by size, and `--json` carries the full footprint. An unimplemented subcommand exits 2 with `not_available`.
  - impl: Walk with `os.scandir` and `lstat`, no hashing, under a configurable time and entry budget. Status uses a tighter budget than `runs footprint`.
  - verify: `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_footprint.py -q`

### SL-1 — Run-Scoped Scratch Root Removed At Run End

- **Scope**: Ask 3, runtime side. Hand every launched agent a run-owned scratch directory and remove it when the run ends.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/run_scratch.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/observability.py`, `phase-loop-runtime/tests/test_run_scratch.py`
- **Interfaces provided**: IF-0-RUNRETAIN-2
- **Interfaces consumed**: `run_artifacts` (pre-existing), terminal-summary writer (pre-existing)
- **Parallel-safe**: yes; disjoint from SL-0 files.
- **Tasks**:
  - test: The launched agent environment carries `PHASE_LOOP_RUN_SCRATCH` and `TMPDIR` inside the run directory.
  - test: The scratch directory is gone after a complete, blocked or crashed-then-finalized run. It is kept when `PHASE_LOOP_KEEP_RUN_SCRATCH=1`.
  - test: Paths outside `<run>/scratch/`, including symlink targets, are never removed.
  - impl: Create the scratch root in `run_artifacts`. Export it in the launcher. Remove it with a symlink-safe tree delete next to the terminal-summary write, and record `scratch_bytes_removed` in the summary.
  - verify: `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_scratch.py -q`

### SL-2 — Cited-Artifact Protection, Promotion And Resolver

- **Scope**: Ask 2 (`runs refs`, `runs promote`). Know every run file that tracked files cite, copy the cited files to the D-2 location, and keep existing readers resolving.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/run_references.py`, `phase-loop-runtime/src/phase_loop_runtime/closeout.py`, `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py`, `phase-loop-runtime/scripts/verify_harden_evidence.py`, `phase-loop-runtime/tests/test_run_references.py`, `phase-loop-runtime/tests/test_legible_evidence.py`
- **Interfaces provided**: IF-0-RUNRETAIN-3
- **Interfaces consumed**: IF-0-RUNRETAIN-1
- **Parallel-safe**: yes; disjoint files.
- **Tasks**:
  - test: Citations in `.json`, `.md` and `.yaml` tracked files are collected: relative, `**` glob and absolute paths into this or a sibling worktree. Untracked files are ignored. A citation that cannot be resolved makes `collect` fail closed.
  - test: `promote` is dry-run by default. With `--apply` it copies each cited file to `evidence/phase-loop-runs/<run>/<relpath>`, verifies sha256 and writes the tracked promotion index. Re-running it is idempotent.
  - test: A file over 256 KiB, or one that would take its run past 2 MiB, goes to `PHASE_LOOP_RUN_ARCHIVE_DEST` instead. Its index entry records the sha256 and the sidecar location. Without a destination it is refused.
  - test: After the run directory is removed, `closeout`, `legible_evidence` and `verify_harden_evidence` resolve a promoted artifact. A missing artifact still fails as before.
  - impl: Scan with `git ls-files` and the existing glob semantics; route the three readers through `resolve_run_artifact`.
  - verify: `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_references.py -q`

### SL-3 — Dry-Run-First Compaction Of Settled Runs

- **Scope**: Ask 1 (`runs compact`). Compact bulky artifacts of settled runs and keep small decision and ruling records.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/run_compaction.py`, `phase-loop-runtime/tests/test_run_compaction.py`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-RUNRETAIN-1, IF-0-RUNRETAIN-3
- **Parallel-safe**: no; it is the only destructive lane.
- **Tasks**:
  - test: A managed run is settled only if its `terminal-summary.json` has a terminal `terminal_status` (complete, blocked or dry_run), nothing in it was written in the last 7 days, and it has no live heartbeat. An executing, unknown or recently written run is never touched.
  - test: Unmanaged runs are reported but untouched without `--include-unmanaged`. With it, the 7-day window and the protected set still apply.
  - test: Logs and transcripts are gzipped. A regenerable bundle is removed only after its digest is in the receipt. A log that cannot be regenerated is deleted only with `--purge`.
  - test: A protected path is untouched unless a sha-matched promoted copy exists. A `**` citation protects its whole subtree.
  - test: JSON decision and ruling records under the size threshold are always kept.
  - test: Dry-run is the default and leaves the tree byte-identical. `--apply` writes `compaction-receipt.json` with each path's action, bytes before and after, and the reason. A second `--apply` is a no-op.
  - impl: Model the policy on `sandbox_retention.py` (window, size ceiling, archive-before-remove) instead of adding a new pattern. Apply the D-3 per-class actions. No automatic trigger in this phase (D-1).
  - verify: `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_compaction.py -q`

### SL-4 — Operator Docs, Skill Guidance And Phase Verification Reducer

- **Scope**: Document the contract and tell detailed-execute agents to use the scratch root and to cite promoted paths, not bulky run folders.
- **Owned files**: `docs/phase-loop/run-retention.md`, `skills-src/*/*-execute-detailed/SKILL.md`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-execute-detailed/SKILL.md`, `CHANGELOG.md`
- **Interfaces provided**: (none)
- **Interfaces consumed**: IF-0-RUNRETAIN-1, IF-0-RUNRETAIN-2, IF-0-RUNRETAIN-3
- **Parallel-safe**: no; reducer.
- **Tasks**:
  - impl: Write the operator doc covering the commands, the safety invariants, decisions D-1 to D-4 and the cross-repo follow-ups. Add the skill guidance and regenerate the bundled copies with the repo's skill sync.
  - impl: Do not repair other lanes' files; route failures to the owning lane.
  - verify: `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_footprint.py tests/test_run_scratch.py tests/test_run_references.py tests/test_run_compaction.py tests/test_sandbox_retention.py -q`

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`medium`, unsupported=`inherit_default`, inherit-default=`true`
- SL-3: executor=`codex`, effort=`high`, work-unit=`lane_execute`, unsupported=`inherit_default`, inherit-default=`true`, reason=`only destructive lane`

## Execution Notes

- Each lane may land as its own PR in lane order. SL-0 and SL-1 deliver the disk relief that needs no decision.
- While validating, never delete or prune a real run folder or worktree on a shared host. Destructive tests run only on `tmp_path` fixtures.
- Consiliency/jev-assembler#37 is reviewed and merged in that repository. It does not gate any lane here.
- Filing Consiliency/dotfiles follow-ups is an outward action for the owner to approve. This phase does not file them.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/run_*.py`, `phase-loop-runtime/src/phase_loop_runtime/runs_cli.py`, `docs/phase-loop/run-retention.md`
- evidence paths: `plans/phase-plan-v11-RUNRETAIN.md`, `plans/evidence/run-retention-1592-investigation-20261014.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

```bash
python skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v11-RUNRETAIN.md
cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_footprint.py tests/test_run_scratch.py tests/test_run_references.py tests/test_run_compaction.py tests/test_sandbox_retention.py -q
```

automation:
  suite_command: cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_footprint.py tests/test_run_scratch.py tests/test_run_references.py tests/test_run_compaction.py tests/test_sandbox_retention.py -q

## Acceptance Criteria

- [ ] AC-1 — proven by `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_footprint.py -q`; falsified by a footprint that mutates the tree, follows a symlink out of the repo, omits an unmanaged run, or reports a budget-cut scan without `partial: true`.
- [ ] AC-2 — proven by `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_scratch.py -q`; falsified by a finished run whose scratch root survives without the keep flag, or a removal that reaches outside `<run>/scratch/`.
- [ ] AC-3 — proven by `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_references.py -q`; falsified by a tracked glob or absolute citation missing from the protected set, an unresolvable citation that passes, an over-cap file tracked in git, or a reader that fails on a promoted artifact.
- [ ] AC-4 — proven by `cd phase-loop-runtime && PYTHONPATH=src python -m pytest tests/test_run_compaction.py -q`; falsified by compaction that changes bytes without `--apply`, touches an executing, unknown or under-7-day run or an unmanaged run without `--include-unmanaged`, removes a protected path without a sha-matched promoted copy, deletes a non-regenerable log without `--purge`, or drops a small decision record.
