"""Durable supervised attempt journal, admission index and verifying reader.

Harness-local seam IF-0-JOURNAL-1 (``plans/artifacts/v12-JOURNAL-interface.md``).
Journal lines are exactly the pinned public ``supervised_run_status.v1``
``journal_line`` records. The admission index, identifier grammar, caps, cursor
and local diagnostic codes are harness-local and never enter a public record.

Writers only append or create exclusively; every append is drained and fsynced.
Readers open read-only and make one bounded pass: they never create, truncate,
rename, unlink, chmod or break a lock, and they never repair what they read.
Diagnostics and refusals carry closed codes only, never input values, paths or
exception text. Reservation and the writer are Linux-only, because process
start identity comes from ``/proc``; readers work anywhere.

Same-login processes can forge a self-consistent chain or index. Writer binding
is not authentication against them.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
from types import MappingProxyType
import unicodedata

import rfc8785

from . import __version__ as _HARNESS_VERSION

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX hosts keep readers only
    fcntl = None
try:
    import pwd
except ImportError:  # pragma: no cover - non-POSIX hosts keep readers only
    pwd = None

JOURNAL_FAMILY = "supervised_run_status.v1"
INDEX_SCHEMA = "phase_loop.supervised_admission_index.v1"
HARNESS_ID = "phase-loop-runtime"
REDACTION_POSTURE = "digests_and_repo_relative_locators_only"
MESSAGE_LABEL = "untrusted_display_text"

#: Section 9: the only text ``AttemptWriter.event`` writes (owner ruling).
EVENT_PHRASES = frozenset({
    "attempt queued",
    "worker process started",
    "proposal bytes captured",
    "output streams digested",
    "attempt evidence bound",
    "cancellation requested",
    "workspace audit failed; proposal withheld",
    "evidence retention state recorded",
    "proposal withheld",
})
REF_KINDS = ("proposal_bytes", "evidence_envelope", "stdout", "stderr", "attempt_evidence_directory")
TERMINATION_REASONS = ("completed", "cancelled", "timed_out", "failed_to_start")
TERMINATION_BY = ("worker", "harness", "operator")
#: Public ``x-semantic-rules`` codes, used unchanged.
PUBLIC_CODES = frozenset({
    "journal_torn_line", "journal_malformed_line", "journal_unknown_version", "journal_foreign_writer",
    "attempt_overwritten", "attempt_provenance_mismatch", "attempt_evidence_copied", "refused_after_launch",
    "lifecycle_invalid", "raw_output_in_record", "locator_not_repo_relative", "projection_behind_journal",
    "projection_not_from_journal", "owner_not_live", "run_record_foreign", "runtime_not_work_outcome",
    "read_unbounded",
})
#: Harness-local codes; none of them ever appears in a public record.
LOCAL_CODES = frozenset({
    "journal_missing", "journal_unexpected_entry", "journal_path_unsafe", "journal_oversize",
    "attempt_unindexed", "index_unverifiable", "run_record_unreadable", "journal_root_unsafe",
    "identifier_invalid", "liveness_unsupported", "attempt_reserved", "run_assignment_mismatch",
    "writer_identity_mismatch", "journal_writer_busy", "journal_exists", "writer_poisoned",
    "writer_closed", "journal_write_failed", "event_cap_reached", "phrase_invalid", "ref_invalid",
    "limits_invalid",
})

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_HEX = re.compile(r"[0-9a-f]{64}")
_HEX_PATTERN = "^[0-9a-f]{64}$"
_SEGMENT = re.compile(r"([0-9]{4})\.jsonl")
_LINE_MAX_BYTES = 65536
_UNITS_MAX_BYTES = 32768
_INDEX_MAX_BYTES = 64 * 1024 * 1024
_RUN_RECORD_BYTES = 65
_REFS_MAX = 16
_STRING_MAX = 512
_MESSAGE_MAX = 200
_SCAN_MAX = 100000
_SAFE_INTEGER = 9007199254740991
_RESERVED = "attempt_reserved"
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
#: ``x-journal-rules.lifecycle`` with the implicit start: the first state is queued.
_NEXT = MappingProxyType({
    None: ("queued",),
    "queued": ("running", "refused"),
    "running": ("cancelling", "finished"),
    "cancelling": ("finished",),
    "finished": (),
    "refused": (),
})


# --------------------------------------------------------------------------
# Records (all immutable)
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    assignment_digest: str
    envelope_digest: str
    run_id: str
    attempt_id: str


@dataclass(frozen=True, slots=True)
class Units:
    target_unit_ids: tuple[str, ...]
    readonly_neighbor_unit_ids: tuple[str, ...]
    snapshot_ref: str


@dataclass(frozen=True, slots=True)
class WriterIdentity:
    harness_id: str
    harness_version: str
    writer_instance_id: str
    owner_pid: int
    process_start_time: str


@dataclass(frozen=True, slots=True)
class Ref:
    kind: str
    sha256: str
    locator: str | None


@dataclass(frozen=True, slots=True)
class Termination:
    reason: str
    signal: str | None
    by: str


@dataclass(frozen=True, slots=True)
class TerminalRefusal:
    reason: str
    constraint: str | None
    tier: str | None


@dataclass(frozen=True, slots=True)
class ResultBinding:
    envelope_digest: str
    run_id: str
    attempt_id: str
    proposal_bytes_digest: str | None
    evidence_envelope_digest: str


@dataclass(frozen=True, slots=True)
class Reservation:
    identity: AttemptIdentity
    units: Units
    index_seq: int
    entry_sha256: str
    writer: WriterIdentity


@dataclass(frozen=True, slots=True)
class ChainHead:
    segment_index: int
    segment_sha256: str
    last_seq: int


@dataclass(frozen=True, slots=True)
class JournalLimits:
    per_attempt_line_cap: int = 10000
    event_message_max_chars: int = 200
    segment_max_lines: int = 1000
    segment_max_bytes: int = 1024 * 1024
    read_segment_max_bytes: int = 4 * 1024 * 1024
    index_max_entries: int = 100000


DEFAULT_LIMITS = JournalLimits()


@dataclass(frozen=True, slots=True)
class JournalRoot:
    """A verified root, bound by device and inode; every use re-verifies it."""

    path: Path
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class JournalRefused:
    code: str


@dataclass(frozen=True, slots=True)
class IndexEntry:
    index_seq: int
    entry_sha256: str
    previous_entry_sha256: str | None
    identity: AttemptIdentity
    units: Units
    writer: WriterIdentity
    launch_digest: str
    caller_context_sha256: str


@dataclass(frozen=True, slots=True)
class TerminalRecord:
    state: str
    worker_invocations: int
    termination: Termination | None
    refusal: TerminalRefusal | None
    result_binding: ResultBinding | None


@dataclass(frozen=True, slots=True)
class AttemptRead:
    attempt_id: str
    identity: AttemptIdentity | None
    units: Units | None
    writer: WriterIdentity | None
    lines: tuple[bytes, ...]
    state: str | None
    terminal: TerminalRecord | None
    chain_head: ChainHead | None
    diagnostics: tuple[str, ...]
    display: str


@dataclass(frozen=True, slots=True)
class IndexRead:
    assignment_digest: str
    entries: tuple[IndexEntry, ...]
    head_sha256: str | None
    diagnostics: tuple[str, ...]


class _Fail(Exception):
    """Internal closed-code failure; converted at every API boundary."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------
# Closed structural checker for the five public definitions
# --------------------------------------------------------------------------

def _string(minimum=None, maximum=None):
    value = {"type": "string"}
    if minimum is not None:
        value["minLength"] = minimum
    if maximum is not None:
        value["maxLength"] = maximum
    return value


def _object(required, properties):
    return {"type": "object", "additionalProperties": False, "required": list(required),
            "properties": dict(properties)}


_SHA = {"type": "string", "pattern": _HEX_PATTERN}
_NULLABLE_SHA = {"anyOf": [_SHA, {"type": "null"}]}
_IDENTITY_SCHEMA = _object(
    ["assignment_digest", "envelope_digest", "run_id", "attempt_id"],
    {"assignment_digest": _SHA, "envelope_digest": _SHA, "run_id": _string(1, 128), "attempt_id": _string(1, 128)})
_UNIT_SCHEMA = _string(1, 200)
_UNITS_SCHEMA = _object(
    ["target_unit_ids", "readonly_neighbor_unit_ids", "snapshot_ref"],
    {"target_unit_ids": {"type": "array", "minItems": 1, "items": _UNIT_SCHEMA},
     "readonly_neighbor_unit_ids": {"type": "array", "items": _UNIT_SCHEMA}, "snapshot_ref": _SHA})
_WRITER_SCHEMA = _object(
    ["harness_id", "harness_version", "writer_instance_id", "owner_pid", "process_start_time"],
    {"harness_id": _string(1), "harness_version": _string(1), "writer_instance_id": _string(1),
     "owner_pid": {"type": "integer", "minimum": 1}, "process_start_time": _string(1)})
_REF_SCHEMA = _object(
    ["kind", "sha256", "locator"],
    {"kind": {"enum": list(REF_KINDS)}, "sha256": {"type": "string"}, "locator": {"type": ["string", "null"]}})
