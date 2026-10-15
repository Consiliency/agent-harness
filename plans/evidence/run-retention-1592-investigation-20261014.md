# Investigation: run-bundle and per-run cache growth (agent-harness#1592)

Frozen research input for `plans/phase-plan-v11-RUNRETAIN.md`. Line numbers were taken
from `origin/main` on 2026-10-14 and are pointers, not contracts. Paths are under
`phase-loop-runtime/src/phase_loop_runtime/` unless shown otherwise. Nothing was deleted
or pruned on any host while gathering this.

## What writes `.phase-loop/runs/<run>/`

- Path helpers: `runtime_paths.py` `phase_loop_runs_dir` (canonical) and
  `phase_loop_runs_dirs` (also reads legacy `.codex/phase-loop/runs`). `.phase-loop/` is
  added to `.git/info/exclude`, so run directories are never tracked.
- Launch runs: `observability.py` `run_artifacts()` creates `<UTC>-<NN>-<phase>-<action>/`
  with `launch.json`, `output.log`, `heartbeat.json`, `terminal-summary.json`,
  `task-snapshot.json`, hook files, `context.md` and `claude-bundle/`.
- Other runtime-written runs: hotfix verification (`observability.py`), legible
  transition/attest runs and implementation-panel records (`runner.py`, `panel_invoker.py`),
  train re-verify (`train_runner.py`), legible sidecars (`legible_evidence.py`),
  `verification.json`/`verification.log` (`verification_evidence.py`), a `codex-turn-*`
  temp dir inside the run (`launcher.py`).
- Likely bulky: `output.log`, `verification.log`, `legible-final.log`, junit XML,
  `context.md`, `claude-bundle/plugin`, review bundles, `implementation-panel-stream/`.
- Small decision records: `launch.json`, `heartbeat.json`, `terminal-summary.json`,
  verification/panel/ruling JSON, receipts.
- No worktrees or tarballs are written into run directories; lane worktrees are repo
  siblings (`runtime_paths.py` `lane_worktree_root`).
- On this host the main checkout holds one 32 KiB run. dev0 data was not inspected from here.

## Agent-written ("unmanaged") run directories

The 69/48/76 GB folders on dev0 are named by detailed-execute run ids
(`recur-expansion-proof`), not by the runtime's `<UTC>-<NN>-…` scheme. Neither the
runtime nor `skills-src/codex/codex-execute-detailed/SKILL.md` defines that layout: the
executing agent chose to write there. Consiliency/jev-assembler `plans/manifest.json`
cites dozens of such files (for example
`.phase-loop/runs/mock-settlement-preparation/f5-scope/scope-ruling.json`) and at least one
glob (`.phase-loop/runs/mock-settlement-final/**`).

## Per-run caches

- `recur-falsifiers-*`: Consiliency/jev-assembler `scripts/run-recur-falsifiers.mjs`
  calls `mkdtempSync(join(repoRoot, ".cache/recur-falsifiers-"))` and never removes it.
- `.phase-loop/jev-scratch`: Consiliency/jev-assembler `scripts/run-jev-falsifiers.mjs` and
  `scripts/jev-baml-compat.mjs`.
- Neither string occurs in this repository. The runtime creates no per-run `.cache/`; its
  scratch (`review_stage.py`, `launcher.py`, `sandbox_policy.py`) is mostly
  `TemporaryDirectory` or removed in `finally`; `panel_invoker.py` `_gc_stale_panel_scratch`
  sweeps crash residue at panel-leg start.

## "Settled"

No run-level state machine and no `settled` status exist. The per-run terminal record is
`terminal-summary.json` (`models.py`, writer in `observability.py`) with `terminal_status`
in complete, blocked, dry_run, unknown, executing. `plan_manifest.py` warns that a run's
terminal summary does not prove the phase finished. End-of-run points (`runner.py`
`run_loop` tail, `_perform_phase_closeout`, `train_runner.py` `_live_post_merge_prune`)
never touch `runs/`.

## Status output

`phase-loop status` (`cli.py`, `render.py` `render_status`) and `phase-loop state`
(`state_ops.py` `inspect_state`) print no run count or size. The only size accounting is
`sandbox_retention.py` `SandboxEntry.size_bytes` (review sandboxes).

## Existing retention code to reuse, not duplicate

- `sandbox_retention.py` / `sandbox_policy.py`: TTL, total-size ceiling, archive-before-reap,
  env settings. The model for RUNRETAIN's compaction policy.
- `state_ops.py` `archive_state`: moves state files, excludes `runs/`.
- Worktree pruning: `prune_merged_worktrees.sh`, `train_runner.py` post-merge prune.

## Tracked readers of run files (must keep resolving)

`plans/manifest.json` (legible-attest operational evidence and verification paths, one
absolute `/mnt/workspace/...` path), v10 phase plans (junit paths), skill docs;
validators `legible_evidence.py`, `cli.py` verification-artifact bound, `closeout.py`
`missing_verification_artifact`, `phase_loop_drift_audit.py`, `handoff.py` latest-run
pick, `phase-loop-runtime/scripts/verify_harden_evidence.py` `run_owned_receipt`.

## Ownership split

| Ask | agent-harness | Consiliency/jev-assembler | Consiliency/dotfiles |
|---|---|---|---|
| 1 compaction | runtime command and policy | none | none |
| 2 promotion | reference scanner, promote command, resolver, skill guidance | adopt: cite promoted paths | none |
| 3 caches | run-scoped scratch dir handed to agents, removed at run end | fix `run-recur-falsifiers.mjs` / jev-scratch scripts to use it or clean up in `finally`; one-off cleanup of existing dirs | none |
| 4 sizes | `status`/`state` footprint | none | dotfiles#107 guardrail report can call `phase-loop runs footprint --json` |

Consiliency/dotfiles#108 (worktree reaper) should consult `phase-loop runs refs --json`
before removing a worktree whose tracked files cite run artifacts.

## Overlap check

- agent-harness#627 (salvage worktrees/branches), agent-harness#1354 (worktree sweep
  liveness, `--dry-run`; EC-LOOPFIX-5), agent-harness#1462 (seat process end, session
  archive): all scope worktrees, branches or seat processes. RUNRETAIN touches only
  `.phase-loop/runs/` and the scratch it hands out, never worktrees or branches.
- Reuse the recency signal agent-harness#1354 settles on for "run is quiet", rather than a
  second liveness definition.
