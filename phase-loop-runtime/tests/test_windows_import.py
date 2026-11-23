"""Every ``phase_loop_runtime`` module imports on a simulated native Windows
(agent-harness#2092).

The simulation runs in a fresh interpreter. It imports the stdlib and third-party
modules first, because on a real Windows host they take their own ``win32`` branches.
It then removes the POSIX-only stdlib modules (``fcntl``, ``pwd``, ``termios`` and
others), the POSIX-only ``os``/``signal``/``select`` names, and sets
``os.name == "nt"`` and ``sys.platform == "win32"``. Only then does it import every
module in the package. ``pathlib`` keeps building POSIX paths, and ``msvcrt`` and the
Windows certificate store are stubbed, so the host can run the check.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import phase_loop_runtime

WINDOWS_SIM_PRELUDE = textwrap.dedent(
    """
    import os, select, signal, sys, types
    # Warm the stdlib and third-party modules before the platform names change.
    import asyncio, concurrent.futures, ctypes, errno, getpass, hashlib, http.client
    import json, logging, multiprocessing, pathlib, platform, re, shlex, shutil, socket
    import ssl, subprocess, tempfile, threading, time, typing, urllib.request, uuid, weakref
    for optional in ("pydantic", "yaml", "jsonschema", "rfc8785", "consiliency_contract"):
        try:
            __import__(optional)
        except Exception:
            pass
    for name in [n for n in dir(select) if n.startswith(("POLL", "EPOLL", "KQ"))] + [
            "poll", "epoll", "kqueue", "kevent", "devpoll"]:
        if hasattr(select, name):
            delattr(select, name)
    for module in ("fcntl", "termios", "pty", "tty", "pwd", "grp", "resource", "posix",
                   "syslog", "crypt", "readline"):
        sys.modules[module] = None
    # ``os``: the O_* flags native Windows has, and the POSIX-only names it lacks.
    windows_open_flags = {"O_RDONLY", "O_WRONLY", "O_RDWR", "O_APPEND", "O_CREAT", "O_EXCL",
                          "O_TRUNC", "O_BINARY", "O_TEXT", "O_NOINHERIT", "O_TEMPORARY",
                          "O_SHORT_LIVED", "O_RANDOM", "O_SEQUENTIAL"}
    posix_prefixes = ("EX_", "RTLD_", "ST_", "SCHED_", "POSIX_", "PRIO_", "CLD_", "GRND_",
                      "MFD_", "EFD_", "SPLICE_", "XATTR_", "WCOREDUMP", "WIF", "WEXIT",
                      "WSTOP", "WTERM", "PIDFD_", "P_PID", "P_PGID", "P_ALL", "F_LOCK",
                      "F_TLOCK", "F_ULOCK", "F_TEST", "SEEK_DATA", "SEEK_HOLE", "RWF_",
                      "NGROUPS_MAX", "TMP_MAX", "CLONE_", "TFD_", "POSIX_SPAWN_")
    posix_functions = (
        "uname", "killpg", "getpgid", "getpgrp", "setpgid", "setpgrp", "setsid", "getsid",
        "fork", "forkpty", "openpty", "pidfd_open", "pread", "pwrite", "preadv", "pwritev",
        "pipe2", "WNOHANG", "WUNTRACED", "WCONTINUED", "WEXITED", "WNOWAIT", "WSTOPPED",
        "getuid", "geteuid", "getgid", "getegid", "getgroups", "setuid", "setgid", "seteuid",
        "setegid", "setreuid", "setregid", "setresuid", "setresgid", "getresuid",
        "getresgid", "initgroups", "setgroups", "getgrouplist", "chown", "fchown", "lchown",
        "fchmod", "lchmod", "chroot", "fchdir", "sync", "fdatasync", "sysconf", "confstr",
        "pathconf", "fpathconf", "statvfs", "fstatvfs", "getloadavg", "memfd_create",
        "eventfd", "mkfifo", "mknod", "major", "minor", "makedev", "sched_getaffinity",
        "sched_setaffinity", "sched_yield", "nice", "getpriority", "setpriority",
        "posix_spawn", "posix_spawnp", "posix_fallocate", "posix_fadvise", "wait", "wait3",
        "wait4", "waitid", "ttyname", "ctermid", "getrandom", "sendfile", "splice",
        "copy_file_range", "unshare", "setns", "login_tty", "grantpt", "unlockpt", "ptsname",
        "posix_openpt", "lockf", "plock", "getxattr", "setxattr", "listxattr", "removexattr")
    for name in list(vars(os)):
        if ((name.startswith("O_") and name not in windows_open_flags)
                or name.startswith(posix_prefixes) or name in posix_functions):
            delattr(os, name)
    # ``signal``: native Windows keeps only these signal numbers.
    windows_signals = {"SIGABRT", "SIGFPE", "SIGILL", "SIGINT", "SIGSEGV", "SIGTERM",
                       "SIGBREAK", "SIG_DFL", "SIG_IGN"}
    for name in list(vars(signal)):
        if ((name.startswith("SIG") and name.isupper() and name not in windows_signals)
                or name in ("setitimer", "getitimer", "alarm", "pause", "pidfd_send_signal",
                            "pthread_kill", "pthread_sigmask", "siginterrupt", "sigwait",
                            "sigpending", "sigwaitinfo", "sigtimedwait", "ITIMER_REAL",
                            "ITIMER_VIRTUAL", "ITIMER_PROF", "ItimerError")):
            delattr(signal, name)
    msvcrt = types.ModuleType("msvcrt")
    msvcrt.LK_UNLCK, msvcrt.LK_LOCK, msvcrt.LK_NBLCK = 0, 1, 2
    msvcrt.locking = lambda *args: None
    msvcrt.get_osfhandle = lambda fd: fd
    msvcrt.open_osfhandle = lambda handle, flags: handle
    sys.modules.setdefault("msvcrt", msvcrt)
    ssl.enum_certificates = lambda store: []
    ssl.enum_crls = lambda store: []
    _path_new = pathlib.Path.__new__
    def _posix_path_new(cls, *args, **kwargs):
        return _path_new(pathlib.PosixPath if cls is pathlib.Path else cls, *args, **kwargs)
    pathlib.Path.__new__ = _posix_path_new
    pathlib.WindowsPath = pathlib.PosixPath
    os.name = "nt"
    sys.platform = "win32"
    """
)

_IMPORT_ALL = WINDOWS_SIM_PRELUDE + textwrap.dedent(
    """
    import importlib, pkgutil, traceback
    import phase_loop_runtime as package
    failures = {}
    def _skip(name):
        failures[name] = "walk_packages could not import this package"
    names = sorted(info.name for info in pkgutil.walk_packages(
        package.__path__, "phase_loop_runtime.", onerror=_skip))
    for name in names:
        try:
            importlib.import_module(name)
        except BaseException as exc:
            frames = [f for f in traceback.extract_tb(exc.__traceback__)
                      if "phase_loop_runtime" in f.filename]
            where = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "?"
            failures[name] = f"{type(exc).__name__}: {exc} @ {where}"
    print(json.dumps({"modules": names, "failures": failures}))
    """
)


def windows_sim_env() -> dict[str, str]:
    package_parent = Path(phase_loop_runtime.__file__).resolve().parents[1]
    existing = os.environ.get("PYTHONPATH", "")
    return {**os.environ, "PYTHONPATH": os.pathsep.join(
        [str(package_parent), existing] if existing else [str(package_parent)])}


def run_windows_sim(body: str, *, timeout: float = 300) -> dict:
    done = subprocess.run([sys.executable, "-c", WINDOWS_SIM_PRELUDE + textwrap.dedent(body)],
                          capture_output=True, text=True, timeout=timeout,
                          env=windows_sim_env(), check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_every_module_imports_on_simulated_windows() -> None:
    done = subprocess.run([sys.executable, "-c", _IMPORT_ALL], capture_output=True,
                          text=True, timeout=300, env=windows_sim_env(), check=False)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert len(result["modules"]) > 100
    assert "phase_loop_runtime.runner" in result["modules"]
    assert result["failures"] == {}
    # The closeout registry must still register the FAB gate on Windows.
    assert "fab_gate is not importable" not in done.stderr


def test_posix_only_modules_fail_closed_on_simulated_windows() -> None:
    result = run_windows_sim(
        """
        import json
        from phase_loop_runtime import (claude_seat_sdk, publish_scope_correction,
                                        seat_codex_credential, seat_keyring_exec,
                                        seat_seccomp, supervised_launch_binding,
                                        vendor_access_writer)
        from phase_loop_runtime.convergence.adapters import patch_return
        from phase_loop_runtime import (agy_hold, grok_jail_surface, run_status,
                                        seat_codex_runtime, seat_grok_credential)
        from phase_loop_runtime.grok_roll import catalog, evidence
        outcome = {
            "pwd_absent": [m.pwd is None for m in (claude_seat_sdk, seat_codex_credential,
                                                   supervised_launch_binding, patch_return)],
            "fcntl_absent": [m.fcntl is None for m in (publish_scope_correction,
                                                       seat_keyring_exec, seat_seccomp,
                                                       vendor_access_writer, patch_return)],
            "managed_binding": supervised_launch_binding.MANAGED_BINDING,
            "flags_absent": [flags is None for flags in (
                agy_hold._DIR_FLAGS, agy_hold._FILE_FLAGS, run_status._DIR_FLAGS,
                run_status._READ_FLAGS, run_status._CREATE_FLAGS, grok_jail_surface._WALK,
                catalog._DIR_FLAGS, catalog._FILE_FLAGS, evidence._DIR_FLAGS,
                evidence._FILE_FLAGS, seat_codex_runtime._WALK, seat_grok_credential._O_READ)],
        }
        try:
            os.open(".", run_status._DIR_FLAGS)
            outcome["open_without_flags"] = "opened"
        except Exception as exc:
            outcome["open_without_flags"] = type(exc).__name__
        from phase_loop_runtime.supervised_launch import Refused
        locator = supervised_launch_binding.read_binding_locator(
            supervised_launch_binding.MANAGED_BINDING)
        outcome["locator"] = type(locator).__name__ if isinstance(locator, Refused) else "accepted"
        try:
            seat_seccomp.sealed_keyring_filter()
            outcome["filter"] = "sealed"
        except Exception as exc:
            outcome["filter"] = type(exc).__name__
        try:
            claude_seat_sdk.state_dir()
            outcome["state_dir"] = "resolved"
        except Exception as exc:
            outcome["state_dir"] = type(exc).__name__
        print(json.dumps(outcome))
        """
    )
    assert all(result["pwd_absent"]) and all(result["fcntl_absent"])
    assert result["managed_binding"] is None
    assert all(result["flags_absent"])
    assert result["open_without_flags"] == "TypeError"
    assert result["locator"] == "Refused"
    assert result["filter"] != "sealed"
    assert result["state_dir"] != "resolved"


def test_posix_imports_are_unchanged() -> None:
    if os.name == "nt":
        return
    import fcntl
    import pwd

    from phase_loop_runtime import (claude_seat_sdk, publish_scope_correction,
                                    seat_codex_credential, seat_grok_credential,
                                    seat_keyring_exec, seat_seccomp,
                                    supervised_launch_binding, vendor_access_writer)
    from phase_loop_runtime.convergence.adapters import patch_return

    for module in (claude_seat_sdk, seat_codex_credential, seat_grok_credential,
                   supervised_launch_binding, patch_return):
        assert module.pwd is pwd
    for module in (publish_scope_correction, seat_keyring_exec, seat_seccomp,
                   vendor_access_writer, patch_return):
        assert module.fcntl is fcntl


def test_posix_open_flags_are_unchanged() -> None:
    if os.name == "nt":
        return
    from phase_loop_runtime import (agy_hold, grok_jail_surface, run_status,
                                    seat_codex_runtime, seat_grok_credential)
    from phase_loop_runtime.grok_roll import catalog, evidence

    directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    read = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    walk = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    for flags in (agy_hold._DIR_FLAGS, run_status._DIR_FLAGS, catalog._DIR_FLAGS,
                  evidence._DIR_FLAGS):
        assert flags == directory
    for flags in (agy_hold._FILE_FLAGS, run_status._READ_FLAGS, evidence._FILE_FLAGS):
        assert flags == read
    for flags in (catalog._FILE_FLAGS, seat_grok_credential._O_READ):
        assert flags == read | getattr(os, "O_NOCTTY", 0)
    assert run_status._CREATE_FLAGS == (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                        | os.O_CLOEXEC)
    assert grok_jail_surface._WALK == walk and seat_codex_runtime._WALK == walk
