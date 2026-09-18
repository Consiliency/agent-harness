"""Enforce the sandbox egress policy: public internet yes, private network no.

A panelist needs the internet -- to search, read documentation, and install what a check
requires -- so blanket denial is the wrong boundary. What must stay unreachable is
everything *inside*: the rest of the tailnet, loopback services (the review broker among
them), the docker bridges, and cloud metadata.

**Enforcement is real, and unprivileged.** Inside a user namespace we hold ``NET_ADMIN``
for that namespace, so ``iptables`` rules there are binding. ``slirp4netns`` supplies the
uplink in userspace. Nothing needs root, a sudoers entry, or a container runtime, which
also means it behaves the same for any operator rather than depending on how a host was
set up.

The alternative -- exporting ``HTTP_PROXY`` and filtering at a proxy -- was rejected. It is
honoured only by programs that choose to honour it: a raw socket, or a tool that ignores
the variables, walks straight past. That is a speed bump, and recording it as "network
filtered" would be a fail-open in the evidence record.

Measured on this host before it was built:

=================  ==========  ==========================================
target             result      note
=================  ==========  ==========================================
``1.1.1.1``        ``301``     public internet reachable
``ai:8020``        ``200``     inference router, allowlisted host+port
``ai:6333``        BLOCKED     qdrant, ~69 GB of user data, same machine
``169.254.169.254``  BLOCKED   cloud metadata / credential-theft target
=================  ==========  ==========================================
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time

from .sandbox_policy import EgressPolicy, egress_allowlist

__all__ = [
    "EgressUnavailable",
    "SLIRP_UPLINK_CIDR",
    "PRIVATE_CIDRS",
    "egress_rules",
    "egress_isolation_available",
    "enforcement_report",
    "require_egress_isolation",
    "run_in_isolated_network",
]

# slirp4netns puts the uplink here. It sits INSIDE 10/8, so denying 10/8 without
# re-allowing this first kills every connection including the ones we mean to permit.
SLIRP_UPLINK_CIDR = "10.0.2.0/24"

PRIVATE_CIDRS: tuple[str, ...] = (
    "10.0.0.0/8",        # RFC1918 + the docker bridges
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",     # CGNAT: the tailnet. Neither "private" nor "global" to Python.
    "169.254.0.0/16",    # link-local, and cloud metadata at .169.254
    "127.0.0.0/8",       # loopback services, including the review broker socket
)


class EgressUnavailable(RuntimeError):
    """Egress isolation was required and could not be enforced."""


def egress_rules(policy: EgressPolicy | None = None) -> list[str]:
    """The iptables rules, in the order they must be applied.

    Order IS the policy. The allowlisted endpoints come first, because they live inside
    ``100.64.0.0/10`` and a deny for that range would otherwise swallow them. The uplink
    subnet comes before the ``10/8`` deny for the same reason.
    """
    policy = policy or egress_allowlist()
    rules = [f"-I OUTPUT 1 -d {SLIRP_UPLINK_CIDR} -j ACCEPT"]
    rules += [
        f"-A OUTPUT -d {host} -p tcp --dport {port} -j ACCEPT"
        for host, port in policy.allow
    ]
    rules += [f"-A OUTPUT -d {cidr} -j REJECT" for cidr in PRIVATE_CIDRS]
    return rules


def egress_isolation_available() -> bool:
    """Can this host enforce the policy at all?

    Checked by trying it, not by inspecting the platform: a kernel flag, a seccomp profile
    or a container runtime can each remove unprivileged user namespaces without changing
    anything observable about the OS.
    """
    if not (shutil.which("unshare") and shutil.which("slirp4netns") and shutil.which("iptables")):
        return False
    try:
        return subprocess.run(
            ["unshare", "--net", "--map-root-user", "true"],
            capture_output=True, timeout=10,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def enforcement_report(
    available: bool | None = None, *, applied: bool = False,
) -> dict[str, object]:
    """What this sandbox ACTUALLY enforced, for the review evidence.

    Never what it intended. A sandbox that records ``network_filtered: true`` without
    having filtered anything is worse than one that admits it could not: the first is
    believed.
    """
    if available is None:
        available = egress_isolation_available()
    if available and applied:
        return {
            "network_filtered": True,
            "mechanism": "user-namespace+slirp4netns",
            "denied": list(PRIVATE_CIDRS),
            "allowed": [f"{h}:{p}" for h, p in egress_allowlist().allow],
        }
    if available and not applied:
        # The board caught this: the mechanism was built and verified, the report was
        # wired into the evidence, and NO provider was ever launched through
        # `run_in_isolated_network`. The record therefore claimed a boundary that was not
        # in force -- the exact fail-open this module exists to prevent, inside the module
        # that prevents it. Until the launch path routes through the namespace, the record
        # says so.
        return {
            "network_filtered": False,
            "mechanism": None,
            "available_but_unapplied": True,
            "reason": (
                "egress isolation is AVAILABLE on this host but the provider launch does "
                "not yet run through it; this seat was NOT network-restricted"
            ),
        }
    return {
        "network_filtered": False,
        "mechanism": None,
        "reason": (
            "unprivileged user namespaces or slirp4netns unavailable; egress was NOT "
            "restricted and this seat could reach the private network"
        ),
    }


def require_egress_isolation(available: bool | None = None) -> None:
    """Refuse rather than run a seat that believes it is isolated and is not."""
    if available is None:
        available = egress_isolation_available()
    if not available:
        raise EgressUnavailable(enforcement_report(False)["reason"])


def run_in_isolated_network(
    script: str,
    *,
    timeout_s: float = 120.0,
    policy: EgressPolicy | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> str:
    """Run ``script`` in a network namespace carrying the egress policy.

    Returns combined output. Raises :class:`EgressUnavailable` when the mechanism is not
    available, rather than silently running without isolation.
    """
    require_egress_isolation()
    rules = "\n".join(f"iptables {rule}" for rule in egress_rules(policy))

    with tempfile.TemporaryDirectory(prefix="pl-egress-") as work:
        ready = os.path.join(work, "ready")
        pidfile = os.path.join(work, "pid")
        payload = os.path.join(work, "payload.sh")
        with open(payload, "w", encoding="utf-8") as handle:
            handle.write(
                "set -e\n"
                "ip link set lo up 2>/dev/null || true\n"
                f"{rules}\n"
                + (f"cd {cwd}\n" if cwd else "")
                + script
                + "\n"
            )

        holder = subprocess.Popen(
            ["unshare", "--net", "--map-root-user", "bash", "-c",
             f'echo $$ > {pidfile}; touch {ready}; sleep {timeout_s + 10}'],
        )
        try:
            deadline = time.monotonic() + 15
            while not os.path.exists(ready) and time.monotonic() < deadline:
                time.sleep(0.1)
            if not os.path.exists(ready):
                raise EgressUnavailable("network namespace did not come up")
            with open(pidfile, encoding="utf-8") as handle:
                nspid = handle.read().strip()

            slirp = subprocess.Popen(
                ["slirp4netns", "--configure", "--mtu=65520",
                 "--disable-host-loopback", nspid, "tap0"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                time.sleep(2.5)  # slirp needs the tap configured before traffic flows
                return subprocess.run(
                    ["nsenter", "--net", "-t", nspid, "-U", "--preserve-credentials",
                     "bash", payload],
                    capture_output=True, text=True, timeout=timeout_s,
                ).stdout
            finally:
                slirp.terminate()
        finally:
            holder.terminate()
