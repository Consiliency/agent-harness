# Worktree pruning (gemini-execute-phase)

Read this at closeout and, cheaply, at phase start.

## Worktree lifecycle — prune after merge (standing rule)

**Prune a worktree — and delete its now-dead branch — as soon as its PR merges. Never leave merged or abandoned worktrees behind.** Forced removal of the run's own lane worktrees at merge time is already allowed runner hygiene; this rule additionally covers the **sibling worktrees under the shared workspace volume** (`/mnt/workspace/worktrees/<project>-<branch>`, or the repo-sibling `../<project>-<branch>` fallback on hosts without it) that outlive a single run. Left unpruned they accumulate without bound — the shared volume has reached thousands of stale merged worktrees because nothing swept them.

This is a **sweep**, not "delete the tree you are standing in." At closeout the current run's own branch/worktree is still unmerged, so it is KEPT by the criterion below — which is exactly right. Run the sweep at closeout (and, cheaply, at phase start).

For each sibling worktree from `git worktree list` (excluding the primary checkout and this run's own worktree), classify:

- **SAFE to prune** — the branch is MERGED **and** the tree is CLEAN. MERGED means either `git merge-base --is-ancestor <branch> origin/main` (fetch first) OR `gh pr view <branch> --json state -q .state` reports `MERGED` (catches squash/rebase merges that are not ancestors). CLEAN means `git -C <path> status --porcelain` is empty. Then `git worktree remove --force <path>` and `git branch -D <branch>` — the ref is dead once its PR merged to `origin`, so deleting it is correct regardless of the branch's naming.
- **KEEP** — unmerged (work not on `origin/main` and no merged PR) OR dirty (`--porcelain` non-empty). Leave it and log one line. This preserves the current run's own worktree and any in-flight peer work.

**Permission-locked fallback (gotcha).** A worktree whose `node_modules` (or other build output) was installed under a **different uid** — e.g. CI-offload / rootless-docker runs — is permission-locked. `git worktree remove --force` and a plain `rm -rf` will FAIL with `Permission denied`. When removal fails on permissions, fall back to `sudo rm -rf <path>` (or re-run the cleanup as the installing uid), then `git worktree prune` to drop the dangling administrative entry, then `git branch -D <branch>`. A permission-denied removal is still SAFE — do not reclassify it as KEEP.
