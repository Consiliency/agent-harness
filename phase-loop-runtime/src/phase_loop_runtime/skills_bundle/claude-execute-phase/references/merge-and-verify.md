# claude-execute-phase — gates, merge and final verification (Steps 6–9)

Reference for `claude-execute-phase` (linked from its `SKILL.md`). Read it when a lane reports done and through final verification. Read "Browser verification" earlier, at plan intake in both modes, when any test needs a browser.

## Contents

- Step 6 — Gate verification
- Step 6.5 — Parent-tree leakage check
- Step 7 — Auto-merge
- Step 8 — Retry-once, then halt
- Step 9 — Final verification, cleanup, and summary
- Worktree lifecycle — prune after merge (standing rule)
- Output contract
- Worktree layout
- Browser verification

## Step 6 — Gate verification

For each gate the lane provides:

1. If the plan doc's `## Verification` section has a command that names this gate's artifact (e.g., `psql` for schema gates, `grep` for symbol gates), run it against the lane's worktree.
2. Else fall back:
   - Files listed under `Owned files` exist.
   - Symbols listed under `Interfaces provided` are grep-visible at expected paths.
   - Lane's own verify command exited 0.

Any failure here counts as a lane failure and triggers retry-once.

## Step 6.5 — Parent-tree leakage check

Detects two isolation failure modes before merge: (a) teammate writes landing in the parent checkout, (b) `EnterWorktree` falling back to in-place branch creation on the parent.

Run:
```bash
bash scripts/parent_tree_leakage_check.sh <lane-id> <owned-globs-file> <merge-target>
```

Verdicts (emitted on stdout; details on stderr):