_HEADER_BODY = _object(
    ["body_kind", "segment_index", "previous_segment_sha256", "previous_last_seq"],
    {"body_kind": {"const": "header"}, "segment_index": {"type": "integer", "minimum": 0},
     "previous_segment_sha256": _NULLABLE_SHA, "previous_last_seq": {"type": ["integer", "null"]}})
_EVENT_BODY = _object(
    ["body_kind", "message", "refs"],
    {"body_kind": {"const": "event"},
     "message": _object(["label", "text"], {"label": {"const": MESSAGE_LABEL}, "text": {"type": "string"}}),
     "refs": {"type": "array", "items": _REF_SCHEMA}})
_STATE_BODY = _object(
    ["body_kind", "state", "worker_invocations"],
    {"body_kind": {"const": "state"}, "state": {"enum": ["queued", "running", "cancelling"]},
     "worker_invocations": {"type": "integer", "minimum": 0}})
_TERMINAL_BODY = _object(
    ["body_kind", "state", "worker_invocations", "termination", "refusal", "result_binding"],
    {"body_kind": {"const": "terminal"}, "state": {"enum": ["finished", "refused"]},
     "worker_invocations": {"type": "integer", "minimum": 0},
     "termination": {"anyOf": [{"type": "null"}, _object(
         ["reason", "signal", "by"],
         {"reason": {"enum": list(TERMINATION_REASONS)}, "signal": {"type": ["string", "null"]},
          "by": {"enum": list(TERMINATION_BY)}})]},
     "refusal": {"anyOf": [{"type": "null"}, _object(
         ["reason", "constraint", "tier"],
         {"reason": _string(1), "constraint": {"type": ["string", "null"]}, "tier": {"type": ["string", "null"]}})]},
     "result_binding": {"anyOf": [{"type": "null"}, _object(
         ["envelope_digest", "run_id", "attempt_id", "proposal_bytes_digest", "evidence_envelope_digest"],
         {"envelope_digest": _SHA, "run_id": {"type": "string"}, "attempt_id": {"type": "string"},
          "proposal_bytes_digest": _NULLABLE_SHA, "evidence_envelope_digest": _SHA})]}})
_JOURNAL_LINE = _object(
    ["schema", "version", "line_kind", "seq", "attempt", "units", "writer", "observed_at",
     "redaction_posture", "body"],
    {"schema": {"type": "string"}, "version": {"type": "string"},
     "line_kind": {"enum": ["header", "event", "state", "terminal"]},
     "seq": {"type": "integer", "minimum": 0}, "attempt": _IDENTITY_SCHEMA, "units": _UNITS_SCHEMA,
     "writer": _WRITER_SCHEMA, "observed_at": {"type": "string"},
     "redaction_posture": {"const": REDACTION_POSTURE},
     "body": {"oneOf": [_HEADER_BODY, _EVENT_BODY, _STATE_BODY, _TERMINAL_BODY]}})
_STATES = ["queued", "running", "cancelling", "finished", "refused"]
_PROJECTION = _object(
    ["schema", "assignment_digest", "attempts"],
    {"schema": {"const": JOURNAL_FAMILY + "/projection"}, "assignment_digest": _SHA,
     "attempts": {"type": "array", "items": _object(
         ["attempt", "state", "journal_seq", "segment_index", "segment_sha256"],
         {"attempt": _IDENTITY_SCHEMA, "state": {"enum": _STATES},
          "journal_seq": {"type": "integer", "minimum": 0}, "segment_index": {"type": "integer", "minimum": 0},
          "segment_sha256": _SHA})}})
_PAGE_REQUEST = _object(
    ["assignment_digest", "page_size", "cursor"],
    {"assignment_digest": _SHA, "page_size": {"type": ["integer", "null"]}, "cursor": {"type": ["string", "null"]}})
_PAGE = _object(
    ["events", "has_more", "omitted"],
    {"events": {"type": "array", "items": _JOURNAL_LINE}, "has_more": {"type": ["boolean", "null"]},
     "omitted": {"anyOf": [{"type": "null"}, _object(
         ["before", "after", "retention_dropped"],
         {"before": {"type": "integer", "minimum": 0}, "after": {"type": "integer", "minimum": 0},
          "retention_dropped": {"type": "integer", "minimum": 0}})]}})
_READER_VIEW = _object(
    ["row", "run_record", "display"],
    {"row": _object(["assignment_digest", "snapshot_ref"], {"assignment_digest": _SHA, "snapshot_ref": _SHA}),
     "run_record": _object(
         ["attempt", "units", "state", "termination_reason"],
         {"attempt": _IDENTITY_SCHEMA, "units": _UNITS_SCHEMA, "state": {"enum": _STATES},
          "termination_reason": {"type": ["string", "null"]}}),
     "display": _object(
         ["runtime_state", "work_outcome", "evidence"],
         {"runtime_state": {"type": "string"},
          "work_outcome": {"anyOf": [{"type": "null"}, _object(
              ["value", "source", "ref"],
              {"value": {"type": "string"}, "source": {"enum": ["work_result_reducer", "run_status"]},
               "ref": _NULLABLE_SHA})]},
          "evidence": {"anyOf": [{"type": "null"}, _object(
              ["source", "ref"],
              {"source": {"enum": ["requirement_admission", "run_status"]}, "ref": _SHA})]}})})

#: The checker's tables. Tests assert they equal the pinned schema's resolved
#: definitions (descriptions dropped), so a drift on either side is caught.
STRUCTURE = MappingProxyType({
    "journal_line": _JOURNAL_LINE, "projection": _PROJECTION, "page_request": _PAGE_REQUEST,
    "page": _PAGE, "reader_view": _READER_VIEW,
})
_KEYWORDS = frozenset({"type", "enum", "const", "pattern", "minLength", "maxLength", "minimum", "minItems",
                       "items", "properties", "required", "additionalProperties", "anyOf", "oneOf"})


def _is_type(value, name):
    if name == "object":
        return type(value) is dict
    if name == "array":
        return type(value) is list
    if name == "string":
        return type(value) is str
    if name == "integer":
        return type(value) is int
    if name == "boolean":
        return type(value) is bool
    if name == "null":
        return value is None
    return False


def _same(value, expected):
    return type(value) is type(expected) and value == expected


def _conforms(schema, value):
    if not _KEYWORDS.issuperset(schema):
        return False
    if "type" in schema:
        names = (schema["type"],) if isinstance(schema["type"], str) else schema["type"]
        if not any(_is_type(value, name) for name in names):
            return False
    if "enum" in schema and not any(_same(value, item) for item in schema["enum"]):
        return False
    if "const" in schema and not _same(value, schema["const"]):
        return False
    if type(value) is str:
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            return False
        if "pattern" in schema and (schema["pattern"] != _HEX_PATTERN or _HEX.fullmatch(value) is None):
            return False
    if type(value) is int and value < schema.get("minimum", value):
        return False
    if type(value) is list:
        if len(value) < schema.get("minItems", 0):
            return False
        if "items" in schema and not all(_conforms(schema["items"], item) for item in value):
            return False
    if type(value) is dict:
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and not set(value) <= set(properties):
            return False
        if not all(key in value for key in schema.get("required", ())):
            return False
        if not all(_conforms(sub, value[key]) for key, sub in properties.items() if key in value):
            return False
    if "anyOf" in schema and not any(_conforms(sub, value) for sub in schema["anyOf"]):
        return False
    if "oneOf" in schema and sum(_conforms(sub, value) for sub in schema["oneOf"]) != 1:
        return False
    return True


def check_structure(definition: str, value) -> bool:
    """True when ``value`` conforms to the pinned public ``definition``."""
    schema = STRUCTURE.get(definition) if isinstance(definition, str) else None
    if schema is None:
        return False
    try:
        return _conforms(schema, value)
    except (TypeError, ValueError, RecursionError):
        return False


# --------------------------------------------------------------------------
# Small validated helpers
# --------------------------------------------------------------------------

def _valid_id(value) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def _hex(value) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _text(value, maximum=_STRING_MAX, *, empty=False) -> bool:
    return type(value) is str and (empty or value != "") and len(value) <= maximum


def _optional_text(value) -> bool:
    return value is None or _text(value, empty=True)


def _display_safe(text: str) -> bool:
    return not any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in text)


def _repo_relative(locator: str) -> bool:
    return (locator != "" and not locator.startswith("/") and "\\" not in locator
            and ".." not in locator.split("/"))


def _count(value) -> bool:
    return type(value) is int and 0 <= value <= _SAFE_INTEGER


def _identity_json(identity: AttemptIdentity) -> dict:
    return {"assignment_digest": identity.assignment_digest, "envelope_digest": identity.envelope_digest,
            "run_id": identity.run_id, "attempt_id": identity.attempt_id}


def _units_json(units: Units) -> dict:
    return {"target_unit_ids": list(units.target_unit_ids),
            "readonly_neighbor_unit_ids": list(units.readonly_neighbor_unit_ids),
            "snapshot_ref": units.snapshot_ref}


def _writer_json(writer: WriterIdentity) -> dict:
    return {"harness_id": writer.harness_id, "harness_version": writer.harness_version,
            "writer_instance_id": writer.writer_instance_id, "owner_pid": writer.owner_pid,
            "process_start_time": writer.process_start_time}


