"""Linux ownership for the qualified, brokered Gemini heartbeat route."""
from contextlib import contextmanager
from hashlib import sha256
import errno
import json
import os
from pathlib import Path
import select
import shutil
import signal
import stat
import time

from .agy_canary_evidence import AgyCanaryEvidenceError, _linux_memfd_seal_abi, _sealed_tree_fd


# The closed set of qualified agy entry images: image SHA256 -> its measured `--help` SHA256.
# Each member has its own live qualification record, listed in
# plans/evidence/qualified-provider-images.json; verify_qualified_agy_image.py requires this
# literal and that catalog to name exactly the same members (agent-harness#1008).
QUALIFIED_IMAGES = {
    # agy 1.2.11
    "ec7cf797ecb0e1d91ddf3b6d9d6c1d616bb89f78a5b0e43536b72a7fce695f56":
        "83e3a0c36269f23972ba33d0013b9a6b2933ddb07cde268fa40e0fb1a5f33755",
    # agy 1.2.12
    "ce6fdd9e7621ee9ac6eedaa337731ca1f235e412ff57cf9eabcd2aa23b3576ca":
        "83e3a0c36269f23972ba33d0013b9a6b2933ddb07cde268fa40e0fb1a5f33755",
    # agy 1.2.14
    "0d0d3eba22daf29504dd290151c7ed9a4d33b0c6aa0acfc5da27bc3b01d2f029":
        "83e3a0c36269f23972ba33d0013b9a6b2933ddb07cde268fa40e0fb1a5f33755",
    # agy 1.2.15
    "5f9c16b286895f8f7fdecd423883ca256a85077b8acf9a6bc1111761d34df164":
        "8fcf40227fe84704f7f8155b3b5ebcee79dfdc5208fde6e8b07569c24425f976",
    # agy 1.2.16
    "a759ce7c7a235d9b6c281a25ead97cbbf2e92314a3ffd224e2f9144f3fae7a86":
        "8fcf40227fe84704f7f8155b3b5ebcee79dfdc5208fde6e8b07569c24425f976",
}
PROFILE_ID = "agy_memfd_home_deny_all_v1"
PRIVATE_HOME = "/dev/phase-loop-agy"
_CAPABILITY = "gemini_heartbeat_capability_unavailable"
_ADMISSION = "gemini_heartbeat_admission_handshake_failed"


class GeminiQuiescenceError(RuntimeError):
    pass


_MAX_IMAGE_BYTES = 300_000_000
ADMISSION_CLASSES = ("release_qualified", "locally_qualified", "qualification_candidate")
# Process-local qualification candidate. Set ONLY by the qualification worker entry
# (agy_qualification._worker_entry) after it has proved its inherited fd is a fully
# sealed memfd whose digest passes the provenance gate (agent-harness#1076).
_CANDIDATE = None


