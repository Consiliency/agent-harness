#!/usr/bin/env bash
# prune_merged_worktrees.sh — standing "prune after merge" sweep.
#
# Prunes SIBLING git worktrees (typically under the workspace worktrees base or a
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
# SAFETY (three independent guards — a linked-worktree invocation must NEVER remove
# the PRIMARY checkout, which would destroy the shared object store):
#   (a) The PRIMARY worktree (first `worktree ` record of `git worktree list
#       --porcelain`) and the CURRENT worktree are always skipped, never classified.
#   (b) The `sudo rm -rf` fallback is CONFINED: it runs only for a path strictly
#       under the approved worktrees base ($PHASE_LOOP_WORKTREES_BASE, else the
#       parent of the current worktree). A path outside the base is never sudo-rm'd.
#   (c) The fallback escalates ONLY on a genuine PERMISSION-denied git error
#       (foreign-uid node_modules from CI-offload / rootless-docker). "is a main
#       working tree", "is locked", or any other failure → skip + warn, never sudo.
#
# Usage:
#   prune_merged_worktrees.sh [--dry-run]
#     --dry-run   Print PRUNE/KEEP decisions without removing anything.
#
# Env:
#   PHASE_LOOP_WORKTREES_BASE   Approved base dir for the sudo fallback confinement.
#                               Defaults to the parent of the current worktree.
#
# Idempotent: re-running after a clean sweep is a no-op. Exit 0 on success.

set -euo pipefail

# --- pure predicates (extracted so the self-test can exercise them directly) ---

# path_under_base <path> <base> — true iff <path> is strictly under <base>, using a
# trailing-slash boundary so `/base-evil` does NOT match base `/base`. Both are
# realpath-normalized. An empty path or base is always false (never confine nothing).
path_under_base() {
  local path="$1" base="$2"
  [[ -n "$path" && -n "$base" ]] || return 1
  local rp rb
  rp=$(realpath -m -- "$path" 2>/dev/null) || return 1
  rb=$(realpath -m -- "$base" 2>/dev/null) || return 1
  [[ "$rp" == "$rb" ]] && return 1          # equal to base ≠ strictly under
  [[ "$rp" == "$rb"/* ]]
}

# primary_worktree — the PRIMARY (main) checkout: the FIRST `worktree ` record of
# `git worktree list --porcelain`. Git always lists the main tree first.
primary_worktree() {
  git worktree list --porcelain | awk '/^worktree /{sub(/^worktree /,""); print; exit}'
}

# list_worktrees — every worktree path, one per line, tolerant of spaces in paths
# (parses the porcelain `worktree ` record instead of splitting on whitespace).
list_worktrees() {
  git worktree list --porcelain | awk '/^worktree /{sub(/^worktree /,""); print}'
}

# Guard: only source the predicates (for the self-test) without running the sweep.
[[ "${PRUNE_MERGED_WORKTREES_LIB:-0}" == "1" ]] && return 0 2>/dev/null || true

# --- sweep ---

DRY_RUN=0
for arg in "$@"; do
  [[ "$arg" == "--dry-run" ]] && DRY_RUN=1
done

SELF_WT=$(git rev-parse --show-toplevel)          # the worktree this invocation runs in
PRIMARY_WT=$(primary_worktree)                     # NEVER remove this
# Approved base for the sudo fallback. Explicit override wins; else the parent of
# the current worktree (the sibling worktrees live alongside it).
WORKTREES_BASE="${PHASE_LOOP_WORKTREES_BASE:-$(dirname -- "$SELF_WT")}"
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

# remove_worktree <path> — returns 0 iff <path> is gone afterward. Tries the
# git-native removal first; escalates to a CONFINED, PERMISSION-ONLY sudo fallback.
remove_worktree() {
  local path="$1"
  # Empty-var guard: never operate on an unset/empty path.
  [[ -n "$path" ]] || { echo "WARN:  refusing removal of empty path" >&2; return 1; }

  local err rc=0
  err=$(git worktree remove --force "$path" 2>&1) || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    return 0
  fi

  # Escalate ONLY on a genuine permission lock (foreign-uid build output).
  if ! grep -qi 'permission denied' <<<"$err"; then
    echo "WARN:  $path — git worktree remove failed (not a permission lock): ${err%%$'\n'*}; skipping" >&2
    return 1
  fi
  # Confine the sudo path: must be strictly under the approved worktrees base.
  if ! path_under_base "$path" "$WORKTREES_BASE"; then
    echo "WARN:  $path — permission-locked but OUTSIDE approved base ($WORKTREES_BASE); refusing sudo rm" >&2
    return 1
  fi

  echo "WARN:  $path — permission-locked (foreign uid); using confined 'sudo -n rm -rf'" >&2
  local src=0
  sudo -n rm -rf -- "$path" || src=$?
  if [[ "$src" -ne 0 ]]; then
    echo "WARN:  $path — 'sudo -n rm -rf' failed (rc=$src; no non-interactive sudo?); skipping" >&2
    return 1
  fi
  git worktree prune
  [[ ! -e "$path" ]]
}

while IFS= read -r wt; do
  [[ -n "$wt" ]] || continue
  [[ "$wt" == "$PRIMARY_WT" ]] && continue        # (a) never touch the primary checkout
  [[ "$wt" == "$SELF_WT" ]] && continue           #     never touch the current worktree

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
done < <(list_worktrees)

echo "prune-merged-worktrees: pruned=$PRUNED kept=$KEPT dry_run=$DRY_RUN base=$WORKTREES_BASE"
