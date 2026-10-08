"""Admission of qualified provider entry images.

Release-qualified images are admitted statically, by digest. With the caller's env,
``check`` also admits a locally self-qualified image through
``agy_qualification.lookup``, which may run ``agy --help`` from a sealed memfd to
measure the help digest (agent-harness#1331). It never qualifies an image."""

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


def _locally_qualified(data, source, env):
    """The image's local self-qualification admission (agent-harness#1076), else refuse.

    Same lookup as ``gemini_heartbeat.admit`` step 2: opt-out, failed entry, provenance,
    then the qualified entry for this host and runtime. Lookup only; it never qualifies."""
    from . import agy_qualification
    from .panel_invoker import ProviderProcessGroupQuiescenceError
    from .sandbox_egress import EgressUnavailable
    from .seat_jail import SeatSandboxRefused
    try:
        return agy_qualification.lookup(dict(env), data, str(source)).image
    except gemini_heartbeat.AdmissionMiss as miss:
        miss.image.close()
        raise AgyImageUnqualified("agy_image_unqualified") from None
    except (EgressUnavailable, gemini_heartbeat.GeminiQuiescenceError,
            ProviderProcessGroupQuiescenceError, SeatSandboxRefused):
        # The help measurement's own typed outcomes keep their type, so each reaches its
        # handler: a seat refusal its code (agent-harness#1333 PR1), a quiescence failure the
        # leg's quiescence path, a jail refusal its notice (agent-harness#1350 president).
        # This precedes the broad mapping below, so the AgyCanaryEvidenceError BASE (a real
        # memfd seal failure) is still the typed refusal.
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        # Opt-out, a failed record, an unsafe store, an unreadable image or a seal failure.
        raise AgyImageUnqualified("agy_image_unqualified") from exc


def check(path, env=None):
    """Admit a release-qualified agy image. With ``env``, also admit a locally
    self-qualified one, so the seat probe and launch honour the same admission as the
    heartbeat route (agent-harness#1331). Without ``env`` (canary evidence) only
    release-qualified images are admitted."""
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
        if size > 300_000_000:
            raise AgyImageUnqualified("agy_image_unqualified")
        if sha256(data).hexdigest() not in gemini_heartbeat.QUALIFIED_IMAGES:
            if env is None:
                raise AgyImageUnqualified("agy_image_unqualified")
            return _locally_qualified(data, source, env)
        return gemini_heartbeat.VerifiedImage.from_bytes(data, source)
    except (OSError, ValueError) as exc:
        raise AgyImageUnqualified("agy_image_unqualified") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def admit_for_seat(path, env):
    """Admission for the two owned review-seat sites only (agent-harness#1333 PR1).

    ``check`` with the seat's env, from one read: a release member is admitted offline
    before any config or store read, otherwise a ``locally_qualified`` image through
    ``agy_qualification.lookup`` (agent-harness#1331); what runs is the sealed memfd of
    those bytes, never the path. A miss, the opt-out, a failed record, an unsafe store, an
    unreadable image or a memfd-seal failure is the typed refusal. What the help measurement
    raises with its own type passes through unchanged: a typed seat refusal
    (``EgressUnavailable`` and its subclasses, e.g. ``seat_filtered_egress_unavailable``), a
    quiescence failure (``GeminiQuiescenceError``, ``ProviderProcessGroupQuiescenceError``)
    and a jail refusal (``SeatSandboxRefused``). The executor and canary callers call ``check``
    without an env and stay release-only.
    """
    return check(path, env)


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
