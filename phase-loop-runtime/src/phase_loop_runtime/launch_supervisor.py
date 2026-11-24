"""Local LaneExec supervisor transactions and private file operations."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import stat
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from . import sandbox_policy, supervised_launch_binding
from .convergence.adapters.patch_return import WorkerResult
from .launch_lifetime import LaunchLifetime
from .launch_process_contract import (
    LaunchEvidence,
    LaunchResponse,
    PreparedPaths,
    SnapshotEvidence,
    Termination,
    decode_launch_request,
    encode_launch_response,
)
from .placement_process_contract import canonical_bytes
from .run_status import process_start_identity
from .sandbox_placement import ANSWER_BOUND_S, Debt, PlacementLifecycle
from .supervised_envelope_v2 import canonicalize_v2, parse_v2
from .supervised_worker_cli import ControllerSnapshot, read_controller_snapshot


@contextlib.contextmanager
def trusted_directory(path, *, path_only=False):
    """Hold the exact directory reached by a no-follow walk from the filesystem root."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("untrusted directory")
    flags = (os.O_PATH if path_only else os.O_RDONLY) | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
                raise ValueError("untrusted directory")
        yield fd
    finally:
        os.close(fd)


def local_devices(directories):
    """Return the verified device, raising before claim or at the chain-start recheck."""
    witness = sandbox_policy.staging_root()
    observed = os.stat(witness)
    device = observed.st_dev
    for directory in directories:
        with trusted_directory(directory) as fd:
            info = os.fstat(fd)
            if os.major(info.st_dev) == 0:
                raise ValueError("anonymous attempt device")
            if info.st_dev != device:
                raise ValueError("different staging device")
    return device, observed.st_ino


def publish_controller(controller, expected_digest, envelope):
    """Publish or reuse only the exact, trusted controller document admitted earlier."""
    if not 0 < len(controller) <= 1 << 20 or hashlib.sha256(controller).hexdigest() != expected_digest:
        return False
    locator = supervised_launch_binding.read_binding_locator(supervised_launch_binding.MANAGED_BINDING)
    if not isinstance(locator, supervised_launch_binding.BindingLocator):
        return False
    h = hashlib.sha256(envelope).hexdigest()
    name = h + ".json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    with trusted_directory(locator.controller_root) as directory:
        try:
            fd = os.open(name, flags, 0o600, dir_fd=directory)
        except FileExistsError:
            snapshot = read_controller_snapshot(locator.controller_root, h)
            return isinstance(snapshot, ControllerSnapshot) and snapshot.raw_bytes == controller
        with os.fdopen(fd, "wb") as stream:
            created = os.fstat(fd)
            try:
                stream.write(controller)
                stream.flush()
                os.fsync(fd)
                os.fsync(directory)
                snapshot = read_controller_snapshot(locator.controller_root, h)
                if not isinstance(snapshot, ControllerSnapshot) or snapshot.raw_bytes != controller:
                    raise ValueError("controller verification failed")
                if snapshot.locations[-1] != (created.st_dev, created.st_ino):
                    raise ValueError("controller replaced")
                return True
            except (OSError, ValueError):
                current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                    os.unlink(name, dir_fd=directory)
                    os.fsync(directory)
                return False


def _read_exact(conn, size, deadline):
    import time

    data = bytearray()
    while len(data) < size:
        conn.settimeout(max(0, deadline - time.monotonic()))
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise ValueError("short frame")
        data.extend(chunk)
    return bytes(data)


def _read_frame(conn, cap, deadline):
    from .placement_process_contract import load_strict_object

    size = int.from_bytes(_read_exact(conn, 4, deadline), "big")
    if not 0 < size <= cap:
        raise ValueError("frame length")
    return load_strict_object(_read_exact(conn, size, deadline))


def _send_frame(conn, value):
    from .placement_process_contract import canonical_bytes

    data = canonical_bytes(value)
    conn.sendall(len(data).to_bytes(4, "big") + data)


class CancelListener:
    """Serve the lifecycle's authenticated, generation-specific cancellation protocol."""

    def __init__(self, lifecycle, ids, owner, cancelled):
        import threading

        self.life = lifecycle
        self.ids = ids
        self.owner = owner
        self.cancelled = cancelled
        self.stop = threading.Event()

    def _serve(self, listener):
        import socket
        import struct
        import time

        from .run_status import process_start_identity

        rid, req, generation = self.ids
        while not self.stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                try:
                    deadline = time.monotonic() + 1
                    cred = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                    pid, uid, _ = struct.unpack("3i", cred)
                    start = process_start_identity(pid)
                    if uid != os.geteuid() or not start:
                        continue
                    frame = _read_frame(conn, 4096, deadline)
                    expected = dict(
                        version=1,
                        op="cancel",
                        reservation_id=rid,
                        request_id=req,
                        generation=generation,
                        sender_pid=pid,
                        sender_start=start,
                    )
                    if (
                        frame != expected
                        or type(frame["version"]) is not int
                        or type(frame["sender_pid"]) is not int
                        or conn.recv(1)
                        or start != process_start_identity(pid)
                    ):
                        continue
                    outcome = "owner_unverified"
                    with self.life.launch_operation_lock(
                        rid, generation, timeout_s=max(0, deadline - time.monotonic())
                    ) as held:
                        claim = self.life.launch_claim_record(rid) if held else None
                        if (
                            claim
                            and claim.get("generation") == generation
                            and claim.get("claimed")
                            and claim.get("request_id") == req
                            and claim.get("owner") == self.owner
                        ):
                            if self.life.launch_terminal(req):
                                outcome = "already_terminal"
                            else:
                                self.cancelled.set()
                                outcome = "cancel_pending"
                    _send_frame(conn, dict(version=1, generation=generation, outcome=outcome))
                except (OSError, ValueError):
                    continue

    @contextlib.contextmanager
    def serving(self):
        import socket
        import threading

        with trusted_directory(self.life.launch_root / "ctl", path_only=True) as directory:
            info = os.fstat(directory)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("control directory")
            name = self.ids[2] + ".sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(f"/proc/self/fd/{directory}/{name}")
                original = os.stat(name, dir_fd=directory, follow_symlinks=False)
                try:
                    os.chmod(name, 0o600, dir_fd=directory)
                    listener.listen(4)
                    listener.settimeout(0.05)
                    thread = threading.Thread(target=self._serve, args=(listener,), daemon=True)
                    thread.start()
                    try:
                        yield
                    finally:
                        self.stop.set()
                        thread.join()
                finally:
                    current = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == (original.st_dev, original.st_ino):
                        os.unlink(name, dir_fd=directory)


