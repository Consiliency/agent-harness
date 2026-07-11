# PUSHFLOW — push-after-merge visibility (POST070FIX phase 2)

- **Closeout pushes by DEFAULT (CLI arg layer, IF-0-PUSHFLOW-1).** The
  `phase-loop run` / `resume` / `dry-run` default closeout mode flips from
  `manual` to `push` at the CLI arg layer (`cli.py` `_resolve_run_closeout_mode`),
  so phase-owned work lands on origin instead of accumulating 70–100 commits ahead
  locally. An explicit `--closeout-mode` always wins; the new `--no-push` flag
  restores the prior `manual` default. The push runs through the existing runner
  closeout path unchanged and degrades gracefully with no push remote (recorded as
  `push_refused`, never an error). No `runner.py` edit — the runner closeout push
  path is left to its single-writer owner.

- **`commits_ahead_of_origin` ahead-of-origin signal.** The worktree index now
  reports, per worktree, how many commits its branch is ahead of the base ref
  (`git rev-list --count <base>..<branch>`), mirroring the existing `main_behind`
  divergence signal. `phase-loop worktree-index` renders `[N ahead]` (and a WARN
  hint past `AHEAD_WARN_THRESHOLD`); the opt-in `--fail-on-ahead` flag soft-blocks
  (exit non-zero) when a worktree exceeds the threshold. `phase-loop doctor` gains
  a metadata-only `worktree_divergence` aggregate (max ahead + verdict). WARN by
  default; never human_required.

- **`phase-loop doctor` pinned-clone staleness check.** A new BOM entry compares
  the pinned agent clone (`~/.local/share/agent-harness`, via `AGENT_HARNESS_HOME`)
  against the checked-in `RELEASE_PIN`; a `stale` verdict flags a clone left behind
  the pin (the live gap where clones sat at 0.6.0 under `RELEASE_PIN=v0.7.0`). The
  check is local (works offline) and never gates — WARN only. Fix: re-run
  `install-agent-harness.sh` to re-pin the clone; the documented release step
  requires bumping `RELEASE_PIN` in lockstep with the release so clones re-pin
  (see `docs/releases/outside-agent-release-handoff.md`).
