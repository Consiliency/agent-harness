"""The jailed ``sdk`` transport (SEATS CLAUDE SL-3, IF-0-CLAUDE-3), landed unadmitted.

The ``sdk`` transport runs the Claude Agent SDK (pinned ``claude-agent-sdk`` 0.2.167) in a
dedicated, credential-free host worker, never in the board parent, and connects it to the
same jailed CLI the TUI and ``print`` transports run, over a custom transport on a pair of
inherited anonymous pipes. The worker contract is ``plans/seats-claude-sdk-worker-contract.md``.

This module is the parent's half. It never imports the SDK or the adapter, at load time or
later; the worker payload under ``data/claude_sdk/worker/`` runs only in the worker.

* :func:`build_sdk_cli_argv` -- the one function that supplies the CLI's actual flags: the
  jailed TUI command with the frozen launch delta of ``launch-v1.json``
  (:func:`sdk_cli_delta`). The SDK's ``cli_path`` and CLI options are inert.
* :class:`SDKBridge` -- the parent stream gate and the outbound allowlist. Every complete
  CLI stdout line goes through ``print``'s :class:`~.claude_seat_print.StreamAdmission`, is
  parsed once more under the strict frame rules for forwarding, has every decoded key and
  value scanned, and must be in the frozen inbound vocabulary before the parsed object (and
  only it) crosses to the worker. Every worker frame is checked against a stateful
  allowlist; the parent writes CLI-bound bytes from its own templates, never the worker's.
  Final text comes only from ``StreamAdmission.result_text``.
* :func:`seal` / :func:`preflight` -- the hashed worker install: sealed into a read-only
  snapshot (closure, interpreter, standard library, loader and runtime libraries), verified
  once per snapshot and re-checked by signature before every worker, before the leg's
  credential is resolved.
* :func:`worker_filter_program` -- the worker's in-process syscall filter, which the
  launcher delivers and the bootstrap installs before any non-stdlib import.
* :data:`RECEIPT_FIELDS` / :func:`validate_receipt` -- the closed ``claude-sdk-boundary.v1``
  receipt schema and its proof-input binding (:func:`proof_inputs_sha256`).

``ADMITTED`` is ``False``: the transport seam refuses ``sdk`` before importing this module.
Activation is GL-2 alone, after the OD-3a section, the boundary proof and the owner's
enforcement prerequisites.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import errno
import hashlib
import json
import os
import platform
import pwd
import re
import secrets
import shutil
import stat
import struct
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from . import claude_seat_transport as _ct
from .claude_seat_transport import RecordCitation, TransportRefused

ADMITTED = False
#: The OD-3a section this transport will cite at GL-2. Unset until G1 ratifies it.
ACTIVATION: RecordCitation | None = None
TRANSPORT = "sdk"
SDK_PACKAGE = "claude-agent-sdk"
SDK_VERSION = "0.2.167"
MARKDOWN_IT_VERSION = "4.2.0"
CONTRACT = "plans/seats-claude-sdk-worker-contract.md"

DEPENDENCY_UNAVAILABLE = "claude_sdk_dependency_unavailable"
PROVENANCE_REFUSED = "claude_sdk_provenance_refused"
WORKER_UNAVAILABLE = "claude_sdk_worker_unavailable"
CONTRACT_VIOLATION = "claude_sdk_worker_contract_violation"
STREAM_UNSAFE = "claude_seat_stream_unsafe"
RESULT_UNPROVEN = "claude_seat_result_unproven"
TOKEN_IN_OUTPUT = "claude_seat_token_in_output"

#: The worker's closed failure codes, mapped to this transport's typed codes.
WORKER_FAILURES: Mapping[str, str] = MappingProxyType({
    "worker_prerequisite_missing": WORKER_UNAVAILABLE,
    "filter_install_failed": WORKER_UNAVAILABLE,
    "closure_missing": DEPENDENCY_UNAVAILABLE,
    "dependency_missing": DEPENDENCY_UNAVAILABLE,
    "closure_unverified": PROVENANCE_REFUSED,
    "preloaded_origin": PROVENANCE_REFUSED,
    "timer_invalid": STREAM_UNSAFE,
    "protocol_violation": CONTRACT_VIOLATION,
    "session_failed": RESULT_UNPROVEN,
})

# --------------------------------------------------------------------------------------
# Packaged data, read only through importlib.resources on the installed package.
# --------------------------------------------------------------------------------------

LAUNCH_FIXTURE = "launch-v1.json"
EXPORT = "requirements-v1.txt"
CLOSURE_MANIFEST = "closure-linux-x86_64-cp314-v1.json"
RECEIPT = "receipt-v1.json"
WORKER_PAYLOAD = ("claude_sdk_bootstrap.py", "claude_sdk_worker.py", "claude_sdk_adapter.py")
_DATA_CAP_BYTES = 16 << 20


class SDKRefused(TransportRefused):
    """A refusal of this transport, always one of its typed codes."""


def _refuse(code: str) -> SDKRefused:
    return SDKRefused(code)


def data_dir() -> Path:
    """``phase_loop_runtime/data/claude_sdk`` of the package this module was loaded from.
    The resource root must be this module's own directory: no cwd, subject-tree or source
    checkout copy can stand in for it."""
    from importlib import resources

    here = Path(__file__).resolve(strict=True).parent
    try:
        root = Path(str(resources.files(__package__))).resolve(strict=True)
    except (OSError, TypeError, ValueError, ModuleNotFoundError):
        raise _refuse(PROVENANCE_REFUSED) from None
    if root != here:
        raise _refuse(PROVENANCE_REFUSED)
    data = root / "data" / "claude_sdk"
    for part in (root / "data", data, data / "worker"):
        try:
            info = part.lstat()
        except OSError:
            raise _refuse(DEPENDENCY_UNAVAILABLE) from None
        if not stat.S_ISDIR(info.st_mode):
            raise _refuse(PROVENANCE_REFUSED)
    return data


def read_packaged(name: str, *, cap: int = _DATA_CAP_BYTES) -> bytes:
    """One packaged file's bytes: a regular, non-symlinked file under :func:`data_dir`."""
    parts = name.split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise _refuse(PROVENANCE_REFUSED)
    path = data_dir().joinpath(*parts)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        raise _refuse(DEPENDENCY_UNAVAILABLE) from None
    except OSError:
        raise _refuse(PROVENANCE_REFUSED) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
            raise _refuse(PROVENANCE_REFUSED)
        chunks, total = [], 0
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise _refuse(PROVENANCE_REFUSED)
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    """The frozen JSON encoding: ASCII, sorted keys, no whitespace, no NaN."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii")


_FIXTURE_CACHE: dict[str, Mapping[str, object]] = {}


def sdk_cli_delta() -> Mapping[str, object]:
    """``SDK_CLI_DELTA``: the complete versioned launch fixture (``launch-v1.json``), as
    packaged. Its ``cli`` section is the delta :func:`build_sdk_cli_argv` applies."""
    raw = read_packaged(LAUNCH_FIXTURE)
    digest = sha256_hex(raw)
    cached = _FIXTURE_CACHE.get(digest)
    if cached is not None:
        return cached
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, ValueError, _StrictError):
        raise _refuse(PROVENANCE_REFUSED) from None
    if (not isinstance(value, dict) or value.get("schema") != "claude-sdk-launch.v1"
            or value.get("sdk", {}).get("version") != SDK_VERSION):
        raise _refuse(PROVENANCE_REFUSED)
    frozen = MappingProxyType(value)
    _FIXTURE_CACHE.clear()
    _FIXTURE_CACHE[digest] = frozen
    return frozen


# --------------------------------------------------------------------------------------
# The CLI argv.
# --------------------------------------------------------------------------------------

def _pi():
    from . import panel_invoker

    return panel_invoker


def apply_cli_delta(tui_command: Sequence[str], delta: Mapping[str, object]) -> list[str]:
    """The jailed TUI command with the fixture's delta: its tokens inserted after argv0,
    the listed value flags in ``--flag=value`` form, every refused flag absent and every
    required flag present with its frozen value. Values are never read as flags."""
    command = list(tui_command)
    if not command:
        raise ValueError("an empty jailed command")
    refused = set(delta["refuse"])
    equals = set(delta["equals_form"])
    takes_value = set(delta["value_flags"])
    out = [command[0], *delta["insert_after_argv0"]]
    rest = command[1:]
    index = 0
    while index < len(rest):
        token = rest[index]
        flag = token.split("=", 1)[0]
        if flag in refused or token in delta["insert_after_argv0"]:
            raise ValueError(f"the jailed sdk command never carries {flag}")
        if token in takes_value:
            if index + 1 >= len(rest):
                raise ValueError(f"{token} has no value")
            value = rest[index + 1]
            out.extend([f"{token}={value}"] if token in equals else [token, value])
            index += 2
            continue
        if not token.startswith("--"):
            raise ValueError("a jailed command token is neither a flag nor a flag's value")
        out.append(token)
        index += 1
    for flag, value in dict(delta["require"]).items():
        if value is None:
            if out.count(flag) != 1:
                raise ValueError(f"the jailed sdk command lacks {flag}")
        elif flag in equals:
            if out.count(f"{flag}={value}") != 1:
                raise ValueError(f"the jailed sdk command lacks {flag}={value}")
        else:
            positions = [i for i, item in enumerate(out) if item == flag]
            if len(positions) != 1 or positions[0] + 1 >= len(out) \
                    or out[positions[0] + 1] != value:
                raise ValueError(f"the jailed sdk command lacks {flag} {value}")
    return out


def build_sdk_cli_argv(jail: object, *, model: str | None, effort: str | None,
                       session_id: str, env: Mapping[str, str] | None = None,
                       session_name: str | None = None) -> list[str]:
    """The jailed CLI argv of the ``sdk`` transport: the jailed TUI command
    (``panel_invoker._broker_claude_tui_command`` with the seat jail) and the frozen
    :func:`sdk_cli_delta`. Nothing else supplies CLI flags."""
    command = _pi()._broker_claude_tui_command(
        model=model, effort=effort, session_id=session_id, sandboxed=jail, env=env,
        session_name=session_name)
    return apply_cli_delta(command, sdk_cli_delta()["cli"]["delta"])


def cli_env(jail: object) -> dict[str, str]:
    """The CLI's environment: the jail's own, exactly. The SDK's stock additions
    (entrypoint, SDK version, session-state and trace variables) are never added."""
    return dict(getattr(jail, "env"))


# --------------------------------------------------------------------------------------
# The worker's syscall filter (x86_64 only: the qualified host class).
# --------------------------------------------------------------------------------------

AUDIT_ARCH_X86_64 = 0xC000003E
_RET_KILL_PROCESS = 0x80000000
_RET_ALLOW = 0x7FFF0000
_RET_ERRNO = 0x00050000
CLONE_THREAD = 0x00010000
AF_UNIX = 1
#: x86_64 syscall numbers of the denied operations: process creation and exec, network
#: endpoints, namespace and privilege changes, tracing and peer memory, key management,
#: kernel loading, BPF, perf, userfaultfd, io_uring and the new mount API.
X86_64_DENIED: Mapping[str, int] = MappingProxyType({
    "execve": 59, "execveat": 322, "fork": 57, "vfork": 58,
    "socket": 41, "connect": 42, "accept": 43, "bind": 49, "listen": 50, "accept4": 288,
    "unshare": 272, "setns": 308, "mount": 165, "umount2": 166, "pivot_root": 155,
    "chroot": 161, "ptrace": 101, "process_vm_readv": 310, "process_vm_writev": 311,
    "setuid": 105, "setgid": 106, "setreuid": 113, "setregid": 114, "setgroups": 116,
    "setresuid": 117, "setresgid": 119, "setfsuid": 122, "setfsgid": 123, "capset": 126,
    "keyctl": 250, "add_key": 248, "request_key": 249, "bpf": 321, "perf_event_open": 298,
    "userfaultfd": 323, "kexec_load": 246, "kexec_file_load": 320, "init_module": 175,
    "finit_module": 313, "delete_module": 176, "open_by_handle_at": 304,
    "name_to_handle_at": 303, "io_uring_setup": 425, "io_uring_enter": 426,
    "io_uring_register": 427, "open_tree": 428, "move_mount": 429, "fsopen": 430,
    "fsconfig": 431, "fsmount": 432, "fspick": 433, "mount_setattr": 442,
    "pidfd_open": 434, "pidfd_send_signal": 424, "pidfd_getfd": 438,
})
X86_64_CLONE = 56
X86_64_CLONE3 = 435
X86_64_SOCKETPAIR = 53


def _insn(code: int, jt: int, jf: int, k: int) -> bytes:
    return struct.pack("<HBBI", code, jt, jf, k)


def worker_filter_program(machine: str | None = None) -> bytes:
    """The worker's seccomp program. Threads (``clone`` with ``CLONE_THREAD``) and the
    event loop's ``AF_UNIX`` ``socketpair`` are the only process and socket operations
    left; ``clone3`` reports ``ENOSYS`` so the C library falls back to ``clone``. Any other
    architecture, or an x32 call, kills the process."""
    machine = platform.machine() if machine is None else machine
    if machine != "x86_64":
        raise _refuse(WORKER_UNAVAILABLE)
    ld, jeq, jge, jset, ret = 0x20, 0x15, 0x35, 0x45, 0x06
    program = [
        _insn(ld, 0, 0, 4), _insn(jeq, 1, 0, AUDIT_ARCH_X86_64), _insn(ret, 0, 0, _RET_KILL_PROCESS),
        _insn(ld, 0, 0, 0), _insn(jge, 0, 1, 0x40000000), _insn(ret, 0, 0, _RET_KILL_PROCESS),
        # clone: a thread, or nothing.
        _insn(jeq, 0, 4, X86_64_CLONE), _insn(ld, 0, 0, 16), _insn(jset, 0, 1, CLONE_THREAD),
        _insn(ret, 0, 0, _RET_ALLOW), _insn(ret, 0, 0, _RET_ERRNO | errno.EPERM),
        # socketpair: AF_UNIX only.
        _insn(jeq, 0, 4, X86_64_SOCKETPAIR), _insn(ld, 0, 0, 16), _insn(jeq, 0, 1, AF_UNIX),
        _insn(ret, 0, 0, _RET_ALLOW), _insn(ret, 0, 0, _RET_ERRNO | errno.EPERM),
        _insn(jeq, 0, 1, X86_64_CLONE3), _insn(ret, 0, 0, _RET_ERRNO | errno.ENOSYS),
    ]
    for number in sorted(set(X86_64_DENIED.values())):
        program.extend([_insn(jeq, 0, 1, number), _insn(ret, 0, 0, _RET_ERRNO | errno.EPERM)])
    program.append(_insn(ret, 0, 0, _RET_ALLOW))
    return b"".join(program)


# --------------------------------------------------------------------------------------
# Strict frames, shared by both directions.
# --------------------------------------------------------------------------------------

NESTING_BOUND = 64
FRAME_CAP_BYTES = 16 << 20
HELLO_CAP_BYTES = 8 << 20
WORKER_STDERR_CAP_BYTES = 64 << 10


class _StrictError(ValueError):
    pass


def _unique_pairs(pairs):
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise _StrictError("duplicate key")
    return dict(pairs)


def parse_strict(raw: bytes) -> dict:
    """One frame: strict UTF-8, nesting within :data:`NESTING_BOUND`, no duplicate key in
    any object, a JSON object. Anything else raises ``ValueError``."""
    from .claude_seat_print import _nesting

    if _nesting(raw, NESTING_BOUND) > NESTING_BOUND:
        raise _StrictError("nesting")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, RecursionError) as exc:
        raise _StrictError("encoding") from exc
    if not isinstance(value, dict):
        raise _StrictError("not an object")
    return value


def decoded_strings(value: object):
    """Every decoded key and string value in a parsed frame, JSON escapes resolved."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for key, child in item.items():
                yield key
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)