def write_blob(directory, name, raw):
    with trusted_directory(directory) as root:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
        os.fsync(root)


def read_blob(directory_fd, name, cap):
    if Path(name).name != name or name in (".", ".."):
        raise ValueError("invalid blob name")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(name, flags, dir_fd=directory_fd), "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or info.st_size > cap
        ):
            raise ValueError("invalid private blob")
        raw = stream.read(cap + 1)
        if len(raw) != info.st_size or len(raw) > cap:
            raise ValueError("changed blob")
        return raw


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SupervisorHandoff:
    version: int
    client: str
    reservation_id: str
    request_id: str
    run_id: str
    generation: str
    stage: str
    withhold_required: bool
    digests: Mapping
    inventory_fd: int
    stage_fd: int
    controller: bytes
    controller_sha256: str
    local_verdict: Callable | None = None

    @property
    def ids(self):
        return self.reservation_id, self.request_id, self.generation

    def message(self):
        keys = (
            "version",
            "client",
            "reservation_id",
            "request_id",
            "run_id",
            "generation",
            "stage",
            "withhold_required",
            "digests",
        )
        return {key: getattr(self, key) for key in keys}


@dataclass(frozen=True)
class StagedCapture:
    generation: str
    stage_id: tuple[int, int]
    stage_fd: int
    tree: str
    scratch: str
    snapshot_sha256: str
    seed_sha256: str | None
    recipe_sha256: str
    paths: PreparedPaths
    tree_fd: int
    scratch_fd: int


@dataclass(frozen=True)
class SupervisorEffects:
    lifecycle: PlacementLifecycle
    capped_popen: Callable
    load_caps: Callable
    readiness_code: Callable
    clock: Callable
    verdict: Callable | None = None
    run_staged: Callable | None = None
    # A fixture supplies verified containment/result observations. Production
    # has no provider until SEATS and WORKER publish the reviewed interfaces.
    observe_result: Callable | None = None
    containment_ready: Callable | None = None
    child_stream: Callable | None = None
    signal_group: Callable | None = None


def _owner():
    pid = os.getpid()
    start = process_start_identity(pid)
    return {"pid": pid, "start": start} if start else None


def _same_directory(fd, path):
    with trusted_directory(path) as local:
        a = os.fstat(fd)
        b = os.fstat(local)
        return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino) and (
            a.st_uid == os.geteuid() and stat.S_IMODE(a.st_mode) == 0o700
        )


def _cas(life, handoff, before, owner, **changes):
    with life.launch_request_lock(handoff.request_id, timeout_s=ANSWER_BOUND_S) as held:
        record = life.launch_record(handoff.request_id) if held else None
        if (
            not record
            or record["generation"] != handoff.generation
            or record["owner"] != owner
            or record["reservation_id"] != handoff.reservation_id
            or record["phase"] != before
        ):
            return False
        life.write_launch_record(handoff.request_id, dict(record, **changes))
        return True


def _transfer(life, handoff, child, paths, digest):
    owner = _owner()
    with life.launch_request_lock(handoff.request_id, timeout_s=ANSWER_BOUND_S) as held:
        record = life.launch_record(handoff.request_id) if held else None
        if (
            not record
            or record["owner"] != owner
            or record["phase"] != "caller"
            or record["reservation_id"] != handoff.reservation_id
            or record["generation"] != handoff.generation
            or process_start_identity(child["pid"]) != child["start"]
            or not child["start"]
        ):
            return False
        info = os.fstat(handoff.stage_fd)
        # The intermediate record makes caller death between the two writes ambiguous.
        record.update(handoff=True)
        life.write_launch_record(handoff.request_id, record)
        if not life.record_allocation(
            *handoff.ids,
            kind="stage",
            owner=child,
            run_id=handoff.run_id,
            basename=handoff.stage,
            file_id=(info.st_dev, info.st_ino),
            deadline=time.monotonic() + ANSWER_BOUND_S,
        ):
            return False
        life.write_launch_record(
            handoff.request_id,
            dict(record, phase="supervisor", owner=child, envelope_digest=digest, **paths.to_json()),
        )
        return True


def handoff_attempt(
    service,
    req,
    generation,
    stage,
    paths,
    ttl,
    argv,
    tree,
    template,
    seed,
    envelope,
    controller,
    settings,
    cancelled,
    withhold,
    witness,
):
    from .launch_exec import _refusal

    life = service.lifecycle
    limits = settings.effective_seed_limits(req.workload, req.reservation.target.kind)
    parts = {"config": service.config.canonical, "envelope": envelope, "snapshot": tree.descriptor_bytes}
    if seed.manifest is not None:
        parts["seed"] = seed.manifest
    digests = {name: _sha(raw) for name, raw in parts.items()}
    digests.setdefault("seed", None)
    body = req.to_json()
    if req.reservation_json:
        body["reservation"] = dict(req.reservation_json)
    recipe = dict(
        version=1,
        witness=witness,
        request=body,
        paths=paths.to_json(),
        argv=list(argv),
        image_links=list(template.record["image_links"]),
        seed_limits=limits,
        snapshot_sha256=tree.content_sha256,
        ttl_s=ttl,
        return_budget_s=settings.return_budget_s,
        return_max_bytes=settings.return_max_bytes,
        caps_sha256=service.config.seat_caps_sha256,
        sizes={k: len(v) for k, v in parts.items()},
    )
    raw = canonicalize_v2(recipe)
    if len(raw) > 1 << 20:
        return _refusal(req, "sandbox_launch_refused")
    digests["recipe"] = _sha(raw)
    for name, data in {**parts, "recipe": raw}.items():
        write_blob(stage, name + ".blob", data)
    with trusted_directory(life.inventory) as inventory_fd, trusted_directory(stage) as stage_fd:
        h = SupervisorHandoff(
            1,
            service.client,
            req.reservation.reservation_id,
            req.request_id,
            paths.run_id,
            generation,
            generation,
            withhold is not None,
            digests,
            inventory_fd,
            stage_fd,
            controller,
            _sha(controller),
            withhold,
        )
        if service.supervisor_runner:
            child = _owner()
            if child is None:
                return _refusal(req, "sandbox_placement_capability_unmet")
            if _transfer(life, h, child, paths, parse_v2(envelope).value["envelope_digest"]):
                try:
                    service.supervisor_runner(h)
                except (OSError, ValueError):
                    # The durable request and claim determine whether this observation is uncertain.
                    pass
        else:
            try:
                detached(service, h, paths, cancelled, withhold)
            except (OSError, ValueError):
                pass
    terminal = life.launch_terminal(req.request_id)
    if terminal is not None:
        return terminal
    record = life.launch_record(req.request_id)
    if (
        record
        and record["phase"] == "caller"
        and not record.get("handoff")
        and not service._claim_held(record, req.request_id)
    ):
        return _refusal(req, "sandbox_placement_capability_unmet")
    return service._uncertain(record, req.request_id, service._claim_held(record, req.request_id))


