"""Windows ownership primitives. Leased production dispatch is not qualified yet."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import runpy
import subprocess
import sys
import threading
import time
import uuid


def _kernel():
    if os.name != "nt":
        raise OSError("Windows process ownership requires native Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "DuplicateHandle": ([wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes = args
        function.restype = result
    return kernel


def process_is_live(pid: int) -> bool:
    """Probe without os.kill(pid, 0), which can terminate processes on Windows."""
    if pid <= 0:
        return False
    kernel = _kernel()
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: no such process.
            return False
        if error == 5:  # Access denied is not evidence of death.
            return True
        raise ctypes.WinError(error)
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0x102  # WAIT_TIMEOUT
    finally:
        kernel.CloseHandle(handle)


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits), ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class Job:
    """Noninheritable, unnamed Job Object; descendants cannot request breakaway."""

    def __init__(self):
        self.kernel = _kernel()
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign(self, process: subprocess.Popen) -> None:
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE. Open by the still-live waiting
        # child's pid; the caller owns its Popen handle throughout admission.
        handle = self.kernel.OpenProcess(0x0100 | 0x0001, False, process.pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel.CloseHandle(handle)

    def active_processes(self) -> int:
        value = _Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.ActiveProcesses

    def terminate(self) -> None:
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def member_handles(self) -> list[int]:
        """Retain wait handles before termination (accounting can settle first)."""
        count = max(32, self.active_processes() * 2)
        while True:
            class ProcessIds(ctypes.Structure):
                _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                            ("ids", ctypes.c_size_t * count)]
            value = ProcessIds()
            if self.kernel.QueryInformationJobObject(self.handle, 3, ctypes.byref(value), ctypes.sizeof(value), None):
                break
            error = ctypes.get_last_error()
            if error != 234:  # ERROR_MORE_DATA
                raise ctypes.WinError(error)
            count *= 2
        handles = []
        try:
            for pid in value.ids[:value.listed]:
                handle = self.kernel.OpenProcess(0x00100000, False, pid)
                if not handle:
                    error = ctypes.get_last_error()
                    if error != 87:
                        raise ctypes.WinError(error)
                else:
                    handles.append(handle)
            return handles
        except BaseException:
            for handle in handles:
                self.kernel.CloseHandle(handle)
            raise

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    output: str
    timed_out: bool
    output_limited: bool
    quiescent: bool


def run_owned(command: list[str], *, stdin_text: str | None = None,
              cwd: str | Path | None = None, env: dict[str, str] | None = None,
              timeout_seconds: float | None = 30, max_bytes: int = 1048576,
              cancel: threading.Event | None = None, on_started=None,
              on_output=None, on_tick=None) -> ProcessResult:
    """Exercise admitted ownership with bounded IO; not a leased-launch backend.

    One deadline covers admission, execution and confirmation of cleanup. A false
    quiescent result must never release a generation lease or claim completion.
    """
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else float("inf")
    execution_deadline = deadline - min(1.0, timeout_seconds / 5) if timeout_seconds is not None else deadline
    if not command or (timeout_seconds is not None and timeout_seconds <= 0) or not 0 < max_bytes <= 1048576:
        raise ValueError("A command and positive timeout and byte limit are required")
    executable = shutil.which(command[0], path=env.get("PATH") if env else None)
    if executable is None or Path(executable).suffix.lower() != ".exe":
        raise ValueError("Native Windows ownership accepts explicit .exe entry points only")
    payload = json.dumps({"command": [executable, *command[1:]], "stdin": stdin_text}).encode("utf-8") + b"\n"
    if len(payload) > max_bytes:
        raise ValueError("Executor request exceeds the byte limit")
    output = bytearray()
    overflow = threading.Event()
    io_error = threading.Event()
    job = Job()
    process = None
    threads = []
    timed_out = False
    quiescent = False
    members = []
    try:
        # The isolated stdlib-only child cannot launch the executor until it gets
        # the JSON admission message. Nothing writes that message before assign.
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(Path(__file__).resolve()), "--admitted-child"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            close_fds=True, cwd=cwd, env=env,
        )
        try:
            job.assign(process)
        except BaseException:
            process.kill()
            process.wait(timeout=min(5, max(0.001, deadline - time.monotonic())))
            raise
        if time.monotonic() >= execution_deadline:
            job.terminate()
            raise TimeoutError("Executor admission deadline expired")
        if on_started:
            on_started(process.pid)

        def write_request():
            try:
                process.stdin.write(payload)
                process.stdin.close()
            except Exception:
                io_error.set()

        def read_output():
            try:
                while chunk := process.stdout.read1(65536):
                    room = max_bytes - len(output)
                    output.extend(chunk[:room])
                    if on_output and room:
                        on_output(chunk[:room])
                    if len(chunk) > room:
                        overflow.set()
                        return
            except Exception:
                io_error.set()

        for target in (read_output, write_request):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            threads.append(thread)
        while process.poll() is None:
            if time.monotonic() >= execution_deadline:
                timed_out = True
                break
            if overflow.is_set() or io_error.is_set() or (cancel and cancel.is_set()):
                break
            if on_tick:
                on_tick()
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        returncode = process.poll()
        if overflow.is_set() or io_error.is_set():
            returncode = 1
        members = job.member_handles()
        job.terminate()
        cleanup_deadline = min(deadline, time.monotonic() + 5)
        while time.monotonic() < cleanup_deadline:
            if job.active_processes() == 0 and all(job.kernel.WaitForSingleObject(handle, 0) == 0 for handle in members):
                quiescent = True
                break
            time.sleep(0.005)
        process.wait(timeout=max(0.001, cleanup_deadline - time.monotonic()))
        for thread in threads:
            thread.join(timeout=max(0, cleanup_deadline - time.monotonic()))
        if io_error.is_set() or any(thread.is_alive() for thread in threads):
            returncode = 1
        return ProcessResult(returncode if returncode is not None else 1,
                             output.decode("utf-8", errors="replace"), timed_out,
                             overflow.is_set(), quiescent)
    finally:
        # A dead owner closes the same noninherited handle in the OS; the job
        # kills descendants even when Python finally blocks cannot execute.
        job.close()
        for handle in members:
            job.kernel.CloseHandle(handle)
        if process is not None:
            for pipe in (process.stdin, process.stdout):
                if pipe is not None and not any(thread.is_alive() for thread in threads):
                    pipe.close()


def start_leased_guardian(command: list[str], lease_authority, *, timeout_seconds=30,
                         cwd=None, env=None, stdin_text=None, stream_events=False, deadline=None) -> subprocess.Popen:
    """Stage a guardian holding a duplicate lease outside its executor job.

    This prerequisite does not admit production reclamation. The caller must
    preserve the generation unless a separately verified completion record and
    protected inventory establish safe reclamation.
    """
    import msvcrt
    from .windows_storage import BoundDirectory

    if not all(hasattr(lease_authority, name) for name in ("generation", "fileno", "identity", "is_open", "path")):
        raise ValueError("A live generation lease authority is required")
    identity = f"{lease_authority.generation}:{os.fstat(lease_authority.fileno()).st_dev}:{os.fstat(lease_authority.fileno()).st_ino}"
    if identity != lease_authority.identity or not lease_authority.is_open():
        raise ValueError("Lease identity changed before guardian admission")
    marker = lease_authority.path.with_name(lease_authority.path.name + ".supervision")
    request = {"command": command, "timeout": timeout_seconds, "identity": identity,
               "generation": lease_authority.generation, "marker": str(marker), "nonce": uuid.uuid4().hex,
               "stdin": stdin_text, "stream_events": stream_events,
               "deadline": deadline if deadline is not None else time.monotonic() + timeout_seconds if timeout_seconds is not None else None}
    payload = json.dumps(request).encode() + b"\n"
    if len(payload) > 1048576:
        raise ValueError("Guardian request exceeds byte limit")
    with BoundDirectory(marker, create_private=True, deadline=request["deadline"]) as bound:
        try:
            previous = json.loads(bound.read_record("pending.json"))
        except FileNotFoundError:
            previous = None
        if previous is not None:
            complete = json.loads(bound.read_record("complete.json"))
            if complete != {**previous, "quiescent": True}:
                raise ValueError("Previous guardian did not prove quiescence")
        bound.create_record("pending.json", json.dumps({"identity": identity, "nonce": request["nonce"]}).encode(), replace=previous is not None)
    if request["deadline"] is not None and time.monotonic() >= request["deadline"]:
        raise TimeoutError("Guardian admission deadline expired")
    kernel = _kernel()
    current = kernel.GetCurrentProcess()
    lease = wintypes.HANDLE()
    parent = wintypes.HANDLE()
    try:
        if not kernel.DuplicateHandle(current, msvcrt.get_osfhandle(lease_authority.fileno()), current, ctypes.byref(lease), 0, True, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.DuplicateHandle(current, current, current, ctypes.byref(parent), 0x00100000, True, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": [lease.value, parent.value]}
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(Path(__file__).resolve()), "--leased-guardian", str(lease.value), str(parent.value)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True, startupinfo=startup, cwd=cwd, env=env,
        )
        # The bounded setup request is drained by a dedicated writer so a failed
        # guardian cannot block the caller while the guardian watches parent death.
        def send():
            try:
                process.stdin.write(payload)
                process.stdin.flush()
                if not stream_events:
                    process.stdin.close()
            except (OSError, ValueError):
                pass
        threading.Thread(target=send, daemon=True).start()
        return process
    finally:
        if lease:
            kernel.CloseHandle(lease)
        if parent:
            kernel.CloseHandle(parent)


def _guardian_main(lease_handle: int, parent_handle: int):
    import msvcrt
    BoundDirectory = runpy.run_path(str(Path(__file__).with_name("windows_storage.py")))["BoundDirectory"]
    kernel = _kernel()
    lease_fd = msvcrt.open_osfhandle(lease_handle, os.O_RDWR | os.O_BINARY | os.O_NOINHERIT)
    cancel = threading.Event()
    stopped = threading.Event()
    cancel_reader = None
    def watch_parent():
        while not stopped.is_set():
            if kernel.WaitForSingleObject(parent_handle, 50) != 0x102:
                cancel.set()
                return
    try:
        admission = sys.stdin.buffer.readline(1048577)
        if not admission.endswith(b"\n") or len(admission) > 1048576:
            return 2
        request = json.loads(admission)
        identity = f"{request['generation']}:{os.fstat(lease_fd).st_dev}:{os.fstat(lease_fd).st_ino}"
        if identity != request["identity"]:
            return 2
        threading.Thread(target=watch_parent, daemon=True).start()
        if request.get("stream_events"):
            def watch_cancel():
                if sys.stdin.buffer.readline(16) == b"cancel\n":
                    cancel.set()
            cancel_reader = threading.Thread(target=watch_cancel, daemon=True)
            cancel_reader.start()
        with BoundDirectory(Path(request["marker"]), create_private=True, deadline=request.get("deadline")) as bound:
            def emit(kind, value):
                print(json.dumps({"kind": kind, "value": value}), flush=True)
            def output(chunk):
                import base64
                emit("output", base64.b64encode(chunk).decode("ascii"))
            remaining = request["deadline"] - time.monotonic() if request.get("deadline") is not None else None
            result = run_owned(request["command"], stdin_text=request.get("stdin"),
                               timeout_seconds=remaining, cancel=cancel,
                               on_started=(lambda pid: emit("started", pid)) if request.get("stream_events") else None,
                               on_output=output if request.get("stream_events") else None)
            if result.quiescent:
                bound.create_record("complete.json", json.dumps({"identity": identity, "nonce": request["nonce"], "quiescent": True}).encode(), replace=True)
        if request.get("stream_events"):
            emit("result", asdict(result))
        else:
            print(json.dumps(asdict(result)), flush=True)
        return 0 if result.quiescent else 1
    finally:
        stopped.set()
        if cancel_reader is not None:
            cancel_reader.join(timeout=1)
        kernel.CloseHandle(parent_handle)
        os.close(lease_fd)


def run_leased(command, *, lease_authority, stdin_text=None, cwd=None, env=None,
               timeout_seconds=None, on_started=None, on_output=None, on_tick=None, cancel=None):
    """Consume the guardian's bounded events without taking custody of its job."""
    import base64
    import queue
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else float("inf")
    process = start_leased_guardian(command, lease_authority, stdin_text=stdin_text,
                                    timeout_seconds=timeout_seconds, cwd=cwd, env=env,
                                    stream_events=True, deadline=deadline if timeout_seconds is not None else None)
    events = queue.Queue()
    def read():
        try:
            while line := process.stdout.readline(1500000):
                if not line.endswith(b"\n"):
                    raise ValueError("Guardian event exceeds byte limit")
                events.put(json.loads(line))
        except Exception:
            events.put({"kind": "invalid"})
        finally:
            events.put(None)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    result = None
    cancelled = False
    try:
        while time.monotonic() < deadline:
            if on_tick:
                on_tick()
            if cancel is not None and cancel.is_set() and not cancelled:
                process.stdin.write(b"cancel\n")
                process.stdin.flush()
                cancelled = True
            try:
                event = events.get(timeout=0.01)
            except queue.Empty:
                continue
            if event is None:
                break
            if event["kind"] == "started" and on_started:
                on_started(event["value"])
            elif event["kind"] == "output" and on_output:
                on_output(base64.b64decode(event["value"], validate=True))
            elif event["kind"] == "result":
                result = ProcessResult(**event["value"])
                process.stdin.close()
                break
            elif event["kind"] == "invalid":
                raise ValueError("Invalid guardian event")
        if result is None:
            raise TimeoutError("Guardian completion was not confirmed")
        process.wait(timeout=min(5, max(0.001, deadline - time.monotonic())))
        if process.returncode != 0 or not result.quiescent:
            raise ValueError("Guardian did not confirm cleanup")
        return result
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=5)
        if not reader.is_alive():
            process.stdout.close()
        process.stderr.close()
        process.stdin.close()


def _admitted_child():
    admission = sys.stdin.buffer.readline(1048577)
    if not admission.endswith(b"\n") or len(admission) > 1048576:
        raise SystemExit(2)
    request = json.loads(admission)
    # The prompt goes to the executor as UTF-8 whatever the host code page is (this
    # isolated child does not inherit PYTHONUTF8). It is written as bytes: a text-mode
    # pipe on Windows turns each "\n" into "\r\n", so the executor would not receive
    # the resolved payload byte for byte (agent-harness#2092).
    stdin_text = request["stdin"]
    completed = subprocess.run(request["command"],
                               input=None if stdin_text is None else stdin_text.encode("utf-8"),
                               stdin=subprocess.DEVNULL if stdin_text is None else None,
                               check=False, close_fds=True)
    return completed.returncode


if __name__ == "__main__":
    if sys.argv[1:] == ["--admitted-child"]:
        raise SystemExit(_admitted_child())
    if len(sys.argv) == 4 and sys.argv[1] == "--leased-guardian":
        raise SystemExit(_guardian_main(int(sys.argv[2]), int(sys.argv[3])))
    raise SystemExit(2)
