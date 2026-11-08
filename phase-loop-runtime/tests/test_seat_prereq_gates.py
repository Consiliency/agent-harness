"""The host-capability gates in ``_seat_prereq``, with the host mocked.

A gate may skip only on a CONFIRMED capability refusal; every other probe outcome (a
timeout, an exec or I/O error, a signal, an unexpected exit or text) fails the test. Every
skip path fails instead under ``PHASE_LOOP_REQUIRE_LIVE_JAIL=1``.
"""

from __future__ import annotations

import errno
import os
import re
import subprocess
import sys

import pytest

from . import _seat_prereq as prereq

SKIPPED = pytest.skip.Exception
FAILED = pytest.fail.Exception
STRICT = prereq.REQUIRE_LIVE_JAIL_ENV
INNER = ("/usr/bin/unshare", "--user", "--pid", "--fork", "/usr/bin/true")

UNSHARE_EPERM = "unshare: unshare failed: Operation not permitted\n"
UNSHARE_EACCES = "unshare: unshare failed: Permission denied\n"
BWRAP_EPERM = ("bwrap: No permissions to create a new namespace, likely because the kernel "
               "does not allow non-privileged user namespaces. See <https://deb.li/bubblewrap> "
               "or <file:///usr/share/doc/bubblewrap/README.Debian.gz>.\n")
BWRAP_EPERM_UPSTREAM = ("bwrap: No permissions to creating new namespace, likely because the "
                        "kernel does not allow non-privileged user namespaces.\n")
BWRAP_EACCES = "bwrap: Creating new namespace failed: Permission denied\n"
BWRAP_ENOSPC = ("bwrap: Creating new namespace failed: nesting depth or "
                "/proc/sys/user/max_*_namespaces exceeded (ENOSPC)\n")
SETPRIV_EPERM = "setpriv: setresuid failed: Operation not permitted\n"


@pytest.fixture(autouse=True)
def _lenient(monkeypatch):
    monkeypatch.delenv(STRICT, raising=False)
    prereq.nested_namespace_refusal.cache_clear()
    yield
    prereq.nested_namespace_refusal.cache_clear()


def _fails(match, fn, *args):
    """``fn(*args)`` must FAIL with ``match``. A skip is a failure of this test, so a gate
    that regresses to skipping cannot pass by being skipped."""
    try:
        fn(*args)
    except FAILED as exc:
        assert re.search(match, str(exc)), str(exc)
        return
    except SKIPPED as exc:
        pytest.fail(f"expected a failure matching {match!r}, got a skip: {exc}")
    pytest.fail(f"expected a failure matching {match!r}, got none")


def _done(returncode, stderr=""):
    return subprocess.CompletedProcess(["probe"], returncode, "", stderr)


def _bwrap_present(monkeypatch, present=True):
    real = os.access

    def access(path, mode, *args, **kwargs):
        if str(path) == "/usr/bin/bwrap":
            return present
        return real(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "access", access)


def _host_run(monkeypatch, outcome):
    """``subprocess.run`` for the probe: return ``outcome``, or raise it."""

    def run(argv, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(prereq.subprocess, "run", run)


# --------------------------------------------------------------------------------------
# skip_unless_capable: the one strict-mode switch.
# --------------------------------------------------------------------------------------

def test_capable_host_neither_skips_nor_fails(monkeypatch):
    prereq.skip_unless_capable(None)
    monkeypatch.setenv(STRICT, "1")
    prereq.skip_unless_capable(None)


@pytest.mark.parametrize("value", [None, "0", "", "yes"])
def test_a_refusal_skips_unless_strict_mode_is_exactly_1(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv(STRICT, value)
    with pytest.raises(SKIPPED, match="REASON-SENTINEL"):
        prereq.skip_unless_capable("REASON-SENTINEL")


def test_strict_mode_turns_a_refusal_into_a_failure(monkeypatch):
    monkeypatch.setenv(STRICT, "1")
    _fails("REASON-SENTINEL", prereq.skip_unless_capable, "REASON-SENTINEL")


# --------------------------------------------------------------------------------------
# The nested-namespace gate: a skip only on a confirmed permission refusal.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("stderr", [UNSHARE_EPERM, UNSHARE_EACCES, BWRAP_EPERM,
                                    BWRAP_EPERM_UPSTREAM, BWRAP_EACCES])
def test_nested_permission_refusal_skips_and_fails_in_strict_mode(monkeypatch, stderr):
    _bwrap_present(monkeypatch)
    _host_run(monkeypatch, _done(1, stderr))
    reason = prereq.nested_namespace_refusal(INNER)
    assert reason is not None and stderr.strip()[:60] in reason
    with pytest.raises(SKIPPED):
        prereq.skip_unless_capable(reason)
    monkeypatch.setenv(STRICT, "1")
    _fails("", prereq.skip_unless_capable, reason)


