"""LaneExec return, status and cancel mapping (LANEEXEC SL-2).

Three pure pieces the launch service composes; none starts a process, reads a journal or
signals anything:

* :func:`collect_return` turns one terminated attempt into at most one bounded return,
  named by a :class:`~phase_loop_runtime.launch_process_contract.ReturnDescriptor`, under the
  binding artifact §3 L-S5 rules (``x-return``). ``patch`` reads only the WORKER
  :class:`~phase_loop_runtime.convergence.adapters.patch_return.ProposalReturn`; ``result``
  reads ``{out}/result.json``; ``none`` returns null.
* :func:`map_status`, :func:`map_cancel` and :func:`map_worker_terminal` are the binding
  §3 L-S4 tables, closed and total: every input outside a table maps to the fail-closed row,
  and a zero-signal cancel outcome never maps to ``cancelled`` or ``already_terminal``.
* :func:`build_launch_evidence` builds the metadata-only ``LaunchEvidence`` record.

Returned bytes are never placed in a record, an outcome, a message or evidence: outcomes hold
only codes, digests, lengths and the descriptor path. Exceptions become closed codes
``from None``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from . import openshell_artifacts
from .convergence.adapters.patch_return import ProposalReturn, WorkerResult
from .launch_process_contract import (
    LaunchEvidence,
    LaunchResponse,
    ReturnDescriptor,
    SnapshotEvidence,
    Termination,
    validate_launch_message,
)
from .run_status_projection import AttemptStatus, v2_status_mapping

__all__ = [
    "CANCEL_TABLE",
    "PATCH_CAP_MAX",
    "PROPOSAL_STATUS_TABLE",
    "RESULT_CAP",
    "RESULT_KINDS",
    "STATUS_UNCERTAIN_CODE",
    "CancelMapping",
    "LaunchReturnError",
    "ReturnAttempt",
    "ReturnOutcome",
    "ReturnPolicy",
    "StatusMapping",
    "TerminalMapping",
    "build_launch_evidence",
    "collect_return",
    "map_cancel",
    "map_status",
    "map_worker_result",
    "map_worker_terminal",
]

#: ``x-return.patch``: default and maximum patch cap; operator configuration may only lower it.
PATCH_CAP_MAX = 67108864
#: ``x-return.result``: ``{out}/result.json`` is at most this many bytes.
RESULT_CAP = 1048576
#: ``$defs.ResultKind``.
RESULT_KINDS: tuple[str, ...] = ("patch", "result", "none")

_RESULT_INVALID = "sandbox_launch_result_invalid"
_RESULT_WITHHELD = "sandbox_launch_result_withheld"
_AUDIT_FAILED = "sandbox_launch_audit_failed"

_PATCH_FILE = "patch.bin"
_RESULT_FILE = "result.json"
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600


class LaunchReturnError(ValueError):
    """A closed code for a caller error (an invalid policy or evidence field)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# -- L-S5: return -------------------------------------------------------------------------

#: Binding §3 L-S5, ``patch`` row: every landed ``ProposalReturn.status`` and its code when the
#: return is null. ``returned`` is the only status that delivers bytes; ``withheld_incomplete``
#: (every non-completed termination, cancelled and timed-out included) and ``absent`` return
#: null with no extra code. A status outside this table fails closed as ``audit_failed``.
PROPOSAL_STATUS_TABLE: Mapping[str, str | None] = MappingProxyType({
    "returned": None,
    "absent": None,
    "withheld_incomplete": None,
    "withheld_oversized": _RESULT_INVALID,
    "withheld_malformed": _RESULT_INVALID,
    "withheld_audit_error": _AUDIT_FAILED,
    "withheld_unexplained_change": _AUDIT_FAILED,
    "withheld_evidence_error": _AUDIT_FAILED,
})
_UNKNOWN_PROPOSAL_CODE = _AUDIT_FAILED


