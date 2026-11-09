"""Isolated local supervised worker commands; production launch remains gated."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import stat
import sys
from typing import Sequence

from .supervised_launch import AttemptBinding, Refused, _Refusal, discard_admission, prepare_launch_v2
from .supervised_dependency import preflight_supervised_route

STATUS_PAGE_SIZE = 50


def _production_codec(*, workspace, target, reference_roots):
    from . import supervised_launch_binding as binding
    return binding.load_v2_binding(binding.MANAGED_BINDING, workspace=workspace,
                                   target=target, reference_roots=reference_roots)


def read_envelope_file(path: Path, *, cap: int) -> tuple[bytes, int] | Refused:
    from .convergence.adapters.patch_return import _directory_fd
    fd = None
    try:
        parent = _directory_fd(path.parent)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022 or info.st_size > cap):
            return Refused("envelope_mode_unsafe")
        data = bytearray()
        while len(data) <= cap:
            chunk = os.read(fd, min(65536, cap + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > cap:
            return Refused("envelope_too_large")
        return bytes(data), info.st_mode
    except (OSError, ValueError):
        return Refused("envelope_file_unsafe")
    finally:
        if fd is not None:
            os.close(fd)


def open_result_file(path: Path, *, excluded: tuple[Path, ...]) -> int | Refused:
    from .convergence.adapters.patch_return import _directory_fd
    try:
        if not path.is_absolute() or ".." in path.parts:
            return Refused("result_path_unsafe")
        resolved = path.resolve()
        if any(resolved == root.resolve() or root.resolve() in resolved.parents for root in excluded):
            return Refused("result_path_unsafe")
        parent = _directory_fd(path.parent)
        try:
            info = os.fstat(parent)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                return Refused("result_path_unsafe")
            return os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        finally:
            os.close(parent)
    except (OSError, ValueError):
        return Refused("result_path_unsafe")


def main(argv: Sequence[str] | None = None, *, state_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="supervised-worker")
    verbs = parser.add_subparsers(dest="verb", required=True)
    launch = verbs.add_parser("launch")
    launch.add_argument("--envelope", required=True)
    launch.add_argument("--result", required=True)
    for name in ("status", "cancel"):
        command = verbs.add_parser(name)
        target = command.add_mutually_exclusive_group(required=True)
        target.add_argument("--run")
        target.add_argument("--attempt")
        if name == "status":
            command.add_argument("--page", action="store_true")
            command.add_argument("--cursor")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code
    def refuse(reason):
        print(reason)
        return 10
    preflight = preflight_supervised_route("supervised-" + args.verb)
    if isinstance(preflight, Refused):
        return refuse(preflight.reason)
    if not sys.flags.isolated:
        return refuse("isolation_required")
    if args.verb == "launch":
        result = _launch_v2(Path(args.envelope), Path(args.result), state_root=state_root)
        return refuse(result.reason) if isinstance(result, Refused) else result
    from . import run_status as journal, run_status_projection as projection
    from .convergence.adapters.patch_return import (default_state_root, evidence_resolver,
        cancel_attempt, PRODUCTION_LAUNCHER_COMMANDS, CANCEL_WAIT_SECONDS)
    state_root = state_root if state_root is not None else default_state_root()
    if args.verb == "cancel":
        print(cancel_attempt(state_root=state_root, run_id=args.run, attempt_id=args.attempt,
                            wait_seconds=CANCEL_WAIT_SECONDS, launcher_commands=PRODUCTION_LAUNCHER_COMMANDS))
        return 0
    if args.cursor and not args.page:
        return 2
    root = journal.open_journal_root(state_root / "journal", create=False)
    if isinstance(root, journal.JournalRefused):
        return refuse(root.code)
    attempt = args.attempt
    if args.run:
        ids = journal.resolve_run(root, args.run)
        if isinstance(ids, journal.JournalRefused) or not ids:
            return refuse("unknown_attempt")
        attempt = ids[-1]
    status = projection.attempt_status(root, attempt)
    page, cursor, diagnostics = None, None, None
    if args.page:
        read = journal.read_attempt(root, attempt)
        if read.identity is None:
            return refuse("unknown_attempt")
        response = projection.read_page(root, json.dumps(dict(assignment_digest=read.identity.assignment_digest,
            page_size=STATUS_PAGE_SIZE, cursor=args.cursor)).encode(), evidence=evidence_resolver(state_root))
        if isinstance(response, journal.JournalRefused):
            return refuse(response.code)
        page, cursor, diagnostics = response.page, response.next_cursor, response.diagnostics
    print(json.dumps(dict(attempt=asdict(status), page=page, next_cursor=cursor, page_diagnostics=diagnostics)))
    return 0



@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    raw_bytes: bytes = field(repr=False)
    document: object = field(repr=False)
    attempt: AttemptBinding
    exclusions: tuple[Path, ...] = field(repr=False)
    locations: tuple[tuple[int, int], ...] = field(repr=False)


def read_controller_snapshot(controller_root: Path, envelope_sha256: str, *, cap=1048576):
    """Hold a complete controller snapshot and validate exclusions without a reread."""
    from .supervised_launch_binding import _v2_data
    import re
    fd = None
    try:
        if (not controller_root.is_absolute() or ".." in controller_root.parts
                or str(controller_root) != os.path.normpath(str(controller_root))
                or re.fullmatch(r"[0-9a-f]{64}", envelope_sha256) is None):
            return Refused("binding_invalid")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        locations = []
        info = os.fstat(fd)
        locations.append((info.st_dev, info.st_ino))
        for part in controller_root.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022:
                return Refused("binding_invalid")
            locations.append((info.st_dev, info.st_ino))
        child = os.open(envelope_sha256 + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        os.close(fd)
        fd = child
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
                or info.st_nlink != 1 or info.st_size > cap):
            return Refused("binding_invalid")
        locations.append((info.st_dev, info.st_ino))
        data = bytearray()
        while len(data) <= cap:
            chunk = os.read(fd, min(65536, cap + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        if len(data) > cap:
            return Refused("binding_invalid")
        raw = bytes(data)
        document = _v2_data(raw)
        if set(document) != {"h", "attempt", "context", "slots"} or document["h"] != envelope_sha256:
            return Refused("binding_invalid")
        authority = document["context"]
        fields = {"expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref", "timeout_max_seconds",
                  "qualified_routes", "policy_epoch", "revoked_record_ids", "caller_context_suitability"}
        if set(authority) != fields or set(document["attempt"]) != {"assignment_digest", "run_id", "attempt_id"}:
            return Refused("binding_invalid")
        maximum = authority["timeout_max_seconds"]
        if (type(maximum) not in (int, float) or maximum != int(maximum) or not 0 < maximum <= 3600
                or not isinstance(authority["qualified_routes"], tuple)
                or not isinstance(authority["revoked_record_ids"], tuple)
                or not all(type(value) is str and value for value in authority["revoked_record_ids"])
                or type(authority["policy_epoch"]) is not str or not authority["policy_epoch"]
                or (authority["caller_context_suitability"] is not None
                    and not hasattr(authority["caller_context_suitability"], "items"))):
            return Refused("binding_invalid")
        for name in ("expected_assignment_digest", "expected_snapshot_ref", "expected_crosswalk_ref"):
            if type(authority[name]) is not str or re.fullmatch(r"[0-9a-f]{64}", authority[name]) is None:
                return Refused("binding_invalid")
        attempt = AttemptBinding(**document["attempt"])
        if attempt.assignment_digest != authority["expected_assignment_digest"]:
            return Refused("binding_invalid")
        for value in (attempt.run_id, attempt.attempt_id):
            if type(value) is not str or not value or len(value) > 200 or any(ord(c) < 32 or c in "/\\" for c in value):
                return Refused("binding_invalid")
        slots = document["slots"]
        from .supervised_launch import _path
        exclusions = (_path(slots["workspace"]), _path(slots["target"]), *(_path(root) for root in slots["reference_roots"]))
        if not isinstance(slots["reference_roots"], tuple):
            return Refused("binding_invalid")
        for root in exclusions:
            root_info = root.lstat()
            if not stat.S_ISDIR(root_info.st_mode) or (root_info.st_dev, root_info.st_ino) in locations:
                return Refused("binding_invalid")
        return ControllerSnapshot(raw, document, attempt, exclusions, tuple(locations))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, _Refusal):
        return Refused("binding_invalid")
    finally:
        if fd is not None:
            os.close(fd)


def _launch_v2(envelope_path: Path, result_path: Path, *, state_root=None):
    from . import supervised_launch_binding as binding
    from .supervised_capture_v2 import CapturedLaunch, capture_launch_v2
    from hashlib import sha256
    held = read_envelope_file(envelope_path, cap=1048576)
    if isinstance(held, Refused):
        return held
    envelope_bytes, _mode = held
    locator = binding.read_binding_locator(binding.MANAGED_BINDING)
    if isinstance(locator, Refused):
        return locator
    controller = read_controller_snapshot(locator.controller_root, sha256(envelope_bytes).hexdigest())
    if isinstance(controller, Refused):
        return controller
    workspace, target, *references = controller.exclusions
    passive = _production_codec(workspace=workspace, target=target, reference_roots=tuple(references))
    if isinstance(passive, Refused):
        return passive
    agreed = binding.reconcile_v2_binding(locator, passive, controller=controller.document, attempt=controller.attempt)
    if isinstance(agreed, Refused):
        return agreed
    active = binding.activate_v2_binding(agreed)
    if isinstance(active, Refused):
        return active
    # Only the retained envelope bytes and reconciled hand-off reach the codec.
    try:
        decoded = active.codec.decode_v2(envelope_bytes, bundle=active.bundle)
    except ValueError:
        return Refused("envelope_schema_invalid")
    diagnostics = active.codec.precheck_v2_admission(decoded, context=active.context, spec=active.spec, attempt=controller.attempt)
    if diagnostics:
        return Refused(diagnostics[0], diagnostics=diagnostics)
    prepared = None
    descriptor = None
    capture = None
    try:
        capture = capture_launch_v2(spec=active.spec, context=active.context, attempt=controller.attempt)
        if isinstance(capture, Refused):
            return capture
        prepared = prepare_launch_v2(envelope_bytes, binding=active, capture=capture, attempt=controller.attempt)
        if isinstance(prepared, Refused):
            return prepared
        descriptor = open_result_file(result_path, excluded=controller.exclusions)
        if isinstance(descriptor, Refused):
            discard_admission(prepared)
            return descriptor
        from .convergence.adapters.patch_return import default_state_root, run_patch_return
        from .run_status_projection import v2_status_mapping
        config = dict(active.snapshots)[active.spec.config_path]
        result = run_patch_return(prepared, config_bytes=config, state_root=state_root or default_state_root())
        mapped = v2_status_mapping(result)
        record = dict(runtime_state=mapped.runtime_state, journal_acknowledged=mapped.journal_acknowledged,
                      refusal=mapped.refusal, public_status=None if mapped.public_status_bytes is None else json.loads(mapped.public_status_bytes))
        raw = json.dumps(record, separators=(",", ":"), allow_nan=False).encode()
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
        return 0 if result.state == "finished" else 10
    except BaseException:
        if prepared is not None:
            discard_admission(prepared)
        return Refused("launch_invalid")
    finally:
        if type(descriptor) is int:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if type(capture) is CapturedLaunch:
            capture.close()


if __name__ == "__main__":
    raise SystemExit(main())
