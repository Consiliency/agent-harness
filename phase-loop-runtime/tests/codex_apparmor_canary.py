"""Administrator-run, credential-free AppArmor experiment; never installed by the runtime.

Render and compile are unprivileged. A separately authorized administrator must verify
the rendered manifest before executing protected staged bytes with Python -I -S.
Mocks and compilation do not establish kernel enforcement or a production repair.
"""

from __future__ import annotations

import argparse
import contextvars
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import select
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid


AA = Path("/sys/kernel/security/apparmor")
PARSER = "/usr/sbin/apparmor_parser"
FEATURES = "/usr/bin/aa-features-abi"
PYTHON = "/usr/bin/python3"
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
       "HOME": "/home/canary", "TMPDIR": "/scratch"}
CAPS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
META_LIMIT = 65536
COLLECT_LIMIT = 1048576
POLICY_HASHES = {
    "baseline.policy": "e7f15a673916c8a8208234e4f623da2bb12018d0a5b06fa5d5c59643ddb4710c",
    "candidate.policy": "48b4fb0d745b7dd46c311b460e91612a7f416d6e72eaeaac7a6e21090532d793",
}
INPUT_NAMES = ("codex_apparmor_canary.py", *POLICY_HASHES, "parser.conf", "features.dump", "fixture.txt")
PRIMARY = ["/usr/bin/unshare", "--user", "--map-root-user", "--mount", "/usr/bin/true"]
WORKER = ("import os; os.write(1,b'READY\\n'); "
          "go=os.read(0,1); "
          "fd=os.open('/dev/null',os.O_RDONLY); os.dup2(fd,0); os.close(fd); "
          "os._exit(125) if go!=b'G' else os.execv('/usr/bin/unshare',"
          + repr(PRIMARY) + ")")
LIBC = ctypes.CDLL(None, use_errno=True)
COMMAND_OWNERS = contextvars.ContextVar("command_owners", default=None)
CANCELLATION = {signal.SIGTERM, signal.SIGHUP, signal.SIGINT}


class Inconclusive(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Inconclusive(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def remaining(deadline):
    budget = deadline - time.monotonic()
    require(budget > 0, "command/cleanup deadline")
    return budget


def file_digest(path, deadline=None):
    if deadline is not None:
        remaining(deadline)
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            if deadline is not None:
                remaining(deadline)
            value.update(chunk)
    if deadline is not None:
        remaining(deadline)
    return value.hexdigest()


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def stamp():
    return {"realtime_ns": time.time_ns(), "monotonic_ns": time.monotonic_ns()}


def protected(path, directory=False):
    """No symlinks, hardlinks, writable ancestors, or non-root owners."""
    path = Path(path)
    require(path.is_absolute() and str(path) == str(path.resolve()), "noncanonical staging")
    for item in (path, *path.parents):
        info = item.lstat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, "unprotected staging ancestry")
        if item == path and not directory:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "staging is not single-link regular file")
        else:
            require(stat.S_ISDIR(info.st_mode), "staging ancestry is not a directory")
    return path


def executable(path, deadline=None):
    resolved = Path(path).resolve(strict=True)
    info = resolved.stat()
    require(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o6022, "privileged or writable executable")
    require(info.st_uid == 0, "executable not root-owned")
    try:
        capabilities = os.getxattr(resolved, "security.capability")
    except OSError as error:
        if error.errno not in (errno.ENODATA, errno.ENOTSUP):
            raise
        capabilities = b""
    require(not capabilities, "file capabilities on executable")
    protected(resolved)
    return {"path": str(resolved), "sha256": file_digest(resolved, deadline)}


def bounded(argv, timeout=30, limit=META_LIMIT, deadline=None):
    """Drain both pipes concurrently; never buffer unbounded command output."""
    end = time.monotonic() + timeout
    if deadline is not None:
        end = min(end, deadline)
    budget = remaining(end)  # Refuse an expired budget before spawning anything.
    work_end = end - min(1, budget / 4)  # Teardown consumes this same budget.
    owner = CommandOwnership(end)
    registry = COMMAND_OWNERS.get()
    if registry is not None:
        registry.append(owner)
    streams = None
    subreaper = ctypes.c_int()
    subreaper_active = False
    try:
        prctl(37, ctypes.byref(subreaper))
        prctl(36, 1)  # Adopt command descendants even if their intermediary exits.
        subreaper_active = True
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, CANCELLATION)
        try:
            owner.adopted_before = {int(pid): start_time(int(pid)) for pid in
                                    Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()}
            owner.child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, env=ENV, close_fds=True,
                                           start_new_session=registry is not None,
                                           preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, previous))
            child = owner.child
            owner.session_pid = os.getsid(child.pid)
            handle = Process(child.pid)
            owner.children[handle.pid] = handle
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        streams = selectors.DefaultSelector()
        streams.register(child.stdout, selectors.EVENT_READ, 0)
        streams.register(child.stderr, selectors.EVENT_READ, 1)
        buffers = [bytearray(), bytearray()]
        while streams.get_map():
            for key, _ in streams.select(min(0.05, remaining(work_end))):
                data = os.read(key.fileobj.fileno(), 8192)
                if not data:
                    streams.unregister(key.fileobj)
                else:
                    buffers[key.data].extend(data)
                    require(sum(map(len, buffers)) <= limit, "command output overflow")
        try:
            code = child.wait(timeout=remaining(work_end))
        except subprocess.TimeoutExpired as error:
            raise Inconclusive("command deadline") from error
        remaining(work_end)
        require(code == 0, "command failed: " + Path(argv[0]).name)
        return bytes(buffers[0])
    finally:
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, CANCELLATION)
        try:
            try:
                if streams is not None:
                    streams.close()
            finally:
                owner.reap()
            if subreaper_active:
                prctl(36, subreaper.value)
            remaining(end)
            if registry is not None:
                registry.remove(owner)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def parser_argv(root, arm, operation, namespace=None):
    require(arm in POLICY_HASHES, "unknown arm")
    require(operation in ("compile", "preprocess", "load", "remove"), "unknown parser operation")
    argv = [PARSER, "-K", "--config-file", str(root / "parser.conf"),
            "--base", str(root), "--Include", str(root),
            "--policy-features", str(root / "features.dump")]
    if operation in ("load", "remove"):
        require(bool(re.fullmatch(r"phase_loop_codex_canary_[0-9a-f]{32}", namespace or "")),
                "empty or foreign policy namespace")
        argv += ["--namespace", namespace, "-r" if operation == "load" else "-R"]
    else:
        require(namespace is None, "offline parser namespace")
        argv += ["-Q"]
        if operation == "preprocess":
            argv += ["-p"]
    return argv + [str(root / arm)]


def policy_check(root):
    for name, expected in POLICY_HASHES.items():
        data = (root / name).read_bytes()
        # Hash pinning is authoritative; reject open input syntax independently too.
        require(not re.search(rb"(?m)^\s*(?:#\s*)?(?:include|include-if-exists|abi|@\{|\$)", data),
                "open policy input")
        require(digest(data) == expected, "reviewed policy bytes changed")
    require((root / "parser.conf").read_bytes() == b"", "nonempty parser config")
    require((root / "features.dump").stat().st_size > 0, "empty features input")


def closure(root, deadline=None):
    return {name: file_digest(root / name, deadline) for name in INPUT_NAMES}


