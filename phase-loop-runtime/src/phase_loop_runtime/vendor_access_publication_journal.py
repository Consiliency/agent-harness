"""Bounded ACK-only publication state, under caller-held private_directory_writer.

No payload, revision, server receipt or comparison fingerprint is persisted.
Only the closed transitions below are supported; unsafe state is never repaired.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
import stat
import uuid

from .vendor_access_pending import _canonical_id, _name

MAX_BYTES = 1024
_FIELDS = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns',
           'st_mode', 'st_uid', 'st_nlink')


@dataclass(frozen=True)
class PublicationRecord:
    version: int
    binding_sha256: str
    barrier_id: str
    attempt_id: str
    phase: str


def _record_name(directory, digest):
    _name(directory, digest)  # validate the full binding digest and private directory
    key = hashlib.sha256(('vendor-access-publication-barrier-v1:' + digest).encode('ascii')).hexdigest()
    return key + '.publication.json'


def canonical(record):
    return (json.dumps(asdict(record), sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_publication_key')
        result[key] = value
    return result


def _validate(record, digest):
    if (type(record) is not PublicationRecord or type(record.version) is not int
            or record.version != 1 or record.binding_sha256 != digest
            or not _canonical_id(record.barrier_id) or not _canonical_id(record.attempt_id)
            or record.phase not in ('prepared', 'acknowledged')):
        raise ValueError('invalid_publication_record')


def load_publication(directory, digest, *, durable=False):
    """Read canonical private state; optionally re-establish file then dir durability."""
    name = _record_name(directory, digest)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 < before.st_size <= MAX_BYTES):
            raise ValueError('unsafe_publication_record')
        raw = os.read(fd, MAX_BYTES + 1)
        after = os.fstat(fd)
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if any(getattr(before, k) != getattr(other, k)
               for other in (after, current) for k in _FIELDS):
            raise ValueError('publication_record_changed')
        try:
            record = PublicationRecord(**json.loads(raw.decode('ascii'), object_pairs_hook=_pairs))
        except (TypeError, UnicodeError) as exc:
            raise ValueError('invalid_publication_record') from exc
        _validate(record, digest)
        if raw != canonical(record):
            raise ValueError('noncanonical_publication_record')
        if durable:
            os.fsync(fd)
            os.fsync(directory)
        return record
    finally:
        os.close(fd)


def transition_publication(directory, digest, expected, desired, *, barrier_created=False):
    """absent→prepared(first), ACK(x)→prepared(y), prepared(a)→ACK(a) only.

    Absent requires the caller to have created the immutable barrier this tick.
    A no-overwrite first link protects even against unexpected destination entry.
    Replacement requires exact expected state under the cooperative writer lock.
    """
    name = _record_name(directory, digest)
    _validate(desired, digest)
    if expected is None:
        allowed = (barrier_created and desired.phase == 'prepared'
                   and desired.attempt_id == desired.barrier_id)
    else:
        _validate(expected, digest)
        allowed = (expected.barrier_id == desired.barrier_id and (
            (expected.phase == 'acknowledged' and desired.phase == 'prepared'
             and expected.attempt_id != desired.attempt_id)
            or (expected.phase == 'prepared' and desired.phase == 'acknowledged'
                and expected.attempt_id == desired.attempt_id)))
    if not allowed or load_publication(directory, digest) != expected:
        raise ValueError('publication_transition_conflict')
    temporary = '.publication-' + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(desired))
            stream.flush()
            os.fsync(stream.fileno())
        if load_publication(directory, digest) != expected:
            raise ValueError('publication_transition_conflict')
        if expected is None:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        else:
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass  # replace consumed this writer's temporary
    os.fsync(directory)
    return desired
