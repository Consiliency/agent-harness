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
# class before any long proof), then the three interpreter suites with the
# chronology selection below, then Gate A. It returns the junit evidence produced BY those
# stage executions, so the export below is a read, not a second run.
#
# ONE `dagger call`, deliberately. This used to be two -- `call all`, then
# `call junit ... export` -- and the second call re-declared the py3.10 suite and
# Gate A in a fresh session with its own upload of $SOURCE. That deduped only while
# the engine still held those layers and the upload hashed identically; when it did
# not, the export RE-RAN the two heaviest stages. Run 31751696509 ran Gate A twice
# (50m59s + 49m44s) and py3.10 twice and hit the 120-minute job ceiling looking like
# a hang (agent-harness#550). Chaining `export` onto `all` keeps both in one session
# where they are one DAG node, so the artifact cannot be anything other than the
# output of the execution that gated the run.
#
# CHRONOLOGY decides whether the heavy CONFORM chronology node runs in this
# execution. The workflow computes it with ci/chronology-scope.sh (push to main,
# nightly, dispatch, or a PR touching one of the node's inputs => true) and hands
# it over in the environment. Unset means "nobody decided" and resolves to the
# expensive-but-correct answer, never to the skip.
CHRONOLOGY="${CHRONOLOGY:-true}"
case "$CHRONOLOGY" in
  true|false) ;;
  *) echo "CHRONOLOGY must be 'true' or 'false', got '$CHRONOLOGY'" >&2; exit 1 ;;
esac
echo "chronology node: $([ "$CHRONOLOGY" = true ] && echo retained || echo deselected) (CHRONOLOGY=$CHRONOLOGY)"

JUNIT_DIR=./junit-offload
rm -rf "$JUNIT_DIR"
dagger -m "$MODULE" call all --source="$SOURCE" --chronology="$CHRONOLOGY" export --path="$JUNIT_DIR"

# `all`'s per-stage verdict roll-up used to be its stdout; it travels in the
# evidence directory now, so print it to keep the job log self-describing.
cat "$JUNIT_DIR/verdicts.txt"
