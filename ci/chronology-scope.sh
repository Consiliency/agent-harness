#!/usr/bin/env bash
# Decide whether THIS CI execution runs the heavy CONFORM chronology node.
#
# The node (CHRONOLOGY_NODE below) is a ~50-minute proof that the frozen CONFORM
# mutation definitions are unchanged and were never executed pre-implementation.
# Measured on the offloaded suite it is ~88% of the per-PR wall clock, and it ran
# twice per run (py3.10 lane + Gate A) plus a third time on the hosted runner via
# publish-pypi's Gate A. The proof's process reads far more than the modules it
# mutates (pytest collects the whole `tests/` tree, conftest bootstraps runtime
# plugins, sibling tests read repo docs), so this script does NOT claim a diff
# outside its table cannot change the verdict. The property it provides is
# narrower and holds by construction: the node runs unconditionally on every push
# to main and nightly, and on every PR whose diff touches the runtime package or
# the CI plumbing. For any other PR the proof is deferred to the landing merge --
# a regression surfaces on main at the latest, never silently.
#
# Output: prints `chronology=true|false` (a GITHUB_OUTPUT line) and a reason to
# stderr. Exit 0 in both cases. FAIL CLOSED: anything this script cannot decide
# (unknown event, no base, diff command failure) resolves to `true` -- the
# expensive-but-correct answer -- never to `false`.
#
# `--match <path>` mode: prints `match` / `no-match` for one path and exits 0.
# tests/test_ci_chronology_scope.py drives this mode to assert every input file
# named by the frozen mutation definitions is covered, so the exclusion cannot
# drift into a silent no-op when a mutation target moves.
set -euo pipefail

CHRONOLOGY_NODE="tests/test_outside_agent_conform_evidence.py::test_mutation_definitions_are_frozen_but_not_executed_preimplementation"

# Repo-relative path patterns (bash `case` globs): the whole runtime package
# directory (the proof's process executes inside it and its packaging inputs --
# pyproject.toml, MANIFEST.in, README.md, protocol/ -- are pinned by the frozen
# corpus, so no per-file enumeration is attempted) and the CI plumbing that
# selects the node in the first place.
chronology_input_path() {
  case "$1" in
    phase-loop-runtime/*) return 0 ;;
    ci/*) return 0 ;;
    .github/workflows/test.yml) return 0 ;;
    .github/workflows/publish-pypi.yml) return 0 ;;
  esac
  return 1
}

if [ "${1:-}" = "--match" ]; then
  if chronology_input_path "${2:?path required}"; then echo match; else echo no-match; fi
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
  if chronology_input_path "$path"; then
    decide true "PR touches chronology input: $path"; exit 0
  fi
done <"$changed"
decide false "PR touches no chronology input ($count paths changed)"
