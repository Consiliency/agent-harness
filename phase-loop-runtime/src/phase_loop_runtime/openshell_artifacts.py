"""Bounded source and quarantine primitives. Nothing here accepts or publishes edits.

All limits are explicit caller policy inputs. Git runs with a new config/object view;
repository hooks, filters, remotes and ambient environment are never imported.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import tempfile
import time
import zlib
from dataclasses import asdict, dataclass, field
from typing import Callable


class Refused(ValueError):
    """Input-free code only; never format untrusted output or credential material."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def decode(data: bytes, cap: int) -> dict:
    if len(data) > cap:
        raise Refused("envelope_limit")
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise Refused("duplicate_field")
            out[key] = value
        return out
    try:
        value = json.loads(data, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Refused("number")))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused("envelope_invalid") from None
    if not isinstance(value, dict):
        raise Refused("envelope_invalid")
    return value


@dataclass(frozen=True)
class Limits:
    source_bytes: int
    file_bytes: int
    files: int
    patch_bytes: int
    output_bytes: int

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in asdict(self).values()):
            raise Refused("limits_invalid")


@dataclass(frozen=True)
class Bound:
    end: float
    cancelled: Callable[[], bool] = field(repr=False, compare=False)

    def check(self) -> float:
        if self.cancelled():
            raise Refused("cancelled")
        left = self.end - time.monotonic()
        if not math.isfinite(left) or left <= 0:
            raise Refused("end_reached")
        return left


def run_process(argv: tuple[str, ...], *, cwd: Path, env: dict[str, str],
                data: bytes, cap: int, bound: Bound,
                pass_fds: tuple[int, ...] = ()) -> tuple[int, bytes, bytes]:
    """Bound pipes and kill the process group even after leader exit.

    This is a supervisor primitive, NOT isolation: setsid descendants can escape.
    An endpoint-owned isolation adapter must supply the destruction barrier.
    """
    bound.check()
    if cap <= 0 or not Path(argv[0]).is_absolute():
        raise Refused("launch_invalid")
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            close_fds=True, pass_fds=pass_fds, start_new_session=True)
    streams = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    offset = 0
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        os.set_blocking(proc.stdin.fileno(), False)
        if data:
            selector.register(proc.stdin, selectors.EVENT_WRITE)
        else:
            proc.stdin.close()
        while selector.get_map() or proc.poll() is None:
            left = bound.check()
            for key, _ in selector.select(min(left, 0.05)):
                stream = key.fileobj
                if stream is proc.stdin:
                    try:
                        offset += os.write(stream.fileno(), data[offset:offset + 4096])
                    except BrokenPipeError:
                        offset = len(data)
                    if offset == len(data):
                        selector.unregister(stream)
                        stream.close()
                else:
                    chunk = os.read(stream.fileno(), min(65536, cap + 1))
                    if not chunk:
                        selector.unregister(stream)
                    streams[stream].extend(chunk)
                    if sum(map(len, streams.values())) > cap:
                        raise Refused("output_limit")
        bound.check()
        return proc.returncode, bytes(streams[proc.stdout]), bytes(streams[proc.stderr])
    finally:
        selector.close()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # No unbounded wait on an uninterruptible child. Endpoint teardown is still owed.
        try:
            proc.wait(timeout=max(0.001, min(0.1, bound.end - time.monotonic())))
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()


def git(root: Path, *args: str, bound: Bound, cap: int, data: bytes = b"") -> bytes:
    env = {"PATH": "/usr/bin:/bin", "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
           "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
    rc, out, _ = run_process(("/usr/bin/git", "-c", "core.hooksPath=/dev/null",
                              "-c", "core.attributesFile=/dev/null", *args),
                             cwd=root, env=env, data=data, cap=cap, bound=bound)
    if rc:
        raise Refused("git_refused")
    return out


def safe_path(path: str) -> str:
    if (not isinstance(path, str) or not path or len(path) > 4096 or
            any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or
                part in (".", "..") or part.lower() in
                (".git", ".gitmodules", ".gitattributes") or
                part.lower().startswith(".git~")
                for part in path.split("/"))):
        raise Refused("path_unsupported")
    return path


