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
  endpoint escape reaches it. The provider's own scratch is then moved off a
  RAM-backed temp dir (agent-harness#1147): only ``TMPDIR`` / ``CLAUDE_CODE_TMPDIR``
  may be added, set to the runtime's own private disk-backed dir.
* **Time and process group.** The child runs in its own session. Non-review
  actions use the requested wall-clock timeout; review actions have no such
  deadline. Cleanup sends SIGKILL to the owned process group and waits for the
  leader; this is not a guarantee about descendants that leave that group.
* **Output.** Each pipe is limited in bytes before accumulation, and the
  returned diagnostic is a fixed metadata-only phrase. Provider text is never
  copied into the envelope, so a credential the provider printed cannot be
  laundered into a result.

Unparseable, unknown, or truncated provider output is blocked rather than
reported as success.
"""
from __future__ import annotations
from contextlib import ExitStack

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Callable, Mapping
import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from phase_loop_runtime import sandbox_policy
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
_DETAIL_NO_SCRATCH = "adapter has no disk-backed scratch and RAM fallback is refused"


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
    """The bounded child environment, built only from the permitted pure scrubbers, then
    given the provider-launch scratch decision."""

    return sandbox_policy.child_scratch_env(
        strip_mutation_credentials(scrub_subscription_env(os.environ)),
        sandbox_policy.CHILD_SCRATCH_RELOCATE,
    )


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
    from ... import panel_invoker, sandbox_egress
    profile_stack = ExitStack()
    try:
        environment = _child_environment()
    except sandbox_policy.SandboxSpaceError:
        return _envelope(ConvergenceResultStatus.FAILED, request.attempt_id, _DETAIL_NO_SCRATCH)
    command = list(request.argv)
    role = panel_invoker.SeatLaunchRole.EXECUTOR_TRUSTED
    profile = panel_invoker.SeatProfile(env=environment)
    try:
        if request.allowed_action == "review":
            role = panel_invoker.SeatLaunchRole.PROVIDER_REVIEW
            prefix = profile_stack.enter_context(sandbox_egress.isolated_network(timeout_s=None, required=True))
            token = panel_invoker._EGRESS_LAUNCH_PREFIX.set(prefix)
            profile_stack.callback(panel_invoker._EGRESS_LAUNCH_PREFIX.reset, token)
            command, profile = profile_stack.enter_context(panel_invoker._seat_command_profile(
                command, env=environment, cwd=request.cwd, readonly_paths=(request.cwd,),
            ))
        process = panel_invoker.launch_owned(
            command, role=role, profile=profile,
            cwd=str(request.cwd),
            env=environment,
            bufsize=0,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except (OSError, sandbox_egress.EgressUnavailable):
        profile_stack.close()
        return _envelope(ConvergenceResultStatus.FAILED, request.attempt_id, _DETAIL_SPAWN_FAILED)
    except BaseException as primary:
        try:
            profile_stack.close()
        except BaseException as cleanup:
            raise primary from cleanup
        raise
    try:
        deadline = None if request.allowed_action == "review" else time.monotonic() + request.timeout_seconds
        selector = selectors.DefaultSelector()
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while not overflow:
            remaining = deadline - time.monotonic() if deadline is not None else 0.05
            if deadline is not None and remaining <= 0:
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
        profile_stack.close()
        raise primary_error
    profile_stack.close()
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

# Patch-return capture is deliberately separate from the convergence envelope.
PROPOSAL_CAP_MAX = 67_108_864
WORKER_ENV_DROP = frozenset({"SSH_AUTH_SOCK", "SSH_ASKPASS", "GIT_ASKPASS",
    "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"})
WORKER_ENV_DROP_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


@dataclass(frozen=True)
class CaptureRequest:
    attempt_id: str
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: int
    stdin: bytes
    proposal_cap: int
    environment: Mapping[str, str]


@dataclass(frozen=True)
class StreamDigest:
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class SpawnRefused:
    reason: str


@dataclass(frozen=True)
class BoundedCapture:
    attempt_id: str
    termination: str
    terminated_by: str
    signal: str | None
    exit_code: int | None
    stdout: StreamDigest
    stderr: StreamDigest
    streams_complete: bool
    proposal: bytes | None
    proposal_overflow: bool
    stdin_delivered: bool
    spawn_count: int
    duration_ns: int | None
    observed_start_utc: str | None
    observed_end_utc: str | None


def worker_child_environment(allow: frozenset[str]) -> dict[str, str]:
    environment = _child_environment()
    return {key: value for key, value in environment.items()
            if key not in WORKER_ENV_DROP and not key.startswith(WORKER_ENV_DROP_PREFIXES)
            and key in (allow | {"TMPDIR", "CLAUDE_CODE_TMPDIR"})}


def run_bounded_capture(request: CaptureRequest, *,
                        before_spawn: Callable[[], SpawnRefused | None],
                        cancel: threading.Event) -> BoundedCapture | SpawnRefused:
    if not 1 <= request.proposal_cap <= PROPOSAL_CAP_MAX or request.timeout_seconds <= 0:
        return SpawnRefused("capture_settings_invalid")
    from ... import panel_invoker
    hashes = {name: hashlib.sha256() for name in ("stdout", "stderr")}
    counts = dict.fromkeys(hashes, 0)
    proposal = bytearray()
    try:
        refusal = before_spawn()
    except Exception:
        return SpawnRefused("before_spawn_failed")
    if refusal is not None:
        return refusal
    start = time.monotonic_ns()
    deadline = time.monotonic() + request.timeout_seconds
    started = datetime.now(timezone.utc).isoformat()
    try:
        process = panel_invoker.launch_owned(
            list(request.argv), role=panel_invoker.SeatLaunchRole.EXECUTOR_TRUSTED,
            profile=panel_invoker.SeatProfile(env=dict(request.environment)),
            cwd=str(request.cwd), env=dict(request.environment), bufsize=0,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        empty = StreamDigest(hashlib.sha256(b"").hexdigest(), 0)
        return BoundedCapture(request.attempt_id, "failed_to_start", "harness", None,
                              None, empty, empty, True, b"", False, False, 1,
                              time.monotonic_ns() - start, started,
                              datetime.now(timezone.utc).isoformat())
    termination, by, sig, code = "completed", "worker", None, None
    delivered = not request.stdin
    offset = 0
    reaped = False
    complete = False
    selector = selectors.DefaultSelector()

    def reclaim():
        nonlocal reaped
        if not reaped:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            reaped = True

    try:
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        if request.stdin:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
        while selector.get_map() or not reaped:
            if not reaped:
                exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if exited is not None:
                    code = exited.si_status if exited.si_code == os.CLD_EXITED else -exited.si_status
                    reclaim()
                elif cancel.is_set():
                    termination, by, sig = "cancelled", "operator", "SIGKILL"
                    reclaim()
                elif time.monotonic() >= deadline:
                    termination, by, sig = "timed_out", "harness", "SIGKILL"
                    reclaim()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            for key, _mask in selector.select(min(remaining, 0.05)):
                if key.data == "stdin":
                    try:
                        offset += os.write(key.fd, request.stdin[offset:offset + 65536])
                    except BrokenPipeError:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    except BlockingIOError:
                        continue
                    if offset == len(request.stdin):
                        delivered = True
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                else:
                    try:
                        chunk = os.read(key.fd, 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    hashes[key.data].update(chunk)
                    counts[key.data] += len(chunk)
                    if key.data == "stdout":
                        proposal.extend(chunk[:max(0, request.proposal_cap - len(proposal))])
        complete = not any(key.data in hashes for key in selector.get_map().values())
    finally:
        reclaim()
        selector.close()
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
    overflow = counts["stdout"] > request.proposal_cap
    return BoundedCapture(request.attempt_id, termination, by, sig, code,
                          *(StreamDigest(hashes[name].hexdigest(), counts[name])
                            for name in ("stdout", "stderr")),
                          complete, None if overflow else bytes(proposal), overflow,
                          delivered, 1, time.monotonic_ns() - start, started,
                          datetime.now(timezone.utc).isoformat())
