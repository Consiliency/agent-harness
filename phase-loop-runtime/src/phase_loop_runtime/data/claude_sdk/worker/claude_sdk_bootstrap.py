"""The trusted bootstrap of the ``sdk`` transport's host worker (SEATS CLAUDE SL-3).

Started by the owned launcher as ``<worker-python> -I -S -B claude_sdk_bootstrap.py IN OUT``,
where ``IN`` and ``OUT`` are the numbers of the two inherited anonymous pipe ends that are
the worker's only channel to its parent. Isolated mode, no site processing and no bytecode
writes: no project, user or ``.pth`` path is ever read.

In order, before anything outside the standard library is imported:

1. read the parent's bounded ``hello`` frame (the per-launch nonce, the syscall filter, the
   approved closure roots and their exhaustive file inventory, the sealed prompt and the
   frozen public configuration);
2. install the delivered syscall filter in this process (fail-closed: no filter, no worker);
3. verify every file under the approved roots against the inventory -- an unlisted file, a
   ``.pth``, any bytecode or ``__pycache__`` entry, a symlink or a digest mismatch refuses;
4. refuse a preloaded module whose origin is outside the trusted standard library;
5. restrict imports to the standard library, this payload and the verified roots, source
   and extension modules only, never reading bytecode; then load ``claude_sdk_worker``
   from this directory.

Every failure is reduced to one closed code on the channel; no exception text leaves the
process. This file imports only the standard library.
"""

import base64
import hashlib
import json
import os
import stat
import sys

FRAME_SCHEMA = 1
#: The hello carries the inventory, so its cap is the largest of any frame.
HELLO_CAP_BYTES = 8 << 20
FRAME_CAP_BYTES = 16 << 20
NESTING_BOUND = 64
#: The codes a worker may report; the parent maps each to a typed transport code.
FAILURE_CODES = frozenset({
    "worker_prerequisite_missing", "filter_install_failed", "closure_unverified",
    "closure_missing", "preloaded_origin", "protocol_violation", "timer_invalid",
    "dependency_missing", "session_failed",
})
#: Installer metadata allowed beside a verified distribution without a digest.
INSTALLER_METADATA = frozenset({"INSTALLER", "RECORD", "REQUESTED", "direct_url.json",
                                "uv_cache.json"})
_PR_SET_NO_NEW_PRIVS = 38
_SECCOMP_SET_MODE_FILTER = 1
_SECCOMP_FILTER_FLAG_TSYNC = 1
_SYS_SECCOMP = {"x86_64": 317}


class BootstrapRefused(Exception):
    """A closed failure code; never carries detail."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code if code in FAILURE_CODES else "protocol_violation"


# -- strict frames --------------------------------------------------------------------

def _depth(raw, bound):
    depth = deepest = 0
    in_string = escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            if depth > deepest:
                deepest = depth
                if deepest > bound:
                    return deepest
        elif byte in (0x5D, 0x7D):
            depth -= 1
    return deepest


def _unique(pairs):
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise BootstrapRefused("protocol_violation")
    return dict(pairs)


def parse_frame(raw):
    """One frame: strict UTF-8, bounded depth, no duplicate key anywhere, an object."""
    if _depth(raw, NESTING_BOUND) > NESTING_BOUND:
        raise BootstrapRefused("protocol_violation")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise BootstrapRefused("protocol_violation") from None
    if not isinstance(value, dict):
        raise BootstrapRefused("protocol_violation")
    return value


def encode_frame(value):
    """The one encoding both ends use: ASCII JSON, sorted keys, no whitespace, one line."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii") + b"\n"


