"""Skip guards for the seat-jail tests (agent-harness#1132).

One literal per missing prerequisite, so every gated test says the same thing and a skip
can never be mistaken for a pass. The D8 host prerequisite is run once per host by the
maintainer, as root; these tests never run it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache

import pytest

SEAT_UID_PREREQUISITE = (
    "D8 host prerequisite missing: newuidmap/newgidmap absent or no /etc/subuid and "
    "/etc/subgid range for the operator; maintainer prerequisite (root, once per host): "
    "apt install uidmap + usermod --add-subuids/--add-subgids <operator>"
)
SEAT_TOKEN_PREREQUISITE = (
    "no Claude seat credential: run `claude auth login`, or store a `claude setup-token` token "
    "owner-only at $XDG_STATE_HOME/phase-loop/seat-credentials/claude"
)
USERNS_UNAVAILABLE = "unprivileged bwrap user namespaces unavailable on this host"
NESTED_NAMESPACE_REFUSED = (
    "this host refuses a namespace nested inside unprivileged bwrap: on Ubuntu 25.04 and later "
    "the bwrap-userns-restrict AppArmor profile runs bwrap's children as `unpriv_bwrap`, which "
    "denies every capability. This is host policy, probed with no runtime code in the path"
)

#: With this set to 1, a capability gate FAILS instead of skipping, so a host that is meant
#: to run the live tests cannot pass them by skipping.
REQUIRE_LIVE_JAIL_ENV = "PHASE_LOOP_REQUIRE_LIVE_JAIL"


def skip_unless_capable(reason: str | None) -> None:
    """``None`` means the host is capable. Otherwise skip with ``reason``, or fail with it
    under ``PHASE_LOOP_REQUIRE_LIVE_JAIL=1``."""
    if reason is None:
        return
    if os.environ.get(REQUIRE_LIVE_JAIL_ENV) == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@lru_cache(maxsize=1)
def unprivileged_bwrap_ok() -> bool:
    if not os.access("/usr/bin/bwrap", os.X_OK):
        return False
    try:
        done = subprocess.run(
            ["/usr/bin/bwrap", "--unshare-user", "--ro-bind", "/", "/", "true"],
            capture_output=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def seat_uid_ready() -> bool:
    from phase_loop_runtime import seat_uid

    return seat_uid.seat_uid_available()


requires_userns = pytest.mark.skipif(not unprivileged_bwrap_ok(), reason=USERNS_UNAVAILABLE)


def require_seat_uid() -> None:
    if not seat_uid_ready():
        pytest.skip(SEAT_UID_PREREQUISITE)


@lru_cache(maxsize=1)
def seat_uid_switch_refusal() -> str | None:
    """The runtime's own verdict on this host's seat uid switch, or ``None`` if it works.

    This runs the first step of the seat-jail qualification
    (``seat_jail_qualification._run_probe_in_jail``) with a no-op command: a seat id leased
    from the subordinate range, the seat-uid holder, the production jail and
    ``panel_invoker._compose_seat_jail_prefix``. Only a confirmed denial
    (:func:`uid_switch_verdict`) is a refusal. Any other outcome, a probe error included, is
    ``None``: the gated tests then run and report it, so a defect still fails them. Without
    the D8 prerequisites there is nothing to probe, and the tests' own gates apply.
    """
    import tempfile
    from pathlib import Path

    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import sandbox_egress, seat_jail, seat_uid

    if not (hasattr(os, "memfd_create") and seat_uid_ready()
            and sandbox_egress.egress_isolation_available()):
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="pl-uid-switch-probe-",
                                         ignore_cleanup_errors=True) as scratch:
            review = Path(scratch) / "review"
            tree = review / seat_jail.HOST_TREE_DIRNAME
            tree.mkdir(parents=True)
            seat_dir = Path(scratch) / "seat"
            seat_dir.mkdir(mode=0o700)
            uids = seat_uid.subordinate_range(seat_uid.SUBUID_FILE)
            gids = seat_uid.subordinate_range(seat_uid.SUBGID_FILE)
            with seat_uid.lease_seat_id(seat_uid.seat_id_count(uids, gids)) as n, \
                    sandbox_egress.isolated_network(timeout_s=120, required=True,
                                                    seat_uid_map=True) as egress:
                token = pi._EGRESS_LAUNCH_PREFIX.set(tuple(egress))
                holder = seat_uid.holder_pid_from_prefix(egress)
                jail = seat_jail.build_seat_jail(
                    "claude", seat_dir, Path("/usr/bin/true"), tree=tree,
                    bundle_memfd=seat_jail.memfd_with("b", b"B"),
                    instructions_memfd=seat_jail.memfd_with("i", b"I"),
                    token_fd=seat_jail.token_pipe(b"UID-SWITCH-PROBE"), seat_ids=(n, n))
                try:
                    pi._require_canonical_jail(jail)
                    done = subprocess.run(
                        [*pi._compose_seat_jail_prefix(jail), "/bin/sh", "-c", "exit 0"],
                        capture_output=True, text=True, timeout=60, pass_fds=jail.pass_fds,
                        env=pi._jail_launch_env(), stdin=subprocess.DEVNULL)
                finally:
                    seat_jail.close_jail_fds(jail)
                    for parent in (review, seat_dir):
                        seat_uid.teardown_in_h(holder, str(parent))
                    pi._EGRESS_LAUNCH_PREFIX.reset(token)
    except Exception:  # noqa: BLE001 - not a refusal: the tests run and report it
        return None
    return uid_switch_verdict(done)


#: util-linux ``setpriv``'s exit status when a privilege change fails (SETPRIV_EXIT_PRIVERR).
SETPRIV_PRIVERR_EXIT = 127
#: The exact final stderr line of a denied uid or gid switch (EPERM or EACCES).
UID_SWITCH_DENIAL = re.compile(
    r"setpriv: setres[ug]id failed: (?:Operation not permitted|Permission denied)")


def uid_switch_verdict(done: subprocess.CompletedProcess) -> str | None:
    """The refusal reason only for a CONFIRMED denial: setpriv's privilege-error exit status,
    an exact denial line, and the runtime classifier's ``uid_switch_denied``. Any other
    outcome is ``None``, so the test runs and reports it; this gate never skips on an error."""
    from phase_loop_runtime import seat_jail_autoqualify
    from phase_loop_runtime.seat_jail_qualification import QualificationError

    if done.returncode != SETPRIV_PRIVERR_EXIT:
        return None
    stderr = done.stderr[-400:]
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    if not lines or not UID_SWITCH_DENIAL.fullmatch(lines[-1].strip()):
        return None
    reason = seat_jail_autoqualify.classify_failure(
        QualificationError(f"probe failed to run: {stderr}"))
    if reason != "uid_switch_denied":
        return None
    return (f"seat jail qualification would fail on this host with uid_switch_denied "
            f"[{lines[-1].strip()}]: {seat_jail_autoqualify.REASON_FIXES[reason]}")


def require_seat_uid_switch() -> None:
    """Skip (or, under PHASE_LOOP_REQUIRE_LIVE_JAIL=1, fail) where the seat cannot become its
    uid inside bwrap. See :func:`seat_uid_switch_refusal`."""
    skip_unless_capable(seat_uid_switch_refusal())


#: The exit status with which util-linux ``unshare`` (``err(EXIT_FAILURE, ...)``) and
#: ``bwrap`` (``die``) report a refused namespace. The outer ``bwrap`` passes it through.
NAMESPACE_REFUSAL_EXIT = 1

#: The exact final stderr lines of a namespace PERMISSION refusal: EPERM or EACCES from
#: ``unshare(2)`` or ``clone(2)``, as ``unshare`` and ``bwrap`` word it. Any other line
#: (ENOSPC "nesting depth", ENOENT, a mount failure, ...) is not a refusal.
NAMESPACE_PERMISSION_REFUSALS = (
    re.compile(r"unshare: unshare failed: (?:Operation not permitted|Permission denied)"),
    re.compile(r"bwrap: No permissions to creat(?:e a new|ing new) namespace(?:,.*)?"),
    re.compile(r"bwrap: Creating new namespace failed: "
               r"(?:Operation not permitted|Permission denied)"),
)


def nested_namespace_verdict(done: subprocess.CompletedProcess) -> str | None:
    """``None`` if the nested step ran, or the refusal reason for a CONFIRMED namespace
    permission refusal: the refusal exit status AND an exact refusal line. Anything else (a
    signal, another exit status, other text) FAILS the test, because it is not host policy."""
    if done.returncode == 0:
        return None
    stderr = done.stderr if isinstance(done.stderr, str) else (done.stderr or b"").decode(
        "utf-8", "replace")
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    last = lines[-1].strip() if lines else ""
    if done.returncode == NAMESPACE_REFUSAL_EXIT and any(
            pattern.fullmatch(last) for pattern in NAMESPACE_PERMISSION_REFUSALS):
        return f"{NESTED_NAMESPACE_REFUSED} [{last[:200]}]"
    pytest.fail(f"nested-namespace probe failed, and not with a namespace permission refusal: "
                f"exit {done.returncode}, stderr {stderr[-300:]!r}")


@lru_cache(maxsize=None)
def nested_namespace_refusal(inner: tuple[str, ...]) -> str | None:
    """Why this host refuses to run ``inner`` inside an unprivileged ``bwrap`` with its own
    user and pid namespaces, or ``None`` if it can. ``inner`` is the test's own nested
    step, ending in a no-op. This is a pure host probe: no runtime code is in the path.

    Only a confirmed permission refusal (:func:`nested_namespace_verdict`) is a refusal. A
    timeout, an exec or I/O error, a signal or any other failure FAILS the calling test.
    The one other refusal is ``/usr/bin/bwrap`` missing, a prerequisite like the others
    here. Both go through :func:`skip_unless_capable`, so strict mode fails on them too."""
    if not os.access("/usr/bin/bwrap", os.X_OK):
        return USERNS_UNAVAILABLE
    try:
        done = subprocess.run(
            ["/usr/bin/bwrap", "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/",
             "--proc", "/proc", "--dev", "/dev", "--", *inner],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"nested-namespace probe timed out after {exc.timeout}s")
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.fail(f"nested-namespace probe could not run: {exc!r}")
    return nested_namespace_verdict(done)


#: A multicall binary's own refusal of a file name it does not dispatch: uutils coreutils
#: (Ubuntu 26.04's default ``sleep``) and BusyBox.
MULTICALL_NAME_REFUSALS = (
    re.compile(r"coreutils: unknown program '?provider'?"),
    re.compile(r"provider: applet not found"),
)


def sleep_runnable_as_seat_provider(directory) -> str:
    """The name of a ``sleep`` on PATH that still sleeps when its file is named
    ``provider``, which is how the seat runs a probe's executable
    (``/run/phase-loop-seat/provider``). Each candidate is tried as a copy named
    ``provider``. A candidate that refuses the name exactly as a multicall binary does is
    incompatible. Any other copy or launch error, timeout or exit FAILS the test. If no
    candidate is compatible, :func:`skip_unless_capable` decides."""
    from pathlib import Path

    incompatible = []
    for name in ("sleep", "gnusleep"):
        source = shutil.which(name)
        if source is None:
            continue
        named = Path(directory) / name / "provider"
        try:
            named.parent.mkdir(parents=True)
            shutil.copy2(source, named)
        except OSError as exc:
            pytest.fail(f"could not copy {source} as `provider`: {exc!r}")
        try:
            done = subprocess.run([str(named), "0"], capture_output=True, text=True,
                                  timeout=10, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            pytest.fail(f"{source} copied as `provider` did not finish `0` within 10s")
        except (OSError, subprocess.SubprocessError) as exc:
            pytest.fail(f"could not run {source} copied as `provider`: {exc!r}")
        if done.returncode == 0:
            return name
        lines = [line for line in done.stderr.strip().splitlines() if line.strip()]
        last = lines[-1].strip() if lines else ""
        if done.returncode > 0 and any(p.fullmatch(last) for p in MULTICALL_NAME_REFUSALS):
            incompatible.append(f"{name}: {last}")
            continue
        pytest.fail(f"{source} copied as `provider` failed unexpectedly: exit "
                    f"{done.returncode}, stderr {done.stderr[-300:]!r}")
    skip_unless_capable(
        "no `sleep` on PATH runs from a file named `provider`, as the seat runs a probe "
        f"({'; '.join(incompatible) or 'no sleep or gnusleep on PATH'})")
    raise AssertionError("unreachable")  # pragma: no cover - skip_unless_capable raised


def require_seat_token() -> None:
    """A Claude seat credential: a stored override that applies to this session (plan
    amendment A4), or the user's Claude login (plan amendment A1)."""
    from phase_loop_runtime import seat_credentials

    if seat_credentials.override_decision().applies:
        return
    if seat_credentials.read_login_token() is None:
        pytest.skip(SEAT_TOKEN_PREREQUISITE)


def have(tool: str) -> bool:
    return shutil.which(tool) is not None