def _render(template: object, values: Mapping[str, str]) -> object:
    """``template`` with each whole-string placeholder (``<NAME>``) replaced."""
    if isinstance(template, str):
        return values.get(template, template)
    if isinstance(template, list):
        return [_render(item, values) for item in template]
    if isinstance(template, dict):
        return {key: _render(item, values) for key, item in template.items()}
    return template


# --------------------------------------------------------------------------------------
# The parent bridge: the stream gate and the outbound allowlist.
# --------------------------------------------------------------------------------------

#: Bridge actions for the duplex driver.
TO_WORKER = "worker"
TO_CLI = "cli_stdin"
CLOSE_CLI_STDIN = "close_cli_stdin"
STOP = "stop"


class SDKBridge:
    """One leg's parent-side protocol state. The driver feeds it bytes and performs the
    actions it returns: ``(TO_WORKER, bytes)``, ``(TO_CLI, bytes)``, ``(CLOSE_CLI_STDIN,)``
    and ``(STOP, code)``, after which both process trees are terminated. The bridge holds
    no process and no descriptor; nothing a worker sends can launch, credential or admit."""

    def __init__(self, *, token: bytes, session_id: str, prompt: str,
                 fixture: Mapping[str, object] | None = None, nonce: str | None = None,
                 stream_cap: int | None = None, line_cap: int | None = None) -> None:
        from . import seat_jail
        from .claude_seat_print import StreamAdmission

        self._fixture = fixture if fixture is not None else sdk_cli_delta()
        protocol = self._fixture["protocol"]
        self._protocol = protocol
        self._token = token
        self._forms = seat_jail.secret_encodings(token)
        self.admission = StreamAdmission(token=token, session_id=session_id,
                                         stream_cap=stream_cap, line_cap=line_cap)
        self.session_id = session_id
        self.prompt = prompt
        self.nonce = nonce if nonce is not None else secrets.token_hex(32)
        if not re.fullmatch(r"[0-9a-f]{64}", self.nonce):
            raise ValueError("a launch nonce is 64 lowercase hex digits")
        self._request_id = re.compile(protocol["request_id_pattern"])
        self._line_cap = FRAME_CAP_BYTES if line_cap is None else line_cap
        self.state = "new"
        self._sent = 0
        self._received = 0
        self._worker_buffer = bytearray()
        self._cli_buffer = bytearray()
        self._outstanding: dict[str, str] = {}
        self.violation: str | None = None
        self.cancelled = False
        self.stdin_closed = False
        self.cli_eof = False
        self.worker_outcome: str | None = None
        self.worker_failure: str | None = None
        self.forwarded = 0

    # -- helpers --------------------------------------------------------------------

    def _stop(self, code: str) -> list[tuple]:
        if self.violation is None or code == TOKEN_IN_OUTPUT:
            self.violation = code
        return [(STOP, self.violation)]

    def _frame(self, kind: str, body: object) -> bytes:
        data = canonical({"launch": self.nonce, "seq": self._sent, "kind": kind,
                          "body": body}) + b"\n"
        self._sent += 1
        return data

    def _scan(self, value: object) -> bool:
        return any(any(form in text.encode("utf-8", errors="surrogatepass")
                       for form in self._forms) for text in decoded_strings(value))

    def _template(self, name: str, values: Mapping[str, str]) -> object:
        return _render(self._protocol["outbound"][name], values)

    # -- the worker ---------------------------------------------------------------------

    def hello(self, *, filter_program: bytes, roots: Sequence[str],
              inventory: Mapping[str, str], excluded: Sequence[str],
              options: Mapping[str, object]) -> bytes:
        """The bounded readiness frame: the nonce, the filter, the verified closure, the
        frozen timers and options, and the sealed prompt -- and no credential."""
        if self.state != "new":
            raise ValueError("one hello per launch")
        body = {
            "filter": base64.b64encode(filter_program).decode("ascii"),
            "roots": list(roots), "inventory": dict(inventory), "excluded": list(excluded),
            "timers": dict(self._fixture["worker"]["timers"]), "options": dict(options),
            "prompt": self.prompt,
        }
        if self._scan(body):
            raise _refuse(TOKEN_IN_OUTPUT)
        data = self._frame("hello", body)
        if len(data) > HELLO_CAP_BYTES:
            raise _refuse(WORKER_UNAVAILABLE)
        self.state = "hello"
        return data

    def start(self) -> list[tuple]:
        """Called once the jailed CLI is running: only now may the SDK connect."""
        if self.violation is not None:
            return [(STOP, self.violation)]
        if self.state != "ready":
            return self._stop(CONTRACT_VIOLATION)
        self.state = "started"
        return [(TO_WORKER, self._frame("start", {}))]

    def cancel(self) -> list[tuple]:
        self.cancelled = True
        if self.state in ("new", "hello") or self.violation is not None:
            return []
        return [(TO_WORKER, self._frame("cancel", {}))]

    def worker_bytes(self, chunk: bytes) -> list[tuple]:
        if self.violation is not None:
            return [(STOP, self.violation)]
        self._worker_buffer.extend(chunk)
        actions: list[tuple] = []
        while True:
            end = self._worker_buffer.find(b"\n")
            if end < 0:
                if len(self._worker_buffer) > FRAME_CAP_BYTES:
                    return self._stop(CONTRACT_VIOLATION)
                return actions
            line = bytes(self._worker_buffer[:end])
            del self._worker_buffer[:end + 1]
            actions.extend(self._worker_frame(line))
            if self.violation is not None:
                return actions

    def worker_eof(self) -> list[tuple]:
        if self.violation is None and self._worker_buffer:
            return self._stop(CONTRACT_VIOLATION)
        return []

    def _worker_frame(self, line: bytes) -> list[tuple]:
        try:
            frame = parse_strict(line)
        except ValueError:
            return self._stop(CONTRACT_VIOLATION)
        if (set(frame) != {"launch", "seq", "kind", "body"} or frame["launch"] != self.nonce
                or type(frame["seq"]) is not int or frame["seq"] != self._received
                or not isinstance(frame["kind"], str)):
            return self._stop(CONTRACT_VIOLATION)
        self._received += 1
        kind, body = frame["kind"], frame["body"]
        if kind == "failed":
            code = body.get("code") if isinstance(body, dict) and set(body) == {"code"} else None
            self.worker_failure = code if code in WORKER_FAILURES else "protocol_violation"
            return self._stop(WORKER_FAILURES[self.worker_failure])
        if kind == "ready":
            if self.state != "hello" or body != {}:
                return self._stop(CONTRACT_VIOLATION)
            self.state = "ready"
            return []
        if kind == "done":
            if (self.state in ("new", "hello", "ready") or not isinstance(body, dict)
                    or set(body) != {"outcome"} or body["outcome"] not in ("result", "no_result")
                    or self.worker_outcome is not None):
                return self._stop(CONTRACT_VIOLATION)
            self.worker_outcome = body["outcome"]
            return []
        if kind == "end_input":
            if self.state != "user_sent" or body != {}:
                return self._stop(CONTRACT_VIOLATION)
            self.state = "ended"
            self.stdin_closed = True
            return [(CLOSE_CLI_STDIN,)]
        if kind != "cli" or not isinstance(body, dict):
            return self._stop(CONTRACT_VIOLATION)
        return self._outbound(body)

    def _outbound(self, body: dict) -> list[tuple]:
        """The stateful allowlist: one initialize with the frozen empty fields, then one
        sealed-prompt user envelope whose canonical digest is the parent's template, then
        end-input; an interrupt only after parent cancellation."""
        request_id = body.get("request_id")
        if self.state == "started":
            if not (isinstance(request_id, str) and self._request_id.fullmatch(request_id)):
                return self._stop(CONTRACT_VIOLATION)
            expected = self._template("initialize", {"<REQUEST_ID>": request_id})
            if canonical(body) != canonical(expected):
                return self._stop(CONTRACT_VIOLATION)
            self._outstanding[request_id] = "initialize"
            self.state = "init_sent"
            return [(TO_CLI, canonical(expected) + b"\n")]
        if self.state == "init_answered":
            expected = self._template("user", {"<PROMPT>": self.prompt})
            if sha256_hex(canonical(body)) != sha256_hex(canonical(expected)):
                return self._stop(CONTRACT_VIOLATION)
            self.state = "user_sent"
            return [(TO_CLI, canonical(expected) + b"\n")]
        if self.cancelled and isinstance(request_id, str) \
                and self._request_id.fullmatch(request_id) \
                and request_id not in self._outstanding:
            expected = self._template("interrupt", {"<REQUEST_ID>": request_id})
            if canonical(body) == canonical(expected):
                if self.stdin_closed:
                    return []
                self._outstanding[request_id] = "interrupt"
                return [(TO_CLI, canonical(expected) + b"\n")]
        return self._stop(CONTRACT_VIOLATION)

    # -- the CLI --------------------------------------------------------------------

    def cli_stderr(self, chunk: bytes) -> list[tuple]:
        """Bounded and scanned; never sent to the SDK."""
        if self.admission.feed_stderr(chunk):
            return self._stop(self.admission.violation or STREAM_UNSAFE)
        return []

    def cli_stdout(self, chunk: bytes) -> list[tuple]:
        if self.violation is not None:
            return [(STOP, self.violation)]
        self._cli_buffer.extend(chunk)
        actions: list[tuple] = []
        while True:
            end = self._cli_buffer.find(b"\n")
            if end < 0:
                if len(self._cli_buffer) > self._line_cap:
                    actions.extend(self._stop(STREAM_UNSAFE))
                return actions
            line = bytes(self._cli_buffer[:end + 1])
            del self._cli_buffer[:end + 1]
            actions.extend(self._cli_line(line))
            if self.violation is not None:
                return actions

    def cli_stdout_eof(self) -> list[tuple]:
        """Raw EOF on the CLI's stdout: a final unterminated line is read, then the worker
        is told the stream ended."""
        actions: list[tuple] = []
        if self.violation is None and self._cli_buffer:
            line = bytes(self._cli_buffer)
            self._cli_buffer.clear()
            actions.extend(self._cli_line(line))
        self.admission.finish()
        self.cli_eof = True
        if self.violation is None and self.admission.violation is not None:
            actions.extend(self._stop(self.admission.violation))
        if self.violation is None and self.state not in ("new", "hello", "ready"):
            actions.append((TO_WORKER, self._frame("eof", {})))
        return actions

    def _cli_line(self, line: bytes) -> list[tuple]:
        # 1. print's raw admission: the token in any encoding, caps, init and result.
        if self.admission.feed(line):
            return self._stop(self.admission.violation or STREAM_UNSAFE)
        raw = line.rstrip(b"\n")
        if not raw.strip() or not raw.lstrip().startswith(b"{"):
            return []  # not a frame: it reaches neither admission nor the SDK
        # 2. one strict parse for forwarding; 3. every decoded key and value scanned.
        try:
            frame = parse_strict(raw.strip())
        except ValueError:
            return self._stop(CONTRACT_VIOLATION)
        if self._scan(frame):
            return self._stop(TOKEN_IN_OUTPUT)
        # 4. the frozen inbound vocabulary.
        kind = frame.get("type")
        if kind in self._protocol["inbound"]["refused"]:
            return self._stop(CONTRACT_VIOLATION)
        if kind == "control_response":
            response = frame.get("response")
            request_id = response.get("request_id") if isinstance(response, dict) else None
            if (set(frame) != {"type", "response"} or not isinstance(request_id, str)
                    or request_id not in self._outstanding
                    or response.get("subtype") not in ("success", "error")):
                return self._stop(CONTRACT_VIOLATION)
            if self._outstanding.pop(request_id) == "initialize":
                if self.state != "init_sent" or response.get("subtype") != "success":
                    return self._stop(CONTRACT_VIOLATION)
                self.state = "init_answered"
        elif kind not in self._protocol["inbound"]["forward"]:
            return self._stop(CONTRACT_VIOLATION)
        if self.state in ("new", "hello", "ready"):
            return self._stop(CONTRACT_VIOLATION)
        self.forwarded += 1
        return [(TO_WORKER, self._frame("cli", frame))]

    # -- the outcome ----------------------------------------------------------------

    def outcome(self, returncode: int) -> tuple[str, str]:
        """``("admitted", text)`` only for one successful conforming result for this session,
        with raw EOF, the full outbound sequence and exit zero; else ``("refused", code)``.
        The worker's own view of the session confers nothing."""
        if not self.cli_eof:
            self.cli_stdout_eof()
        if self.violation is not None:
            return "refused", self.violation
        if self.admission.violation is not None:
            return "refused", self.admission.violation
        if (self.state != "ended" or not self.stdin_closed or self._outstanding
                or not self.admission.admitted(int(returncode))):
            return "refused", RESULT_UNPROVEN
        text = self.admission.result_text or ""
        if any(form in text.encode("utf-8", errors="surrogatepass") for form in self._forms):
            return "refused", TOKEN_IN_OUTPUT
        return "admitted", text


