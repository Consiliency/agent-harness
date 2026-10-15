# claude-execute-phase — setup and Steps 0–2a

Reference for `claude-execute-phase` (linked from its `SKILL.md`). Read it at the start of an interactive run, before Step 3.

## Contents

- Environment variables
- Expected helpers
- Deferred tool preloading
- Teamwork posture (hard rules)
- Step 0 — Read predecessor handoff (if present)
- Step 1 — Resolve + parse plan doc
- Step 2 — Preflight
- Step 2.5 — Baseline-capture
- Step 2a — Worktree hygiene preflight

## Environment variables

Plan-location variables are inherited from `claude-plan-phase` so the two skills resolve the same defaults:

| Variable | Default | Meaning |
|---|---|---|
| `PLAN_SPEC` | Auto-detected highest `specs/phase-plans-v*.md` | Path to spec file (used only for version extraction here). |
| `PLAN_VERSION` | Extracted `v\d+` from spec filename | Version token embedded in plan-doc filename. |
| `PLAN_PHASE_ALIASES` | Built-in alias table | Path to alias-map JSON. |
| `PLAN_DOC` | `plans/phase-plan-<VERSION>-<PHASE_ALIAS>.md` | Override the resolved plan-doc path directly. |
| `EXECUTE_MERGE_TARGET` | Current branch at invocation | Branch lanes merge into. |
| `EXECUTE_WORKTREE_ROOT` | `.worktrees/` (inside repo; auto-gitignored) | Root dir for per-lane worktrees. |
| `EXECUTE_MAX_PARALLEL_LANES` | `4` | Max concurrent lane dispatches per wave; parallelism-maximizing default. Lower to `2` when stale-base churn becomes problematic on phases with many interdependent lanes. |

## Expected helpers

Helpers under `resolve_skill_bundle_root("claude")/_shared/` may be absent on some hosts. Each helper degrades as listed:

- `_shared/next_reflection_path.py` — legacy helper only; current closeout writes reflections to `resolve_skill_bundle_root("codex")/claude-execute-phase/reflections/<repo_hash>/<branch_slug>/<run_id>.md`.
- `_shared/review_with_cli.py` — used only with `--review-external`; no fallback (required for that flag).

## Deferred tool preloading

Several tools this skill uses are deferred and must be registered via `ToolSearch` before first call. Load them in a single query at the top of Step 1 so mid-workflow calls (especially `TaskUpdate` on every dispatch and `AskUserQuestion` on preflight failures) don't pay a round-trip:

```
ToolSearch(query: "select:TaskCreate,TaskUpdate,TaskList,TeamCreate,AskUserQuestion")
```


## Teamwork posture (hard rules)

- **Main thread = dispatcher.** Read plan doc + TaskList + git state. Do not Grep/Read source code during execution, except for the Step 7 destructiveness check and file-touch audit.
- **Parallel-by-default.** Ready lanes dispatch in a single message, every round.
- **Name every teammate via the allocator.** Bare `lane-<sl-id>` names collide in rapid dispatch.
- **TaskCreate tasks are the source of truth for lane status.** Update them as lanes transition.
- **No speculative refactoring.** Lane teammates must stay within their `Owned files` globs; reject their work at gate verification if they wandered. Use the file-touch audit to catch this pre-merge.
- **Never trust a branch name.** Resolve work by `commit_sha` from the reply envelope.
- **Never `--no-ff` merge without the destructiveness check.**
- **Never resume a STOPped teammate with no commits.** Kill + respawn.
- **Never override the dirty-tree preflight.** `verify_harness.sh` is the gate. Only paths forward: (a) commit as `chore:`, (b) `git stash push -u` and restore post-phase, (c) abort.
- **Never rely on implicit shell CWD.** Every orchestrator git/script invocation MUST either wrap as `bash -c 'cd "$(git rev-parse --show-toplevel)" && <cmd>'` or pass `git -C <repo-root>`. `git worktree remove` on the shell's current CWD bricks subsequent Bash calls.

## Step 0 — Read predecessor handoff (if present)

Handoffs are keyed on the current repo so each workspace has its own slot. Resolve the predecessor path first:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
  REPO_KEY="_no-git-$(pwd | sha1sum | cut -c1-12)"
else
  REPO_KEY="$(basename "$REPO_ROOT")-$(printf '%s' "$REPO_ROOT" | sha1sum | cut -c1-12)"
fi
PREDECESSOR_HANDOFF="$(python3 - <<'PYH'
from pathlib import Path
repo = Path.cwd().resolve()
skill = "claude-plan-phase"
try:
    # Primary: the installed phase_loop_runtime.skill_paths resolver.
    from phase_loop_runtime.skill_paths import resolve_handoff_root
    print(resolve_handoff_root(repo) / skill / "latest.md")