def _verify(h, life):
    import re

    if (
        type(h.version) is not int
        or h.version != 1
        or h.client != life.client
        or type(h.withhold_required) is not bool
        or h.stage != h.generation
        or not re.fullmatch("[a-f0-9]{32}", h.generation)
        or set(h.digests) != {"config", "recipe", "envelope", "snapshot", "seed"}
        or not all(
            (n == "seed" and d is None) or isinstance(d, str) and re.fullmatch("[a-f0-9]{64}", d)
            for n, d in h.digests.items()
        )
    ):
        raise ValueError("invalid handoff")
    stage = life.launch_root / "stages" / h.stage
    if not _same_directory(h.inventory_fd, life.inventory) or not _same_directory(h.stage_fd, stage):
        raise ValueError("staging directory mismatch")
    blobs = {}
    for name, digest in h.digests.items():
        if digest is None:
            continue
        raw = read_blob(h.stage_fd, name + ".blob", 1 << 20)
        if _sha(raw) != digest:
            raise ValueError("staging digest mismatch")
        blobs[name] = raw
    parsed = parse_v2(blobs["recipe"])
    if canonicalize_v2(parsed.value) != blobs["recipe"]:
        raise ValueError("recipe is not canonical")
    recipe = json.loads(blobs["recipe"])
    keys = {
        "version",
        "witness",
        "request",
        "paths",
        "argv",
        "image_links",
        "seed_limits",
        "snapshot_sha256",
        "ttl_s",
        "return_budget_s",
        "return_max_bytes",
        "caps_sha256",
        "sizes",
    }
    if (
        set(recipe) != keys
        or recipe["version"] != 1
        or recipe["sizes"] != {k: len(v) for k, v in blobs.items() if k != "recipe"}
    ):
        raise ValueError("recipe mismatch")
    req = decode_launch_request("launch", canonicalize_v2(recipe["request"]))
    paths = PreparedPaths.from_json(recipe["paths"])
    if (
        req.request_id != h.request_id
        or req.reservation.reservation_id != h.reservation_id
        or h.run_id != paths.run_id
        or req.reservation.client != h.client
        or req.reservation.config_sha256 != h.digests["config"]
        or parse_v2(blobs["config"]).value["seat_caps_sha256"] != recipe["caps_sha256"]
    ):
        raise ValueError("binding mismatch")
    record = life.launch_record(h.request_id)
    if not record or record.get("body_sha256") != _sha(canonicalize_v2(recipe["request"])):
        raise ValueError("request changed")
    from . import launch_snapshot

    descriptor = json.loads(blobs["snapshot"])
    if (
        descriptor["content_sha256"] != recipe["snapshot_sha256"]
        or launch_snapshot.tree_manifest_sha256(
            launch_snapshot._walk_tree_rows(stage / "snapshot" / "tree")
        )
        != descriptor["content_sha256"]
    ):
        raise ValueError("staged tree changed")
    return stage, blobs, recipe, req, paths


def _publish_scratch(source, generated, recipe, request, manifest):
    """Reopen the immutable seed by its declared manifest. No operator seed path is read."""
    from .launch_process_contract import SeedLimits
    from .launch_snapshot import (
        SeedRefused,
        _check_manifest,
        _list_all,
        _open_dir_at,
        _write_under,
    )

    if (request.seed is None) != (manifest is None):
        raise SeedRefused("manifest_invalid")
    entries = (
        ()
        if manifest is None
        else _check_manifest(
            manifest, request.seed, request.request_id, SeedLimits(**recipe["seed_limits"])
        )
    )
    expected = set()
    with trusted_directory(generated) as scratch:
        for entry in entries:
            rel = Path(entry.relpath)
            with trusted_directory(source / "seed" / rel.parent) as src:
                raw = read_blob(src, rel.name, entry.size)
            if len(raw) != entry.size or _sha(raw) != entry.sha256:
                raise SeedRefused("source_changed")
            _write_under(scratch, entry.relpath, raw, 0o700 if entry.executable else 0o600, expected)
        if request.reservation.target.kind == "local":
            for image_path in recipe["image_links"]:
                rel = Path(image_path).relative_to("/")
                if ".." in rel.parts or not rel.parts:
                    raise SeedRefused("image_link_conflict")
                with contextlib.ExitStack() as opened:
                    parent = scratch
                    for i, part in enumerate(rel.parts[:-1]):
                        try:
                            os.mkdir(part, mode=0o700, dir_fd=parent)
                        except FileExistsError:
                            pass
                        parent = _open_dir_at(parent, part)
                        opened.callback(os.close, parent)
                        expected.add("/".join(rel.parts[: i + 1]))
                    os.symlink(image_path, rel.name, dir_fd=parent)
                    expected.add(str(rel))
        if expected != set(_list_all(scratch, "")):
            raise SeedRefused("scratch_unprovisioned")
        for name in sorted(expected, key=lambda n: -n.count("/")):
            path = generated / name
            with trusted_directory(path.parent) as parent:
                if stat.S_ISLNK(os.stat(path.name, dir_fd=parent, follow_symlinks=False).st_mode):
                    continue
                fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        os.fsync(scratch)


def _rename_new(parent, source, target):
    """Linux renameat2(RENAME_NOREPLACE) also refuses an existing empty directory."""
    import ctypes

    with trusted_directory(parent) as directory:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
        if rename(directory, os.fsencode(source), directory, os.fsencode(target), 1):
            raise OSError(ctypes.get_errno(), "scratch publication refused")
        os.fsync(directory)


