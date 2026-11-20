"""Linux ownership for the qualified, brokered Gemini heartbeat route."""
from contextlib import contextmanager
from hashlib import sha256
from datetime import datetime
import errno
from importlib import resources
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import stat
import time

from . import agy_provenance
from .agy_canary_evidence import AgyCanaryEvidenceError, _linux_memfd_seal_abi, _sealed_tree_fd


# The shipped agy catalog (AGYROLL §3.1): package data, schema ``qualified_agy_catalog.v3``.
# Each member names its own v2 qualification record under plans/evidence/, bound to the seat
# QCI (``agy_qualification.seat_qci()``); ``verify_qualified_agy_image.py --contract`` checks
# them on every pull request. Adding a member edits only the data file, never this module.
CATALOG_SCHEMA = "qualified_agy_catalog.v3"
CATALOG_ROUTE = "linux-x64"
_CATALOG_MEMBER_KEYS = frozenset({"release_version", "image_sha256", "help_sha256", "asset_sha256",
                                  "qci", "published_at", "pinned", "record"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_RELEASE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_RFC3339 = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]+)?"
                      r"(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])")
#: Why the last ``load_catalog`` call returned what it did: ``ok``, ``missing``,
#: ``malformed`` or ``empty``. Anything but ``ok`` is an empty catalog (fail-closed).
CATALOG_STATUS = "unloaded"


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("agy catalog repeats a key")
        value[key] = item
    return value


def parse_catalog(text: str) -> list[dict]:
    """The members of a ``qualified_agy_catalog.v3`` document, or ``ValueError``. Closed keys,
    hex64 digests, unique images, versions and records, exactly the ``linux-x64`` route."""
    catalog = json.loads(text, object_pairs_hook=_unique_object)
    if not isinstance(catalog, dict) or set(catalog) != {"schema", "routes"} or catalog["schema"] != CATALOG_SCHEMA:
        raise ValueError("agy catalog schema mismatch")
    routes = catalog["routes"]
    if not isinstance(routes, dict) or set(routes) != {CATALOG_ROUTE} or not isinstance(routes[CATALOG_ROUTE], list):
        raise ValueError("agy catalog route mismatch")
    members = routes[CATALOG_ROUTE]
    for member in members:
        if not isinstance(member, dict) or set(member) != _CATALOG_MEMBER_KEYS:
            raise ValueError("agy catalog member keys mismatch")
        if not all(isinstance(member[key], str) and _HEX64.fullmatch(member[key])
                   for key in ("image_sha256", "help_sha256", "asset_sha256", "qci")):
            raise ValueError("agy catalog digest malformed")
        version = member["release_version"]
        if not isinstance(version, str) or not _RELEASE.fullmatch(version):
            raise ValueError("agy catalog release version malformed")
        if not isinstance(member["published_at"], str) or not _RFC3339.fullmatch(member["published_at"]):
            raise ValueError("agy catalog published_at malformed")
        # a real calendar instant, not just its shape (agent-harness#1937 review B5)
        datetime.fromisoformat(member["published_at"].replace("z", "Z"))
        if type(member["pinned"]) is not bool:
            raise ValueError("agy catalog pinned is not a bool")
        if member["record"] != f"agy-{version}-linux-x64-qualification.json":
            raise ValueError("agy catalog record name mismatch")
    for key in ("image_sha256", "release_version", "record"):
        if len({member[key] for member in members}) != len(members):
            raise ValueError(f"agy catalog repeats a {key}")
    return members


def load_catalog(path=None) -> dict[str, str]:
    """``image_sha256 -> help_sha256`` from the shipped catalog (or ``path``). Strict, offline,
    and never raises: a missing or malformed file is an empty catalog, so the release fast
    path admits nothing and every image takes local qualification or a refusal."""
    global CATALOG_STATUS
    try:
        if path is None:
            text = resources.files(__package__).joinpath("data", "agy_catalog.json").read_text(encoding="utf-8")
        else:
            text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        CATALOG_STATUS = "missing"
        return {}
    try:
        members = parse_catalog(text)
    except (ValueError, TypeError, KeyError, RecursionError):
        CATALOG_STATUS = "malformed"
        return {}
    if not members:
        CATALOG_STATUS = "empty"
        return {}
    CATALOG_STATUS = "ok"
    return {member["image_sha256"]: member["help_sha256"] for member in members}


# The closed set of qualified agy entry images: image SHA256 -> its measured `--help` SHA256.
QUALIFIED_IMAGES = load_catalog()
PROFILE_ID = "agy_memfd_home_deny_all_v1"
PRIVATE_HOME = "/dev/phase-loop-agy"
_CAPABILITY = "gemini_heartbeat_capability_unavailable"
_ADMISSION = "gemini_heartbeat_admission_handshake_failed"


