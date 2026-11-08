"""Skip guards for the seat-jail tests (agent-harness#1132).

One literal per missing prerequisite, so every gated test says the same thing and a skip
can never be mistaken for a pass. The D8 host prerequisite is run once per host by the
maintainer, as root; these tests never run it.
"""

from __future__ import annotations

import os
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
    ``panel_invoker._compose_seat_jail_prefix``. A failure is typed by
    ``seat_jail_autoqualify.classify_failure``, the classifier that first-use qualification
    applies to the same probe. Only ``uid_switch_denied`` is a refusal. Any other outcome is
    left to the tests themselves, so a defect still fails them. Without the D8
    prerequisites there is nothing to probe, and the tests' own gates apply.
    """
    import tempfile
    from pathlib import Path

    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import sandbox_egress, seat_jail, seat_jail_autoqualify, seat_uid
    from phase_loop_runtime.seat_jail_qualification import QualificationError

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
    if done.returncode == 0:
        return None
    stderr = done.stderr[-400:]
    reason = seat_jail_autoqualify.classify_failure(
        QualificationError(f"probe failed to run: {stderr}"))
    if reason != "uid_switch_denied":
        return None
    return (f"seat jail qualification would fail on this host with uid_switch_denied "
            f"[{stderr.strip()}]: {seat_jail_autoqualify.REASON_FIXES[reason]}")


def require_seat_uid_switch() -> None:
    """Skip (or, under PHASE_LOOP_REQUIRE_LIVE_JAIL=1, fail) where the seat cannot become its
    uid inside bwrap. See :func:`seat_uid_switch_refusal`."""
    skip_unless_capable(seat_uid_switch_refusal())


@lru_cache(maxsize=None)
def nested_namespace_refusal(inner: tuple[str, ...]) -> str | None:
    """Why this host cannot run ``inner`` inside an unprivileged ``bwrap`` with its own user
    and pid namespaces, or ``None`` if it can. ``inner`` is the test's own nested step,
    ending in a no-op. This is a pure host probe: no runtime code is in the path."""
    if not os.access("/usr/bin/bwrap", os.X_OK):
        return USERNS_UNAVAILABLE
    try:
        done = subprocess.run(
            ["/usr/bin/bwrap", "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/",
             "--proc", "/proc", "--dev", "/dev", "--", *inner],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{NESTED_NAMESPACE_REFUSED} [{type(exc).__name__}]"
    if done.returncode == 0:
        return None
    return f"{NESTED_NAMESPACE_REFUSED} [{done.stderr.strip()[-200:]}]"


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