def _provision(h, effects, stage, blobs, recipe, req, paths, owner, cancelled):
    from .launch_exec import _refusal
    from .launch_snapshot import SeedRefused

    life = effects.lifecycle
    rid, key, gen = h.ids
    with life.launch_lock(rid, timeout_s=ANSWER_BOUND_S) as lock:
        if not lock.held:
            return _refusal(req, "sandbox_placement_operation_timeout")
        code, active = lock.window(req.reservation_json)
        if code:
            return _refusal(req, code)
        if (life.launch_claim_record(rid) or {}).get("claimed"):
            return _refusal(req, "sandbox_launch_exec_claimed")
        record = life.launch_prepare_record(rid)
        if (
            not record
            or paths != PreparedPaths.from_json(record)
            or record["snapshot_root"] != req.snapshot.root
        ):
            return _refusal(req, "sandbox_launch_input_mismatch")
        if not owner or owner != _owner() or cancelled.is_set():
            return _refusal(req, "sandbox_placement_capability_unmet")
        run = life.launch_run_dir(paths.run_id)
        generated = run / gen
        allocation = dict(kind="scratch", run_id=paths.run_id, owner=owner, basename=gen)
        claimed = False
        try:
            if not life.record_allocation(
                *h.ids, **allocation, file_id=None, deadline=time.monotonic() + ANSWER_BOUND_S
            ):
                raise SeedRefused("scratch_unprovisioned")
            with trusted_directory(run) as fd:
                os.mkdir(gen, 0o700, dir_fd=fd)
                info = os.stat(gen, dir_fd=fd, follow_symlinks=False)
                os.fsync(fd)
            if not life.record_allocation(
                *h.ids,
                **allocation,
                file_id=(info.st_dev, info.st_ino),
                deadline=time.monotonic() + ANSWER_BOUND_S,
            ):
                raise SeedRefused("scratch_unprovisioned")
            _publish_scratch(stage, generated, recipe, req, blobs.get("seed"))
            if req.reservation.target.kind == "local":
                try:
                    local_devices((stage / "snapshot" / "tree", stage / "home", stage / "out", generated))
                except (OSError, RuntimeError, ValueError):
                    return _refusal(req, "sandbox_placement_capability_unmet")
            _rename_new(run, gen, "scratch")
            directory = lock.return_dir(paths.run_id)
            code = lock.claim(key, paths.run_id, owner=owner, generation=gen)
            if code:
                return _refusal(req, code)
            claimed = True
            return directory
        except (OSError, ValueError, SeedRefused) as error:
            return replace(
                _refusal(req, "sandbox_launch_seed_refused"),
                seed_reason=error.reason if isinstance(error, SeedRefused) else "scratch_unprovisioned",
            )
        finally:
            # A failed journal write can have committed. Never collect across that ambiguity.
            actual = life.launch_claim_record(rid)
            if not claimed and not (actual and actual.get("claimed") and actual.get("generation") == gen):
                life.collect_allocation(*h.ids, kind="scratch", deadline=time.monotonic() + ANSWER_BOUND_S)


def _rollback(h, effects, cause):
    with effects.lifecycle.launch_lock(h.reservation_id, timeout_s=ANSWER_BOUND_S) as lock:
        if (
            not lock.held
            or not lock.record_rollback_intent(h.request_id, h.generation, cause=cause)
            or not effects.lifecycle.collect_allocation(
                *h.ids, kind="scratch", deadline=time.monotonic() + ANSWER_BOUND_S
            )
        ):
            return False
        return lock.rollback(h.request_id, generation=h.generation)


@dataclass(frozen=True)
class TerminatedAttempt:
    """Trusted fixture observation of the matching launcher, workers and capped parent."""

    worker_invocations: int
    worker_result: WorkerResult | None
    evidence_root: Path | None
    descendants_ended: bool
    parent_collected: bool


