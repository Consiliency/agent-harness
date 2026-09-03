#!/usr/bin/env bash
# Decide whether THIS CI execution runs the heavy CONFORM chronology node.
#
# The node (CHRONOLOGY_NODE below) is a ~50-60 minute proof that the frozen
# CONFORM mutation definitions are unchanged and were never executed
# pre-implementation. Measured on the offloaded suite (run 33709063249) it is
# ~88% of the per-PR wall clock, and it runs twice per run (py3.10 lane + Gate A).
# It proves a property of frozen HISTORY, not of the diff under review, so a
# pull request DEFERS it: the landing push to main executes it on the exact
# merged tree, and the nightly bounds how long a regression can stay invisible.
# The one exception is a PR that changes the gate's own selection plumbing --
# this script, the workflows, the offload/Dagger plumbing, the witness, Gate A's
# consumer and its probe (the table below) -- because such a PR could change
# WHETHER the node runs, and that must be proven on the PR itself.
# Exception record (rule / reason / owner / accepted limitation):
# .consiliency/plans/detailed-split-pr-gate-chronology-746-*.md, and the
# CHANGELOG entry for Consiliency/agent-harness#746.
#
# Output: prints `chronology=true|false` (a GITHUB_OUTPUT line) and a reason to
# stderr. Exit 0 in both cases. FAIL CLOSED: anything this script cannot decide
# (unknown event, no base, diff command failure) resolves to `true` -- the
# expensive-but-correct answer -- never to `false`.
#
# `--match <path>` mode: prints `match` / `no-match` for one path and exits 0.
# tests/test_ci_chronology_scope.py drives this mode to pin the table to exactly
# the selection consumers, so it can neither drift wider (re-running the node on
# ordinary PRs) nor narrower (letting a plumbing change skip its own proof).
set -euo pipefail

CHRONOLOGY_NODE="tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation"

# Repo-relative path patterns (bash `case` globs): exactly the plumbing that
# selects, runs, or witnesses the node. Per-file under phase-loop-runtime/scripts
# on purpose: the other scripts there (regenerate_skills_bundle.py,
# sync_skills_bundle.py, check_model_id_sources.py, sweep_fleet_worktrees.sh) are
# not selection plumbing. The runtime package itself is NOT in the table -- the
# landing push proves it.
gate_plumbing_path() {
  case "$1" in
    ci/*) return 0 ;;
    .github/workflows/test.yml) return 0 ;;
    .github/workflows/publish-pypi.yml) return 0 ;;
    phase-loop-runtime/scripts/chronology_witness.py) return 0 ;;
    phase-loop-runtime/scripts/gate_a_cleanroom.sh) return 0 ;;
    phase-loop-runtime/scripts/_gate_a_probe.py) return 0 ;;
  esac
  return 1
}

if [ "${1:-}" = "--match" ]; then
  if gate_plumbing_path "${2:?path required}"; then echo match; else echo no-match; fi
  exit 0
fi
if [ "${1:-}" = "--node" ]; then
  echo "$CHRONOLOGY_NODE"
  exit 0
fi

decide() {
  # $1 = value, $2 = reason
  echo "chronology=$1"
  echo "chronology=$1 ($2)" >&2
}

# An operator override (workflow_dispatch input, or a local run) wins outright.
case "${CHRONOLOGY_FORCE:-}" in
  true|1)  decide true  "forced by CHRONOLOGY_FORCE"; exit 0 ;;
  false|0) decide false "forced off by CHRONOLOGY_FORCE"; exit 0 ;;
esac

event="${GITHUB_EVENT_NAME:-}"
case "$event" in
  push|schedule|workflow_dispatch)
    decide true "event=$event always retains the node"; exit 0 ;;
  pull_request) ;;
  *)
    decide true "event='${event}' is not a recognised scope; failing closed"; exit 0 ;;
esac

base="${CHRONOLOGY_BASE_SHA:-}"
if [ -z "$base" ]; then
  decide true "pull_request without CHRONOLOGY_BASE_SHA; failing closed"; exit 0
fi
# --no-renames: a rename reports BOTH endpoints, so moving an input out of the
# table still surfaces the old (matched) path instead of only the new one.
# -z: NUL-terminated records. Without it git quotes pathnames containing
# non-ASCII bytes, tabs, newlines or quotes (core.quotePath), and the leading
# `"` would defeat every prefix pattern above. NUL bytes do not survive a shell
# variable, so the listing goes through a file.
changed="$(mktemp)"
trap 'rm -f "$changed"' EXIT
if ! git diff -z --name-only --no-renames "$base...HEAD" >"$changed" 2>/dev/null; then
  decide true "git diff $base...HEAD failed (shallow or missing base?); failing closed"; exit 0
fi
count=0
while IFS= read -r -d '' path; do
  [ -n "$path" ] || continue
  count=$((count + 1))
  if gate_plumbing_path "$path"; then
    decide true "PR touches gate plumbing: $path"; exit 0
  fi
done <"$changed"
decide false "PR defers the chronology node to the landing push ($count paths changed)"
