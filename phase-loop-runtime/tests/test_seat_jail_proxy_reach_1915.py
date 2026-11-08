"""A jailed seat reaches its egress proxy, and nothing else (agent-harness#1915).

Live only: with ``PHASE_LOOP_REQUIRE_LIVE_JAIL=1`` on a jail-capable host a missing
prerequisite fails instead of skipping. One jailed process, after the seat-uid drop:

- runs outside the uid-drop AppArmor profile (`seat_jail_apparmor`), so the hand-back took it
  back to the confinement every other bwrap child has;
- reaches the proxy bridge on its loopback port, and the proxy answers there: a listed
  host is admitted and an unlisted one refused;
- reaches nothing else: a listener on the host's own address, which the host itself can
  reach, gets no connection, and the seat's other loopback ports refuse. Each of those
  fails with a network error (no route, refused), never a refused socket.

The proxy runs a fixture allowlist of ``.invalid`` hosts, and the admitted tunnel is closed
before any byte follows the CONNECT, so no request leaves the host. On a Ubuntu 24.04+/26.04
host this needs the current override from ``python3 -m phase_loop_runtime.seat_jail_apparmor``
installed by an administrator.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import socket
import subprocess
import urllib.parse
from pathlib import Path

import pytest

from phase_loop_runtime import seat_egress_proxy, seat_jail
from phase_loop_runtime.seat_route_contract import AllowlistRef

LISTED = "fixture-reach.invalid"
UNLISTED = "not-listed.invalid"
UID_DROP_PROFILE = "phase_loop_seat_uid_drop"
#: How a destination with no route from the seat fails: never EACCES or EPERM.
NETWORK_ERRORS = frozenset({"ENETUNREACH", "EHOSTUNREACH", "ECONNREFUSED", "ETIMEDOUT",
                            "EADDRNOTAVAIL"})

_JAILED_PROBE = r"""
import base64, errno, json, os, socket, sys, urllib.parse

spec = json.loads(sys.argv[1])


def outcome(exc):
    if isinstance(exc, TimeoutError) and not exc.errno:
        return "ETIMEDOUT"
    return errno.errorcode.get(exc.errno, str(exc.errno)) if exc.errno else type(exc).__name__


def label():
    for path in ("/proc/self/attr/apparmor/current", "/proc/self/attr/current"):
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read().strip("\0\n ")
        except OSError:
            continue
    return None


def connect(family, address):
    try:
        with socket.socket(family, socket.SOCK_STREAM) as client:
            client.settimeout(10)
            client.connect(address)
            return "connected"
    except OSError as exc:
        return outcome(exc)


def through_proxy(host):
    proxy = urllib.parse.urlsplit(os.environ["HTTPS_PROXY"])
    basic = base64.b64encode(f"{proxy.username}:{proxy.password}".encode()).decode()
    try:
        with socket.create_connection((proxy.hostname, proxy.port), timeout=10) as client:
            client.sendall((f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n"
                            f"Proxy-Authorization: Basic {basic}\r\n\r\n").encode())
            return client.recv(128).split(b"\r\n", 1)[0].decode("latin-1")
    except OSError as exc:
        return outcome(exc)


print(json.dumps({
    "label": label(),
    "listed": through_proxy(spec["listed"]),
    "unlisted": through_proxy(spec["unlisted"]),
    "host_address": connect(socket.AF_INET, (spec["host_address"], spec["host_port"])),
    "loopback_other_port": connect(socket.AF_INET, ("127.0.0.1", spec["other_port"])),
    "inet6_loopback": connect(socket.AF_INET6, ("::1", spec["other_port"])),
}))
"""


def _fixture_ref(allowlist_id: str) -> AllowlistRef:
    return AllowlistRef(
        id=allowlist_id, content_digest=hashlib.sha256(allowlist_id.encode()).hexdigest(),
        request_set=({"host": LISTED, "port": 443, "method": "GET", "path": "/"},),
        probe_rows=())


def _host_address() -> str | None:
    """This host's own outbound IPv4 address (a UDP connect sends no packet)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("192.0.2.1", 9))
        except OSError:
            return None
        address = probe.getsockname()[0]
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def _live_jail_or_fail() -> str:
    if os.environ.get("PHASE_LOOP_REQUIRE_LIVE_JAIL") != "1":
        pytest.skip("set PHASE_LOOP_REQUIRE_LIVE_JAIL=1 on a jail-capable host")
    from phase_loop_runtime import sandbox_egress, seat_uid

    missing = []
    if not seat_uid.seat_uid_available():
        missing.append(seat_uid.PREREQUISITE)
    if not sandbox_egress.egress_isolation_available():
        missing.append("egress isolation unavailable")
    reason = seat_egress_proxy.unavailable_reason()
    if reason is not None:
        missing.append(reason)
    address = _host_address()
    if address is None:
        missing.append("this host has no non-loopback IPv4 address for the control listener")
    if missing:
        pytest.fail("live jail unavailable: " + "; ".join(missing))
    assert address is not None
    return address