class LocalPiLink:
    """A single same-uid client and an explicitly supplied admitted-child duplex stream."""

    def __init__(self, root, rid):
        if not root:
            raise ValueError("local link root unavailable")
        self.root = Path(root)
        self.rid = rid
        if len(os.fsencode(self.root / rid / "link.sock")) >= 108:
            raise ValueError("local link address too long")
        self.lost = threading.Event()

    @contextlib.contextmanager
    def listening(self):
        with trusted_directory(self.root) as root:
            os.mkdir(self.rid, 0o700, dir_fd=root)
            created = os.stat(self.rid, dir_fd=root, follow_symlinks=False)
            try:
                with (
                    trusted_directory(self.root / self.rid) as directory,
                    socket.socket(socket.AF_UNIX) as listener,
                ):
                    listener.bind(f"/proc/self/fd/{directory}/link.sock")
                    node = os.stat("link.sock", dir_fd=directory, follow_symlinks=False)
                    try:
                        os.chmod("link.sock", 0o600, dir_fd=directory)
                        listener.listen(1)
                        yield listener
                    finally:
                        present = os.stat("link.sock", dir_fd=directory, follow_symlinks=False)
                        if os.path.samestat(present, node):
                            os.unlink("link.sock", dir_fd=directory)
            finally:
                present = os.stat(self.rid, dir_fd=root, follow_symlinks=False)
                if os.path.samestat(present, created):
                    os.rmdir(self.rid, dir_fd=root)

    def relay(self, listener, child, *, stop, cancelled, clock, accept_deadline):
        import select
        import struct

        try:
            with child:
                listener.settimeout(0.05)
                while not stop.is_set() and clock() < accept_deadline:
                    try:
                        peer, _ = listener.accept()
                        break
                    except TimeoutError:
                        continue
                else:
                    return
                listener.close()
                with peer:
                    _, uid, _ = struct.unpack(
                        "3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    )
                    if uid != os.geteuid():
                        return
                    peer.setblocking(False)
                    child.setblocking(False)
                    other = {peer: child, child: peer}
                    queue = {peer: bytearray(), child: bytearray()}
                    while not stop.is_set():
                        readable = [s for s in other if not queue[other[s]]]
                        writable = [s for s in other if queue[s]]
                        reads, writes, _ = select.select(readable, writable, [], 0.05)
                        for s in writes:
                            del queue[s][: s.send(queue[s])]
                        for s in reads:
                            chunk = s.recv(65536)
                            if not chunk:
                                return
                            queue[other[s]].extend(chunk)
        except (OSError, ValueError):
            pass
        finally:
            if not stop.is_set():
                self.lost.set()
                cancelled.set()


def _initial_responses(h, req, paths, recipe, blobs):
    uncertain = LaunchResponse(
        h.request_id,
        h.reservation_id,
        h.run_id,
        "uncertain",
        "sandbox_placement_lost_after_launch",
        None,
        None,
        None,
        None,
        0,
        parse_v2(blobs["envelope"]).value["envelope_digest"],
        paths.scratch_path,
        paths.tree_path,
        None,
        None,
        req.caller_context,
    )
    snapshot = json.loads(blobs["snapshot"])
    ev = LaunchEvidence(
        SnapshotEvidence.from_json(snapshot),
        None,
        req.command.template_sha256,
        req.image_digest,
        req.reservation.policy_digest,
        req.reservation.egress_sha256,
        req.reservation.transport_id,
        recipe["caps_sha256"],
        False,
        None,
        None,
        None,
        0,
        0,
    )
    failed = replace(
        uncertain,
        state="finished",
        code=None,
        evidence=ev,
        termination=Termination("failed_to_start", None, "harness"),
    )
    return uncertain, failed


def _publish_admitted_controller(h, blobs):
    try:
        published = publish_controller(h.controller, h.controller_sha256, blobs["envelope"])
    except (ValueError, OSError):
        published = False
    return published


def _local(h, effects, stage, blobs, recipe, req, paths, directory, lifetime, cancelled):
    with contextlib.ExitStack() as link_stack:
        return _local_chain(
            h, effects, stage, blobs, recipe, req, paths, directory, lifetime, cancelled, link_stack
        )


def _local_chain(h, effects, stage, blobs, recipe, req, paths, directory, lifetime, cancelled, link_stack):
    import signal
    import subprocess

    from . import openshell_artifacts
    from .launch_exec import _refusal
    from .launch_return import (
        ReturnAttempt,
        ReturnPolicy,
        collect_return,
        map_worker_result,
    )
    from .seat_resource_caps import caps_sha256
    from .seat_uid import trusted_module_argv

    life = effects.lifecycle
    uncertain, failed = _initial_responses(h, req, paths, recipe, blobs)
    ev = failed.evidence
    end = time.monotonic() + ANSWER_BOUND_S

    def record_debt(ended, collected):
        old = life.read_cleanup_debt(*h.ids)
        debt = Debt(old.cause if old else "collection_unknown", ended, collected, "inapplicable", False)
        return life.write_cleanup_debt(*h.ids, debt=debt, deadline=time.monotonic() + ANSWER_BOUND_S)

    try:
        devices = (stage / "snapshot" / "tree", stage / "home", stage / "out", Path(paths.scratch_path))
        code = effects.readiness_code()
        device = local_devices(devices)
        caps_ok = (
            code is None
            and list(device) == recipe["witness"]
            and caps_sha256(effects.load_caps()) == recipe["caps_sha256"]
        )
    except Exception:
        caps_ok = False
    if not caps_ok:
        if _rollback(h, effects, "caps_recheck_refused"):
            return _refusal(req, "sandbox_placement_capability_unmet")
        return uncertain

    link = None
    if req.workload == "pi-runner":
        try:
            link = LocalPiLink(json.loads(blobs["config"])["launch"]["local_link_root"], h.reservation_id)
            listener = link_stack.enter_context(link.listening())
        except (OSError, ValueError, KeyError):
            if _rollback(h, effects, "link_socket_creation_failed"):
                return _refusal(req, "sandbox_launch_bridge_lost")
            return uncertain
    command = trusted_module_argv(
        "phase_loop_runtime.supervised_worker_cli",
        "launch",
        "--envelope",
        str(stage / "envelope.blob"),
        "--result",
        str(stage / "worker-result"),
    )
    def settle_unstarted():
        # fence_launch acquires the operation lock itself. The outer lease still
        # owns this attempt, and this callback runs only before entry to spawn.
        cause = "collection_unknown"
        if lifetime.fenced.is_set() or effects.clock() >= lifetime.renewal_cutoff:
            cause = "renewal_lost"
        elif cancelled.is_set():
            cause = "cancel"
        deadline = time.monotonic() + ANSWER_BOUND_S
        if not life.fence_launch(*h.ids, cause=cause, deadline=deadline):
            return
        with life.launch_operation_lock(
            h.reservation_id, h.generation, timeout_s=max(0, deadline - time.monotonic())
        ) as held:
            if held:
                debt = life.read_cleanup_debt(*h.ids)
                if debt is not None:
                    life.write_cleanup_debt_locked(
                        *h.ids, debt=replace(debt, descendants_ended=True, parent_collected=True),
                        deadline=deadline,
                    )

    with (
        contextlib.ExitStack() as before_start,
        life.launch_operation_lock(
            h.reservation_id, h.generation, timeout_s=max(0, end - time.monotonic())
        ) as held,
    ):
        before_start.callback(settle_unstarted)
        if not held or cancelled.is_set() or lifetime.fenced.is_set():
            return uncertain
        before_spawn = set(threading.enumerate())
        checked_at = time.monotonic()
        remaining = lifetime.renewal_cutoff - effects.clock()
        if remaining <= 0 or not life.mark_start_intent(*h.ids, deadline=min(end, checked_at + remaining)):
            return uncertain
        # Persisting start intent may consume the remaining window.
        start = effects.clock()
        if start >= lifetime.renewal_cutoff or lifetime.fenced.is_set() or cancelled.is_set():
            return uncertain
        lifetime.started(at=start)
        # Start is authorized under the operation lock. A slow bounded spawn
        # can create its first process slightly after the renewal cutoff.
        before_start.pop_all()
        try:
            proc = effects.capped_popen(
                command,
                seat_key=f"laneexec:{h.client}:{h.reservation_id}",
                env={"PATH": "/usr/bin:/bin"},
                cwd="/",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            life.write_cleanup_debt_locked(
                *h.ids,
                debt=Debt("start_unknown", False, False, "inapplicable", False),
                deadline=time.monotonic() + ANSWER_BOUND_S,
            )
            return replace(failed, code="sandbox_placement_capability_unmet")
    relay = None
    if link is not None:
        stream = effects.child_stream(h, proc)
        stop_relay = threading.Event()
        relay = threading.Thread(
            target=link.relay,
            args=(listener, stream),
            kwargs=dict(
                stop=stop_relay,
                cancelled=cancelled,
                clock=effects.clock,
                accept_deadline=lifetime.first_start + 120,
            ),
            daemon=True,
        )
        relay.start()
        link_stack.callback(relay.join)
        link_stack.callback(stop_relay.set)
    # SEATS can reap its outer child concurrently. Only the containment provider
    # holding the actual group handle can signal it, independently of PID reuse.
    stop_reason = None
    while proc.poll() is None:
        if (
            cancelled.wait(0.05)
            or lifetime.fenced.is_set()
            or effects.clock() >= lifetime.execution_deadline
        ):
            stop_reason = "cancelled" if cancelled.is_set() or lifetime.fenced.is_set() else "timed_out"
            try:
                if effects.signal_group is None or not effects.signal_group(h, proc, signal.SIGTERM):
                    record_debt(False, False)
                    return uncertain
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if effects.signal_group is None or not effects.signal_group(h, proc, signal.SIGKILL):
                    record_debt(False, False)
                    return uncertain
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    record_debt(False, False)
                    return uncertain
            except ProcessLookupError:
                pass
            break
    lifetime.terminated()

    # Keep SEATS' own collector alive through its bounded release allowance.
    # Joining its thread alone cannot attest that the parent cgroup was collected.
    def wait_for_collectors():
        for thread in set(threading.enumerate()) - before_spawn:
            if thread is not relay and thread is not threading.current_thread():
                thread.join(max(0, lifetime.release_deadline - effects.clock()))

    link_stack.callback(wait_for_collectors)
    observed = effects.observe_result(h, proc) if effects.observe_result else None
    if not isinstance(observed, TerminatedAttempt):
        record_debt(False, False)
        return uncertain
    if observed.descendants_ended is not True:
        record_debt(False, observed.parent_collected)
        return uncertain
    if observed.worker_result is None and observed.worker_invocations != 0:
        record_debt(True, observed.parent_collected)
        return uncertain
    if observed.worker_result is not None:
        identity = observed.worker_result.identity
        admitted = parse_v2(blobs["envelope"]).value
        if (
            identity is None
            or (identity.run_id, identity.attempt_id) != (h.run_id, h.run_id)
            or identity.envelope_digest != admitted["envelope_digest"]
            or identity.assignment_digest != admitted["assignment_digest"]
            or observed.worker_invocations != observed.worker_result.worker_invocations
        ):
            record_debt(True, observed.parent_collected)
            return uncertain
    mapping = map_worker_result(observed.worker_result)
    if mapping.state == "uncertain" or mapping.termination is None:
        record_debt(True, observed.parent_collected)
        return uncertain
    termination = Termination(stop_reason, None, "harness") if stop_reason else mapping.termination
    terminal = replace(
        failed,
        termination=termination,
        worker_invocations=observed.worker_invocations,
        evidence=replace(
            ev,
            exit_status=proc.returncode,
            renewals=lifetime.confirmed_count,
            duration_ms=max(0, int((effects.clock() - lifetime.first_start) * 1000)),
        ),
    )
    if link is not None and link.lost.is_set():
        terminal = replace(
            terminal,
            code="sandbox_launch_bridge_lost",
            termination=Termination("cancelled", None, "harness"),
        )
    if lifetime.fenced.is_set():
        terminal = replace(
            terminal,
            code="sandbox_launch_liveness_lost",
            termination=Termination("cancelled", None, "harness"),
        )
    cap = recipe["return_max_bytes"]
    limits = openshell_artifacts.Limits(1 << 30, 1 << 26, 200000, 1 << 26, 1 << 26)
    policy = ReturnPolicy(limits, patch_cap=cap, result_cap=cap)
    attempt = ReturnAttempt(
        directory,
        observed.worker_result,
        observed.evidence_root,
        stage / "out",
        parse_v2(blobs["snapshot"]).value["base_commit"],
        req.snapshot.masks,
        req.snapshot.mask_dirs,
    )
    with contextlib.ExitStack() as stack:
        # The predicate runs before entering the publication transaction. Retain the
        # operation lock across SL-2's exclusive write and the terminal-record CAS.
        def withhold(data):
            if h.withhold_required:
                if h.local_verdict is not None:
                    if not _predicate_releases(
                        h.local_verdict, data, lifetime.return_deadline - effects.clock()
                    ):
                        return True
                elif (
                    effects.verdict is None or effects.verdict(data, lifetime.return_deadline) is not False
                ):
                    return True
            held = stack.enter_context(
                life.launch_operation_lock(
                    h.reservation_id,
                    h.generation,
                    timeout_s=max(0, lifetime.return_deadline - effects.clock()),
                )
            )
            claim = life.launch_claim_record(h.reservation_id) if held else None
            return (
                not held
                or not claim
                or not claim["claimed"]
                or claim.get("generation") != h.generation
                or cancelled.is_set()
                or lifetime.fenced.is_set()
                or life._generation_closed(claim)
            )

        bound = openshell_artifacts.Bound(
            time.monotonic() + max(0, lifetime.return_deadline - effects.clock()), lifetime.fenced.is_set
        )
        result = collect_return(attempt, req.result_kind, policy=policy, withhold=withhold, bound=bound)
        terminal = replace(terminal, return_=result.descriptor, code=terminal.code or result.code)
        if result.descriptor is not None:
            published = _cas(
                life,
                h,
                "supervisor",
                _owner(),
                phase="terminal",
                terminal=encode_launch_response(terminal).decode(),
            )
            if not published:
                life.write_cleanup_debt_locked(
                    *h.ids,
                    debt=Debt("collection_unknown", True, observed.parent_collected, "inapplicable", False),
                    deadline=time.monotonic() + ANSWER_BOUND_S,
                )
                return uncertain
    record_debt(True, observed.parent_collected)
    return terminal


def run_supervisor(handoff: SupervisorHandoff, *, effects: SupervisorEffects) -> None:
    from .launch_exec import _refusal

    h = handoff
    life = effects.lifecycle
    stage, blobs, recipe, req, paths = _verify(h, life)
    owner = _owner()
    cancelled = threading.Event()

    def finish(response):
        _cas(
            life,
            h,
            "supervisor",
            owner,
            phase="terminal",
            terminal=encode_launch_response(response).decode(),
        )

    with life.launch_lease_lock(h.reservation_id, timeout_s=0.05) as lease:
        if not lease:
            with life.launch_lock(h.reservation_id, timeout_s=ANSWER_BOUND_S) as lock:
                claim = life.launch_claim_record(h.reservation_id) if lock.held else None
            finish(
                _refusal(
                    req,
                    "sandbox_launch_exec_claimed"
                    if claim and claim["claimed"]
                    else "sandbox_placement_operation_timeout",
                )
            )
            life.collect_allocation(*h.ids, kind="stage", deadline=time.monotonic() + ANSWER_BOUND_S)
            return
        if req.reservation.target.kind == "local" and (
            effects.containment_ready is None
            or not effects.containment_ready()
            or req.workload == "pi-runner"
            and effects.child_stream is None
        ):
            finish(_refusal(req, "sandbox_placement_capability_unmet"))
            life.collect_allocation(*h.ids, kind="stage", deadline=time.monotonic() + ANSWER_BOUND_S)
            return
        listener = CancelListener(life, h.ids, owner, cancelled)
        with listener.serving(), contextlib.ExitStack() as workers:
            directory = _provision(h, effects, stage, blobs, recipe, req, paths, owner, cancelled)
            if isinstance(directory, LaunchResponse):
                finish(directory)
                life.collect_allocation(*h.ids, kind="stage", deadline=time.monotonic() + ANSWER_BOUND_S)
                return

            def confirmed_at():
                key = dict(
                    version=1,
                    reservation_id=h.reservation_id,
                    request_id=h.request_id,
                    generation=h.generation,
                )
                renewal = life._confirmed_renewal(key, life._disposition(key))
                return renewal["heartbeat_at"] if renewal else None

            local = req.reservation.target.kind == "local"
            initial = confirmed_at() if local else effects.clock()
            lifetime = LaunchLifetime(
                h.generation,
                recipe["ttl_s"],
                initial if initial is not None else 0,
                req.timeout_seconds,
                recipe["return_budget_s"],
                effects.clock,
                confirmation_clock=confirmed_at if local else None,
            )
            if local:
                stop = threading.Event()
                heartbeat = threading.Thread(
                    target=lifetime.renew,
                    args=(life, h.reservation_id, h.request_id, stop, cancelled.set),
                    daemon=True,
                )
                heartbeat.start()
                workers.callback(heartbeat.join)
                workers.callback(stop.set)
            if not _publish_admitted_controller(h, blobs):
                _, failed = _initial_responses(h, req, paths, recipe, blobs)
                if local:
                    life.write_cleanup_debt(
                        *h.ids,
                        debt=Debt("collection_unknown", True, True, "inapplicable", False),
                        deadline=time.monotonic() + ANSWER_BOUND_S,
                    )
                finish(failed)
                return
            if req.reservation.target.kind == "openshell":
                call = effects.run_staged
                if call is None:
                    from .launch_openshell import run_staged as call
                info = os.fstat(h.stage_fd)
                with (
                    trusted_directory(stage / "snapshot" / "tree") as tree_fd,
                    trusted_directory(life.launch_run_dir(h.run_id) / "scratch") as scratch_fd,
                ):
                    staged = StagedCapture(
                        h.generation,
                        (info.st_dev, info.st_ino),
                        h.stage_fd,
                        "tree",
                        "scratch",
                        h.digests["snapshot"],
                        h.digests["seed"],
                        h.digests["recipe"],
                        paths,
                        tree_fd,
                        scratch_fd,
                    )
                    finish(call(h, staged=staged, return_dir=directory, lifetime=lifetime))
                return
            response = _local(h, effects, stage, blobs, recipe, req, paths, directory, lifetime, cancelled)
            finish(response)
            debt = life.read_cleanup_debt(*h.ids)
            if debt and debt.descendants_ended is True and debt.parent_collected is True:
                with life.launch_lock(h.reservation_id, timeout_s=ANSWER_BOUND_S) as lock:
                    if lock.held:
                        for kind in ("stage", "scratch"):
                            life.collect_allocation(*h.ids, kind=kind, deadline=time.monotonic() + ANSWER_BOUND_S)
            elif response.state == "refused":
                life.collect_allocation(*h.ids, kind="stage", deadline=time.monotonic() + ANSWER_BOUND_S)


def _send_start(conn, h):
    import array

    raw = canonical_bytes(h.message())
    if len(raw) > 65536:
        raise ValueError("start frame oversized")
    frame = len(raw).to_bytes(4, "big") + raw
    rights = array.array("i", (h.inventory_fd, h.stage_fd))
    n = conn.sendmsg([frame], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)])
    conn.sendall(frame[n:])


