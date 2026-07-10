#!/usr/bin/env bash
# prune_merged_worktrees.sh — standing "prune after merge" sweep (Step 9.6).
#
# Prunes SIBLING git worktrees (typically under /mnt/workspace/worktrees/ or a
# repo sibling) whose branch has MERGED and whose tree is CLEAN, then deletes the
# now-dead branch. Unlike sweep_stale_worktrees.sh (which keys off local
# incorporation into HEAD and keeps human-named branches), this sweep is keyed off
# the PR having merged to origin/main, so the branch ref is dead and is deleted
# regardless of naming.
#
# SAFE to prune  = MERGED and CLEAN.
#   MERGED = `git merge-base --is-ancestor <branch> origin/main`  (fetch first)
#            OR  `gh pr view <branch>` reports state MERGED.
#   CLEAN  = `git -C <path> status --porcelain` is empty.
# KEEP           = unmerged OR dirty. Preserves this run's own (unmerged) worktree
#                  and any in-flight peer work.
#
# Permission gotcha: worktrees whose node_modules/build output was installed under a
# DIFFERENT uid (CI-offload / rootless-docker) are permission-locked; `git worktree
# remove --force` and plain `rm -rf` FAIL. This script falls back to `sudo rm -rf`
# then `git worktree prune`. A permission-denied removal is still SAFE, not KEEP.
#
# Usage:
#   prune_merged_worktrees.sh [--dry-run]
#     --dry-run   Print PRUNE/KEEP decisions without removing anything.
#
# Idempotent: re-running after a clean sweep is a no-op. Exit 0 on success.

set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done

TOPLEVEL=$(git rev-parse --show-toplevel)
SELF_WT=$(git rev-parse --show-toplevel)  # the worktree this invocation runs in
PRUNED=0
KEPT=0

# Best-effort refresh of origin/main so the ancestor check is accurate. Non-fatal.
git fetch --quiet origin main 2>/dev/null || true

is_merged() {
  local branch="$1"
  # (1) branch tip is an ancestor of origin/main → its PR merged (or fast-forwarded).
  if git merge-base --is-ancestor "$branch" origin/main 2>/dev/null; then
    return 0
  fi
  # (2) gh reports the PR for this branch as MERGED (squash/rebase merges are not
  #     ancestors, so this catches them). gh absent / no PR → not merged.
  if command -v gh >/dev/null 2>&1; then
    local state
    state=$(gh pr view "$branch" --json state -q .state 2>/dev/null || true)
    [[ "$state" == "MERGED" ]] && return 0
  fi
  return 1
}

remove_worktree() {
  # Try the git-native removal first; on failure (usually a foreign-uid
  # permission lock) fall back to sudo rm -rf + prune. Returns 0 if the path is gone.
  local path="$1"
  if git worktree remove --force "$path" 2>/dev/null; then
    return 0
  fi
  echo "WARN:  $path — git worktree remove failed (likely a permission lock); using sudo rm -rf" >&2
  sudo rm -rf "$path"
  git worktree prune
  [[ ! -e "$path" ]]
}

while IFS= read -r wt; do
  [[ "$wt" == "$TOPLEVEL" ]] && continue
  [[ "$wt" == "$SELF_WT" ]] && continue

  wt_branch=$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "<detached>")
  if [[ "$wt_branch" == "<detached>" || "$wt_branch" == "HEAD" ]]; then
    echo "KEEP:  $wt (detached HEAD) — no branch to evaluate/merge-check" >&2
    KEPT=$((KEPT + 1))
    continue
  fi

  if [[ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ]]; then
    echo "KEEP:  $wt (branch $wt_branch) — dirty tree" >&2
    KEPT=$((KEPT + 1))
    continue
  fi

  if ! is_merged "$wt_branch"; then
    echo "KEEP:  $wt (branch $wt_branch) — unmerged (not on origin/main, no merged PR)" >&2
    KEPT=$((KEPT + 1))
    continue
  fi

  echo "PRUNE: $wt (branch $wt_branch) — MERGED and CLEAN"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    if remove_worktree "$wt"; then
      git branch -D "$wt_branch" 2>/dev/null || true
      PRUNED=$((PRUNED + 1))
    else
      echo "WARN:  $wt — removal did not complete; leaving branch $wt_branch intact" >&2
      KEPT=$((KEPT + 1))
    fi
  fi
done < <(git worktree list --porcelain | awk '/^worktree /{print $2}')

echo "prune-merged-worktrees: pruned=$PRUNED kept=$KEPT dry_run=$DRY_RUN"