@dataclass(frozen=True)
class SourceFile:
    path: str
    mode: int
    data: bytes = field(repr=False)

    def manifest(self) -> dict:
        return {"path": self.path, "mode": self.mode, "size": len(self.data),
                "sha256": digest(self.data)}


@dataclass(frozen=True)
class SourceBundle:
    base: str
    tree: str
    files: tuple[SourceFile, ...]
    owned_paths: tuple[str, ...]
    limits: Limits

    @property
    def manifest(self) -> dict:
        return {"base": self.base, "tree": self.tree,
                "files": [f.manifest() for f in self.files],
                "owned_paths": self.owned_paths, "limits": asdict(self.limits)}

    @property
    def sha256(self) -> str:
        return digest(canonical(self.manifest))

    def validate(self):
        if not all(re.fullmatch(r"[0-9a-f]{40}", x) for x in (self.base, self.tree)):
            raise Refused("object_format_unsupported")
        if not self.owned_paths or len(set(self.owned_paths)) != len(self.owned_paths):
            raise Refused("ownership_invalid")
        for path in self.owned_paths:
            safe_path(path)
        if len(self.files) > self.limits.files:
            raise Refused("source_limit")
        seen = set()
        total = 0
        for entry in self.files:
            safe_path(entry.path)
            if entry.path in seen or entry.mode not in (0o100644, 0o100755):
                raise Refused("entry_unsupported")
            seen.add(entry.path)
            if len(entry.data) > self.limits.file_bytes:
                raise Refused("file_limit")
            if entry.data.startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise Refused("lfs_unsupported")
            total += len(entry.data)
        if total > self.limits.source_bytes:
            raise Refused("source_limit")
        if any(str(parent) in seen for p in seen for parent in Path(p).parents if str(parent) != "."):
            raise Refused("path_conflict")


def scan(root: Path, limits: Limits, bound: Bound) -> tuple[SourceFile, ...]:
    """Private, quiescent directory only; no concurrent untrusted writer permitted."""
    result = []
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        bound.check()
        if Path(directory) == root:
            dirs[:] = [d for d in dirs if d != ".git"]
            files = [f for f in files if f != ".git"]
        for name in dirs:
            path = Path(directory) / name
            safe_path(path.relative_to(root).as_posix())
            if not stat.S_ISDIR(path.lstat().st_mode):
                raise Refused("link_unsupported")
        for name in files:
            path = Path(directory) / name
            relative = safe_path(path.relative_to(root).as_posix())
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                    info.st_mode & 0o7022 or info.st_size > limits.file_bytes):
                raise Refused("file_unsupported")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                current = os.fstat(stream.fileno())
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    raise Refused("source_changed")
                data = stream.read(limits.file_bytes + 1)
            total += len(data)
            if len(data) > limits.file_bytes or total > limits.source_bytes:
                raise Refused("source_limit")
            result.append(SourceFile(relative, 0o100755 if info.st_mode & 0o111 else 0o100644, data))
            if len(result) > limits.files:
                raise Refused("source_limit")
    return tuple(sorted(result, key=lambda f: f.path))


def init_tree(root: Path, bundle: SourceBundle, bound: Bound):
    """Create a new disposable tree; never accepts an existing checkout."""
    bundle.validate()
    root.mkdir(mode=0o700)
    git(root, "init", "--template=", "--object-format=sha1", bound=bound, cap=bundle.limits.output_bytes)
    for entry in bundle.files:
        bound.check()
        path = root / entry.path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(entry.data)
            os.fchmod(stream.fileno(), entry.mode & 0o777)
    stage_files(root, bundle.files, bundle.limits, bound)
    git(root, "update-index", "--refresh", bound=bound, cap=bundle.limits.output_bytes)
    tree = git(root, "write-tree", bound=bound, cap=bundle.limits.output_bytes).decode().strip()
    if tree != bundle.tree:
        raise Refused("tree_mismatch")


