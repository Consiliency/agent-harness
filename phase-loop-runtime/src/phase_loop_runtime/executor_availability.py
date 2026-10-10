"""Executor availability + auth gates (EXECREG IF-0-EXECREG-1, lane c).

Provides the two boolean gates that hang off ``ExecutorCapabilityRecord`` as
``is_available`` / ``auth_ok`` callables:

* ``is_executor_available`` — a PATH probe (``shutil.which`` on the executor's
  CLI binary), mirroring the advisor-board availability pattern
  (``advisor_board/registries.py``). Metadata-only, no subprocess.
* ``auth_ok_for`` — derived from the record's existing ``auth_preflight_probes``
  (the same command tuples ``run_auth_preflight`` uses), **cached with a bounded
  TTL** so it is not re-run on every dispatch.

Both gates are **dormant** on the execute path until AUTOSEL wires them into
default-executor resolution — EXECREG only makes them present, correct, and
testable. The cache/memo lives here (module level, keyed by executor); the frozen
record only holds a thin closure, never mutable state.
"""
from __future__ import annotations

import shutil
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

# Executor -> availability-probe CLI binary. Mirrors the advisor-board harness
# registry (codex->codex, gemini->agy, grok->grok, ...). ``command`` and
# ``manual`` shell out to no named CLI, so they have no PATH-probe binary.
_EXECUTOR_CLI: dict[str, str] = {
    "codex": "codex",
    "claude": "claude",
    "gemini": "agy",
    "opencode": "opencode",
    "pi": "pi",
    "grok": "grok",
}


def executor_cli(executor: str) -> str | None:
    """The CLI binary an executor is PATH-probed for, or ``None`` (command/manual)."""
    return _EXECUTOR_CLI.get(executor)


def is_executor_available(executor: str, *, which: Callable[[str], object | None] = shutil.which) -> bool:
    """True iff the executor's CLI binary is on PATH. Executors with no external
    CLI (``command`` / ``manual``) report ``False`` (never a crash). ``which`` is
    injectable so a test can simulate an empty PATH."""
    cli = _EXECUTOR_CLI.get(executor)
    if cli is None:
        return False
    return which(cli) is not None


# --- auth_ok: cached, bounded probe gate -----------------------------------

_AUTH_TTL_SECONDS = 300.0
# Strict per-probe subprocess timeout. Auth/version probes are near-instant; a
# hung CLI (network wedge, prompt-for-input) must NOT freeze the runner because
# ``auth_ok_for`` is on the dispatch hot path. On timeout the gate fails CLOSED.
_PROBE_TIMEOUT_SECONDS = 10.0
# (executor, probes) -> (captured_at_monotonic, ok). Keyed by the probe tuple too,
# so a call with a changed probe set never reuses a prior executor's verdict.
_auth_cache: dict[tuple[str, tuple[str, ...]], tuple[float, bool]] = {}


@dataclass(frozen=True)
class ProbeRefusal:
    """Why an executor's probes did not pass (agent-harness#1431).

    ``kind`` is one of ``raised`` / ``timed_out`` / ``nonzero_exit`` / ``not_logged_in``.
    ``code`` is the refusal's own typed code when the probe RAISED one (a code-shaped
    exception message such as ``agy_image_unqualified``), else ``None``. Nothing here is
    CLI output: only the probe that failed, how it failed and, for a typed refusal of
    ours, its code.
    """

    kind: str
    probe: str
    code: str | None = None
    exception: str | None = None
    returncode: int | None = None


_CODE_SHAPED = re.compile(r"[a-z][a-z0-9_]{2,79}")
# The refusal behind each cached FAILED verdict, under the same key as ``_auth_cache``.
_auth_refusals: dict[tuple[str, tuple[str, ...]], ProbeRefusal] = {}


def _run_probe(probe: str) -> subprocess.CompletedProcess:
    # A probe may start an agent CLI, so it takes the scratch decision like any launch
    # (agent-harness#1147); a refusal under PHASE_LOOP_SANDBOX_REFUSE_RAM fails the probe.
    from .panel_invoker import run_provider
    from .sandbox_policy import CHILD_SCRATCH_RELOCATE, SandboxSpaceError, child_scratch_env

    try:
        env = child_scratch_env(os.environ, CHILD_SCRATCH_RELOCATE)
    except SandboxSpaceError as exc:
        return subprocess.CompletedProcess(probe, 1, "", str(exc))
    return run_provider(
        shlex.split(probe),
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=_PROBE_TIMEOUT_SECONDS,
    )