def _identity_of(value) -> AttemptIdentity:
    return AttemptIdentity(value["assignment_digest"], value["envelope_digest"], value["run_id"],
                           value["attempt_id"])


def _units_of(value) -> Units:
    return Units(tuple(value["target_unit_ids"]), tuple(value["readonly_neighbor_unit_ids"]),
                 value["snapshot_ref"])


def _writer_of(value) -> WriterIdentity:
    return WriterIdentity(value["harness_id"], value["harness_version"], value["writer_instance_id"],
                          value["owner_pid"], value["process_start_time"])


def _valid_identity(identity) -> bool:
    return (isinstance(identity, AttemptIdentity) and _hex(identity.assignment_digest)
            and _hex(identity.envelope_digest) and _valid_id(identity.run_id) and _valid_id(identity.attempt_id))


def _normal_units(units) -> Units | None:
    if not isinstance(units, Units):
        return None
    targets, neighbors = units.target_unit_ids, units.readonly_neighbor_unit_ids
    if not isinstance(targets, (tuple, list)) or not isinstance(neighbors, (tuple, list)):
        return None
    normal = Units(tuple(targets), tuple(neighbors), units.snapshot_ref)
    if (not normal.target_unit_ids or not _hex(normal.snapshot_ref)
            or not all(_text(item, 200) for item in normal.target_unit_ids + normal.readonly_neighbor_unit_ids)):
        return None
    if len(rfc8785.dumps(_units_json(normal))) > _UNITS_MAX_BYTES:
        return None
    return normal


def _valid_writer(writer) -> bool:
    return (isinstance(writer, WriterIdentity) and _text(writer.harness_id) and _text(writer.harness_version)
            and _text(writer.writer_instance_id) and type(writer.owner_pid) is int and writer.owner_pid >= 1
            and _text(writer.process_start_time))


def _strings_bounded(value) -> bool:
    if type(value) is str:
        return len(value) <= _STRING_MAX
    if type(value) is dict:
        return all(_strings_bounded(item) for item in value.values())
    if type(value) is list:
        return all(_strings_bounded(item) for item in value)
    return True