@dataclass(frozen=True)
class ReturnPolicy:
    """Operator return bounds: ``patch_cap`` at most :data:`PATCH_CAP_MAX` (``x-return.patch``)
    and the binary-literal limits applied to returned patch bytes."""

    binary_limits: openshell_artifacts.Limits
    patch_cap: int = PATCH_CAP_MAX

    def __post_init__(self) -> None:
        if (type(self.patch_cap) is not int or not 0 < self.patch_cap <= PATCH_CAP_MAX
                or not isinstance(self.binary_limits, openshell_artifacts.Limits)):
            raise LaunchReturnError("return_policy_invalid")


@dataclass(frozen=True)
class ReturnAttempt:
    """One terminated attempt, as the launch service knows it.

    ``return_dir`` is the 0700 per-attempt return directory under the client's LaneExec state
    directory; its parent must exist. ``evidence_root`` is the WORKER evidence store the
    proposal ``locator`` is relative to (``<state_root>/evidence``). ``out_dir`` is the
    attempt's out directory, or None when it is unreachable. ``base_commit`` is the snapshot's
    B; ``masks`` and ``mask_dirs`` are the request's snapshot masks."""

    return_dir: Path
    worker_result: WorkerResult | None = None
    evidence_root: Path | None = None
    out_dir: Path | None = None
    base_commit: str | None = None
    masks: tuple[str, ...] = ()
    mask_dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReturnOutcome:
    """The return step's result: a descriptor, or null with an optional closed code.

    ``status`` names the rule that applied (the proposal status for ``patch``); it is
    metadata and never carries returned bytes."""

    kind: str
    status: str
    descriptor: ReturnDescriptor | None
    code: str | None

    def evidence(self) -> dict[str, Any]:
        """Metadata-only return evidence: no path, no bytes."""
        descriptor = self.descriptor
        return {"kind": self.kind, "status": self.status, "code": self.code,
                "sha256": None if descriptor is None else descriptor.sha256,
                "byte_length": None if descriptor is None else descriptor.byte_length}


def _null(kind: str, status: str, code: str | None) -> ReturnOutcome:
    return ReturnOutcome(kind, status, None, code)


