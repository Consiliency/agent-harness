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
#
# agent-harness#1042 (maintainer ruling 2026-09-25) retired the agent-harness#746
# exception that retained the node on a PR touching the gate's own selection
# plumbing (the table below): that cost ~50 minutes on every CI PR. Such a PR is
# still covered: the static guards in tests/test_ci_chronology_scope.py (run on
# every PR) pin that push/nightly/dispatch retain the node and that every
# consumer spells it the same way; the PR lane asserts the node is collectable;
# and the landing push's junit witness reds main if the node did not run and
# pass. To prove it BEFORE merge, dispatch test.yml on the branch with
# chronology=true. The table is kept: the reason line names a touched plumbing
# path, and ci/gate_metrics.py classifies runs with `--match`.
#
# Output: prints `chronology=true|false` (a GITHUB_OUTPUT line) and a reason to
# stderr. Exit 0 in both cases. FAIL CLOSED: an unknown event resolves to `true`
# -- the expensive-but-correct answer. A pull_request always resolves to `false`;
# its diff is read only to name a touched plumbing path in the reason.
#
# `--match <path>` mode: prints `match` / `no-match` for one path and exits 0.
# tests/test_ci_chronology_scope.py drives this mode to pin the table to the
# selection consumers.
set -euo pipefail

CHRONOLOGY_NODE="tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation"

# Repo-relative path patterns (bash `case` globs): the plumbing that selects,
# runs, or witnesses the node. `ci/*` is taken as a whole on purpose -- every
# file there is CI plumbing, and a reporter or instrument (main-red.sh,
# gate_metrics.py) retaining the node is a fail-closed over-approximation, cheap
# and rare; a new selection consumer added under ci/ can never be forgotten. Per-file under phase-loop-runtime/scripts
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
deferred="the landing push proves it; dispatch test.yml with chronology=true to prove it on the branch"
if [ -z "$base" ]; then
  decide false "pull_request (no CHRONOLOGY_BASE_SHA to name touched plumbing); $deferred"; exit 0
fi
# --no-renames: a rename reports BOTH endpoints. -z: NUL-terminated records, so
# quoted pathnames (core.quotePath) still match the table. NUL bytes do not
# survive a shell variable, so the listing goes through a file.
changed="$(mktemp)"
trap 'rm -f "$changed"' EXIT
if ! git diff -z --name-only --no-renames "$base...HEAD" >"$changed" 2>/dev/null; then
  decide false "pull_request (git diff $base...HEAD failed; touched plumbing unknown); $deferred"; exit 0
fi
count=0
while IFS= read -r -d '' path; do
  [ -n "$path" ] || continue
  count=$((count + 1))
  if gate_plumbing_path "$path"; then
    decide false "pull_request touches gate plumbing ($path); $deferred"; exit 0
  fi
done <"$changed"
decide false "PR defers the chronology node to the landing push ($count paths changed)"