# --------------------------------------------------------------------------------------
# The hashed worker install: closure manifest, seal, registration and verification.
# --------------------------------------------------------------------------------------

REGISTRATION_SCHEMA = "claude-sdk-worker-registration.v1"
SNAPSHOT_SCHEMA = "claude-sdk-worker-snapshot.v1"
CLOSURE_SCHEMA = "claude-sdk-closure.v1"
HOST_CLASS = "linux-x86_64-cp314"
#: Installer metadata allowed beside a distribution without a digest.
INSTALLER_METADATA = frozenset({"INSTALLER", "RECORD", "REQUESTED", "direct_url.json",
                                "uv_cache.json"})
#: Files a venv adds to its site directory, removed when sealing.
VENV_ARTIFACTS = frozenset({"_virtualenv.pth", "_virtualenv.py"})
#: Standard-library entries never copied into a snapshot.
STDLIB_EXCLUDED = frozenset({"__pycache__", "site-packages", "dist-packages", "test",
                             "idlelib", "turtledemo", "ensurepip"})
_LIBRARY_DIRS = ("/lib/x86_64-linux-gnu", "/usr/lib/x86_64-linux-gnu", "/lib64", "/usr/lib64",
                 "/lib", "/usr/lib")
_SIGNATURE_CACHE: dict[str, str] = {}