def _strict_json(raw: bytes):
    """Parse one JSON text, refusing duplicates, non-integers and unsafe values."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def integer(text):
        value = int(text)
        if abs(value) > _SAFE_INTEGER:
            raise ValueError()
        return value

    def refuse(_):
        raise ValueError()

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_int=integer,
                       parse_float=refuse, parse_constant=refuse)
    stack = [value]
    while stack:
        item = stack.pop()
        if type(item) is str and any(0xD800 <= ord(c) <= 0xDFFF for c in item):
            raise ValueError()
        if type(item) is dict:
            stack.extend(item.keys())
            stack.extend(item.values())
        elif type(item) is list:
            stack.extend(item)
    return value


def _parse(raw: bytes):
    try:
        return _strict_json(raw)
    except (ValueError, UnicodeError, RecursionError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# Trusted filesystem primitives
# --------------------------------------------------------------------------

def _trusted(st, directory: bool) -> bool:
    if st.st_uid != os.geteuid():
        return False
    if stat.S_IMODE(st.st_mode) != (0o700 if directory else 0o600):
        return False
    if directory:
        return stat.S_ISDIR(st.st_mode)
    return stat.S_ISREG(st.st_mode) and st.st_nlink == 1


def _keep(stack: ExitStack, fd: int) -> int:
    stack.callback(os.close, fd)
    return fd


def _verified(fd: int, directory: bool) -> int:
    try:
        trusted = _trusted(os.fstat(fd), directory)
    except OSError:
        trusted = False
    if not trusted:
        os.close(fd)
        raise _Fail("journal_path_unsafe")
    return fd


def _subdir(parent_fd: int, name: str) -> int:
    """Open one verified directory component; ``FileNotFoundError`` propagates."""
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        raise
    except OSError:
        raise _Fail("journal_path_unsafe") from None
    return _verified(fd, True)


def _read_all(fd: int, cap: int) -> bytes | None:
    chunks, total = [], 0
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > cap:
            return None
        chunks.append(chunk)


def _read_file(parent_fd: int, name: str, cap: int, oversize: str) -> bytes:
    """One verified, bounded, read-only file read; ``FileNotFoundError`` propagates."""
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        raise
    except OSError:
        raise _Fail("journal_path_unsafe") from None
    fd = _verified(fd, False)
    try:
        if os.fstat(fd).st_size > cap:
            raise _Fail(oversize)
        data = _read_all(fd, cap)
    finally:
        os.close(fd)
    if data is None:
        raise _Fail(oversize)
    return data


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def _barrier(fd: int) -> None:
    """fsync ``fd``. A failure is a write failure, never a trust failure.

    Every barrier runs whether this call created the entry or adopted one left
    by a creator that may have died, or failed, before its own barrier. The
    barrier is idempotent, so adoption always completes the durability chain.
    """
    try:
        os.fsync(fd)
    except OSError:
        raise _Fail("journal_write_failed") from None


def _lock(parent_fd: int) -> int:
    """Open (creating 0600 if absent) a verified ``lock`` under ``parent_fd``; its entry is made durable."""
    created = True
    try:
        fd = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                     dir_fd=parent_fd)
    except FileExistsError:
        created = False
        try:
            fd = os.open("lock", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent_fd)
        except OSError:
            raise _Fail("journal_path_unsafe") from None
    if created:
        try:
            os.fchmod(fd, 0o600)
        except BaseException:
            os.close(fd)
            raise
    fd = _verified(fd, False)
    try:
        _barrier(parent_fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _walk(text: str, *, create: bool) -> tuple[int, list[tuple[int, int]]]:
    """Open ``text`` one component at a time with O_NOFOLLOW at each component."""
    fd = os.open("/", _DIR_FLAGS)
    chain = []
    try:
        st = os.fstat(fd)
        chain.append((st.st_dev, st.st_ino))
        for name in PurePosixPath(text).parts[1:]:
            created = False
            try:
                child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                    created = True
                except FileExistsError:
                    pass
                child = os.open(name, _DIR_FLAGS, dir_fd=fd)
                if created:
                    try:
                        os.fchmod(child, 0o700)
                    except BaseException:
                        os.close(child)
                        raise
            try:
                st = os.fstat(child)
                # Creating a root also completes the entry barrier of every
                # component this account owns: one may be a crashed creator's.
                if create and (created or st.st_uid == os.geteuid()):
                    _barrier(fd)
            except BaseException:
                os.close(child)
                raise
            os.close(fd)
            fd = child
            chain.append((st.st_dev, st.st_ino))
            if created and not _trusted(st, True):
                raise _Fail("journal_root_unsafe")
        return fd, chain
    except BaseException:
        os.close(fd)
        raise


def _root_fd(root) -> int:
    if not isinstance(root, JournalRoot) or not isinstance(root.path, Path):
        raise _Fail("journal_root_unsafe")
    try:
        fd, _ = _walk(str(root.path), create=False)
    except FileNotFoundError:
        raise _Fail("journal_path_unsafe") from None
    except OSError:
        raise _Fail("journal_path_unsafe") from None
    try:
        st = os.fstat(fd)
        bound = (st.st_dev, st.st_ino) == (root.device, root.inode) and _trusted(st, True)
    except OSError:
        bound = False
    if not bound:
        os.close(fd)
        raise _Fail("journal_path_unsafe")
    return fd


def _nested(outer: str, inner: str) -> bool:
    return inner == outer or inner.startswith(outer.rstrip("/") + "/")


def _excluded_paths(excluded) -> tuple[str, ...] | None:
    try:
        items = tuple(excluded)
    except TypeError:
        return None
    out = []
    for item in items:
        try:
            raw = os.fspath(item)
        except TypeError:
            return None
        if not isinstance(raw, str) or not raw.startswith("/") or "\x00" in raw:
            return None
        out.append(raw)
    return tuple(out)


# --------------------------------------------------------------------------
# Root and identity
# --------------------------------------------------------------------------

def default_journal_root() -> Path:
    """The fixed per-user root, derived from the password database, never the environment."""
    if pwd is None:  # pragma: no cover - non-POSIX
        raise OSError("journal_root_unsafe")
    home = pwd.getpwuid(os.geteuid()).pw_dir
    return Path(home) / ".local" / "state" / "agent-harness" / "supervised-worker" / "journal"


def open_journal_root(path: Path, *, create: bool, excluded: tuple[Path, ...] = ()) -> JournalRoot | JournalRefused:
    try:
        text = os.fspath(path)
    except TypeError:
        return JournalRefused("journal_root_unsafe")
    if not isinstance(text, str) or not text.startswith("/") or "\x00" in text:
        return JournalRefused("journal_root_unsafe")
    pure = PurePosixPath(text)
    if ".." in pure.parts:
        return JournalRefused("journal_root_unsafe")
    text = str(pure)
    roots = _excluded_paths(excluded)
    if roots is None:
        return JournalRefused("journal_root_unsafe")
    for raw in roots:
        for form in {os.path.normpath(raw), os.path.realpath(raw)}:
            if _nested(form, text) or _nested(text, form):
                return JournalRefused("journal_root_unsafe")
    try:
        fd, chain = _walk(text, create=bool(create))
    except FileNotFoundError:
        return JournalRefused("journal_missing")
    except _Fail as failure:
        return JournalRefused(failure.code)
    except OSError:
        return JournalRefused("journal_root_unsafe")
    try:
        st = os.fstat(fd)
        if not _trusted(st, True):
            return JournalRefused("journal_root_unsafe")
        for raw in roots:
            try:
                other = os.stat(raw)
            except OSError:
                continue
            if (other.st_dev, other.st_ino) in chain:
                return JournalRefused("journal_root_unsafe")
        for name in ("attempts", "assignments", "runs"):
            try:
                child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    continue
                os.mkdir(name, 0o700, dir_fd=fd)
                child = os.open(name, _DIR_FLAGS, dir_fd=fd)
                try:
                    os.fchmod(child, 0o700)
                except BaseException:
                    os.close(child)
                    raise
            trusted = _trusted(os.fstat(child), True)
            os.close(child)
            if not trusted:
                return JournalRefused("journal_root_unsafe")
        if create:
            _barrier(fd)
        return JournalRoot(Path(text), st.st_dev, st.st_ino)
    except _Fail as failure:
        return JournalRefused(failure.code)
    except OSError:
        return JournalRefused("journal_root_unsafe")
    finally:
        os.close(fd)


def _read_proc(path: str) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        return os.read(fd, 4096)
    finally:
        os.close(fd)


def process_start_identity(pid: int) -> str | None:
    """``linux-proc:<boot_id>:<starttime clock ticks>`` for a live process, else None."""
    if type(pid) is not int or pid < 1:
        return None
    try:
        boot = _read_proc("/proc/sys/kernel/random/boot_id").decode("ascii").strip()
        fields = _read_proc(f"/proc/{pid}/stat").decode("ascii", "replace").rsplit(")", 1)[1].split()
        state, start = fields[0], fields[19]
    except (OSError, UnicodeError, IndexError):
        return None
    if state in ("Z", "X", "x") or not start.isdigit() or re.fullmatch(r"[0-9a-f-]{36}", boot) is None:
        return None
    return f"linux-proc:{boot}:{start}"


def make_ref(kind: str, data: bytes, locator: str | None) -> Ref:
    """A digest-only reference; ``data`` itself is never kept or written."""
    if (not isinstance(kind, str) or kind not in REF_KINDS or not isinstance(data, (bytes, bytearray, memoryview))
            or not (locator is None or (_text(locator) and _repo_relative(locator)))):
        raise ValueError("ref_invalid") from None
    return Ref(kind, hashlib.sha256(data).hexdigest(), locator)


def _valid_ref(ref) -> bool:
    return (isinstance(ref, Ref) and ref.kind in REF_KINDS and _hex(ref.sha256)
            and (ref.locator is None or (_text(ref.locator) and _repo_relative(ref.locator))))


def _mint_writer() -> WriterIdentity | None:
    start = process_start_identity(os.getpid())
    if start is None or fcntl is None:
        return None
    return WriterIdentity(HARNESS_ID, _HARNESS_VERSION, secrets.token_hex(16), os.getpid(), start)


# --------------------------------------------------------------------------
# Admission index (local)
# --------------------------------------------------------------------------

_INDEX_KEYS = frozenset({"schema", "version", "index_seq", "previous_entry_sha256", "assignment_digest",
                         "envelope_digest", "run_id", "attempt_id", "launch_digest", "caller_context_sha256",
                         "units", "writer"})


def _index_entry(raw: bytes, position: int, previous: str | None, digest: str) -> IndexEntry:
    obj = _parse(raw)
    if type(obj) is not dict or set(obj) != _INDEX_KEYS:
        raise _Fail("index_unverifiable")
    try:
        canonical = rfc8785.dumps(obj) == raw
    except Exception:
        canonical = False
    if not canonical:
        raise _Fail("index_unverifiable")
    if obj["schema"] != INDEX_SCHEMA or obj["version"] != "1" or not _same(obj["index_seq"], position):
        raise _Fail("index_unverifiable")
    if obj["previous_entry_sha256"] != previous:
        raise _Fail("index_unverifiable")
    if obj["assignment_digest"] != digest:
        raise _Fail("index_unverifiable")
    if (not _hex(obj["envelope_digest"]) or not _valid_id(obj["run_id"]) or not _valid_id(obj["attempt_id"])
            or not _hex(obj["launch_digest"]) or not _hex(obj["caller_context_sha256"])
            or not _conforms(_UNITS_SCHEMA, obj["units"]) or not _conforms(_WRITER_SCHEMA, obj["writer"])):
        raise _Fail("index_unverifiable")
    return IndexEntry(position, _sha256(raw), previous, _identity_of(obj), _units_of(obj["units"]),
                      _writer_of(obj["writer"]), obj["launch_digest"], obj["caller_context_sha256"])


def _load_index(assignment_fd: int, digest: str) -> tuple[tuple[IndexEntry, ...], str | None]:
    """Read and verify the whole index once; any defect is ``index_unverifiable``."""
    try:
        data = _read_file(assignment_fd, "index.jsonl", _INDEX_MAX_BYTES, "index_unverifiable")
    except FileNotFoundError:
        return (), None
    if data and not data.endswith(b"\n"):
        raise _Fail("index_unverifiable")
    lines = data.split(b"\n")[:-1]
    if len(lines) > DEFAULT_LIMITS.index_max_entries:
        raise _Fail("index_unverifiable")
    entries, previous, seen = [], None, set()
    for position, raw in enumerate(lines):
        entry = _index_entry(raw, position, previous, digest)
        if entry.identity.attempt_id in seen:
            raise _Fail("index_unverifiable")
        seen.add(entry.identity.attempt_id)
        entries.append(entry)
        previous = entry.entry_sha256
    return tuple(entries), previous


def read_index(root: JournalRoot, assignment_digest: str) -> IndexRead:
    if not _hex(assignment_digest):
        return IndexRead("", (), None, ("identifier_invalid",))
    try:
        with ExitStack() as stack:
            root_fd = _keep(stack, _root_fd(root))
            assignments_fd = _keep(stack, _subdir(root_fd, "assignments"))
            assignment_fd = _keep(stack, _subdir(assignments_fd, assignment_digest))
            entries, head = _load_index(assignment_fd, assignment_digest)
    except FileNotFoundError:
        return IndexRead(assignment_digest, (), None, ())
    except _Fail as failure:
        return IndexRead(assignment_digest, (), None, (failure.code,))
    except OSError:
        return IndexRead(assignment_digest, (), None, ("journal_path_unsafe",))
    return IndexRead(assignment_digest, entries, head, ())


def _open_run(runs_fd: int, run_id: str) -> int | None:
    """A verified read-only descriptor of ``runs/<run_id>``, or None when absent."""
    try:
        fd = os.open(run_id, _READ_FLAGS, dir_fd=runs_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise _Fail("run_record_unreadable") from None
    try:
        return _verified(fd, False)
    except _Fail:
        raise _Fail("run_record_unreadable") from None


def _run_digest(fd: int) -> str:
    data = _read_all(fd, _RUN_RECORD_BYTES)
    if (data is None or len(data) != _RUN_RECORD_BYTES or not data.endswith(b"\n")
            or _HEX.fullmatch(data[:-1].decode("ascii", "replace")) is None):
        raise _Fail("run_record_unreadable")
    return data[:-1].decode("ascii")


def _read_run(runs_fd: int, run_id: str) -> str | None:
    fd = _open_run(runs_fd, run_id)
    if fd is None:
        return None
    try:
        return _run_digest(fd)
    finally:
        os.close(fd)


def resolve_run(root: JournalRoot, run_id: str) -> tuple[str, ...] | JournalRefused:
    if not _valid_id(run_id):
        return JournalRefused("identifier_invalid")
    try:
        with ExitStack() as stack:
            root_fd = _keep(stack, _root_fd(root))
            try:
                runs_fd = _keep(stack, _subdir(root_fd, "runs"))
            except FileNotFoundError:
                return ()
            digest = _read_run(runs_fd, run_id)
            if digest is None:
                return ()
            try:
                assignments_fd = _keep(stack, _subdir(root_fd, "assignments"))
                assignment_fd = _keep(stack, _subdir(assignments_fd, digest))
            except FileNotFoundError:
                return ()
            entries, _ = _load_index(assignment_fd, digest)
    except _Fail as failure:
        return JournalRefused(failure.code)
    except OSError:
        return JournalRefused("journal_path_unsafe")
    return tuple(entry.identity.attempt_id for entry in entries if entry.identity.run_id == run_id)


# --------------------------------------------------------------------------
# Reservation (section 5)
# --------------------------------------------------------------------------

def _assignment_dir(assignments_fd: int, digest: str) -> int:
    """Create or adopt ``assignments/<digest>``; its entry is fsynced on every reservation."""
    created = True
    try:
        os.mkdir(digest, 0o700, dir_fd=assignments_fd)
    except FileExistsError:
        created = False
    except OSError:
        raise _Fail("journal_path_unsafe") from None
    try:
        fd = os.open(digest, _DIR_FLAGS, dir_fd=assignments_fd)
    except OSError:
        raise _Fail("journal_path_unsafe") from None
    if created:
        try:
            os.fchmod(fd, 0o700)
        except BaseException:
            os.close(fd)
            raise
    fd = _verified(fd, True)
    try:
        _barrier(assignments_fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _claim_run(runs_fd: int, run_id: str, digest: str) -> None:
    """Write or adopt the run claim; the claim file and ``runs/`` are fsynced every time."""
    record = (digest + "\n").encode("ascii")
    for _ in range(3):
        fd = _open_run(runs_fd, run_id)
        if fd is None:
            try:
                fd = os.open(run_id, _CREATE_FLAGS, 0o600, dir_fd=runs_fd)
            except FileExistsError:
                continue
            try:
                os.fchmod(fd, 0o600)
                _write_all(fd, record)
            except BaseException:
                os.close(fd)
                raise
        else:
            try:
                existing = _run_digest(fd)
            except BaseException:
                os.close(fd)
                raise
            if existing != digest:
                os.close(fd)
                raise _Fail("run_assignment_mismatch")
        try:
            _barrier(fd)
        finally:
            os.close(fd)
        _barrier(runs_fd)
        return
    raise _Fail("run_record_unreadable")


def _claim_attempt(attempts_fd: int, attempt_id: str) -> None:
    try:
        os.mkdir(attempt_id, 0o700, dir_fd=attempts_fd)
    except FileExistsError:
        raise _Fail("attempt_reserved") from None
    fd = os.open(attempt_id, _DIR_FLAGS, dir_fd=attempts_fd)
    try:
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
    _barrier(attempts_fd)


def _append_index(assignment_fd: int, line: bytes) -> None:
    created = True
    try:
        index_fd = os.open("index.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                           | os.O_CLOEXEC, 0o600, dir_fd=assignment_fd)
    except FileExistsError:
        created = False
        index_fd = os.open("index.jsonl", os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                           dir_fd=assignment_fd)
    try:
        if created:
            os.fchmod(index_fd, 0o600)
        if not _trusted(os.fstat(index_fd), False):
            raise _Fail("journal_path_unsafe")
        _write_all(index_fd, line)
        _barrier(index_fd)
    finally:
        os.close(index_fd)
    # Created now or by an earlier reservation whose directory barrier failed.
    _barrier(assignment_fd)


def reserve_attempt(root: JournalRoot, identity: AttemptIdentity, *, units: Units, launch_digest: str,
                    caller_context_sha256: str) -> Reservation | JournalRefused:
    """Atomically and durably claim ``identity.attempt_id`` before any launch."""
    if not isinstance(root, JournalRoot):
        return JournalRefused("journal_root_unsafe")
    units = _normal_units(units)
    if (not _valid_identity(identity) or units is None or not _hex(launch_digest)
            or not _hex(caller_context_sha256)):
        return JournalRefused("identifier_invalid")
    writer = _mint_writer()
    if writer is None:
        return JournalRefused("liveness_unsupported")
    try:
        with ExitStack() as stack:
            root_fd = _keep(stack, _root_fd(root))
            assignments_fd = _keep(stack, _subdir(root_fd, "assignments"))
            assignment_fd = _keep(stack, _assignment_dir(assignments_fd, identity.assignment_digest))
            lock_fd = _keep(stack, _lock(assignment_fd))
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            entries, head = _load_index(assignment_fd, identity.assignment_digest)
            if len(entries) >= DEFAULT_LIMITS.index_max_entries:
                raise _Fail("index_unverifiable")
            if any(entry.identity.attempt_id == identity.attempt_id for entry in entries):
                raise _Fail(_RESERVED)
            runs_fd = _keep(stack, _subdir(root_fd, "runs"))
            _claim_run(runs_fd, identity.run_id, identity.assignment_digest)
            attempts_fd = _keep(stack, _subdir(root_fd, "attempts"))
            _claim_attempt(attempts_fd, identity.attempt_id)
            entry = {"schema": INDEX_SCHEMA, "version": "1", "index_seq": len(entries),
                     "previous_entry_sha256": head, "launch_digest": launch_digest,
                     "caller_context_sha256": caller_context_sha256, "units": _units_json(units),
                     "writer": _writer_json(writer), **_identity_json(identity)}
            raw = rfc8785.dumps(entry)
            _append_index(assignment_fd, raw + b"\n")
    except _Fail as failure:
        return JournalRefused(failure.code)
    except FileNotFoundError:
        return JournalRefused("journal_missing")
    except OSError:
        return JournalRefused("journal_write_failed")
    return Reservation(identity, units, len(entries), _sha256(raw), writer)


# --------------------------------------------------------------------------
# Writer (section 6)
# --------------------------------------------------------------------------

def _limits_ok(limits) -> bool:
    if not isinstance(limits, JournalLimits):
        return False
    values = (limits.per_attempt_line_cap, limits.event_message_max_chars, limits.segment_max_lines,
              limits.segment_max_bytes, limits.read_segment_max_bytes, limits.index_max_entries)
    if not all(type(value) is int and value > 0 for value in values):
        return False
    return (4 <= limits.per_attempt_line_cap <= 19998 and limits.segment_max_lines >= 2
            and limits.segment_max_bytes >= 2 * _LINE_MAX_BYTES
            and limits.read_segment_max_bytes >= limits.segment_max_bytes
            and 1 <= limits.event_message_max_chars <= _MESSAGE_MAX)


class AttemptWriter:
    """The single writer of one attempt journal; built only by ``open_writer``."""

    __slots__ = ("_identity", "_units", "_writer", "_limits", "_attempt_fd", "_lock_fd", "_segment_fd",
                 "_segment_index", "_segment_lines", "_segment_bytes", "_hash", "_next_seq", "_total_lines",
                 "_state", "_invocations", "_terminal", "_poisoned", "_closed")

    def __init__(self, identity, units, writer, limits, attempt_fd, lock_fd):
        self._identity, self._units, self._writer, self._limits = identity, units, writer, limits
        self._attempt_fd, self._lock_fd, self._segment_fd = attempt_fd, lock_fd, None
        self._segment_index, self._segment_lines, self._segment_bytes = 0, 0, 0
        self._hash = hashlib.sha256()
        self._next_seq, self._total_lines = 0, 0
        self._state, self._invocations = None, 0
        self._terminal = self._poisoned = self._closed = False

    def _line(self, kind: str, body: dict, seq: int) -> bytes:
        line = {"schema": JOURNAL_FAMILY, "version": "1", "line_kind": kind, "seq": seq,
                "attempt": _identity_json(self._identity), "units": _units_json(self._units),
                "writer": _writer_json(self._writer), "observed_at": _now(),
                "redaction_posture": REDACTION_POSTURE, "body": body}
        if not _strings_bounded(line):
            raise _Fail("raw_output_in_record")
        data = rfc8785.dumps(line) + b"\n"
        if len(data) > _LINE_MAX_BYTES:
            raise _Fail("raw_output_in_record")
        return data

    def _header(self, index: int, previous: str | None, last: int | None) -> bytes:
        return self._line("header", {"body_kind": "header", "segment_index": index,
                                     "previous_segment_sha256": previous, "previous_last_seq": last},
                          self._next_seq)

    def _start_segment(self, index: int, previous: str | None, last: int | None) -> None:
        fd = os.open(f"{index:04d}.jsonl", _CREATE_FLAGS | os.O_APPEND, 0o600, dir_fd=self._attempt_fd)
        old, self._segment_fd = self._segment_fd, fd
        try:
            os.fchmod(fd, 0o600)
            header = self._header(index, previous, last)
            _write_all(fd, header)
            os.fsync(fd)
            os.fsync(self._attempt_fd)
        finally:
            if old is not None:
                os.close(old)
        self._hash = hashlib.sha256(header)
        self._segment_index, self._segment_lines, self._segment_bytes = index, 1, len(header)
        self._total_lines += 1
        self._next_seq += 1

    def _rotate(self) -> None:
        previous = self._hash.hexdigest()
        self._start_segment(self._segment_index + 1, previous, self._next_seq - 1)

    def _head(self) -> ChainHead:
        return ChainHead(self._segment_index, self._hash.hexdigest(), self._next_seq - 1)

    def _blocked(self) -> JournalRefused | None:
        if self._closed:
            return JournalRefused("writer_closed")
        if self._poisoned:
            return JournalRefused("writer_poisoned")
        return None

    def _transition_ok(self, new: str) -> bool:
        return not self._terminal and new in _NEXT[self._state]

    def _append(self, kind: str, body: dict, *, terminal: bool) -> ChainHead | JournalRefused:
        limits = self._limits
        try:
            data = self._line(kind, body, self._next_seq)
        except _Fail as failure:
            return JournalRefused(failure.code)
        rotate = (self._segment_lines + 1 > limits.segment_max_lines
                  or self._segment_bytes + len(data) > limits.segment_max_bytes)
        needed = 2 if rotate else 1
        cap = limits.per_attempt_line_cap if terminal else limits.per_attempt_line_cap - 2
        if self._total_lines + needed > cap:
            return JournalRefused("event_cap_reached")
        try:
            if rotate:
                self._rotate()
                data = self._line(kind, body, self._next_seq)
            _write_all(self._segment_fd, data)
            self._hash.update(data)
            os.fsync(self._segment_fd)
        except (OSError, _Fail):
            self._poisoned = True
            return JournalRefused("journal_write_failed")
        self._segment_lines += 1
        self._segment_bytes += len(data)
        self._total_lines += 1
        self._next_seq += 1
        return self._head()

    def state(self, state: str, *, worker_invocations: int) -> ChainHead | JournalRefused:
        blocked = self._blocked()
        if blocked is not None:
            return blocked
        if state not in ("queued", "running", "cancelling") or not _count(worker_invocations):
            return JournalRefused("lifecycle_invalid")
        if not self._transition_ok(state) or worker_invocations < self._invocations:
            return JournalRefused("lifecycle_invalid")
        head = self._append("state", {"body_kind": "state", "state": state,
                                      "worker_invocations": worker_invocations}, terminal=False)
        if isinstance(head, ChainHead):
            self._state, self._invocations = state, worker_invocations
        return head

    def event(self, phrase: str, *, refs=()) -> ChainHead | JournalRefused:
        blocked = self._blocked()
        if blocked is not None:
            return blocked
        if self._terminal:
            return JournalRefused("lifecycle_invalid")
        if not isinstance(phrase, str) or phrase not in EVENT_PHRASES:
            return JournalRefused("phrase_invalid")
        if len(phrase) > self._limits.event_message_max_chars:
            return JournalRefused("raw_output_in_record")
        try:
            refs = tuple(refs)
        except TypeError:
            return JournalRefused("ref_invalid")
        if len(refs) > _REFS_MAX or not all(_valid_ref(ref) for ref in refs):
            return JournalRefused("ref_invalid")
        body = {"body_kind": "event", "message": {"label": MESSAGE_LABEL, "text": phrase},
                "refs": [{"kind": ref.kind, "sha256": ref.sha256, "locator": ref.locator} for ref in refs]}
        return self._append("event", body, terminal=False)

    def terminal(self, state: str, *, worker_invocations: int, termination: Termination | None,
                 refusal: TerminalRefusal | None, result_binding: ResultBinding | None) -> ChainHead | JournalRefused:
        blocked = self._blocked()
        if blocked is not None:
            return blocked
        if state not in ("finished", "refused") or not _count(worker_invocations):
            return JournalRefused("lifecycle_invalid")
        if not self._transition_ok(state) or worker_invocations < self._invocations:
            return JournalRefused("lifecycle_invalid")
        if state == "finished":
            if (not isinstance(termination, Termination) or termination.reason not in TERMINATION_REASONS
                    or termination.by not in TERMINATION_BY or not _optional_text(termination.signal)
                    or refusal is not None):
                return JournalRefused("lifecycle_invalid")
        elif (not isinstance(refusal, TerminalRefusal) or not _text(refusal.reason)
              or not _optional_text(refusal.constraint) or not _optional_text(refusal.tier)
              or termination is not None or worker_invocations != 0 or result_binding is not None):
            return JournalRefused("lifecycle_invalid")
        binding = None
        if result_binding is not None:
            identity = self._identity
            if (not isinstance(result_binding, ResultBinding) or not _hex(result_binding.envelope_digest)
                    or not _hex(result_binding.evidence_envelope_digest)
                    or not (result_binding.proposal_bytes_digest is None or _hex(result_binding.proposal_bytes_digest))):
                return JournalRefused("lifecycle_invalid")
            if (result_binding.envelope_digest, result_binding.run_id, result_binding.attempt_id) != (
                    identity.envelope_digest, identity.run_id, identity.attempt_id):
                return JournalRefused("attempt_provenance_mismatch")
            binding = {"envelope_digest": result_binding.envelope_digest, "run_id": result_binding.run_id,
                       "attempt_id": result_binding.attempt_id,
                       "proposal_bytes_digest": result_binding.proposal_bytes_digest,
                       "evidence_envelope_digest": result_binding.evidence_envelope_digest}
        body = {"body_kind": "terminal", "state": state, "worker_invocations": worker_invocations,
                "termination": None if termination is None else {
                    "reason": termination.reason, "signal": termination.signal, "by": termination.by},
                "refusal": None if refusal is None else {
                    "reason": refusal.reason, "constraint": refusal.constraint, "tier": refusal.tier},
                "result_binding": binding}
        head = self._append("terminal", body, terminal=True)
        if isinstance(head, ChainHead):
            self._terminal, self._state, self._invocations = True, state, worker_invocations
        return head

    def close(self) -> None:
        """Release the lock and every descriptor; idempotent and never raises."""
        if self._closed:
            return
        self._closed = True
        for fd in (self._segment_fd, self._lock_fd, self._attempt_fd):
            if fd is None:
                continue
            try:
                os.close(fd)
            except OSError:
                pass


def open_writer(root: JournalRoot, reservation: Reservation, *,
                limits: JournalLimits = DEFAULT_LIMITS) -> AttemptWriter | JournalRefused:
    """Open the single, never-resumed writer for a reservation made in this process."""
    if fcntl is None or process_start_identity(os.getpid()) is None:
        return JournalRefused("liveness_unsupported")
    if (not isinstance(reservation, Reservation) or not _valid_identity(reservation.identity)
            or _normal_units(reservation.units) != reservation.units or not _valid_writer(reservation.writer)):
        return JournalRefused("identifier_invalid")
    if not _limits_ok(limits):
        return JournalRefused("limits_invalid")
    writer = reservation.writer
    if (writer.owner_pid != os.getpid()
            or writer.process_start_time != process_start_identity(os.getpid())):
        return JournalRefused("writer_identity_mismatch")
    identity = reservation.identity
    stack = ExitStack()
    try:
        root_fd = _keep(stack, _root_fd(root))
        assignments_fd = _keep(stack, _subdir(root_fd, "assignments"))
        assignment_fd = _keep(stack, _subdir(assignments_fd, identity.assignment_digest))
        entries, _ = _load_index(assignment_fd, identity.assignment_digest)
        if not any(entry.index_seq == reservation.index_seq and entry.entry_sha256 == reservation.entry_sha256
                   and entry.identity == identity and entry.units == reservation.units
                   and entry.writer == reservation.writer for entry in entries):
            raise _Fail("attempt_unindexed")
        attempts_fd = _keep(stack, _subdir(root_fd, "attempts"))
        attempt_fd = _subdir(attempts_fd, identity.attempt_id)
        stack.close()
    except _Fail as failure:
        stack.close()
        return JournalRefused(failure.code)
    except FileNotFoundError:
        stack.close()
        return JournalRefused("journal_missing")
    except OSError:
        stack.close()
        return JournalRefused("journal_path_unsafe")
    lock_fd = None
    try:
        lock_fd = _lock(attempt_fd)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise _Fail("journal_writer_busy") from None
        if any(name != "lock" for name in os.listdir(attempt_fd)):
            raise _Fail("journal_exists")
    except _Fail as failure:
        code = failure.code
    except OSError:
        code = "journal_write_failed"
    else:
        attempt = AttemptWriter(identity, reservation.units, writer, limits, attempt_fd, lock_fd)
        try:
            attempt._start_segment(0, None, None)
        except (OSError, _Fail):
            attempt.close()
            return JournalRefused("journal_write_failed")
        return attempt
    for fd in (lock_fd, attempt_fd):
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    return JournalRefused(code)


# --------------------------------------------------------------------------
# Reader (section 7)
# --------------------------------------------------------------------------

def _unknown(attempt_id, diagnostics, entry: IndexEntry | None = None) -> AttemptRead:
    return AttemptRead(attempt_id if _valid_id(attempt_id) else "", entry.identity if entry else None,
                       entry.units if entry else None, entry.writer if entry else None, (), None, None, None,
                       tuple(sorted(set(diagnostics))), "unknown")


def _assignment_names(assignments_fd: int) -> list[str]:
    names = []
    with os.scandir(assignments_fd) as entries:
        for item in entries:
            if len(names) >= _SCAN_MAX:
                raise _Fail("journal_oversize")
            if _hex(item.name):
                names.append(item.name)
    return sorted(names)


def _locate(root_fd: int, attempt_id: str, hint: str | None):
    """The index entry naming ``attempt_id``: (entry, entries, diagnostics)."""
    try:
        assignments_fd = _subdir(root_fd, "assignments")
    except FileNotFoundError:
        return None, (), {"attempt_unindexed"}
    except _Fail as failure:
        return None, (), {failure.code}
    try:
        names = [hint] if hint is not None else _assignment_names(assignments_fd)
        unverifiable = False
        for name in names:
            try:
                assignment_fd = _subdir(assignments_fd, name)
            except FileNotFoundError:
                continue
            try:
                entries, _ = _load_index(assignment_fd, name)
            except _Fail as failure:
                if hint is not None:
                    return None, (), {failure.code}
                unverifiable = True
                continue
            finally:
                os.close(assignment_fd)
            for entry in entries:
                if entry.identity.attempt_id == attempt_id:
                    return entry, entries, set()
        return None, (), {"attempt_unindexed"} | ({"index_unverifiable"} if unverifiable else set())
    except _Fail as failure:
        return None, (), {failure.code}
    except OSError:
        return None, (), {"journal_path_unsafe"}
    finally:
        os.close(assignments_fd)


def _segment_evidence(data: bytes) -> str | None:
    """The bound evidence-envelope digest named by a segment's final complete line, if any."""
    if not data.endswith(b"\n"):
        return None
    line = _parse(data[:-1].rsplit(b"\n", 1)[-1])
    if not check_structure("journal_line", line) or line["line_kind"] != "terminal":
        return None
    binding = line["body"]["result_binding"]
    return None if binding is None else binding["evidence_envelope_digest"]