def test_live_jail_seat_reaches_its_proxy_and_nothing_else(
        tmp_path, monkeypatch, live_seat_attempt):
    host_address = _live_jail_or_fail()
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import sandbox_egress, seat_profiles, seat_uid

    monkeypatch.setattr(seat_egress_proxy, "allowlist_ref", _fixture_ref)
    profile = dataclasses.replace(
        seat_profiles.profile_for("gemini"), leg="fixture", vendor="fixture",
        allowlist_id="fixture-reach", window=None)
    monkeypatch.setitem(seat_profiles._REGISTRY, "fixture", profile)
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        other_port = unused.getsockname()[1]
    assert other_port != seat_egress_proxy.SEAT_PROXY_PORT
    listener = socket.create_server((host_address, 0))
    listener.settimeout(5)
    host_port = listener.getsockname()[1]
    # Positive control: the host itself reaches the listener, so a refusal from the seat is
    # the seat's network, not an unreachable address.
    with socket.create_connection((host_address, host_port), timeout=5):
        accepted, _peer = listener.accept()
        accepted.close()
    spec = json.dumps({"listed": LISTED, "unlisted": UNLISTED, "host_address": host_address,
                       "host_port": host_port, "other_port": other_port})
    base = tmp_path / "reach"
    review = base / "seat" / "review"
    tree = review / seat_jail.HOST_TREE_DIRNAME
    tree.mkdir(parents=True)
    (tree / "README").write_text("proxy reach probe tree\n", encoding="utf-8")
    seat_dir = base / "seat" / "dirs"
    seat_dir.mkdir(mode=0o700)
    uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
    gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
    try:
        with seat_egress_proxy.start_proxy(allowlist_id=profile.allowlist_id) as proxy:
            token = urllib.parse.urlsplit(proxy.proxy_url).password or proxy.proxy_url
            config = seat_dir / seat_jail.HOST_GEMINI_CONFIG_DIRNAME
            pi._write_gemini_config(config, b"")
            certificate = seat_dir / "egress-ca.pem"
            shutil.copyfile(proxy.ca_cert, certificate)
            certificate.chmod(0o444)
            with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
                    sandbox_egress.isolated_network(
                        timeout_s=900, required=True, seat_uid_map=True,
                        proxy_socket=proxy.socket,
                        proxy_port=seat_egress_proxy.SEAT_PROXY_PORT) as egress:
                prefix_token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
                holder = seat_uid.holder_pid_from_prefix(egress)
                jail = seat_jail.build_seat_jail(
                    "fixture", seat_dir, Path("/usr/bin/python3"), tree=tree,
                    bundle_memfd=seat_jail.memfd_with("b", b"B"),
                    instructions_memfd=seat_jail.memfd_with("i", b"I"),
                    token_fd=None, seat_ids=(n, n), gemini_config=config,
                    egress_ca=certificate, egress_proxy=proxy.proxy_url)
                try:
                    pi._require_canonical_jail(jail)
                    done = subprocess.run(
                        [*pi._compose_seat_jail_prefix(jail), "/usr/bin/python3", "-I", "-c",
                         _JAILED_PROBE, spec],
                        capture_output=True, text=True, timeout=900, pass_fds=jail.pass_fds,
                        env=pi._jail_launch_env(), stdin=subprocess.DEVNULL)
                finally:
                    seat_jail.close_jail_fds(jail)
                    for parent in (review, seat_dir):
                        seat_uid.teardown_in_h(holder, str(parent))
                    pi._EGRESS_LAUNCH_PREFIX.reset(prefix_token)
        listener.settimeout(1)
        try:
            stray, _peer = listener.accept()
        except (BlockingIOError, TimeoutError, socket.timeout):
            stray = None
        if stray is not None:
            stray.close()
    finally:
        listener.close()
    assert token not in done.stdout and token not in done.stderr
    assert done.returncode == 0, done.stderr[-400:]
    results = json.loads(done.stdout.strip().splitlines()[-1])
    assert UID_DROP_PROFILE not in (results["label"] or ""), results
    assert results["listed"].startswith("HTTP/1.1 200"), results
    assert results["unlisted"].startswith("HTTP/1.1 403"), results
    assert results["host_address"] in NETWORK_ERRORS, results
    assert stray is None, "the host listener received a connection from the seat"
    assert results["loopback_other_port"] == "ECONNREFUSED", results
    # A host without IPv6 in the seat's namespace has no such family at all.
    assert results["inet6_loopback"] in NETWORK_ERRORS | {"EAFNOSUPPORT"}, results
