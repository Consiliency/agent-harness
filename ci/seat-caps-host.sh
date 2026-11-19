#!/usr/bin/env bash
# Host preparation for the agy release gate on an ephemeral hosted runner
# (agent-harness#1993; docs/seat-resource-caps.md, "CI and hosted runners").
#
# The runtime's per-seat resource caps (agent-harness#1895) need a systemd user manager
# that delegates cpu, cpuset, io, memory and pids, and a whole block device under the
# automatic scratch paths for io.max. Hosted runner pools differ in storage layout, so
# this script gives every runner the same scratch device: a private sparse loop-backed
# ext4 filesystem. It only prepares the host. It changes nothing about how the runtime
# decides readiness or enforces caps.
#
#   context -- CMD...            run a diagnostic CMD in this shell's own environment
#                                (no user manager needed); never fails the step
#   delegate                     give the user manager the five controllers
#   provision                    create, attach, format and mount the scratch device
#   run [--baseline] -- CMD...   run CMD as a oneshot unit of the user manager; without
#                                --baseline, CMD's scratch paths and its temporary
#                                directory (TMPDIR) point at the device
#   majmin                       print the scratch device's MAJ:MIN
#   mountpoint                   print the scratch filesystem's mount point
#   teardown                     stop leftover units, unmount, detach only the owned device
#
# Every subcommand is usable from a fresh step shell: none relies on variables exported
# by an earlier step. State lives in "$RUNNER_TEMP/seat-caps" and evidence in
# "$RUNNER_TEMP/seat-caps-evidence", which teardown never deletes.
set -euo pipefail

# Empty on a runner. The script's own tests point it at a scratch tree.
root="${CI_HOST_ROOT:-}"

: "${RUNNER_TEMP:?RUNNER_TEMP must name the runner temporary directory}"
state_dir="$RUNNER_TEMP/seat-caps"
state="$state_dir/state"
image="$state_dir/scratch.img"
mnt="$state_dir/mnt"
evidence="$RUNNER_TEMP/seat-caps-evidence"
image_size=8G
image_bytes=$((8 * 1024 * 1024 * 1024))
headroom_bytes=$((2 * 1024 * 1024 * 1024))
unit_prefix=ci-seat-caps-run-
uid="$(id -u)"
gid="$(id -g)"
user="$(id -un)"
subcommand="${1:-}"

usage() {
  echo "usage: seat-caps-host.sh {context -- CMD...|delegate|provision|run [--baseline] -- CMD...|majmin|mountpoint|teardown}" >&2
  exit 2
}

note() {
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$subcommand" "$*" >>"$evidence/host.log"
  printf '%s\n' "$*" >&2
}

fail() {
  printf '%s %s error: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$subcommand" "$*" >>"$evidence/host.log"
  printf '::error::%s\n' "$*" >&2
}

ensure_evidence() {
  mkdir -p "$evidence"
  chmod 0700 "$evidence"
}

# --- state: append-only key=value lines, parsed and never sourced -----------------
declare -A st=()

record() {
  printf '%s=%s\n' "$1" "$2" >>"$state"
}

load_state() {
  st=()
  [ -f "$state" ] || return 1
  local key value
  while IFS='=' read -r key value; do
    [ -n "$key" ] && st["$key"]="$value"
  done <"$state"
  return 0
}

# Refuse to act on a state file whose values are not exactly what provision writes.
validate_state() {
  local key value ok=1
  for key in "${!st[@]}"; do
    value="${st[$key]}"
    case "$key" in
      uid) [ "$value" = "$uid" ] || ok=0 ;;
      gid) [ "$value" = "$gid" ] || ok=0 ;;
      image) [ "$value" = "$image" ] || ok=0 ;;
      loop) [[ $value =~ ^/dev/loop[0-9]+$ ]] || ok=0 ;;
      majmin) [[ $value =~ ^[0-9]+:[0-9]+$ ]] || ok=0 ;;
      mountdir | mount) [ "$value" = "$mnt" ] || ok=0 ;;
      provisioned) [ "$value" = 1 ] || ok=0 ;;
      *) ok=0 ;;
    esac
    if [ "$ok" = 0 ]; then
      fail "unexpected scratch state entry '$key=$value' in $state"
      return 1
    fi
  done
  return 0
}