class Channel:
    """The worker's end of the IPC pipe pair. Frames carry the launch nonce and a monotonic
    sequence number in each direction; a cross-leg, replayed or out-of-order frame refuses."""

    parse = staticmethod(parse_frame)

    def __init__(self, in_fd, out_fd):
        self.in_fd = in_fd
        self.out_fd = out_fd
        self.nonce = None
        self.sent = 0
        self.received = 0
        self._buffer = bytearray()
        self.closed = False

    def _line(self, cap):
        while True:
            end = self._buffer.find(b"\n")
            if end >= 0:
                line = bytes(self._buffer[:end])
                del self._buffer[:end + 1]
                return line
            if len(self._buffer) > cap:
                raise BootstrapRefused("protocol_violation")
            chunk = os.read(self.in_fd, 1 << 16)
            if not chunk:
                return None
            self._buffer.extend(chunk)

    def take(self, line):
        """Check one parent frame's envelope; returns ``(kind, body)``."""
        frame = parse_frame(line)
        if set(frame) != {"launch", "seq", "kind", "body"}:
            raise BootstrapRefused("protocol_violation")
        if (frame["launch"] != self.nonce or type(frame["seq"]) is not int
                or frame["seq"] != self.received or not isinstance(frame["kind"], str)):
            raise BootstrapRefused("protocol_violation")
        self.received += 1
        return frame["kind"], frame["body"]

    def read_hello(self):
        line = self._line(HELLO_CAP_BYTES)
        if line is None:
            raise BootstrapRefused("protocol_violation")
        frame = parse_frame(line)
        nonce = frame.get("launch")
        if (set(frame) != {"launch", "seq", "kind", "body"} or frame.get("kind") != "hello"
                or frame.get("seq") != 0 or not isinstance(nonce, str)
                or len(nonce) != 64 or not nonce.isascii()
                or any(c not in "0123456789abcdef" for c in nonce)
                or not isinstance(frame.get("body"), dict)):
            raise BootstrapRefused("protocol_violation")
        self.nonce = nonce
        self.received = 1
        return frame["body"]

    def read(self):
        """The next parent frame as ``(kind, body)``, or ``None`` at EOF."""
        line = self._line(FRAME_CAP_BYTES)
        if line is None:
            return None
        return self.take(line)

    def send(self, kind, body):
        if self.closed:
            raise BootstrapRefused("protocol_violation")
        data = encode_frame({"launch": self.nonce, "seq": self.sent, "kind": kind, "body": body})
        if len(data) > FRAME_CAP_BYTES:
            raise BootstrapRefused("protocol_violation")
        self.sent += 1
        view = memoryview(data)
        while view:
            written = os.write(self.out_fd, view)
            view = view[written:]

    def fail(self, code):
        try:
            if self.nonce is not None and not self.closed:
                self.send("failed", {"code": code if code in FAILURE_CODES
                                     else "protocol_violation"})
        except (OSError, BootstrapRefused):
            pass
        self.closed = True


# -- the syscall filter ---------------------------------------------------------------

def install_filter(program, machine):
    """Install the delivered filter on every thread of this process, after setting
    no-new-privileges. Any failure raises; the caller refuses startup."""
    import ctypes

    number = _SYS_SECCOMP.get(machine)
    if number is None or not program or len(program) % 8 or len(program) // 8 > 4096:
        raise BootstrapRefused("filter_install_failed")

    class _Fprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    libc = ctypes.CDLL(None, use_errno=True)
    buffer = ctypes.create_string_buffer(program, len(program))
    fprog = _Fprog(len(program) // 8, ctypes.cast(buffer, ctypes.c_void_p))
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise BootstrapRefused("filter_install_failed")
    if libc.syscall(number, _SECCOMP_SET_MODE_FILTER, _SECCOMP_FILTER_FLAG_TSYNC,
                    ctypes.byref(fprog)) != 0:
        raise BootstrapRefused("filter_install_failed")


# -- the closure ----------------------------------------------------------------------

def _hash_file(path):
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _forbidden_name(name):
    return (name == "__pycache__" or name.endswith((".pyc", ".pyo", ".pth"))
            or name.startswith("_virtualenv"))


def verify_closure(roots, inventory, excluded):
    """Every regular file under every root is in ``inventory`` (``relpath -> sha256``),
    each inventory entry exists and matches, and nothing else is present except installer
    metadata inside ``*.dist-info`` and the ``excluded`` paths, which the parent hashes once
    per installation snapshot. ``relpath`` is ``<root index>/<path>``."""
    if (not isinstance(roots, list) or not roots or not isinstance(inventory, dict)
            or not isinstance(excluded, list)):
        raise BootstrapRefused("closure_unverified")
    seen = set()
    for index, root in enumerate(roots):
        if not isinstance(root, str) or not os.path.isabs(root):
            raise BootstrapRefused("closure_unverified")
        try:
            info = os.lstat(root)
        except OSError:
            raise BootstrapRefused("closure_missing") from None
        if not stat.S_ISDIR(info.st_mode):
            raise BootstrapRefused("closure_unverified")
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            for name in (*dirnames, *filenames):
                if _forbidden_name(name):
                    raise BootstrapRefused("closure_unverified")
            for name in dirnames:
                if stat.S_ISLNK(os.lstat(os.path.join(directory, name)).st_mode):
                    raise BootstrapRefused("closure_unverified")
            for name in filenames:
                path = os.path.join(directory, name)
                info = os.lstat(path)
                if not stat.S_ISREG(info.st_mode):
                    raise BootstrapRefused("closure_unverified")
                rel = f"{index}/{os.path.relpath(path, root)}"
                parent = os.path.basename(directory)
                if rel in inventory:
                    if _hash_file(path) != inventory[rel]:
                        raise BootstrapRefused("closure_unverified")
                    seen.add(rel)
                elif rel in excluded:
                    seen.add(rel)
                elif not (parent.endswith(".dist-info") and name in INSTALLER_METADATA):
                    raise BootstrapRefused("closure_unverified")
    if set(inventory) - seen or set(excluded) - seen:
        raise BootstrapRefused("closure_missing")


def _trusted_stdlib(paths):
    return tuple(os.path.realpath(p) for p in paths if os.path.isdir(p))


def _inside(origin, roots):
    real = os.path.realpath(origin)
    return any(real == root or real.startswith(root + os.sep) for root in roots)


def check_preloaded(stdlib):
    """A module already loaded must be built in, frozen or from the trusted stdlib."""
    for module in list(sys.modules.values()):
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None) if spec is not None else None
        if origin in (None, "built-in", "frozen"):
            continue
        if not _inside(origin, stdlib):
            raise BootstrapRefused("preloaded_origin")


