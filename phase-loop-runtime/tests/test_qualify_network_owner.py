"""The agy qualification observer enters the provider's network namespace with the user
namespace that OWNS it (v0.7.18 cut, agent-harness#1066).

Since agent-harness#1052 an ordinary owned provider runs in a nested, capability-less user
namespace. Entering the PROVIDER's user namespace cannot read the holder's egress rules, so
every qualification operation failed at "network rule observation". Real namespaces here:
an outer ``unshare --user --net`` owns the network namespace, a nested ``unshare --user``
child plays the provider.
"""
from __future__ import annotations

import errno
import importlib.util
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qualify_gemini_heartbeat.py"
# The sdist ships tests/ but not scripts/ (a standalone-from-sdist run has no script).
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="scripts/ is not shipped in this tree")


def _load():
    spec = importlib.util.spec_from_file_location("qualify_gemini_heartbeat_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _descendants(pid: int) -> list[int]:
    out, frontier = [], [pid]
    while frontier:
        current = frontier.pop()
        try:  # a pid can be reaped between the listing and the read
            children = [int(x) for x in Path(f"/proc/{current}/task/{current}/children").read_text().split()]
        except (FileNotFoundError, ProcessLookupError):
            children = []
        out.extend(children)
        frontier.extend(children)
    return out


@pytest.fixture
def nested_provider():
    if shutil.which("unshare") is None:
        pytest.skip("unshare unavailable")
    # `& wait` keeps the outer shell alive as the netns owner, whatever the shell's exec policy.
    outer = subprocess.Popen(
        ["unshare", "--user", "--net", "--map-root-user", "sh", "-c", "unshare --user sleep 60 & wait"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        provider = None
        while time.monotonic() < deadline and outer.poll() is None and provider is None:
            for pid in _descendants(outer.pid):
                try:
                    if Path(f"/proc/{pid}/cmdline").read_bytes().startswith(b"sleep"):
                        provider = pid
                except FileNotFoundError:
                    continue
            time.sleep(0.05)
        if provider is None:
            pytest.skip("unprivileged nested user namespaces are unavailable here")
        yield outer.pid, provider
    finally:
        # The whole session: the backgrounded provider is reparented, not killed, with the shell.
        try:
            os.killpg(outer.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        outer.wait()


def test_the_owner_is_the_ancestor_whose_user_namespace_owns_the_network(nested_provider):
    outer, provider = nested_provider
    module = _load()
    assert os.stat(f"/proc/{provider}/ns/user").st_ino != os.stat(f"/proc/{outer}/ns/user").st_ino
    assert os.stat(f"/proc/{provider}/ns/net").st_ino == os.stat(f"/proc/{outer}/ns/net").st_ino
    assert module._network_owner_pid(provider) == outer
    assert module._network_owner_pid(outer) == outer


def test_our_own_process_resolves_to_itself_or_an_owning_ancestor():
    module = _load()
    try:
        owner = module._network_owner_pid(os.getpid())
    except PermissionError as exc:  # EPERM: our user ns does not own our netns (a sandboxed runner)
        pytest.skip(f"NS_GET_USERNS not permitted here: {errno.errorcode.get(exc.errno)}")
    except module.QualificationFailure:
        pytest.skip("this process's network namespace is owned outside its ancestry")
    user = os.stat(f"/proc/{owner}/ns/user")
    assert owner == os.getpid() or user.st_ino != os.stat("/proc/self/ns/user").st_ino


@pytest.mark.parametrize("own", [False, True], ids=["owner-is-another-namespace", "owner-is-ours"])
def test_inspect_network_enters_the_provider_net_with_the_owner_user(monkeypatch, own):
    """The argv: the PROVIDER's netns always; the owner's user ns unless it is our own."""
    module = _load()
    from phase_loop_runtime import sandbox_egress
    monkeypatch.setattr(sandbox_egress, "egress_rules", lambda: ["-A OUTPUT -j DROP"])
    owner = os.getpid() if own else 4242
    monkeypatch.setattr(module, "_network_owner_pid", lambda pid: owner)
    real_stat = os.stat
    monkeypatch.setattr(module.os, "stat", lambda path, *a, **k: (
        real_stat("/proc/self/ns/net") if (not own and path == "/proc/4242/ns/user") else real_stat(path, *a, **k)))
    seen = []

    class _Done:
        returncode = 0
        stdout = b"-P OUTPUT ACCEPT\n"

    monkeypatch.setattr(module.panel, "run_provider", lambda argv, **k: seen.append(argv) or _Done())
    result = module.inspect_network(1234)
    assert result["network_rules_verified"] and result["network_rule_checks"] == 1
    head = seen[0][:seen[0].index("iptables")]
    assert head[:2] == ["nsenter", "--net=/proc/1234/ns/net"]
    if own:
        assert head == ["nsenter", "--net=/proc/1234/ns/net"]
    else:
        assert head == ["nsenter", "--net=/proc/1234/ns/net", "--user=/proc/4242/ns/user", "--preserve-credentials"]
    assert seen[0][len(head):] == ["iptables", "-C", "OUTPUT", "-j", "DROP"]


def test_inspect_network_fails_when_a_rule_is_absent(monkeypatch):
    module = _load()
    from phase_loop_runtime import sandbox_egress
    monkeypatch.setattr(sandbox_egress, "egress_rules", lambda: ["-A OUTPUT -j DROP"])
    monkeypatch.setattr(module, "_network_owner_pid", lambda pid: os.getpid())

    class _Missing:
        returncode = 1
        stdout = b""

    monkeypatch.setattr(module.panel, "run_provider", lambda argv, **k: _Missing())
    with pytest.raises(module.QualificationFailure, match="network rule observation failed"):
        module.inspect_network(1234)


def test_the_walk_checks_pid_1_itself(monkeypatch):
    """A provider whose network namespace is owned by pid 1's user namespace resolves to 1
    (the walk used to stop before examining pid 1; agent-harness#1067 r1, grok)."""
    module = _load()
    owner_ns = os.stat("/proc/self/ns/net")      # any nsfs identity distinct from the chain's
    other_ns = os.stat("/proc/self/ns/user")
    parents = {4242: 1}

    monkeypatch.setattr(module.os, "open", lambda path, *a, **k: 7)
    monkeypatch.setattr(module.os, "close", lambda fd: None)
    import fcntl  # the script imports it inside the function
    monkeypatch.setattr(fcntl, "ioctl", lambda fd, req: 8)
    real_fstat, real_stat = os.fstat, os.stat
    monkeypatch.setattr(module.os, "fstat", lambda fd: owner_ns if fd == 8 else real_fstat(fd))
    monkeypatch.setattr(module.os, "stat", lambda path, *a, **k: (
        owner_ns if path == "/proc/1/ns/user" else other_ns if path == "/proc/4242/ns/user" else real_stat(path, *a, **k)))
    real_read = Path.read_text
    monkeypatch.setattr(module.Path, "read_text", lambda self, *a, **k: (
        f"4242 (sleep) S {parents[4242]} 0 0" if str(self) == "/proc/4242/stat" else real_read(self, *a, **k)))
    assert module._network_owner_pid(4242) == 1