def _terminal_evidence(attempts_fd: int, attempt_id: str) -> str | None:
    """An attempt's bound evidence-envelope digest, from its final line only."""
    try:
        attempt_fd = _subdir(attempts_fd, attempt_id)
    except (OSError, _Fail):
        return None
    try:
        names = sorted(name for name in os.listdir(attempt_fd) if _SEGMENT.fullmatch(name))
        if not names:
            return None
        data = _read_file(attempt_fd, names[-1], DEFAULT_LIMITS.read_segment_max_bytes, "journal_oversize")
    except (OSError, _Fail):
        return None
    finally:
        os.close(attempt_fd)
    return _segment_evidence(data)


def _inventory(attempt_fd: int, limits: JournalLimits) -> tuple[dict[int, str], set[str]]:
    segments, diagnostics = {}, set()
    with os.scandir(attempt_fd) as entries:
        for count, item in enumerate(entries):
            if count > limits.per_attempt_line_cap + 1:
                raise _Fail("journal_oversize")
            match = _SEGMENT.fullmatch(item.name)
            if match is not None:
                segments[int(match.group(1))] = item.name
            elif item.name == "lock":
                if not _trusted(os.stat("lock", dir_fd=attempt_fd, follow_symlinks=False), False):
                    diagnostics.add("journal_path_unsafe")
            else:
                diagnostics.add("journal_unexpected_entry")
    return segments, diagnostics


