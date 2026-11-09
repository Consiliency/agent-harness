"""v13 PLACECLI SL-2: the reservation-scoped ForwardTcp-to-Unix bridge.

The real helper process runs (through ``seat_uid.trusted_module_argv``). The ForwardTcp
stream's local end is a fake guest relay; the requester's side is a behavioural fake of
agent-toolkit's ``cred-proxy.mjs``. Model bytes cross the bridge, the guest holds
placeholders only, and no credential reaches the sandbox side, the helper, a record or a
message.
"""

from __future__ import annotations

import ast
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time

import pytest

from phase_loop_runtime import placement_bridge as pb
from phase_loop_runtime import placement_process_contract as contract

FIXTURES = Path(__file__).parent / "fixtures" / "placement-cli"
sys.path.insert(0, str(FIXTURES))
import fake_cred_proxy  # noqa: E402

SECRET = "sk-ant-SENTINEL-do-not-cross-0123456789"
_REAL_SPAWN = pb._spawn_helper
PLACEHOLDER = "Bearer placeholder-not-a-key"
DIGEST = "sha256:" + "e" * 64


@pytest.fixture
def short_dir():
    """Unix socket paths are short: keep the bridge root under /tmp."""
    path = Path(tempfile.mkdtemp(prefix="pb", dir="/tmp"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def reservation(rid="rsv-1", *, workload="pi-runner", kind="openshell", client="agent-toolkit"):
    body = {
        "schema": "placement.reservation.v1", "reservation_id": rid, "workload": workload,
        "target": {"name": "ai" if kind == "openshell" else "local", "kind": kind,
                   "rank": 0 if kind == "openshell" else 1},
        "transport_id": "ai-openshell", "image_digest": DIGEST,
        "policy_vector": "full-remote-pi-runner" if kind == "openshell" else "minimal-without-app",
        "policy_digest": DIGEST, "providers": ["anthropic"], "egress_sha256": DIGEST,
        "client": client, "inventory": client,
        "rank_policy": "agent_executor" if workload == "pi-runner" else "seats_single_target",
        "lease_id": "lease-1", "expires_at": "2099-01-01T00:00:00Z", "config_sha256": "f" * 64,
        "bridge": None,
    }
    return contract.Reservation.from_json(body)


class Guest:
    """The sandbox side of the ForwardTcp stream: placeholders only."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        self.listener.listen(1)
        self.received = b""
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        self.listener.settimeout(10)
        try:
            link, _ = self.listener.accept()
        except OSError:
            return
        with link:
            link.settimeout(10)
            link.sendall(b"POST /anthropic/v1/messages HTTP/1.1\r\nhost: guest\r\n"
                         b"authorization: " + PLACEHOLDER.encode() + b"\r\n"
                         b"content-length: 2\r\n\r\n{}")
            link.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                data = link.recv(65536)
                if not data:
                    break
                chunks.append(data)
            self.received = b"".join(chunks)

    def close(self) -> None:
        self.listener.close()
        self.thread.join(5)


def requester_proxy(socket_path: str, seen: dict) -> None:
    """The requester's credential proxy: connected to the bridge, it answers the guest."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(10)
    client.connect(socket_path)
    with client:
        request = b""
        while True:
            data = client.recv(65536)
            if not data:
                break
            request += data
        seen["request"] = request

        def provider(origin, path, headers, body):
            seen["provider"] = (origin, path, dict(headers))
            return b'{"content":"model bytes"}'

        answer = fake_cred_proxy.handle(request, {"anthropic": "https://api.anthropic.com"},
                                        lambda name: SECRET, provider)
        client.sendall(answer)
        client.shutdown(socket.SHUT_WR)
        time.sleep(0.2)


def _helper_sockets(pid: int) -> set[int]:
    inodes = set()
    for fd in os.listdir(f"/proc/{pid}/fd"):
        try:
            target = os.readlink(f"/proc/{pid}/fd/{fd}")
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(int(target[8:-1]))
    return inodes


def _tcp_inodes(pid: int) -> set[int]:
    inodes = set()
    for table in ("tcp", "tcp6", "udp", "udp6"):
        try:
            lines = Path(f"/proc/{pid}/net/{table}").read_text().splitlines()[1:]
        except OSError:
            continue
        inodes.update(int(line.split()[9]) for line in lines if len(line.split()) > 9)
    return inodes


def test_one_private_socket_per_reservation_and_model_bytes_cross(short_dir):
    guest = Guest(short_dir / "guest.sock")
    bridge = pb.ForwardTcpUnixBridge(short_dir / "b")
    handle = bridge.open(reservation(), pb.BridgeExposure("pi-link", str(short_dir / "guest.sock")),
                         cancelled=threading.Event())
    try:
        directory, socket_path = Path(handle.directory), handle.descriptor.socket_path
        assert handle.descriptor.service_name == "pi-link"
        assert stat.S_IMODE(os.lstat(directory).st_mode) == 0o700
        assert stat.S_IMODE(os.lstat(socket_path).st_mode) == 0o600
        assert stat.S_ISSOCK(os.lstat(socket_path).st_mode)
        assert os.listdir(directory) == ["s"]
        assert handle.descriptor.to_json()["lifetime"] == "reservation"
        cmdline = Path(f"/proc/{handle.pid}/cmdline").read_bytes().split(b"\0")
        assert cmdline[1:3] == [b"-I", b"-c"] and b"-m" not in cmdline
        assert b"phase_loop_runtime.placement_bridge" in cmdline
        environ = Path(f"/proc/{handle.pid}/environ").read_bytes()
        assert SECRET.encode() not in environ and SECRET.encode() not in b"\0".join(cmdline)
        # No public listener: every socket the helper holds is a Unix socket.
        assert not _helper_sockets(handle.pid) & _tcp_inodes(handle.pid)
        seen: dict = {}
        requester_proxy(socket_path, seen)
        guest.thread.join(10)
        assert PLACEHOLDER.encode() in seen["request"]            # placeholders stay guest-side
        assert seen["provider"][2]["authorization"] == "Bearer " + SECRET
        assert b"model bytes" in guest.received
        assert SECRET.encode() not in guest.received
        assert SECRET.encode() not in json.dumps(handle.to_json()).encode()
    finally:
        flags = bridge.close(handle, cancelled=threading.Event())
        guest.close()
    assert flags.destruction_observed and flags.barrier_confirmed and not flags.cleanup_pending
    assert not directory.exists()
    assert not pb._helper_alive(handle.pid, handle.start_ticks)


def test_a_stale_directory_is_refused_and_never_reused(short_dir):
    bridge = pb.ForwardTcpUnixBridge(short_dir / "b")
    handle = bridge.open(reservation(), pb.BridgeExposure("pi-link", str(short_dir / "up")),
                         cancelled=threading.Event())
    try:
        with pytest.raises(pb.BridgeUnavailable) as caught:
            bridge.open(reservation(), pb.BridgeExposure("pi-link", str(short_dir / "up")),
                        cancelled=threading.Event())
        assert caught.value.code == "bridge_stale_socket"
        other = bridge.open(reservation("rsv-2"), pb.BridgeExposure("pi-link", str(short_dir / "up")),
                            cancelled=threading.Event())
        assert other.descriptor.socket_path != handle.descriptor.socket_path
        bridge.close(other, cancelled=threading.Event())
    finally:
        bridge.close(handle, cancelled=threading.Event())


def test_a_cancelled_open_leaves_nothing(short_dir):
    bridge = pb.ForwardTcpUnixBridge(short_dir / "b")
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(pb.BridgeUnavailable) as caught:
        bridge.open(reservation(), pb.BridgeExposure("pi-link", str(short_dir / "up")), cancelled=cancelled)
    assert caught.value.code == "bridge_cancelled"
    assert not (short_dir / "b").exists() or not any((short_dir / "b").rglob("s"))


def test_close_from_another_process_tears_the_helper_down(short_dir):
    opener = pb.ForwardTcpUnixBridge(short_dir / "b")
    handle = opener.open(reservation(), pb.BridgeExposure("pi-link", str(short_dir / "up")),
                         cancelled=threading.Event())
    process = opener._children.pop(handle.pid)          # as if the opening CLI call had exited
    restored = pb.BridgeHandle.from_json(json.loads(json.dumps(handle.to_json())))
    closer = pb.ForwardTcpUnixBridge(short_dir / "b")
    flags = closer.close(restored, cancelled=threading.Event())
    process.wait(10)
    assert flags.destruction_observed and not Path(handle.directory).exists()


@pytest.mark.parametrize("workload,kind,client", [("pi-runner", "local", "agent-toolkit"),
                                                  ("qualification", "openshell", "agent-harness")])
def test_only_remote_pi_or_leg_reservations_get_a_bridge(short_dir, workload, kind, client):
    with pytest.raises(pb.BridgeUnavailable) as caught:
        pb.ForwardTcpUnixBridge(short_dir / "b").open(
            reservation(workload=workload, kind=kind, client=client),
            pb.BridgeExposure("pi-link", str(short_dir / "up")), cancelled=threading.Event())
    assert caught.value.code == "bridge_not_applicable"


@pytest.mark.parametrize("exposure", [("pi-link", "relative/up"), ("bad name", "/tmp/up"),
                                      ("pi-link", "/" + "x" * 200)])
def test_the_exposure_is_validated(exposure):
    with pytest.raises(pb.BridgeUnavailable):
        pb.BridgeExposure(*exposure)


def test_a_root_whose_socket_path_is_too_long_falls_back_or_refuses(short_dir):
    deep = short_dir / ("d" * 120)
    bridge = pb.ForwardTcpUnixBridge(deep, fallback_root=short_dir / "b")
    handle = bridge.open(reservation(), pb.BridgeExposure("pi-link", str(short_dir / "up")),
                         cancelled=threading.Event())
    try:
        assert handle.descriptor.socket_path.startswith(str(short_dir / "b"))
    finally:
        bridge.close(handle, cancelled=threading.Event())
    with pytest.raises(pb.BridgeUnavailable) as caught:
        pb.ForwardTcpUnixBridge(deep).open(reservation("rsv-x"), pb.BridgeExposure("pi-link", "/tmp/up"),
                                           cancelled=threading.Event())
    assert caught.value.code == "bridge_path_too_long"


def test_the_lifecycle_opens_the_bridge_for_remote_pi_and_tears_it_down_on_release(tmp_path, short_dir):
    from test_placement_lifecycle_process import Env, release, reserve

    env = Env(tmp_path)
    env.toolkit()
    env.coordinator.upstream = str(short_dir / "guest.sock")
    lifecycle = env.lifecycle(bridge=pb.ForwardTcpUnixBridge(short_dir / "b"))
    response, raw, code = reserve(lifecycle)
    assert code == 0
    descriptor = response.reservation.bridge
    assert stat.S_IMODE(os.lstat(descriptor.socket_path).st_mode) == 0o600
    assert SECRET.encode() not in raw
    released, code = release(env.lifecycle(bridge=pb.ForwardTcpUnixBridge(short_dir / "b")),
                             response.reservation.to_json())
    assert code == 0 and released.state == "released"
    assert not Path(descriptor.socket_path).exists()
    journal = b"".join(path.read_bytes() for path in (env.state).rglob("*.json"))
    assert SECRET.encode() not in journal


# -- the black-box corpus --------------------------------------------------------------------

def test_the_corpus_covers_every_live_step_and_the_coordinator_faults():
    cases = json.loads((FIXTURES / "cases.json").read_text())["cases"]
    ids = [case["id"] for case in cases]
    assert [i.split("-")[0] for i in ids[:10]] == [f"L{n}" for n in range(10)]
    assert {"X-unavailable", "X-deadline", "X-lost-reply", "X-snapshot-expiry",
            "X-duplicate-binding"} <= set(ids)
    for case in cases:
        assert case["client"] in contract.CLIENTS and case["steps"]
        for step in case["steps"]:
            assert step["verb"] in contract.VERBS and step["expect"]["exit"] in (0, 10, 20, 70)


def test_the_fake_coordinator_never_branches_on_a_case():
    source = (FIXTURES / "fake_coordinator.py").read_text()
    tree = ast.parse(source)
    strings = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
               and isinstance(node.value, str)}
    cases = json.loads((FIXTURES / "cases.json").read_text())["cases"]
    assert not strings & {case["id"] for case in cases}
    assert "case" not in {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert all("agent_harness" not in line for line in (FIXTURES / "fake_cred_proxy.py").read_text().splitlines()
               if line.startswith(("import", "from")))


# -- mutation controls ------------------------------------------------------------------------

def _check_modes(short_dir):
    bridge = pb.ForwardTcpUnixBridge(short_dir / "b")
    handle = bridge.open(reservation("m-modes"), pb.BridgeExposure("pi-link", "/tmp/up"),
                         cancelled=threading.Event())
    try:
        return (stat.S_IMODE(os.lstat(handle.descriptor.socket_path).st_mode) == 0o600
                and stat.S_IMODE(os.lstat(handle.directory).st_mode) == 0o700)
    finally:
        bridge.close(handle, cancelled=threading.Event())


def _check_no_reuse(short_dir):
    bridge = pb.ForwardTcpUnixBridge(short_dir / "b")
    handle = bridge.open(reservation("m-reuse"), pb.BridgeExposure("pi-link", "/tmp/up"),
                         cancelled=threading.Event())
    try:
        try:
            bridge.open(reservation("m-reuse"), pb.BridgeExposure("pi-link", "/tmp/up"),
                        cancelled=threading.Event())
        except pb.BridgeUnavailable as exc:
            return exc.code == "bridge_stale_socket"
        return False
    finally:
        bridge.close(handle, cancelled=threading.Event())


def _check_service(short_dir):
    bridge = pb.ForwardTcpUnixBridge(short_dir / "b")
    handle = bridge.open(reservation("m-svc"), pb.BridgeExposure("pi-link", "/tmp/up"),
                         cancelled=threading.Event())
    bridge.close(handle, cancelled=threading.Event())
    return handle.descriptor.service_name == "pi-link"


def _check_teardown(short_dir):
    bridge = pb.ForwardTcpUnixBridge(short_dir / "b")
    handle = bridge.open(reservation("m-down"), pb.BridgeExposure("pi-link", "/tmp/up"),
                         cancelled=threading.Event())
    process = bridge._children.get(handle.pid)
    bridge.close(handle, cancelled=threading.Event())
    gone = not Path(handle.directory).exists() and not pb._helper_alive(handle.pid, handle.start_ticks)
    if not gone and process is not None:
        process.kill()
        process.wait(10)
        shutil.rmtree(handle.directory, ignore_errors=True)
    return gone


def _loose_spawn(directory, upstream, expires):
    process = _REAL_SPAWN(directory, upstream, expires)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not (Path(directory) / "s").exists():
        time.sleep(0.02)
    os.chmod(directory, 0o755)
    return process


BRIDGE_CONTROLS = {
    "modes": (_check_modes, lambda mp: (
        mp.setattr(pb, "_socket_is_private", lambda *a: True),
        mp.setattr(pb, "_spawn_helper", _loose_spawn))),
    "reuse": (_check_no_reuse, lambda mp: mp.setattr(pb, "_stale", lambda directory: False)),
    "service": (_check_service, lambda mp: mp.setattr(
        pb, "BridgeDescriptor", lambda service, path: contract.BridgeDescriptor("swapped", path))),
    "teardown": (_check_teardown, lambda mp: (
        mp.setattr(pb, "_remove_directory", lambda directory: True),
        mp.setattr(pb.ForwardTcpUnixBridge, "_stop", lambda *a: None))),
}


@pytest.mark.parametrize("kind", ["intact", "killed"])
@pytest.mark.parametrize("control", sorted(BRIDGE_CONTROLS))
def test_bridge_mutation_controls(short_dir, monkeypatch, control, kind):
    check, mutate = BRIDGE_CONTROLS[control]
    if kind == "intact":
        assert check(short_dir) is True
        return
    mutate(monkeypatch)
    try:
        holds = check(short_dir)
    except (pb.BridgeUnavailable, OSError, AssertionError):
        holds = False
    assert holds is False