def fixture_inputs(deadline=None):
    """Bind fixed executable and interpreter bootstrap files, never host stdlib trees."""
    paths = {PYTHON, "/usr/bin/unshare", "/usr/bin/true"}
    for path in tuple(paths):
        output = bounded(["/usr/bin/ldd", str(Path(path).resolve())], deadline=deadline).decode()
        for line in output.splitlines():
            match = re.search(r"(?:=>\s*)?(/[^\s]+)\s+\(", line)
            if match:
                paths.add(match.group(1))
        require("not found" not in output, "missing loader dependency")
    version = bounded([PYTHON, "-I", "-S", "-c",
                       "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))"], deadline=deadline).decode().strip()
    require(re.fullmatch(r"3\.\d+", version), "unexpected system Python")
    stdlib = Path("/usr/lib") / ("python" + version)
    encodings = stdlib / "encodings"
    require(encodings.is_dir(), "missing Python encodings")
    # os.py is CPython's prefix landmark even when os is frozen. Python 3.14
    # imports linecache before executing -c to register its source, even `pass`.
    paths.update(str(stdlib / name) for name in ("os.py", "linecache.py"))
    files = {path: executable(path, deadline) for path in sorted(paths)}
    protected(encodings, directory=True)
    encoding_hashes, encoding_directories = {}, []
    for path in sorted(encodings.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            protected(path, directory=True)
            encoding_directories.append(str(path.relative_to(encodings)))
        else:
            require(stat.S_ISREG(mode), "unsupported encoding entry")
            protected(path)  # Check the original entry before executable resolves it.
            item = executable(path, deadline)
            encoding_hashes[str(path.relative_to(encodings))] = item["sha256"]
    return {"files": files, "encodings": str(encodings), "encoding_hashes": encoding_hashes,
            "encoding_directories": encoding_directories,
            "dynload": str(stdlib / "lib-dynload")}


def tools(deadline=None):
    paths = [PARSER, FEATURES, "/usr/bin/aa-exec", "/usr/bin/bwrap", PYTHON,
             "/usr/bin/unshare", "/usr/bin/true", "/usr/bin/journalctl", "/usr/bin/ldd"]
    if Path("/usr/sbin/auditctl").exists():
        paths.append("/usr/sbin/auditctl")
    inventory = {path: executable(path, deadline) for path in paths}
    # ldd is itself executing code. Only its measured bash recipe is supported;
    # bind every possible loader it probes before using it for dependency discovery.
    ldd = Path(inventory["/usr/bin/ldd"]["path"]).read_text()
    require(ldd.startswith("#!/bin/bash\n"), "unsupported ldd interpreter")
    loaders = re.search(r'^RTLDLIST="([^"\n]+)"$', ldd, re.MULTILINE)
    require(loaders is not None, "unknown ldd loader recipe")
    probes = loaders[1].split()
    require(probes and all(p.startswith("/") for p in probes), "invalid ldd loader paths")
    dependencies = {"/bin/bash": executable("/bin/bash", deadline)}
    for path in probes:
        if Path(path).exists():
            dependencies[path] = executable(path, deadline)
    require(len(dependencies) > 1, "ldd loader unavailable")
    # The protected Python trampoline also executes stdlib modules and native
    # extensions. Inventory the same imports under the exact system interpreter,
    # including existing bytecode caches rather than hashing only their sources.
    probe = ("import __future__,argparse,contextvars,ctypes,errno,fcntl,hashlib,json,os,pathlib,platform,re,"
             "select,selectors,signal,stat,subprocess,sys,time,uuid; "
             "argparse.ArgumentParser().parse_args([]); "
             "print(json.dumps(sorted({str(pathlib.Path(p).resolve()) "
             "for m in tuple(sys.modules.values()) "
             "for p in (getattr(m,'__file__',None),getattr(m,'__cached__',None)) "
             "if p and pathlib.Path(p).is_file()})))")
    python_files = json.loads(bounded([PYTHON, "-I", "-S", "-c", probe], deadline=deadline))
    require(isinstance(python_files, list) and python_files, "Python code closure unavailable")
    for path in python_files:
        require(isinstance(path, str) and path.startswith("/usr/lib/python"), "unexpected Python code path")
        dependencies[path] = executable(path, deadline)
    native = [path for path in python_files if path.endswith(".so")]
    for path in [p for p in paths if p != "/usr/bin/ldd"] + ["/bin/bash", *native]:
        with Path(path).open("rb") as stream:
            require(stream.read(4) == b"\x7fELF", "unsupported tool interpreter")
        output = bounded(["/usr/bin/ldd", str(Path(path).resolve())], deadline=deadline).decode()
        require("not found" not in output, "missing tool loader dependency")
        for line in output.splitlines():
            match = re.search(r"(?:=>\s*)?(/[^\s]+)\s+\(", line)
            if match:
                dependency = match[1]
                dependencies[dependency] = executable(dependency, deadline)
    return {"executables": inventory, "dependencies": dependencies,
            "ldd_interpreter": "/bin/bash", "ldd_loader_probes": probes}


def render(out):
    out = out.absolute()
    out.mkdir(mode=0o700)  # Never overwrite a prior render or administrator staging.
    source = Path(__file__).resolve()
    inputs = source.parents[2] / "plans/evidence/codex-apparmor-canary"
    for name in POLICY_HASHES:
        (out / name).write_bytes((inputs / name).read_bytes())
    (out / source.name).write_bytes(source.read_bytes())
    (out / "parser.conf").write_bytes(b"")
    (out / "fixture.txt").write_bytes(b"synthetic credential-free fixture\n")
    (out / "features.dump").write_bytes(bounded([FEATURES, "--extract", "--stdout"], limit=COLLECT_LIMIT))
    policy_check(out)
    manifest = {"schema": 1, "boot_id": boot_id(), "kernel": platform.release(),
                "inputs": closure(out), "tools": tools(), "fixture": fixture_inputs(),
                "parser_help_sha256": digest(bounded(parser_argv(out, "baseline.policy", "compile")[:-1] + ["--help"]))}
    manifest["preprocessed_sha256"] = {
        arm: digest(bounded(parser_argv(out, arm, "preprocess"), limit=COLLECT_LIMIT)) for arm in POLICY_HASHES}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def validate_inputs(root, manifest, deadline=None):
    if deadline is not None:
        remaining(deadline)
    require(set(manifest["inputs"]) == set(INPUT_NAMES), "manifest input inventory changed")
    require({p.name for p in root.iterdir()} == {*manifest["inputs"], "manifest.json"}, "input closure inventory changed")
    for name in (*manifest["inputs"], "manifest.json"):
        protected(root / name)
    policy_check(root)
    require(closure(root, deadline) == manifest["inputs"], "input closure changed")
    require(manifest["boot_id"] == boot_id(), "boot changed since render")
    require(manifest["kernel"] == platform.release(), "kernel changed since render")
    require(tools(deadline=deadline) == manifest["tools"] and fixture_inputs(deadline=deadline) == manifest["fixture"], "executable closure changed")
    help_text = bounded(parser_argv(root, "baseline.policy", "compile")[:-1] + ["--help"], deadline=deadline)
    require(b"Do not attempt to load or save cached profiles" in help_text, "parser cache contract unavailable")
    require(digest(help_text) == manifest["parser_help_sha256"], "parser interface changed")
    features = bounded([FEATURES, "--extract", "--stdout"], limit=COLLECT_LIMIT, deadline=deadline)
    require(digest(features) == manifest["inputs"]["features.dump"], "kernel features changed")
    if deadline is not None:
        remaining(deadline)


def close_fds():
    for name in os.listdir("/proc/self/fd"):
        fd = int(name)
        if fd > 2:
            try:
                os.close(fd)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise


def prctl(option, arg=0):
    require(LIBC.prctl(option, arg, 0, 0, 0) == 0, "prctl refused")


def status(pid):
    text = Path(f"/proc/{pid}/status").read_text()
    require(len(text) <= META_LIMIT, "child status overflow")
    return dict(line.split(":", 1) for line in text.splitlines() if ":" in line)


def verify_drop(observed, uid, gid):
    require(uid > 0 and gid > 0, "host root identity prohibited")
    require([int(x) for x in observed["Uid"].split()] == [uid] * 4, "uid drop incomplete")
    require([int(x) for x in observed["Gid"].split()] == [gid] * 4, "gid drop incomplete")
    require(not observed["Groups"].strip(), "supplementary groups retained")
    require(all(int(observed[key], 16) == 0 for key in CAPS), "capabilities retained")
    require(observed["NoNewPrivs"].strip() == "1", "NoNewPrivs missing")


def drop_identity(uid, gid):
    require(uid > 0 and gid > 0, "host root identity prohibited")
    close_fds()
    header = (ctypes.c_uint32 * 2)(0x20080522, 0)
    temporary = (ctypes.c_uint32 * 6)(0x1c0, 0x1c0, 0, 0, 0, 0)
    require(LIBC.capset(header, temporary) == 0, "temporary capability restriction refused")
    require(LIBC.prctl(47, 4, 0, 0, 0) == 0, "ambient clear refused")
    last = int(Path("/proc/sys/kernel/cap_last_cap").read_text())
    require(0 <= last < 64, "unknown capability ABI")
    # Dropping bounding bits does not remove effective SETPCAP/SETUID/SETGID
    # until the real/effective/saved uid transition has completed.
    for bit in range(last + 1):
        prctl(24, bit)  # PR_CAPBSET_DROP
    os.setgroups([])
    os.setresgid(gid, gid, gid)
    os.setresuid(uid, uid, uid)
    data = (ctypes.c_uint32 * 6)()
    require(LIBC.capset(header, data) == 0, "capset refused")
    require(LIBC.prctl(47, 4, 0, 0, 0) == 0, "ambient clear refused")
    prctl(38, 1)  # PR_SET_NO_NEW_PRIVS
    verify_drop(status("self"), uid, gid)
    close_fds()


def bwrap_argv(root, manifest, uid, gid):
    argv = ["/usr/bin/bwrap", "--die-with-parent", "--unshare-user", "--uid", str(uid),
            "--gid", str(gid), "--cap-drop", "ALL", "--unshare-pid", "--unshare-ipc",
            "--unshare-uts", "--unshare-net", "--tmpfs", "/", "--proc", "/proc",
            "--tmpfs", "/dev", "--dev-bind", "/dev/null", "/dev/null",
            "--dir", "/home", "--dir", "/home/canary",
            "--dir", "/scratch"]
    for destination, item in manifest["fixture"]["files"].items():
        argv += ["--ro-bind", item["path"], destination]
    encodings = manifest["fixture"]["encodings"]
    argv += ["--dir", manifest["fixture"]["dynload"],
             "--ro-bind", encodings, encodings, "--ro-bind", str(root / "fixture.txt"), "/fixture.txt",
             "--chdir", "/scratch", "--clearenv"]
    for name, value in ENV.items():
        argv += ["--setenv", name, value]
    return argv + ["--", PYTHON, "-I", "-S", "-c", WORKER]


def prepare_mounts(expected, deadline):
    require(re.fullmatch(r"mnt:\[[0-9]{1,20}\]", expected), "invalid entry mount identity")
    remaining(deadline)
    before = os.readlink("/proc/self/ns/mnt")
    require(before == expected, "entry mount namespace changed")
    ctypes.set_errno(0)
    result = LIBC.unshare(0x20000)  # CLONE_NEWNS only; no user namespace.
    require(result == 0, f"mount namespace unshare refused: errno={ctypes.get_errno()}")
    after = os.readlink("/proc/self/ns/mnt")
    require(after != before, "mount namespace identity unchanged")
    remaining(deadline)
    LIBC.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                          ctypes.c_ulong, ctypes.c_void_p]
    LIBC.mount.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = LIBC.mount(None, b"/", None, 0x4000 | 0x40000, None)
    require(result == 0, f"private propagation refused: errno={ctypes.get_errno()}")
    rows = mount_rows(Path("/proc/self/mountinfo").read_text(), host=True)
    require(rows and all(not row["propagation"] for row in rows), "prepared mount propagation not private")
    remaining(deadline)
    return after


