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

import contextlib

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import warnings
import time

from .sandbox_policy import EgressPolicy, egress_allowlist

__all__ = [
    "EgressUnavailable",
    "SLIRP_UPLINK_CIDR",
    "PRIVATE_CIDRS",
    "egress_rules",
    "egress_isolation_available",
    "egress_required",
    "enforcement_report",
    "require_egress_isolation",
    "run_in_isolated_network",
    "isolated_network",
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


def egress_required() -> bool:
    """Isolation is REQUIRED by default; refusing is the policy, degrading is not.

    The plan states it directly: "Policy default is to REFUSE when a required property
    cannot be enforced, never to degrade silently." Four board rounds went the other way
    -- round 2 claimed filtering that was never applied, round 3 let a partial install
    claim `applied`, round 4 reported honestly and still launched unrestricted. Honest
    evidence plus open execution is still open execution.

    This costs nothing on a non-Linux coordinator, which cannot obtain review isolation at
    all (``backing.py`` refuses without Linux and ``bwrap``). It costs something on a Linux
    host without ``slirp4netns`` -- a bare CI container, for one -- so
    ``PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL=1`` makes isolation best-effort there. OPTIONAL,
    deliberately, rather than DISABLE: it must not drop filtering on a host that can do it.
    """
    return os.environ.get(
        "PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL", ""
    ).strip() not in ("1", "true", "yes")


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
    if not available and not egress_required():
        return {
            "network_filtered": False,
            "mechanism": None,
            "operator_opt_out": True,
            "reason": (
                "egress isolation unavailable on this host and "
                "PHASE_LOOP_SANDBOX_EGRESS_OPTIONAL is set; this seat was NOT "
                "network-restricted and could reach the private network"
            ),
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



@contextlib.contextmanager
def isolated_network(
    policy: EgressPolicy | None = None,
    *,
    timeout_s: float = 3600.0,
    required: bool | None = None,
):
    """Hold a filtered network namespace open and yield an argv PREFIX for it.

    This is the piece the board found missing. `run_in_isolated_network` ran a script in a
    namespace and was never reachable from the launch path, so a seat's evidence claimed
    filtering that was never applied to it. A prefix composes with the existing spawn --
    argv, cwd, env, stdin and process-group handling all stay exactly as they were, and the
    provider lands inside the namespace instead of beside it.

    ``timeout_s`` bounds how long the holder survives and must EXCEED the leg budget: at a
    fixed 600s a long leg outlived its own namespace mid-run. Callers with a known deadline
    should pass it.

    There are THREE ways this can fail -- the mechanism is absent, the namespace never
    comes up, and the rules fail to install -- and every one of them used to fall through to
    ``yield ()``. A caller-side ``require_egress_isolation()`` guards only the first, which
    is why the decision lives HERE, in the module that owns the policy: ``required`` makes
    all three raise :class:`EgressUnavailable`. It defaults to :func:`egress_required`.

    With ``required=False`` the degraded branches still ``yield ()`` and warn, so a
    best-effort caller can record truthfully rather than assume.
    """
    if required is None:
        required = egress_required()

    def _degrade(reason: str):
        if required:
            raise EgressUnavailable(reason)
        warnings.warn(reason, RuntimeWarning, stacklevel=3)
        return ()

    if not egress_isolation_available():
        yield _degrade(
            "egress isolation unavailable; refusing to launch WITHOUT network restriction"
        )
        return

    rules = "\n".join(f"iptables {rule}" for rule in egress_rules(policy))
    with tempfile.TemporaryDirectory(prefix="pl-egress-ns-") as work:
        ready = os.path.join(work, "ready")
        pidfile = os.path.join(work, "pid")
        holder = subprocess.Popen(
            ["unshare", "--net", "--map-root-user", "bash", "-c",
             f'echo $$ > {pidfile}; touch {ready}; sleep {timeout_s}'],
        )
        slirp = None
        try:
            deadline = time.monotonic() + 15
            while not os.path.exists(ready) and time.monotonic() < deadline:
                time.sleep(0.05)
            if not os.path.exists(ready):
                yield _degrade("network namespace did not come up; launch is UNISOLATED")
                return
            nspid = Path(pidfile).read_text(encoding="utf-8").strip()

            slirp = subprocess.Popen(
                ["slirp4netns", "--configure", "--mtu=65520",
                 "--disable-host-loopback", nspid, "tap0"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(2.5)  # the tap must be configured before traffic flows

            admin = ("nsenter", "--net", "-t", nspid, "-U", "--preserve-credentials")
            # Apply the policy INSIDE the namespace, before anything else runs in it, and
            # CHECK it: a partially installed ruleset that still yielded a prefix would be
            # reported as applied filtering while leaving holes.
            installed = subprocess.run(
                [*admin, "bash", "-c",
                 "set -e\nip link set lo up 2>/dev/null || true\n" + rules],
                capture_output=True, text=True, timeout=30,
            )
            if installed.returncode != 0:
                # A PARTIAL ruleset is the worst outcome of the three: the namespace is up,
                # so everything downstream looks isolated while specific denies are missing.
                yield _degrade(
                    "egress rules failed to install "
                    f"({installed.stderr.strip()[:120]}); launch is UNISOLATED"
                )
                return

            # The seat runs with the capability bounding set EMPTIED. Without this the
            # provider holds CAP_NET_ADMIN over the very namespace that confines it: board
            # round 3 demonstrated `iptables -F OUTPUT` taking qdrant from BLOCKED to 200 in
            # one command. Rules a reviewer can withdraw are a suggestion, not a boundary.
            # Emptying the BOUNDING set (not merely the effective one) means the capability
            # cannot be regained by re-exec either.
            prefix = (*admin, "setpriv", "--bounding-set=-all", "--inh-caps=-all", "--")
            yield prefix
        finally:
            if slirp is not None:
                slirp.terminate()
            holder.terminate()


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
