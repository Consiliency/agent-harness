"""Pinned in-process startup API for managed executable dependencies."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import threading
import uuid
from typing import Callable, Iterator, Literal, Sequence

import rfc8785

from . import __version__
from .executable_dependency import (
    FILE_MAX_BYTES,
    SAFE_INTEGER_MAX,
    AdmittedExecutableDependency,
    ExecutableDependencyError,
    ExecutableRequirementIdentity,
    admit_executable_dependency,
)


@dataclass(frozen=True)
class DependencyRequirement:
    provider: str
    selected_executable: ExecutableRequirementIdentity
    authority_id: str
    expected_authority_sha256: str
    adapter_id: str
    adapter_version: str
    policy_id: str
    policy_version: str
    base_profile_sha256: str
    mode: Literal["required"] = "required"


@dataclass(frozen=True)
class QualifiedRuntimePackage:
    distribution: Literal["phase-loop-runtime"]
    version: str
    install_root: str
    install_root_device: int
    install_root_inode: int
    installed_tree_manifest_id: str
    installed_tree_files_sha256: str
    distribution_metadata_sha256: str
    distribution_record_path: str
    distribution_record_sha256: str
    python_executable: str
    python_executable_device: int
    python_executable_inode: int
    python_executable_size: int
    python_executable_sha256: str
    private_runtime_binding_sha256: str


@dataclass(frozen=True)
class DependencyStartupSpec:
    requirement: DependencyRequirement | None
    borrowed_authority_fd: int | None
    expected_authority_sha256: str | None
    runtime_package: QualifiedRuntimePackage


_CURRENT_TASK: ContextVar[DependencyTaskLease | None] = ContextVar("executable_dependency_task", default=None)
_REGISTRY_LOCK = threading.RLock()
_ACTIVE_REQUIRED: dict[str, DependencyStartupSession] = {}
_SKILL_EVAL_ARGV_LOCK = threading.Lock()


class DependencyTaskLease:
    """An explicit child-work capability owned by one startup session."""

    def __init__(self, session: DependencyStartupSession, task_id: str) -> None:
        self._session = session
        self.task_id = task_id
        self._bound = False
        self._released = False

    @property
    def released(self) -> bool:
        with self._session._lock:
            return self._released

    @property
    def bound(self) -> bool:
        with self._session._lock:
            return self._bound

    @contextmanager
    def bind_current(self) -> Iterator[None]:
        with self._session._lock:
            self._session._require_open()
            if self._released or self._bound:
                raise ExecutableDependencyError("task_invalid", "lease state")
            if _CURRENT_TASK.get() is not None:
                raise ExecutableDependencyError("task_replacement")
            self._bound = True
        token = _CURRENT_TASK.set(self)
        try:
            yield
        finally:
            _CURRENT_TASK.reset(token)
            with self._session._lock:
                self._bound = False

    def release(self) -> None:
        with self._session._lock:
            if self._released:
                raise ExecutableDependencyError("task_invalid", "duplicate release")
            if self._bound:
                raise ExecutableDependencyError("task_live", self.task_id)
            self._released = True
            self._session._tasks.pop(self.task_id, None)

    def _release_if_pending(self) -> None:
        with self._session._lock:
            if self._released:
                return
            if self._bound:
                raise ExecutableDependencyError("task_live", self.task_id)
            self._released = True
            self._session._tasks.pop(self.task_id, None)


class DependencyStartupSession:
    """Own the admitted dependency and every explicit task using it."""

    def __init__(
        self,
        *,
        runtime_package: QualifiedRuntimePackage,
        dependency: AdmittedExecutableDependency | None,
    ) -> None:
        self.session_id = uuid.uuid4().hex
        self.runtime_package = runtime_package
        self.dependency = dependency
        self._lock = threading.RLock()
        self._tasks: dict[str, DependencyTaskLease] = {}
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _require_open(self) -> None:
        if self._closed:
            raise ExecutableDependencyError("session_closed")

    def acquire_task(self, task_id: str) -> DependencyTaskLease:
        with self._lock:
            self._require_open()
            if self.dependency is None:
                raise ExecutableDependencyError("task_invalid", "standalone session")
            if not isinstance(task_id, str) or not task_id or len(task_id) > 256:
                raise ExecutableDependencyError("task_invalid", "task ID")
            if task_id in self._tasks:
                raise ExecutableDependencyError("task_invalid", "duplicate task ID")
            lease = DependencyTaskLease(self, task_id)
            self._tasks[task_id] = lease
            return lease

    def run_cli(self, argv: Sequence[str]) -> int:
        from .cli import main

        return self._run("cli", argv, _cli_provider_capable(argv), lambda: main(list(argv)))

    def run_skill_eval(self, argv: Sequence[str]) -> int:
        from .skill_eval import console_main

        def invoke() -> int:
            if not _SKILL_EVAL_ARGV_LOCK.acquire(blocking=False):
                raise ExecutableDependencyError("task_replacement", "skill-eval argv")
            saved = sys.argv
            try:
                sys.argv = ["phase-loop-skill-eval", *argv]
                result = console_main()
                return 0 if result is None else int(result)
            finally:
                sys.argv = saved
                _SKILL_EVAL_ARGV_LOCK.release()

        return self._run("skill-eval", argv, bool(argv and argv[0] == "run"), invoke)

    def run_seat_jail_qualification(self, argv: Sequence[str]) -> int:
        from .seat_jail_qualification import main

        provider_capable = not any(item in {"-h", "--help", "--version"} for item in argv)
        return self._run("seat-jail-qualification", argv, provider_capable, lambda: main(list(argv)))

    def _run(
        self,
        label: str,
        argv: Sequence[str],
        provider_capable: bool,
        invoke: Callable[[], int],
    ) -> int:
        del argv
        with self._lock:
            self._require_open()
        _validate_runtime_package(self.runtime_package)
        if not provider_capable or self.dependency is None:
            return int(invoke())
        lease = self.acquire_task(f"{label}:{uuid.uuid4().hex}")
        try:
            with lease.bind_current():
                self.dependency.revalidate()
                return int(invoke())
        finally:
            lease._release_if_pending()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._tasks:
                raise ExecutableDependencyError("task_live", ",".join(sorted(self._tasks)))
            self._closed = True
        with _REGISTRY_LOCK:
            _ACTIVE_REQUIRED.pop(self.session_id, None)
        if self.dependency is not None:
            self.dependency.close()

    def __enter__(self) -> DependencyStartupSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def open_dependency_startup(spec: DependencyStartupSpec) -> DependencyStartupSession:
    """Validate the pinned runtime and open one same-process startup session."""

    if not isinstance(spec, DependencyStartupSpec):
        raise ExecutableDependencyError("authority_invalid", "startup spec")
    _validate_runtime_package(spec.runtime_package)
    requirement = spec.requirement
    supplied = spec.borrowed_authority_fd is not None or spec.expected_authority_sha256 is not None
    if requirement is None:
        if supplied:
            raise ExecutableDependencyError("authority_invalid", "authority without requirement")
        return DependencyStartupSession(runtime_package=spec.runtime_package, dependency=None)
    if spec.borrowed_authority_fd is None or spec.expected_authority_sha256 is None:
        raise ExecutableDependencyError("authority_missing")
    if spec.expected_authority_sha256 != requirement.expected_authority_sha256:
        raise ExecutableDependencyError("authority_invalid", "expected digest")
    dependency = admit_executable_dependency(
        requirement,
        spec.borrowed_authority_fd,
        spec.expected_authority_sha256,
    )
    session = DependencyStartupSession(runtime_package=spec.runtime_package, dependency=dependency)
    try:
        with _REGISTRY_LOCK:
            if _ACTIVE_REQUIRED:
                raise ExecutableDependencyError("session_replacement")
            _ACTIVE_REQUIRED[session.session_id] = session
    except BaseException:
        dependency.close()
        raise
    return session


def current_dependency_for_provider(
    provider: str,
    command: Sequence[str] | None = None,
) -> AdmittedExecutableDependency | None:
    """Return the bound dependency, refusing a managed unbound thread."""

    lease = _CURRENT_TASK.get()
    if lease is None:
        with _REGISTRY_LOCK:
            if _ACTIVE_REQUIRED:
                raise ExecutableDependencyError("task_unbound")
        return None
    session = lease._session
    with session._lock:
        session._require_open()
        if lease._released or not lease._bound:
            raise ExecutableDependencyError("task_invalid")
        dependency = session.dependency
    if dependency is None:
        raise ExecutableDependencyError("task_invalid", "missing dependency")
    if command is None:
        dependency.validate_provider(provider)
    else:
        dependency.validate_command(command, provider=provider)
    return dependency


def acquire_child_dependency_task(task_id: str) -> DependencyTaskLease | None:
    """Acquire from the current bound task before submitting child work."""

    lease = _CURRENT_TASK.get()
    if lease is None:
        with _REGISTRY_LOCK:
            if _ACTIVE_REQUIRED:
                raise ExecutableDependencyError("task_unbound")
        return None
    return lease._session.acquire_task(task_id)


@contextmanager
def bind_child_dependency_task(lease: DependencyTaskLease | None) -> Iterator[None]:
    if lease is None:
        yield
        return
    try:
        with lease.bind_current():
            yield
    finally:
        lease._release_if_pending()


def release_unstarted_dependency_task(lease: DependencyTaskLease | None) -> None:
    if lease is not None:
        lease._release_if_pending()


def _cli_provider_capable(argv: Sequence[str]) -> bool:
    if any(item in {"-h", "--help", "--version", "--dry-run", "dry-run"} for item in argv):
        return False
    if not argv:
        return True
    if any(
        item in {"run", "resume", "execute", "maintain-skills", "run-train", "advisor-board"}
        for item in argv
    ):
        return True
    return "seat-sandbox" in argv and "qualify" in argv


def _validate_runtime_package(package: QualifiedRuntimePackage) -> None:
    if not isinstance(package, QualifiedRuntimePackage) or package.distribution != "phase-loop-runtime":
        raise ExecutableDependencyError("runtime_mismatch", "distribution")
    if package.version != __version__:
        raise ExecutableDependencyError("runtime_mismatch", "version")
    for value in (
        package.installed_tree_manifest_id,
        package.installed_tree_files_sha256,
        package.distribution_metadata_sha256,
        package.distribution_record_sha256,
        package.python_executable_sha256,
        package.private_runtime_binding_sha256,
    ):
        if not _is_sha256(value):
            raise ExecutableDependencyError("runtime_mismatch", "digest")
    for value in (
        package.install_root_device,
        package.install_root_inode,
        package.python_executable_device,
        package.python_executable_inode,
        package.python_executable_size,
    ):
        if type(value) is not int or not 0 <= value <= SAFE_INTEGER_MAX:
            raise ExecutableDependencyError("runtime_mismatch", "identity integer")
    if (
        package.install_root_inode < 1
        or package.python_executable_inode < 1
        or not 1 <= package.python_executable_size <= FILE_MAX_BYTES
    ):
        raise ExecutableDependencyError("runtime_mismatch", "identity bound")
    root = _absolute_path(package.install_root)
    python = _absolute_path(package.python_executable)
    record_relative = _relative_path(package.distribution_record_path)
    try:
        root_lstat = os.lstat(root)
        root_stat = os.stat(root)
        if stat.S_ISLNK(root_lstat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise ExecutableDependencyError("runtime_mismatch", "install root type")
        _safe_identity(root_stat)
        if (root_stat.st_dev, root_stat.st_ino) != (package.install_root_device, package.install_root_inode):
            raise ExecutableDependencyError("runtime_mismatch", "install root identity")
        module_path = Path(__file__).resolve()
        if not module_path.is_relative_to(Path(root).resolve()):
            raise ExecutableDependencyError("runtime_mismatch", "import root")

        python_stat = os.stat(python, follow_symlinks=False)
        if os.path.realpath(sys.executable) != python or not stat.S_ISREG(python_stat.st_mode):
            raise ExecutableDependencyError("runtime_mismatch", "Python path")
        _safe_identity(python_stat)
        if (
            python_stat.st_dev,
            python_stat.st_ino,
            python_stat.st_size,
            _file_sha256(Path(python), FILE_MAX_BYTES),
        ) != (
            package.python_executable_device,
            package.python_executable_inode,
            package.python_executable_size,
            package.python_executable_sha256,
        ):
            raise ExecutableDependencyError("runtime_mismatch", "Python identity")

        rows: list[dict[str, object]] = []
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            filenames.sort()
            for name in tuple(dirnames):
                path = Path(directory) / name
                if path.is_symlink():
                    raise ExecutableDependencyError("runtime_mismatch", "package symlink")
            for name in filenames:
                path = Path(directory) / name
                observed = path.lstat()
                if not stat.S_ISREG(observed.st_mode):
                    raise ExecutableDependencyError("runtime_mismatch", "package special file")
                relative = _relative_path(path.relative_to(root).as_posix())
                rows.append(
                    {
                        "path": relative,
                        "sha256": _file_sha256(path, FILE_MAX_BYTES),
                        "size": observed.st_size,
                    }
                )
        rows.sort(key=lambda item: str(item["path"]).encode("ascii"))
        if _digest(rfc8785.dumps(rows)) != package.installed_tree_files_sha256:
            raise ExecutableDependencyError("runtime_mismatch", "installed tree")
        record = Path(root) / record_relative
        if _file_sha256(record, FILE_MAX_BYTES) != package.distribution_record_sha256:
            raise ExecutableDependencyError("runtime_mismatch", "distribution record")
        metadata_root = str(PurePosixPath(record_relative).parent)
        if metadata_root == ".":
            raise ExecutableDependencyError("runtime_mismatch", "distribution metadata path")
        metadata = [row for row in rows if str(row["path"]).startswith(metadata_root + "/")]
        if not metadata or _digest(rfc8785.dumps(metadata)) != package.distribution_metadata_sha256:
            raise ExecutableDependencyError("runtime_mismatch", "distribution metadata")
    except ExecutableDependencyError:
        raise
    except (OSError, ValueError) as exc:
        raise ExecutableDependencyError("runtime_mismatch", type(exc).__name__) from exc


def _file_sha256(path: Path, limit: int) -> str:
    observed = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(observed.st_mode) or not 0 <= observed.st_size <= limit:
        raise ExecutableDependencyError("runtime_mismatch", "file size or type")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if (observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ExecutableDependencyError("runtime_mismatch", "file changed")
    return digest.hexdigest()


def _safe_identity(value: os.stat_result) -> None:
    for item in (value.st_dev, value.st_ino, value.st_size):
        if type(item) is not int or not 0 <= item <= SAFE_INTEGER_MAX:
            raise ExecutableDependencyError("runtime_mismatch", "unsupported host identity")


def _absolute_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or value == "/":
        raise ExecutableDependencyError("runtime_mismatch", "absolute path")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ExecutableDependencyError("runtime_mismatch", "non-ASCII path") from exc
    parts = PurePosixPath(value).parts
    if (
        "\x00" in value
        or "//" in value
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in parts[1:])
        or PurePosixPath(value).as_posix() != value
    ):
        raise ExecutableDependencyError("runtime_mismatch", "path spelling")
    return value


def _relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ExecutableDependencyError("runtime_mismatch", "relative path")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ExecutableDependencyError("runtime_mismatch", "non-ASCII path") from exc
    if "\x00" in value or "//" in value or value.endswith("/") or PurePosixPath(value).as_posix() != value:
        raise ExecutableDependencyError("runtime_mismatch", "path spelling")
    if any(part in {"", ".", ".."} for part in PurePosixPath(value).parts):
        raise ExecutableDependencyError("runtime_mismatch", "relative path")
    return value


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "DependencyRequirement",
    "DependencyStartupSession",
    "DependencyStartupSpec",
    "DependencyTaskLease",
    "ExecutableRequirementIdentity",
    "QualifiedRuntimePackage",
    "open_dependency_startup",
]