class GeminiQuiescenceError(RuntimeError):
    pass


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

    @classmethod
    def from_fd(cls, fd, *, path=None):
        """Stream an opened, ``fstat``-checked image descriptor into one sealed memfd (AGYFRESH §1.2).

        The image is copied in 1 MiB chunks through one reused buffer while it is hashed, so
        it exists once, in the memfd. The sealed memfd is re-hashed through the same buffer,
        so peak anonymous memory is one chunk. Above ``agy_provenance.MAX_MEMBER_BYTES``
        (read at call time) it refuses. The memfd gets the mode and seals of ``from_bytes``.
        ``fd`` stays the caller's to close.
        """
        digest, size = sha256(), 0
        buffer = bytearray(_CHUNK_BYTES)
        view = memoryview(buffer)
        image = _new_image_memfd()
        try:
            while count := os.readv(fd, [buffer]):
                size += count
                if size > agy_provenance.MAX_MEMBER_BYTES:
                    raise ValueError(_CAPABILITY)
                digest.update(view[:count])
                written = 0
                while written < count:
                    step = os.write(image, view[written:count])
                    if step <= 0:
                        raise OSError(errno.EIO, "agy image memfd short write")
                    written += step
            _seal_image_memfd(image)
            os.fchmod(image, 0o500)
            if _fd_digest_into(image, buffer) != digest.hexdigest():
                raise ValueError(_CAPABILITY)
        except BaseException:
            os.close(image)
            raise
        return cls(image, digest.hexdigest(), path)

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


_CHUNK_BYTES = 1024 * 1024


def _new_image_memfd():
    """An empty, sealable image memfd, created as ``_sealed_tree_fd(executable=True)`` does."""
    _linux_memfd_seal_abi()
    fd = os.memfd_create("agy-image", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.fchmod(fd, 0o755)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _seal_image_memfd(fd):
    """Apply and confirm the seals ``_sealed_tree_fd`` applies; a failure is the seal error."""
    import fcntl

    seal_abi = _linux_memfd_seal_abi()
    required = (seal_abi["F_SEAL_WRITE"] | seal_abi["F_SEAL_GROW"]
                | seal_abi["F_SEAL_SHRINK"] | seal_abi["F_SEAL_SEAL"])
    try:
        os.fsync(fd)
        fcntl.fcntl(fd, seal_abi["F_ADD_SEALS"], required)
        if fcntl.fcntl(fd, seal_abi["F_GET_SEALS"]) != required:
            raise AgyCanaryEvidenceError("agy image memfd sealing did not hold")
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError as exc:
        raise AgyCanaryEvidenceError("agy image memfd sealing failed") from exc


def _fd_digest_into(fd, buffer):
    """``_fd_digest`` through a caller's reused buffer: no allocation per chunk."""
    value, offset, view = sha256(), 0, memoryview(buffer)
    while count := os.preadv(fd, [buffer], offset):
        value.update(view[:count])
        offset += count
    os.lseek(fd, 0, os.SEEK_SET)
    return value.hexdigest()


def _fd_digest(fd):
    value, offset = sha256(), 0
    while chunk := os.pread(fd, 1024 * 1024, offset):
        value.update(chunk)
        offset += len(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return value.hexdigest()


class Admission:
    """The image a Gemini heartbeat leg executes, with exactly one admission class."""

    def __init__(self, image, help_sha256, admission_class, path=None, *, source="subject"):
        if admission_class not in ADMISSION_CLASSES:
            raise ValueError(_CAPABILITY)
        if source not in {"subject", "lkg"}:
            raise ValueError(_CAPABILITY)
        self.image, self.help_sha256, self.admission_class = image, help_sha256, admission_class
        self.path, self.source = path, source

    def close(self):
        self.image.close()


class AdmissionMiss(ValueError):
    """No admission for a non-release image; carries the VerifiedImage for first use."""

    def __init__(self, image, path):
        super().__init__(_CAPABILITY)
        self.image, self.path = image, path


def _open_image_fd(path):
    """Open the resolved agy (I1): final target, O_NOFOLLOW, regular, within the member bound."""
    fd = os.open(os.path.realpath(path), os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > agy_provenance.MAX_MEMBER_BYTES:
            raise ValueError(_CAPABILITY)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_image(path):
    """The single read of the resolved agy (I1), streamed into one sealed memfd (AGYFRESH §1.2)."""
    fd = _open_image_fd(path)
    try:
        return VerifiedImage.from_fd(fd, path=path)
    finally:
        os.close(fd)


def _read_image(path):
    """The resolved agy's bytes, for callers that need them (one read, capped at call time).

    Seat admission uses ``_open_image``, which never holds the image outside its memfd.
    """
    fd = _open_image_fd(path)
    try:
        chunks, size = [], 0
        while chunk := os.read(fd, _CHUNK_BYTES):
            size += len(chunk)
            if size > agy_provenance.MAX_MEMBER_BYTES:
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


def admit(env, *, subject_path=None, keep_miss=False):
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
        path = (os.fspath(subject_path) if subject_path is not None
                else shutil.which("agy", path=env.get("PATH", os.defpath)))
        if path is None:
            raise ValueError(_CAPABILITY)
        image = _open_image(path)
        if image.sha256 in QUALIFIED_IMAGES:
            return Admission(image, QUALIFIED_IMAGES[image.sha256], "release_qualified", Path(path),
                             source="subject")
    except (OSError, AgyCanaryEvidenceError, ValueError) as exc:
        raise ValueError(_CAPABILITY) from exc
    from . import agy_qualification
    try:
        # lookup takes ownership of the image: it is closed there unless it is handed on.
        return agy_qualification.lookup(env, image, path)
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