def state_dir() -> Path:
    """The operator's private state for the worker install, from the password database
    (never from the environment)."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "state" / "agent-harness" \
        / "claude-sdk-worker"


def registration_path(directory: Path | None = None) -> Path:
    return (directory or state_dir()) / "registration.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def closure_manifest(raw: bytes | None = None) -> dict:
    """The packaged per-file closure manifest (or ``raw``), parsed and shape-checked. Each
    package lists its files as sorted ``[installed path, sha256]`` pairs."""
    raw = read_packaged(CLOSURE_MANIFEST) if raw is None else raw
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, ValueError):
        raise _refuse(PROVENANCE_REFUSED) from None
    if (not isinstance(value, dict) or value.get("schema") != CLOSURE_SCHEMA
            or not isinstance(value.get("packages"), list)
            or not isinstance(value.get("excluded"), list)):
        raise _refuse(PROVENANCE_REFUSED)
    files: dict[str, str] = {}
    for package in value["packages"]:
        rows = package.get("files")
        if not isinstance(rows, list) or not all(
                isinstance(row, list) and len(row) == 2 and all(isinstance(v, str) for v in row)
                for row in rows):
            raise _refuse(PROVENANCE_REFUSED)
        for rel, digest in rows:
            name = rel.rsplit("/", 1)[-1]
            if (rel in files or rel.startswith("/") or ".." in rel.split("/")
                    or name.endswith((".pyc", ".pyo", ".pth")) or "__pycache__" in rel.split("/")
                    or not re.fullmatch(r"[0-9a-f]{64}", str(digest))):
                raise _refuse(PROVENANCE_REFUSED)
            files[rel] = digest
    for rel in value["excluded"]:
        if rel not in files:
            raise _refuse(PROVENANCE_REFUSED)
    value["_files"] = files
    return value


def manifest_from_wheels(wheels: Sequence[Path], export: bytes) -> dict:
    """The closure manifest generated offline from hash-verified wheels: each wheel's
    sha256 must be one the frozen export pins for its distribution. Installed paths are the
    wheel's own (``*.data/purelib`` and ``platlib`` mapped to the site root); ``RECORD``
    is installer metadata; scripts and headers are not part of the closure."""
    import zipfile

    pins = export_pins(export)
    packages = []
    for wheel in sorted(wheels, key=lambda p: p.name):
        digest = file_sha256(wheel)
        name = re.sub(r"[-_.]+", "-", wheel.name.split("-", 1)[0]).lower()
        pinned = pins.get(name)
        if pinned is None or digest not in pinned["hashes"]:
            raise _refuse(PROVENANCE_REFUSED)
        files = {}
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                rel = info.filename
                parts = rel.split("/")
                if parts[0].endswith(".data"):
                    if len(parts) < 3 or parts[1] not in ("purelib", "platlib"):
                        continue
                    rel = "/".join(parts[2:])
                if parts[0].endswith(".dist-info") and parts[-1] == "RECORD":
                    continue
                files[rel] = hashlib.sha256(archive.read(info)).hexdigest()
        packages.append({"name": name, "version": pinned["version"], "wheel": wheel.name,
                         "wheel_sha256": digest,
                         "files": [[rel, files[rel]] for rel in sorted(files)]})
    bundled = [rel for package in packages for rel, _digest in package["files"]
               if rel == "claude_agent_sdk/_bundled/claude"]
    return {"schema": CLOSURE_SCHEMA, "host_class": HOST_CLASS,
            "export_sha256": sha256_hex(export), "packages": packages, "excluded": bundled}


def export_pins(export: bytes) -> dict[str, dict]:
    """``{distribution: {"version", "hashes"}}`` from the frozen hashed export."""
    pins: dict[str, dict] = {}
    current = None
    for line in export.decode("utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", stripped)
        if match:
            current = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            pins[current] = {"version": match.group(2), "hashes": set()}
            continue
        hashed = re.match(r"^--hash=sha256:([0-9a-f]{64})", stripped)
        if hashed and current is not None:
            pins[current]["hashes"].add(hashed.group(1))
    return pins


def _site_dir(venv: Path, version: str) -> Path:
    major_minor = ".".join(version.split(".")[:2])
    return venv / "lib" / f"python{major_minor}" / "site-packages"


def _pyvenv(venv: Path) -> dict[str, str]:
    path = venv / "pyvenv.cfg"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise _refuse(PROVENANCE_REFUSED)
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    if not values.get("home") or not re.fullmatch(r"3\.\d+\.\d+", values.get("version_info", "")):
        raise _refuse(PROVENANCE_REFUSED)
    return values


def _elf_needed(path: Path) -> tuple[str | None, list[str], list[str]]:
    """``(interpreter, needed, runpath)`` of one ELF64 little-endian file, read without
    executing it."""
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        return None, [], []
    phoff, = struct.unpack_from("<Q", data, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    interp = None
    dynamic = None
    loads = []
    for index in range(phnum):
        p_type, _flags, p_offset, p_vaddr, _paddr, p_filesz = struct.unpack_from(
            "<IIQQQQ", data, phoff + index * phentsize)
        if p_type == 3:
            interp = data[p_offset:p_offset + p_filesz].rstrip(b"\0").decode()
        elif p_type == 2:
            dynamic = (p_offset, p_filesz)
        elif p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz))
    if dynamic is None:
        return interp, [], []

    def to_offset(address: int) -> int:
        for vaddr, offset, size in loads:
            if vaddr <= address < vaddr + size:
                return offset + address - vaddr
        raise ValueError("unmapped address")

    entries = []
    for at in range(dynamic[0], dynamic[0] + dynamic[1], 16):
        tag, value = struct.unpack_from("<qQ", data, at)
        if tag == 0:
            break
        entries.append((tag, value))
    strtab = next((to_offset(v) for t, v in entries if t == 5), None)
    if strtab is None:
        return interp, [], []

    def string(offset: int) -> str:
        end = data.index(b"\0", strtab + offset)
        return data[strtab + offset:end].decode()

    needed = [string(v) for t, v in entries if t == 1]
    runpath = [part for t, v in entries if t in (15, 29) for part in string(v).split(":") if part]
    return interp, needed, runpath


def runtime_files(interpreter: Path, prefix: Path, version: str,
                  closure_root: Path) -> list[Path]:
    """The interpreter, its standard library (no bytecode, site or test trees), the ELF
    loader and every shared library the interpreter, its extension modules and the
    closure's extension modules need, resolved without executing anything."""
    major_minor = ".".join(version.split(".")[:2])
    stdlib = prefix / "lib" / f"python{major_minor}"
    if not (stdlib / "os.py").is_file():
        raise _refuse(DEPENDENCY_UNAVAILABLE)
    files: list[Path] = [interpreter]
    for directory, dirnames, filenames in os.walk(stdlib):
        dirnames[:] = sorted(d for d in dirnames if d not in STDLIB_EXCLUDED)
        files.extend(Path(directory) / name for name in sorted(filenames)
                     if not name.endswith((".pyc", ".pyo")))
    elf = [interpreter, *(p for p in files if p.suffix == ".so"),
           *sorted(closure_root.rglob("*.so")), *sorted(closure_root.rglob("*.so.*"))]
    seen: set[str] = set()
    pending = list(elf)
    libraries: list[Path] = []
    while pending:
        current = pending.pop()
        interp, needed, runpath = _elf_needed(current)
        if interp and interp not in seen:
            seen.add(interp)
            libraries.append(Path(interp))
        for name in needed:
            if name in seen:
                continue
            seen.add(name)
            search = [p.replace("$ORIGIN", str(current.parent)) for p in runpath] + [
                str(prefix / "lib"), *_LIBRARY_DIRS]
            found = next((Path(d) / name for d in search if (Path(d) / name).exists()), None)
            if found is None:
                raise _refuse(DEPENDENCY_UNAVAILABLE)
            if str(found).startswith(str(closure_root)):
                continue  # vendored beside the extension; part of the closure
            libraries.append(found)
            pending.append(found.resolve())
    return [*files, *libraries]


