#!/usr/bin/env bash
# The offloaded gate command.
#
# The dagger-offload composite sets AGENT_DAGGER=1 and AGENT_REMOTE_HOST=<host>
# and then runs this script; the routing convention is this script's job, not the
# composite's (see Consiliency/ci-actions dagger-offload README, and
# governed-pipeline's daggerRemoteEnv() for the reference implementation).
#
# Fail-closed by construction. The composite already refuses to proceed when the
# dagger CLI is missing or the remote engine is unreachable; this script adds the
# matching refusal on its own side: if it is invoked on the offload path
# (AGENT_DAGGER=1) without a resolvable remote target, it exits non-zero rather
# than quietly running the suite locally. A silent local run would bill the hosted
# runner for work that was supposed to move, and would read as a green "offload".
set -euo pipefail

MODULE="${MODULE:-ci/dagger}"
SOURCE="${SOURCE:-.}"

if [ "${AGENT_DAGGER:-0}" = "1" ]; then
  if [ -z "${AGENT_REMOTE_HOST:-}" ] && [ -z "${DOCKER_HOST:-}" ]; then
    echo "offload requested (AGENT_DAGGER=1) but no remote target is set:" >&2
    echo "  neither AGENT_REMOTE_HOST nor DOCKER_HOST is present." >&2
    echo "  Refusing to fall back to a local run -- that would read as a green offload." >&2
    exit 1
  fi
  # DOCKER_HOST is what actually routes the dagger engine at the remote host; the
  # composite's SSH config step has already taught ssh how to reach it.
  export DOCKER_HOST="${DOCKER_HOST:-ssh://${AGENT_REMOTE_HOST}}"
  echo "offloading agent-harness CI to ${DOCKER_HOST}"
else
  echo "running agent-harness CI locally (no offload requested)"
fi

# `all` runs the object-database probe first (seconds, catches the incomplete-clone
# class before any long proof), then the three interpreter suites with the two-lane
# chronology selection, then Gate A.
dagger -m "$MODULE" call all --source="$SOURCE"

# Export the junit evidence so the workflow can upload it as an artifact. The
# two-lane plan's evidence contract has to survive the move off the hosted runner.
dagger -m "$MODULE" call junit --source="$SOURCE" export --path=./junit-offload