def _probes_verdict(
    executor: str, probes: tuple[str, ...], runner: Callable[[str], subprocess.CompletedProcess]
) -> tuple[bool, ProbeRefusal | None]:
    """``_probes_pass`` with the reason: ``(True, None)`` or ``(False, refusal)``.

    All probes must exit 0. For codex/claude the login-status probe must also
    report an authenticated session (mirroring ``run_auth_preflight``'s core).
    Deeper auth semantics stay in ``run_auth_preflight`` at launch — this is the
    cheap cached gate AUTOSEL scans with. A probe that TIMES OUT (or otherwise
    raises) fails the gate CLOSED — a wedged CLI is treated as unusable, never a
    runner crash and never an optimistic pass. The refusal says which probe failed and
    how, and carries a typed refusal's own code, so a caller that drops the executor can
    say why (agent-harness#1431)."""
    if not probes:
        # No probe surface (gemini/pi already only version+help; command/manual
        # have none) — nothing to fail, treat as authed-if-reachable.
        return True, None
    outputs: dict[str, str] = {}
    for probe in probes:
        try:
            completed = runner(probe)
        except subprocess.TimeoutExpired:
            return False, ProbeRefusal("timed_out", probe, exception="TimeoutExpired")
        except Exception as exc:
            # A wedged/timed-out/erroring probe (TimeoutExpired, OSError, any
            # runner exception) fails the gate CLOSED — never a crash, never a pass.
            message = str(exc)
            return False, ProbeRefusal(
                "raised", probe, exception=type(exc).__name__,
                code=message if _CODE_SHAPED.fullmatch(message) else None,
            )
        if completed.returncode != 0:
            return False, ProbeRefusal("nonzero_exit", probe, returncode=completed.returncode)
        outputs[probe] = ((completed.stdout or "") + " " + (completed.stderr or "")).strip().lower()
    if executor == "codex":
        if "logged in" in outputs.get("codex login status", ""):
            return True, None
        return False, ProbeRefusal("not_logged_in", "codex login status")
    if executor == "claude":
        status = outputs.get("claude auth status", "")
        if '"loggedin": true' in status.replace(" ", "") or '"loggedin":true' in status.replace(" ", ""):
            return True, None
        return False, ProbeRefusal("not_logged_in", "claude auth status")
    return True, None


def _probes_pass(executor: str, probes: tuple[str, ...], runner: Callable[[str], subprocess.CompletedProcess]) -> bool:
    """The boolean of ``_probes_verdict`` (fails CLOSED on any failing or raising probe)."""
    return _probes_verdict(executor, probes, runner)[0]


def auth_ok_for(
    executor: str,
    probes: tuple[str, ...],
    *,
    now: float | None = None,
    ttl_seconds: float = _AUTH_TTL_SECONDS,
    runner: Callable[[str], subprocess.CompletedProcess] = _run_probe,
) -> bool:
    """Cached, bounded auth gate for an executor. Re-runs the probes only after
    the TTL elapses; within the window returns the cached verdict."""
    stamp = time.monotonic() if now is None else now
    key = (executor, tuple(probes))
    cached = _auth_cache.get(key)
    if cached is not None and (stamp - cached[0]) < ttl_seconds:
        return cached[1]
    ok, refusal = _probes_verdict(executor, probes, runner)
    _auth_cache[key] = (stamp, ok)
    if refusal is None:
        _auth_refusals.pop(key, None)
    else:
        _auth_refusals[key] = refusal
    return ok


def auth_refusal_for(executor: str, probes: tuple[str, ...]) -> ProbeRefusal | None:
    """Why ``auth_ok_for(executor, probes)`` last failed, else ``None``.

    Read-only: it never runs a probe. ``None`` when the gate last passed, or was never
    evaluated for this key."""
    return _auth_refusals.get((executor, tuple(probes)))


def clear_auth_cache() -> None:
    """Test hook — drop the memoized auth verdicts."""
    _auth_cache.clear()
    _auth_refusals.clear()
