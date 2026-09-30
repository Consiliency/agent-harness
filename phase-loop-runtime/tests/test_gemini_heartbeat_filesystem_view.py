"""The Gemini heartbeat sandbox's filesystem view.

The owner wrapper for the Gemini heartbeat profile binds the host root read-only,
replaces host directories the provider has no use for with empty private tmpfs mounts,
and leaves only the private HOME, a private /tmp, an empty private working directory
and the subscription credential file writable. The live tests run a small synthetic
probe through the real wrapper (no provider, synthetic credential) and compare what it
saw with the host afterwards.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
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
root = next(line.split() for line in open("/proc/self/mountinfo") if line.split()[4] == "/")
print(json.dumps({
    "root_options": root[5].split(","),
    "etc_write": attempt_write("/etc/" + scratch),
    "usr_write": attempt_write("/usr/" + scratch),
    "hidden_exists": os.path.exists(hidden),
    "hidden_write": attempt_write(hidden),
    "cwd": os.getcwd(),
    "cwd_entries": sorted(os.listdir(cwd)),
    "cwd_write": attempt_write(os.path.join(cwd, scratch)),
    "tmp_write": attempt_write("/tmp/" + scratch),
    "home_write": attempt_write(os.path.join(os.environ["HOME"], scratch)),
    "credential": open(credential).read(),
    "linked_credential": open(os.path.join(os.environ["HOME"], ".gemini/antigravity-cli/antigravity-oauth-token")).read(),
    "credential_write": attempt_write(credential, "synthetic-refreshed\n"),
    "listings": {d: sorted(os.listdir(d)) for d in ("/home", "/mnt", "/root", "/srv", "/media")
                 if os.path.isdir(d) and os.access(d, os.R_OK)},
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


@pytest.fixture
def layout(tmp_path):
    credential = tmp_path / "home/.gemini/antigravity-cli/antigravity-oauth-token"
    credential.parent.mkdir(parents=True)
    credential.write_text("synthetic-token-only\n")
    cwd = tmp_path / "out"
    cwd.mkdir()
    (cwd / "panel-other.txt").write_text("another seat's output\n")
    hidden = tmp_path / "host-file.txt"
    hidden.write_text("host content\n")
    return credential, cwd, hidden


def test_the_gemini_owner_binds_the_host_root_read_only(tmp_path, layout):
    credential, cwd, _ = layout
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "view", 0, threading.Event())
    profile = _profile(credential)
    argv = monitor.owned_command(("fixture",), gemini_profile=profile, cwd=cwd)
    assert argv[:6] == ["/usr/bin/bwrap", "--die-with-parent", "--unshare-pid",
                        "--ro-bind", "/", "/"]
    assert "--bind" not in argv[:argv.index("--tmpfs")]
    assert argv.index("--unshare-pid") < argv.index("--proc") < argv.index("--")
    for root in panel._GEMINI_PRIVATE_ROOTS:
        if os.path.isdir(root) and os.path.realpath(root) == root:
            assert argv[argv.index(root) - 1] == "--tmpfs", root
    bind = argv.index("--bind")
    assert argv[bind:bind + 3] == ["--bind", os.path.realpath(credential), str(credential.absolute())]
    assert argv[argv.index(str(cwd)) - 1] == "--dir"
    # The HOME mounts come after the view, on its /dev.
    assert argv.index("--dev") < argv.index(gh.PRIVATE_HOME)
    assert argv[-2:] == ["--", "fixture"]


def test_the_probe_view_carries_its_marker_and_no_profile_descriptors(tmp_path, layout):
    credential, cwd, _ = layout
    monitor = panel._ReviewMonitor(tmp_path / "m.json", "view", 0, threading.Event())
    profile = _profile(credential)
    profile.mount_args = ["--info-fd", "13", *profile.mount_args]
    probe = monitor.owned_command((), gemini_profile=profile, cwd=cwd, probe_marker="/tmp/marker")
    launch = monitor.owned_command((), gemini_profile=profile, cwd=cwd)
    assert "--info-fd" not in probe and "--info-fd" in launch
    assert probe[-4:] == ["--ro-bind", "/tmp/marker", "/tmp/marker", "--"]
    assert probe[:-4] == launch[:-len(profile.mount_args) - 1]


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


def _assert_view(tmp_path, layout, seen, scratch):
    credential, cwd, hidden = layout
    assert "ro" in seen["root_options"], seen["root_options"]
    assert seen["etc_write"] in ("EROFS", "EACCES") and seen["usr_write"] in ("EROFS", "EACCES")
    # Paths outside the view are absent, and a write there never reaches the host.
    assert seen["hidden_exists"] is False
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
    for directory, entries in seen["listings"].items():
        allowed = {Path(str(p)).relative_to(directory).parts[0]
                   for p in (credential, cwd) if str(p).startswith(directory + "/")}
        assert set(entries) <= allowed, (directory, entries)
    assert not (Path("/etc") / scratch).exists() and not (Path("/usr") / scratch).exists()


@needs_bwrap
def test_the_gemini_sandbox_view_is_read_only_with_private_scratch(tmp_path, layout):
    seen, scratch = _run_view(tmp_path, layout)
    _assert_view(tmp_path, layout, seen, scratch)


@needs_bwrap
@pytest.mark.skipif(
    not sandbox_egress.egress_isolation_available(),
    reason="this host cannot enforce egress isolation (sandbox_egress.egress_isolation_available() is False)",
)
def test_the_gemini_sandbox_view_holds_inside_the_egress_namespace(tmp_path, layout):
    with sandbox_egress.isolated_network(timeout_s=None) as prefix:
        seen, scratch = _run_view(tmp_path, layout, prefix=prefix)
    _assert_view(tmp_path, layout, seen, scratch)