def trampoline(root, uid, gid, namespace, deadline, entry_mnt):
    require(os.getuid() == 0 and os.geteuid() == 0, "drop trampoline requires root")
    require(re.fullmatch(r"phase_loop_codex_canary_[0-9a-f]{32}", namespace), "invalid trampoline namespace")
    label = Path("/proc/self/attr/current").read_text().strip()
    require(label == "unconfined", "unconfined Python self-view not observed")
    require(deadline <= time.monotonic() + 10, "invalid startup deadline")
    os.write(1, b"ENTRY\n")
    require(select.select([0], [], [], remaining(deadline))[0], "entry acknowledgment deadline")
    require(os.read(0, 1) == b"E", "entry acknowledgment refused")
    remaining(deadline)
    manifest = json.loads((root / "manifest.json").read_text())
    validate_inputs(root, manifest, deadline=deadline)
    prepared = prepare_mounts(entry_mnt, deadline)
    os.write(1, ("PREPARED " + prepared + "\n").encode("ascii"))
    # Protected code is executed by Python before bwrap ever receives on-exec selection.
    argv = bwrap_argv(root, manifest, uid, gid)
    remaining(deadline)
    drop_identity(uid, gid)
    remaining(deadline)
    os.execve(argv[0], argv, ENV)


def start_time(pid):
    text = Path(f"/proc/{pid}/stat").read_text()
    return int(text[text.rfind(")") + 2:].split()[19])


class Process:
    """A numeric PID alone never authorizes a signal or an observation."""

    def __init__(self, pid):
        self.pid = pid
        self.reaped = False
        self.start = start_time(pid)
        self.fd = os.pidfd_open(pid)
        try:
            require(start_time(pid) == self.start, "PID reused during acquisition")
        except BaseException:
            os.close(self.fd)
            raise

    def alive(self):
        try:
            return start_time(self.pid) == self.start and not select.select([self.fd], [], [], 0)[0]
        except FileNotFoundError:
            return False

    def send(self, sig):
        if self.alive():
            signal.pidfd_send_signal(self.fd, sig)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def collect(self):
        """Death is not reaping: consume even an already-readable pidfd's status."""
        if self.reaped:
            return True
        try:
            require(start_time(self.pid) == self.start, "PID reused before wait")
        except FileNotFoundError:
            return True  # Already reaped by the observer or its original parent.
        try:
            pid, state = os.waitpid(self.pid, os.WNOHANG | 0x40000000)
        except ChildProcessError:
            # A zombie still owned by an intermediary must become adopted/reaped.
            return False
        self.reaped = bool(pid and (os.WIFEXITED(state) or os.WIFSIGNALED(state)))
        return self.reaped


def descendants(owner, found, deadline=None):
    if deadline is not None:
        remaining(deadline)
    if not owner.alive():
        return
    children = Path(f"/proc/{owner.pid}/task/{owner.pid}/children").read_text().split()
    require(len(children) <= 64, "too many child processes")
    for child in children:
        pid = int(child)
        if pid not in found:
            require(len(found) < 64, "too many owned processes")
            try:
                handle = Process(pid)
            except FileNotFoundError:
                continue  # The verified parent's child was already reaped.
            try:
                require(owner.alive() and int(status(pid)["PPid"]) == owner.pid, "descendant ownership changed")
            except FileNotFoundError:
                handle.close()
                continue
            except BaseException:
                handle.close()
                raise
            found[pid] = handle
        try:
            require(start_time(pid) == found[pid].start, "descendant PID reused")
        except FileNotFoundError:
            continue
        descendants(found[pid], found, deadline)


