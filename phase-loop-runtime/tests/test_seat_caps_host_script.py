"""ci/seat-caps-host.sh lifecycle, against fake host commands (agent-harness#1993).

No privilege and no real loop device: every host command the script uses (sudo, losetup,
mount, systemctl, ...) is a small fake on PATH that records its calls, and absolute host
paths sit under CI_HOST_ROOT. The real provisioning runs only on hosted runners. These
checks cover what can be proven without them: rollback from every partial provision,
teardown from a fresh step environment, refusal to force a busy unmount or detach a
device the job does not own, and the run handoff.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap

import pytest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "ci" / "seat-caps-host.sh"
UID = os.getuid()

pytestmark = [
    pytest.mark.skipif(not SCRIPT.is_file(), reason="the host script is repository source"),
    pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash"),
]

FAKES = {
    "sudo": r'''
[ "$1" = -n ] && shift
exec "$@"
''',
    "losetup": r'''
loops="$FAKE_STATE/loops"; mkdir -p "$loops"
# FAKE_LOSETUP_QUERY_FAIL: "all" fails every query; "after1" fails every query after the first.
query_fails() {
  case "${FAKE_LOSETUP_QUERY_FAIL:-}" in
    all) return 0 ;;
    after1)
      n=$(cat "$FAKE_STATE/queries" 2>/dev/null || echo 0); n=$((n + 1))
      echo "$n" > "$FAKE_STATE/queries"; [ "$n" -gt 1 ] ;;
    *) return 1 ;;
  esac
}
case "$*" in
  "--find --show "*)
    [ -n "${FAKE_LOSETUP_ATTACH_FAIL:-}" ] && exit 1
    img="$3"; echo "$img" > "$loops/loop7"; echo /dev/loop7 ;;
  "--list --noheadings --output NAME,BACK-FILE")
    query_fails && { echo "losetup: cannot list devices" >&2; exit 1; }
    for f in "$loops"/*; do [ -f "$f" ] && printf '/dev/%s %s  \n' "$(basename "$f")" "$(cat "$f")"; done
    exit 0 ;;
  "-nO BACK-FILE "*) query_fails && exit 1; f="$loops/$(basename "$3")"; [ -f "$f" ] || exit 1; cat "$f" ;;
  "-nO NAME -j "*) query_fails && exit 1; for f in "$loops"/*; do [ -f "$f" ] && [ "$(cat "$f")" = "$4" ] && echo "/dev/$(basename "$f")"; done; exit 0 ;;
  "-d "*)
    [ -n "${FAKE_LOSETUP_DETACH_FAIL:-}" ] && { echo "losetup: detach failed" >&2; exit 1; }
    [ -n "${FAKE_LOSETUP_DETACH_NOOP:-}" ] && exit 0
    rm -f "$loops/$(basename "$2")" ;;
  "--json --list "*) echo '{}' ;;
  *) echo "unexpected losetup $*" >&2; exit 99 ;;
esac
''',
    "lsblk": r'''
for last; do :; done
echo " 7:${last#/dev/loop}"
''',
    "mkfs.ext4": "exit 0\n",
    "truncate": r'''
: > "$3"
''',
    "chown": "exit 0\n",
    "mount": r'''
mkdir -p "$FAKE_STATE/mounts"
printf '%s\n' "$1" > "$FAKE_STATE/mounts/$(printf '%s' "$2" | tr / _)"
''',
    "umount": r'''
case " $* " in *" -l "*) exit 99 ;; esac
[ -n "${FAKE_BUSY:-}" ] && { echo "target is busy" >&2; exit 32; }
rm -f "$FAKE_STATE/mounts/$(printf '%s' "$1" | tr / _)"
# What was written below the mount point lived on the unmounted filesystem.
find "$1" -mindepth 1 -delete
''',
    "findmnt": r'''
target=""; mode=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mountpoint) target="$2"; shift 2 ;;
    -no) mode="$2"; shift 2 ;;
    --json) echo '{}'; exit 0 ;;
    *) shift ;;
  esac
done
m="$FAKE_STATE/mounts/$(printf '%s' "$target" | tr / _)"
[ -f "$m" ] || exit 1
[ -n "$mode" ] && echo "$(cat "$m") ${FAKE_FSTYPE:-ext4}"
exit 0
''',
    "df": r'''
echo "Avail"; echo "${FAKE_AVAIL:-99999999999}"
''',
    "systemd-run": r'''
echo "env XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-unset} DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unset}" >> "$FAKE_LOG"
exit "${FAKE_RUN_STATUS:-0}"
''',
    "systemctl": r'''
echo "env XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-unset} DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unset}" >> "$FAKE_LOG"
case "$*" in
  "--user list-units"*) printf '%b' "${FAKE_UNITS:-}" ;;
esac
exit 0
''',
    "loginctl": "exit 0\n",
    "sleep": "exit 0\n",
    "fuser": "echo 'mnt: 1234 python'\n",
}


@pytest.fixture
def world(tmp_path):
    # A short root: the fake bus is a real Unix socket, whose path length is limited.
    root = Path(tempfile.mkdtemp(prefix="sch-", dir="/tmp" if os.path.isdir("/tmp") else None))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    for name, body in FAKES.items():
        path = bin_dir / name
        path.write_text(
            "#!/bin/sh\n"
            f'echo "{name} $*" >> "$FAKE_LOG"\n'
            f'case " ${{FAKE_FAIL:-}} " in *" {name} "*) exit 1 ;; esac\n' + body)
        path.chmod(0o755)
    (root / "dev").mkdir()
    (root / "dev" / "loop-control").touch()
    manager = root / "sys/fs/cgroup/user.slice" / f"user-{UID}.slice" / f"user@{UID}.service"
    manager.mkdir(parents=True)
    (manager / "cgroup.controllers").write_text("cpuset cpu io memory pids\n")
    runner_temp = tmp_path / "rt"
    runner_temp.mkdir()
    state = tmp_path / "fake-state"
    state.mkdir()
    sockets = []

    def bus(present=True):
        path = root / "run" / "user" / str(UID) / "bus"
        if present and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(path))
            sockets.append(sock)
        elif not present and path.exists():
            path.unlink()

    def run(*args, env=None, clean=False, check=None):
        base = {"PATH": f"{bin_dir}:/usr/bin:/bin", "RUNNER_TEMP": str(runner_temp),
                "HOME": str(tmp_path), "CI_HOST_ROOT": str(root), "FAKE_LOG": str(log),
                "FAKE_STATE": str(state)}
        if not clean:
            base.update({"XDG_RUNTIME_DIR": "/nonexistent", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/x"})
        base.update(env or {})
        done = subprocess.run(["bash", str(SCRIPT), *args], env=base, capture_output=True, text=True,
                              timeout=60)
        if check is not None:
            assert done.returncode == check, done.stderr
        return done

    ns = type("World", (), {})()
    ns.root, ns.run, ns.bus, ns.log, ns.state = root, run, bus, log, state
    ns.runner_temp = runner_temp
    ns.bin = bin_dir
    ns.state_dir = runner_temp / "seat-caps"
    ns.mnt = ns.state_dir / "mnt"
    ns.image = ns.state_dir / "scratch.img"
    ns.evidence = runner_temp / "seat-caps-evidence"
    ns.manager = manager
    yield ns
    for sock in sockets:
        sock.close()
    shutil.rmtree(root, ignore_errors=True)


def _calls(world):
    return world.log.read_text().splitlines() if world.log.exists() else []


def _loops(world):
    loops = world.state / "loops"
    return sorted(p.name for p in loops.iterdir()) if loops.is_dir() else []


def _mounts(world):
    mounts = world.state / "mounts"
    return sorted(p.name for p in mounts.iterdir()) if mounts.is_dir() else []


def _assert_clean(world):
    assert not world.state_dir.exists()
    assert _loops(world) == [] and _mounts(world) == []


def _provision(world):
    world.bus()
    world.run("delegate", check=0)
    world.run("provision", check=0)


# --- delegate --------------------------------------------------------------------------

def test_delegate_writes_the_dropin_restarts_the_manager_and_checks_controllers(world):
    world.bus()
    world.run("delegate", check=0)
    dropin = world.root / "etc/systemd/system/user@.service.d/delegate.conf"
    assert dropin.read_text() == "[Service]\nDelegate=cpu cpuset io memory pids\n"
    calls = _calls(world)
    assert "systemctl daemon-reload" in calls and f"systemctl restart user@{UID}.service" in calls
    assert any(call.startswith("loginctl enable-linger ") for call in calls)


def test_delegate_fails_loudly_when_the_bus_never_appears(world):
    done = world.run("delegate", check=1)
    assert "::error::the user manager bus did not appear" in done.stderr
    assert "error: the user manager bus did not appear" in (world.evidence / "host.log").read_text()


def test_delegate_fails_when_a_controller_is_missing(world):
    world.bus()
    (world.manager / "cgroup.controllers").write_text("cpu memory pids\n")
    done = world.run("delegate", check=1)
    assert "does not delegate io" in done.stderr


# --- provision -------------------------------------------------------------------------

def test_provision_records_every_step_and_leaves_the_device_mounted(world):
    _provision(world)
    lines = (world.state_dir / "state").read_text().splitlines()
    assert [line.split("=", 1)[0] for line in lines] == [
        "uid", "gid", "image", "loop", "majmin", "mountdir", "mount", "provisioned"]
    assert stat.S_IMODE((world.state_dir / "state").stat().st_mode) == 0o600
    assert stat.S_IMODE(world.state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(world.evidence.stat().st_mode) == 0o700
    assert _loops(world) == ["loop7"] and len(_mounts(world)) == 1
    assert world.run("majmin", check=0).stdout == "7:7\n"
    assert world.run("mountpoint", check=0).stdout == f"{world.mnt}\n"
    assert (world.evidence / "kernel.txt").is_file()
    assert "sudo losetup --find --show " + str(world.image) in _calls(world)


@pytest.mark.parametrize("env", [
    {"FAKE_FAIL": "truncate"}, {"FAKE_LOSETUP_ATTACH_FAIL": "1"}, {"FAKE_FAIL": "lsblk"},
    {"FAKE_FAIL": "mkfs.ext4"}, {"FAKE_FAIL": "mount"}, {"FAKE_FAIL": "chown"},
    {"FAKE_FSTYPE": "xfs"},
], ids=lambda env: next(iter(env.values())))
def test_a_failure_at_any_provision_step_rolls_back_every_recorded_item(world, env):
    world.bus()
    done = world.run("provision", env=env)
    assert done.returncode != 0
    assert "rolling back the recorded state" in done.stderr
    _assert_clean(world)
    log = (world.evidence / "host.log").read_text()
    assert "provision failed with status" in log and "teardown complete" in log
    assert not any(" -D" in call or "umount -l" in call for call in _calls(world))


def test_rollback_that_cannot_query_loops_keeps_its_state_and_fails(world):
    world.bus()
    done = world.run("provision", env={"FAKE_FAIL": "losetup"})
    assert done.returncode == 1
    assert "rollback also failed" in done.stderr
    assert "attachment state is unknown" in done.stderr
    assert (world.state_dir / "state").is_file() and world.image.exists()
    world.run("teardown", clean=True, check=0)
    _assert_clean(world)


def test_a_signal_during_provision_rolls_back(world):
    world.bus()
    hold = world.root / "hold"
    # mkfs runs for about 2 s; the script is signalled meanwhile and must then roll back.
    bin_dir = Path(world.log).parent / "bin"
    (bin_dir / "mkfs.ext4").write_text(
        f'#!/bin/sh\necho "mkfs.ext4 $*" >> "$FAKE_LOG"\ntouch {hold}\n'
        'i=0; while [ $i -lt 40 ]; do i=$((i+1)); /bin/sleep 0.05; done\n')
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "RUNNER_TEMP": str(world.runner_temp),
           "HOME": str(world.runner_temp), "CI_HOST_ROOT": str(world.root),
           "FAKE_LOG": str(world.log), "FAKE_STATE": str(world.state)}
    process = subprocess.Popen(["bash", str(SCRIPT), "provision"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(200):
        if hold.exists():
            break
        subprocess.run(["/bin/sleep", "0.05"], check=True)
    process.terminate()
    _out, err = process.communicate(timeout=30)
    assert process.returncode == 143, err
    _assert_clean(world)


def test_preflight_failure_keeps_its_evidence_and_creates_no_state(world):
    world.bus()
    (world.root / "dev" / "loop-control").unlink()
    done = world.run("provision", check=1)
    assert "::error::/dev/loop-control is absent" in done.stderr
    assert "error: /dev/loop-control is absent" in (world.evidence / "host.log").read_text()
    assert not world.state_dir.exists()


def test_provision_refuses_low_space_and_existing_state(world):
    world.bus()
    world.run("provision", env={"FAKE_AVAIL": "1024"}, check=1)
    world.state_dir.mkdir()
    done = world.run("provision", check=1)
    assert "already exists" in done.stderr
    assert world.state_dir.is_dir()  # never removed by a refused provision


# --- teardown --------------------------------------------------------------------------

def test_teardown_without_state_is_a_no_op(world):
    done = world.run("teardown", clean=True, check=0)
    assert "nothing provisioned" in done.stderr


def test_teardown_without_state_still_stops_a_leftover_gate_unit(world):
    world.bus()
    units = "ci-seat-caps-run-1-2.service loaded active running y\\n"
    world.run("teardown", clean=True, env={"FAKE_UNITS": units}, check=0)
    assert "systemctl --user stop ci-seat-caps-run-1-2.service" in _calls(world)


def test_teardown_removes_a_state_directory_without_its_file(world):
    world.state_dir.mkdir(mode=0o700)
    world.run("teardown", clean=True, check=0)
    assert not world.state_dir.exists()


def test_teardown_from_a_clean_step_environment_stops_units_and_cleans_up(world):
    _provision(world)
    units = "phase-loop-seat-abc.slice loaded active active x\\nci-seat-caps-run-1-2.service loaded active running y\\n"
    world.log.write_text("")
    world.run("teardown", clean=True, env={"FAKE_UNITS": units}, check=0)
    _assert_clean(world)
    calls = _calls(world)
    assert "systemctl --user stop phase-loop-seat-abc.slice" in calls
    assert "systemctl --user stop ci-seat-caps-run-1-2.service" in calls
    # The manager connection is set by teardown itself, not inherited.
    assert (f"env XDG_RUNTIME_DIR=/run/user/{UID} "
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{UID}/bus") in calls
    assert "teardown complete" in (world.evidence / "host.log").read_text()


def test_teardown_without_a_manager_still_unmounts_and_detaches(world):
    _provision(world)
    world.bus(present=False)
    done = world.run("teardown", clean=True, check=0)
    assert "no user units can be listed or stopped" in done.stderr
    _assert_clean(world)


def test_a_busy_mount_is_never_forced_and_the_device_stays_attached(world):
    _provision(world)
    done = world.run("teardown", env={"FAKE_BUSY": "1"}, check=1)
    assert "still busy after 3 retries" in done.stderr
    assert _loops(world) == ["loop7"] and len(_mounts(world)) == 1
    assert (world.state_dir / "state").is_file()
    assert (world.evidence / "teardown-holders.txt").read_text().startswith("mnt: 1234")
    calls = _calls(world)
    assert sum(call.startswith("umount ") for call in calls) == 4
    assert not any(call.startswith("losetup -d") or " -D" in call or "umount -l" in call
                   for call in calls)


def test_a_device_backed_by_another_file_is_not_detached(world):
    _provision(world)
    (world.state / "loops" / "loop7").write_text("/somewhere/else.img\n")
    done = world.run("teardown", check=1)
    assert "not '" in done.stderr and "leaving it attached" in done.stderr
    assert _loops(world) == ["loop7"]
    assert not any(call.startswith("losetup -d") for call in _calls(world))


def _assert_retained(world):
    """A teardown that could not establish the attachment state keeps what it needs."""
    assert _loops(world) == ["loop7"] or world.image.exists()
    assert world.image.exists(), "the backing image was removed before detach was confirmed"
    assert (world.state_dir / "state").is_file()
    log = (world.evidence / "host.log").read_text()
    assert "teardown incomplete" in log
    assert "teardown complete" not in log


@pytest.mark.parametrize("env", [
    {"FAKE_LOSETUP_QUERY_FAIL": "all"},
    {"FAKE_FAIL": "losetup"},
], ids=["query-fails", "every-losetup-fails"])
def test_a_failed_loop_query_is_unknown_state_never_success(world, env):
    _provision(world)
    done = world.run("teardown", env=env)
    assert done.returncode == 1, done.stderr
    assert "attachment state is unknown" in done.stderr
    assert _loops(world) == ["loop7"]
    _assert_retained(world)
    # A later teardown with a working query finishes the job.
    world.run("teardown", clean=True, check=0)
    _assert_clean(world)


def test_a_failed_detach_keeps_the_image_and_state_for_a_retry(world):
    _provision(world)
    done = world.run("teardown", env={"FAKE_LOSETUP_DETACH_FAIL": "1"})
    assert done.returncode == 1 and "could not detach /dev/loop7" in done.stderr
    assert _loops(world) == ["loop7"]
    _assert_retained(world)
    world.run("teardown", clean=True, check=0)
    _assert_clean(world)


def test_a_detach_that_leaves_the_device_attached_is_caught(world):
    _provision(world)
    done = world.run("teardown", env={"FAKE_LOSETUP_DETACH_NOOP": "1"})
    assert done.returncode == 1 and "is still attached after detach" in done.stderr
    _assert_retained(world)
    world.run("teardown", clean=True, check=0)
    _assert_clean(world)


def test_a_failed_confirmation_query_after_detach_is_unknown_state(world):
    _provision(world)
    (world.state / "queries").unlink(missing_ok=True)
    done = world.run("teardown", env={"FAKE_LOSETUP_QUERY_FAIL": "after1"})
    assert done.returncode == 1, done.stderr
    assert "attachment state is unknown" in done.stderr
    _assert_retained(world)
    world.run("teardown", clean=True, check=0)
    _assert_clean(world)


def _state(world, *lines):
    world.state_dir.mkdir(mode=0o700)
    (world.state_dir / "state").write_text("".join(f"{line}\n" for line in lines))


def test_teardown_finds_an_attach_whose_record_was_never_written(world):
    _state(world, f"uid={UID}", f"gid={os.getgid()}", f"image={world.image}")
    world.image.touch()
    (world.state / "loops").mkdir()
    (world.state / "loops" / "loop7").write_text(f"{world.image}\n")
    world.run("teardown", clean=True, check=0)
    _assert_clean(world)


def test_teardown_unmounts_a_mount_whose_record_was_never_written(world):
    _state(world, f"uid={UID}", f"gid={os.getgid()}", f"image={world.image}", "loop=/dev/loop7",
           "majmin=7:7", f"mountdir={world.mnt}")
    world.image.touch()
    world.mnt.mkdir()
    (world.state / "loops").mkdir()
    (world.state / "loops" / "loop7").write_text(f"{world.image}\n")
    (world.state / "mounts").mkdir()
    (world.state / "mounts" / str(world.mnt).replace("/", "_")).write_text("/dev/loop7\n")
    world.run("teardown", clean=True, check=0)
    _assert_clean(world)


def test_teardown_refuses_a_tampered_state_file(world):
    _state(world, f"uid={UID}", "loop=/dev/sda")
    done = world.run("teardown", check=1)
    assert "unexpected scratch state entry 'loop=/dev/sda'" in done.stderr
    assert not any(call.startswith("losetup") for call in _calls(world))
    assert world.state_dir.exists()


# --- run and context ---------------------------------------------------------------------

def test_run_sets_its_own_manager_environment_and_the_scratch_overrides(world):
    _provision(world)
    world.log.write_text("")
    done = world.run("run", "--", "python", "verify.py", clean=True, env={"FAKE_RUN_STATUS": "7"})
    assert done.returncode == 7
    calls = _calls(world)
    (launch,) = [call for call in calls if call.startswith("systemd-run ")]
    assert launch.startswith("systemd-run --user --pipe --wait --collect --quiet --same-dir "
                             "-p Type=oneshot --unit=ci-seat-caps-run-")
    assert f"-E XDG_RUNTIME_DIR=/run/user/{UID} -E PYTHONDONTWRITEBYTECODE=1" in launch
    assert f"-E PHASE_LOOP_SANDBOX_STAGING_DIR={world.mnt}/sandboxes" in launch
    assert f"-E XDG_CACHE_HOME={world.mnt}/cache" in launch
    assert launch.endswith("-- python verify.py")
    assert (f"env XDG_RUNTIME_DIR=/run/user/{UID} "
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{UID}/bus") in calls


def test_run_refuses_without_a_provisioned_and_mounted_device(world):
    world.bus()
    done = world.run("run", "--", "true", check=1)
    assert "no scratch device is provisioned" in done.stderr
    world.run("provision", check=0)
    for marker in (world.state / "mounts").iterdir():
        marker.unlink()
    done = world.run("run", "--", "true", check=1)
    assert "is not the provisioned /dev/loop7 ext4 filesystem" in done.stderr


def test_baseline_run_needs_no_provision_and_adds_no_scratch_paths(world):
    world.bus()
    world.run("run", "--baseline", "--", "true", check=0)
    (launch,) = [call for call in _calls(world) if call.startswith("systemd-run ")]
    assert "PHASE_LOOP_SANDBOX_STAGING_DIR" not in launch and "XDG_CACHE_HOME" not in launch


def test_run_refuses_without_a_bus(world):
    done = world.run("run", "--baseline", "--", "true", check=1)
    assert "no user manager bus" in done.stderr


def test_context_never_fails_the_step(world):
    done = world.run("context", "--", "false", check=0)
    assert "::warning::host-context diagnostic exited 1" in done.stderr
    world.run("context", "--", "true", check=0)


# --- the scratch binding as the conformance suite sees it ------------------------------

BINDING = REPO / "phase-loop-runtime" / "tests" / "test_seat_caps_scratch_binding.py"


def _exec_systemd_run(world):
    """A systemd-run that really runs CMD, in a clean environment holding only the -E
    values, as a user-manager unit does."""
    (world.bin / "systemd-run").write_text(f"#!{sys.executable}\n" + textwrap.dedent("""
        import os, sys
        args, env, i = sys.argv[1:], {}, 0
        while args[i] != "--":
            if args[i] == "-E":
                key, sep, value = args[i + 1].partition("=")
                if sep:
                    env[key] = value
                elif key in os.environ:  # "-E NAME": the value of systemd-run's own NAME
                    env[key] = os.environ[key]
                i += 2
            else:
                i += 1
        os.execvpe(args[i + 1], args[i + 1:], env)
    """))


def _binding_run(world):
    _provision(world)
    _exec_systemd_run(world)
    runtime = REPO / "phase-loop-runtime"
    return world.run(
        "run", "--", "env", "CI_SCRATCH_DEVICE=7:7", f"CI_SCRATCH_STUB_ROOT={world.mnt}",
        f"PYTHONPATH={runtime / 'src'}{os.pathsep}{runtime / 'tests'}",
        sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rs", str(BINDING),
        clean=True)


def test_the_conformance_session_resolves_its_scratch_on_the_device(world):
    """agent-harness#1993, AWS: the suite's isolation moves both automatic paths below
    pytest's tmp_path. Through the real run wrapper they must still be on the device,
    which needs TMPDIR on it; with the two overrides alone they land on the host's /tmp."""
    done = _binding_run(world)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert "1 passed" in done.stdout


