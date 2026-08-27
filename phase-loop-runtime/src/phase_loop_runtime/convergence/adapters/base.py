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
* **Output.** Only a bounded prefix of the child's stdout is parsed, and the
  returned diagnostic is a fixed metadata-only phrase. Provider text is never
  copied into the envelope, so a credential the provider printed cannot be
  laundered into a result.

Unparseable, unknown, or truncated provider output is blocked rather than
reported as success.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
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
    """Run one bounded provider action and normalize it into the frozen envelope."""

    if Path(request.argv[0]).name != provider:
        return _envelope(ConvergenceResultStatus.BLOCKED, request.attempt_id, _DETAIL_OUT_OF_BOUNDS)
    if not request.cwd.is_dir():
        return _envelope(ConvergenceResultStatus.BLOCKED, request.attempt_id, _DETAIL_BAD_CWD)
    try:
        process = subprocess.Popen(
            list(request.argv),
            cwd=str(request.cwd),
            env=_child_environment(),
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        return _envelope(ConvergenceResultStatus.FAILED, request.attempt_id, _DETAIL_SPAWN_FAILED)
    try:
        stdout, _stderr = process.communicate(timeout=request.timeout_seconds)
    except subprocess.TimeoutExpired:
        # ``start_new_session`` made the child its own process-group leader, so
        # its pid is the pgid: killing the group reclaims any helper it forked
        # rather than orphaning them behind the timed-out leader.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):  # pragma: no cover - already reaped
            process.kill()
        process.communicate()
        return _envelope(ConvergenceResultStatus.DEGRADED, request.attempt_id, _DETAIL_TIMEOUT)
    if process.returncode:
        return _envelope(ConvergenceResultStatus.FAILED, request.attempt_id, _DETAIL_NONZERO)
    return _envelope(_declared_status(stdout), request.attempt_id, _declared_detail(stdout))


def _parse_status(stdout: str | None) -> ConvergenceResultStatus | None:
    """The status a well-formed bounded result declares, or ``None``.

    Output is read only up to the metadata-only bound, so a provider that
    streams unbounded text yields a truncated -- therefore unparseable -- payload
    and is blocked instead of being trusted.
    """

    try:
        payload = json.loads((stdout or "")[:_MAX_OUTPUT_BYTES])
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