def mount_rows(text, host=False):
    rows = []
    for line in text.splitlines():
        left, right = line.split(" - ", 1)
        fields, tail = left.split(), right.split()
        if host:
            for index in (3, 4):
                require(not re.search(r"\\(?!040|011|012|134)", fields[index]), "unknown host mount escape")
                fields[index] = re.sub(r"\\(040|011|012|134)", lambda m: chr(int(m[1], 8)), fields[index])
        else:
            require(not any("\\" in x for x in fields[3:5]), "escaped mount path")
        rows.append({"dev": fields[2], "root": fields[3], "path": fields[4],
                     "options": fields[5].split(","), "propagation": fields[6:], "fs": tail[0]})
    return rows


def expected_binds(root, manifest):
    bindings = {dest: item["path"] for dest, item in manifest["fixture"]["files"].items()}
    encodings = manifest["fixture"]["encodings"]
    bindings[encodings] = encodings
    bindings["/fixture.txt"] = str(root / "fixture.txt")
    bindings["/dev/null"] = "/dev/null"
    result = {}
    # Resolve a host file against the longest matching host mountpoint.
    host = mount_rows(Path("/proc/self/mountinfo").read_text(), host=True)
    for dest, path in bindings.items():
        containing = [r for r in host if Path(path).is_relative_to(r["path"])]
        row = max(containing, key=lambda r: len(r["path"]))
        relative = Path(path).relative_to(row["path"])
        result[dest] = (row["dev"], str(Path(row["root"]) / relative))
    return result


def validate_gate(observation, uid, gid, namespace, binds):
    verify_drop(observation["status"], uid, gid)
    # AppArmor may elide the repeated namespace in a compound label. Both
    # representations name exactly the same two profiles in our namespace.
    expected = {f":{namespace}:bwrap//&unpriv_bwrap (enforce)",
                f":{namespace}:bwrap//&:{namespace}:unpriv_bwrap (enforce)"}
    require(observation["label"] in expected, "unexpected AppArmor stack")
    for name in ("user", "mnt", "pid", "net", "ipc", "uts"):
        require(observation["namespaces"][name] != observation["host_namespaces"][name], "namespace not isolated: " + name)
    require(observation["user_parent"] == observation["host_namespaces"]["user"], "unexpected user namespace chain")
    require(observation["user_owner"] == uid, "wrong user namespace owner")
    require(observation["uid_map"] == [[uid, uid, 1]], "wrong host-operator uid map")
    require(observation["gid_map"] == [[gid, gid, 1]], "wrong host-operator gid map")
    require(observation["fds"] == {"0": "gate", "1": "status", "2": "status"}, "descriptor leak")
    validate_mounts(observation["mounts"], binds)


def validate_mounts(mounts, binds):
    seen = set()
    for row in mounts:
        path = row["path"]
        require(path not in seen, "duplicate mount")
        require(not row["propagation"], "mount propagation not private")
        if path in binds:
            require((row["dev"], row["root"]) == tuple(binds[path]), "unexpected bind")
            require(path == "/dev/null" or "ro" in row["options"], "writable host bind")
            seen.add(path)
        else:
            require((path, row["fs"]) in {("/", "tmpfs"), ("/proc", "proc"), ("/dev", "tmpfs")}, "unexpected mount")
    require(seen == set(binds), "missing fixture bind")
    require(any(r["path"] == "/" and r["fs"] == "tmpfs" for r in mounts), "root not synthetic")


def observe_gate(worker, child):
    require(worker.alive(), "worker exited before gate")
    pid = worker.pid
    base = Path(f"/proc/{pid}")
    namespaces = {name: os.readlink(base / "ns" / name) for name in ("user", "mnt", "pid", "net", "ipc", "uts")}
    host = {name: os.readlink(Path("/proc/self/ns") / name) for name in namespaces}
    with (base / "ns/user").open("rb") as stream:
        parent = fcntl.ioctl(stream.fileno(), 0xb702)  # NS_GET_PARENT
        try:
            parent_identity = os.readlink(f"/proc/self/fd/{parent}")
        finally:
            os.close(parent)
        owner = int.from_bytes(fcntl.ioctl(stream.fileno(), 0xb704, bytes(4)), sys.byteorder)
    descriptors = {}
    for path in (base / "fd").iterdir():
        target = os.readlink(path)
        if path.name == "0" and target == f"pipe:[{os.fstat(child.stdin.fileno()).st_ino}]":
            descriptors[path.name] = "gate"
        elif path.name in ("1", "2"):
            stream = child.stdout if path.name == "1" else child.stderr
            require(target == f"pipe:[{os.fstat(stream.fileno()).st_ino}]", "unexpected stdio")
            descriptors[path.name] = "status"
        else:
            descriptors[path.name] = "unexpected"
    observation = {"pid": pid, "start": worker.start, "status": status(pid),
                   "label": (base / "attr/current").read_text().strip(),
                   "namespaces": namespaces, "host_namespaces": host, "user_parent": parent_identity,
                   "user_owner": owner, "fds": descriptors,
                   "mounts": mount_rows((base / "mountinfo").read_text())}
    null = (base / "root/dev/null").stat()
    require(stat.S_ISCHR(null.st_mode) and null.st_rdev == os.makedev(1, 3), "non-null synthetic device")
    for name in ("uid_map", "gid_map"):
        observation[name] = [[int(x) for x in line.split()] for line in (base / name).read_text().splitlines()]
    require(worker.alive(), "worker identity changed during gate")
    require(len(json.dumps(observation)) <= META_LIMIT, "gate metadata overflow")
    return observation


def ptrace(request, pid, addr=0, data=0):
    LIBC.ptrace.restype = ctypes.c_long
    result = LIBC.ptrace(ctypes.c_uint(request), ctypes.c_uint(pid), ctypes.c_void_p(addr), ctypes.c_void_p(data))
    if result == -1:
        raise Inconclusive("ptrace refused")
    return result