def test_nested_probe_that_runs_is_capable(monkeypatch):
    _bwrap_present(monkeypatch)
    _host_run(monkeypatch, _done(0))
    assert prereq.nested_namespace_refusal(INNER) is None


def test_nested_probe_timeout_fails(monkeypatch):
    _bwrap_present(monkeypatch)
    _host_run(monkeypatch, subprocess.TimeoutExpired(["bwrap"], 30))
    _fails("timed out", prereq.nested_namespace_refusal, INNER)


def test_nested_probe_io_error_fails(monkeypatch):
    _bwrap_present(monkeypatch)
    _host_run(monkeypatch, OSError(errno.EIO, "Input/output error"))
    _fails("could not run", prereq.nested_namespace_refusal, INNER)


@pytest.mark.parametrize("returncode,stderr", [
    (-9, ""),                                       # killed by a signal
    (-9, UNSHARE_EPERM),                            # refusal text, but a signal
    (2, UNSHARE_EPERM),                             # refusal text, wrong exit status
    (127, BWRAP_EPERM),
    (1, BWRAP_ENOSPC),                              # namespace limit, not permission
    (1, "bwrap: execvp /usr/bin/true: No such file or directory\n"),
    (1, "bwrap: Can't mount proc on /newroot/proc: Operation not permitted\n"),
    (1, UNSHARE_EPERM + "a later line\n"),          # refusal not the final line
    (1, ""),
])
def test_nested_probe_other_failures_fail(monkeypatch, returncode, stderr):
    _bwrap_present(monkeypatch)
    _host_run(monkeypatch, _done(returncode, stderr))
    _fails("not with a namespace permission refusal", prereq.nested_namespace_refusal, INNER)


def test_missing_bwrap_is_a_capability_skip_and_fails_in_strict_mode(monkeypatch):
    _bwrap_present(monkeypatch, present=False)
    reason = prereq.nested_namespace_refusal(INNER)
    assert reason == prereq.USERNS_UNAVAILABLE
    with pytest.raises(SKIPPED):
        prereq.skip_unless_capable(reason)
    monkeypatch.setenv(STRICT, "1")
    _fails("", prereq.skip_unless_capable, reason)


# --------------------------------------------------------------------------------------
# The uid-switch gate: a refusal only on a confirmed denial; never a skip on an error.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("stderr", [SETPRIV_EPERM,
                                    "setpriv: setresgid failed: Permission denied\n"])
def test_uid_switch_denial_is_the_runtime_uid_switch_denied_reason(stderr):
    from phase_loop_runtime import seat_jail_autoqualify

    reason = prereq.uid_switch_verdict(_done(prereq.SETPRIV_PRIVERR_EXIT, stderr))
    assert reason is not None and "uid_switch_denied" in reason
    assert seat_jail_autoqualify.REASON_FIXES["uid_switch_denied"] in reason


@pytest.mark.parametrize("returncode,stderr", [
    (0, ""),
    (1, SETPRIV_EPERM),                             # denial text, wrong exit status
    (-9, SETPRIV_EPERM),
    (127, "setpriv: unknown capability: x\n"),
    (127, SETPRIV_EPERM + "a later line\n"),
    (127, ""),
])
def test_uid_switch_other_outcomes_are_not_refusals(returncode, stderr):
    assert prereq.uid_switch_verdict(_done(returncode, stderr)) is None


def test_uid_switch_gate_skips_and_fails_in_strict_mode(monkeypatch):
    monkeypatch.setattr(prereq, "seat_uid_switch_refusal", lambda: "DENIED-SENTINEL")
    with pytest.raises(SKIPPED, match="DENIED-SENTINEL"):
        prereq.require_seat_uid_switch()
    monkeypatch.setenv(STRICT, "1")
    _fails("DENIED-SENTINEL", prereq.require_seat_uid_switch)


def _live_worker_prerequisites(monkeypatch):
    from phase_loop_runtime import panel_invoker as pi
    from phase_loop_runtime import sandbox_egress, seat_jail, seat_uid

    monkeypatch.setattr(seat_uid, "seat_uid_available", lambda *a, **k: True)
    monkeypatch.setattr(prereq, "seat_uid_ready", lambda: True)
    monkeypatch.setattr(sandbox_egress, "egress_isolation_available", lambda: True)
    for module, name in ((pi, "_PRLIMIT"), (seat_jail, "BWRAP"),
                         (pi, "_CLAUDE_SDK_WORKER_DROP_TOOL")):
        monkeypatch.setattr(module, name, sys.executable)
    monkeypatch.setattr(prereq, "seat_uid_switch_refusal", lambda: "DENIED-SENTINEL")