def _copy_regular(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    real = source.resolve(strict=True)
    if not real.is_file():
        raise _refuse(PROVENANCE_REFUSED)
    shutil.copyfile(real, destination)
    os.chmod(destination, 0o555 if os.access(real, os.X_OK) else 0o444)


def _snapshot_inventory(root: Path, *, hashes: bool) -> dict[str, list]:
    """``{relpath: [sha256 or None, size, mode]}`` for every entry under ``root``; a
    symlink or special file refuses."""
    out: dict[str, list] = {}
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames:
            if stat.S_ISLNK(os.lstat(os.path.join(directory, name)).st_mode):
                raise _refuse(PROVENANCE_REFUSED)
        for name in filenames:
            path = Path(directory) / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise _refuse(PROVENANCE_REFUSED)
            rel = path.relative_to(root).as_posix()
            out[rel] = [file_sha256(path) if hashes else None, info.st_size,
                        stat.S_IMODE(info.st_mode)]
    return dict(sorted(out.items()))


def _signature(root: Path) -> str:
    """The snapshot's device/inode/size/mtime/ctime/mode signature: every entry, files and
    directories, so any addition, removal or change invalidates it."""
    rows = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted((*dirnames, *filenames)):
            path = os.path.join(directory, name)
            info = os.lstat(path)
            rows.append([os.path.relpath(path, root), info.st_dev, info.st_ino, info.st_size,
                         info.st_mtime_ns, info.st_ctime_ns, info.st_mode])
    info = os.lstat(root)
    rows.append([".", info.st_dev, info.st_ino, 0, info.st_mtime_ns, info.st_ctime_ns,
                 info.st_mode])
    return sha256_hex(canonical(sorted(rows)))


def _make_read_only(root: Path) -> None:
    for directory, dirnames, _filenames in os.walk(root, topdown=False):
        for name in dirnames:
            os.chmod(os.path.join(directory, name), 0o555)
    os.chmod(root, 0o555)


def seal(venv: Path, *, directory: Path | None = None, manifest_raw: bytes | None = None,
         export_raw: bytes | None = None) -> dict:
    """Seal one documented worker venv (``uv venv`` + ``uv pip sync --require-hashes
    --only-binary :all:`` of the frozen export) into a read-only snapshot and register it.

    The site directory must hold exactly the closure manifest's files, byte for byte,
    plus installer metadata, installer bytecode and the venv's own artifacts; the last two
    are normalized away. The snapshot holds the closure, the interpreter, the standard
    library, the ELF loader and the runtime libraries, every one a regular read-only file
    copied from its resolved source. Returns the registration."""
    directory = directory or state_dir()
    manifest = closure_manifest(manifest_raw)
    export_raw = read_packaged(EXPORT) if export_raw is None else export_raw
    if manifest.get("export_sha256") != sha256_hex(export_raw):
        raise _refuse(PROVENANCE_REFUSED)
    venv = venv.resolve(strict=True)
    cfg = _pyvenv(venv)
    interpreter = (venv / "bin" / "python").resolve(strict=True)
    home = Path(cfg["home"]).resolve(strict=True)
    prefix = home.parent
    site = _site_dir(venv, cfg["version_info"])
    expected = manifest["_files"]
    present: set[str] = set()
    for path in sorted(site.rglob("*")):
        rel = path.relative_to(site).as_posix()
        parts = rel.split("/")
        if path.is_symlink():
            raise _refuse(PROVENANCE_REFUSED)
        if path.is_dir():
            continue
        if "__pycache__" in parts or rel.endswith((".pyc", ".pyo")) or rel in VENV_ARTIFACTS:
            continue  # installer- and venv-generated; normalized away
        if rel.endswith(".pth"):
            raise _refuse(PROVENANCE_REFUSED)
        if rel in expected:
            if file_sha256(path) != expected[rel]:
                raise _refuse(PROVENANCE_REFUSED)
            present.add(rel)
        elif not (len(parts) == 2 and parts[0].endswith(".dist-info")
                  and parts[1] in INSTALLER_METADATA):
            raise _refuse(PROVENANCE_REFUSED)
    if present != set(expected):
        raise _refuse(DEPENDENCY_UNAVAILABLE)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    snapshots = directory / "snapshots"
    snapshots.mkdir(exist_ok=True, mode=0o700)
    staging = Path(_mkdtemp(snapshots))
    try:
        closure = staging / "closure"
        for rel in sorted(expected):
            _copy_regular(site / rel, closure / rel)
        runtime = staging / "runtime"
        for source in runtime_files(interpreter, prefix, cfg["version_info"], site):
            target = runtime / str(source).lstrip("/")
            if not target.exists():
                _copy_regular(source, target)
        runtime_inventory = _snapshot_inventory(runtime, hashes=True)
        closure_inventory = _snapshot_inventory(closure, hashes=True)
        runtime_manifest = {"schema": SNAPSHOT_SCHEMA, "part": "runtime",
                            "interpreter": str(interpreter).lstrip("/"),
                            "version": cfg["version_info"],
                            "pyvenv_cfg_sha256": file_sha256(venv / "pyvenv.cfg"),
                            "files": runtime_inventory}
        snapshot_manifest = {"schema": SNAPSHOT_SCHEMA, "host_class": HOST_CLASS,
                             "closure_manifest_sha256": manifest_digest(manifest_raw),
                             "export_sha256": sha256_hex(export_raw),
                             "runtime_manifest_sha256": sha256_hex(canonical(runtime_manifest)),
                             "closure": closure_inventory, "runtime": runtime_manifest}
        (staging / "snapshot.json").write_bytes(canonical(snapshot_manifest))
        os.chmod(staging / "snapshot.json", 0o444)
        digest = sha256_hex(canonical(snapshot_manifest))
        final = snapshots / digest
        if final.exists():
            shutil.rmtree(staging, onerror=_force_remove)
        else:
            _make_read_only(staging)
            os.chmod(staging, 0o755)
            os.rename(staging, final)
            os.chmod(final, 0o555)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, onerror=_force_remove)
        raise
    registration = {
        "schema": REGISTRATION_SCHEMA, "host_class": HOST_CLASS, "snapshot": str(final),
        "snapshot_sha256": digest, "interpreter": str(interpreter).lstrip("/"),
        "version": cfg["version_info"],
        "runtime_manifest_sha256": snapshot_manifest["runtime_manifest_sha256"],
        "closure_manifest_sha256": snapshot_manifest["closure_manifest_sha256"],
        "export_sha256": snapshot_manifest["export_sha256"],
    }
    target = registration_path(directory)
    temporary = target.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
                         | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical(registration))
    os.replace(temporary, target)
    return registration


