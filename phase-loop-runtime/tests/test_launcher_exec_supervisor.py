"""Real-launch supervision through the exec'd lease supervisor (agent-harness#1140).

The lease supervisor used to run as Python inside ``preexec_fn``, between fork
and exec in a child of the (threaded) launcher.  It is now its own program.
These tests launch real executors through ``launch(..., lease_authority=...)``
and observe, from outside, every guarantee the old path gave: the executor's
session, subreaper mode, signal forwarding with SIGKILL escalation, orphan
reaping, exit-code mapping, and the executor's exact env, cwd, descriptors and
signal dispositions.
"""

from __future__ import annotations

import ast
import errno
import fcntl
import io
import json
import logging
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from phase_loop_runtime import launcher
from phase_loop_runtime.launcher import launch

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="lease supervision relies on prctl and /proc"
)

# Held almost continuously by busy threads in the no-hang test.  Module-level so
# a named mutation can make the launch path need it in a forked child.
_BUSY_LOCK = threading.Lock()


class _Lease:
    generation = "exec-supervisor-test"

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        return self._fd


@pytest.fixture
def lease_fd(tmp_path):
    fd = os.open(tmp_path / "lease.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    yield fd
    os.close(fd)


def _launch_supervised(command, lease_fd, tmp_path, **kwargs):
    return launch(
        command,
        lease_authority=_Lease(lease_fd),
        log_path=tmp_path / "executor.log",
        heartbeat_interval_seconds=30,
        **kwargs,
    )


class _BackgroundLaunch:
    def __init__(self, command, lease_fd, tmp_path, **kwargs) -> None:
        self.outcome: dict = {}
        self.thread = threading.Thread(target=self._run, args=(command, lease_fd, tmp_path), kwargs=kwargs, daemon=True)
        self.thread.start()

    def _run(self, command, lease_fd, tmp_path, **kwargs) -> None:
        try:
            self.outcome["result"] = _launch_supervised(command, lease_fd, tmp_path, **kwargs)
        except BaseException as exc:
            self.outcome["error"] = exc

    def result(self, timeout: float):
        self.thread.join(timeout)
        assert not self.thread.is_alive(), f"supervised launch did not return within {timeout}s"
        assert "error" not in self.outcome, self.outcome.get("error")
        return self.outcome["result"]


def _wait_for_json(path: Path, launched: _BackgroundLaunch, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert "error" not in launched.outcome, launched.outcome.get("error")
        assert time.monotonic() < deadline, f"executor never wrote {path.name}"
        time.sleep(0.02)
    time.sleep(0.05)
    return json.loads(path.read_text(encoding="utf-8"))


def _alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def _ppid(pid: int) -> int | None:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def _python(source: str, *args: str) -> list[str]:
    return [sys.executable, "-c", textwrap.dedent(source), *args]


def test_lease_launch_execs_the_supervisor_program_without_preexec_fn(monkeypatch, lease_fd, tmp_path):
    spawns = []
    real_popen = launcher.subprocess.Popen

    def spy(*args, **kwargs):
        spawns.append((list(args[0]), dict(kwargs)))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(launcher.subprocess, "Popen", spy)
    command = [sys.executable, "-c", "pass"]
    result = _launch_supervised(command, lease_fd, tmp_path)

    assert result.returncode == 0
    assert result.command == command
    assert all(kwargs.get("preexec_fn") is None for _argv, kwargs in spawns), (
        "no Python may run between fork and exec on the executor launch path"
    )
    supervised = [(argv, kwargs) for argv, kwargs in spawns if str(launcher._LEASE_SUPERVISOR_SCRIPT) in argv]
    assert len(supervised) == 1
    argv, kwargs = supervised[0]
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True
    assert lease_fd in kwargs["pass_fds"]
    supervisor_script = Path(launcher.__file__).with_name("lease_supervisor.py")
    assert argv[:3] == [sys.executable, "-I", str(supervisor_script)]
    assert Path(launcher._LEASE_SUPERVISOR_SCRIPT) == supervisor_script
    assert argv[argv.index("--") + 1 :] == command


def test_supervisor_program_imports_only_the_standard_library():
    # ``-I`` drops PYTHONPATH: a package import here would bind to whichever copy
    # is installed, not the one that launched the supervisor.
    tree = ast.parse(Path(launcher._LEASE_SUPERVISOR_SCRIPT).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in the exec'd supervisor"
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
    assert imported
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported - set(sys.stdlib_module_names)


def test_lease_launch_does_not_hang_while_threads_hold_locks(lease_fd, tmp_path):
    stop = threading.Event()
    logger = logging.getLogger("phase_loop_runtime.tests.exec_supervisor.busy")
    handler = logging.StreamHandler(io.StringIO())
    logger.addHandler(handler)
    logger.propagate = False

    def hold_lock():
        while not stop.is_set():
            with _BUSY_LOCK:
                time.sleep(0.002)

    def log_busily():
        while not stop.is_set():
            logger.warning("busy %s", "x" * 64)

    busy = [threading.Thread(target=target, daemon=True) for target in (hold_lock, hold_lock, log_busily, log_busily)]
    for thread in busy:
        thread.start()
    returncodes = []

    def launch_repeatedly():
        for index in range(5):
            returncodes.append(_launch_supervised(["/bin/true"], lease_fd, tmp_path / f"run-{index}").returncode)

    try:
        launcher_thread = threading.Thread(target=launch_repeatedly, daemon=True)
        launcher_thread.start()
        launcher_thread.join(60)
        assert not launcher_thread.is_alive(), "a supervised launch hung while other threads held locks"
        assert returncodes == [0] * 5
    finally:
        stop.set()
        for thread in busy:
            thread.join(5)
        logger.removeHandler(handler)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
def test_supervisor_forwards_sigterm_to_the_executor_process_group(lease_fd, tmp_path, signum):
    marker = tmp_path / "marker.json"
    command = _python(
        """
        import json, os, signal, subprocess, sys, time
        from pathlib import Path
        marker = Path(sys.argv[1])
        peer = subprocess.Popen([sys.executable, "-c",
            "import os, signal, sys, time\\n"
            "from pathlib import Path\\n"
            "def on_term(signum, frame):\\n"
            "    Path(sys.argv[1]).write_text(str(signum)); os._exit(0)\\n"
            "signal.signal(signal.SIGTERM, on_term)\\n"
            "Path(sys.argv[2]).write_text('ready')\\n"
            "time.sleep(60)\\n",
            str(marker.with_suffix('.peer')), str(marker.with_suffix('.peer-ready'))])
        def on_term(signum, frame):
            marker.with_suffix('.executor').write_text(str(signum))
            peer.wait()
            os._exit(7)
        signal.signal(signal.SIGTERM, on_term)
        while not marker.with_suffix('.peer-ready').exists():
            time.sleep(0.01)
        marker.write_text(json.dumps({"pid": os.getpid(), "ppid": os.getppid(), "peer_pid": peer.pid}))
        time.sleep(60)
        """,
        str(marker),
    )
    launched = _BackgroundLaunch(command, lease_fd, tmp_path)
    observed = _wait_for_json(marker, launched)

    os.kill(observed["ppid"], signum)
    result = launched.result(timeout=15)

    assert result.process_pid == observed["ppid"], "executor is not the supervisor's direct child"
    assert marker.with_suffix(".executor").read_text() == str(int(signal.SIGTERM))
    assert marker.with_suffix(".peer").read_text() == str(int(signal.SIGTERM)), "SIGTERM missed the executor's process group"
    assert result.returncode == 7


def test_supervisor_escalates_to_sigkill_one_second_after_forwarding(lease_fd, tmp_path):
    marker = tmp_path / "marker.json"
    command = _python(
        """
        import json, os, signal, sys, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        open(sys.argv[1], "w").write(json.dumps({"pid": os.getpid(), "ppid": os.getppid()}))
        time.sleep(60)
        """,
        str(marker),
    )
    launched = _BackgroundLaunch(command, lease_fd, tmp_path)
    observed = _wait_for_json(marker, launched)

    sent = time.monotonic()
    os.kill(observed["ppid"], signal.SIGTERM)
    while _alive(observed["pid"]):
        assert time.monotonic() - sent < 10, "SIGTERM-ignoring executor was never killed"
        time.sleep(0.01)
    killed_after = time.monotonic() - sent
    result = launched.result(timeout=15)

    assert 0.8 <= killed_after < 5, killed_after
    assert result.returncode == 1, "a signal death must map to exit code 1"


def test_supervisor_reaps_session_detached_orphans_after_the_grace(lease_fd, tmp_path):
    marker = tmp_path / "marker.json"
    command = _python(
        """
        import ctypes, json, os, subprocess, sys, time
        from pathlib import Path
        marker = Path(sys.argv[1])
        subreaper = ctypes.c_int()
        ctypes.CDLL(None).prctl(37, ctypes.byref(subreaper), 0, 0, 0)  # PR_GET_CHILD_SUBREAPER
        orphan = subprocess.Popen([sys.executable, "-c",
            "import os, signal, sys, time\\n"
            "from pathlib import Path\\n"
            "os.setsid()\\n"
            "def on_term(signum, frame):\\n"
            "    Path(sys.argv[1]).write_text(repr(time.time())); os._exit(0)\\n"
            "signal.signal(signal.SIGTERM, on_term)\\n"
            "Path(sys.argv[2]).write_text('ready')\\n"
            "time.sleep(60)\\n",
            str(marker.with_suffix('.orphan-term')), str(marker.with_suffix('.orphan-ready'))])
        while not marker.with_suffix('.orphan-ready').exists():
            time.sleep(0.01)
        marker.write_text(json.dumps({
            "pid": os.getpid(), "ppid": os.getppid(), "orphan_pid": orphan.pid,
            "sid": os.getsid(0), "pgid": os.getpgid(0), "subreaper": subreaper.value,
            "exited_at": time.time(),
        }))
        os._exit(0)
        """,
        str(marker),
    )
    launched = _BackgroundLaunch(command, lease_fd, tmp_path)
    observed = _wait_for_json(marker, launched)

    assert observed["sid"] == observed["pid"], "executor is not a session leader"
    assert observed["pgid"] == observed["pid"]
    assert observed["subreaper"] == 1, "executor is not a child subreaper"
    deadline = time.monotonic() + 5
    while _ppid(observed["orphan_pid"]) != observed["ppid"]:
        assert time.monotonic() < deadline, "the supervisor did not adopt the orphan (subreaper)"
        time.sleep(0.01)
    result = launched.result(timeout=20)

    assert result.returncode == 0
    assert not _alive(observed["orphan_pid"]), "launch returned while an adopted orphan was alive"
    terminated_at = float(marker.with_suffix(".orphan-term").read_text())
    assert terminated_at - observed["exited_at"] >= 4.5, "orphans were signalled before the reap grace"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("raise SystemExit(0)", 0),
        ("raise SystemExit(3)", 3),
        ("raise SystemExit(255)", 255),
        ("import os, signal; os.kill(os.getpid(), signal.SIGKILL)", 1),
    ],
    ids=["exit-0", "exit-3", "exit-255", "signal-death"],
)
def test_supervisor_maps_executor_exit_codes(lease_fd, tmp_path, source, expected):
    assert _launch_supervised([sys.executable, "-c", source], lease_fd, tmp_path).returncode == expected


def test_executor_env_cwd_descriptors_and_signals_match_the_popen_handoff(monkeypatch, lease_fd, tmp_path):
    spawns = []
    real_popen = launcher.subprocess.Popen

    def spy(*args, **kwargs):
        if lease_fd in kwargs.get("pass_fds", ()):
            spawns.append(dict(kwargs))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(launcher.subprocess, "Popen", spy)
    workdir = tmp_path / "work"
    workdir.mkdir()
    out = tmp_path / "probe"
    script = (
        # The descriptor listing runs first, to stdout: dash keeps a saved copy
        # of a redirected descriptor (fd 10) open after its first redirection.
        'echo FDS-BEGIN; ls /proc/$$/fd; echo FDS-END; '
        'cat /proc/$$/environ > "$1.environ"; readlink /proc/$$/cwd > "$1.cwd"; '
        'grep -E "^(SigIgn|SigBlk):" /proc/$$/status > "$1.sig"; cut -d" " -f1,5,6 /proc/$$/stat > "$1.stat"; '
        'echo $PPID > "$1.ppid"; while [ ! -e "$1.release" ]; do sleep 0.02; done'
    )
    # No LANG/LC_*: an interpreter in the handoff would coerce LC_CTYPE (PEP 538).
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PHASE_LOOP_EXEC_SUPERVISOR_PROBE": "café ü"}
    launched = _BackgroundLaunch(["/bin/sh", "-c", script, "sh", str(out)], lease_fd, tmp_path, env=env, cwd=workdir)
    try:
        deadline = time.monotonic() + 15
        while not Path(f"{out}.ppid").exists() or not Path(f"{out}.ppid").read_text().strip():
            assert "error" not in launched.outcome, launched.outcome.get("error")
            assert time.monotonic() < deadline, "executor probe never ran"
            time.sleep(0.02)
        supervisor_pid = int(Path(f"{out}.ppid").read_text())
        deadline = time.monotonic() + 5
        while sorted(os.listdir(f"/proc/{supervisor_pid}/fd")) != [str(lease_fd)]:
            assert time.monotonic() < deadline, os.listdir(f"/proc/{supervisor_pid}/fd")
            time.sleep(0.02)
    finally:
        # Release the probe even when an assertion fails, so it never outlives the test.
        Path(f"{out}.release").write_text("release")
    result = launched.result(timeout=15)

    assert result.returncode == 0
    assert result.process_pid == supervisor_pid
    assert len(spawns) == 1
    popen_env = spawns[0]["env"]
    expected_environ = b"".join(os.fsencode(key) + b"=" + os.fsencode(value) + b"\0" for key, value in popen_env.items())
    assert Path(f"{out}.environ").read_bytes() == expected_environ
    assert Path(f"{out}.cwd").read_text().strip() == str(workdir.resolve())
    listed = result.output.split("FDS-BEGIN", 1)[1].split("FDS-END", 1)[0].split()
    assert sorted(listed, key=int) == sorted(["0", "1", "2", str(lease_fd)], key=int)
    pid, pgrp, session = Path(f"{out}.stat").read_text().split()
    assert pid == pgrp == session, "executor is not the leader of its own session"

    def mask(status_text: str, field: str) -> int:
        for line in status_text.splitlines():
            if line.startswith(f"{field}:"):
                return int(line.split()[1], 16)
        raise AssertionError(field)

    probe_status = Path(f"{out}.sig").read_text()
    launcher_ignored = mask(Path("/proc/self/status").read_text(), "SigIgn")
    restored = (1 << (signal.SIGPIPE - 1)) | (1 << (signal.SIGXFSZ - 1))
    assert mask(probe_status, "SigIgn") == launcher_ignored & ~restored
    assert mask(probe_status, "SigBlk") == mask(Path("/proc/thread-self/status").read_text(), "SigBlk")


@pytest.mark.parametrize("case", ["absolute", "path-search", "not-executable"])
def test_executor_exec_failure_raises_like_a_direct_popen(lease_fd, tmp_path, case):
    if case == "absolute":
        command, expected = [str(tmp_path / "no-such-executor")], FileNotFoundError
    elif case == "path-search":
        command, expected = ["phase-loop-exec-supervisor-no-such-executor"], FileNotFoundError
    else:
        target = tmp_path / "not-executable"
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        target.chmod(0o644)
        command, expected = [str(target)], PermissionError
    with pytest.raises(expected) as caught:
        _launch_supervised(command, lease_fd, tmp_path, env={"PATH": "/usr/bin:/bin"})
    assert caught.value.filename == command[0]
    assert caught.value.errno == (errno.ENOENT if expected is FileNotFoundError else errno.EACCES)


def test_supervisor_without_a_passed_lease_still_runs_the_executor(tmp_path):
    # Mirrors the old preexec path: a lease descriptor that was not handed through
    # is not held (and never reaches the executor), but the executor still runs.
    unpassed_fd = os.open(tmp_path / "unpassed.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        read_fd, write_fd = os.pipe()
        try:
            completed = subprocess.run(
                [*launcher._lease_supervisor_command(["/bin/sh", "-c", "ls /proc/$$/fd"], unpassed_fd, write_fd)],
                pass_fds=(), close_fds=True, capture_output=True, text=True, timeout=30,
            )
        finally:
            os.close(write_fd)
            os.close(read_fd)
    finally:
        os.close(unpassed_fd)
    assert completed.returncode == 0, completed.stderr
    assert sorted(completed.stdout.split(), key=int) == ["0", "1", "2"]