@pytest.mark.skipif(not hasattr(os, "memfd_create"), reason="needs os.memfd_create")
@pytest.mark.parametrize("module", ["test_seats_claude_sdk", "test_seats_claude_transport"])
def test_live_worker_uid_switch_refusal_skips_and_fails_in_strict_mode(monkeypatch, module):
    import importlib

    tests = importlib.import_module(f"{__package__}.{module}")
    _live_worker_prerequisites(monkeypatch)
    with pytest.raises(SKIPPED, match="live worker unavailable: DENIED-SENTINEL"):
        tests.require_live_worker()
    monkeypatch.setenv(STRICT, "1")
    _fails("live worker unavailable: DENIED-SENTINEL", tests.require_live_worker)


# --------------------------------------------------------------------------------------
# The seat-provider sleep: incompatible only on a multicall name refusal; else a failure.
# --------------------------------------------------------------------------------------

def _candidates(monkeypatch, tmp_path, **found):
    """``shutil.which`` finds each named candidate as a real file under ``tmp_path``."""
    sources = {}
    for name, present in found.items():
        if present:
            source = tmp_path / "bin" / name
            source.parent.mkdir(exist_ok=True)
            source.write_text("#!/bin/sh\n")
            source.chmod(0o755)
            sources[name] = str(source)
    monkeypatch.setattr(prereq.shutil, "which", lambda name, *a, **k: sources.get(name))
    return sources


def _runs(monkeypatch, outcomes):
    """``subprocess.run`` for each copied candidate, in order."""
    pending = list(outcomes)

    def run(argv, **kwargs):
        assert argv[0].endswith("/provider") and argv[1:] == ["0"]
        outcome = pending.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(prereq.subprocess, "run", run)


MULTICALL = _done(1, "coreutils: unknown program 'provider'\n")


def test_sleep_compatible_candidate_is_chosen(monkeypatch, tmp_path):
    _candidates(monkeypatch, tmp_path, sleep=True, gnusleep=True)
    _runs(monkeypatch, [MULTICALL, _done(0)])
    assert prereq.sleep_runnable_as_seat_provider(tmp_path / "work") == "gnusleep"
    assert (tmp_path / "work" / "gnusleep" / "provider").is_file()


@pytest.mark.parametrize("found", [dict(sleep=True, gnusleep=True), dict(sleep=True),
                                   dict(sleep=False, gnusleep=False)])
def test_sleep_none_compatible_skips_and_fails_in_strict_mode(monkeypatch, tmp_path, found):
    _candidates(monkeypatch, tmp_path, **found)
    _runs(monkeypatch, [MULTICALL, _done(1, "provider: applet not found\n")])
    with pytest.raises(SKIPPED, match="no `sleep` on PATH runs from a file named `provider`"):
        prereq.sleep_runnable_as_seat_provider(tmp_path / "lenient")
    monkeypatch.setenv(STRICT, "1")
    _runs(monkeypatch, [MULTICALL, _done(1, "provider: applet not found\n")])
    _fails("no `sleep` on PATH runs from a file named `provider`",
           prereq.sleep_runnable_as_seat_provider, tmp_path / "strict")


def test_sleep_copy_error_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(prereq.shutil, "which", lambda name, *a, **k: (
        str(tmp_path / "vanished-sleep") if name == "sleep" else None))
    _fails("could not copy", prereq.sleep_runnable_as_seat_provider, tmp_path / "work")


def test_sleep_launch_io_error_fails(monkeypatch, tmp_path):
    _candidates(monkeypatch, tmp_path, sleep=True, gnusleep=True)
    _runs(monkeypatch, [OSError(errno.EIO, "Input/output error")])
    _fails("could not run", prereq.sleep_runnable_as_seat_provider, tmp_path / "work")


def test_sleep_launch_timeout_fails(monkeypatch, tmp_path):
    _candidates(monkeypatch, tmp_path, sleep=True, gnusleep=True)
    _runs(monkeypatch, [subprocess.TimeoutExpired(["provider", "0"], 10)])
    _fails("did not finish", prereq.sleep_runnable_as_seat_provider, tmp_path / "work")


@pytest.mark.parametrize("outcome", [
    _done(1, "sleep: invalid time interval '0'\n"),
    _done(-9, "coreutils: unknown program 'provider'\n"),   # signal, not a refusal
    _done(1, "coreutils: unknown program 'other'\n"),
    _done(1, ""),
])
def test_sleep_unexpected_exit_fails(monkeypatch, tmp_path, outcome):
    _candidates(monkeypatch, tmp_path, sleep=True, gnusleep=True)
    _runs(monkeypatch, [outcome])
    _fails("failed unexpectedly", prereq.sleep_runnable_as_seat_provider, tmp_path / "work")
