"""Content-addressed opaque JCS echoes kept outside the closed journal layout."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat

ECHO_CAP = 1048576


@dataclass(frozen=True, slots=True)
class EchoRefused:
    code: str = "echo_unavailable"


def _directory(path: Path, *, create):
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError()
    root = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
            os.close(root)
            root = child
        info = os.fstat(root)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError()
        if create:
            try:
                os.mkdir("echo", 0o700, dir_fd=root)
            except FileExistsError:
                pass
        child = os.open("echo", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root)
    finally:
        os.close(root)
    info = os.fstat(child)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(child)
        raise ValueError()
    return child


def _read(directory, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
                or info.st_size > ECHO_CAP):
            raise ValueError()
        chunks, size = [], 0
        while size <= ECHO_CAP:
            chunk = os.read(descriptor, min(65536, ECHO_CAP + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        payload = b"".join(chunks)
        if size > ECHO_CAP or hashlib.sha256(payload).hexdigest() != name:
            raise ValueError()
        return payload
    finally:
        os.close(descriptor)


def write_echo(state_root, payload: bytes) -> str | EchoRefused:
    directory, temporary = None, None
    try:
        if type(payload) is not bytes or len(payload) > ECHO_CAP:
            raise ValueError()
        digest = hashlib.sha256(payload).hexdigest()
        directory = _directory(Path(state_root), create=True)
        temporary = ".echo-" + secrets.token_hex(16)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=directory)
        try:
            offset = 0
            while offset < len(payload):
                size = os.write(descriptor, payload[offset:])
                if size <= 0:
                    raise OSError()
                offset += size
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, digest, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            if _read(directory, digest) != payload:
                raise ValueError()
        os.unlink(temporary, dir_fd=directory)
        temporary = None
        os.fsync(directory)
        return digest
    except (OSError, TypeError, ValueError):
        return EchoRefused()
    finally:
        if directory is not None:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except OSError:
                    pass
            os.close(directory)


def read_echo(state_root, sha256: str) -> bytes | EchoRefused:
    directory = None
    try:
        if type(sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ValueError()
        directory = _directory(Path(state_root), create=False)
        return _read(directory, sha256)
    except (OSError, TypeError, ValueError):
        return EchoRefused()
    finally:
        if directory is not None:
            os.close(directory)
