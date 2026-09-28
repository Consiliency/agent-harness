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
    assert argv[:4] == [sys.executable, "-I", "-S", str(supervisor_script.resolve())]
    assert Path(launcher._LEASE_SUPERVISOR_SCRIPT) == supervisor_script.resolve()
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


def _supervisor_with_prelude(monkeypatch, *prelude: str) -> None:
    """Run the real supervisor file, with ``prelude`` executed in its process first.

    Failure injection without a production test hook: the supervisor module is
    loaded from its path and ``main`` runs after the prelude has patched it.
    """
    real_command = launcher._lease_supervisor_command
    script = str(launcher._LEASE_SUPERVISOR_SCRIPT)

    def command(executor_command, lease_fd, status_fd):
        argv = real_command(executor_command, lease_fd, status_fd)
        index = argv.index(script)
        code = "\n".join((
            "import errno, importlib.util, os, sys",
            f"spec = importlib.util.spec_from_file_location('lease_supervisor', {script!r})",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            *prelude,
            "module.main(sys.argv[1:])",
        ))
        return [*argv[:index], "-c", code, *argv[index + 1 :]]

    monkeypatch.setattr(launcher, "_lease_supervisor_command", command)


_FAILING_FORK = (
    "def failing_fork():",
    "    raise BlockingIOError(errno.EAGAIN, os.strerror(errno.EAGAIN))",
    "os.fork = failing_fork",
)


@pytest.mark.parametrize(
    ("prelude", "reason"),
    [
        pytest.param(_FAILING_FORK, "setup:EAGAIN", id="fork-EAGAIN"),
        pytest.param(
            (
                "def no_proc():",
                "    raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), '/proc/self/environ')",
                "module._initial_environment = no_proc",
            ),
            "setup:ENOENT",
            id="no-proc-environ",
        ),
        pytest.param(
            (
                "def failing_setsid():",
                "    raise PermissionError(errno.EPERM, os.strerror(errno.EPERM))",
                "os.setsid = failing_setsid",
            ),
            "setup:EPERM",
            id="executor-setsid-EPERM",
        ),
        pytest.param(("os._exit(3)",), None, id="silent-death-before-fork"),
    ],
)
def test_supervisor_setup_failure_raises_like_a_failing_preexec_fn(monkeypatch, lease_fd, tmp_path, prelude, reason):
    # The old preexec path raised this from Popen for any exception before the
    # executor's exec; an executor that never ran must not look like an exit code.
    _supervisor_with_prelude(monkeypatch, *prelude)
    ran = tmp_path / "executor-ran"
    with pytest.raises(subprocess.SubprocessError, match=r"^Exception occurred in preexec_fn\.$") as caught:
        _launch_supervised(["/bin/sh", "-c", 'touch "$0"', str(ran)], lease_fd, tmp_path)
    assert not ran.exists(), "the executor ran although setup failed"
    if reason is None:
        # Nothing reported: caught by the launcher's nonzero-exit-without-release check.
        assert caught.value.__cause__ is None
    else:
        assert str(caught.value.__cause__) == f"lease supervisor {reason}"


@pytest.mark.skipif(os.geteuid() == 0, reason="RLIMIT_NPROC is not enforced for root")
def test_real_rlimit_nproc_eagain_on_the_executor_fork_raises(monkeypatch, lease_fd, tmp_path):
    _supervisor_with_prelude(monkeypatch, "import resource", "resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))")
    ran = tmp_path / "executor-ran"
    with pytest.raises(subprocess.SubprocessError, match=r"^Exception occurred in preexec_fn\.$") as caught:
        _launch_supervised(["/bin/sh", "-c", 'touch "$0"', str(ran)], lease_fd, tmp_path)
    assert not ran.exists()
    assert str(caught.value.__cause__) == "lease supervisor setup:EAGAIN"