def _walk(path: Path) -> int:
    """An O_PATH-free descriptor walk from ``/`` that follows no symlink."""
    if not path.is_absolute() or any(part in (".", "..") for part in path.parts):
        raise ValueError("path_invalid")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_capped(parent: Path, relative: Sequence[str], cap: int) -> bytes | None:
    """Read a regular file below ``parent`` without following a link; None when it exceeds
    ``cap``. Raises OSError or ValueError when it is missing or not a private regular file."""
    if not relative:
        raise ValueError("path_invalid")
    directory = _walk(parent.joinpath(*relative[:-1]))
    try:
        fd = os.open(relative[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
    finally:
        os.close(directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError("file_invalid")
        if info.st_size > cap:
            return None
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(fd, min(65536, cap + 1 - total) or 1):
            chunks.append(chunk)
            total += len(chunk)
            if total > cap:
                return None
        return b"".join(chunks)
    finally:
        os.close(fd)


def _private_return_dir(path: Path) -> int:
    """Create (if absent) and open the 0700 per-attempt return directory."""
    parent = _walk(path.parent)
    try:
        try:
            os.mkdir(path.name, _DIRECTORY_MODE, dir_fd=parent)
        except FileExistsError:
            pass
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=parent)
    finally:
        os.close(parent)
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != _DIRECTORY_MODE:
        os.close(fd)
        raise ValueError("return_dir_mode")
    return fd


def _write_once(directory: int, name: str, data: bytes) -> None:
    """Create ``name`` exclusively and write it; a partial file this call created is removed,
    and an existing file is never touched."""
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 _FILE_MODE, dir_fd=directory)
    try:
        try:
            os.fchmod(fd, _FILE_MODE)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short_write")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
    except BaseException:
        try:
            os.unlink(name, dir_fd=directory)
        except OSError:
            pass
        raise


def _gone(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _deliver(attempt: ReturnAttempt, kind: str, status: str, data: bytes,
             withhold: Callable[[bytes], bool] | None,
             bound: openshell_artifacts.Bound) -> ReturnOutcome:
    """Apply ``withhold`` to the in-memory bytes, then write them once and name them.

    A true or raising predicate returns ``result_withheld`` before any file exists. The
    return budget is checked before the write and again after the last I/O, at the point of
    publication; an expired budget removes the uncommitted file and returns
    ``result_invalid``, never a descriptor."""
    if withhold is not None:
        try:
            withheld = withhold(data) is not False
        except Exception:  # noqa: BLE001 - a failing predicate withholds
            withheld = True
        if withheld:
            return _null(kind, "withheld_by_predicate", _RESULT_WITHHELD)
    name = _PATCH_FILE if kind == "patch" else _RESULT_FILE
    try:
        bound.check()
    except openshell_artifacts.Refused:
        return _null(kind, status, _RESULT_INVALID)
    try:
        directory = _private_return_dir(attempt.return_dir)
    except (OSError, ValueError):
        return _null(kind, status, _RESULT_INVALID)
    try:
        try:
            _write_once(directory, name, data)
        except (OSError, ValueError):
            return _null(kind, status, _RESULT_INVALID)
        try:
            bound.check()
        except openshell_artifacts.Refused:
            try:
                os.unlink(name, dir_fd=directory)
                os.fsync(directory)
            except OSError:
                pass
            # No descriptor names the file either way; the status records whether the
            # uncommitted bytes are verified gone.
            cleaned = _gone(directory, name)
            return _null(kind, "budget_exhausted" if cleaned else "budget_exhausted_cleanup_pending",
                         _RESULT_INVALID)
    finally:
        os.close(directory)
    descriptor = ReturnDescriptor(
        kind=kind, format="worker_proposal_bytes" if kind == "patch" else "json_object",
        path=str(attempt.return_dir / name), sha256=hashlib.sha256(data).hexdigest(),
        byte_length=len(data), base_commit=attempt.base_commit if kind == "patch" else None)
    return ReturnOutcome(kind, status, descriptor, None)


def _masked(path: str, masks: Sequence[str], mask_dirs: Sequence[str]) -> bool:
    if path in masks:
        return True
    return any(path == directory or path.startswith(directory + "/") for directory in mask_dirs)


def _locator_parts(locator: object) -> tuple[str, ...] | None:
    if not isinstance(locator, str) or not locator or locator.startswith("/"):
        return None
    parts = tuple(locator.split("/"))
    if any(part in ("", ".", "..") or "\0" in part for part in parts):
        return None
    return parts


def _collect_patch(attempt: ReturnAttempt, policy: ReturnPolicy,
                   withhold: Callable[[bytes], bool] | None,
                   bound: openshell_artifacts.Bound) -> ReturnOutcome:
    result = attempt.worker_result
    proposal = None if result is None else result.proposal
    if proposal is None:
        return _null("patch", "absent", None)
    if not isinstance(proposal, ProposalReturn):
        return _null("patch", "unknown", _UNKNOWN_PROPOSAL_CODE)
    status = proposal.status
    if status not in PROPOSAL_STATUS_TABLE:
        return _null("patch", "unknown", _UNKNOWN_PROPOSAL_CODE)
    if status != "returned":
        return _null("patch", status, PROPOSAL_STATUS_TABLE[status])
    if (type(proposal.byte_length) is not int or proposal.byte_length < 0
            or proposal.byte_length > policy.patch_cap):
        return _null("patch", status, _RESULT_INVALID)
    if any(_masked(baseline.path, attempt.masks, attempt.mask_dirs)
           for baseline in proposal.baselines):
        return _null("patch", status, _AUDIT_FAILED)
    parts = _locator_parts(proposal.locator)
    digest = proposal.proposal_bytes_digest
    if (parts is None or attempt.evidence_root is None or not isinstance(digest, str)
            or not isinstance(attempt.base_commit, str)):
        return _null("patch", status, _AUDIT_FAILED)
    try:
        bound.check()
        data = _read_capped(attempt.evidence_root, parts, policy.patch_cap)
    except openshell_artifacts.Refused:
        return _null("patch", status, _RESULT_INVALID)
    except (OSError, ValueError):
        return _null("patch", status, _AUDIT_FAILED)
    if data is None:
        return _null("patch", status, _RESULT_INVALID)
    if hashlib.sha256(data).hexdigest() != digest:
        return _null("patch", status, _AUDIT_FAILED)
    try:
        openshell_artifacts.check_binary_literals(data, policy.binary_limits, bound)
    except openshell_artifacts.Refused:
        return _null("patch", status, _RESULT_INVALID)
    return _deliver(attempt, "patch", status, data, withhold, bound)


class _Strict(ValueError):
    pass


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _Strict("duplicate_key")
        value[key] = item
    return value


def _no_constant(_name: str) -> Any:
    raise _Strict("non_finite")


def _finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise _Strict("non_finite")
    return value


_JSON_WHITESPACE = " \t\n\r"


def _strict_object(data: bytes) -> bool:
    """``x-return.result``: one JSON object, no duplicate keys, non-finite numbers or trailing
    data, and ``truncated``, when present, exactly false."""
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return False
    if text.startswith("﻿"):
        return False
    decoder = json.JSONDecoder(object_pairs_hook=_unique, parse_constant=_no_constant,
                               parse_float=_finite)
    start = len(text) - len(text.lstrip(_JSON_WHITESPACE))
    try:
        value, end = decoder.raw_decode(text, start)
    except (ValueError, RecursionError):
        return False
    if text[end:].strip(_JSON_WHITESPACE) or not isinstance(value, dict):
        return False
    return "truncated" not in value or value["truncated"] is False


def _collect_result(attempt: ReturnAttempt, withhold: Callable[[bytes], bool] | None,
                    bound: openshell_artifacts.Bound) -> ReturnOutcome:
    if attempt.out_dir is None:
        return _null("result", "out_unreachable", None)
    try:
        bound.check()
        data = _read_capped(attempt.out_dir, (_RESULT_FILE,), RESULT_CAP)
    except (openshell_artifacts.Refused, OSError, ValueError):
        return _null("result", "invalid", _RESULT_INVALID)
    if data is None or not _strict_object(data):
        return _null("result", "invalid", _RESULT_INVALID)
    return _deliver(attempt, "result", "returned", data, withhold, bound)


def collect_return(attempt: ReturnAttempt, kind: str, *, policy: ReturnPolicy,
                   withhold: Callable[[bytes], bool] | None,
                   bound: openshell_artifacts.Bound) -> ReturnOutcome:
    """Binding §3 L-S5: run the return step for one terminated attempt.

    It yields a descriptor or null with the rule's code, for every terminal state.
    ``bound`` is the return budget (``return_budget_s``); its ``cancelled`` callable is the
    return step's own, not the attempt's cancel, since a cancelled attempt still runs return.
    Returned bytes are written once, 0600 in the 0700 ``attempt.return_dir``."""
    if not isinstance(policy, ReturnPolicy) or not isinstance(attempt, ReturnAttempt):
        raise LaunchReturnError("return_arguments_invalid")
    if kind == "none":
        return _null("none", "none", None)
    try:
        if kind == "patch":
            return _collect_patch(attempt, policy, withhold, bound)
        if kind == "result":
            return _collect_result(attempt, withhold, bound)
    except openshell_artifacts.Refused:
        return _null(kind, "invalid", _RESULT_INVALID)
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return _null(kind, "invalid", _RESULT_INVALID if kind == "result" else _AUDIT_FAILED)
    raise LaunchReturnError("result_kind_invalid")


# -- L-S4: the worker terminal ------------------------------------------------------------

@dataclass(frozen=True)
class TerminalMapping:
    """The LaneExec terminal state for a chain that has started (``x-exec.after_start``)."""

    state: str
    termination: Termination | None


_FAILED_TO_START = Termination("failed_to_start", None, "harness")
_FINISHED_RUNTIME_STATES: Mapping[str, str] = MappingProxyType({
    "finished (completed)": "completed",
    "finished (cancelled)": "cancelled",
    "finished (timed_out)": "timed_out",
    "finished (failed_to_start)": "failed_to_start",
})


def map_worker_terminal(runtime_state: str | None,
                        termination: Termination | None = None) -> TerminalMapping:
    """Binding §3 L-S4 after the first chain process.

    ``runtime_state`` is the CLOSEOUT §4.3 ``runtime_state`` of the chain root's result
    record, or None when the chain root exited without one (its own refusal). A refusal at
    or after the first chain process, the CLI's or an inner WORKER ``refused``, is
    ``finished``/``failed_to_start``; ``unknown`` and every state outside the table are
    ``uncertain``. ``termination`` is the worker's, kept unchanged when its reason matches."""
    if runtime_state is None or runtime_state == "refused":
        return TerminalMapping("finished", _FAILED_TO_START)
    reason = _FINISHED_RUNTIME_STATES.get(runtime_state) if isinstance(runtime_state, str) else None
    if reason is None:
        return TerminalMapping("uncertain", None)
    if isinstance(termination, Termination) and termination.reason == reason:
        return TerminalMapping("finished", termination)
    return TerminalMapping("finished", Termination(reason, None, "harness"))


def map_worker_result(result: WorkerResult | None) -> TerminalMapping:
    """:func:`map_worker_terminal` over an in-process ``WorkerResult`` through CLOSEOUT's
    ``v2_status_mapping``; None is the chain root's own refusal."""
    if result is None:
        return map_worker_terminal(None)
    try:
        mapped = v2_status_mapping(result)
    except Exception:  # noqa: BLE001 - an unmappable result is uncertain
        return TerminalMapping("uncertain", None)
    worker = getattr(result, "termination", None)
    termination = None
    if worker is not None:
        try:
            termination = Termination(worker.reason, worker.signal, worker.by)
        except AttributeError:
            termination = None
    return map_worker_terminal(mapped.runtime_state, termination)


# -- L-S4: status ---------------------------------------------------------------------------

#: The schema's three ``uncertain`` codes admit one for a status LaneExec cannot settle:
#: placement lost after launch. The launch service stamps it on the synthesized response.
STATUS_UNCERTAIN_CODE = "sandbox_placement_lost_after_launch"
_LIVE_DISPLAYS = frozenset({"queued", "running", "cancelling"})


@dataclass(frozen=True)
class StatusMapping:
    """``state`` is the wire StatusResponse state; ``row`` names the L-S4 row that matched;
    ``launch`` is the recorded terminal response when that row applied."""

    state: str
    row: str
    launch: LaunchResponse | None


def map_status(*, record_present: bool, terminal: LaunchResponse | None,
               journal: AttemptStatus | None, claim_held: bool) -> StatusMapping:
    """Binding §3 L-S4 status table, first matching row.

    ``record_present``: a launch record exists for the id in the ``--client`` inventory.
    ``terminal``: the terminal LaunchResponse that record holds, if any. ``journal``: the
    JOURNAL ``attempt_status`` for the record's attempt id, or None when there is no JOURNAL
    attempt. ``claim_held``: LaneExec holds the exec claim. Readable JOURNAL bytes alone
    never establish a terminal: anything not live is ``uncertain``."""
    if record_present is not True:
        return StatusMapping("unknown_attempt", "no_record", None)
    if isinstance(terminal, LaunchResponse) and terminal.state in ("finished", "refused",
                                                                  "uncertain"):
        return StatusMapping(terminal.state, "laneexec_terminal", terminal)
    if (isinstance(journal, AttemptStatus) and journal.identity is not None
            and journal.display in _LIVE_DISPLAYS and journal.state == journal.display):
        return StatusMapping(journal.display, "journal_live", None)
    if journal is None:
        row = "claim_without_journal" if claim_held is True else "no_journal_attempt"
        return StatusMapping("uncertain", row, None)
    return StatusMapping("uncertain", "journal_not_live", None)


# -- L-S4: cancel ---------------------------------------------------------------------------

#: Binding §3 L-S4 cancel rows keyed by ``(cancel_attempt outcome, LaneExec holds a claim)``.
#: The zero-signal outcomes (``owner_unverified``, ``owner_not_live`` and ``unknown_attempt``
#: under a held claim) are ``cancel_pending`` and journaled locally; none is a success.
CANCEL_TABLE: Mapping[tuple[str, bool], str] = MappingProxyType({
    ("cancelled", True): "cancelled", ("cancelled", False): "cancelled",
    ("already_terminal", True): "already_terminal",
    ("already_terminal", False): "already_terminal",
    ("cancel_pending", True): "cancel_pending", ("cancel_pending", False): "cancel_pending",
    ("unknown_attempt", False): "unknown_attempt",
    ("unknown_attempt", True): "cancel_pending",
    ("owner_unverified", True): "cancel_pending", ("owner_unverified", False): "cancel_pending",
    ("owner_not_live", True): "cancel_pending", ("owner_not_live", False): "cancel_pending",
})
_ZERO_SIGNAL = frozenset({("unknown_attempt", True), ("owner_unverified", True),
                          ("owner_unverified", False), ("owner_not_live", True),
                          ("owner_not_live", False)})


@dataclass(frozen=True)
class CancelMapping:
    """``state`` is the wire CancelResponse state. ``local_outcome`` is the ``cancel_attempt``
    outcome to journal in the LaneExec launch record and evidence when no signal was sent,
    else None."""

    state: str
    local_outcome: str | None


def map_cancel(outcome: str | None, *, record_present: bool, claim_held: bool) -> CancelMapping:
    """Binding §3 L-S4 cancel table. ``outcome`` is ``cancel_attempt``'s, or None when it was
    not called. With no launch record in the ``--client`` inventory the answer is
    ``unknown_attempt``; an outcome outside the table is ``cancel_pending``, never success."""
    if record_present is not True:
        return CancelMapping("unknown_attempt", None)
    key = (outcome, claim_held is True)
    state = CANCEL_TABLE.get(key) if isinstance(outcome, str) else None
    if state is None:
        return CancelMapping("cancel_pending", "unmapped")
    return CancelMapping(state, outcome if key in _ZERO_SIGNAL else None)


# -- LaunchEvidence -----------------------------------------------------------------------

def build_launch_evidence(*, snapshot: SnapshotEvidence | None, launch_digest: str | None,
                          template_sha256: str, image_digest: str, policy_digest: str,
                          egress_sha256: str, transport_id: str, caps_sha256: str | None,
                          bridge_attached: bool, stdout_sha256: str | None,
                          stderr_sha256: str | None, exit_status: int | None,
                          duration_ms: int, renewals: int) -> LaunchEvidence:
    """``x-evidence``: a metadata-only ``LaunchEvidence``, schema-checked before it is
    returned. Streams enter only as digests; anything else refuses ``evidence_invalid``."""
    try:
        record = LaunchEvidence(snapshot, launch_digest, template_sha256, image_digest,
                                policy_digest, egress_sha256, transport_id, caps_sha256,
                                bridge_attached, stdout_sha256, stderr_sha256, exit_status,
                                duration_ms, renewals)
        valid = validate_launch_message("LaunchEvidence", record.to_json())
    except (AttributeError, TypeError, ValueError):
        valid = False
    if not valid:
        raise LaunchReturnError("evidence_invalid") from None
    return record