except Exception:
    # Fallback: the repo-local handoff_path.py mirror, only when the runtime is not importable.
    from importlib import util
    spec = util.spec_from_file_location("handoff_path", repo / "shared" / "phase-loop" / "handoff_path.py")
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    print(mod.resolve_handoff_path(repo, skill))
PYH
)"
```

If `$PREDECESSOR_HANDOFF` exists, `Read` it in full — `claude-plan-phase` just produced the lane plan and may have flagged gotchas the dispatch loop needs to know about.

Defense-in-depth checks (the repo-key scheme prevents the common cross-project case, but these still catch symlink-shared workspaces, manual file copies, and stale handoffs):

- `from:` must be `claude-plan-phase`.
- Timestamp must be <7 days.
- Every `artifact:` path must resolve under `$(git rev-parse --show-toplevel)`.

On any failure, flag via `AskUserQuestion` with `[use anyway, ignore, abort]`.

Fold the handoff's "Open items" and "Repo-specific gotchas" into each lane teammate's brief (Step 5's Teammate brief contents) so they carry the same context without the user having to reinject it.

If absent, proceed standalone — the plan doc is authoritative either way.

## Step 1 — Resolve + parse plan doc

Resolve in order: `$PLAN_DOC` → `<plan-path>` arg → default path built from `$PLAN_VERSION` + phase alias argument.

`Read` the plan doc. Parse these sections (headings are stable IDs from `claude-plan-phase`):

- `## Interface Freeze Gates` — list of `IF-0-<PHASE>-<N>` items with descriptions.
- `## Cross-Repo Gates` (optional) — `IF-XR-<N>`.
- `## Lane Index & Dependencies` — machine-readable DAG block (`SL-N`, `Depends on:`, `Blocks:`, `Parallel-safe:`).
- `## Lanes` — per-lane: `Scope`, `Owned files`, `Interfaces provided`, `Interfaces consumed`, task table.
- `## Verification` — final end-to-end commands.

Build the lane graph. Topologically sort it; reject on cycle with a clear error.

## Step 2 — Preflight

- **Run `scripts/verify_harness.sh <merge-target>`.** Enforces the hard gates: git + git-worktree available, inside a work tree, merge-target branch exists locally, working tree clean (allowlist: `.claude/worktrees/`, `.claude/claude-execute-phase-state.json`), `.gitignore` covers worktree paths. **Non-zero exit blocks dispatch.** On dirty-tree failure, invoke `AskUserQuestion` with `[commit the changes as a chore, stash for the duration of the phase, abort /claude-execute-phase]` and take the user's answer. No override.
- Record merge target = current branch (or `$EXECUTE_MERGE_TARGET`).
- Apply the merge-target safety gate in `SKILL.md` (Step 2) before any lane dispatch or merge.
- Sanity check: every symbol appearing in any lane's `Interfaces consumed` must either be produced by an upstream lane's `Interfaces provided` OR be pre-existing (skip unknown symbols with a warning, don't hard-fail).
- Producer-dependency check: if a lane consumes another lane's findings, interfaces, or artifacts, that producer lane must appear in `Depends on`. If a lane writes a synthesized artifact, it must be downstream of every producer lane it summarizes. Missing dependencies block execution until the plan is corrected.
- If `--dry-run`: print the topological schedule with per-lane model/thinking assignments (see Step 3) and stop here.

## Step 2.5 — Baseline-capture

Run the plan's full regression command once at phase start against the pre-phase tip. Cache the failing-test list to `.claude/claude-execute-phase-state.json#baseline_fails`. Step 9 diffs against this cached list rather than reconstructing it.

Before hypothesizing test pollution on a post-merge failure, run the failing test in isolation (fresh process) to distinguish a direct regression from fixture pollution.

## Step 2a — Worktree hygiene preflight

Prune stale worktrees in `.claude/worktrees/` at phase start. Skip on `--resume`.

```bash
bash "$(git rev-parse --show-toplevel)/.claude/skills/claude-execute-phase/scripts/sweep_stale_worktrees.sh"
# Pass --dry-run to preview decisions without removing anything.
```

For each worktree marked `PRUNE`:

1. `git worktree unlock <path>` (succeeds silently if unlocked).
2. `git worktree remove -f -f <path>` — double-force bypasses both the lock and the unmerged-changes check (safe since the ancestor check already confirmed incorporation).
3. `git branch -D <branch>` **only** if the branch name matches an auto-named pattern (`worktree-*`, `phase/*/sl-*`). Leave human-named branches (`skills/*`, `feature/*`, `fix/*`) intact even when their work is on the merge target — the user may still want the reference.

Worktrees marked `KEEP` are left alone; log a one-line warning per worktree.
