#!/usr/bin/env bash
# Decide whether a qualified-agy-image run must check the FULL source-pin set
# (agent-harness#1029). Prints `full=true|false` and appends it to $GITHUB_OUTPUT.
#
# - workflow_dispatch: always.
# - pull_request: when MERGING the PR changes RELEASE_PIN (a release cut) or the
#   qualification evidence (a new record must match the tree it lands on). The
#   checkout is GitHub's merge commit, so `HEAD^1..HEAD` is exactly the PR's effect
#   on the base -- never files the base gained after the PR forked (#1032 r1).
# - anything else (push, schedule): false. Nightly reports drift in its own step.
# A git error fails the run: an unknown answer must not read as "not a release".
set -euo pipefail
full=false
case "${EVENT:-}" in
  workflow_dispatch) full=true ;;
  pull_request)
    rc=0
    git diff --quiet HEAD^1 HEAD -- RELEASE_PIN plans/evidence/qualified-provider-images.json \
      'plans/evidence/agy-*-linux-x64-qualification.json' || rc=$?
    case "$rc" in
      0) ;;
      1) full=true ;;
      *) echo "::error::cannot diff the pull request's merge commit against its base" >&2; exit 1 ;;
    esac ;;
esac
echo "full=$full"
if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "full=$full" >> "$GITHUB_OUTPUT"; fi
