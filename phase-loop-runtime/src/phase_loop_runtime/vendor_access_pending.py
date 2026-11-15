"""Offline, immutable pending-revocation journal; no credential or gateway access.

Caller supplies an already trusted private directory descriptor and a binding
SHA-256. Records contain only a canonical UUID mutation ID. There is deliberately
no clear/acknowledge API yet: readiness and restore-tombstone rules are unfinished.
A successful record_pending return is required before any future gateway mutation.
"""
import os
import re
import stat
import uuid


def _name(directory: int, binding_sha256: str) -> str:
    info = os.fstat(directory)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('unsafe_pending_directory')
    if type(binding_sha256) is not str or not re.fullmatch('[0-9a-f]{64}', binding_sha256):
        raise ValueError('invalid_binding_digest')
    return binding_sha256 + '.pending'


def _canonical_id(value: str) -> bool:
    if type(value) is not str or len(value) != 36:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return str(parsed) == value


def load_pending(directory: int, binding_sha256: str) -> str | None:
    """Absent means no record; malformed/unsafe state raises, never means absent."""
    return _load_record(directory, _name(directory, binding_sha256), links=1)


def _load_record(directory: int, name: str, *, links: int) -> str | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != links
                or before.st_size != 37):
            raise ValueError('unsafe_pending_record')
        raw = os.read(fd, 38)
        after = os.fstat(fd)
        if before != after:
            # Reading may update atime; compare only consistency-relevant fields.
            fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns',
                      'st_mode', 'st_uid', 'st_nlink')
            if any(getattr(before, key) != getattr(after, key) for key in fields):
                raise ValueError('pending_record_changed')
        value = raw.decode('ascii')
        if not value.endswith('\n') or not _canonical_id(value[:-1]):
            raise ValueError('invalid_pending_record')
        return value[:-1]
    finally:
        os.close(fd)


def record_pending(directory: int, binding_sha256: str, mutation_id: str) -> str:
    """Fsync data, publish without replacing an existing record, then fsync directory.

    Different existing IDs refuse reconciliation rather than dropping old intent.
    On ANY error the caller must not mutate the gateway. Crash-left temp files are
    inert unless still hard-linked to a published record: that crash window
    refuses on link count and requires explicit recover_pending_link before use.
    Automatic orphan discovery is not implemented. Single-writer host
    admission is a separate requirement, not supplied by this filesystem primitive.
    """
    name = _name(directory, binding_sha256)
    if not _canonical_id(mutation_id):
        raise ValueError('invalid_mutation_id')
    temporary = '.pending-' + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write((mutation_id + '\n').encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        except FileExistsError:
            if load_pending(directory, binding_sha256) != mutation_id:
                raise ValueError('pending_operation_conflict')
    finally:
        os.unlink(temporary, dir_fd=directory)
    os.fsync(directory)
    return mutation_id


def recover_pending_link(directory: int, binding_sha256: str, temporary: str) -> str:
    """Recover one identified publication orphan under caller-held exclusive access.

    No directory scan, broad cleanup or pending-record deletion. Caller must hold
    the same exclusive single-writer admission used for publication; this offline
    primitive does not establish that admission. Both names must be regular,
    private, same-owner links to the same validated two-link record. Any failure
    prevents gateway use. Orphan discovery and activation wiring remain absent.
    """
    name = _name(directory, binding_sha256)
    if type(temporary) is not str or not re.fullmatch(r'\.pending-[0-9a-f]{32}', temporary):
        raise ValueError('invalid_pending_temporary')
    value = _load_record(directory, name, links=2)
    if value is None:
        raise ValueError('pending_record_absent')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        target = os.fstat(fd)
        orphan = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_size',
                  'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
        if (target.st_nlink != 2 or not stat.S_ISREG(target.st_mode)
                or stat.S_IMODE(target.st_mode) != 0o600 or target.st_uid != os.geteuid()
                or any(getattr(target, key) != getattr(other, key)
                       for other in (orphan, current) for key in fields)
                or os.read(fd, 38) != (value + '\n').encode('ascii')):
            raise ValueError('pending_orphan_mismatch')
        os.fsync(fd)
        os.unlink(temporary, dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(fd)
    if load_pending(directory, binding_sha256) != value:
        raise ValueError('pending_record_changed')
    return value
