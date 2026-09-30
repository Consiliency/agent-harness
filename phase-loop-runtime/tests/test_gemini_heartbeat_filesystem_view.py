"""The Gemini heartbeat sandbox's filesystem view.

The owner wrapper for the Gemini heartbeat profile builds the sandbox from an empty root
and exposes only an allowlist of host entries, read-only. The only writable places are
the private HOME, a private /tmp, a private working directory and the subscription
credential file. The live tests run a small synthetic probe through the real wrapper (no
provider, synthetic credential) and compare what it saw with the host afterwards.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import uuid

import pytest

from phase_loop_runtime import gemini_heartbeat as gh
from phase_loop_runtime import panel_invoker as panel
from phase_loop_runtime import sandbox_egress

needs_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None and not os.path.exists("/usr/bin/bwrap"),
    reason="bubblewrap is not installed on this host",
)

VIEW_PROBE = r'''
import errno, json, os, sys
cwd, credential, hidden, scratch = sys.argv[1:5]
def attempt_write(path, data="probe\n"):
    try:
        with open(path, "w") as handle:
            handle.write(data)
        return "ok"
    except OSError as exc:
        return errno.errorcode.get(exc.errno, str(exc.errno))
def attempt_read(path):
    try:
        with open(path) as handle:
            return handle.read()
    except OSError as exc:
        return errno.errorcode.get(exc.errno, str(exc.errno))
mounts = [line.split() for line in open("/proc/self/mountinfo")]
root = next(fields for fields in mounts if fields[4] == "/")
print(json.dumps({
    "root_options": root[5].split(","),
    "mount_points": sorted({fields[4] for fields in mounts}),
    "etc_write": attempt_write("/etc/" + scratch),
    "usr_write": attempt_write("/usr/" + scratch),
    "root_write": attempt_write("/" + scratch),
    "hidden_read": attempt_read(hidden),
    "hidden_write": attempt_write(hidden),
    "cwd": os.getcwd(),
    "cwd_entries": sorted(os.listdir(cwd)),
    "cwd_write": attempt_write(os.path.join(cwd, scratch)),
    "tmp_write": attempt_write("/tmp/" + scratch),
    "home_write": attempt_write(os.path.join(os.environ["HOME"], scratch)),
    "credential": attempt_read(credential),
    "linked_credential": attempt_read(os.path.join(os.environ["HOME"], ".gemini/antigravity-cli/antigravity-oauth-token")),
    "credential_write": attempt_write(credential, "synthetic-refreshed\n"),
    "top_level": sorted(os.listdir("/")),
    "listings": {d: sorted(os.listdir(d)) for d in ("/tmp", "/var/tmp", "/run", "/run/user", "/home", "/mnt", "/root", "/srv", "/media", "/opt")
                 if os.path.isdir(d)},
}))
'''


def _profile(credential):
    """The HOME mounts of the real profile, without its single-use descriptors."""
    config = gh.PRIVATE_HOME + "/.gemini/antigravity-cli"
    mount_args = []
    for directory in (gh.PRIVATE_HOME, gh.PRIVATE_HOME + "/.gemini", config):
        mount_args += ["--perms", "0700", "--dir", directory]
    mount_args += ["--symlink", str(credential.absolute()), config + "/antigravity-oauth-token"]
    return SimpleNamespace(mount_args=mount_args,
                           env={"PATH": "/usr/bin:/bin", "HOME": gh.PRIVATE_HOME})


def _layout(base):
    credential = base / "home/.gemini/antigravity-cli/antigravity-oauth-token"
    credential.parent.mkdir(parents=True)
    credential.write_text("synthetic-token-only\n")
    cwd = base / "out"
    cwd.mkdir()
    (cwd / "panel-other.txt").write_text("another seat's output\n")
    hidden = base / "host-file.txt"
    hidden.write_text("host content\n")
    return credential, cwd, hidden


@pytest.fixture
def layout(tmp_path):
    return _layout(tmp_path)


@pytest.fixture
def outside_tmp_layout():
    """The same layout under a writable host directory other than /tmp."""
    base_dir = "/run/lock"
    if not (os.path.isdir(base_dir) and os.access(base_dir, os.W_OK | os.X_OK)):
        pytest.skip("no writable host directory outside /tmp on this host")
    base = Path(tempfile.mkdtemp(prefix=".pl-view-", dir=base_dir))
    try:
        yield _layout(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _pairs(argv, flag, width):
    return [argv[i + 1:i + 1 + width] for i, arg in enumerate(argv) if arg == flag]


def test_the_gemini_owner_exposes_only_an_allowlisted_read_only_view(tmp_path, layout):
    credential, cwd, _ = layout
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "view", 0, threading.Event())
    profile = _profile(credential)
    argv = monitor.owned_command(("fixture",), gemini_profile=profile, cwd=cwd)
    assert argv[:3] == ["/usr/bin/bwrap", "--die-with-parent", "--unshare-pid"]
    # No bind of the host root, and every read-only bind is an allowlisted entry.
    allowed = set(panel._GEMINI_VIEW_SYSTEM) | set(panel._GEMINI_VIEW_FILES)
    for source, destination in _pairs(argv, "--ro-bind", 2) + _pairs(argv, "--ro-bind-try", 2):
        assert source == destination and source in allowed, source
    # The only writable host bind is the credential file.
    assert _pairs(argv, "--bind", 2) == [[os.path.realpath(credential), str(credential.absolute())]]
    assert [str(cwd)] in _pairs(argv, "--tmpfs", 1) and ["/tmp"] in _pairs(argv, "--tmpfs", 1)
    assert argv.index("--unshare-pid") < argv.index("--proc") < argv.index("--remount-ro") < argv.index("--")
    # The HOME mounts come after the view, on its /dev.
    assert argv.index("--dev") < argv.index(gh.PRIVATE_HOME)
    assert argv[-2:] == ["--", "fixture"]


@pytest.mark.parametrize("links", [0, 2])
def test_the_view_requires_exactly_one_credential_link(tmp_path, layout, links):
    credential, cwd, _ = layout
    mount_args = [arg for arg in _profile(credential).mount_args]
    link = mount_args[-3:]
    del mount_args[-3:]
    mount_args += link * links
    with pytest.raises(ValueError):
        panel._gemini_filesystem_view(cwd, mount_args)


def test_the_probe_view_carries_its_marker_and_no_profile_descriptors(tmp_path, layout):
    credential, cwd, _ = layout
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "view", 0, threading.Event())
    profile = _profile(credential)
    profile.mount_args = ["--info-fd", "13", *profile.mount_args]
    probe = monitor.owned_command((), gemini_profile=profile, cwd=cwd, probe_marker="/tmp/marker")
    launch = monitor.owned_command((), gemini_profile=profile, cwd=cwd)
    assert "--info-fd" not in probe and "--info-fd" in launch
    assert probe[-6:] == ["--ro-bind", "/tmp/marker", "/tmp/marker", "--remount-ro", "/", "--"]
    assert probe[:-6] + probe[-3:-1] == launch[:-len(profile.mount_args) - 1]


def _run_view(tmp_path, layout, prefix=()):
    credential, cwd, hidden = layout
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "view", 0, threading.Event())
    profile = _profile(credential)
    scratch = f".pl-view-probe-{uuid.uuid4().hex}"
    token = panel._EGRESS_LAUNCH_PREFIX.set(tuple(prefix))
    try:
        proc = panel.launch_provider(
            ["/usr/bin/python3", "-I", "-c", VIEW_PROBE, str(cwd), str(credential), str(hidden), scratch],
            process_owner=monitor.owned_command((), gemini_profile=profile, cwd=cwd),
            probe_owner=lambda marker: monitor.owned_command(
                (), gemini_profile=profile, cwd=cwd, probe_marker=marker),
            cwd=str(cwd), env=profile.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out, err = proc.communicate(timeout=60)
    finally:
        panel._EGRESS_LAUNCH_PREFIX.reset(token)
    assert proc.returncode == 0, err.decode()
    return json.loads(out), scratch


def _assert_view(layout, seen, scratch):
    credential, cwd, hidden = layout
    assert "ro" in seen["root_options"], seen["root_options"]
    for key in ("etc_write", "usr_write", "root_write"):
        assert seen[key] == "EROFS", (key, seen[key])
    # Everything outside the allowlist is absent, and a write there never reaches the host.
    assert seen["hidden_read"] == "ENOENT"
    assert hidden.read_text() == "host content\n"
    # The working directory is the same path, private and empty.
    assert seen["cwd"] == str(cwd) and seen["cwd_entries"] == []
    assert seen["cwd_write"] == "ok" and not (cwd / scratch).exists()
    # Private scratch is writable and stays private.
    assert seen["tmp_write"] == "ok" and not (Path("/tmp") / scratch).exists()
    assert seen["home_write"] == "ok"
    # The credential file is the one host path written through.
    assert seen["credential"] == seen["linked_credential"] == "synthetic-token-only\n"
    assert seen["credential_write"] == "ok"
    assert credential.read_text() == "synthetic-refreshed\n"
    assert not (Path("/etc") / scratch).exists() and not (Path("/usr") / scratch).exists()
    # The top level holds only the allowlist and the private mounts' ancestors.
    ancestors = {Path(str(p)).parts[1] for p in (credential, cwd)}
    allowed = {Path(e).parts[1] for e in (*panel._GEMINI_VIEW_SYSTEM, *panel._GEMINI_VIEW_FILES)}
    assert set(seen["top_level"]) <= allowed | ancestors | {"dev", "proc", "tmp"}, seen["top_level"]
    # Scratch and runtime directories show nothing of the host.
    for directory, entries in seen["listings"].items():
        on_path = {Path(str(p)).relative_to(directory).parts[0]
                   for p in (credential, cwd) if str(p).startswith(directory + "/")}
        if directory == "/tmp":
            on_path.add(scratch)
        assert set(entries) <= on_path, (directory, entries)
    for directory in ("/var/tmp", "/run/user"):
        assert not seen["listings"].get(directory), directory


@needs_bwrap
def test_the_gemini_sandbox_view_is_read_only_with_private_scratch(tmp_path, layout):
    seen, scratch = _run_view(tmp_path, layout)
    _assert_view(layout, seen, scratch)


@needs_bwrap
def test_an_existing_cwd_outside_tmp_is_still_private_and_empty(tmp_path, outside_tmp_layout):
    seen, scratch = _run_view(tmp_path, outside_tmp_layout)
    _assert_view(outside_tmp_layout, seen, scratch)


@needs_bwrap
def test_a_second_mount_of_host_data_is_not_carried_into_the_view(tmp_path, layout):
    """Data mounted at a second host path (here under /run) stays out of the view."""
    if shutil.which("unshare") is None:
        pytest.skip("util-linux unshare is not installed")
    credential, cwd, hidden = layout
    alias = "/run/lock/pl-view-alias"
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "view", 0, threading.Event())
    argv = monitor.owned_command(
        ("/usr/bin/python3", "-I", "-c",
         "import json,os,sys; print(json.dumps([os.path.exists(sys.argv[1]), os.path.exists('/run')]))",
         alias + "/" + hidden.name),
        gemini_profile=_profile(credential), cwd=cwd)
    script = ('mount -t tmpfs none /run/lock && mkdir "$1" && mount --bind "$2" "$1" '
              '&& test -r "$1/$3" && shift 3 && exec "$@"')
    proc = subprocess.run(
        ["unshare", "--user", "--map-root-user", "--mount", "/bin/sh", "-c", script, "sh",
         alias, str(hidden.parent), hidden.name, *argv],
        capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
    if proc.returncode != 0 and "mount" in proc.stderr:
        pytest.skip(f"this host cannot build the alias layout: {proc.stderr.strip()}")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [False, False]


@needs_bwrap
@pytest.mark.skipif(
    not sandbox_egress.egress_isolation_available(),
    reason="this host cannot enforce egress isolation (sandbox_egress.egress_isolation_available() is False)",
)
def test_the_gemini_sandbox_view_holds_inside_the_egress_namespace(tmp_path, layout):
    with sandbox_egress.isolated_network(timeout_s=None) as prefix:
        seen, scratch = _run_view(tmp_path, layout, prefix=prefix)
    _assert_view(layout, seen, scratch)