class _AllLines:
    """Retains every line (``read_attempt``)."""

    def __init__(self):
        self.lines: list[bytes] = []
        self.total = 0

    def add(self, raw: bytes, seq: int, kind: str) -> None:
        self.total += 1
        self.lines.append(raw)


class _Window:
    """Retains at most ``max_events`` selectable lines after ``after_seq``; counts the rest.

    ``skipped`` counts lines at or before ``after_seq``. ``lead`` counts later
    lines before the first selected line (all of them when none is selected).
    ``tail`` counts lines after the last selected line. Lines between two
    selected lines are counted in neither.
    """

    def __init__(self, after_seq: int, max_events: int, kinds: frozenset[str]):
        self.after_seq, self.max_events, self.kinds = after_seq, max_events, kinds
        self.total = self.skipped = self.lead = self.tail = 0
        self.events: list[bytes] = []
        self.more = self.found = False

    def add(self, raw: bytes, seq: int, kind: str) -> None:
        self.total += 1
        if seq <= self.after_seq:
            self.skipped += 1
            self.found = self.found or seq == self.after_seq
            return
        selectable = kind in self.kinds
        if selectable and len(self.events) < self.max_events:
            self.events.append(raw)
            self.tail = 0
        elif not self.events:
            self.lead += 1
            self.more = self.more or selectable
        else:
            self.tail += 1
            self.more = self.more or selectable


