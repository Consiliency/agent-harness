"""agent-harness#1098 item 2: every seat runs as the operator's REAL uid, locked down.

Every seat runs inside ``unshare --net --mount --map-root-user``, so every host account was
uid 0 there, and the provider CLIs key scratch by uid -- ``/tmp/claude-0``,
``/tmp/codex-daemon-0``, ``$TMPDIR/codex-bwrap-synthetic-mount-targets-0``. On a shared host
the first account to run a board owned those paths and every other account's seats refused
them: "Directory /tmp/claude-0 is owned by uid 65534, expected 0".

A nested user namespace now maps the operator's own uid and gid, so each account's names
are its own again, and the capability lock-down runs AFTER that switch. Nothing on the host
filesystem is hidden, so there is nothing to predict. Before every launch, a probe through
the launch's own prefix must show the operator's identity and the expected capability
lines, or the launch is refused -- in every egress mode.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import textwrap
import threading

import pytest

from phase_loop_runtime import panel_invoker, sandbox_egress, sandbox_retention


needs_egress = pytest.mark.skipif(
    not sandbox_egress.egress_isolation_available(),
    reason="this host cannot enforce egress isolation (no user namespaces or slirp4netns)",
)

UID, GID = str(os.getuid()), str(os.getgid())
HOLDER = ("nsenter", "--net", "--mount", "-t", "1", "-U", "--preserve-credentials",
          "setpriv", "--bounding-set=-all", "--inh-caps=-all", "--")


@contextmanager
def _egress(prefix):
    token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
    try:
        yield
    finally:
        panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)


def _monitor(tmp_path):
    return panel_invoker._ReviewMonitor(tmp_path / "m.json", "t", 0, threading.Event())


# --- construction: the switch, and its ORDER ------------------------------------------------


def test_the_switch_maps_the_operator_then_locks_down():
    assert panel_invoker._seat_identity_switch() == [
        "/usr/bin/unshare", "--user", f"--map-user={UID}", f"--map-group={GID}", "--keep-caps",
        "/usr/bin/setpriv", "--bounding-set=-all", "--inh-caps=-all", "--ambient-caps=-all", "--",
    ]
    kept = panel_invoker._seat_identity_switch(("setfcap",))
    assert "--bounding-set=-all,+setfcap" in kept and kept[-3:] == ["--pdeathsig", "SIGKILL", "--"]
    with pytest.raises(ValueError):
        panel_invoker._seat_identity_switch(("net_admin",))


_USERNS_ENTRY = ("-U", "--user", "--unshare-user")


@pytest.mark.parametrize("egress", ["empty", "holder"])
@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("caps", [(), ("setfcap",)])
def test_every_composed_prefix_ends_in_the_lock_down_or_refuses(tmp_path, egress, owned, caps):
    """The ORDER is load-bearing: a user-namespace switch resets the lock-down, so the
    bounding-set drop must follow EVERY user-namespace entry, and every prefix that enters
    a namespace or an owner is probed. The single empty prefix is main's unsandboxed host
    launch (no namespace, no owner), unchanged."""
    owner = _monitor(tmp_path).owned_command(()) if owned else ()
    with _egress(HOLDER if egress == "holder" else ()):
        if egress == "empty" and owned and caps:
            # The codex supervisor route outside the namespace: refused, as on main.
            with pytest.raises(sandbox_egress.SeatIdentityUnverified):
                panel_invoker._compose_launch_prefix(str(tmp_path), owner, caps)
            return
        prefix = panel_invoker._compose_launch_prefix(str(tmp_path), owner, caps)
    if egress == "empty" and not owned:
        assert prefix == [] and not panel_invoker._probes_seat(prefix, owner)
        return
    assert panel_invoker._probes_seat(prefix, owner), "a composed prefix escaped the probe"
    last_entry = max(i for i, arg in enumerate(prefix) if arg in _USERNS_ENTRY)
    # A lock-down: setpriv's bounding-set drop, or bubblewrap's own `--cap-drop ALL`
    # (which bubblewrap applies inside the user namespace it creates).
    drops = [i for i, arg in enumerate(prefix)
             if arg.startswith("--bounding-set=") or prefix[i:i + 2] == ["--cap-drop", "ALL"]]
    assert drops and drops[-1] > last_entry, f"no lock-down after the last user-namespace entry: {prefix}"
    if owned and not caps:
        assert "/usr/bin/setpriv" not in prefix and "--user" not in prefix, "bubblewrap replaces the switch"
    else:
        assert prefix[drops[-1]] == "--bounding-set=-all" + ("".join(f",+{c}" for c in caps))
    lock_end = prefix.index("--", drops[-1])
    tail = prefix[lock_end + 1:]
    assert tail in ([], ["/usr/bin/env", f"--chdir={tmp_path}", "--"]), tail
    assert prefix[lock_end - 1] != "--", "nothing may run between the lock-down and the provider"
    if egress == "holder" and not (owned and not caps):
        assert "--bounding-set=-all" not in prefix[:prefix.index("--user")], "a lock-down before the switch"
    if owned and caps:
        head = prefix[:prefix.index("--user")]
        assert head[head.index("setpriv"):head.index("setpriv") + 4] == [
            "setpriv", "--pdeathsig", "SIGKILL", "--"], "the PID supervisor must drop nothing itself"


def test_the_switch_position_does_not_depend_on_a_chdir(tmp_path):
    owner = _monitor(tmp_path).owned_command(())
    with _egress(HOLDER):
        prefix = panel_invoker._compose_launch_prefix(None, owner, ())
    assert prefix.index("--net") < prefix.index("/usr/bin/bwrap") < prefix.index("/usr/bin/env")
    assert prefix[-1] == "--" and prefix[-2].startswith("--chdir=")


# --- the probe runs through the launch's OWN prefix -----------------------------------------


def test_the_probe_runs_through_the_exact_launch_prefix(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        return subprocess.CompletedProcess(
            argv, 0, "\n".join(panel_invoker._expected_seat_identity(argv, ("setfcap",))) + "\n", "")

    class FakePopen:
        def __init__(self, argv, **kwargs):
            seen.append(list(argv))

    monkeypatch.setattr(panel_invoker.subprocess, "run", fake_run)
    monkeypatch.setattr(panel_invoker.subprocess, "Popen", FakePopen)
    owner = _monitor(tmp_path).owned_command(())
    with _egress(HOLDER):
        panel_invoker.launch_provider(["codex", "exec"], process_owner=owner,
                                      retain_caps=("setfcap",), cwd=str(tmp_path))
    probe, launch = seen
    assert launch[-2:] == ["codex", "exec"]
    assert probe[:len(launch) - 2] == launch[:-2], "the probe used a different prefix"
    assert probe[len(launch) - 2:len(launch)] == ["/bin/sh", "-c"]


def test_only_the_gemini_owner_probes_without_its_single_use_descriptors(tmp_path, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(panel_invoker.subprocess, "run", lambda argv, **k: (
        seen.append(list(argv)) or subprocess.CompletedProcess(
            argv, 0, "\n".join(panel_invoker._expected_seat_identity(argv)) + "\n", "")))
    monkeypatch.setattr(panel_invoker.subprocess, "Popen", lambda argv, **k: seen.append(list(argv)))
    monitor = _monitor(tmp_path)
    fd_args = ["--info-fd", "7", "--block-fd", "8"]
    with_fds = monitor.owned_command(())
    with_fds[with_fds.index("--"):with_fds.index("--")] = fd_args
    with _egress(HOLDER):
        panel_invoker.launch_provider(["agy"], process_owner=with_fds,
                                      probe_owner=monitor.owned_command(()), cwd=str(tmp_path))
    probe, launch = seen
    assert [a for a in launch[:-1] if a not in fd_args] == probe[:len(launch) - 1 - len(fd_args)]


# --- real namespace: every route is the operator, locked down -------------------------------

_STATUS = "id -u; id -g; grep -E '^(CapPrm|CapEff|CapBnd|NoNewPrivs):' /proc/self/status"


@needs_egress
def test_every_route_runs_the_seat_as_the_operator(tmp_path):
    monitor = _monitor(tmp_path)
    routes = {
        "plain": ({}, "0000000000000000", "0"),
        "codex": ({"process_owner": monitor.owned_command(()), "retain_caps": ("setfcap",)},
                  "0000000080000000", "0"),
        "owned": ({"process_owner": monitor.owned_command(())}, "0000000000000000", "1"),
    }
    with sandbox_egress.isolated_network(timeout_s=None) as prefix, _egress(prefix):
        for route, (kwargs, bounding, nnp) in routes.items():
            proc = panel_invoker.launch_provider(
                ["/bin/sh", "-c", _STATUS], cwd=str(tmp_path),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
            out = proc.communicate(timeout=60)[0].decode().splitlines()
            assert out == [UID, GID, "CapPrm:\t0000000000000000", "CapEff:\t0000000000000000",
                           f"CapBnd:\t{bounding}", f"NoNewPrivs:\t{nnp}"], (route, out)
        # run_provider (the no-owner waited form) goes through the same switch.
        done = panel_invoker.run_provider(["/bin/sh", "-c", "id -u; stat -c %u /etc/passwd"],
                                          cwd=str(tmp_path), capture_output=True, text=True)
        # Root-owned host files show as the overflow uid, exactly as in the holder on main.
        assert done.stdout.split() == [UID, "65534"]


def _broken_switch(kind):
    good = panel_invoker._seat_identity_switch

    def switch(retain_caps=()):
        argv = good(retain_caps)
        if kind == "uid":       # no identity switch at all: the seat stays uid 0
            return argv[argv.index("/usr/bin/setpriv"):]
        if kind == "caps":      # a widened bounding set
            return [a if not a.startswith("--bounding-set=") else a + ",+net_raw" for a in argv]
        return argv
    return switch


@needs_egress
@pytest.mark.parametrize("mismatch", ["uid", "owner", "caps"])
def test_a_seat_identity_mismatch_refuses_even_under_the_optional_opt_out(
        tmp_path, monkeypatch, mismatch):
    monkeypatch.setenv("PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", "1")
    if mismatch == "owner":
        # A file the operator does NOT own (root's): the seat must not see it as its own.
        @contextmanager
        def foreign_marker():
            yield "/etc/hostname"
        monkeypatch.setattr(panel_invoker, "_seat_probe_marker", foreign_marker)
    else:
        monkeypatch.setattr(panel_invoker, "_seat_identity_switch", _broken_switch(mismatch))
    ran = tmp_path / "provider-ran"
    with sandbox_egress.isolated_network(timeout_s=None) as prefix, _egress(prefix):
        assert prefix, "the namespace must be up for this case"
        with pytest.raises(sandbox_egress.SeatIdentityUnverified):
            panel_invoker.launch_provider(["/bin/sh", "-c", f"touch {ran}"], cwd=str(tmp_path))
    assert not ran.exists()


def test_an_owned_codex_launch_without_a_namespace_is_refused_live(tmp_path):
    ran = tmp_path / "provider-ran"
    with _egress(()):
        with pytest.raises(sandbox_egress.SeatIdentityUnverified):
            panel_invoker.launch_provider(
                ["/bin/sh", "-c", f"touch {ran}"], cwd=str(tmp_path),
                process_owner=_monitor(tmp_path).owned_command(()), retain_caps=("setfcap",))
    assert not ran.exists()


@pytest.mark.skipif(not os.path.exists("/usr/bin/bwrap"), reason="bubblewrap is not installed")
def test_an_owned_bwrap_launch_without_a_namespace_is_switched_and_probed(tmp_path):
    with _egress(()):
        proc = panel_invoker.launch_provider(
            ["/bin/sh", "-c", _STATUS], cwd=str(tmp_path),
            process_owner=_monitor(tmp_path).owned_command(()),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate(timeout=60)[0].decode().splitlines()
    assert out == [UID, GID, "CapPrm:\t0000000000000000", "CapEff:\t0000000000000000",
                   "CapBnd:\t0000000000000000", "NoNewPrivs:\t1"], out


# Runs in a CHILD process so the caller's state can be varied: `setpriv --no-new-privs`
# gives it an inherited no-new-privs, and an outer user namespace makes it uid 0.
_STATE_DRIVER = textwrap.dedent("""
    import subprocess, sys, tempfile, threading
    from pathlib import Path
    from phase_loop_runtime import panel_invoker, sandbox_egress
    base = Path(tempfile.mkdtemp())
    monitor = panel_invoker._ReviewMonitor(base / "m.json", "t", 0, threading.Event())
    routes = {"plain": {}, "codex": {"process_owner": monitor.owned_command(()), "retain_caps": ("setfcap",)},
              "owned": {"process_owner": monitor.owned_command(())}}
    status = "id -u; grep -E '^(CapPrm|CapEff|CapBnd|NoNewPrivs):' /proc/self/status"
    with sandbox_egress.isolated_network(timeout_s=None) as prefix:
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
        try:
            for name, kwargs in routes.items():
                try:
                    proc = panel_invoker.launch_provider(["/bin/sh", "-c", status], cwd=str(base),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
                    print(name, "|".join(proc.communicate(timeout=60)[0].decode().split()))
                except sandbox_egress.SeatIdentityUnverified as exc:
                    print(name, "REFUSED", exc)
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
""")


def _run_state_driver(*wrapper: str) -> dict[str, str]:
    src = str(Path(panel_invoker.__file__).resolve().parents[1])
    done = subprocess.run([*wrapper, sys.executable, "-c", _STATE_DRIVER], capture_output=True,
                          text=True, timeout=240,
                          env={**os.environ, "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")})
    assert done.returncode == 0, done.stdout + done.stderr
    return dict(line.split(" ", 1) for line in done.stdout.splitlines())


@needs_egress
def test_an_inherited_no_new_privs_is_expected_not_refused():
    seen = _run_state_driver("setpriv", "--no-new-privs", "--")
    for route, bounding in (("plain", "0000000000000000"), ("codex", "0000000080000000"),
                            ("owned", "0000000000000000")):
        assert seen[route] == (f"{UID}|CapPrm:|0000000000000000|CapEff:|0000000000000000|"
                               f"CapBnd:|{bounding}|NoNewPrivs:|1"), (route, seen[route])


@needs_egress
def test_a_uid_0_operator_gets_exactly_main_s_root_seat_state():
    """SIMULATED root: the operator is uid 0 of an outer user namespace (really the host
    account running the test) -- the same exec semantics a real root operator sees."""
    seen = _run_state_driver("unshare", "--user", "--map-root-user", "--mount")
    assert seen["codex"] == ("0|CapPrm:|0000000080000000|CapEff:|0000000080000000|"
                             "CapBnd:|0000000080000000|NoNewPrivs:|0"), seen["codex"]
    assert seen["plain"] == ("0|CapPrm:|0000000000000000|CapEff:|0000000000000000|"
                             "CapBnd:|0000000000000000|NoNewPrivs:|0"), seen["plain"]
    assert seen["owned"] == ("0|CapPrm:|0000000000000000|CapEff:|0000000000000000|"
                             "CapBnd:|0000000000000000|NoNewPrivs:|1"), seen["owned"]


def test_a_leg_without_a_namespace_is_typed_seat_identity_unavailable(tmp_path):
    from phase_loop_runtime import sandbox_policy
    choice = sandbox_policy.select_sandbox_root(
        configured=None, fallback=tmp_path, floor_bytes=0, probe_timeout_s=1.0)
    for flag, typed in ((False, "unavailable"), (True, "host_uid")):
        token = panel_invoker._record_sandbox_facts(
            choice, sandbox_egress.enforcement_report(False), staged_at=tmp_path / "t",
            seat_identity=flag)
        try:
            assert panel_invoker._sandbox_evidence()["sandbox_seat_identity"] == typed
        finally:
            panel_invoker._SANDBOX_ROUND_FACTS.reset(token)


# --- the falsifier: a second account's view ------------------------------------------------

# The CLIs' own checks, reproduced: each scratch dir is keyed by uid and is refused when
# another uid owns it. `claude-*` and codex's bwrap synthetic-mount dir follow TMPDIR;
# `codex-daemon-*` is a literal /tmp path.
SEAT = textwrap.dedent("""
    import os, sys, tempfile
    uid = os.getuid()
    for name, base in ((f"claude-{uid}", tempfile.gettempdir()),
                       (f"codex-bwrap-synthetic-mount-targets-{uid}", tempfile.gettempdir()),
                       (f"codex-daemon-{uid}", "/tmp")):
        path = os.path.join(base, name)
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        owner = os.stat(path).st_uid
        if owner != uid:
            print(f"Directory {path} is owned by uid {owner}, expected {uid}")
            sys.exit(3)
    print("SEAT-OK")
""")

DRIVER = textwrap.dedent("""
    import os, subprocess, sys, tempfile, threading
    from pathlib import Path
    from phase_loop_runtime import panel_invoker, sandbox_egress
    if sys.argv[1] == "main":
        # main's seat identity: the holder's root, locked down, and no probe.
        panel_invoker._seat_identity_switch = lambda caps=(): [
            "/usr/bin/setpriv", "--bounding-set=-all" + "".join(",+" + c for c in caps),
            "--inh-caps=-all", "--"]
        panel_invoker._require_seat_identity = lambda *a, **k: None
    base = Path(tempfile.mkdtemp(prefix="pl-panel-"))
    route = {"plain": {}, "codex": {
        "process_owner": panel_invoker._ReviewMonitor(base / "m.json", "t", 0,
                                                      threading.Event()).owned_command(()),
        "retain_caps": ("setfcap",)}}[sys.argv[2]]
    with sandbox_egress.isolated_network(timeout_s=None) as prefix:
        print("NAMESPACE-UP", file=sys.stderr, flush=True)
        token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
        try:
            proc = panel_invoker.launch_provider(
                [sys.executable, "-c", sys.argv[3]], cwd=str(base),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **route)
            out, _ = proc.communicate(timeout=60)
        finally:
            panel_invoker._EGRESS_LAUNCH_PREFIX.reset(token)
    print(out.decode().strip())
    sys.exit(proc.returncode)
""")

# The simulated second account is uid 1000 in its own namespace; everything below already
# exists, owned by someone else (a root-owned host dir, so uid 65534 in there). Scratch
# tmpfs over /tmp and /var/tmp: the host's are never touched.
ACCOUNT = 1000
_FOREIGN_UID0 = ("/tmp/claude-0", "/tmp/codex-daemon-0", "/tmp/codex-bwrap-synthetic-mount-targets-0",
                 "/tmp/shared/claude-0", "/tmp/shared/codex-bwrap-synthetic-mount-targets-0",
                 "/var/tmp/shared/claude-0", "/var/tmp/shared/codex-bwrap-synthetic-mount-targets-0")
_SCENARIOS = {
    "default": ({}, _FOREIGN_UID0),
    "shared-tmpdir": ({"TMPDIR": "/tmp/shared"}, _FOREIGN_UID0),
    "shared-tmpdir-outside-tmp": ({"TMPDIR": "/var/tmp/shared"}, _FOREIGN_UID0),
    # A foreign dir under the account's OWN uid still breaks it -- as on main. We claim
    # separation between accounts, not protection from a hostile pre-creator.
    "foreign-own-uid": ({}, (*_FOREIGN_UID0, f"/tmp/claude-{ACCOUNT}")),
}


def _run_as_a_second_account(mode: str, route: str, scenario: str) -> subprocess.CompletedProcess[str]:
    src = str(Path(panel_invoker.__file__).resolve().parents[1])
    env, foreign = _SCENARIOS[scenario]
    binds = "".join(f"mkdir -p {d}; mount --bind /usr/share {d}; " for d in foreign)
    outer = (
        "set -e; mount -t tmpfs -o mode=1777 t1098 /tmp; mount -t tmpfs -o mode=1777 t1098 /var/tmp; "
        f"mkdir -p /tmp/shared /var/tmp/shared; {binds}echo OUTER-READY >&2; "
        f'exec unshare --user --map-user={ACCOUNT} --map-group={ACCOUNT} "$0" -c "$1" "$2" "$3" "$4"'
    )
    return subprocess.run(
        ["unshare", "--user", "--map-root-user", "--mount", "bash", "-c", outer,
         sys.executable, DRIVER, mode, route, SEAT],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, **env, "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")},
    )


@needs_egress
@pytest.mark.parametrize("route", ["plain", "codex"])
@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_a_second_account_s_seat_is_not_broken_by_another_account_s_scratch(route, scenario):
    control = _run_as_a_second_account("main", route, scenario)
    if "NAMESPACE-UP" not in control.stderr:
        # Only the test's own scaffolding may skip: the outer namespaces, or the filtered
        # namespace nested inside them on main's code path. Anything after that is the code.
        pytest.skip(f"cannot nest the filtered namespace here: {control.stderr.strip()[-200:]}")
    # The control is main's behaviour: the seat is uid 0 and meets another account's
    # `*-0` scratch, so the harness really presents the collision.
    assert control.returncode == 3, control.stdout + control.stderr
    assert "is owned by uid 65534, expected 0" in control.stdout
    fixed = _run_as_a_second_account("fixed", route, scenario)
    if scenario == "foreign-own-uid":
        assert fixed.returncode == 3, fixed.stdout + fixed.stderr
        assert f"claude-{ACCOUNT} is owned by uid 65534, expected {ACCOUNT}" in fixed.stdout
        return
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert fixed.stdout.strip().endswith("SEAT-OK")


# --- retention on a shared /tmp (independent of the seat identity) --------------------------


def test_retention_skips_other_accounts_and_unreadable_entries(tmp_path, monkeypatch):
    mine = tmp_path / "pl-panel-mine"
    mine.mkdir()
    sandbox_retention.mark_as_sandbox(mine)
    locked = tmp_path / "systemd-private-like"
    locked.mkdir()
    locked.chmod(0)
    try:
        # An unreadable sibling used to raise EACCES out of the marker probe and abort
        # the whole reap (on Python <= 3.13).
        assert [e.path for e in sandbox_retention.discover(tmp_path)] == [mine]
        # Another account's sandbox is never this account's to count or remove.
        other = os.getuid() + 1
        monkeypatch.setattr(sandbox_retention.os, "getuid", lambda: other)
        assert sandbox_retention.discover(tmp_path) == []
    finally:
        locked.chmod(0o700)


def test_the_age_sweep_spares_a_live_holder_and_reclaims_a_dead_one(tmp_path):
    stale = 1_000_000_000
    live, dead = tmp_path / "pl-egress-ns-live", tmp_path / "pl-egress-ns-dead"
    unready, bystander = tmp_path / "pl-egress-ns-unready", tmp_path / "pl-egress-ns-bystander"
    for work, pid in ((live, os.getpid()), (dead, 2**22 + 12345), (unready, None), (bystander, None)):
        (work / "leftover").mkdir(parents=True)
        if work is not bystander:
            (work / sandbox_egress.EGRESS_WORK_MARKER).touch()
        if pid is not None:
            (work / "pid").write_text(f"{pid}\n")
        os.utime(work, (stale, stale))
    panel_invoker._gc_stale_panel_scratch(root=tmp_path, max_age_s=3600)
    assert (live / "leftover").is_dir(), "a running holder's dir was reaped by age"
    assert not dead.exists() and not unready.exists()
    assert (bystander / "leftover").is_dir(), "an unmarked lookalike was reaped by name"


def test_retention_archives_a_symlink_as_a_link_never_its_target(tmp_path):
    secret = tmp_path / "token"
    secret.write_text("OAUTH-TOKEN-BYTES\n")
    sandbox = tmp_path / "root" / "pl-panel-x"
    work = sandbox / sandbox_retention.WORK_DIRNAME
    work.mkdir(parents=True)
    (work / "notes.md").write_text("n\n")
    (work / "credential-ref").symlink_to(secret)
    entry = sandbox_retention.SandboxEntry(sandbox, 0.0, 0)
    archive = sandbox_retention._archive_work(entry, tmp_path / "archive")
    with tarfile.open(archive) as tar:
        assert tar.getmember("pl-panel-x/work/credential-ref").issym()
        assert all(b"OAUTH-TOKEN-BYTES" not in (tar.extractfile(m).read() if m.isfile() else b"")
                   for m in tar.getmembers())