class Observer:
    """Root-side syscall observer. No exec arguments, buffers, or payloads are traced."""

    def __init__(self, worker, owned, deadline=None):
        require(platform.machine() in ("x86_64", "aarch64"), "unsupported syscall architecture")
        self.worker = worker
        self.owned = owned
        self.active = {worker.pid: worker}
        self.pending = {}
        self.records = []
        self.exits = {}
        self.deadline = deadline
        if deadline is not None:
            remaining(deadline)
        # Unexpected forks fail closed; adopt their identity for cleanup before refusing.
        ptrace(0x4206, worker.pid, 0, 1 | 2 | 4 | 8)  # SEIZE, TRACESYSGOOD, fork/vfork/clone
        ptrace(0x4207, worker.pid)  # INTERRUPT before GO
        self.wait_stop(worker.pid, deadline if deadline is not None else time.monotonic() + 10)

    def wait_stop(self, pid, end):
        while time.monotonic() < end:
            observed, state = os.waitpid(pid, os.WNOHANG | 0x40000000)
            if observed:
                require(os.WIFSTOPPED(state), "tracee exited before gate")
                return state
            time.sleep(0.005)
        raise Inconclusive("observer attachment deadline")

    def run(self, go):
        require(self.worker.alive(), "worker changed before GO")
        end = self.deadline if self.deadline is not None else time.monotonic() + 10
        remaining(end)
        go()
        ptrace(24, self.worker.pid)  # SYSCALL
        primary_nr = 272 if platform.machine() == "x86_64" else 97
        cap_nr = {125, 126, 157} if platform.machine() == "x86_64" else {90, 91, 167}
        while self.active:
            require(time.monotonic() < end, "inner operation deadline")
            progress = False
            for pid, handle in list(self.active.items()):
                observed, state = os.waitpid(pid, os.WNOHANG | 0x40000000)
                if not observed:
                    continue
                progress = True
                if os.WIFEXITED(state) or os.WIFSIGNALED(state):
                    self.exits[pid] = os.waitstatus_to_exitcode(state)
                    handle.reaped = True
                    del self.active[pid]
                    continue
                require(handle.alive(), "tracee PID changed")
                event = state >> 16
                if event in (1, 2, 3):
                    newborn = ctypes.c_ulong()
                    ptrace(0x4201, pid, 0, ctypes.addressof(newborn))  # GETEVENTMSG
                    self.owned[newborn.value] = Process(newborn.value)
                require(event not in (1, 2, 3), "unexpected fork in fixed primary operation")
                sig = os.WSTOPSIG(state)
                if sig == (signal.SIGTRAP | 0x80):
                    info = ctypes.create_string_buffer(88)
                    size = ptrace(0x420e, pid, 88, ctypes.addressof(info))  # GET_SYSCALL_INFO
                    require(size >= 24, "missing syscall information")
                    op = info.raw[0]
                    if op == 1:
                        require(size >= 80, "truncated syscall entry")
                        arch = int.from_bytes(info.raw[4:8], sys.byteorder)
                        require(arch == (0xc000003e if platform.machine() == "x86_64" else 0xc00000b7), "syscall architecture changed")
                        number = int.from_bytes(info.raw[24:32], sys.byteorder)
                        args = [int.from_bytes(info.raw[i:i + 8], sys.byteorder) for i in range(32, 80, 8)]
                        if number == primary_nr:
                            require(args[0] == 0x10020000, "primary syscall flags changed")  # NEWUSER|NEWNS
                            require(Path(f"/proc/{pid}/attr/current").read_text().strip() == self.expected_label,
                                    "primary task label changed")
                            require(Path(f"/proc/{pid}/exe").resolve() == Path("/usr/bin/unshare").resolve(),
                                    "primary executable changed")
                            self.pending[pid] = {"pid": pid, "start": handle.start, "flags": args[0],
                                                 "syscall": "unshare", **stamp()}
                        elif number in cap_nr:
                            self.records.append({"pid": pid, "start": handle.start, "syscall_number": number})
                    elif op == 2 and pid in self.pending:
                        require(size >= 33, "truncated syscall exit")
                        result = int.from_bytes(info.raw[24:32], sys.byteorder, signed=True)
                        self.records.append({**self.pending.pop(pid), "return": result,
                                             "exit_realtime_ns": time.time_ns(), "exit_monotonic_ns": time.monotonic_ns()})
                    require(len(json.dumps(self.records)) <= COLLECT_LIMIT, "trace overflow")
                # Ptrace's exec trap is synthetic. Forward actual delivery signals.
                ptrace(24, pid, 0, 0 if sig in (signal.SIGTRAP, signal.SIGTRAP | 0x80) else sig)
            if not progress:
                time.sleep(0.001)
        return self.records


def journal_cursor():
    output = bounded(["/usr/bin/journalctl", "-k", "-n", "1", "--no-pager", "-o", "json"], limit=COLLECT_LIMIT)
    rows = [json.loads(line) for line in output.splitlines()]
    require(len(rows) == 1 and rows[0].get("_BOOT_ID") == boot_id().replace("-", ""), "kernel journal unreadable")
    return rows[0]["__CURSOR"]


def loss_counters(deadline=None):
    result = {"audit_status": "unavailable"}
    path = Path("/usr/sbin/auditctl")
    if path.exists():
        executable(path, deadline)
        output = bounded([str(path), "-s"], deadline=deadline).decode()
        result = {key: int(value) for key, value in re.findall(
            r"(?m)^(lost|rate_limit|backlog|backlog_limit|backlog_wait_time_actual)\s+(\d+)$", output)}
        require("lost" in result, "audit counters unreadable")
    for name in ("printk_ratelimit", "printk_ratelimit_burst"):
        path = Path("/proc/sys/kernel") / name
        if path.exists():
            result[name] = int(path.read_text())
    return result


def audit_capture(cursor, observation, begin, finish):
    data = bounded(["/usr/bin/journalctl", "-k", "--no-pager", "-o", "json", "--after-cursor", cursor],
                   limit=COLLECT_LIMIT)
    matches = []
    capture_finish = stamp()
    namespace = re.fullmatch(r":(phase_loop_codex_canary_[0-9a-f]{32}):bwrap//&.* \(enforce\)", observation["label"])
    require(namespace is not None, "unverified audit subject label")
    for line in data.splitlines():
        row = json.loads(line)
        message = row.get("MESSAGE", "")
        require(isinstance(message, str), "malformed kernel journal message")
        require(not re.search(r"(?i)(?:lost \d+|\d+ (?:messages|callbacks) suppressed|rate.limit|audit.*backlog)", message),
                "known audit capture loss")
        fields = {}
        for key, quoted, plain in re.findall(r'(\w+)=(?:"([^"]*)"|(\S+))', message):
            fields[key] = quoted or plain
        if fields.get("pid") != str(observation["pid"]):
            continue
        require(row.get("_TRANSPORT") == "kernel", "audit transport mismatch")
        real_ns = int(row["__REALTIME_TIMESTAMP"]) * 1000
        mono_ns = int(row["__MONOTONIC_TIMESTAMP"]) * 1000
        require(row.get("_BOOT_ID") == boot_id().replace("-", ""), "audit boot mismatch")
        event = re.search(r"audit\((\d+)\.(\d+):(\d+)\)", message)
        if event is None:
            continue
        event_real_ns = int(event.group(1)) * 1000000000 + int(event.group(2).ljust(9, "0")[:9])
        # Kernel audit time uses a coarse clock and millisecond formatting. Keep
        # a whole-arm realtime sanity bound; attributed() uses the same-boot
        # journal monotonic timestamp for the exact syscall entry/exit interval.
        in_interval = (begin["realtime_ns"] - 1000000 <= event_real_ns <= finish["realtime_ns"] + 1000000
                       and begin["monotonic_ns"] <= mono_ns <= capture_finish["monotonic_ns"])
        full = observation["label"].removesuffix(" (enforce)")
        exact_namespaces = (namespace.group(1), "root//" + namespace.group(1))
        # Kernel aa_audit() reports the denying component as namespace+profile;
        # compound-subject audit paths instead report a fully qualified label.
        subject = ((fields.get("namespace") in exact_namespaces and fields.get("profile") == "unpriv_bwrap")
                   or (fields.get("label", fields.get("profile")) == full
                       and fields.get("namespace") in (None, *exact_namespaces)))
        if in_interval:
            if (fields.get("apparmor") == "DENIED" and fields.get("operation") == "capable"
                    and fields.get("capability") == "21" and fields.get("capname") == "sys_admin"
                    and subject):
                matches.append({"pid": observation["pid"], "start": observation["start"],
                                "label": observation["label"], "capability": 21, "operation": "capable",
                                "realtime_ns": event_real_ns, "monotonic_ns": mono_ns,
                                "journal_realtime_ns": real_ns, "audit_namespace": fields.get("namespace"),
                                "audit_profile": fields.get("profile", fields.get("label")),
                                "serial": event.group(3), "boot_id": boot_id()})
    return matches