def stage_files(root: Path, files: tuple[SourceFile, ...], limits: Limits, bound: Bound):
    git(root, "read-tree", "--empty", bound=bound, cap=limits.output_bytes)
    for entry in files:
        oid = git(root, "hash-object", "-w", "--stdin", data=entry.data,
                  bound=bound, cap=limits.output_bytes).decode().strip()
        git(root, "update-index", "--add", "--cacheinfo", f"{entry.mode:o},{oid},{entry.path}",
            bound=bound, cap=limits.output_bytes)


def prepare_source(repo: Path, base: str, owned_paths: tuple[str, ...],
                   limits: Limits, bound: Bound) -> SourceBundle:
    """Require exact clean HEAD (including ignored files), no overlays or filters.

    Reads raw Git objects through a disposable object view; never loads repo config.
    Only SHA-1 repositories and ordinary index files are supported in this slice.
    """
    bound.check()
    def metadata(path: Path) -> str:
        bound.check()
        with path.open("rb") as stream:
            raw = stream.read(limits.output_bytes + 1)
        if len(raw) > limits.output_bytes:
            raise Refused("metadata_limit")
        return raw.decode("utf-8")
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise Refused("base_invalid")
    marker = repo / ".git"
    if marker.is_symlink():
        raise Refused("git_metadata_unsupported")
    if marker.is_file():
        raw = metadata(marker)
        if not raw.startswith("gitdir: "):
            raise Refused("git_metadata_unsupported")
        gitdir = (repo / raw[8:].strip()).resolve(strict=True)
    else:
        gitdir = marker.resolve(strict=True)
    common = gitdir
    if (gitdir / "commondir").exists():
        common = (gitdir / metadata(gitdir / "commondir").strip()).resolve(strict=True)
    if "\n" in str(common) or "\r" in str(common):
        raise Refused("git_metadata_unsupported")
    head = metadata(gitdir / "HEAD").strip()
    if head.startswith("ref: "):
        ref = head[5:]
        safe_path(ref)
        if (common / ref).is_file():
            head = metadata(common / ref).strip()
        else:
            packed = metadata(common / "packed-refs").splitlines()
            head = next((line.split(" ")[0] for line in packed if line.endswith(" " + ref)), "")
    if head != base:
        raise Refused("base_not_head")
    with tempfile.TemporaryDirectory(prefix="worker-source-") as temp:
        view = Path(temp)
        git(view, "init", "--template=", "--object-format=sha1", bound=bound, cap=limits.output_bytes)
        (view / ".git/objects/info/alternates").write_text(str(common / "objects") + "\n")
        if git(view, "cat-file", "-t", base, bound=bound, cap=limits.output_bytes) != b"commit\n":
            raise Refused("base_not_commit")
        tree = git(view, "rev-parse", base + "^{tree}", bound=bound, cap=limits.output_bytes).decode().strip()
        listing = git(view, "ls-tree", "-rz", "--full-tree", base, bound=bound, cap=limits.output_bytes)
        entries = []
        total = 0
        for row in listing.split(b"\0"):
            if not row:
                continue
            header, path = row.split(b"\t", 1)
            mode, kind, oid = header.split()
            if mode not in (b"100644", b"100755") or kind != b"blob":
                raise Refused("entry_unsupported")
            try:
                name = safe_path(path.decode("ascii"))
            except UnicodeError:
                raise Refused("path_unsupported") from None
            size = int(git(view, "cat-file", "-s", oid.decode(), bound=bound, cap=limits.output_bytes))
            total += size
            if size > limits.file_bytes or total > limits.source_bytes or len(entries) >= limits.files:
                raise Refused("source_limit")
            content = git(view, "cat-file", "blob", oid.decode(), bound=bound, cap=limits.file_bytes)
            entries.append(SourceFile(name, int(mode, 8), content))
        bundle = SourceBundle(base, tree, tuple(sorted(entries, key=lambda f: f.path)), owned_paths, limits)
        bundle.validate()
        # An index-only edit must also refuse. Split indexes/extensions needing repo
        # configuration fail in this isolated view rather than following host state.
        with (gitdir / "index").open("rb") as stream:
            index = stream.read(limits.output_bytes + 1)
        if len(index) > limits.output_bytes:
            raise Refused("index_limit")
        (view / ".git/index").write_bytes(index)
        if git(view, "diff-index", "--cached", "--name-only", "--no-renames", base,
               bound=bound, cap=limits.output_bytes):
            raise Refused("dirty_index")
        if scan(repo, limits, bound) != bundle.files:
            raise Refused("dirty_source")
        bound.check()
        return bundle


