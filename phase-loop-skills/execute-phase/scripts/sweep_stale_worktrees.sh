#!/usr/bin/env bash
# sweep_stale_worktrees.sh — prune stale claude-execute-phase worktrees from prior sessions.
#
# For each worktree, checks whether its HEAD commit has been incorporated into the
# current merge target (HEAD).  Worktrees whose work is already on the target AND
# whose tree is clean are removed; everything else is kept and reported.
#
# Decision rules (aligned with prune_merged_worktrees.sh and sweep_fleet_worktrees.sh):
#   MERGED = `git merge-base --is-ancestor <worktree HEAD> HEAD`
#   CLEAN  = `git -C <path> status --porcelain` is empty (untracked files count as dirty).
#   PRUNE  = MERGED and CLEAN.
#   KEEP   = anything else: unmerged, or dirty.
# The PRIMARY checkout and the invoking worktree are always skipped, never classified.
#
# A merged-but-dirty worktree is the common post-merge follow-up state: the commits
# are already on the target while uncommitted edits sit on top. Removing it destroys
# that work irrecoverably, so MERGED alone must never authorize removal (agent-harness#1300).
#
# Usage:
#   sweep_stale_worktrees.sh [--dry-run]
#
#   --dry-run   Print PRUNE/KEEP decisions without removing anything.
#
# Exit code: 0 on success (even if nothing was pruned); non-zero on git errors.

set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done

TOPLEVEL=$(git rev-parse --show-toplevel)

# primary_worktree — the PRIMARY (main) checkout: the FIRST `worktree ` record of
# `git worktree list --porcelain`. Git always lists the main tree first. Invoking
# this script from a linked worktree must not target the primary checkout.
primary_worktree() {
  git worktree list --porcelain | awk '/^worktree /{sub(/^worktree /,""); print; exit}'
}
PRIMARY=$(primary_worktree)

PRUNED=0
KEPT=0
SKIPPED=0

# Collect worktree paths (skip the main checkout)
while IFS= read -r wt; do
  if [[ "$wt" == "$TOPLEVEL" || "$wt" == "$PRIMARY" ]]; then
    SKIPPED=$(( SKIPPED + 1 ))
    continue
  fi

  wt_sha=$(git -C "$wt" rev-parse HEAD 2>/dev/null) || {
    echo "WARN:  $wt — could not read HEAD, skipping" >&2
    continue
  }
  wt_branch=$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "<detached>")

  if ! git merge-base --is-ancestor "$wt_sha" HEAD 2>/dev/null; then
    echo "KEEP:  $wt ($wt_sha, branch $wt_branch) — unmerged work"
    KEPT=$(( KEPT + 1 ))
    continue
  fi

  # MERGED. Refuse to remove a dirty tree: uncommitted work is unrecoverable once
  # the worktree is gone. `status --porcelain` reports untracked files too, which is
  # deliberate — an untracked artifact may be the only copy.
  if ! wt_status=$(git -C "$wt" status --porcelain 2>/dev/null); then
    echo "KEEP:  $wt ($wt_sha, branch $wt_branch) — could not read status, refusing to remove" >&2
    KEPT=$(( KEPT + 1 ))
    continue
  fi
  if [[ -n "$wt_status" ]]; then
    echo "KEEP:  $wt ($wt_sha, branch $wt_branch) — dirty tree ($(printf '%s\n' "$wt_status" | grep -c .) uncommitted path(s))"
    KEPT=$(( KEPT + 1 ))
    continue
  fi

  echo "PRUNE: $wt ($wt_sha, branch $wt_branch) — work incorporated into merge target, tree clean"

  if [[ "$DRY_RUN" -eq 0 ]]; then
    # Plain --force only. `unlock` + `-f -f` would override an intentional lock and
    # force-remove a submodule-bearing tree; a locked worktree is an explicit
    # "do not reclaim" marker and must be respected.
    if ! git worktree remove --force "$wt"; then
      echo "WARN:  $wt — removal failed (locked?), left in place" >&2
      KEPT=$(( KEPT + 1 ))
      continue
    fi

    # Delete the branch only when it matches an auto-named pattern; leave
    # human-named branches (feature/*, fix/*, skills/*, etc.) intact.
    if [[ "$wt_branch" =~ ^(worktree-agent-|phase/.*/sl-) ]]; then
      git branch -D "$wt_branch" 2>/dev/null || true
    fi
  fi

  PRUNED=$(( PRUNED + 1 ))
done < <(git worktree list --porcelain | awk '/^worktree / {print $2}')

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry-run complete: $PRUNED would be pruned, $KEPT would be kept, $SKIPPED skipped."
else
  echo "Sweep complete: $PRUNED pruned, $KEPT kept, $SKIPPED skipped."
fi