class _Replay:
    """One bounded pass over an attempt's segments, applying only reader rules."""

    def __init__(self, attempt_id: str, sink):
        self.attempt_id = attempt_id
        self.sink = sink
        self.diagnostics: set[str] = set()
        self.reference = None
        self.expected_seq = 0
        self.state = None
        self.ran = False
        self.terminal = None
        self.total = 0
        #: After an unparseable line, continuity (seq, lifecycle) is unknowable.
        self.broken = False

    def line(self, raw: bytes, *, position: int, segment: int, previous: str | None, last: int | None,
             final_line: bool) -> int | None:
        diagnostics = self.diagnostics
        obj = _parse(raw)
        if obj is None:
            diagnostics.add("journal_torn_line" if final_line else "journal_malformed_line")
            self.broken = True
            return None
        if not check_structure("journal_line", obj) or obj["line_kind"] != obj["body"]["body_kind"]:
            diagnostics.add("journal_malformed_line")
            self.broken = True
            return None
        seq, kind, body = obj["seq"], obj["line_kind"], obj["body"]
        if seq != self.expected_seq and not self.broken:
            diagnostics.add("attempt_overwritten")
        self.expected_seq = seq + 1
        if obj["schema"] != JOURNAL_FAMILY or obj["version"] != "1":
            diagnostics.add("journal_unknown_version")
        if kind == "header":
            if (position != 0 or body["segment_index"] != segment or body["previous_segment_sha256"] != previous
                    or body["previous_last_seq"] != last):
                diagnostics.add("attempt_overwritten")
        elif position == 0:
            diagnostics.add("attempt_overwritten")
        if self.reference is None:
            self.reference = obj
            if obj["attempt"]["attempt_id"] != self.attempt_id:
                diagnostics.add("attempt_provenance_mismatch")
        else:
            if obj["attempt"] != self.reference["attempt"] or obj["units"] != self.reference["units"]:
                diagnostics.add("attempt_provenance_mismatch")
            if obj["writer"] != self.reference["writer"]:
                diagnostics.add("journal_foreign_writer")
        if not _strings_bounded(obj):
            diagnostics.add("raw_output_in_record")
        if kind == "event":
            text = body["message"]["text"]
            if len(text) > _MESSAGE_MAX or not _display_safe(text):
                diagnostics.add("raw_output_in_record")
            for ref in body["refs"]:
                if not _hex(ref["sha256"]):
                    diagnostics.add("raw_output_in_record")
                if ref["locator"] is not None and not _repo_relative(ref["locator"]):
                    diagnostics.add("locator_not_repo_relative")
        if self.terminal is not None:
            diagnostics.add("lifecycle_invalid")
        if kind in ("state", "terminal") and not self.broken:
            self._transition(obj, kind, body)
        self.sink.add(raw, seq, kind)
        return seq

    def _transition(self, obj: dict, kind: str, body: dict) -> None:
        diagnostics, new = self.diagnostics, body["state"]
        if kind == "terminal" and new == "refused" and (self.ran or body["worker_invocations"] > 0):
            diagnostics.add("refused_after_launch")
        elif new not in _NEXT[self.state]:
            diagnostics.add("lifecycle_invalid")
        if kind == "terminal":
            if new == "finished" and body["termination"] is None:
                diagnostics.add("lifecycle_invalid")
            if new == "refused" and body["refusal"] is None:
                diagnostics.add("lifecycle_invalid")
            binding = body["result_binding"]
            attempt = obj["attempt"]
            if binding is not None and (binding["envelope_digest"], binding["run_id"], binding["attempt_id"]) != (
                    attempt["envelope_digest"], attempt["run_id"], attempt["attempt_id"]):
                diagnostics.add("attempt_provenance_mismatch")
            self.terminal = body
        if new in ("running", "cancelling"):
            self.ran = True
        self.state = new


def _terminal_record(body: dict) -> TerminalRecord:
    termination, refusal, binding = body["termination"], body["refusal"], body["result_binding"]
    return TerminalRecord(
        body["state"], body["worker_invocations"],
        None if termination is None else Termination(termination["reason"], termination["signal"], termination["by"]),
        None if refusal is None else TerminalRefusal(refusal["reason"], refusal["constraint"], refusal["tier"]),
        None if binding is None else ResultBinding(binding["envelope_digest"], binding["run_id"], binding["attempt_id"],
                                                   binding["proposal_bytes_digest"],
                                                   binding["evidence_envelope_digest"]))


class _Pass:
    """The outcome of one replay, before it is shaped into a public record."""

    def __init__(self):
        self.diagnostics: set[str] = set()
        self.entry: IndexEntry | None = None
        self.state = self.terminal = self.head = self.prefix = self.evidence = None
        self.verified = False
        #: Only the segment named by ``prefix_at``; never a history-wide list.
        self.segment: tuple[int, int, int, str] | None = None
        self.evidence_known = False


def _bind(root_fd: int, attempt_id: str, hint: str | None, bound):
    """(entry, entries or None, diagnostics). ``bound`` is a caller-held (entry, earlier digests)."""
    if bound is None:
        return _locate(root_fd, attempt_id, hint)
    entry = bound[0]
    if hint is not None and hint != entry.identity.assignment_digest:
        return None, None, {"attempt_unindexed"}
    return entry, None, set()