# --- user manager -----------------------------------------------------------------
# Always set here, never inherited: each step starts a new shell.
manager_env() {
  export XDG_RUNTIME_DIR="/run/user/$uid"
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
}

bus_ready() {
  [ -S "$root$XDG_RUNTIME_DIR/bus" ]
}

cmd_context() {
  [ "${1:-}" = -- ] && shift
  [ $# -gt 0 ] || usage
  local status=0
  PYTHONDONTWRITEBYTECODE=1 timeout -k 10 120 "$@" || status=$?
  if [ "$status" -ne 0 ]; then
    note "host-context diagnostic exited $status"
    printf '::warning::host-context diagnostic exited %s\n' "$status" >&2
  fi
  return 0
}

cmd_delegate() {
  local dropin="$root/etc/systemd/system/user@.service.d"
  sudo mkdir -p "$dropin"
  printf '[Service]\nDelegate=cpu cpuset io memory pids\n' \
    | sudo tee "$dropin/delegate.conf" >/dev/null
  sudo systemctl daemon-reload
  sudo loginctl enable-linger "$user"
  # A manager started before the drop-in keeps its old controller mask: restart it.
  sudo systemctl restart "user@$uid.service"
  manager_env
  local _
  for _ in $(seq 60); do
    bus_ready && break
    sleep 1
  done
  if ! bus_ready; then
    fail "the user manager bus did not appear at $XDG_RUNTIME_DIR/bus within 60 s"
    exit 1
  fi
  local controllers="$root/sys/fs/cgroup/user.slice/user-$uid.slice/user@$uid.service/cgroup.controllers"
  note "user manager controllers: $(cat "$controllers" 2>/dev/null || echo unavailable)"
  local controller
  for controller in cpu io memory pids; do
    if ! grep -qw "$controller" "$controllers" 2>/dev/null; then
      fail "user manager does not delegate $controller"
      exit 1
    fi
  done
  note "delegation ready"
}

# --- provision ----------------------------------------------------------------------
provisioning=0

on_provision_exit() {
  local status=$1
  trap - EXIT TERM INT
  set +e
  if [ "$provisioning" != 1 ]; then
    exit "$status"
  fi
  [ "$status" -ne 0 ] || status=1
  fail "provision failed with status $status; rolling back the recorded state"
  local cleanup=0
  teardown_core || cleanup=$?
  if [ "$cleanup" -ne 0 ]; then
    fail "rollback also failed with status $cleanup; the original failure was status $status"
  fi
  exit "$status"
}

cmd_provision() {
  local tool missing=()
  for tool in losetup mkfs.ext4 findmnt mount umount lsblk truncate df systemd-run; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
  done
  if [ ${#missing[@]} -ne 0 ]; then
    fail "required host tools are absent: ${missing[*]}"
    exit 1
  fi
  if [ ! -e "$root/dev/loop-control" ]; then
    fail "/dev/loop-control is absent"
    exit 1
  fi
  if ! sudo -n true; then
    fail "non-interactive sudo is unavailable"
    exit 1
  fi
  local avail
  avail="$(df --output=avail -B1 "$RUNNER_TEMP" | tail -n 1 | tr -d ' ')"
  # A sparse image reserves nothing, so this check is the space guard.
  if ! [[ $avail =~ ^[0-9]+$ ]] || [ "$avail" -lt $((image_bytes + headroom_bytes)) ]; then
    fail "free space at $RUNNER_TEMP is ${avail:-unknown} bytes; need $((image_bytes + headroom_bytes))"
    exit 1
  fi
  local path
  for path in "$state_dir" "$image" "$mnt"; do
    if [ -e "$path" ] || [ -L "$path" ]; then
      fail "$path already exists"
      exit 1
    fi
  done

  # From here on, any exit before the end rolls back exactly what the state file records.
  provisioning=1
  trap 'on_provision_exit $?' EXIT
  trap 'exit 143' TERM
  trap 'exit 130' INT

  mkdir -m 0700 "$state_dir"
  (umask 077 && : >"$state")
  record uid "$uid"
  record gid "$gid"
  truncate -s "$image_size" "$image"
  record image "$image"
  local loop majmin
  loop="$(sudo losetup --find --show "$image")"
  if ! [[ $loop =~ ^/dev/loop[0-9]+$ ]]; then
    fail "losetup returned an unexpected device '$loop'"
    exit 1
  fi
  record loop "$loop"
  majmin="$(lsblk -dno MAJ:MIN "$loop" | tr -d ' ')"
  if ! [[ $majmin =~ ^[0-9]+:[0-9]+$ ]]; then
    fail "lsblk returned an unexpected MAJ:MIN '$majmin' for $loop"
    exit 1
  fi
  record majmin "$majmin"
  sudo mkfs.ext4 -q -m 0 -E lazy_itable_init=0 "$loop"
  mkdir -m 0700 "$mnt"
  record mountdir "$mnt"
  sudo mount "$loop" "$mnt"
  record mount "$mnt"
  sudo chown "$uid:$gid" "$mnt"
  chmod 0700 "$mnt"
  # The temporary directory for gate commands (TMPDIR in run). The conformance suite's
  # test isolation moves both automatic scratch paths below pytest's tmp_path, whose
  # root is the temporary directory, so it must be on the device too (agent-harness#1993).
  mkdir -m 0700 "$mnt/tmp"
  local source fstype
  read -r source fstype < <(findmnt -no SOURCE,FSTYPE --mountpoint "$mnt") || true
  if [ "${source:-} ${fstype:-}" != "$loop ext4" ]; then
    fail "$mnt shows '${source:-} ${fstype:-}', expected '$loop ext4'"
    exit 1
  fi
  uname -r >"$evidence/kernel.txt"
  losetup --json --list "$loop" >"$evidence/losetup.json" || true
  findmnt --json "$mnt" >"$evidence/findmnt.json" || true
  record provisioned 1
  provisioning=0
  trap - EXIT TERM INT
  note "provisioned $loop ($majmin) at $mnt"
}

# --- run ----------------------------------------------------------------------------
run_unit=""
run_child=""

on_run_signal() {
  trap - TERM INT
  note "interrupted; stopping $run_unit"
  timeout 30 systemctl --user stop "$run_unit" >/dev/null 2>&1 || true
  kill -TERM "$run_child" 2>/dev/null || true
  wait "$run_child" 2>/dev/null || true
  exit 143
}

mounted_as_expected() {
  local source fstype
  read -r source fstype < <(findmnt -no SOURCE,FSTYPE --mountpoint "${st[mount]}") || true
  [ "${source:-} ${fstype:-}" = "${st[loop]} ext4" ]
}

require_provisioned() {
  if ! load_state; then
    fail "no scratch device is provisioned; run provision first"
    exit 1
  fi
  validate_state || exit 1
  if [ "${st[provisioned]:-}" != 1 ]; then
    fail "the scratch device was not completely provisioned"
    exit 1
  fi
}

cmd_run() {
  local baseline=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --baseline) baseline=1; shift ;;
      --) shift; break ;;
      *) usage ;;
    esac
  done
  [ $# -gt 0 ] || usage
  # Not a fallback: always set, so a step shell needs nothing from an earlier step.
  manager_env
  if ! bus_ready; then
    fail "no user manager bus at $XDG_RUNTIME_DIR/bus; run delegate first"
    exit 1
  fi
  local scratch=()
  if [ "$baseline" = 0 ]; then
    require_provisioned
    if ! mounted_as_expected; then
      fail "${st[mount]} is not the provisioned ${st[loop]} ext4 filesystem"
      exit 1
    fi
    if [ ! -d "${st[mount]}/tmp" ] || [ -L "${st[mount]}/tmp" ]; then
      fail "${st[mount]}/tmp is not the provisioned temporary directory"
      exit 1
    fi
    # The two documented scratch overrides, and TMPDIR. A test session (the strict
    # conformance suite) replaces the overrides with paths below pytest's tmp_path, which
    # is rooted at TMPDIR; without it those paths fall back to the host's /tmp.
    scratch=(-E "PHASE_LOOP_SANDBOX_STAGING_DIR=${st[mount]}/sandboxes"
             -E "XDG_CACHE_HOME=${st[mount]}/cache"
             -E "TMPDIR=${st[mount]}/tmp")
  fi
  run_unit="$unit_prefix$(date +%s)-$$"
  # --same-dir keeps the caller's working directory. Type=oneshot makes a signal death
  # a failure: timeout re-raises its child's signal, which a simple service counts as clean.
  systemd-run --user --pipe --wait --collect --quiet --same-dir -p Type=oneshot \
    --unit="$run_unit" \
    -E "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR" -E PYTHONDONTWRITEBYTECODE=1 \
    -E "PATH=$PATH" -E "HOME=$HOME" "${scratch[@]}" \
    -- "$@" &
  run_child=$!
  trap on_run_signal TERM INT
  local status=0
  wait "$run_child" || status=$?
  trap - TERM INT
  return "$status"
}

cmd_majmin() {
  require_provisioned
  printf '%s\n' "${st[majmin]}"
}

cmd_mountpoint() {
  require_provisioned
  printf '%s\n' "${st[mount]}"
}

# --- teardown -----------------------------------------------------------------------
is_mounted() {
  findmnt --mountpoint "$1" >/dev/null 2>&1
}

stop_units() {
  manager_env
  if ! bus_ready; then
    note "user manager bus is unavailable at $XDG_RUNTIME_DIR/bus; no user units can be listed or stopped"
    return 0
  fi
  local listing units unit rc=0
  if ! listing="$(timeout 30 systemctl --user list-units --no-legend --plain \
      'phase-loop-seat-*' "$unit_prefix*")"; then
    fail "could not list leftover user units"
    return 1
  fi
  units="$(printf '%s\n' "$listing" | awk 'NF {print $1}')"
  for unit in $units; do
    note "stopping leftover unit $unit"
    if ! timeout 30 systemctl --user stop "$unit"; then
      fail "could not stop $unit"
      rc=1
    fi
  done
  return "$rc"
}

unmount_scratch() {
  local target=$1 attempt
  for attempt in 1 2 3 4; do
    if sudo umount "$target"; then
      return 0
    fi
    [ "$attempt" -lt 4 ] && sleep 2
  done
  local holders="fuser unavailable"
  if command -v fuser >/dev/null 2>&1; then
    holders="$(sudo fuser -vm "$target" 2>&1 || true)"
  fi
  printf '%s\n' "$holders" >"$evidence/teardown-holders.txt"
  fail "$target is still busy after 3 retries; leaving the device attached. Holders: $holders"
  return 1
}

# Every attached loop device with its backing file, one "NAME BACK-FILE" line each.
# Fails when the query fails: an unreadable table is unknown state, never "not attached".
loop_table() {
  losetup --list --noheadings --output NAME,BACK-FILE
}

# The backing file of $1 in table $2, or nothing when $1 is not listed (detached).
table_back() {
  local name back
  while read -r name back; do
    if [ "$name" = "$1" ]; then
      printf '%s' "${back%"${back##*[![:space:]]}"}"
      return 0
    fi
  done <<<"$2"
  return 0
}

# Devices in table $1 whose backing file is $2: attaches whose record line was never written.
table_attached_to() {
  local name back
  [ -n "$2" ] || return 0
  while read -r name back; do
    back="${back%"${back##*[![:space:]]}"}"
    [ -n "$name" ] && [ "$back" = "$2" ] && printf '%s\n' "$name"
  done <<<"$1"
  return 0
}

# Undo whatever the state file records, in reverse order. Safe for every prefix of
# provision's writes, including a directory created without its state file.
teardown_core() {
  local rc=0
  # Units first, even with nothing provisioned: a gate killed between delegate and
  # provision can still leave a unit running.
  stop_units || rc=1
  if [ ! -e "$state_dir" ]; then
    note "nothing provisioned"
    return "$rc"
  fi
  if [ ! -f "$state" ]; then
    rmdir "$state_dir" || { fail "could not remove $state_dir"; return 1; }
    note "removed an empty state directory"
    return "$rc"
  fi
  load_state
  validate_state || return 1
  local mountdir="${st[mountdir]:-}" mount="${st[mount]:-}"
  local loop="${st[loop]:-}" image_rec="${st[image]:-}"
  local target="${mount:-$mountdir}"
  if [ -n "$target" ] && is_mounted "$target"; then
    if ! unmount_scratch "$target"; then
      return 1
    fi
  fi
  # Only a device whose backing file is the recorded image is ever detached. The image
  # is deleted only once a successful query shows no device attached to it, so a failed
  # query or detach keeps the image, the state file and the evidence for another attempt.
  local table devices device back seen=" " attachments_clear=0
  if ! table="$(loop_table)"; then
    fail "could not list attached loop devices; the scratch attachment state is unknown"
    rc=1
  else
    devices="$( [ -n "$loop" ] && printf '%s\n' "$loop"; table_attached_to "$table" "$image_rec")"
    while read -r device; do
      [ -n "$device" ] || continue
      case "$seen" in *" $device "*) continue ;; esac
      seen="$seen$device "
      back="$(table_back "$device" "$table")"
      if [ -z "$back" ]; then
        note "$device is not attached"
      elif [ "$back" = "$image_rec" ]; then
        if ! sudo losetup -d "$device"; then
          fail "could not detach $device"
          rc=1
        fi
      else
        fail "$device is backed by '$back', not '$image_rec'; leaving it attached"
        rc=1
      fi
    done <<<"$devices"
    if [ "$rc" -eq 0 ] && [ -n "$image_rec" ]; then
      if ! table="$(loop_table)"; then
        fail "could not confirm that $image_rec is detached; the scratch attachment state is unknown"
        rc=1
      elif [ -n "$(table_attached_to "$table" "$image_rec")" ]; then
        fail "$image_rec is still attached after detach: $(table_attached_to "$table" "$image_rec" | tr '\n' ' ')"
        rc=1
      else
        attachments_clear=1
      fi
    elif [ "$rc" -eq 0 ]; then
      attachments_clear=1
    fi
  fi
  if [ -n "$mountdir" ] && [ -d "$mountdir" ]; then
    rmdir "$mountdir" || { fail "could not remove $mountdir"; rc=1; }
  fi
  if [ -n "$image_rec" ] && [ "$attachments_clear" = 1 ]; then
    rm -f "$image_rec" || { fail "could not remove $image_rec"; rc=1; }
  fi
  if [ "$rc" -eq 0 ]; then
    rm -f "$state"
    rmdir "$state_dir" || { fail "could not remove $state_dir"; rc=1; }
  fi
  if [ "$rc" -eq 0 ]; then
    note "teardown complete"
  else
    note "teardown incomplete; $state and the recorded image are kept"
  fi
  return "$rc"
}

cmd_teardown() {
  teardown_core
}

[ -n "$subcommand" ] || usage
shift
ensure_evidence
case "$subcommand" in
  context) cmd_context "$@" ;;
  delegate) cmd_delegate ;;
  provision) cmd_provision ;;
  run) cmd_run "$@" ;;
  majmin) cmd_majmin ;;
  mountpoint) cmd_mountpoint ;;
  teardown) cmd_teardown ;;
  *) usage ;;
esac
