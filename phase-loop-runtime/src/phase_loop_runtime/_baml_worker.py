"""BAML v1 worker process for ``phase_loop_runtime.baml_modular`` (agent-harness#1135).

This file runs as a standalone script (``python -I -S _baml_worker.py ...``).
It imports only the standard library and, after ``init``, ``baml_bridge``; it
never imports ``phase_loop_runtime``.  Importing this module has no side
effects: everything below runs under ``if __name__ == "__main__":``.

argv: ``<owner pid> <comma-separated env allowlist keys> [--no-pdeathsig]``.

Protocol: one JSON object per line, UTF-8 with ``ensure_ascii=True``.  Requests
arrive on fd 0; responses leave on a dup of fd 1 taken before fd 1 is pointed
at stderr, so nothing the native runtime prints can corrupt the protocol.
Every request carries an ``id`` that the response echoes.  A response has
exactly the keys ``{id, fingerprint, <one of ok|error|request|fault>}``.

Op table (fixed): ``init``, ``parse_closeout``, ``closeout_request``,
``evidence_request``, plus ``env`` when ``init`` carried ``test_mode``.  An op
before ``init`` or a second ``init`` is answered with a ``fault``.  Any
exception raised by an op (``BaseException``, including ``BamlPanic``) is
returned as a ``fault``; the client then discards and kills the worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

_OP_FUNCTIONS = {
    "parse_closeout": ("user.phase_loop_parse_closeout", ("raw",), ("ok", "error")),
    "closeout_request": (
        "user.phase_loop_closeout_request",
        ("phase_alias", "plan_produces", "plan_owned_files", "closeout_commit_sha"),
        ("request",),
    ),
    "evidence_request": (
        "user.phase_loop_evidence_request",
        ("tier2_signal_summary", "sample_artifact_content", "expected_artifact_characteristics"),
        ("request",),
    ),
}
# The client caps a request frame at 4 MiB + 1 KiB; anything larger here is a
# client bug or a hostile writer, and is refused rather than buffered forever.
_MAX_REQUEST_LINE = 4 * 1024 * 1024 + 1024 + 4096
_WATCHDOG_INTERVAL_S = 0.5
_PR_SET_PDEATHSIG = 1


def fingerprint(files: dict[str, str]) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _set_pdeathsig(owner_pid: int) -> None:
    import ctypes
    import signal

    # ctypes.CDLL(None) resolves prctl on glibc and musl alike; find_library("c")
    # and "libc.so.6" do not work on musl.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0) != 0:
        os._exit(70)
    # The owner may have died between our fork and the prctl.
    if os.getppid() != owner_pid:
        os._exit(0)


def _start_watchdog(owner_pid: int) -> None:
    import threading
    import time

    def watch() -> None:
        while True:
            if os.getppid() != owner_pid:
                os._exit(0)
            time.sleep(_WATCHDOG_INTERVAL_S)

    threading.Thread(target=watch, name="baml-worker-watchdog", daemon=True).start()


class _Worker:
    def __init__(self, out_fd: int, no_pdeathsig: bool) -> None:
        self.out_fd = out_fd
        self.no_pdeathsig = no_pdeathsig
        self.fp: str | None = None
        self.fns: dict[str, object] | None = None
        self.test_mode = False

    def send(self, obj: dict) -> None:
        data = (json.dumps(obj, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")
        view = memoryview(data)
        while view:
            written = os.write(self.out_fd, view)
            view = view[written:]

    def handle(self, line: bytes) -> None:
        req_id = None
        try:
            req = json.loads(line.decode("ascii"))
            if not isinstance(req, dict):
                raise ValueError("request is not a JSON object")
            req_id = req.get("id")
            op = req.get("op")
            if op == "init":
                result = self.init(req)
                self.send({"id": req_id, "fingerprint": self.fp, "ok": result})
                return
            if self.fns is None:
                raise RuntimeError(f"op before init: {op!r}")
            if op == "env" and self.test_mode:
                self.send({"id": req_id, "fingerprint": self.fp, "ok": {"env": sorted(os.environ), "cwd": os.getcwd(), "pid": os.getpid()}})
                return
            if op not in _OP_FUNCTIONS:
                raise RuntimeError(f"unknown op: {op!r}")
            _name, params, keys = _OP_FUNCTIONS[op]
            args = req.get("args")
            if not isinstance(args, dict) or set(args) != set(params):
                raise RuntimeError(f"bad args for {op}")
            out = self.fns[op](**args)
            if not isinstance(out, dict) or len(out) != 1:
                raise RuntimeError(f"bridge {op} returned an unexpected shape")
            ((key, value),) = out.items()
            if key not in keys or not isinstance(value, str):
                raise RuntimeError(f"bridge {op} returned key {key!r}")
            self.send({"id": req_id, "fingerprint": self.fp, key: value})
        except BaseException as exc:  # noqa: BLE001 - every op failure is a typed fault
            message = f"{type(exc).__module__}.{type(exc).__qualname__}: {str(exc)[:500]}"
            self.send({"id": req_id, "fingerprint": self.fp, "fault": message})

    def init(self, req: dict) -> dict:
        if self.fns is not None:
            raise RuntimeError("second init")
        self.test_mode = req.get("test_mode") is True
        if self.no_pdeathsig and not self.test_mode:
            raise RuntimeError("--no-pdeathsig requires test_mode")
        for entry in req.get("sys_path") or []:
            if isinstance(entry, str) and os.path.isabs(entry) and entry not in sys.path:
                sys.path.append(entry)
        files = req.get("files")
        if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
            raise RuntimeError("init files must be a map of strings")
        import baml_bridge

        baml_bridge.BamlRuntime.initialize_runtime("baml_src", files)
        fns = {op: baml_bridge.define_function(name, "sync", list(params)) for op, (name, params, _keys) in _OP_FUNCTIONS.items()}
        self.fp = fingerprint(files)
        self.fns = fns
        return {"version": baml_bridge.get_version(), "pid": os.getpid()}

    def serve(self) -> None:
        buf = b""
        while True:
            chunk = os.read(0, 1 << 16)
            if not chunk:
                return  # stdin EOF: the graceful shutdown path
            buf += chunk
            while True:
                newline = buf.find(b"\n")
                if newline < 0:
                    break
                line, buf = buf[:newline], buf[newline + 1 :]
                self.handle(line)
            if len(buf) > _MAX_REQUEST_LINE:
                self.send({"id": None, "fingerprint": self.fp, "fault": "request line over cap"})
                return


def main(argv: list[str]) -> int:
    owner_pid = int(argv[1])
    allowlist = {key for key in argv[2].split(",") if key} if len(argv) > 2 else set()
    no_pdeathsig = "--no-pdeathsig" in argv[3:]

    out_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    # Normalize the environment before baml_bridge is ever imported: this drops
    # interpreter-injected keys (C-locale coercion's LC_CTYPE,
    # __PYVENV_LAUNCHER__) that the parent's allowlist never passed.
    for key in list(os.environ):
        if key not in allowlist:
            del os.environ[key]

    if os.name == "posix":
        if sys.platform.startswith("linux") and not no_pdeathsig:
            _set_pdeathsig(owner_pid)
        elif os.getppid() != owner_pid:
            os._exit(0)
        _start_watchdog(owner_pid)
    # Windows: the parent's Job Object (KILL_ON_JOB_CLOSE) enforces owner death.

    _Worker(out_fd, no_pdeathsig).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