@dataclass(frozen=True)
class Identity:
    request_sha256: str
    base: str
    tree: str
    source_sha256: str
    nonce: str
    generation: str
    task_sha256: str
    image_sha256: str
    limits_sha256: str

    def validate(self, bundle: SourceBundle):
        if any(not isinstance(value, str) for value in asdict(self).values()):
            raise Refused("identity_invalid")
        if (self.base != bundle.base or self.tree != bundle.tree or
                self.source_sha256 != bundle.sha256 or
                self.limits_sha256 != digest(canonical(asdict(bundle.limits)))):
            raise Refused("identity_mismatch")
        for name, value in asdict(self).items():
            if name.endswith("sha256") and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise Refused("identity_invalid")
        if not re.fullmatch(r"[0-9a-f]{32,128}", self.nonce) or not self.generation or len(self.generation) > 128:
            raise Refused("identity_invalid")


def native_witness(raw: bytes) -> dict:
    """Strict native stream, unlike the review reader's best-effort text extraction.

    Evidence remains an untrusted claim, not provider attestation. No text echo grants
    success. Require init, consistent session, exactly one last successful result.
    """
    if not raw.endswith(b"\n"):
        raise Refused("witness_truncated")
    events = [decode(line, len(raw)) for line in raw.splitlines()]
    if len(events) < 2:
        raise Refused("witness_missing")
    first, last = events[0], events[-1]
    session = first.get("session_id")
    if (first.get("type") != "system" or first.get("subtype") != "init" or
            first.get("apiKeySource") != "none" or not isinstance(session, str) or not session):
        raise Refused("subscription_unproven")
    for event in events:
        if event.get("session_id") != session:
            raise Refused("native_session_mismatch")
        if event.get("type") == "system" and event.get("subtype") == "api_retry":
            raise Refused("native_retry_unsupported")
    if (sum(e.get("type") == "result" for e in events) != 1 or
            sum(e.get("type") == "system" and e.get("subtype") == "init" for e in events) != 1 or
            last.get("type") != "result" or last.get("subtype") != "success" or
            last.get("is_error") is not False or not isinstance(last.get("result"), str) or
            last.get("stop_reason") not in (None, "end_turn", "stop_sequence") or
            any(e.get("truncated", False) is not False for e in events)):
        raise Refused("native_unsuccessful")
    return {"session_id": session, "stream_sha256": digest(raw)}


@dataclass(frozen=True)
class QuarantinedPatch:
    identity: Identity
    path: Path
    sha256: str
    # There is deliberately no accepted flag or apply-to-user-tree method.
    required_next_step: str = "isolated_same_base_retest_and_owner_acceptance"


