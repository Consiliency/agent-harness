"""Executor availability + auth gates (EXECREG IF-0-EXECREG-1, lane c).

Provides the two boolean gates that hang off ``ExecutorCapabilityRecord`` as
``is_available`` / ``auth_ok`` callables:

* ``is_executor_available`` — a PATH probe (``shutil.which`` on the executor's
  CLI binary), mirroring the advisor-board availability pattern
  (``advisor_board/registries.py``). Metadata-only, no subprocess.
* ``auth_ok_for`` — derived from the record's existing ``auth_preflight_probes``
  (the same command tuples ``run_auth_preflight`` uses), **cached with a bounded
  TTL** so it is not re-run on every dispatch.

AUTOSEL uses these gates in default-executor resolution; explicit overrides
bypass AUTOSEL's candidate selection. The cache/memo lives here (module level, keyed by executor); the frozen
record only holds a thin closure, never mutable state.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
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
# agent-harness#1585: `claude auth status` can transiently exit non-zero during a
# credential/token refresh race on a healthy host. One bounded retry recovers the
# transient blip without masking a real sign-out or delaying healthy probes.
_CLAUDE_AUTH_RETRY_DELAY_S = 0.25
_PROBE_STDERR_SCAN_CAP_CHARS = 8192
_PROBE_DIAG_KEEP = 50
_CLAUDE_AUTH_METHODS = frozenset({"claude.ai", "oauth_token", "apiKey", "none"})
# (executor, probes) -> (captured_at_monotonic, ok). Keyed by the probe tuple too,
# so a call with a changed probe set never reuses a prior executor's verdict.
_auth_cache: dict[tuple[str, tuple[str, ...]], tuple[float, bool]] = {}


@dataclass(frozen=True)
class ProbeRefusal:
    """Why an executor's probes did not pass (agent-harness#1431).

    ``kind`` is one of ``raised`` / ``timed_out`` / ``nonzero_exit`` / ``not_logged_in``.
    ``code`` is the refusal's own typed code when the probe RAISED one of ours: a
    ``seat_jail.SeatSandboxRefused`` (its ``code``) or an exception whose message is
    exactly a ``seat_jail.NOTICES`` key (such as ``agy_image_unqualified``); else ``None``.
    Nothing here is CLI output or other exception text: only the probe that failed, how it
    failed and, for a typed refusal of ours, its code.
    """

    kind: str
    probe: str
    code: str | None = None
    exception: str | None = None
    returncode: int | None = None


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


def codex_status_logged_in(status: str) -> bool:
    """Does ``codex login status`` output report a login (agent-harness#1528)?

    "Not logged in" (or "not signed in"), in any letter case, is a logged-out probe even
    though it contains the words "logged in"."""
    text = " ".join(status.lower().split())
    if "not logged in" in text or "not signed in" in text:
        return False
    return "logged in" in text


def _typed_refusal_code(exc: BaseException) -> str | None:
    """The code of a typed refusal of ours, decided by type and table, never by shape.

    A ``SeatSandboxRefused`` carries its code; any other exception counts only when its
    whole message is a ``seat_jail.NOTICES`` key. Anything else is ``None``, so no other
    exception text is ever carried (agent-harness#1431)."""
    from .seat_jail import NOTICES, SeatSandboxRefused

    if isinstance(exc, SeatSandboxRefused):
        return exc.code if exc.code in NOTICES else None
    message = str(exc)
    return message if message in NOTICES else None


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-standard JSON constant")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _claude_status_fields(stdout: str) -> tuple[bool | None, str | None]:
    """Closed boolean ``loggedIn`` and allowlisted ``authMethod`` from ``claude auth status``.

    Requires a strict RFC 8259 JSON object (rejecting ``NaN``/``Infinity`` constants and
    duplicate object keys) with a strict boolean ``loggedIn`` field; malformed, ambiguous,
    or truncated JSON never opens the gate, and email, orgId, orgName, tokens, and raw
    stdout are never returned (agent-harness#1585).
    """
    text = (stdout or "").strip()
    if not text:
        return None, None
    try:
        payload = json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (ValueError, TypeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    logged_in = payload.get("loggedIn")
    logged_in_bool = logged_in if type(logged_in) is bool else None
    raw_method = payload.get("authMethod")
    if not isinstance(raw_method, str) or not raw_method:
        method = None
    elif raw_method in _CLAUDE_AUTH_METHODS:
        method = raw_method
    else:
        method = "other"
    return logged_in_bool, method


def _classify_probe_stderr(stderr: str) -> tuple[str, int]:
    """Closed diagnostic category and byte count for probe stderr (agent-harness#1585).

    Never returns raw CLI text, paths, emails, org identifiers, or tokens. Scans at most
    ``_PROBE_STDERR_SCAN_CAP_CHARS`` characters with linear substring checks only.
    """
    raw = stderr or ""
    byte_count = len(raw.encode("utf-8", errors="replace"))
    if not raw.strip():
        return "empty", byte_count
    sample = raw[:_PROBE_STDERR_SCAN_CAP_CHARS].lower()
    if (
        "not logged in" in sample
        or "not signed in" in sample
        or "please run /login" in sample
        or "please run `claude" in sample
    ):
        return "not_logged_in", byte_count
    if "token" in sample and any(word in sample for word in ("expired", "refresh", "revoked", "invalid")):
        return "token_refresh_or_expiry", byte_count
    if any(word in sample for word in ("lock", "busy", "eagain", "temporarily unavailable")):
        return "lock_or_transient", byte_count
    if any(word in sample for word in ("keychain", "keyring", "credential", "secret service")):
        return "credential_store", byte_count
    if "timeout" in sample or "timed out" in sample or "etimedout" in sample:
        return "timeout", byte_count
    if any(word in sample for word in ("econnrefused", "enotfound", "eai_again", "network", "dns", "connection")):
        return "network", byte_count
    if any(word in sample for word in ("eacces", "eperm", "permission denied", "read-only")):
        return "permission", byte_count
    if "rate limit" in sample or "429" in sample or "too many requests" in sample:
        return "rate_limit", byte_count
    if any(word in sample for word in ("401", "403", "unauthorized", "forbidden")):
        return "auth_http_error", byte_count
    if "command not found" in sample or "enoent" in sample or "no such file" in sample:
        return "missing_executable_or_file", byte_count
    return "unclassified", byte_count


def _record_probe_diagnostic(
    *,
    executor: str,
    probe: str,
    outcome: str,
    attempts: int,
    first_returncode: int | None,
    final_returncode: int | None,
    first_stderr: str = "",
    final_stderr: str = "",
    claude_logged_in: bool | None = None,
    claude_auth_method: str | None = None,
    exception: str | None = None,
    code: str | None = None,
) -> None:
    """Persist a closed-field private 0600 diagnostic record for failed or retry-recovered
    auth probes (agent-harness#1585). Best-effort: never raises or alters gate verdicts."""
    try:
        from .president_adapter import write_private_record

        known_executor = executor if executor in _EXECUTOR_CLI else "other"
        first_stderr_class, first_stderr_bytes = _classify_probe_stderr(first_stderr)
        final_stderr_class, final_stderr_bytes = _classify_probe_stderr(final_stderr)
        record: dict[str, object] = {
            "schema": "auth_probe_diag.v1",
            "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "executor": known_executor,
            "probe": probe if len(probe) <= 128 else probe[:128],
            "outcome": outcome,
            "attempts": int(attempts),
            "first_returncode": first_returncode if type(first_returncode) is int else None,
            "final_returncode": final_returncode if type(final_returncode) is int else None,
            "first_stderr_class": first_stderr_class,
            "first_stderr_bytes": first_stderr_bytes,
            "final_stderr_class": final_stderr_class,
            "final_stderr_bytes": final_stderr_bytes,
            "claude_logged_in": claude_logged_in if type(claude_logged_in) is bool else None,
            "claude_auth_method": claude_auth_method,
            "exception": exception,
            "code": code,
        }
        write_private_record(
            f"probe-{uuid.uuid4().hex}.json",
            record,
            prune_prefix="probe-",
            keep=_PROBE_DIAG_KEEP,
        )
    except Exception:
        pass


def _probes_verdict(
    executor: str,
    probes: tuple[str, ...],
    runner: Callable[[str], subprocess.CompletedProcess],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, ProbeRefusal | None]:
    """``_probes_pass`` with the reason: ``(True, None)`` or ``(False, refusal)``.

    All probes must exit 0. For codex/claude the login-status probe must also
    report an authenticated session (mirroring ``run_auth_preflight``'s core).
    Deeper auth semantics stay in ``run_auth_preflight`` at launch — this is the
    cheap cached gate AUTOSEL scans with. A probe that TIMES OUT (or otherwise
    raises) fails the gate CLOSED — a wedged CLI is treated as unusable, never a
    runner crash and never an optimistic pass. The refusal says which probe failed and
    how, and carries a typed refusal's own code, so a caller that drops the executor can
    say why (agent-harness#1431).

    For ``claude auth status`` (agent-harness#1585), a non-zero exit is retried once
    after ``_CLAUDE_AUTH_RETRY_DELAY_S`` to recover transient credential/refresh races,
    and failed or retry-recovered probes retain a private 0600 redacted diagnostic record.
    """
    if not probes:
        # No probe surface (gemini/pi already only version+help; command/manual
        # have none) — nothing to fail, treat as authed-if-reachable.
        return True, None
    outputs: dict[str, str] = {}
    raw_completed: dict[str, subprocess.CompletedProcess] = {}
    retry_meta: dict[str, tuple[int, int | None, str]] = {}
    for probe in probes:
        attempts = 1
        first_rc: int | None = None
        first_stderr = ""
        try:
            completed = runner(probe)
        except subprocess.TimeoutExpired:
            _record_probe_diagnostic(
                executor=executor, probe=probe, outcome="timed_out", attempts=1,
                first_returncode=None, final_returncode=None, exception="TimeoutExpired",
            )
            return False, ProbeRefusal("timed_out", probe, exception="TimeoutExpired")
        except Exception as exc:
            # A wedged/timed-out/erroring probe (TimeoutExpired, OSError, any
            # runner exception) fails the gate CLOSED — never a crash, never a pass.
            typed_code = _typed_refusal_code(exc)
            _record_probe_diagnostic(
                executor=executor, probe=probe, outcome="raised", attempts=1,
                first_returncode=None, final_returncode=None,
                exception=type(exc).__name__, code=typed_code,
            )
            return False, ProbeRefusal(
                "raised", probe, exception=type(exc).__name__, code=typed_code,
            )
        if completed.returncode != 0:
            first_rc = completed.returncode
            first_stderr = completed.stderr or ""
            if executor == "claude" and probe == "claude auth status":
                sleep(_CLAUDE_AUTH_RETRY_DELAY_S)
                attempts = 2
                try:
                    completed = runner(probe)
                except subprocess.TimeoutExpired:
                    _record_probe_diagnostic(
                        executor=executor, probe=probe, outcome="timed_out", attempts=attempts,
                        first_returncode=first_rc, final_returncode=None,
                        first_stderr=first_stderr, exception="TimeoutExpired",
                    )
                    return False, ProbeRefusal("timed_out", probe, exception="TimeoutExpired")
                except Exception as exc:
                    typed_code = _typed_refusal_code(exc)
                    _record_probe_diagnostic(
                        executor=executor, probe=probe, outcome="raised", attempts=attempts,
                        first_returncode=first_rc, final_returncode=None,
                        first_stderr=first_stderr, exception=type(exc).__name__, code=typed_code,
                    )
                    return False, ProbeRefusal(
                        "raised", probe, exception=type(exc).__name__, code=typed_code,
                    )
        if completed.returncode != 0:
            logged_in, auth_method = (
                _claude_status_fields(completed.stdout or "")
                if executor == "claude" and probe == "claude auth status"
                else (None, None)
            )
            kind = "not_logged_in" if (
                executor == "claude" and probe == "claude auth status" and logged_in is False
            ) else "nonzero_exit"
            _record_probe_diagnostic(
                executor=executor, probe=probe, outcome=kind, attempts=attempts,
                first_returncode=first_rc if attempts > 1 else completed.returncode,
                final_returncode=completed.returncode,
                first_stderr=first_stderr if attempts > 1 else (completed.stderr or ""),
                final_stderr=completed.stderr or "",
                claude_logged_in=logged_in,
                claude_auth_method=auth_method,
            )
            return False, ProbeRefusal(kind, probe, returncode=completed.returncode)
        if attempts > 1:
            logged_in, auth_method = _claude_status_fields(completed.stdout or "")
            if logged_in is True:
                _record_probe_diagnostic(
                    executor=executor, probe=probe, outcome="recovered_on_retry", attempts=attempts,
                    first_returncode=first_rc, final_returncode=completed.returncode,
                    first_stderr=first_stderr, final_stderr=completed.stderr or "",
                    claude_logged_in=logged_in,
                    claude_auth_method=auth_method,
                )
        raw_completed[probe] = completed
        retry_meta[probe] = (attempts, first_rc, first_stderr)
        outputs[probe] = ((completed.stdout or "") + " " + (completed.stderr or "")).strip().lower()
    if executor == "codex":
        if codex_status_logged_in(outputs.get("codex login status", "")):
            return True, None
        status_proc = raw_completed.get("codex login status")
        _record_probe_diagnostic(
            executor=executor, probe="codex login status", outcome="not_logged_in", attempts=1,
            first_returncode=0 if status_proc is not None else None,
            final_returncode=0 if status_proc is not None else None,
            first_stderr=(status_proc.stderr or "") if status_proc is not None else "",
            final_stderr=(status_proc.stderr or "") if status_proc is not None else "",
        )
        return False, ProbeRefusal("not_logged_in", "codex login status")
    if executor == "claude":
        status_proc = raw_completed.get("claude auth status")
        status_stdout = (status_proc.stdout or "") if status_proc is not None else ""
        logged_in, auth_method = _claude_status_fields(status_stdout)
        if logged_in is True:
            return True, None
        attempts, first_rc, first_stderr = retry_meta.get("claude auth status", (1, None, ""))
        _record_probe_diagnostic(
            executor=executor, probe="claude auth status", outcome="not_logged_in",
            attempts=attempts,
            first_returncode=first_rc if attempts > 1 else (0 if status_proc is not None else None),
            final_returncode=0 if status_proc is not None else None,
            first_stderr=first_stderr if attempts > 1 else ((status_proc.stderr or "") if status_proc is not None else ""),
            final_stderr=(status_proc.stderr or "") if status_proc is not None else "",
            claude_logged_in=logged_in,
            claude_auth_method=auth_method,
        )
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
    runner: Callable[[str], subprocess.CompletedProcess] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Cached, bounded auth gate for an executor. Re-runs the probes only after
    the TTL elapses; within the window returns the cached verdict. ``runner`` defaults
    to :func:`_run_probe`, looked up when the gate runs."""
    runner = _run_probe if runner is None else runner
    stamp = time.monotonic() if now is None else now
    key = (executor, tuple(probes))
    cached = _auth_cache.get(key)
    if cached is not None and (stamp - cached[0]) < ttl_seconds:
        return cached[1]
    ok, refusal = _probes_verdict(executor, probes, runner, sleep=sleep)
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