class VerifiedImage:
    """One read of one file (agent-harness#1076 I1).

    The digest is taken over the buffer that fills the sealed memfd, and the memfd is
    re-hashed before use. Everything downstream executes this memfd and never opens a
    path again.
    """

    def __init__(self, fd, sha256_hex, path=None):
        self.fd, self.sha256, self.path = fd, sha256_hex, path

    @classmethod
    def from_bytes(cls, data, path=None):
        digest = sha256(data).hexdigest()
        fd = _sealed_tree_fd(data=data, executable=True, label="agy-image")
        try:
            os.fchmod(fd, 0o500)
            if _fd_digest(fd) != digest:
                raise ValueError(_CAPABILITY)
        except BaseException:
            os.close(fd)
            raise
        return cls(fd, digest, path)

    def reopen(self):
        """An independent, re-verified read of the SAME sealed memfd (own file offset)."""
        fd = os.open(f"/proc/self/fd/{self.fd}", os.O_RDONLY | os.O_CLOEXEC)
        try:
            if (os.fstat(fd).st_ino, os.fstat(fd).st_dev) != (os.fstat(self.fd).st_ino, os.fstat(self.fd).st_dev) \
                    or _fd_digest(fd) != self.sha256:
                raise ValueError(_CAPABILITY)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _fd_digest(fd):
    value, offset = sha256(), 0
    while chunk := os.pread(fd, 1024 * 1024, offset):
        value.update(chunk)
        offset += len(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return value.hexdigest()


class Admission:
    """The image a Gemini heartbeat leg executes, with exactly one admission class."""

    def __init__(self, image, help_sha256, admission_class, path=None):
        if admission_class not in ADMISSION_CLASSES:
            raise ValueError(_CAPABILITY)
        self.image, self.help_sha256, self.admission_class, self.path = image, help_sha256, admission_class, path

    def close(self):
        self.image.close()


class AdmissionMiss(ValueError):
    """No admission for a non-release image; carries the VerifiedImage for first use."""

    def __init__(self, image, path):
        super().__init__(_CAPABILITY)
        self.image, self.path = image, path


def _read_image(path):
    """The single read of the resolved agy (I1): final target, O_NOFOLLOW, regular, capped."""
    fd = os.open(os.path.realpath(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_IMAGE_BYTES:
            raise ValueError(_CAPABILITY)
        chunks, size = [], 0
        while chunk := os.read(fd, 1024 * 1024):
            size += len(chunk)
            if size > _MAX_IMAGE_BYTES:
                raise ValueError(_CAPABILITY)
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _local_capabilities():
    _linux_memfd_seal_abi()
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise ValueError(_CAPABILITY)
    fd = _sealed_tree_fd(data=b"", executable=False, label="agy-capability")
    os.close(fd)
    fd = os.pidfd_open(os.getpid())
    try:
        signal.pidfd_send_signal(fd, 0)
    finally:
        os.close(fd)


def admit(env, *, keep_miss=False):
    """Admission, lookup only; never qualifies, never touches the network.

    1. A release-qualified digest is admitted before any config, store or network read (I6).
    2. Otherwise the lookup (opt-out, failed entry, provenance-gated help, qualified entry)
       lives in ``agy_qualification``; a miss refuses with today's
       ``gemini_heartbeat_capability_unavailable`` (``keep_miss=True``, for
       ``ensure_admitted`` only, raises ``AdmissionMiss`` carrying the image instead).
    """
    try:
        _local_capabilities()
        if _CANDIDATE is not None:
            return Admission(VerifiedImage(_CANDIDATE.reopen(), _CANDIDATE.sha256),
                             QUALIFIED_IMAGES.get(_CANDIDATE.sha256), "qualification_candidate")
        path = shutil.which("agy", path=env.get("PATH", os.defpath))
        if path is None:
            raise ValueError(_CAPABILITY)
        data = _read_image(path)
        digest = sha256(data).hexdigest()
        if digest in QUALIFIED_IMAGES:
            image = VerifiedImage.from_bytes(data, path)
            return Admission(image, QUALIFIED_IMAGES[digest], "release_qualified", Path(path))
    except (OSError, AgyCanaryEvidenceError, ValueError) as exc:
        raise ValueError(_CAPABILITY) from exc
    from . import agy_qualification
    try:
        return agy_qualification.lookup(env, data, path)
    except AdmissionMiss as miss:
        # Only ensure_admitted takes the miss's image for first use; every lookup-only
        # caller closes it here, so a refusal never leaks a memfd (codex B2).
        if keep_miss:
            raise
        miss.image.close()
        raise ValueError(_CAPABILITY) from None
    except (OSError, AgyCanaryEvidenceError) as exc:
        raise ValueError(_CAPABILITY) from exc


def require_capability(env):
    """Probe local capabilities and admission; never launch a provider or qualify."""
    admission = admit(env)
    try:
        return admission.path if admission.path is not None else Path(PRIVATE_HOME + "/agy")
    finally:
        admission.close()


def _proc_stat(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    return fields[0], int(fields[1]), fields[19]


class GeminiHeartbeatProfile:
    def __init__(self, env):
        self.env = {**env, "HOME": PRIVATE_HOME, "XDG_CONFIG_HOME": PRIVATE_HOME + "/.config"}
        self.executable = PRIVATE_HOME + "/agy"
        self._fds = set()
        self.process = None
        self.init_fd = None
        self.namespace_fd = None
        self.identity = None
        self.quiescent = False
        self.closed = False
        self.evidence = {"provider_isolation_profile": PROFILE_ID,
                         "provider_agy_home_cleanup_verified": False}

    @property
    def owned_fds(self):
        return tuple(sorted(self._fds))

    @property
    def pass_fds(self):
        return self.image_fd, self.settings_fd, self.info_write_fd, self.gate_read_fd

    def _own(self, fd):
        self._fds.add(fd)
        return fd

    def _close(self, fd):
        if fd in self._fds:
            os.close(fd)
            self._fds.remove(fd)

    def pin_identity(self, info, proc):
        pending = []
        try:
            pid = info["child-pid"]
            if type(pid) is not int or pid <= 0:
                raise ValueError(_ADMISSION)
            init_fd = self._own(os.pidfd_open(pid))
            pending.append(init_fd)
            ns_fd = self._own(os.open(f"/proc/{pid}/ns/pid", os.O_RDONLY | os.O_CLOEXEC))
            pending.append(ns_fd)
            ns = os.fstat(ns_fd)
            own_ns = os.stat("/proc/self/ns/pid")
            if (ns.st_dev, ns.st_ino) == (own_ns.st_dev, own_ns.st_ino):
                raise ValueError(_ADMISSION)
            state, parent, start = _proc_stat(pid)
            nspid = next(line for line in Path(f"/proc/{pid}/status").read_text().splitlines()
                         if line.startswith("NSpid:"))
            if int(nspid.split()[-1]) != 1 or state == "Z":
                raise ValueError(_ADMISSION)
            for _ in range(64):
                if parent == proc.pid:
                    break
                if parent <= 1:
                    raise ValueError(_ADMISSION)
                _, parent, _ = _proc_stat(parent)
            else:
                raise ValueError(_ADMISSION)
            if select.select([init_fd], [], [], 0)[0] or _proc_stat(pid)[2] != start:
                raise ValueError(_ADMISSION)
            self.init_fd, self.namespace_fd = init_fd, ns_fd
            self.identity = {"init_pid": pid, "init_start": start,
                             "pid_namespace_device": ns.st_dev, "pid_namespace_inode": ns.st_ino}
            self.evidence["provider_namespace_identity"] = dict(self.identity)
        except (OSError, ValueError, KeyError, IndexError, StopIteration) as exc:
            for fd in pending:
                self._close(fd)
            raise ValueError(_ADMISSION) from exc

    def admit(self, proc, cancel, *, admission_s=10):
        """Bound the entire blocked-wrapper handshake using the real local clock."""
        self.process = proc
        deadline = time.monotonic() + admission_s
        self._close(self.info_write_fd)
        self._close(self.gate_read_fd)
        data = bytearray()
        try:
            while True:
                if cancel.is_set():
                    raise ValueError("review_operation_cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0 or proc.poll() is not None:
                    raise ValueError(_ADMISSION)
                if not select.select([self.info_read_fd], [], [], min(.05, remaining))[0]:
                    continue
                chunk = os.read(self.info_read_fd, 4096)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > 4096:
                    raise ValueError(_ADMISSION)
            self.pin_identity(json.loads(data), proc)
            if cancel.is_set():
                raise ValueError("review_operation_cancelled")
            if time.monotonic() >= deadline:
                raise ValueError(_ADMISSION)
            os.write(self.gate_write_fd, b"1")
            self._close(self.gate_write_fd)
            self._close(self.info_read_fd)
        except (OSError, ValueError, TypeError) as exc:
            # EOF releases bwrap's gate. The caller must reap the blocked wrapper
            # BEFORE the profile context closes the gate's remaining write end.
            reason = "review_operation_cancelled" if cancel.is_set() else _ADMISSION
            raise ValueError(reason) from exc

    def observe_quiescence(self):
        if self.identity is None:
            raise GeminiQuiescenceError("gemini_heartbeat_quiescence_unverified")
        live = []
        unreadable = 0
        identity = (self.identity["pid_namespace_device"], self.identity["pid_namespace_inode"])
        try:
            held = os.fstat(self.namespace_fd)
            if (held.st_dev, held.st_ino) != identity:
                raise GeminiQuiescenceError("gemini_heartbeat_quiescence_unverified")
            exited = bool(select.select([self.init_fd], [], [], 0)[0])
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    ns = (entry / "ns/pid").stat()
                    if (ns.st_dev, ns.st_ino) == identity:
                        state, _, start = _proc_stat(int(entry.name))
                        if state != "Z":
                            live.append({"pid": int(entry.name), "start": start})
                except OSError as exc:
                    if exc.errno in (errno.ENOENT, errno.ESRCH):
                        continue
                    if exc.errno in (errno.EACCES, errno.EPERM):
                        unreadable += 1
                        continue
                    raise
            return {"init_exited": exited, "live_members": live, "unreadable_entries": unreadable}
        except (OSError, ValueError, IndexError) as exc:
            raise GeminiQuiescenceError("gemini_heartbeat_quiescence_unverified") from exc

    def verify_quiescence(self, *, grace_s=5):
        deadline = time.monotonic() + grace_s
        signalled = False
        while True:
            observation = self.observe_quiescence()
            self.evidence["provider_namespace_quiescence"] = observation
            # The held init pidfd proves namespace-init exit; the retained PID
            # namespace prevents reuse during the corroborating /proc scan.
            if observation["init_exited"] and not observation["live_members"]:
                self.quiescent = True
                return
            if not signalled:
                try:
                    signal.pidfd_send_signal(self.init_fd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    raise GeminiQuiescenceError("gemini_heartbeat_quiescence_unverified") from exc
                signalled = True
            if time.monotonic() >= deadline:
                raise GeminiQuiescenceError("gemini_heartbeat_quiescence_unverified")
            time.sleep(.01)

    def close(self):
        if self.process is not None and self.process.poll() is None:
            # Retain the gate on a fatal unreaped launch; closing it could execute
            # a still-blocked provider. Normal teardown always reaps first.
            raise GeminiQuiescenceError("gemini_heartbeat_quiescence_unverified")
        for fd in tuple(self._fds):
            self._close(fd)
        self.closed = True
        self.evidence["provider_owned_fds_closed"] = True
        self.evidence["provider_agy_home_cleanup_verified"] = self.quiescent


@contextmanager
def owned_profile(env, *, settings_bytes, credential_path, admission=None):
    """An owned agy profile over ONE admitted image (agent-harness#1076).

    With no ``admission`` the profile admits once (lookup only). The image bound into the
    sandbox is an independent read of the admission's sealed memfd, re-hashed here, so
    the executed bytes are the verified bytes whatever happens to the PATH file.
    """
    owned = admission is None
    if owned:
        admission = admit(env)
    profile = GeminiHeartbeatProfile(env)
    try:
        try:
            credential_mode = Path(credential_path).stat().st_mode
        except OSError as exc:
            raise ValueError("brokered Gemini subscription credential reference is unavailable") from exc
        if not stat.S_ISREG(credential_mode):
            raise ValueError("brokered Gemini subscription credential reference is invalid")
        try:
            image_sha256 = admission.image.sha256
            profile.image_fd = profile._own(admission.image.reopen())
            profile.settings_fd = profile._own(_sealed_tree_fd(data=settings_bytes, executable=False, label="agy-settings"))
            os.fchmod(profile.settings_fd, 0o400)
            profile.info_read_fd, profile.info_write_fd = os.pipe2(os.O_CLOEXEC)
            profile._fds.update((profile.info_read_fd, profile.info_write_fd))
            profile.gate_read_fd, profile.gate_write_fd = os.pipe2(os.O_CLOEXEC)
            profile._fds.update((profile.gate_read_fd, profile.gate_write_fd))
            config = PRIVATE_HOME + "/.gemini/antigravity-cli"
            profile.mount_args = ["--info-fd", str(profile.info_write_fd), "--block-fd", str(profile.gate_read_fd)]
            for directory in (PRIVATE_HOME, PRIVATE_HOME + "/.gemini", config, PRIVATE_HOME + "/.config"):
                profile.mount_args += ["--perms", "0700", "--dir", directory]
            profile.mount_args += [
                "--perms", "0500", "--ro-bind-data", str(profile.image_fd), profile.executable,
                "--perms", "0400", "--ro-bind-data", str(profile.settings_fd), config + "/settings.json",
                "--symlink", str(Path(credential_path).absolute()), config + "/antigravity-oauth-token",
            ]
            settings_hash = sha256(settings_bytes).hexdigest()
            description = {"id": PROFILE_ID, "image_sha256": image_sha256,
                           "settings_sha256": settings_hash, "home": PRIVATE_HOME}
            profile.evidence.update({
                "provider_image_sha256": image_sha256,
                "provider_admission_class": admission.admission_class,
                "provider_agy_settings_sha256": settings_hash,
                "provider_profile_sha256": sha256(json.dumps(description, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "provider_agy_subscription_reference": "private_symlink",
            })
        except (OSError, AgyCanaryEvidenceError) as exc:
            raise ValueError(_CAPABILITY) from exc
        yield profile
    finally:
        try:
            profile.close()
        finally:
            if owned:
                admission.close()