class _GuardedFinder:
    """The only path-based finder: source and extension modules under the allowed roots."""

    def __init__(self, allowed):
        import importlib.machinery as machinery

        self._machinery = machinery
        self._allowed = allowed

    def find_spec(self, name, path=None, target=None):
        spec = self._machinery.PathFinder.find_spec(name, path, target)
        if spec is None:
            return None
        loader = spec.loader
        origin = spec.origin
        if origin is None and spec.submodule_search_locations is not None:
            # A namespace package (``opentelemetry``): every portion inside the roots.
            locations = list(spec.submodule_search_locations)
            if not locations or not all(_inside(p, self._allowed) for p in locations):
                raise ImportError("a namespace portion outside the verified roots")
            return spec
        if not isinstance(loader, (self._machinery.SourceFileLoader,
                                   self._machinery.ExtensionFileLoader)):
            raise ImportError("only source and extension modules are imported")
        if origin is None or not _inside(origin, self._allowed):
            raise ImportError("a module outside the verified roots")
        return spec

    def find_distributions(self, *args, **kwargs):
        # Distribution metadata is read from the same path, which holds only the verified
        # roots and the standard library.
        return self._machinery.PathFinder.find_distributions(*args, **kwargs)


def restrict_imports(stdlib, payload, roots):
    import importlib.machinery as machinery

    allowed = tuple(dict.fromkeys((*stdlib, os.path.realpath(payload),
                                   *(os.path.realpath(r) for r in roots))))
    sys.path[:] = [*stdlib, payload, *roots]
    sys.path_importer_cache.clear()
    sys.dont_write_bytecode = True
    sys.meta_path[:] = [machinery.BuiltinImporter, machinery.FrozenImporter,
                        _GuardedFinder(allowed)]


def load_payload_module(name, payload):
    import importlib.machinery as machinery
    import importlib.util as util

    spec = machinery.PathFinder.find_spec(name, [payload])
    if (spec is None or not isinstance(spec.loader, machinery.SourceFileLoader)
            or os.path.dirname(os.path.realpath(spec.origin)) != os.path.realpath(payload)):
        raise BootstrapRefused("closure_unverified")
    module = util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _descriptor(text):
    if not text.isascii() or not text.isdigit() or len(text) > 6:
        raise BootstrapRefused("protocol_violation")
    return int(text)


#: Bytecode is looked up only under this prefix, which can never be a directory, so an
#: adjacent ``__pycache__`` -- an installer's byte-compiled payload included -- is never
#: read: every module the worker imports is compiled from its verified source.
NO_BYTECODE_PREFIX = "/dev/null/claude-sdk-worker"


def main(argv):
    sys.pycache_prefix = NO_BYTECODE_PREFIX
    sys.dont_write_bytecode = True
    if len(argv) != 3:
        return 2
    try:
        channel = Channel(_descriptor(argv[1]), _descriptor(argv[2]))
    except BootstrapRefused:
        return 2
    try:
        hello = channel.read_hello()
        machine = os.uname().machine
        program = base64.b64decode(hello.get("filter", ""), validate=True)
        install_filter(program, machine)
        payload = os.path.dirname(os.path.realpath(__file__))
        stdlib = _trusted_stdlib(sys.path)
        roots = hello.get("roots")
        verify_closure(roots, hello.get("inventory"), hello.get("excluded"))
        check_preloaded(stdlib)
        restrict_imports(stdlib, payload, roots)
        worker = load_payload_module("claude_sdk_worker", payload)
        return worker.run(channel, hello)
    except BootstrapRefused as refusal:
        channel.fail(refusal.code)
        return 3
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        channel.fail("closure_unverified")
        return 3
    except BaseException:
        channel.fail("session_failed")
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