def _mkdtemp(parent: Path) -> str:
    import tempfile

    return tempfile.mkdtemp(prefix=".seal-", dir=parent)


def _force_remove(function, path, _excinfo) -> None:
    os.chmod(os.path.dirname(path), 0o700)
    if os.path.isdir(path) and not os.path.islink(path):
        os.chmod(path, 0o700)
    function(path)


def manifest_digest(raw: bytes | None = None) -> str:
    return sha256_hex(read_packaged(CLOSURE_MANIFEST) if raw is None else raw)


@dataclasses.dataclass(frozen=True)
class WorkerInstall:
    """A registered, verified worker snapshot. ``inventory`` and ``excluded`` are what the
    bootstrap verifies per worker (``0/<path>`` under the closure root)."""

    snapshot: Path
    closure_root: Path
    runtime_root: Path
    interpreter: Path
    snapshot_sha256: str
    runtime_manifest_sha256: str
    closure_manifest_sha256: str
    inventory: Mapping[str, str]
    excluded: tuple[str, ...]


def _read_private_json(path: Path, cap: int = 1 << 20) -> dict:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        raise _refuse(DEPENDENCY_UNAVAILABLE) from None
    except OSError:
        raise _refuse(PROVENANCE_REFUSED) from None
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > cap):
            raise _refuse(PROVENANCE_REFUSED)
        raw = os.read(descriptor, cap + 1)
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, ValueError):
        raise _refuse(PROVENANCE_REFUSED) from None
    if not isinstance(value, dict):
        raise _refuse(PROVENANCE_REFUSED)
    return value


def verify_install(directory: Path | None = None, *, manifest_raw: bytes | None = None,
                   export_raw: bytes | None = None) -> WorkerInstall:
    """The registered snapshot, verified. The first call for a snapshot (per process: one
    board) hashes every file against its manifest and the packaged closure manifest; later
    calls compare the complete signature inventory and re-verify in full on any change."""
    registration = _read_private_json(registration_path(directory))
    keys = {"schema", "host_class", "snapshot", "snapshot_sha256", "interpreter", "version",
            "runtime_manifest_sha256", "closure_manifest_sha256", "export_sha256"}
    if set(registration) != keys or registration["schema"] != REGISTRATION_SCHEMA \
            or registration["host_class"] != HOST_CLASS:
        raise _refuse(PROVENANCE_REFUSED)
    if registration["closure_manifest_sha256"] != manifest_digest(manifest_raw):
        raise _refuse(PROVENANCE_REFUSED)
    export_raw = read_packaged(EXPORT) if export_raw is None else export_raw
    if registration["export_sha256"] != sha256_hex(export_raw):
        raise _refuse(PROVENANCE_REFUSED)
    snapshot = Path(registration["snapshot"])
    try:
        info = snapshot.lstat()
    except OSError:
        raise _refuse(DEPENDENCY_UNAVAILABLE) from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or snapshot.name != registration["snapshot_sha256"]):
        raise _refuse(PROVENANCE_REFUSED)
    signature = _signature(snapshot)
    key = str(snapshot)
    if _SIGNATURE_CACHE.get(key) != signature:
        _SIGNATURE_CACHE.pop(key, None)
        _verify_snapshot_fully(snapshot, registration, manifest_raw)
        if _signature(snapshot) != signature:
            raise _refuse(PROVENANCE_REFUSED)
        _SIGNATURE_CACHE[key] = signature
    manifest = closure_manifest(manifest_raw)
    excluded = tuple(f"0/{rel}" for rel in manifest["excluded"])
    inventory = {f"0/{rel}": digest for rel, digest in manifest["_files"].items()
                 if f"0/{rel}" not in excluded}
    return WorkerInstall(
        snapshot=snapshot, closure_root=snapshot / "closure", runtime_root=snapshot / "runtime",
        interpreter=snapshot / "runtime" / registration["interpreter"],
        snapshot_sha256=registration["snapshot_sha256"],
        runtime_manifest_sha256=registration["runtime_manifest_sha256"],
        closure_manifest_sha256=registration["closure_manifest_sha256"],
        inventory=MappingProxyType(inventory), excluded=excluded)