- **`CLEAN`** — proceed to Step 7.
- **`LEAKAGE_DETECTED`** (dirty files overlap the lane's owned globs):
  1. Verify byte-equality: for each leaked path, `git diff <lane-sha> -- <path>` must be zero lines (confirms the leak is a redundant copy of committed lane work). If non-zero, treat as independent uncommitted work and STOP.
  2. Clean the parent: `git checkout -- <modified>` for tracked changes; `rm <untracked>` for new files. Do NOT `git stash`.
  3. Record in `.claude/claude-execute-phase-state.json` under the lane's `notes`.
  4. Proceed to Step 7.
- **`UNRELATED_DIRTY_TREE`** (dirty files outside the lane's globs) → STOP. Ask via `AskUserQuestion` whether to stash, commit, or abort.
- **`PARENT_ON_WRONG_BRANCH`** (tree clean but parent on a non-merge-target branch — `EnterWorktree` fell back to in-place branch creation):
  1. Merge by SHA per Step 7.
  2. Run `git checkout <merge-target>` in the parent BEFORE Step 7's worktree cleanup — otherwise `git worktree remove` refuses.
  3. Record parent-fallback note in state.
- **`PARENT_ON_MERGE_TARGET`** (alias `LANE_BYPASSED_ISOLATION`) — resolve the reply envelope's `commit_sha`; if `git merge-base --is-ancestor <sha> <merge-target>` is already true before any merge step, the commit landed directly on the target via an `EnterWorktree` fallback:
  1. Skip the merge (already merged).
  2. Clean up the worktree and branch per Step 7's post-merge cleanup.
  3. Record the fallback in `.claude/claude-execute-phase-state.json` and note it in the close-out.

## Step 7 — Auto-merge

**Branch discovery.** Resolve the lane's branch/worktree from the reply envelope's `commit_sha` via `git log --oneline -1 <commit_sha>` + `git worktree list`. Never trust the briefed branch name.

**Cross-lane file-touch audit.** Before the destructiveness check, run:

```bash
python scripts/audit_lane_file_touches.py <lane-sha> <plan-doc-path> <this-lane-id>
```

**Parser contract.** After matching the `**Owned files**:` heading, the parser walks subsequent deeper-indented bullets until the next sibling bullet or blank line and accumulates backticked tokens. Both inline form (`- **Owned files**: \`path/one\`, \`path/two\``) and nested-bullet form (heading followed by `  - \`path/one\``) are supported. A unit test covering both formats ships alongside the script.

Verdicts:

- **`CLEAN`** → every touched file is within this lane's `Owned files` globs. Proceed.
- **`PEER_INTRUSION`** → the lane touched files owned by another lane. Stderr lists peer + files. Pause on `AskUserQuestion`: merge anyway, bounce the lane, or ask the teammate to revert the peer edits.
- **`ORPHAN_FILES`** → the lane touched files outside every lane's globs. Surface to user — likely plan or impl bug.

**Pre-merge destructiveness check** — lanes that committed against a stale base can wipe peer-lane work on `--no-ff` merge. Use the three-outcome script:

```bash
bash scripts/pre_merge_destructiveness_check.sh <lane-sha> <merge-target> <whitelist-path>
```

Where `<whitelist-path>` is a file (one path per line) of deletions the lane legitimately performs per its plan section; `/dev/null` if the lane is purely additive.

The script (or a sibling) also runs an ADDITION-side check mirroring the deletion check: flag commits that ADD more than N files (default ~50) or more than M lines outside the lane's owned globs. Out-of-scope adds surface as a verdict alongside deletions to catch lanes that wandered.

Verdicts:

- **`SAFE`** — deletion list empty or all whitelisted. Merge with `git merge --no-ff <lane-sha>`.
- **`STALE_BASE_DETECTED`** — lane branched from a pre-peer-merge main but did not actively delete. Preview, then finalize with the 3-way merge:
  ```bash
  git merge --no-ff --no-commit <lane-sha>
  ls <peer-lane-owned-paths>   # must exist
  git commit --no-edit
  ```
  Do NOT salvage — salvage loses commit lineage.
- **`CONFLICT`** — lane actively removed files. DO NOT `--no-ff` merge. Salvage:
  ```bash
  git checkout <lane-sha> -- <lane's owned paths from the plan doc>
  git commit -m "feat(<phase>,<sl-id>): <subject>

  Salvage of <SL-ID> lane work: lane commit was based on stale main and
  would have deleted <peer lanes' files>. Cherry-picked in-scope additions only."
  ```
  Count this as a successful completion — no retry.

**Merge conflict** (non-destructive case) → treat as lane failure: `git merge --abort`, surface the conflict to the teammate via `SendMessage` asking it to rebase inside its worktree, then retry the merge.

**Post-merge import smoke** — run immediately after `git merge --no-ff` and before dispatching the next wave:

```bash
packages="$(git diff --name-only HEAD~..HEAD \
    | grep '__init__\.py$' \
    | sed 's|/__init__\.py$||; s|/|.|g' \
    | sort -u)"
if [[ -n "$packages" ]]; then
    bash scripts/post_merge_import_smoke.sh $packages
fi
```

On non-zero exit, the merge broke package load. Unwind with `git reset --hard HEAD~`, then retry per Step 8. Second failure halts the phase.

**Post-merge cleanup.** First, `cd "$(git rev-parse --show-toplevel)"` so subsequent Bash calls survive. Then `git worktree remove --force` any worktrees the lane used. `git branch -D` (not `-d`) every lane branch — salvaged work leaves branches unreachable from the merge target. If Step 6.5 returned `PARENT_ON_WRONG_BRANCH`, `git checkout <merge-target>` in the parent BEFORE removing worktrees.

## Step 8 — Retry-once, then halt

On first failure for a lane, decide between SendMessage-resume and kill-and-respawn based on whether the lane committed anything:

- **`commit_sha` empty AND `verify_exit_code != 0`** (teammate STOPped during preflight, no work done): kill via `TaskStop` and re-`Agent`-spawn fresh. Never resume a STOPped teammate with no commits — the worktree may be reaped and the resumed instance writes into the parent.
- **`commit_sha` populated AND verify failed** (teammate did work but it broke): re-address the same named teammate via `SendMessage` to preserve branch-state context.

In either case, the brief includes: the failure log, the escalated model+thinking hint, and the instruction to fix the failing task and re-run verify.

On second failure:

- Cancel all still-running lane Agents via their task IDs.
- Emit a diagnostic report naming the failing lane, the failing task, the last ~30 log lines, and which lanes were merged vs pending.
- Persist state to `.claude/claude-execute-phase-state.json` and exit cleanly. User can fix and re-run with `--resume`.

## Step 9 — Final verification, cleanup, and summary

After all lanes merged:

1. Run every command under the plan doc's `## Verification` section against the merged tree.
2. Run every assertion under `## Acceptance Criteria` that can be mechanically checked.
3. **Team teardown**. Try `TeamDelete` first. If it blocks (in-process teammates ignore `shutdown_request`), fall back to filesystem cleanup: `bash scripts/team_teardown.sh phase-<alias>` (rm on `the Claude home directory/teams/<team>/` + `the Claude home directory/tasks/<team>/`).
4. **Kill leftover background processes**. Run `ps aux | grep -E "next dev|node.*dev"` and `kill` any stragglers spawned by lane teammates.
5. **Clean-tree verification**. Run `git status`. After successful completion the tree must be clean (lane merges are the only changes, and they're committed). Allowlist: `.claude/worktrees/`, `.claude/claude-execute-phase-state.json`. Anything else → stop and surface.
6. Emit final summary:
   - Lanes merged (with merge-commit SHAs)
   - Gates closed
   - Final verification pass/fail
   - Total wall-clock duration
   - Per-lane breakdown: model used, duration, token spend, retry count
7. Mark the phase's parent TaskCreate (if one exists) as completed.

**Halt exception**: on Step 8 second-failure halt, `.claude/claude-execute-phase-state.json` persists for `--resume`. This is the documented dirty-tree exception; no commit required.

## Worktree lifecycle — prune after merge (standing rule)

**Standing rule: prune a lane's git worktree — and delete its now-dead branch — as soon as its PR merges. Never leave merged or abandoned worktrees behind.** Step 2a and Step 7 only cover the *in-run* `.claude/worktrees/` lanes. This rule covers the **sibling worktrees under the shared workspace volume** (`/mnt/workspace/worktrees/<project>-<branch>`, or the repo-sibling `../<project>-<branch>` fallback on hosts without it) that outlive a single run. Left unpruned, these accumulate without bound — the shared volume has reached thousands of stale merged worktrees because nothing swept them.

This is a **sweep**, not a "delete the tree you're standing in." At closeout you have just *opened* this run's PR, so the current run's own branch/worktree is still unmerged — it is KEPT by the criterion below, which is exactly what you want. Run the sweep at closeout (and, cheaply, at phase start).

For each sibling worktree from `git worktree list` (excluding the primary checkout and this run's own worktree), classify:

- **SAFE to prune** — the branch is MERGED **and** the tree is CLEAN. MERGED means either `git merge-base --is-ancestor <branch> origin/main` (fetch first) OR `gh pr view <branch> --json state -q .state` reports `MERGED`. CLEAN means `git -C <path> status --porcelain` is empty.
- **KEEP** — unmerged (work not yet on `origin/main` and no merged PR) OR dirty (`--porcelain` non-empty). Leave it and log one line. This preserves the current run's own worktree and any in-flight peer work.

To prune a SAFE worktree:

1. `git worktree remove --force <path>`.
2. `git branch -D <branch>` — the branch is dead once its PR merged to `origin/main`, so deleting it is correct. **This is distinct from Step 2a**, which keeps human-named branches (`skills/*`, `feature/*`, `fix/*`) precisely because that case is *local incorporation before the PR merges* and the ref may still be wanted. Once the PR is MERGED on `origin`, delete the branch regardless of naming.

**Permission-locked fallback (gotcha).** Worktrees whose `node_modules` (or other build output) was installed under a **different uid** — e.g. CI-offload / rootless-docker runs — are permission-locked. `git worktree remove --force` and a plain `rm -rf` will FAIL with `Permission denied`. When removal fails on permissions, fall back to `sudo rm -rf <path>` (or re-run the cleanup as the installing uid), then `git worktree prune` to drop the now-dangling administrative entry, then `git branch -D <branch>`. Do not treat a permission-denied removal as "KEEP" — it is still SAFE; it just needs the elevated path.

An idempotent helper is available: `bash "$(git rev-parse --show-toplevel)/.claude/skills/claude-execute-phase/scripts/prune_merged_worktrees.sh"` (pass `--dry-run` to preview). It encodes exactly the MERGED+CLEAN criterion and the `sudo rm -rf` fallback above and is safe to re-run.


## Output contract

On successful completion:

1. Every lane's branch merged into the target branch with a `--no-ff` commit, in topological order.
2. All lane worktrees removed; lane branches deleted.
3. All `TaskCreate`'d lane tasks marked `completed`.
4. `.claude/claude-execute-phase-state.json` deleted (or the `status` field set to `complete`).
5. Team torn down via `TeamDelete` or `team_teardown.sh`.
6. Final summary message to the user.

On halt:

1. Lanes that completed remain merged; their state is preserved.
2. `.claude/claude-execute-phase-state.json` contains the failing lane's name, task, log tail, and which gates/lanes were green vs open.
3. User can `/claude-execute-phase --resume` after fixing the blocker.

## Worktree layout

```
<repo>/
├── .claude/
│   ├── worktrees/
│   │   ├── lane-sl-1-<timestamp>-<random>/
│   │   └── …
│   └── claude-execute-phase-state.json
```

Both paths are auto-added to `.gitignore` in Step 2.

## Browser verification

Read this at plan intake, in adapter and interactive mode, before implementation or lane dispatch. Put the setup it requires in each affected lane brief.

When a plan's `## Verification` section includes Playwright/e2e commands or lane tasks ask for browser smoke-testing, run them:

- **Playwright via PMCP** — `pmcp_invoke(tool_id="playwright::browser_navigate", ...)` and related `playwright::*` tools. Default.
- **Chrome DevTools Protocol (CDP)** — low-level debugging (performance traces, CPU profiling).
- **`claude-in-chrome`** — extension-context automation only.

The PMCP Playwright server provisions on demand. If the repo lacks a Playwright config, add one in the lane rather than deferring the test.