def test_supervisor_runs_no_site_startup_hooks(monkeypatch, lease_fd, tmp_path):
    # A .pth or sitecustomize hook could start a thread before the supervisor's
    # own fork; -S keeps site initialization out of the supervisor entirely.
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=120)
    python = venv / "bin" / "python"
    purelib = Path(
        subprocess.run(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            check=True, capture_output=True, text=True, timeout=60,
        ).stdout.strip()
    )
    pth_marker, customize_marker = tmp_path / "pth-ran", tmp_path / "sitecustomize-ran"
    (purelib / "startup_hook.pth").write_text(f"import pathlib; pathlib.Path({str(pth_marker)!r}).touch()\n", encoding="utf-8")
    (purelib / "sitecustomize.py").write_text(f"import pathlib\npathlib.Path({str(customize_marker)!r}).touch()\n", encoding="utf-8")

    subprocess.run([str(python), "-I", "-c", "pass"], check=True, timeout=60)
    assert pth_marker.exists(), "control: a .pth hook runs under -I alone"
    # A distribution's own sitecustomize (Debian ships one in the stdlib dir)
    # shadows ours; check ours only where the control shows it is reachable.
    customize_reachable = customize_marker.exists()
    for marker in (pth_marker, customize_marker):
        marker.unlink(missing_ok=True)

    monkeypatch.setattr(sys, "executable", str(python))
    assert _launch_supervised(["/bin/true"], lease_fd, tmp_path).returncode == 0
    assert not pth_marker.exists(), "a .pth startup hook ran in the supervisor"
    if customize_reachable:
        assert not customize_marker.exists(), "sitecustomize ran in the supervisor"