def _replay(root_fd: int, attempts_fd: int, attempt_fd: int, attempt_id: str, limits: JournalLimits, *,
            sink, bound=None, prefix_at=None) -> _Pass:
    result = _Pass()
    segments, diagnostics = _inventory(attempt_fd, limits)
    result.diagnostics = diagnostics
    if 0 not in segments:
        result.entry, _, located = _bind(root_fd, attempt_id, None, bound)
        diagnostics |= located | {"journal_missing"}
        return result
    indices = sorted(segments)
    if indices != list(range(len(indices))):
        diagnostics.add("attempt_overwritten")
    replay = _Replay(attempt_id, sink)
    previous, last, head = None, None, None
    for order, index in enumerate(indices):
        final = order == len(indices) - 1
        data = _read_file(attempt_fd, segments[index], limits.read_segment_max_bytes, "journal_oversize")
        parts = data.split(b"\n")
        complete, tail = parts[:-1], parts[-1]
        if not data:
            replay.diagnostics.add("journal_torn_line" if final else "attempt_overwritten")
        running = hashlib.sha256() if prefix_at is not None and prefix_at[0] == index else None
        first_seq = last_seq = None
        for position, raw in enumerate(complete):
            replay.total += 1
            seq = replay.line(raw, position=position, segment=index, previous=previous, last=last,
                              final_line=final and not tail and position == len(complete) - 1)
            if seq is not None:
                first_seq = seq if first_seq is None else first_seq
                last_seq = seq
            if running is not None:
                running.update(raw + b"\n")
                if seq is not None and seq == prefix_at[1]:
                    result.prefix = running.hexdigest()
        del parts, complete
        if tail:
            replay.total += 1
            replay.diagnostics.add("journal_torn_line" if final else "journal_malformed_line")
        previous, last = _sha256(data), replay.expected_seq - 1
        if prefix_at is not None and index == prefix_at[0]:
            result.segment = (index, -1 if first_seq is None else first_seq, -1 if last_seq is None else last_seq,
                              previous)
        head = ChainHead(index, previous, last)
        if final:
            result.evidence, result.evidence_known = _segment_evidence(data), True
        del data
        if replay.total > limits.per_attempt_line_cap:
            replay.diagnostics.add("journal_oversize")
            break
    diagnostics |= replay.diagnostics
    hint = None
    if replay.reference is not None:
        hint = replay.reference["attempt"]["assignment_digest"]
    entry, entries, located = _bind(root_fd, attempt_id, hint, bound)
    diagnostics |= located
    result.entry = entry
    if entry is not None and replay.reference is not None:
        if (_identity_json(entry.identity) != replay.reference["attempt"]
                or _units_json(entry.units) != replay.reference["units"]
                or entry.identity.assignment_digest != hint):
            diagnostics.add("attempt_provenance_mismatch")
        if _writer_json(entry.writer) != replay.reference["writer"]:
            diagnostics.add("journal_foreign_writer")
        binding = replay.terminal["result_binding"] if replay.terminal is not None else None
        if binding is not None:
            digest = binding["evidence_envelope_digest"]
            if bound is not None:
                copied = digest in bound[1]
            else:
                earlier = [item.identity.attempt_id for item in entries if item.index_seq < entry.index_seq]
                copied = any(_terminal_evidence(attempts_fd, other) == digest for other in earlier)
            if copied:
                diagnostics.add("attempt_evidence_copied")
    result.verified = not diagnostics and replay.reference is not None
    result.state, result.terminal, result.head = replay.state, replay.terminal, head
    return result


def _pass(root_fd: int, attempt_id: str, limits: JournalLimits, *, sink, bound=None, prefix_at=None) -> _Pass:
    """Open the attempt directory and replay it; failures become closed diagnostics."""
    failed = _Pass()
    try:
        attempts_fd = _subdir(root_fd, "attempts")
    except FileNotFoundError:
        failed.diagnostics = {"journal_missing"}
        return failed
    except _Fail as failure:
        failed.diagnostics = {failure.code}
        return failed
    try:
        try:
            attempt_fd = _subdir(attempts_fd, attempt_id)
        except FileNotFoundError:
            failed.diagnostics = {"journal_missing"}
            return failed
        except _Fail as failure:
            failed.diagnostics = {failure.code}
            return failed
        try:
            result = _replay(root_fd, attempts_fd, attempt_fd, attempt_id, limits, sink=sink, bound=bound,
                             prefix_at=prefix_at)
        except _Fail as failure:
            failed.diagnostics = {failure.code}
            result = failed
        except OSError:
            failed.diagnostics = {"journal_path_unsafe"}
            result = failed
        finally:
            os.close(attempt_fd)
        if bound is not None and not result.evidence_known:
            result.evidence = _terminal_evidence(attempts_fd, attempt_id)
        return result
    finally:
        os.close(attempts_fd)


def read_attempt(root: JournalRoot, attempt_id: str) -> AttemptRead:
    """One bounded, read-only pass; any diagnostic makes the attempt display unknown."""
    if not _valid_id(attempt_id):
        return _unknown(attempt_id, ("identifier_invalid",))
    try:
        root_fd = _root_fd(root)
    except _Fail as failure:
        return _unknown(attempt_id, (failure.code,))
    sink = _AllLines()
    try:
        result = _pass(root_fd, attempt_id, DEFAULT_LIMITS, sink=sink)
    finally:
        os.close(root_fd)
    if not result.verified:
        return _unknown(attempt_id, result.diagnostics, result.entry)
    entry = result.entry
    return AttemptRead(attempt_id, entry.identity, entry.units, entry.writer, tuple(sink.lines), result.state,
                       None if result.terminal is None else _terminal_record(result.terminal), result.head, (),
                       result.state or "unknown")


#: Line kinds a window may select by default: everything except headers.
EVENT_KINDS = frozenset({"event", "state", "terminal"})
WINDOW_EVENTS_MAX = 100


@dataclass(frozen=True, slots=True)
class AttemptWindow:
    """A bounded slice of one attempt, read in one pass without retaining its history."""

    attempt_id: str
    identity: AttemptIdentity | None
    diagnostics: tuple[str, ...]
    state: str | None
    chain_head: ChainHead | None
    total_lines: int
    skipped: int
    lead: int
    events: tuple[bytes, ...]
    tail: int
    more_events: bool
    found_after_seq: bool
    #: (index, first_seq, last_seq, sha256) of the segment named by ``prefix_at``, when requested.
    segment: tuple[int, int, int, str] | None
    prefix_digest: str | None
    evidence_digest: str | None


def _empty_window(attempt_id: str, entry, diagnostics, evidence=None) -> AttemptWindow:
    return AttemptWindow(attempt_id, entry.identity if isinstance(entry, IndexEntry) else None,
                         tuple(sorted(set(diagnostics))), None, None, 0, 0, 0, (), 0, False, False, None, None, evidence)


def read_attempt_window(root: JournalRoot, index: IndexRead, entry: IndexEntry, *, after_seq: int = -1,
                        max_events: int = 0, earlier_evidence=frozenset(), event_kinds=EVENT_KINDS,
                        prefix_at: tuple[int, int] | None = None) -> AttemptWindow:
    """Verify one indexed attempt like ``read_attempt`` while retaining at most ``max_events`` lines.

    ``index`` is the caller's single verified ``read_index`` result and ``entry``
    one of its entries, so the index is not reloaded per attempt.
    ``earlier_evidence`` is a container (only membership is tested) of the
    ``evidence_digest`` values of the entries before ``entry``, so no earlier
    attempt is rescanned. Diagnostics equal
    those of ``read_attempt`` for the same attempt.
    """
    attempt_id = entry.identity.attempt_id if isinstance(entry, IndexEntry) else ""
    if (not isinstance(index, IndexRead) or index.diagnostics or not isinstance(entry, IndexEntry)
            or not 0 <= entry.index_seq < len(index.entries) or index.entries[entry.index_seq] != entry):
        return _empty_window(attempt_id, None, ("index_unverifiable",))
    if (type(after_seq) is not int or after_seq < -1 or type(max_events) is not int or max_events < 0
            or not isinstance(event_kinds, frozenset)
            or not (prefix_at is None or (isinstance(prefix_at, tuple) and len(prefix_at) == 2
                                          and all(type(item) is int for item in prefix_at)))):
        return _empty_window(attempt_id, entry, ("identifier_invalid",))
    if max_events > WINDOW_EVENTS_MAX:
        return _empty_window(attempt_id, entry, ("read_unbounded",))
    try:
        root_fd = _root_fd(root)
    except _Fail as failure:
        return _empty_window(attempt_id, entry, (failure.code,))
    sink = _Window(after_seq, max_events, event_kinds)
    try:
        result = _pass(root_fd, attempt_id, DEFAULT_LIMITS, sink=sink, bound=(entry, earlier_evidence),
                       prefix_at=prefix_at)
    finally:
        os.close(root_fd)
    if not result.verified:
        return _empty_window(attempt_id, entry, result.diagnostics, result.evidence)
    return AttemptWindow(attempt_id, entry.identity, (), result.state, result.head, sink.total, sink.skipped,
                         sink.lead, tuple(sink.events), sink.tail, sink.more, sink.found, result.segment,
                         result.prefix, result.evidence)


__all__ = [
    "JOURNAL_FAMILY", "INDEX_SCHEMA", "HARNESS_ID", "EVENT_PHRASES", "REF_KINDS", "PUBLIC_CODES", "LOCAL_CODES",
    "STRUCTURE", "AttemptIdentity", "Units", "WriterIdentity", "Ref", "Termination", "TerminalRefusal",
    "ResultBinding", "Reservation", "ChainHead", "JournalLimits", "DEFAULT_LIMITS", "JournalRoot",
    "JournalRefused", "IndexEntry", "TerminalRecord", "AttemptRead", "IndexRead", "AttemptWriter",
    "check_structure", "default_journal_root", "open_journal_root", "process_start_identity", "make_ref",
    "reserve_attempt", "open_writer", "read_attempt", "read_index", "resolve_run", "AttemptWindow",
    "EVENT_KINDS", "WINDOW_EVENTS_MAX", "read_attempt_window",
]