def attributed(arm):
    requests = [r for r in arm["trace"] if r.get("syscall") == "unshare"]
    if len(requests) != 1:
        return False
    request = requests[0]
    return (request["return"] == -errno.EPERM and request["flags"] == 0x10020000
            and request["pid"] == arm["gate"]["pid"] and request["start"] == arm["gate"]["start"] and any(
        a["pid"] == request["pid"] and a["start"] == request["start"]
        and a["capability"] == 21 and a["label"] == arm["gate"]["label"]
        and request["monotonic_ns"] <= a["monotonic_ns"] <= min(
            request.get("exit_monotonic_ns", -1), arm.get("capture_finish", arm["finish"])["monotonic_ns"])
        and arm["begin"]["realtime_ns"] - 1000000 <= a["realtime_ns"] <= arm["finish"]["realtime_ns"] + 1000000
        and a["operation"] == "capable" and a["boot_id"] == arm["boot_id"]
        for a in arm["audit"]))


def outcome(baseline, candidate):
    if not baseline or not attributed(baseline) or not candidate:
        return "inconclusive"
    requests = [r for r in candidate["trace"] if r.get("syscall") == "unshare"]
    if len(requests) != 1:
        return "inconclusive"
    request = requests[0]
    if (request["return"] == 0 and request["flags"] == 0x10020000
            and request["pid"] == candidate["gate"]["pid"] and request["start"] == candidate["gate"]["start"]):
        return "hypothesis_supported"
    return "hypothesis_refuted" if attributed(candidate) else "inconclusive"


def root_policy(disk_root=None, aa_root=None, deadline=None):
    disk_root = Path("/etc/apparmor.d") if disk_root is None else disk_root
    aa_root = AA if aa_root is None else aa_root
    disk = {}
    for path in sorted(disk_root.rglob("*")):
        if path.is_file():
            disk[str(path.relative_to(disk_root))] = file_digest(path, deadline)
    loaded = {}
    for path in sorted((aa_root / "policy/profiles").rglob("raw_data")):
        parent = path.parent
        name = (parent / "name").read_text().strip()
        mode = (parent / "mode").read_text().strip()
        loaded[str(parent.relative_to(aa_root / "policy/profiles"))] = {
            "name": name, "mode": mode, "sha256": file_digest(path, deadline)}
    require(disk and loaded, "disk or loaded root-policy evidence unreadable")
    labels = sorted((aa_root / "profiles").read_text().splitlines())
    require(labels, "loaded root profile set unreadable")
    if deadline is not None:
        remaining(deadline)
    return {"disk": disk, "loaded": loaded, "labels": labels}


class Namespace:
    def __init__(self):
        self.name = "phase_loop_codex_canary_" + uuid.uuid4().hex
        self.path = AA / "policy/namespaces" / self.name
        self.fd = None
        self.identity = None
        self.created = False
        self.acquired = False
        self.creation_uncertain = False

    def create(self):
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, CANCELLATION)
        try:
            self.creation_uncertain = True
            try:
                self.path.mkdir()  # Collision refuses; never claim a foreign namespace.
            except FileExistsError:
                self.creation_uncertain = False
                raise
            self.created = True
            self.creation_uncertain = False
            info = self.path.lstat()
            self.identity = (info.st_dev, info.st_ino)
            self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(self.fd)
            require((info.st_dev, info.st_ino) == self.identity, "namespace replaced during acquisition")
            self.acquired = True
            self.check()
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)

    def check(self):
        info = self.path.lstat()
        require(self.acquired and self.fd is not None and (info.st_dev, info.st_ino) == self.identity,
                "owned namespace identity changed")

    def remove(self):
        self.check()
        os.close(self.fd)
        self.fd = None
        self.path.rmdir()
        require(not self.path.exists(), "owned namespace survived removal")


class CommandOwnership:
    """Controller commands use the same pidfd/session reaper as the outer fixture."""

    def __init__(self, end):
        self.children = {}
        self.child = None
        self.session_pid = None
        self.teardown_errors = []
        self.cleanup_end = end
        self.adopted_before = {}
        self.term_grace = 0  # Reserve the command's remaining teardown time for KILL/reap.

    def reap(self):
        Experiment.reap(self)