def _verify_snapshot_fully(snapshot: Path, registration: dict,
                           manifest_raw: bytes | None) -> None:
    record = snapshot / "snapshot.json"
    info = record.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o222:
        raise _refuse(PROVENANCE_REFUSED)
    raw = record.read_bytes()
    try:
        recorded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, ValueError):
        raise _refuse(PROVENANCE_REFUSED) from None
    if raw != canonical(recorded) or sha256_hex(raw) != registration["snapshot_sha256"]:
        raise _refuse(PROVENANCE_REFUSED)
    if (recorded.get("runtime_manifest_sha256") != registration["runtime_manifest_sha256"]
            or sha256_hex(canonical(recorded.get("runtime"))) != registration[
                "runtime_manifest_sha256"]):
        raise _refuse(PROVENANCE_REFUSED)
    for part, inventory in (("closure", recorded.get("closure")),
                            ("runtime", (recorded.get("runtime") or {}).get("files"))):
        observed = _snapshot_inventory(snapshot / part, hashes=True)
        if observed != inventory:
            raise _refuse(PROVENANCE_REFUSED)
        for _rel, (_digest, _size, mode) in observed.items():
            if mode & 0o222:
                raise _refuse(PROVENANCE_REFUSED)
    expected = closure_manifest(manifest_raw)["_files"]
    if {rel: row[0] for rel, row in recorded["closure"].items()} != expected:
        raise _refuse(PROVENANCE_REFUSED)
    for directory, dirnames, _files in os.walk(snapshot):
        for name in (*dirnames, "."):
            if stat.S_IMODE(os.lstat(os.path.join(directory, name)).st_mode) & 0o222:
                raise _refuse(PROVENANCE_REFUSED)


# --------------------------------------------------------------------------------------
# Preflight: before the leg's credential resolver.
# --------------------------------------------------------------------------------------

#: The parent-side helper SL-1 delivers to launch the worker in its sandbox and drive the
#: duplex exchange with the jailed CLI (IF-0-CLAUDE-3). Its absence is a missing
#: prerequisite.
PARENT_LEG_HELPER = "_run_claude_sdk_leg"
BWRAP = "/usr/bin/bwrap"


def payload_digests(payload: Mapping[str, bytes] | None = None) -> dict[str, str]:
    payload = payload if payload is not None else {
        name: read_packaged(f"worker/{name}") for name in WORKER_PAYLOAD}
    return {name: sha256_hex(payload[name]) for name in WORKER_PAYLOAD}


def installed_bindings(payload: Mapping[str, bytes] | None = None) -> dict[str, str]:
    """The installed artifacts a receipt must bind, recomputed from the package (the
    payload from ``payload`` when the caller already read it)."""
    bindings = {
        "launch_fixture_sha256": sha256_hex(read_packaged(LAUNCH_FIXTURE)),
        "export_sha256": sha256_hex(read_packaged(EXPORT)),
        "closure_manifest_sha256": manifest_digest(),
        "seat_module_sha256": sha256_hex(Path(__file__).read_bytes()),
    }
    bindings.update({f"payload:{name}": digest
                     for name, digest in payload_digests(payload).items()})
    return bindings


def packaged_receipt() -> dict:
    raw = read_packaged(RECEIPT, cap=1 << 20)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeDecodeError, ValueError):
        raise _refuse(PROVENANCE_REFUSED) from None
    if validate_receipt(value):
        raise _refuse(PROVENANCE_REFUSED)
    return value


@dataclasses.dataclass(frozen=True)
class PreparedSdkLaunch:
    """What one leg's preflight verified, carried to its launch: the verified install, the
    worker payload's exact bytes (read once and checked against the receipt), and the
    receipt bindings they were checked against. The launch seals these bytes into the
    worker's memfds; nothing re-reads the packaged payload after the credential."""

    install: WorkerInstall
    payload_bytes: Mapping[str, bytes] = dataclasses.field(repr=False)
    bindings: Mapping[str, str]
    directory: Path | None = None
    #: The closure manifest the install was verified against (``None``: the packaged one).
    manifest_raw: bytes | None = dataclasses.field(default=None, repr=False)


def preflight(directory: Path | None = None) -> PreparedSdkLaunch:
    """Worker readiness and provenance, in order, before any credential-store read: the
    packaged data and its receipt bindings (the worker payload read once, here), the
    registered snapshot, then the worker's launch prerequisites. Returns the prepared
    launch; raises :class:`SDKRefused` with the first typed code."""
    sdk_cli_delta()
    payload = {name: read_packaged(f"worker/{name}") for name in WORKER_PAYLOAD}
    bindings = installed_bindings(payload)
    receipt = packaged_receipt()
    if any(receipt["installed_bindings"].get(name) != digest
           for name, digest in bindings.items()):
        raise _refuse(PROVENANCE_REFUSED)
    install = verify_install(directory)
    if install.runtime_manifest_sha256 not in receipt["runtime_manifest_sha256"]:
        raise _refuse(PROVENANCE_REFUSED)
    worker_filter_program()
    from . import seat_uid

    if not (os.path.isfile(BWRAP) and seat_uid.seat_uid_available()):
        raise _refuse(WORKER_UNAVAILABLE)
    if not callable(getattr(_pi(), PARENT_LEG_HELPER, None)):
        raise _refuse(WORKER_UNAVAILABLE)
    return PreparedSdkLaunch(install=install, payload_bytes=MappingProxyType(payload),
                             bindings=MappingProxyType(bindings), directory=directory)


def still_current(prepared: object) -> PreparedSdkLaunch:
    """The prepared launch, if it is one and its install still verifies (the snapshot's
    signature, re-checked); else a typed refusal. Its payload bytes are never re-read."""
    if not isinstance(prepared, PreparedSdkLaunch):
        raise _refuse(WORKER_UNAVAILABLE)
    for name in WORKER_PAYLOAD:
        data = prepared.payload_bytes.get(name)
        if not isinstance(data, bytes) or sha256_hex(data) != prepared.bindings.get(
                f"payload:{name}"):
            raise _refuse(PROVENANCE_REFUSED)
    current = verify_install(prepared.directory, manifest_raw=prepared.manifest_raw)
    if current.snapshot_sha256 != prepared.install.snapshot_sha256:
        raise _refuse(PROVENANCE_REFUSED)
    return prepared


# --------------------------------------------------------------------------------------
# The launch spec SL-1's launcher consumes.
# --------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class WorkerLaunchSpec:
    """What the owned launcher needs to start one worker, all from the fixture and the
    verified install: the interpreter and flags, the bootstrap, the explicit
    credential-free environment, the read-only and private mounts, the namespaces, the
    finite limits and the syscall filter it delivers. No credential, jail or token pipe."""

    argv: tuple[str, ...]
    env: Mapping[str, str]
    read_only: Mapping[str, str]
    private_tmpfs: Mapping[str, int]
    namespaces: tuple[str, ...]
    limits: Mapping[str, int]
    filter_program: bytes = dataclasses.field(repr=False)


def worker_launch_spec(install: WorkerInstall) -> WorkerLaunchSpec:
    worker = sdk_cli_delta()["worker"]
    payload = data_dir() / "worker"
    mounts = dict(worker["mounts"])
    return WorkerLaunchSpec(
        argv=(f"/{install.interpreter.relative_to(install.runtime_root).as_posix()}",
              *worker["interpreter_flags"], f"{mounts['payload']}/claude_sdk_bootstrap.py"),
        env=MappingProxyType(dict(worker["env"])),
        read_only=MappingProxyType({"/": str(install.runtime_root),
                                    mounts["payload"]: str(payload),
                                    mounts["closure"]: str(install.closure_root)}),
        private_tmpfs=MappingProxyType({path: int(size) for path, size in
                                        dict(worker["tmpfs"]).items()}),
        namespaces=tuple(worker["namespaces"]),
        limits=MappingProxyType({k: int(v) for k, v in dict(worker["limits"]).items()}),
        filter_program=worker_filter_program(),
    )


