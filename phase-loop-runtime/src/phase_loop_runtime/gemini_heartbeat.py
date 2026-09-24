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


QUALIFIED_IMAGE_SHA256 = "1dbb10f8295cc1ad2e558bd006c7808fe53b6c7f678a887eb557b576bb591711"
QUALIFIED_HELP_SHA256 = "5a03bf7dc9d3d7645f5853906cc117363fd8978a79c2a89521f0ff7590dbe454"
PROFILE_ID = "agy_memfd_home_deny_all_v1"
PRIVATE_HOME = "/dev/phase-loop-agy"
_CAPABILITY = "gemini_heartbeat_capability_unavailable"
_ADMISSION = "gemini_heartbeat_admission_handshake_failed"


class GeminiQuiescenceError(RuntimeError):
    pass


def _read_image(path):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(_CAPABILITY)
        chunks = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        data = b"".join(chunks)
        if sha256(data).hexdigest() != QUALIFIED_IMAGE_SHA256:
            raise ValueError(_CAPABILITY)
        return data
    finally:
        os.close(fd)


def require_capability(env):
    """Probe only local capabilities and image bytes; never launch a provider."""
    try:
        _linux_memfd_seal_abi()
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise ValueError(_CAPABILITY)
        image = shutil.which("agy", path=env.get("PATH", os.defpath))
        if image is None:
            raise ValueError(_CAPABILITY)
        _read_image(image)
        fd = _sealed_tree_fd(data=b"", executable=False, label="agy-capability")
        os.close(fd)
        fd = os.pidfd_open(os.getpid())
        try:
            signal.pidfd_send_signal(fd, 0)
        finally:
            os.close(fd)
        return Path(image)
    except (OSError, AgyCanaryEvidenceError, ValueError) as exc:
        raise ValueError(_CAPABILITY) from exc


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
def owned_profile(env, *, settings_bytes, credential_path):
    image = require_capability(env)
    profile = GeminiHeartbeatProfile(env)
    try:
        try:
            credential_mode = Path(credential_path).stat().st_mode
        except OSError as exc:
            raise ValueError("brokered Gemini subscription credential reference is unavailable") from exc
        if not stat.S_ISREG(credential_mode):
            raise ValueError("brokered Gemini subscription credential reference is invalid")
        try:
            data = _read_image(image)
            profile.image_fd = profile._own(_sealed_tree_fd(data=data, executable=True, label="agy-image"))
            copied = sha256()
            while chunk := os.read(profile.image_fd, 1024 * 1024):
                copied.update(chunk)
            if copied.hexdigest() != QUALIFIED_IMAGE_SHA256:
                raise ValueError(_CAPABILITY)
            os.lseek(profile.image_fd, 0, os.SEEK_SET)
            os.fchmod(profile.image_fd, 0o500)
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
            description = {"id": PROFILE_ID, "image_sha256": QUALIFIED_IMAGE_SHA256,
                           "settings_sha256": settings_hash, "home": PRIVATE_HOME}
            profile.evidence.update({
                "provider_image_sha256": QUALIFIED_IMAGE_SHA256,
                "provider_agy_settings_sha256": settings_hash,
                "provider_profile_sha256": sha256(json.dumps(description, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "provider_agy_subscription_reference": "private_symlink",
            })
        except (OSError, AgyCanaryEvidenceError) as exc:
            raise ValueError(_CAPABILITY) from exc
        yield profile
    finally:
        profile.close()
