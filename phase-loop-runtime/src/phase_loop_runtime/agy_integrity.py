"""Static, read-only admission of qualified provider entry images."""

from hashlib import sha256
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import shutil

from . import gemini_heartbeat

_PROVIDER_SEARCH_PATH = os.environ.get("PATH", os.defpath)


class AgyImageUnqualified(RuntimeError):
    pass


def check(path):
    descriptor = None
    try:
        source = Path(path).resolve(strict=True)
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 300_000_000:
            raise AgyImageUnqualified("agy_image_unqualified")
        chunks, size = [], 0
        while size <= 300_000_000:
            chunk = os.read(descriptor, min(1024 * 1024, 300_000_001 - size))
            if not chunk:
                break
            size += len(chunk)
            chunks.append(chunk)
        data = b"".join(chunks)
        if size > 300_000_000 or sha256(data).hexdigest() not in gemini_heartbeat.QUALIFIED_IMAGES:
            raise AgyImageUnqualified("agy_image_unqualified")
        return gemini_heartbeat.VerifiedImage.from_bytes(data, source)
    except (OSError, ValueError) as exc:
        raise AgyImageUnqualified("agy_image_unqualified") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def admit_for_seat(path, env):
    """Admission for the two owned review-seat sites only (agent-harness#1333 PR1).

    A release member is admitted offline by ``check``, before any config or store read.
    Otherwise the bytes of one fresh read go to ``agy_qualification.lookup``, which admits
    only a ``locally_qualified`` image; what runs is lookup's own sealed memfd of those
    bytes, never the path. Every other outcome is the typed refusal. The executor and
    canary callers keep ``check`` and stay release-only.
    """
    try:
        return check(path)
    except AgyImageUnqualified:
        pass
    from . import agy_qualification
    try:
        source = str(Path(path).resolve(strict=True))
        admission = agy_qualification.lookup(env, gemini_heartbeat._read_image(source), source)
    except gemini_heartbeat.AdmissionMiss as miss:
        miss.image.close()
        raise AgyImageUnqualified("agy_image_unqualified") from None
    except (OSError, ValueError) as exc:
        # Opt-out, a failed record, an unsafe store or an unreadable image.
        raise AgyImageUnqualified("agy_image_unqualified") from exc
    return admission.image


def trusted_command(argv, env):
    if not argv or Path(argv[0]).name not in {"agy", "gemini"}:
        return argv
    source = shutil.which(argv[0], path=_PROVIDER_SEARCH_PATH)
    if source is None:
        raise AgyImageUnqualified("agy_image_unqualified")
    image = check(source)
    try:
        return [str(image.path), *argv[1:]]
    finally:
        image.close()


@contextmanager
def admitted_command(argv):
    if not argv or Path(argv[0]).name not in {"agy", "gemini"}:
        yield argv, ()
        return
    source = shutil.which(argv[0], path=_PROVIDER_SEARCH_PATH)
    if source is None:
        raise AgyImageUnqualified("agy_image_unqualified")
    image = check(source)
    try:
        yield [f"/proc/self/fd/{image.fd}", *argv[1:]], (image.fd,)
    finally:
        image.close()