def frozen_options(*, model: str, effort: str | None, session_id: str, settings: str,
                   fixture: Mapping[str, object] | None = None) -> dict[str, object]:
    """The fixture's frozen SDK options, field by field, with this leg's values."""
    values = {"<MODEL>": model, "<EFFORT>": effort, "<SESSION_ID>": session_id,
              "<SETTINGS>": settings}
    fixture = sdk_cli_delta() if fixture is None else fixture
    return {name: values.get(value, value) if isinstance(value, str) else value
            for name, value in dict(fixture["options"]).items()}


# --------------------------------------------------------------------------------------
# The boundary receipt (closed schema ``claude-sdk-boundary.v1``).
# --------------------------------------------------------------------------------------

RECEIPT_SCHEMA = _ct.SDK_RECEIPT_SCHEMA
RECEIPT_PATH = _ct.SDK_RECEIPT
#: The closed field set (``claude_seat_transport`` holds the one definition the base
#: auditor and this module share).
RECEIPT_FIELDS: tuple[str, ...] = _ct.SDK_RECEIPT_FIELDS
PROOF_FILES: tuple[str, ...] = _ct.SDK_PROOF_FILES
PROOF_REGIONS: Mapping[str, tuple[str, ...]] = _ct.SDK_PROOF_REGIONS
PROOF_EXTRAS: tuple[str, ...] = _ct.SDK_PROOF_EXTRAS
DEPENDENCY_INVENTORY: tuple[str, ...] = _ct.SDK_DEPENDENCY_INVENTORY


def validate_receipt(value: object) -> list[str]:
    """Every way ``value`` is not a passing ``claude-sdk-boundary.v1`` receipt, nested
    levels included (``claude_seat_transport.validate_sdk_receipt``)."""
    return _ct.validate_sdk_receipt(value)


def module_dependencies(source: bytes) -> set[str]:
    return _ct.module_dependencies(source)


def source_region(source: bytes, name: str) -> bytes:
    """The bytes of one top-level function, class or assignment named ``name``."""
    region = _ct.source_region(source, name)
    if region is None:
        raise _refuse(PROVENANCE_REFUSED)
    return region


def _checkout_reader(repo: Path):
    def read(rel: str) -> bytes | None:
        path = repo / rel
        if not path.is_file() or path.is_symlink():
            return None
        return path.read_bytes()

    return read


def proof_inputs(repo: Path) -> dict[str, str]:
    """``{input: sha256}`` over every proof input of a checkout, the base auditor's own
    computation; a missing input, an unclassified region dependency or an import outside
    the inventory fails closed."""
    try:
        return _ct.sdk_proof_bindings(_checkout_reader(repo))
    except _ct.AuditError:
        raise _refuse(PROVENANCE_REFUSED) from None


def proof_inputs_sha256(repo: Path, *, extras: Mapping[str, str]) -> str:
    """The canonical binding the receipt and every VB/VL JUnit carry: the checkout's
    proof inputs joined with the receipt-named install and private bindings
    (:data:`PROOF_EXTRAS`), never a commit SHA."""
    try:
        return _ct.sdk_proof_inputs_sha256(proof_inputs(repo), extras)
    except _ct.AuditError:
        raise _refuse(PROVENANCE_REFUSED) from None


# --------------------------------------------------------------------------------------
# The jailed transport entry point.
# --------------------------------------------------------------------------------------

def run_jailed(
    seat: object,
    *,
    timeout_s: int,
    backstop_s: int,
    model: str | None,
    effort: str | None,
    prompt: str,
    broker_evidence: dict[str, object] | None,
    env: Mapping[str, str] | None = None,
    failure_detail_sink: list | None = None,
    quiescence_latch: object | None = None,
    review_monitor: object | None = None,
    session_name: str | None = None,
    **_unused: object,
) -> tuple[str, str]:
    """The ``sdk`` transport on a prepared, login-proven jailed seat, launched from the
    seat's pre-credential preflight (``seat.sdk_prepared``); an absent or no longer current
    one refuses. Without the parent leg helper (:data:`PARENT_LEG_HELPER`) it refuses
    ``claude_sdk_worker_unavailable`` and launches nothing. Tears the seat down whatever
    happens."""
    from . import seat_jail as _seat_jail

    pi = _pi()

    def fail(code: str, status: str = "DEGRADED") -> tuple[str, str]:
        if failure_detail_sink is not None:
            failure_detail_sink.append(pi._LegFailure(template=code))
        if broker_evidence is not None:
            broker_evidence["claude_admission"] = {"outcome": "refused", "code": code}
        return status, ""

    try:
        if review_monitor is not None and review_monitor.cancel.is_set():  # type: ignore[attr-defined]
            return "UNAVAILABLE", "review_operation_cancelled"
        if broker_evidence is not None:
            broker_evidence.update({"claude_transport": TRANSPORT, "claude_route": TRANSPORT,
                                    "claude_code_entrypoint": "unset",
                                    "claude_sdk_location": "host_worker",
                                    "claude_sdk_version": SDK_VERSION})
        try:
            # The launch the pre-credential preflight prepared (``seat.sdk_prepared``),
            # still current; never a new preflight or new payload bytes after the credential.
            prepared = still_current(getattr(seat, "sdk_prepared", None))
        except SDKRefused as refusal:
            return fail(refusal.code)
        install = prepared.install
        helper = getattr(pi, PARENT_LEG_HELPER, None)
        if not callable(helper):
            return fail(WORKER_UNAVAILABLE)
        jail = seat.jail  # type: ignore[attr-defined]
        import uuid

        session_id = str(uuid.uuid4())
        requested = model or pi.HARDEN_SUPPORTED_SUBSCRIPTION_ROUTES["claude"]
        command = build_sdk_cli_argv(jail, model=model, effort=effort, session_id=session_id,
                                     env=env, session_name=session_name)
        sealed = pi._BROKER_CLAUDE_DIRECT_REQUEST + prompt
        bridge = SDKBridge(token=seat.token, session_id=session_id,  # type: ignore[attr-defined]
                           prompt=sealed)
        spec = worker_launch_spec(install)
        effort_value = command[command.index("--effort") + 1] if "--effort" in command else None
        options = frozen_options(model=requested, effort=effort_value, session_id=session_id,
                                 settings=pi._claude_panel_settings(env))
        try:
            run = helper(command, spec=spec, bridge=bridge, prepared=prepared, options=options,
                         cwd=Path(_seat_jail.SEAT_TREE), env=cli_env(jail),
                         deadline_s=float(max(1, int(backstop_s))), seat=seat,
                         quiescence_latch=quiescence_latch, review_monitor=review_monitor)
        except TransportRefused as refusal:
            return fail(refusal.code)
        verdict, value = bridge.outcome(int(getattr(run, "returncode", 1)))
        if verdict != "admitted":
            return fail(value)
        if broker_evidence is not None:
            broker_evidence.update(bridge.admission.evidence())
            broker_evidence["claude_admission"] = {"outcome": "admitted", "code": "none"}
        status = pi._classify_leg(0, value.strip(), "claude_print_result", "review")
        return (status, value.strip()) if status == "OK" else fail(RESULT_UNPROVEN)
    finally:
        pi._cleanup_jailed_seat(seat, primary=sys.exception())


# --------------------------------------------------------------------------------------
# The operator commands.
# --------------------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m phase_loop_runtime.claude_seat_sdk")
    sub = parser.add_subparsers(dest="command", required=True)
    sealing = sub.add_parser("seal", help="seal and register a documented worker venv")
    sealing.add_argument("venv")
    sub.add_parser("verify", help="verify the registered worker install")
    manifest = sub.add_parser("manifest", help="regenerate the closure manifest from wheels")
    manifest.add_argument("wheels", help="a directory of the export's downloaded wheels")
    args = parser.parse_args(argv)
    try:
        if args.command == "seal":
            registration = seal(Path(args.venv))
            print(f"claude-sdk worker sealed: snapshot {registration['snapshot_sha256']}")
        elif args.command == "verify":
            install = verify_install()
            print(f"claude-sdk worker verified: snapshot {install.snapshot_sha256}")
        else:
            wheels = sorted(Path(args.wheels).glob("*.whl"))
            sys.stdout.write(canonical(manifest_from_wheels(wheels, read_packaged(EXPORT)))
                             .decode("ascii") + "\n")
    except SDKRefused as refusal:
        print(f"claude-sdk worker: refused ({refusal.code})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
