"""Admission of qualified provider entry images.

Release-qualified images are admitted statically, by digest. With the caller's env,
``check`` is the seat admission boundary, ``agy_qualification.admit_seat`` (AGYFRESH §2.2):
it also admits a locally self-qualified image through ``agy_qualification.lookup``, which may
run ``agy --help`` from a sealed memfd to measure the help digest (agent-harness#1331), and,
for a subject-side refusal, a held image (HOLD). It never qualifies an image."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import shutil

from . import agy_provenance, gemini_heartbeat

_PROVIDER_SEARCH_PATH = os.environ.get("PATH", os.defpath)


class AgyImageUnqualified(RuntimeError):
    def __init__(self, message: str = "agy_image_unqualified", *, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


def _admitted_for_seat(path, env, evidence=None):
    """``agy_qualification.admit_seat(first_use=False)`` for a seat, else refuse.

    What runs is the admitted image's sealed memfd, never the path. A refusal is the typed
    ``agy_image_unqualified``; the help measurement's own typed outcomes keep their type, so
    each reaches its handler: a seat refusal its code (agent-harness#1333 PR1), a quiescence
    failure the leg's quiescence path, a jail refusal its notice (agent-harness#1350
    president). They precede the broad mapping below, so the ``AgyCanaryEvidenceError`` BASE
    (a real memfd seal failure) is still the typed refusal."""
    from . import agy_qualification
    from .panel_invoker import ProviderProcessGroupQuiescenceError
    from .sandbox_egress import EgressUnavailable
    from .seat_jail import SeatSandboxRefused
    try:
        admission = agy_qualification.admit_seat(dict(env), path, first_use=False)
    except (EgressUnavailable, gemini_heartbeat.GeminiQuiescenceError,
            ProviderProcessGroupQuiescenceError, SeatSandboxRefused):
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        # Opt-out, a failed record, an unsafe store, an unreadable image or a seal failure,
        # with no held image: the subject's refusal.
        reason = getattr(exc, "_verdict_reason", None)
        if reason not in agy_qualification.VERDICT_REFUSAL_REASONS:
            reason = "admission_error"
        raise AgyImageUnqualified("agy_image_unqualified", reason=reason) from exc
    if evidence is not None:
        evidence.update(admission.evidence())
    return admission.image


def check(path, env=None, *, evidence=None):
    """Admit a release-qualified agy image. With ``env``, the seat admission boundary
    (``_admitted_for_seat``), so the seat probe and launch honour the same admission as the
    heartbeat route (agent-harness#1331), the hold included. Without ``env`` (the executor
    and canary) only release-qualified images are admitted, and nothing is ever held.

    The image is read once, streamed into one sealed memfd (AGYFRESH §1.2), within
    ``agy_provenance.MAX_MEMBER_BYTES`` read at call time."""
    if env is not None:
        return _admitted_for_seat(path, env, evidence)
    descriptor = image = None
    try:
        source = Path(path).resolve(strict=True)
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > agy_provenance.MAX_MEMBER_BYTES:
            raise AgyImageUnqualified("agy_image_unqualified", reason="image_unreadable")
        try:
            image = gemini_heartbeat.VerifiedImage.from_fd(descriptor, path=source)
        except gemini_heartbeat.ImageOverBound as exc:
            raise AgyImageUnqualified("agy_image_unqualified", reason="image_unreadable") from exc
        except gemini_heartbeat.AgyCanaryEvidenceError as exc:
            # A memfd seal failure is the typed refusal, as when lookup sealed the bytes.
            raise AgyImageUnqualified("agy_image_unqualified", reason="admission_error") from exc
        except ValueError as exc:
            raise AgyImageUnqualified("agy_image_unqualified", reason="admission_error") from exc
        os.close(descriptor)
        descriptor = None
        if image.sha256 not in gemini_heartbeat.QUALIFIED_IMAGES:
            raise AgyImageUnqualified("agy_image_unqualified", reason="no_qualification_record")
        if evidence is not None:
            evidence.update(provider_admission_class="release_qualified",
                            provider_image_sha256=image.sha256)
        admitted, image = image, None
        return admitted
    except (OSError, ValueError) as exc:
        raise AgyImageUnqualified("agy_image_unqualified", reason="image_unreadable") from exc
    finally:
        if image is not None:
            image.close()
        if descriptor is not None:
            os.close(descriptor)


def admit_for_seat(path, env, *, evidence=None):
    """Admission for the two owned review-seat sites only (agent-harness#1333 PR1).

    ``check`` with the seat's env, from one read: a release member is admitted offline
    before any config or store read, otherwise a ``locally_qualified`` image through
    ``agy_qualification.lookup`` (agent-harness#1331), otherwise, for a subject-side
    refusal, a held image (HOLD, AGYFRESH §2.2); what runs is the sealed memfd of
    those bytes, never the path. On the local-qualification path (an image that is not a
    release member), a miss, the opt-out, a failed record, an unsafe store, an unreadable
    image or a memfd-seal failure is the typed refusal. What the help measurement raises with
    its own type passes through unchanged, and on the brokered review route the leg keeps its
    code and notice: a typed seat refusal
    (``EgressUnavailable`` and its subclasses, e.g. ``seat_filtered_egress_unavailable``), a
    quiescence failure (``GeminiQuiescenceError``, ``ProviderProcessGroupQuiescenceError``)
    and a jail refusal (``SeatSandboxRefused``). The executor and canary callers call ``check``
    without an env and stay release-only.
    """
    return check(path, env, evidence=evidence)


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
