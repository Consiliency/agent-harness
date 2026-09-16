"""Bounded, credential-stripped adapter execution primitives.

An adapter performs exactly one non-coordinating provider action and returns a
:class:`ConvergenceResultEnvelope`. It never drives a train, publishes, merges,
releases, or packages, and it imports no coordinator, publisher, or broker
effect path.

Four bounds hold on every execution:

* **Identity.** ``argv[0]`` must name the expected provider executable exactly.
  A prefix match would admit a look-alike such as ``codex-rogue``.
* **Environment.** The child inherits only what survives the two pure scrubbers
  this package is permitted to use -- the subscription scrubber and the
  mutation-credential stripper -- so no mutation credential, vendor API key, or
  endpoint escape reaches it.
* **Time and process group.** The child runs in its own session; a timeout kills
  the whole process group, so a provider that forked helpers cannot outlive its
  bound.
* **Output.** Each pipe is limited in bytes before accumulation, and the
  returned diagnostic is a fixed metadata-only phrase. Provider text is never
  copied into the envelope, so a credential the provider printed cannot be
  laundered into a result.

Unparseable, unknown, or truncated provider output is blocked rather than
reported as success.
"""
from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from phase_loop_runtime.advisor_board.backing import scrub_subscription_env
from phase_loop_runtime.convergence.broker.credsep import strip_mutation_credentials
from phase_loop_runtime.convergence.contracts import AdmissionRequest
from phase_loop_runtime.train_ledger import ConvergenceResultEnvelope, ConvergenceResultStatus

_ALLOWED_ACTIONS = frozenset({"execute", "repair", "review"})
#: Bounds on the request shape and on what a child may hand back.
_MAX_ARGV = 64
_MAX_TIMEOUT_SECONDS = 3600.0
_MAX_OUTPUT_BYTES = 64 * 1024

#: Fixed, metadata-only diagnostics. Provider output never appears in an
#: envelope, so a secret the provider printed cannot travel with the result.
_DETAIL_OUT_OF_BOUNDS = "adapter command is not the expected provider executable"
_DETAIL_BAD_CWD = "adapter working directory is outside bounded execution"
_DETAIL_TIMEOUT = "adapter exceeded its bounded execution time"
_DETAIL_SPAWN_FAILED = "adapter could not be executed"
_DETAIL_NONZERO = "adapter exited non-zero"
_DETAIL_MALFORMED = "adapter returned no parseable convergence result"
_DETAIL_OK = "adapter returned a bounded convergence result"
_DETAIL_OVERFLOW = "adapter exceeded its bounded output size"
_DETAIL_CLEANUP = "adapter process cleanup failed"


@dataclass(frozen=True)
class AdapterExecutionRequest:
    attempt_id: str
    admission: AdmissionRequest
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: float
    allowed_action: str
    evidence_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.argv or self.timeout_seconds <= 0 or self.allowed_action not in _ALLOWED_ACTIONS:
            raise ValueError("adapter request is outside bounded execution contract")
        if len(self.argv) > _MAX_ARGV or not all(
            isinstance(item, str) and item for item in self.argv
        ):
            raise ValueError("adapter argv is outside bounded execution contract")
        if self.timeout_seconds > _MAX_TIMEOUT_SECONDS:
            raise ValueError("adapter timeout is outside bounded execution contract")
        if self.admission.attempt_id != self.attempt_id:
            raise ValueError("adapter request must preserve admission attempt id")
        # The admission's exact-version predicate is the binding an adapter
        # carries into the provider call. A whitespace-only predicate is truthy
        # -- so it clears the shared ``AdmissionRequest`` check -- but binds
        # nothing, which is exactly the shape this bound has to reject.
        if not self.admission.expected_version_predicate.strip():
            raise ValueError("adapter request requires a nonempty expected-version predicate")


def _child_environment() -> dict[str, str]:
    """The bounded child environment, built only from the permitted pure scrubbers."""

    return strip_mutation_credentials(scrub_subscription_env(os.environ))


def _envelope(status: ConvergenceResultStatus, attempt_id: str, detail: str) -> ConvergenceResultEnvelope:
    return ConvergenceResultEnvelope(status, attempt_id, detail)


