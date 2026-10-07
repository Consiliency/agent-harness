"""Test-only launch inventory and regression check; never a runtime boundary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import sys
import threading
import ast
from collections import Counter


PROVIDERS = frozenset({"codex", "claude", "grok", "agy", "gemini", "opencode"})
_local = threading.local()
_which = shutil.which


def static_references(source):
    """Count references, including defaults and partials, by lexical owner."""
    tree = ast.parse(source)
    primitives = {
        'subprocess.Popen', 'subprocess.run', 'subprocess.call',
        'subprocess.check_call', 'subprocess.check_output', 'subprocess.getoutput',
        'subprocess.getstatusoutput', '_posixsubprocess.fork_exec',
        'pty.fork', 'pty.spawn', 'os.fork', 'os.forkpty', 'os.system', 'os.popen',
        'os.posix_spawn', 'os.posix_spawnp', 'os.spawnv', 'os.spawnve',
        'os.spawnvp', 'os.spawnvpe', 'os.spawnl', 'os.spawnle', 'os.spawnlp',
        'os.spawnlpe', 'os.execl', 'os.execle', 'os.execlp', 'os.execlpe',
        'os.execv', 'os.execve', 'os.execvp', 'os.execvpe',
        'multiprocessing.Process', 'multiprocessing.Pool',
        'ctypes.CDLL', 'ctypes.PyDLL', 'ctypes.cdll', 'ctypes.pydll',
        'cffi.FFI', 'concurrent.futures.ProcessPoolExecutor',
    }
    seams = {'launch_owned', 'launch_provider', 'run_provider'}
    io = {'read_text', 'read_bytes', 'open', 'glob', 'rglob', 'stat', 'lstat'}
    aliases = {}

    def qualified(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + '.' + node.attr
        return ''

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = (node.module or '') + '.' + item.name
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and qualified(node.value) in primitives:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases[target.id] = qualified(node.value)
    counts = Counter()

    class References(ast.NodeVisitor):
        owner = []

        def visit_FunctionDef(self, node):
            self.owner.append(node.name)
            self.generic_visit(node)
            self.owner.pop()

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

        def record(self, primitive):
            counts[('.'.join(self.owner) or '<module>', primitive)] += 1

        def visit_Attribute(self, node):
            name = qualified(node)
            if name in primitives:
                self.record(name)
            elif node.attr in seams:
                self.record(node.attr)
            self.generic_visit(node)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                name = qualified(node)
                if name in primitives or name.rsplit('.', 1)[-1] in seams:
                    self.record(name if name in primitives else name.rsplit('.', 1)[-1])

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr in io:
                self.record('io.' + node.func.attr)
            elif isinstance(node.func, ast.Name) and node.func.id == 'open':
                self.record('io.open')
            self.generic_visit(node)

        def visit_Import(self, node):
            for item in node.names:
                if item.name in {'ctypes', 'cffi', 'multiprocessing'}:
                    self.record('import.' + item.name)

        def visit_ImportFrom(self, node):
            if node.module in {'ctypes', 'cffi', 'multiprocessing'}:
                self.record('import.' + node.module)

    References().visit(tree)
    return counts


def provider_executable(executable, env=None, hashes=()):
    if isinstance(executable, int) or executable is None:
        return False
    name = os.fsdecode(executable)
    if Path(name).name in PROVIDERS:
        return True
    resolved = _which(name, path=(env or os.environ).get("PATH"))
    if resolved is None or not hashes:
        return False
    digest = hashlib.sha256()
    with open(resolved, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() in hashes


_TOLERATED = [0]


def _tolerated():
    return _TOLERATED[0] > 0


class tolerate_unowned:
    """Within this block an unowned provider start is recorded, not failed. Only for a test
    whose subject is ANOTHER launch guard and that starts such a launch on purpose (the
    agent-harness#1147 scratch-hook falsifiers)."""

    def __enter__(self):
        _TOLERATED[0] += 1
        return self

    def __exit__(self, *exc):
        _TOLERATED[0] -= 1
        return False


_INSTALLED_ALLOWED = [0]


class allow_installed_inference:
    """Within this block the installed provider may run for inference. Only for the opt-in
    live jailed-seat test, whose purpose is to run the real CLI inside the host's jail
    (agent-harness#1282). ``node`` is the calling pytest item; anything but an item marked
    ``host_seat_credentials`` is refused, so no ordinary test can enable it."""

    def __init__(self, node=None):
        marker = getattr(node, "get_closest_marker", None)
        if marker is None or marker("host_seat_credentials") is None:
            raise RuntimeError(
                "installed-inference exemption refused: only a test marked "
                "host_seat_credentials may run the installed provider")

    def __enter__(self):
        _INSTALLED_ALLOWED[0] += 1
        return self

    def __exit__(self, *exc):
        _INSTALLED_ALLOWED[0] -= 1
        return False


def install(path, *, fail=False, hashes=(), native_inference_hashes=()):
    """Record executable/caller metadata only, without arguments or environment."""
    hashes = set(hashes)
    for provider in PROVIDERS:
        executable = shutil.which(provider)
        if executable is not None:
            digest = hashlib.sha256()
            with open(executable, "rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            hashes.add(digest.hexdigest())
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    closed = False
    native_inference_hashes = frozenset(native_inference_hashes)
    image_cache = {}

    def installed_inference(argv):
        if not native_inference_hashes or not isinstance(argv, (list, tuple)):
            return False
        words = [os.fsdecode(word) for word in argv if isinstance(word, (str, bytes))]
        if not any(word in {'exec', '-p', '-m', '--print', '--model'} or
                   word.startswith(('--model=', '--print=')) for word in words):
            return False
        sources = words[:1]
        sources.extend(words[index + 1] for index, word in enumerate(words[:-1])
                       if word in {'--ro-bind', '--ro-bind-data'})
        for source in sources:
            if source.isdecimal():
                source = '/proc/self/fd/' + source
            try:
                info = os.stat(source)
                identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                digest = image_cache.get(identity)
                if digest is None:
                    with open(source, 'rb') as image:
                        content = hashlib.sha256()
                        for block in iter(lambda: image.read(1024 * 1024), b''):
                            content.update(block)
                        digest = content.hexdigest()
                    image_cache[identity] = digest
                if digest in native_inference_hashes:
                    return True
            except OSError:
                continue
        return False

    def observe(event, args):
        if closed or getattr(_local, "observing", False):
            return
        if event not in {"subprocess.Popen", "os.exec", "os.posix_spawn", "os.spawn",
                         "os.system", "seat_test.fork_exec", "seat_test.fork",
                         "seat_test.forkpty", "seat_test.pty_fork"}:
            return
        _local.observing = True
        try:
            executable = args[0] if args else None
            if event == "seat_test.fork_exec":
                executable = args[1][0] if len(args) > 1 and args[1] else None
            elif event == "os.system":
                try:
                    words = shlex.split(os.fsdecode(executable))
                    executable = words[0] if words else None
                except ValueError:
                    executable = None
            env = args[3] if event == "subprocess.Popen" else (
                args[2] if event in {"os.exec", "os.posix_spawn"} else None
            )
            provider = provider_executable(executable, env, hashes)
            module = sys.modules.get("phase_loop_runtime.panel_invoker")
            marker = getattr(module, "_OWNED_LAUNCH", None)
            owned = marker is not None and marker.get(False)
            frame = sys._getframe(1)
            while frame is not None and (frame.f_code.co_filename == __file__ or
                                        frame.f_globals.get("__name__") in {"subprocess", "os"}):
                frame = frame.f_back
            record = {
                "pid": os.getpid(), "event": event,
                "executable": Path(os.fsdecode(executable)).name if isinstance(executable, (str, bytes)) else None,
                "provider": provider, "owned": owned,
                "module": frame.f_globals.get("__name__") if frame is not None else None,
                "function": frame.f_code.co_name if frame is not None else None,
            }
            os.write(descriptor, (json.dumps(record, sort_keys=True) + "\n").encode())
            if (event == 'subprocess.Popen' and not _INSTALLED_ALLOWED[0]
                    and installed_inference(args[1])):
                raise RuntimeError('test selected an installed provider for inference; use a fixture CLI')
            if fail and provider and not owned and not _tolerated():
                raise RuntimeError("provider launch lacks the owned launch marker")
        finally:
            _local.observing = False

    sys.addaudithook(observe)

    def wrap(original, event, executable=None):
        def audited(*args, **kwargs):
            sys.audit(event, *(args if executable is None else (executable,)))
            return original(*args, **kwargs)
        return audited

    import _posixsubprocess
    import pty

    _posixsubprocess.fork_exec = wrap(_posixsubprocess.fork_exec, "seat_test.fork_exec")
    os.fork = wrap(os.fork, "seat_test.fork")
    os.forkpty = wrap(os.forkpty, "seat_test.forkpty")
    pty.fork = wrap(pty.fork, "seat_test.pty_fork")

    def close():
        nonlocal closed
        if not closed:
            closed = True
            os.close(descriptor)

    return close
