"""Explicit, local-only capture of brokered provider IO, never review authority."""
from __future__ import annotations

from contextvars import ContextVar
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import threading
import uuid


class PrivateCaptureError(RuntimeError):
    """Capture could not establish retention; messages contain no provider data."""


_CURRENT: ContextVar[PrivateSessionCapture | None] = ContextVar("private_provider_capture", default=None)
_IDENTITY = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def _identity(info):
    return tuple(getattr(info, key) for key in _IDENTITY)


def _open_directory(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise PrivateCaptureError("capture_path_not_canonical")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def current_private_capture():
    return _CURRENT.get()


class PrivateSessionCapture:
    """One opt-in scope. Root must already be canonical, owned and mode 0700.

    Raw files can contain sensitive provider output. This is NOT a redaction,
    encryption, automatic backup or approval facility.
    """

    def __init__(self, root: Path | str, *, max_attempt_bytes=32 * 1024 * 1024,
                 max_total_bytes=128 * 1024 * 1024):
        if (type(max_attempt_bytes) is not int or type(max_total_bytes) is not int
                or not 1 <= max_attempt_bytes <= max_total_bytes <= 1024 * 1024 * 1024):
            raise PrivateCaptureError("capture_byte_limits_invalid")
        self.root = Path(root)
        self.max_attempt_bytes = max_attempt_bytes
        self.max_total_bytes = max_total_bytes
        self._lock = threading.Lock()
        self._total = 0
        self._closed = False
        self._token = None
        self.receipts = []
        self._fd = None
        try:
            self._fd = _open_directory(self.root)
            info = os.fstat(self._fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PrivateCaptureError("capture_root_not_private")
            self._root_identity = (info.st_dev, info.st_ino)
        except BaseException as exc:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            if not isinstance(exc, Exception):
                raise
            raise PrivateCaptureError("capture_root_unavailable") from None

    def __enter__(self):
        with self._lock:
            if self._closed:
                raise PrivateCaptureError("capture_scope_closed")
            if self._token is not None:
                raise PrivateCaptureError("capture_scope_reentered")
            self._token = _CURRENT.set(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        with self._lock:
            if self._token is None:
                raise PrivateCaptureError("capture_scope_not_entered")
            _CURRENT.reset(self._token)
            self._token = None
            self._closed = True
            os.close(self._fd)
            self._fd = None
        if exc_type is None and any(r["status"] != "saved" for r in self.receipts):
            raise PrivateCaptureError("private_session_retention_incomplete")

    def run(self, fn, *args):
        with self._lock:
            if self._closed:
                raise PrivateCaptureError("capture_scope_closed")
        token = _CURRENT.set(self)
        try:
            return fn(*args)
        finally:
            _CURRENT.reset(token)

    def _verify_root(self):
        if self._closed or self._fd is None:
            raise PrivateCaptureError("capture_scope_closed")
        fd = _open_directory(self.root)
        try:
            info = os.fstat(fd)
            pinned = os.fstat(self._fd)
            if ((info.st_dev, info.st_ino) != self._root_identity
                    or (pinned.st_dev, pinned.st_ino) != self._root_identity
                    or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700
                    or pinned.st_uid != os.getuid() or stat.S_IMODE(pinned.st_mode) != 0o700):
                raise PrivateCaptureError("capture_root_changed")
        finally:
            os.close(fd)

    def begin(self, provider, model):
        if provider not in {"claude", "gemini"}:
            raise PrivateCaptureError("private_capture_provider_unsupported")
        with self._lock:
            if self._closed:
                raise PrivateCaptureError("capture_scope_closed")
            fd = None
            receipt = None
            try:
                self._verify_root()
                name = "session-" + uuid.uuid4().hex
                os.mkdir(name, 0o700, dir_fd=self._fd)
                receipt = {"session": name, "status": "pending"}
                self.receipts.append(receipt)
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=self._fd)
                os.fsync(self._fd)
                attempt = PrivateCaptureAttempt(self, name, fd, provider, model, receipt)
                attempt._verify_directory()
                return attempt
            except BaseException as exc:
                if fd is not None:
                    os.close(fd)
                if receipt is not None:
                    receipt.update(status="failed", reason="capture_attempt_allocation_failed")
                if not isinstance(exc, Exception):
                    raise
                raise PrivateCaptureError("capture_attempt_allocation_failed") from None

    def _reserve(self, attempt, count):
        with self._lock:
            if (self._closed or attempt.total + count > self.max_attempt_bytes
                    or self._total + count > self.max_total_bytes):
                raise PrivateCaptureError("capture_budget_or_scope_exhausted")
            attempt.total += count
            self._total += count


class PrivateCaptureAttempt:
    def __init__(self, owner, name, fd, provider, model, receipt):
        self.owner, self.name, self.fd = owner, name, fd
        info = os.fstat(fd)
        self._directory_identity = (info.st_dev, info.st_ino)
        self.provider, self.model, self.receipt = provider, model, receipt
        self.total = 0
        self.process_number = 0
        self.quiescent = True
        self.failure = None
        self.outcome = None
        self._streams = {}
        self.files = {}

    def fail(self, reason):
        if self.failure is None:
            self.failure = reason
        self.receipt.update(status="failed", reason=self.failure)

    def check(self):
        if self.failure:
            raise PrivateCaptureError(self.failure)

    def _verify_directory(self):
        if self.fd is None:
            raise PrivateCaptureError("capture_attempt_closed")
        self.owner._verify_root()
        fd = _open_directory(self.owner.root / self.name)
        try:
            info = os.fstat(fd)
            pinned = os.fstat(self.fd)
            if ((info.st_dev, info.st_ino) != self._directory_identity
                    or (pinned.st_dev, pinned.st_ino) != self._directory_identity
                    or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700
                    or pinned.st_uid != os.getuid() or stat.S_IMODE(pinned.st_mode) != 0o700):
                raise PrivateCaptureError("capture_directory_changed")
        finally:
            os.close(fd)

    def open_stream(self, name):
        self.check()
        try:
            if not re.fullmatch(r"(?:bundle\.md|instructions\.md|input\.txt|claude\.jsonl|"
                                r"(?:stdin|stdout|stderr|pty)-[1-9][0-9]*\.bin)", name):
                raise PrivateCaptureError("capture_artifact_name_invalid")
            if name in self.files or name in self._streams:
                raise PrivateCaptureError("capture_artifact_name_reused")
            self._verify_directory()
            fd = os.open(name + ".partial", os.O_RDWR | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
            self._streams[name] = [fd, sha256(), 0]
            self.files[name] = {"status": "partial", "bytes": 0}
            return name
        except Exception:
            self.fail("capture_stream_open_failed")
            self.check()

    def append(self, name, chunk):
        """Latch storage failure without changing provider liveness/termination."""
        if self.failure:
            return
        try:
            self._verify_directory()
            fd, digest, count = self._streams[name]
            info = os.fstat(fd)
            named = os.stat(name + ".partial", dir_fd=self.fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_size != count or _identity(info) != _identity(named)):
                raise OSError("capture file changed")
            self.owner._reserve(self, len(chunk))
            offset = 0
            while offset < len(chunk):
                written = os.write(fd, chunk[offset:])
                if written <= 0:
                    raise OSError("short capture write")
                digest.update(chunk[offset:offset + written])
                offset += written
                self._streams[name][2] = count + offset
                self.files[name]["bytes"] = count + offset
        except Exception:
            self.fail("capture_write_or_limit_failed")

    def save(self, name, data):
        self.open_stream(name)
        self.append(name, data)
        self.finish_stream(name)
        self.check()

    def _verify_file(self, fd, name, digest, count, *, links=1, expected=None):
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != links or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_size != count
                or (expected is not None and (before.st_dev, before.st_ino) != expected)):
            raise OSError("capture file changed")
        os.lseek(fd, 0, os.SEEK_SET)
        checked = sha256()
        remaining = count
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                raise OSError("short capture read")
            checked.update(chunk)
            remaining -= len(chunk)
        named = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        if (_identity(before) != _identity(os.fstat(fd))
                or _identity(before) != _identity(named) or checked.digest() != digest.digest()):
            raise OSError("capture verification failed")
        return before

    def _publish_file(self, fd, name, digest, count):
        self._verify_directory()
        os.fsync(fd)
        before = self._verify_file(fd, name + ".partial", digest, count)
        expected = (before.st_dev, before.st_ino)
        os.link(name + ".partial", name, src_dir_fd=self.fd, dst_dir_fd=self.fd,
                follow_symlinks=False)
        published = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                            dir_fd=self.fd)
        try:
            linked = self._verify_file(published, name, digest, count, links=2, expected=expected)
            partial = os.stat(name + ".partial", dir_fd=self.fd, follow_symlinks=False)
            if (_identity(linked) != _identity(os.fstat(fd))
                    or _identity(linked) != _identity(partial)):
                raise OSError("capture publication changed")
            self._verify_directory()
            os.unlink(name + ".partial", dir_fd=self.fd)
            os.fsync(self.fd)
            self._verify_directory()
            final = self._verify_file(published, name, digest, count, expected=expected)
            self._verify_directory()
            named = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            if (_identity(final) != _identity(os.fstat(fd))
                    or _identity(final) != _identity(named)):
                raise OSError("capture publication changed")
        finally:
            os.close(published)

    def finish_stream(self, name):
        if name not in self._streams:
            return
        fd, digest, count = self._streams.pop(name)
        try:
            if not self.failure:
                self._publish_file(fd, name, digest, count)
                self.files[name] = {"status": "saved", "bytes": count, "sha256": digest.hexdigest()}
            else:
                self._verify_directory()
                os.fsync(fd)
                self._verify_file(fd, name + ".partial", digest, count)
        except Exception:
            self.fail("capture_verification_failed")
        finally:
            os.close(fd)

    def copy_transcript(self, path, *, required):
        """Read only the caller's exact new-session JSONL, never adjacent sessions."""
        parent = None
        fd = None
        try:
            self.check()
            parent = _open_directory(path.parent)
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                         os.O_CLOEXEC, dir_fd=parent)
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_nlink != 1 or before.st_size > self.owner.max_attempt_bytes - self.total):
                raise PrivateCaptureError("capture_transcript_unsafe_or_oversized")
            self.open_stream("claude.jsonl")
            remaining = before.st_size
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    raise PrivateCaptureError("capture_transcript_changed")
                self.append("claude.jsonl", chunk)
                self.check()
                remaining -= len(chunk)
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (_identity(before) != _identity(os.fstat(fd))
                    or _identity(before) != _identity(named)):
                raise PrivateCaptureError("capture_transcript_changed")
            self.finish_stream("claude.jsonl")
            self.check()
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if (_identity(before) != _identity(os.fstat(fd))
                    or _identity(before) != _identity(named)):
                raise PrivateCaptureError("capture_transcript_changed")
            return _identity(before)
        except FileNotFoundError:
            if fd is not None:
                self.fail("capture_transcript_changed")
                self.check()
            self.files["claude.jsonl"] = {"status": "missing", "bytes": 0}
            if required:
                self.fail("capture_required_transcript_missing")
            self.check()
            return None
        except Exception:
            self.fail("capture_transcript_failed")
            self.check()
        finally:
            if fd is not None:
                os.close(fd)
            if parent is not None:
                os.close(parent)

    def close(self, *, completed):
        """Caller owns this attempt until its adapter thread exits."""
        if self.fd is None:
            return
        if not completed or not self.quiescent:
            self.fail("capture_attempt_incomplete")
        for name in list(self._streams):
            self.finish_stream(name)
        fd = None
        try:
            self._verify_directory()
            payload = {
                "schema": "private_provider_session.v1", "session": self.name,
                "provider": self.provider, "model": self.model,
                "status": "failed" if self.failure else "saved",
                "reason": self.failure, "quiescent": self.quiescent,
                "files": self.files, "provider_outcome": self.outcome,
                "source": self.receipt.get("source"),
            }
            body = json.dumps(payload, sort_keys=True, indent=2).encode()
            self.owner._reserve(self, len(body))
            fd = os.open("manifest.json.partial", os.O_RDWR | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
            offset = 0
            while offset < len(body):
                written = os.write(fd, body[offset:])
                if written <= 0:
                    raise OSError("short capture write")
                offset += written
            self._publish_file(fd, "manifest.json", sha256(body), len(body))
            self.receipt.update(status=payload["status"], manifest_sha256=sha256(body).hexdigest())
        except Exception:
            self.fail("capture_manifest_failed")
        finally:
            if fd is not None:
                os.close(fd)
            os.close(self.fd)
            self.fd = None