def test_supervisor_does_not_leak_interpreter_locale_coercion(lease_fd, tmp_path):
    env = {"PATH": "/usr/bin:/bin"}
    probe = subprocess.run(
        [sys.executable, "-I", "-S", "-c", "import os; print(os.environ.get('LC_CTYPE', ''))"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    if not probe.stdout.strip():
        pytest.skip("this interpreter does not coerce LC_CTYPE here (no C.UTF-8 locale), so there is nothing to leak")
    result = _launch_supervised(["/bin/sh", "-c", "tr '\\0' '\\n' < /proc/$$/environ"], lease_fd, tmp_path, env=env)
    assert result.returncode == 0
    assert "LC_CTYPE=" not in result.output, result.output


def _processes_mentioning(token: str) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if token.encode() in (entry / "cmdline").read_bytes():
                found.append(int(entry.name))
        except OSError:
            continue
    return found


@pytest.mark.parametrize(
    ("signum", "pause"),
    [(signal.SIGKILL, "before"), (signal.SIGTERM, "before"), (signal.SIGTERM, "after")],
    ids=["SIGKILL-before-release", "SIGTERM-before-release", "SIGTERM-after-release"],
)
def test_supervisor_death_around_release_never_leaves_an_executor(monkeypatch, lease_fd, tmp_path, signum, pause):
    # The supervisor is paused just before (or just after) it releases the forked
    # child to exec, and is then signalled.  Before release, the launch must fail
    # and nothing may have run: the child reads EOF (SIGKILL) or is terminated by
    # the already-installed forwarding (SIGTERM).  After release, SIGTERM must be
    # forwarded, so no executor-side process may outlive the launch either way.
    pause_file, resume_file = tmp_path / "supervisor-paused", tmp_path / "supervisor-resume"
    wait_lines = (
        f"        open({str(pause_file)!r}, 'w').write(str(os.getpid()))",
        "        deadline = time.monotonic() + 60",
        f"        while not os.path.exists({str(resume_file)!r}) and time.monotonic() < deadline:",
        "            time.sleep(0.01)",
    )
    if pause == "before":
        body = ("    if data == module._GO:", *wait_lines, "    return real_write(fd, data)")
    else:
        body = ("    written = real_write(fd, data)", "    if data == module._GO:", *wait_lines, "    return written")
    _supervisor_with_prelude(
        monkeypatch, "import time", "real_write = os.write", "def paused_write(fd, data):", *body, "os.write = paused_write"
    )
    token = f"phase-loop-release-probe-{os.getpid()}-{int(signum)}-{pause}"
    ran = tmp_path / "executor-ran"
    # A loop, not a final ``sleep``: the shell must not exec away the token.
    launched = _BackgroundLaunch(["/bin/sh", "-c", 'touch "$0"; while :; do sleep 1; done', str(ran), token], lease_fd, tmp_path)
    deadline = time.monotonic() + 15
    while not pause_file.exists() or not pause_file.read_text():
        assert "error" not in launched.outcome, launched.outcome.get("error")
        assert time.monotonic() < deadline, "supervisor never reached the release point"
        time.sleep(0.01)
    supervisor_pid = int(pause_file.read_text())
    try:
        os.kill(supervisor_pid, signum)
        if signum == signal.SIGTERM:
            time.sleep(0.2)
    finally:
        resume_file.write_text("resume")
    launched.thread.join(20)
    assert not launched.thread.is_alive(), "launch did not return after the supervisor was signalled"
    deadline = time.monotonic() + 5
    while _processes_mentioning(token):
        assert time.monotonic() < deadline, f"executor-side process left running: {_processes_mentioning(token)}"
        time.sleep(0.02)
    error = launched.outcome.get("error")
    if pause == "before":
        assert isinstance(error, subprocess.SubprocessError), launched.outcome
        assert str(error) == "Exception occurred in preexec_fn."
        time.sleep(0.3)
        assert not ran.exists(), "the executor ran although the supervisor died before releasing it"
    else:
        # Released: the executor may or may not have reached exec before the
        # forwarded SIGTERM; either outcome is a clean, fully reaped launch.
        assert error is None or isinstance(error, subprocess.SubprocessError), launched.outcome


def test_silent_supervisor_death_with_stdin_raises_the_launch_error(monkeypatch, lease_fd, tmp_path):
    # With no record the launcher settles the dead supervisor before feeding it
    # stdin, so the caller sees the launch failure, not a BrokenPipeError.
    _supervisor_with_prelude(monkeypatch, "os._exit(3)")
    with pytest.raises(subprocess.SubprocessError, match=r"^Exception occurred in preexec_fn\.$"):
        _launch_supervised(["/bin/cat"], lease_fd, tmp_path, stdin_text="x" * 262144)


def _open_fds() -> set[str]:
    return set(os.listdir("/proc/self/fd"))


@pytest.mark.parametrize("failure", ["popen-raises", "exec-fails", "setup-fails", "silent-death"])
def test_failed_launches_do_not_leak_descriptors(monkeypatch, lease_fd, tmp_path, failure):
    # Every failure path closes both ends of the status pipe (the go-pipe lives
    # only in the supervisor and its child, which are gone).  Count across N.
    command, kwargs, expected = ["/bin/true"], {}, subprocess.SubprocessError
    if failure == "popen-raises":
        kwargs, expected = {"cwd": tmp_path / "no-such-cwd"}, FileNotFoundError
    elif failure == "exec-fails":
        command, expected = [str(tmp_path / "no-such-executor")], FileNotFoundError
    elif failure == "setup-fails":
        _supervisor_with_prelude(monkeypatch, *_FAILING_FORK)
    else:
        _supervisor_with_prelude(monkeypatch, "os._exit(3)")
    with pytest.raises(expected):
        _launch_supervised(command, lease_fd, tmp_path / "warm-up", **kwargs)
    before = _open_fds()
    for index in range(20):
        with pytest.raises(expected):
            _launch_supervised(command, lease_fd, tmp_path / f"run-{index}", **kwargs)
    leaked = _open_fds() - before
    assert not leaked, {fd: os.readlink(f"/proc/self/fd/{fd}") for fd in leaked if os.path.exists(f"/proc/self/fd/{fd}")}



def _pause_prelude(pause_file: Path, resume_file: Path, pid_expr: str = "os.getpid()") -> tuple[str, ...]:
    return (
        f"    open({str(pause_file)!r}, 'w').write(str({pid_expr}))",
        "    deadline = time.monotonic() + 60",
        f"    while not os.path.exists({str(resume_file)!r}) and time.monotonic() < deadline:",
        "        time.sleep(0.01)",
    )


def _wait_for_pid(pause_file: Path, launched: _BackgroundLaunch) -> int:
    deadline = time.monotonic() + 15
    while not pause_file.exists() or not pause_file.read_text():
        assert "error" not in launched.outcome, launched.outcome.get("error")
        assert time.monotonic() < deadline, "supervisor never reached the pause point"
        time.sleep(0.01)
    return int(pause_file.read_text())


def _children(pid: int) -> list[int]:
    return [child for child in (int(entry.name) for entry in Path("/proc").iterdir() if entry.name.isdigit()) if _ppid(child) == pid]


def _stat_fields(pid: int) -> list[str]:
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()


def test_executor_child_is_a_group_leader_before_it_is_released(monkeypatch, lease_fd, tmp_path):
    # killpg(executor_pid) is the only forwarding target, so the child must own
    # that group before release (and before any forwarding can happen).
    pause_file, resume_file = tmp_path / "paused", tmp_path / "resume"
    _supervisor_with_prelude(
        monkeypatch, "import time", "real_write = os.write", "def paused_write(fd, data):",
        "  if data == module._GO:", *("  " + line for line in _pause_prelude(pause_file, resume_file)),
        "  return real_write(fd, data)", "os.write = paused_write",
    )
    launched = _BackgroundLaunch(["/bin/true"], lease_fd, tmp_path)
    try:
        supervisor_pid = _wait_for_pid(pause_file, launched)
        (child,) = _children(supervisor_pid)
        fields = _stat_fields(child)
        assert int(fields[2]) == child, "child is not its own process-group leader before release"
        assert int(fields[3]) == child, "child is not its own session leader before release"
    finally:
        resume_file.write_text("resume")
    assert launched.result(timeout=15).returncode == 0


@pytest.mark.parametrize("signum", [signal.SIGKILL, signal.SIGTERM], ids=["SIGKILL", "SIGTERM"])
def test_supervisor_death_before_grouped_leaves_no_executor(monkeypatch, lease_fd, tmp_path, signum):
    # The child is held before its setsid (so before ``grouped``) while the
    # supervisor waits for ``grouped``; the supervisor is killed, then the child
    # continues and must find the supervisor gone and never exec.
    pause_file, resume_file = tmp_path / "paused", tmp_path / "resume"
    _supervisor_with_prelude(
        monkeypatch, "import time", "real_setsid = os.setsid", "def paused_setsid():",
        *_pause_prelude(pause_file, resume_file, "os.getppid()"), "    return real_setsid()", "os.setsid = paused_setsid",
    )
    token = f"phase-loop-grouped-probe-{os.getpid()}-{int(signum)}"
    ran = tmp_path / "executor-ran"
    launched = _BackgroundLaunch(["/bin/sh", "-c", 'touch "$0"; while :; do sleep 1; done', str(ran), token], lease_fd, tmp_path)
    try:
        os.kill(_wait_for_pid(pause_file, launched), signum)
        time.sleep(0.2)
    finally:
        resume_file.write_text("resume")
    launched.thread.join(20)
    assert not launched.thread.is_alive()
    assert isinstance(launched.outcome.get("error"), subprocess.SubprocessError), launched.outcome
    deadline = time.monotonic() + 5
    while _processes_mentioning(token):
        assert time.monotonic() < deadline, _processes_mentioning(token)
        time.sleep(0.02)
    time.sleep(0.3)
    assert not ran.exists(), "the executor ran although the supervisor died before it was grouped"


def test_forwarding_never_signals_a_bare_pid_after_the_executor_is_reaped(monkeypatch, lease_fd, tmp_path):
    # Pid-reuse regression: once the executor is reaped (the supervisor stays in
    # its reap grace for a session-detached orphan), a forwarded SIGTERM and its
    # SIGKILL escalation may only target the executor's process group.
    signal_log, marker = tmp_path / "signals.log", tmp_path / "marker.json"
    _supervisor_with_prelude(
        monkeypatch, "real_kill, real_killpg = os.kill, os.killpg",
        "def record(kind, target, signum):",
        f"    with open({str(signal_log)!r}, 'a') as log: log.write(f'{{kind}} {{target}} {{int(signum)}}\\n')",
        "def spy_kill(pid, signum):", "    record('kill', pid, signum)", "    return real_kill(pid, signum)",
        "def spy_killpg(pgid, signum):", "    record('killpg', pgid, signum)", "    return real_killpg(pgid, signum)",
        "os.kill, os.killpg = spy_kill, spy_killpg",
    )
    command = _python(
        """
        import json, os, subprocess, sys
        orphan = subprocess.Popen([sys.executable, "-c", "import time\\nwhile True: time.sleep(0.1)"],
                                  start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        open(sys.argv[1], "w").write(json.dumps({"pid": os.getpid(), "ppid": os.getppid(), "orphan": orphan.pid}))
        """,
        str(marker),
    )
    launched = _BackgroundLaunch(command, lease_fd, tmp_path)
    observed = _wait_for_json(marker, launched)
    deadline = time.monotonic() + 5
    while _alive(observed["pid"]):
        assert time.monotonic() < deadline, "executor did not exit"
        time.sleep(0.01)
    os.kill(observed["ppid"], signal.SIGTERM)
    result = launched.result(timeout=20)
    assert not _alive(observed["orphan"])
    entries = signal_log.read_text().splitlines()
    assert f"killpg {observed['pid']} {int(signal.SIGTERM)}" in entries, entries
    assert f"killpg {observed['pid']} {int(signal.SIGKILL)}" in entries, entries
    assert not [entry for entry in entries if entry.startswith("kill ")], entries
    assert result.returncode == 0


def test_termination_before_release_withholds_go_even_when_the_child_ignores_sigterm(monkeypatch, lease_fd, tmp_path):
    # Pins the ``terminated`` flag itself: the child ignores SIGTERM, so the
    # forwarded signal cannot stop it; only withholding GO keeps it from exec.
    pause_file, resume_file = tmp_path / "paused", tmp_path / "resume"
    _supervisor_with_prelude(
        monkeypatch, "import signal, time", "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
        "real_sigmask = signal.pthread_sigmask", "def paused_sigmask(how, mask):",
        "  if how == signal.SIG_BLOCK:", *("  " + line for line in _pause_prelude(pause_file, resume_file)),
        "  return real_sigmask(how, mask)", "signal.pthread_sigmask = paused_sigmask",
    )
    token = f"phase-loop-terminated-probe-{os.getpid()}"
    ran = tmp_path / "executor-ran"
    launched = _BackgroundLaunch(["/bin/sh", "-c", 'touch "$0"; while :; do sleep 1; done', str(ran), token], lease_fd, tmp_path)
    try:
        os.kill(_wait_for_pid(pause_file, launched), signal.SIGTERM)
        time.sleep(0.2)
    finally:
        resume_file.write_text("resume")
    launched.thread.join(20)
    assert not launched.thread.is_alive()
    assert isinstance(launched.outcome.get("error"), subprocess.SubprocessError), launched.outcome
    deadline = time.monotonic() + 5
    while _processes_mentioning(token):
        assert time.monotonic() < deadline, _processes_mentioning(token)
        time.sleep(0.02)
    assert not ran.exists(), "GO was released after a termination request"


def test_silent_death_after_the_early_settle_is_caught_at_exit(monkeypatch, lease_fd, tmp_path):
    # Pins the exit-time check on its own: the status pipe closes, the early
    # settle times out, and only then does the supervisor die unreported.
    _supervisor_with_prelude(monkeypatch, "import time", "os.close(int(sys.argv[4]))", "time.sleep(1.5)", "os._exit(3)")
    with pytest.raises(subprocess.SubprocessError, match=r"^Exception occurred in preexec_fn\.$"):
        _launch_supervised(["/bin/true"], lease_fd, tmp_path)