class Experiment:
    def __init__(self, root, evidence, uid, gid):
        self.root, self.evidence, self.uid, self.gid = root, evidence, uid, gid
        self.manifest = json.loads((root / "manifest.json").read_text())
        self.namespace = Namespace()
        self.children = {}
        self.child = None
        self.session_pid = None
        self.teardown_errors = []
        self.operation_end = None
        self.before = None
        self.loaded = False
        self.evidence_created = False
        self.cleanup_end = None
        self.commands = []
        self.result = {"outcome": "inconclusive", "started": stamp(), "boot_id": boot_id(),
                       "kernel": platform.release(), "operator_uid": uid, "operator_gid": gid,
                       "namespace": self.namespace.name, "arms": {}, "parser": []}

    def checkpoint(self):
        if self.evidence_created:
            self.result["processes"] = [{"pid": h.pid, "start": h.start} for h in self.children.values()]
            if self.child is not None and self.child.pid not in self.children:
                self.result["processes"].append({"pid": self.child.pid, "start": None,
                                                  "ownership": "direct unreaped Popen child"})
            self.result["process_session"] = self.session_pid
            self.result["teardown_errors"] = list(self.teardown_errors)
            self.result["controller_commands"] = [
                {"session": owner.session_pid, "deadline": owner.cleanup_end,
                 "direct_pid": owner.child.pid if owner.child is not None else None,
                 "processes": [{"pid": h.pid, "start": h.start} for h in owner.children.values()],
                 "errors": list(owner.teardown_errors)} for owner in self.commands]
            self.result["namespace_identity"] = self.namespace.identity
            self.result["namespace_created"] = self.namespace.created
            self.result["namespace_acquired"] = self.namespace.acquired
            self.result["namespace_creation_uncertain"] = self.namespace.creation_uncertain
            temp = self.evidence / ("checkpoint-" + uuid.uuid4().hex + ".tmp")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(self.result, stream, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.evidence / "checkpoint.json")

    def parse(self, arm, operation):
        end = time.monotonic() + 30
        if self.cleanup_end is not None:
            end = min(end, self.cleanup_end)
        remaining(end)
        if operation in ("load", "remove"):
            self.namespace.check()
        # Cleanup must never parse a policy/config/features file that changed after
        # admission. If revalidation fails, still remove the exact held namespace.
        validate_inputs(self.root, self.manifest, deadline=end)
        remaining(end)
        argv = parser_argv(self.root, arm, operation,
                           self.namespace.name if operation in ("load", "remove") else None)
        row = {"argv": argv, "argv_sha256": digest(json.dumps(argv).encode()),
               "inputs": self.manifest["inputs"], "operation": operation, "status": "started"}
        self.result["parser"].append(row)
        if operation == "load":
            self.loaded = True  # A failed load may have installed one profile.
        output = bounded(argv, timeout=remaining(end), limit=COLLECT_LIMIT, deadline=end)
        remaining(end)
        if operation == "preprocess":
            require(digest(output) == self.manifest["preprocessed_sha256"][arm], "preprocessed policy changed")
        row.update(status="passed", output_sha256=digest(output))
        return output

    def reap(self):
        if not self.children and self.child is None and self.session_pid is None:
            require(not self.teardown_errors, "; ".join(self.teardown_errors))
            return
        own_budget = self.cleanup_end is None
        if own_budget:
            self.cleanup_end = time.monotonic() + 30
        end = self.cleanup_end
        child = self.child
        if child is not None and not isinstance(self, CommandOwnership):
            self.session_pid = child.pid

        def attempt(action):
            try:
                return action()
            except BaseException as error:
                message = str(error) if isinstance(error, Inconclusive) else type(error).__name__
                if message not in self.teardown_errors:
                    self.teardown_errors.append(message)
                return None

        def discover():
            for handle in list(self.children.values()):
                attempt(lambda: descendants(handle, self.children, deadline=end))
            if self.session_pid is not None:
                def adopted():
                    remaining(end)
                    entries = Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()
                    require(len(entries) <= 64, "too many adopted processes")
                    for raw in entries:
                        pid = int(raw)
                        if pid not in self.children and (child is None or pid != child.pid):
                            handle = Process(pid)
                            try:
                                sid = os.getsid(pid)
                                command = hasattr(self, "adopted_before")
                                if command and self.adopted_before.get(pid) == handle.start:
                                    continue
                                if not command and sid != self.session_pid:
                                    continue
                                require(int(status(pid)["PPid"]) == os.getpid(), "adopted ownership changed")
                                require(start_time(pid) == handle.start, "adopted PID reused")
                                self.children[pid] = handle
                                if command and sid != self.session_pid:
                                    self.teardown_errors.append("command descendant escaped owned session")
                            finally:
                                if pid not in self.children:
                                    handle.close()
                attempt(adopted)

        def collect():
            if self.child is not None:
                # Popen retains direct-child ownership even if pidfd acquisition
                # failed. Its poll/send_signal/wait never signal an already-reaped PID.
                def direct():
                    if child.poll() is not None:
                        child.wait(timeout=remaining(end))
                        self.child = None
                attempt(direct)
            for pid, handle in list(self.children.items()):
                if child is not None and pid == child.pid and self.child is not None:
                    continue
                if attempt(handle.collect):
                    if attempt(lambda: (handle.close(), True)[1]):
                        del self.children[pid]

        try:
            discover()
            for sig, deadline in ((signal.SIGTERM, min(end, time.monotonic() + getattr(self, "term_grace", 2))),
                                  (signal.SIGKILL, end)):
                while True:
                    if self.child is not None:
                        attempt(lambda: child.send_signal(sig))
                        attempt(lambda: child.send_signal(signal.SIGCONT))
                    for handle in list(self.children.values()):
                        attempt(lambda: handle.send(sig))
                        attempt(lambda: handle.send(signal.SIGCONT))
                    collect()  # Also runs for processes dead before teardown began.
                    discover()  # Intermediary exit can adopt additional children.
                    collect()
                    if not self.children and self.child is None:
                        break
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(min(0.001 if hasattr(self, "adopted_before") else 0.01,
                                   max(0, deadline - time.monotonic())))
                if not self.children and self.child is None:
                    break
        finally:
            if child is not None:
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None:
                        attempt(stream.close)
            # Only resolved handles are closed; unresolved pidfds and identities
            # remain available for bounded retry and exact administrator recovery.
            collect()
        require(not self.children and self.child is None, "owned descendants not proved reaped")
        require(not self.teardown_errors, "; ".join(self.teardown_errors))
        self.session_pid = None
        remaining(end)
        if own_budget:
            self.cleanup_end = None

    def arm(self, name):
        self.parse(name + ".policy", "preprocess")
        self.parse(name + ".policy", "load")
        self.namespace.check()
        profiles = sorted((self.namespace.path / "profiles").iterdir())
        actual = sorted(((p / "name").read_text().strip(), (p / "mode").read_text().strip()) for p in profiles)
        require(actual == [("bwrap", "enforce"), ("unpriv_bwrap", "enforce")], "unexpected loaded arm profiles")
        cursor = journal_cursor()
        begin = stamp()
        end = time.monotonic() + 10
        entry_mnt = os.readlink("/proc/self/ns/mnt")
        argv = ["/usr/bin/aa-exec", "-n", self.namespace.name, "-p", "unconfined", "--", PYTHON,
                "-I", "-S", str(self.root / "codex_apparmor_canary.py"), "__drop",
                str(self.uid), str(self.gid), self.namespace.name, str(end), entry_mnt]
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGHUP, signal.SIGINT})
        try:
            self.child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          close_fds=True, start_new_session=True, env=ENV, bufsize=0,
                                          preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, previous))
            self.session_pid = self.child.pid
            owner = Process(self.child.pid)
            self.children[owner.pid] = owner
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        record = {"begin": begin, "cursor": cursor, "profiles": actual,
                  "trace": [], "audit": [], "go_sent": False, "boot_id": boot_id()}
        self.result["arms"][name] = record
        entry_size = self.entry(owner, end, entry_mnt, record)
        output, errors = bytearray(), bytearray()
        while not output.endswith(b"READY\n"):
            require(time.monotonic() < end and owner.alive(), "outer setup failed or deadline")
            ready, _, _ = select.select([self.child.stdout, self.child.stderr], [], [], 0.02)
            for stream in ready:
                data = os.read(stream.fileno(), 4096)
                require(data, "outer exited before gate")
                (output if stream is self.child.stdout else errors).extend(data)
                require(entry_size + len(output) + len(errors) <= META_LIMIT, "outer metadata overflow")
                require(not errors, "outer setup stderr")
        require(re.fullmatch(rb"PREPARED mnt:\[[0-9]{1,20}\]\nREADY\n", output), "malformed fixture startup")
        prepared = output.splitlines()[0].decode("ascii").removeprefix("PREPARED ")
        require(prepared != entry_mnt, "reported prepared namespace unchanged")
        record["preparation"] = {"mnt": prepared, "provenance": "trusted child self-report; not independently observed",
                                 "primary_evidence": False}
        descendants(owner, self.children, deadline=end)
        workers = [h for h in self.children.values() if h.alive() and
                   Path(f"/proc/{h.pid}/exe").resolve() == Path(PYTHON).resolve()]
        require(len(workers) == 1, "fixed worker identity missing or ambiguous")
        worker = workers[0]
        counters = loss_counters(deadline=end)
        remaining(end)
        record["loss_before"] = counters
        # Attachment, host gates, the primary and final drain share this operation
        # budget. Startup has its own existing 10s bound, propagated to __drop.
        self.operation_end = time.monotonic() + 10
        self.primary(worker, expected_binds(self.root, self.manifest), record)
        record["finish"] = stamp()
        # Drain synthetic diagnostics with a hard limit, without retaining their text.
        self.child.stdin.close()
        for stream in (self.child.stdout, self.child.stderr):
            os.set_blocking(stream.fileno(), False)
        size = entry_size + len(output) + len(errors)
        streams = [self.child.stdout, self.child.stderr]
        while streams or self.child.poll() is None:
            remaining(self.operation_end)
            ready, _, _ = select.select(streams, [], [], min(0.02, remaining(self.operation_end)))
            for stream in ready:
                try:
                    data = os.read(stream.fileno(), 8192)
                except BlockingIOError:
                    continue
                if not data:
                    streams.remove(stream)
                size += len(data)
                require(size <= META_LIMIT, "inner diagnostic overflow")
        remaining(self.operation_end)
        record["diagnostic_bytes"] = size
        record["audit"] = audit_capture(cursor, record["gate"], begin, record["finish"])
        record["capture_finish"] = stamp()
        require(len(json.dumps({"trace": record["trace"], "audit": record["audit"]})) <= COLLECT_LIMIT,
                "combined audit/trace overflow")
        record["loss_after"] = loss_counters()
        require(record["loss_after"].get("lost") == counters.get("lost"), "audit loss counter changed")
        self.reap()
        return record

    def entry(self, owner, end, entry_mnt, record):
        output, errors = bytearray(), bytearray()

        def receive(ready):
            for stream in ready:
                data = os.read(stream.fileno(), 4096)
                require(data, "outer exited before entry acknowledgment")
                (output if stream is self.child.stdout else errors).extend(data)
                require(len(output) + len(errors) <= META_LIMIT, "outer metadata overflow")
                require(b"ENTRY\n".startswith(output) and not errors, "malformed entry marker")

        while output != b"ENTRY\n":
            remaining(end)
            require(owner.alive(), "entry child exited")
            receive(select.select([self.child.stdout, self.child.stderr], [], [], min(0.02, remaining(end)))[0])
        base = Path(f"/proc/{owner.pid}")
        require(owner.pid == self.child.pid and owner.alive(), "entry direct child identity changed")
        observed = {"pid": owner.pid, "start": owner.start,
                    "exe": str((base / "exe").resolve(strict=True)),
                    "user": os.readlink(base / "ns/user"),
                    "mnt": os.readlink(base / "ns/mnt"),
                    "label": (base / "attr/current").read_text().strip(),
                    "provenance": "independent root-controller proc observation"}
        require(observed["exe"] == str(Path(PYTHON).resolve(strict=True)), "wrong entry executable")
        require(observed["user"] == os.readlink("/proc/self/ns/user") == os.readlink("/proc/1/ns/user"),
                "entry user namespace changed")
        require(observed["mnt"] == entry_mnt, "entry mount namespace changed")
        require(observed["label"] == f":{self.namespace.name}:unconfined", "wrong root-view entry label")
        # No poll/wait here: the unreaped direct child reserves its numeric PID.
        receive(select.select([self.child.stdout, self.child.stderr], [], [], 0)[0])
        require(owner.alive() and start_time(owner.pid) == owner.start, "entry child identity changed after observation")
        record["entry"] = observed
        self.checkpoint()
        remaining(end)
        self.child.stdin.write(b"E")
        self.child.stdin.flush()
        record["entry_ack_sent"] = True
        return len(output) + len(errors)

    def primary(self, worker, binds, record):
        observer = Observer(worker, self.children, deadline=self.operation_end)  # Stopped and attached before GO.
        record["gate"] = observe_gate(worker, self.child)
        validate_gate(record["gate"], self.uid, self.gid, self.namespace.name, binds)
        observer.expected_label = record["gate"]["label"]
        self.checkpoint()

        def go():
            if self.operation_end is not None:
                remaining(self.operation_end)
            require(worker.alive(), "worker identity changed before GO")
            self.child.stdin.write(b"G")
            self.child.stdin.flush()
            record["go_sent"] = True

        record["trace"] = observer.run(go)
        record["exit_codes"] = observer.exits

    def reap_commands(self):
        errors = []
        for owner in list(self.commands):
            try:
                owner.reap()  # Retains the command's original absolute deadline.
                self.commands.remove(owner)
            except BaseException as error:
                errors.append(str(error) if isinstance(error, Inconclusive) else type(error).__name__)
        require(not self.commands and not errors, "controller commands unresolved: " + "; ".join(errors))

    def run(self):
        token = COMMAND_OWNERS.set(self.commands)
        try:
            return self._run()
        finally:
            COMMAND_OWNERS.reset(token)

    def _run(self):
        try:
            protected(self.root, directory=True)
            require(self.evidence.parent.is_dir(), "missing protected evidence parent")
            protected(self.evidence.parent, directory=True)
            self.evidence.mkdir(mode=0o700)
            self.evidence_created = True
            protected(self.evidence, directory=True)
            require(os.getuid() == 0 and os.geteuid() == 0 and self.uid > 0 and self.gid > 0, "nonzero operator and root controller required")
            require(Path("/proc/self/attr/current").read_text().strip() == "unconfined", "inherited controller confinement")
            require(os.readlink("/proc/self/ns/user") == os.readlink("/proc/1/ns/user"), "controller not in host user namespace")
            validate_inputs(self.root, self.manifest)
            self.result["manifest_sha256"] = file_digest(self.root / "manifest.json")
            self.result["inputs"] = self.manifest
            journal_cursor()
            # Require child reaping even if a bwrap intermediary exits first.
            prctl(36, 1)  # PR_SET_CHILD_SUBREAPER
            self.before = root_policy()
            self.result["root_before"] = self.before
            for arm in POLICY_HASHES:
                self.parse(arm, "compile")
            self.checkpoint()
            self.namespace.create()
            self.result["namespace_identity"] = self.namespace.identity
            self.checkpoint()
            baseline = self.arm("baseline")
            if attributed(baseline):
                self.result["outcome"] = outcome(baseline, self.arm("candidate"))
            else:
                self.result["reason"] = "baseline attribution absent; candidate not run"
        except BaseException as error:
            self.result.update(outcome="inconclusive", reason=str(error) if isinstance(error, Inconclusive) else type(error).__name__)
        finally:
            if self.cleanup_end is None:
                self.cleanup_end = time.monotonic() + 30
            cleanup = {"status": "failed", "owned_target": str(self.namespace.path)
                       if self.namespace.created or self.namespace.creation_uncertain else None}
            self.result["cleanup"] = cleanup
            try:
                previous = signal.pthread_sigmask(signal.SIG_BLOCK, CANCELLATION)
                try:
                    try:
                        self.reap_commands()
                    finally:
                        self.reap()
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, previous)
                require(not self.namespace.creation_uncertain, "namespace creation ownership unresolved")
                if self.namespace.created:
                    try:
                        if self.loaded:
                            self.parse("baseline.policy", "remove")
                    finally:
                        self.reap_commands()
                        self.namespace.remove()
                    require(not self.namespace.path.exists(), "namespace absence unproven")
                if self.before is not None:
                    remaining(self.cleanup_end)
                    after = root_policy(deadline=self.cleanup_end)
                    self.result["root_after"] = after
                    require(after == self.before, "global policy changed; no automatic repair")
                self.reap_commands()
                remaining(self.cleanup_end)
                cleanup["status"] = "passed"
            except BaseException as error:
                cleanup["reason"] = str(error) if isinstance(error, Inconclusive) else type(error).__name__
                self.result["outcome"] = "inconclusive"
            self.result["finished"] = stamp()
            self.checkpoint()
            # Never overwrite an existing result or write through an evidence symlink.
            if self.evidence_created:
                protected(self.evidence, directory=True)
                fd = os.open(self.evidence / "result.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as stream:
                    json.dump(self.result, stream, indent=2, sort_keys=True)
                    stream.write("\n")
        return self.result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "__drop":
        require(len(argv) == 6, "invalid internal entry")
        trampoline(Path(__file__).parent, int(argv[1]), int(argv[2]), argv[3], float(argv[4]), argv[5])
        return 125
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rendering = commands.add_parser("render")
    rendering.add_argument("--out", type=Path, required=True)
    running = commands.add_parser("run")
    running.add_argument("--operator-uid", type=int, required=True)
    running.add_argument("--operator-gid", type=int, required=True)
    running.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "render":
        render(args.out)
        return 0
    require(args.operator_uid > 0 and args.operator_gid > 0, "nonzero operator required")
    require(os.getuid() == 0 and os.geteuid() == 0, "administrator authorization required")
    require(sys.flags.isolated and sys.flags.no_site, "invoke protected helper with -I -S")
    def cancelled(signum, frame):
        raise Inconclusive("cancelled by signal " + str(signum))

    previous = {sig: signal.signal(sig, cancelled) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        result = Experiment(Path(__file__).parent, args.evidence, args.operator_uid, args.operator_gid).run()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(json.dumps({"outcome": result["outcome"], "cleanup": result["cleanup"]}))
    return 0 if result["outcome"] != "inconclusive" and result["cleanup"]["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Inconclusive as error:
        print("inconclusive: " + str(error), file=sys.stderr)
        raise SystemExit(1)