def _receive_start(conn, deadline):
    import array
    import struct

    from .placement_process_contract import load_strict_object

    peer = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    if struct.unpack("3i", peer)[1] != os.geteuid():
        raise ValueError("start peer uid mismatch")
    fds = []
    try:
        # Receive exactly the header in this recvmsg. MSG_CMSG_CLOEXEC protects
        # every installed descriptor, including ones we are about to reject.
        header, ancillary, flags, _ = conn.recvmsg(4, socket.CMSG_SPACE(8 * 4), socket.MSG_CMSG_CLOEXEC)
        unexpected = False
        for level, kind, data in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                unexpected = True
                continue
            received = array.array("i")
            received.frombytes(data)
            fds.extend(received)
        if unexpected or len(fds) != 2 or flags & socket.MSG_CTRUNC:
            raise ValueError("bad directory descriptors")
        header += _read_exact(conn, 4 - len(header), deadline)
        size = int.from_bytes(header, "big")
        if not 0 < size <= 65536:
            raise ValueError("start frame length")
        raw = _read_exact(conn, size, deadline)
        msg = load_strict_object(raw)
        if canonical_bytes(msg) != raw or set(msg) != {
            "version",
            "client",
            "request_id",
            "reservation_id",
            "run_id",
            "generation",
            "stage",
            "withhold_required",
            "digests",
        }:
            raise ValueError("bad start frame")
        return msg, fds
    except BaseException:
        for fd in fds:
            os.close(fd)
        raise