def check_binary_literals(patch: bytes, limits: Limits, bound: Bound):
    """Bound actual inflation before Git sees even a dishonest literal header."""
    lines = iter(patch.splitlines())
    total = 0
    for line in lines:
        bound.check()
        if line.startswith(b"delta "):
            raise Refused("binary_delta_unsupported")
        if not line.startswith(b"literal "):
            continue
        try:
            size = int(line[8:])
        except ValueError:
            raise Refused("binary_size_invalid") from None
        if size < 0 or size > limits.file_bytes:
            raise Refused("binary_expansion_limit")
        inflater = zlib.decompressobj()
        expanded = 0
        try:
            for encoded in lines:
                bound.check()
                if not encoded:
                    break
                prefix = encoded[0]
                length = prefix - 64 if 65 <= prefix <= 90 else prefix - 70 if 97 <= prefix <= 122 else 0
                if not length or len(encoded) != 1 + ((length + 3) // 4) * 5 or inflater.eof:
                    raise Refused("binary_encoding_invalid")
                compressed = base64.b85decode(encoded[1:])[:length]
                expanded += len(inflater.decompress(compressed, size - expanded + 1))
                if expanded > size or inflater.unconsumed_tail:
                    raise Refused("binary_expansion_limit")
            if not inflater.eof or inflater.unused_data or expanded != size:
                raise Refused("binary_encoding_invalid")
        except Refused:
            raise
        except (ValueError, zlib.error):
            raise Refused("binary_encoding_invalid") from None
        total += expanded
        # Both forward and reverse literals are present in a Git binary diff.
        if total > 2 * limits.source_bytes:
            raise Refused("binary_expansion_limit")


def validate_result(identity: Identity, envelope: bytes, bundle: SourceBundle,
                    quarantine: Path, bound: Bound) -> QuarantinedPatch:
    bound.check()
    bundle.validate()
    identity.validate(bundle)
    value = decode(envelope, bundle.limits.output_bytes)
    if (set(value) != {"identity", "patch", "patch_sha256", "patch_size", "native",
                       "native_sha256", "test_claim", "truncated", "exit_status"} or
            canonical(value["identity"]) != canonical(asdict(identity)) or
            value["truncated"] is not False or type(value["exit_status"]) is not int or
            value["exit_status"] != 0 or value["test_claim"] != "passed"):
        raise Refused("result_invalid")
    try:
        patch = base64.b64decode(value["patch"], validate=True)
        native = base64.b64decode(value["native"], validate=True)
    except (ValueError, TypeError):
        raise Refused("encoding_invalid") from None
    if (len(patch) > bundle.limits.patch_bytes or type(value["patch_size"]) is not int or
            len(patch) != value["patch_size"] or digest(patch) != value["patch_sha256"] or
            digest(native) != value["native_sha256"]):
        raise Refused("artifact_mismatch")
    native_witness(native)
    check_binary_literals(patch, bundle.limits, bound)
    for line in patch.splitlines():
        if line.startswith((b"new file mode ", b"deleted file mode ", b"old mode ", b"new mode ")):
            if line.split()[-1] not in (b"100644", b"100755"):
                raise Refused("patch_mode_unsupported")
        if line.startswith(b"index ") and len(line.split()) == 3:
            if line.split()[-1] not in (b"100644", b"100755"):
                raise Refused("patch_mode_unsupported")
    # Git parses the binary patch; never interpret its prose/commands. All effects
    # stay in a new disposable same-tree index and worktree with no repo config.
    with tempfile.TemporaryDirectory(prefix="worker-check-") as temp:
        root = Path(temp) / "tree"
        init_tree(root, bundle, bound)
        if patch:
            stats = git(root, "apply", "--numstat", "-z", "--binary", "-",
                        data=patch, bound=bound, cap=bundle.limits.output_bytes)
            for row in stats.split(b"\0"):
                if row:
                    try:
                        path = safe_path(row.split(b"\t", 2)[2].decode("ascii"))
                    except (IndexError, UnicodeError):
                        raise Refused("patch_path_invalid") from None
                    if path not in bundle.owned_paths:
                        raise Refused("ownership_escape")
            git(root, "apply", "--check", "--index", "--binary", "-",
                data=patch, bound=bound, cap=bundle.limits.output_bytes)
            git(root, "apply", "--index", "--binary", "-", data=patch,
                bound=bound, cap=bundle.limits.output_bytes)
        after = scan(root, bundle.limits, bound)
        SourceBundle(bundle.base, bundle.tree, after, bundle.owned_paths, bundle.limits).validate()
        before_map = {f.path: f for f in bundle.files}
        after_map = {f.path: f for f in after}
        if any(before_map.get(p) != after_map.get(p) and p not in bundle.owned_paths
               for p in before_map.keys() | after_map.keys()):
            raise Refused("ownership_escape")
    bound.check()
    # Caller provides a NEW quarantine directory under its private runtime root.
    quarantine.mkdir(mode=0o700)
    path = quarantine / "untrusted.patch"
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(patch)
    bound.check()
    return QuarantinedPatch(identity, path, digest(patch))
