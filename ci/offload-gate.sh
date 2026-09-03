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
OFFLOAD_LOCK="${OFFLOAD_LOCK:-/tmp/dagger-offload.lock}"
OFFLOAD_LOCK_WAIT_SECONDS="${OFFLOAD_LOCK_WAIT_SECONDS:-5400}"
OFFLOAD_LOCK_POLL_SECONDS="${OFFLOAD_LOCK_POLL_SECONDS:-1}"
_lock_fifo=""
_lock_out=""
_lock_pid=""
_lock_host=""

# The lock is held by a `flock ... -c cat` on the engine host whose stdin is a
# pipe we keep open here; closing our end (or dying: the runner kills the ssh)
# ends `cat`, `flock` exits, and the kernel releases the lock. No state survives
# a crash on either side.
offload_lock_host() {
  case "${DOCKER_HOST:-}" in
    ssh://*) printf '%s\n' "${DOCKER_HOST#ssh://}" ;;
    *) printf '' ;;
  esac
}

offload_lock_acquire() {
  local host
  host="$(offload_lock_host)"
  _lock_host="$host"
  if [ -z "$host" ]; then
    echo "offload lock: DOCKER_HOST is not an ssh:// engine; nothing to serialise against" >&2
    return 0
  fi
  # DOCKER_HOST may carry a port (ssh://user@host:2222); ssh wants it as -p.
  local -a ssh_target=("$host")
  case "$host" in
    *:*) ssh_target=(-p "${host##*:}" "${host%:*}") ;;
  esac
  _lock_fifo="$(mktemp -u)"
  _lock_out="$(mktemp)"
  mkfifo "$_lock_fifo"
  # Keepalives so a dead link surfaces as an exited ssh (which the supervisor
  # below turns into a stopped call) instead of a holder that looks alive.
  ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 "${ssh_target[@]}" \
    "flock -w '$OFFLOAD_LOCK_WAIT_SECONDS' '$OFFLOAD_LOCK' -c 'echo acquired; exec cat'" \
    <"$_lock_fifo" >"$_lock_out" 2>&1 &
  _lock_pid=$!
  exec 3>"$_lock_fifo"
  trap offload_lock_release EXIT
  echo "offload lock: waiting for $OFFLOAD_LOCK on $host (up to ${OFFLOAD_LOCK_WAIT_SECONDS}s)"
  while ! grep -q '^acquired$' "$_lock_out"; do
    if ! kill -0 "$_lock_pid" 2>/dev/null; then
      echo "offload lock: could not take $OFFLOAD_LOCK on $host within ${OFFLOAD_LOCK_WAIT_SECONDS}s (another offloaded suite is running there); refusing to run unlocked" >&2
      cat "$_lock_out" >&2
      exec 3>&-
      rm -f "$_lock_fifo" "$_lock_out"
      exit 1
    fi
    sleep 1
  done
  echo "offload lock: held ($OFFLOAD_LOCK on $host)"
}

offload_lock_release() {
  [ -n "$_lock_pid" ] || return 0
  exec 3>&-
  wait "$_lock_pid" 2>/dev/null || true
  rm -f "$_lock_fifo" "$_lock_out"
  _lock_pid=""
  echo "offload lock: released"
}

# Run the call while watching the lock holder. Once `acquired` has been seen the
# holder is an idle ssh; if it dies mid-call (link drop, remote flock killed) the
# kernel has already released the lock and a sibling may be starting, so the only
# honest outcome is to stop this call and fail -- never to finish it unlocked.
# The holder is checked once more AFTER the call returns: a holder that died in
# the last poll interval means the tail of the call ran unlocked, and that run
# is reported red even when dagger itself succeeded.
offload_lock_holder_alive() {
  [ -z "$_lock_pid" ] || kill -0 "$_lock_pid" 2>/dev/null
}

offload_lock_supervise() {
  "$@" &
  local call_pid=$!
  while kill -0 "$call_pid" 2>/dev/null; do
    if ! offload_lock_holder_alive; then
      echo "offload lock: lost $OFFLOAD_LOCK on $_lock_host during the call (lock holder exited); stopping the call rather than finishing unlocked" >&2
      cat "$_lock_out" >&2
      kill "$call_pid" 2>/dev/null || true
      wait "$call_pid" 2>/dev/null || true
      exit 1
    fi
    sleep "$OFFLOAD_LOCK_POLL_SECONDS"
  done
  local rc=0
  wait "$call_pid" || rc=$?
  if ! offload_lock_holder_alive; then
    echo "offload lock: lost $OFFLOAD_LOCK on $_lock_host before the call returned (lock holder exited); the call's tail ran unlocked, refusing to report it" >&2
    cat "$_lock_out" >&2
    exit 1
  fi
  return "$rc"
}

CHRONOLOGY="${CHRONOLOGY:-true}"
case "$CHRONOLOGY" in
  true|false) ;;
  *) echo "CHRONOLOGY must be 'true' or 'false', got '$CHRONOLOGY'" >&2; exit 1 ;;
esac
echo "chronology node: $([ "$CHRONOLOGY" = true ] && echo retained || echo deselected) (CHRONOLOGY=$CHRONOLOGY)"

# ONE offloaded suite per engine host at a time. The engine on the tailnet host
# prunes its store when a session ends (`dagql prune` + containerd GC), and that
# prune removes the rootfs of containers a still-running sibling session is
# executing in; the sibling then dies as a 200+ FileNotFoundError cascade that
# reads as a repo regression (agent-harness#746 diagnosis; runs 33713513497 and
# 33709063249). Serialising the calls on the HOST side -- a `flock` held on the
# engine host for the whole `dagger call` -- makes overlap impossible regardless
# of how many workflows dispatch at once. The lock lives on the host, not the
# runner, because the runners are ephemeral and independent; the path is
# deliberately generic so any repo offloading to the same engine can share it.
# Fail closed: if the lock cannot be taken within the wait, exit non-zero with a
# message naming the lock -- never run unlocked.
JUNIT_DIR=./junit-offload
rm -rf "$JUNIT_DIR"
offload_lock_acquire
offload_lock_supervise dagger -m "$MODULE" call all --source="$SOURCE" --chronology="$CHRONOLOGY" export --path="$JUNIT_DIR"
offload_lock_release

# `all`'s per-stage verdict roll-up used to be its stdout; it travels in the
# evidence directory now, so print it to keep the job log self-describing.
cat "$JUNIT_DIR/verdicts.txt"