def _predicate_releases(predicate, candidate, remaining):
    if remaining <= 0:
        return False
    done = threading.Event()
    released = False

    def evaluate():
        nonlocal released
        try:
            released = predicate(candidate) is False
        except Exception:
            pass
        finally:
            done.set()

    threading.Thread(target=evaluate, daemon=True).start()
    return done.wait(remaining) and released


def detached(service, handoff, paths, cancelled, withhold):
    import subprocess

    from .seat_uid import trusted_module_argv

    h = handoff
    caller, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with caller, child:
        deadline = time.monotonic() + ANSWER_BOUND_S
        caller.settimeout(ANSWER_BOUND_S)
        proc = subprocess.Popen(
            trusted_module_argv(
                "phase_loop_runtime.launch_supervisor",
                str(child.fileno()),
                h.client,
                h.request_id,
                h.controller_sha256,
            ),
            env={
                "PATH": "/usr/bin:/bin",
                **{
                    k: os.environ[k]
                    for k in ("PHASE_LOOP_SANDBOX_STAGING_DIR", "PHASE_LOOP_SANDBOX_REFUSE_RAM")
                    if k in os.environ
                },
            },
            pass_fds=(child.fileno(),),
            start_new_session=True,
            cwd="/",
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child.close()
        try:
            _send_start(caller, h)
            import selectors

            with selectors.DefaultSelector() as selector:
                os.set_blocking(proc.stdin.fileno(), False)
                selector.register(proc.stdin, selectors.EVENT_WRITE)
                pending = memoryview(h.controller)
                while pending:
                    left = deadline - time.monotonic()
                    if left <= 0 or cancelled.is_set() or not selector.select(left):
                        raise TimeoutError("controller delivery")
                    pending = pending[os.write(proc.stdin.fileno(), pending[:65536]) :]
            proc.stdin.close()
            ack = _read_frame(caller, 4096, deadline)
            owner = dict(pid=proc.pid, start=process_start_identity(proc.pid))
            if not owner["start"] or ack != dict(version=1, generation=h.generation, owner=owner):
                raise ValueError("unexpected supervisor identity")
            envelope = read_blob(h.stage_fd, "envelope.blob", 1 << 20)
            if not _transfer(
                service.lifecycle, h, owner, paths, parse_v2(envelope).value["envelope_digest"]
            ):
                raise ValueError("handoff not acknowledged")
            caller.sendall(b"1")
            recipe = json.loads(read_blob(h.stage_fd, "recipe.blob", 1 << 20))
            end = (
                time.monotonic()
                + recipe["request"]["timeout_seconds"]
                + recipe["return_budget_s"]
                + 2 * ANSWER_BOUND_S
            )
            received = False
            while time.monotonic() < end:
                if service.lifecycle.launch_terminal(h.request_id):
                    break
                if cancelled.is_set():
                    service.lifecycle.cancel_launch_owner(
                        *h.ids, deadline=time.monotonic() + ANSWER_BOUND_S
                    )
                    break
                caller.settimeout(min(0.1, max(0.001, end - time.monotonic())))
                try:
                    flag = caller.recv(1)
                except TimeoutError:
                    continue
                if not flag:
                    break
                if flag != b"V" or not h.withhold_required or received:
                    raise ValueError("unexpected verdict request")
                received = True
                length = int.from_bytes(_read_exact(caller, 4, end), "big")
                from .launch_return import PATCH_CAP_MAX, RESULT_CAP

                ceiling = PATCH_CAP_MAX if recipe["request"]["result_kind"] == "patch" else RESULT_CAP
                if length > min(recipe["return_max_bytes"], ceiling):
                    raise ValueError("candidate oversize")
                candidate = _read_exact(caller, length, end)
                permitted = _predicate_releases(
                    withhold, candidate, min(end - time.monotonic(), recipe["return_budget_s"])
                )
                caller.sendall(bytes([0 if permitted else 1]))
        except (ValueError, OSError):
            pass
        finally:
            proc.stdin.close()
            caller.close()
            # EOF from the caller is never a cancel. Reap the direct child
            # asynchronously if the public call returns an uncertain observation.
            threading.Thread(target=proc.wait, daemon=True).start()


def main(argv: Sequence[str] | None = None) -> int:
    import re
    import selectors
    import sys

    from .launch_service import build_launch_service

    args = list(sys.argv[1:] if argv is None else argv)
    if (
        not sys.flags.isolated
        or len(args) != 4
        or not args[0].isdecimal()
        or not re.fullmatch("[0-9a-f]{64}", args[3])
    ):
        return 70
    _, client, req_id, controller_digest = args
    end = time.monotonic() + ANSWER_BOUND_S
    fds = []
    try:
        with socket.socket(fileno=int(args[0])) as conn:
            conn.settimeout(ANSWER_BOUND_S)
            msg, fds = _receive_start(conn, end)
            if msg["client"] != client or msg["request_id"] != req_id:
                return 70
            data = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
                while len(data) <= 1 << 20:
                    left = end - time.monotonic()
                    if left <= 0 or not selector.select(left):
                        data.clear()
                        break
                    chunk = os.read(sys.stdin.fileno(), min(65536, (1 << 20) + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
            h = SupervisorHandoff(
                **msg,
                inventory_fd=fds[0],
                stage_fd=fds[1],
                controller=bytes(data),
                controller_sha256=controller_digest,
            )
            life = PlacementLifecycle(client)
            service = build_launch_service(client, config=life.config(), lifecycle=life)
            _verify(h, life)
            owner = _owner()
            if not owner:
                return 10
            _send_frame(conn, dict(version=1, generation=h.generation, owner=owner))
            try:
                ready = _read_exact(conn, 1, end) == b"1"
            except (OSError, ValueError):
                ready = False
            record = life.launch_record(req_id)
            if (
                not record
                or record.get("owner") != owner
                or record.get("generation") != h.generation
                or record.get("phase") != "supervisor"
            ):
                return 10

            def verdict(candidate, deadline):
                if not ready:
                    return True
                try:
                    conn.settimeout(max(0, deadline - time.monotonic()))
                    conn.sendall(b"V" + len(candidate).to_bytes(4, "big") + candidate)
                    return _read_exact(conn, 1, deadline) != b"\x00"
                except (ValueError, OSError):
                    return True

            run_supervisor(
                h,
                effects=SupervisorEffects(
                    life,
                    service.capped_popen,
                    service.load_caps,
                    service.readiness_code,
                    time.monotonic,
                    verdict,
                ),
            )
            return 0
    except (OSError, ValueError):
        return 70
    finally:
        for fd in fds:
            os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