def run_bounded(request: AdapterExecutionRequest, *, provider: str) -> ConvergenceResultEnvelope:
    """Run one bounded provider action and normalize it into the frozen envelope.

    Keep an operation exception even if later cleanup is interrupted.
    """

    if Path(request.argv[0]).name != provider:
        return _envelope(ConvergenceResultStatus.BLOCKED, request.attempt_id, _DETAIL_OUT_OF_BOUNDS)
    if not request.cwd.is_dir():
        return _envelope(ConvergenceResultStatus.BLOCKED, request.attempt_id, _DETAIL_BAD_CWD)
    stdout = bytearray()
    counts = {"stdout": 0, "stderr": 0}
    overflow = expired = False
    returncode = None
    primary_error = cleanup_error = None
    selector = None
    try:
        process = subprocess.Popen(
            list(request.argv),
            cwd=str(request.cwd),
            env=_child_environment(),
            bufsize=0,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        return _envelope(ConvergenceResultStatus.FAILED, request.attempt_id, _DETAIL_SPAWN_FAILED)
    try:
        deadline = time.monotonic() + request.timeout_seconds
        selector = selectors.DefaultSelector()
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while not overflow:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                expired = True
                break
            # Keep the leader unreaped until its group is reclaimed: its
            # PID cannot be reused as an unrelated group's identity.
            exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if exited is not None:
                returncode = exited.si_status if exited.si_code == os.CLD_EXITED else -exited.si_status
            ready = selector.select(0 if returncode is not None else min(remaining, 0.05))
            if not ready and returncode is not None:
                break
            for key, _mask in ready:
                name = key.data
                try:
                    chunk = os.read(key.fd, min(8192, _MAX_OUTPUT_BYTES + 1 - counts[name]))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                counts[name] += len(chunk)
                if name == "stdout":
                    stdout.extend(chunk[:_MAX_OUTPUT_BYTES - len(stdout)])
                if counts[name] > _MAX_OUTPUT_BYTES:
                    overflow = True
                    break
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            if selector is not None:
                selector.close()
        except BaseException as exc:
            cleanup_error = exc
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except BaseException as exc:
            if cleanup_error is None or (
                isinstance(cleanup_error, Exception) and not isinstance(exc, Exception)
            ):
                cleanup_error = exc
        for pipe in (process.stdout, process.stderr):
            try:
                pipe.close()
            except BaseException as exc:
                if cleanup_error is None or (
                    isinstance(cleanup_error, Exception) and not isinstance(exc, Exception)
                ):
                    cleanup_error = exc
        try:
            process.wait(timeout=1)
        except BaseException as exc:
            if cleanup_error is None or (
                isinstance(cleanup_error, Exception) and not isinstance(exc, Exception)
            ):
                cleanup_error = exc
    if primary_error is not None:
        raise primary_error
    if cleanup_error is not None:
        if not isinstance(cleanup_error, Exception):
            raise cleanup_error
        return _envelope(ConvergenceResultStatus.DEGRADED, request.attempt_id, _DETAIL_CLEANUP)
    if overflow:
        return _envelope(ConvergenceResultStatus.BLOCKED, request.attempt_id, _DETAIL_OVERFLOW)
    if expired:
        return _envelope(ConvergenceResultStatus.DEGRADED, request.attempt_id, _DETAIL_TIMEOUT)
    if returncode:
        return _envelope(ConvergenceResultStatus.FAILED, request.attempt_id, _DETAIL_NONZERO)
    try:
        decoded = stdout.decode("utf-8")
    except UnicodeDecodeError:
        return _envelope(ConvergenceResultStatus.BLOCKED, request.attempt_id, _DETAIL_MALFORMED)
    return _envelope(_declared_status(decoded), request.attempt_id, _declared_detail(decoded))


def _parse_status(stdout: str | None) -> ConvergenceResultStatus | None:
    """The status a well-formed bounded result declares, or ``None``.

    The caller enforces the byte budget before decoding and parsing.
    """

    try:
        payload = json.loads(stdout or "")
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return ConvergenceResultStatus(payload.get("status"))
    except ValueError:
        return None


def _declared_status(stdout: str | None) -> ConvergenceResultStatus:
    status = _parse_status(stdout)
    return ConvergenceResultStatus.BLOCKED if status is None else status


def _declared_detail(stdout: str | None) -> str:
    return _DETAIL_MALFORMED if _parse_status(stdout) is None else _DETAIL_OK