def test_run_points_tmpdir_at_the_provisioned_temporary_directory(world):
    _provision(world)
    assert stat.S_IMODE((world.mnt / "tmp").stat().st_mode) == 0o700
    world.log.write_text("")
    world.run("run", "--", "true", check=0)
    (launch,) = [call for call in _calls(world) if call.startswith("systemd-run ")]
    assert f"-E TMPDIR={world.mnt}/tmp" in launch
    (world.mnt / "tmp").rmdir()
    done = world.run("run", "--", "true", check=1)
    assert "is not the provisioned temporary directory" in done.stderr



# --- the verifier's API token: by name only, to the one unit that asks for it ---------

SECRET = "ghs_fake-token-value-0123456789"


def _no_secret_anywhere(world, done):
    assert SECRET not in done.stderr, "the token reached the script's own output"
    assert all(SECRET not in call for call in _calls(world)), "the token reached the logged argv"
    for path in world.evidence.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="replace"), path


def test_pass_env_hands_the_token_by_name_never_in_argv_or_evidence(world):
    _provision(world)
    world.log.write_text("")
    done = world.run("run", "--pass-env", "GITHUB_TOKEN", "--", "true",
                     env={"GITHUB_TOKEN": SECRET}, check=0)
    (launch,) = [call for call in _calls(world) if call.startswith("systemd-run ")]
    assert " -E GITHUB_TOKEN " in f"{launch} "
    _no_secret_anywhere(world, done)


def test_the_unit_receives_the_token_only_when_asked(world):
    _provision(world)
    _exec_systemd_run(world)
    asked = world.run("run", "--pass-env", "GITHUB_TOKEN", "--", "/usr/bin/printenv", "GITHUB_TOKEN",
                      env={"GITHUB_TOKEN": SECRET}, check=0)
    assert asked.stdout.strip() == SECRET
    _no_secret_anywhere(world, asked)
    unasked = world.run("run", "--", "/usr/bin/printenv", "GITHUB_TOKEN", env={"GITHUB_TOKEN": SECRET})
    assert unasked.returncode != 0 and SECRET not in unasked.stdout


def test_pass_env_skips_an_unset_name_and_refuses_a_malformed_one(world):
    _provision(world)
    world.log.write_text("")
    world.run("run", "--pass-env", "GITHUB_TOKEN", "--", "true", check=0)
    (launch,) = [call for call in _calls(world) if call.startswith("systemd-run ")]
    assert "GITHUB_TOKEN" not in launch
    assert world.run("run", "--pass-env", "lower=x", "--", "true").returncode == 2
    assert world.run("run", "--pass-env").returncode == 2
