"""Process-free, fixture-frozen admission seam. Not a public wire codec.

All callers supply an explicitly trusted codec, validator and operator config.
This module never launches children, probes tools or writes evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from .executable_dependency import ExecutableDependencyError
from .executable_dependency_startup import refuse_unwired_dependency_route


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Refused:
    reason: str


class _Refusal(Exception):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise _Refusal(reason)


def _json(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise _Refusal("nonfinite")

    result = json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)
    _require(type(result) is dict, "object_required")
    return result


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _parts(path: Path) -> tuple[str, ...]:
    _require(path.is_absolute() and ".." not in path.parts, "absolute_path_required")
    return path.parts[1:]


def _beneath(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _read_file(path: Path, *, cap: int, trusted: bool = False,
               excluded: tuple[Path, ...] = (), nofollow: bool = True,
               regular: bool = True, bounded: bool = True, operator_owned: bool = True) -> bytes:
    """Walk from / with held dir fds; never resolve away a symlink first."""
    parts = _parts(path)
    _require(bool(parts), "file_required")
    _require(not any(_beneath(path, root) for root in excluded), "untrusted_location")
    fd = os.open("/", os.O_PATH | os.O_DIRECTORY)
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NONBLOCK
            if nofollow:
                flags |= os.O_NOFOLLOW
            if index < len(parts) - 1:
                flags = os.O_PATH | os.O_DIRECTORY | (os.O_NOFOLLOW if nofollow else 0)
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if trusted:
                _require(info.st_uid in ({os.getuid()} if operator_owned else {0, os.getuid()}) if index == len(parts) - 1 else
                         info.st_uid in {0, os.getuid()}, "trusted_uid")  # MUTATION: trusted_uid
                _require(not info.st_mode & 0o022, "trusted_mode")  # MUTATION: trusted_mode
        if regular:
            _require(stat.S_ISREG(info.st_mode), "reference_regular")  # MUTATION: reference_regular
        data = os.read(fd, cap + 1)
        if bounded:
            _require(len(data) <= cap, "file_cap")
        return data
    finally:
        os.close(fd)


def trusted_bytes(path: Path, *, excluded: tuple[Path, ...] = ()) -> bytes:
    return _read_file(path, cap=1024 * 1024, trusted=True, excluded=excluded)


def _executable_bytes(path: Path, *, excluded: tuple[Path, ...] = ()) -> bytes:
    return _read_file(path, cap=1024 * 1024, trusted=True, excluded=excluded, operator_owned=False)


@dataclass(frozen=True)
class LaunchConfig:
    """Explicit paths to operator-owned config and closed argv template."""
    config_path: Path
    template_path: Path
    qualification_path: Path | None = None


@dataclass(frozen=True)
class ExecutableIdentity:
    path: str
    digest: str


@dataclass(frozen=True)
class LaunchInputs:
    instruction: bytes
    instruction_digest: str
    baseline: bytes
    baseline_digest: str
    argv: tuple[str, ...]
    executable: ExecutableIdentity
    wrappers: tuple[ExecutableIdentity, ...]
    workspace: str
    target: str
    workspace_class: str
    root_device: int
    root_inode: int
    tier: str
    constraints: tuple[str, ...]
    timeout: int
    config_digest: str
    template_digest: str
    qualification_digest: str


@dataclass(frozen=True)
class EnvelopeCapture:
    raw_bytes: bytes
    raw_digest: str
    envelope: Mapping


@dataclass(frozen=True)
class EnvelopeView:
    envelope: Mapping
    envelope_digest: str
    raw_digest: str
    launch_digest: str
    inputs: LaunchInputs


@dataclass(frozen=True)
class Admit:
    launch_digest: str
    attempt_id: str


class Validator(Protocol):
    def __call__(self, view: EnvelopeView) -> Admit | Refused: ...


@dataclass(frozen=True, eq=False)
class PreparedLaunch:
    view: EnvelopeView
    admit: Admit
    _token: object = field(default_factory=object, repr=False)


_TOKENS: dict[object, PreparedLaunch] = {}
_LOCK = threading.Lock()


def _identity(name: str, search: tuple[str, ...], excluded: tuple[Path, ...]) -> ExecutableIdentity:
    if Path(name).is_absolute():
        candidates = [Path(name)]
    else:
        _require("/" not in name and bool(name), "executable_path")
        _require(all(entry and Path(entry).is_absolute() for entry in search), "unsafe_path")
        candidates = [Path(entry) / name for entry in search]
    for path in candidates:
        if not path.exists():
            continue
        data = _executable_bytes(path, excluded=excluded)
        _require(bool(path.stat().st_mode & 0o111), "not_executable")
        return ExecutableIdentity(str(path), sha256(data))
    raise _Refusal("executable_missing")


def classify_workspace(workspace: Path, target: Path, tier: str) -> tuple[str, int, int]:
    _parts(workspace)
    _parts(target)
    _require(not workspace.is_symlink() and workspace.is_dir(), "workspace_invalid")
    # Check every ancestor without resolving away links.
    _require(all(not part.is_symlink() for part in (workspace, *workspace.parents)), "workspace_symlink")
    _require(target.is_dir() and all(not part.is_symlink() for part in (target, *target.parents)),
             "target_invalid")
    info = workspace.stat()
    target_info = target.stat()
    if (info.st_dev, info.st_ino) == (target_info.st_dev, target_info.st_ino):
        kind = "in_place"
    elif (workspace / ".git").is_file():
        kind = "worktree"
    elif _beneath(workspace, target) or _beneath(target, workspace):
        kind = "unknown"
    else:
        kind = "separate"
    if tier == "provider_readonly_patch_return_audit":  # MUTATION: workspace
        _require(kind == "separate", "workspace_tier")
        def unreadable(error):
            raise _Refusal("workspace_uninspectable") from error

        # Compare physical inode identities too: path separation alone cannot
        # establish that object/ref directories are not shared through aliases.
        protected = {(target_info.st_dev, target_info.st_ino)}
        for parent, dirs, files in os.walk(target, followlinks=False, onerror=unreadable):
            for name in dirs + files:
                item = (Path(parent) / name).lstat()
                protected.add((item.st_dev, item.st_ino))
        for parent, dirs, files in os.walk(workspace, followlinks=False, onerror=unreadable):
            for name in dirs + files:
                path = Path(parent) / name
                item = path.lstat()
                _require(not stat.S_ISLNK(item.st_mode), "workspace_storage")
                _require(stat.S_ISDIR(item.st_mode) or
                         (stat.S_ISREG(item.st_mode) and item.st_nlink == 1), "workspace_storage")
                _require(name not in {"alternates", "commondir"}, "workspace_storage")
                _require((item.st_dev, item.st_ino) not in protected, "workspace_shared")
    _require(kind != "unknown", "workspace_unknown")
    return kind, info.st_dev, info.st_ino


def _reference(spec: dict, roots: tuple[Path, ...], cap: int) -> bytes:
    _require(set(spec) == {"root", "path", "digest"}, "reference_fields")
    root, relative = Path(spec["root"]), Path(spec["path"])
    _require(root in roots and not relative.is_absolute() and ".." not in relative.parts,
             "reference_root")  # MUTATION: reference_root
    data = _read_file(root / relative, cap=cap,
                      nofollow=True, regular=True, bounded=False)  # MUTATION: reference_nofollow
    _require(len(data) <= cap, "reference_cap")  # MUTATION: reference_cap
    _require(sha256(data) == spec["digest"], "reference_digest")
    return data


def _launch_digest(raw_digest: str, inputs: LaunchInputs, attempt: str) -> str:
    payload = asdict(inputs)
    # Bytes are represented by their bound hashes in the canonical input encoding.
    payload.pop("instruction")
    payload.pop("baseline")
    chunks = (raw_digest.encode(), _canonical(payload), attempt.encode())
    return sha256(b"agent-harness:supervised-launch:v1\0" +
                  b"".join(len(chunk).to_bytes(8, "big") + chunk for chunk in chunks))


def prepare_launch(envelope_bytes: bytes, *, validator: Validator,
                   decoder: Callable[[EnvelopeCapture], tuple[Mapping, str]],
                   config: LaunchConfig) -> PreparedLaunch | Refused:
    """Capture, bind and admit one attempt, without any child or evidence effects."""
    try:
        refuse_unwired_dependency_route("supervised-launch")
    except ExecutableDependencyError as exc:
        return Refused(exc.code)
    try:
        _require(type(envelope_bytes) is bytes, "envelope_bytes")
        _require(callable(validator) and callable(decoder), "binding_unavailable")
        configuration_bytes = trusted_bytes(config.config_path)
        settings = _json(configuration_bytes)
        limits = [settings[key] for key in ("envelope_cap", "reference_cap", "aggregate_cap")]
        _require(all(type(value) is int and value > 0 for value in limits), "invalid_limits")
        _require(len(envelope_bytes) <= settings["envelope_cap"], "envelope_cap")  # MUTATION: envelope_cap
        raw_digest = sha256(envelope_bytes)
        capture = EnvelopeCapture(envelope_bytes, raw_digest, _freeze(_json(envelope_bytes)))
        decoded, envelope_digest = decoder(capture)
        _require(isinstance(decoded, Mapping) and isinstance(envelope_digest, str) and bool(envelope_digest), "codec_invalid")
        envelope = _freeze(decoded)
        required = {"schema", "version", "assignment_digest", "run_id", "attempt_id",
                    "target_unit_ids", "readonly_neighbor_unit_ids", "snapshot_reference",
                    "obligation_references", "dependency_declaration", "caller_context",
                    "redaction_posture", "launch_inputs"}
        _require(set(decoded) == required, "envelope_fields")
        _require(not decoded["dependency_declaration"], "dependency_route_unwired")
        _require(type(decoded["attempt_id"]) is str and bool(decoded["attempt_id"]), "attempt_invalid")
        launch = decoded["launch_inputs"]
        _require(set(launch) == {"instruction", "baseline", "executable", "wrappers", "workspace",
                                 "target", "tier", "constraints", "timeout"}, "launch_fields")
        tier = launch["tier"]
        _require(tier in {"provider_readonly_patch_return_audit", "post_write_audit_only"}, "tier_unsupported")
        _require(launch["constraints"] in ([], ()), "constraints_unsupported")
        _require(type(launch["timeout"]) is int and 0 < launch["timeout"] <= settings["timeout_max"], "timeout_invalid")
        workspace, target = Path(launch["workspace"]), Path(launch["target"])
        roots = tuple(Path(root) for root in settings["reference_roots"])
        excluded = (workspace, target, *roots)
        # Re-read under outside-workspace restrictions before using trusted inputs.
        trusted_bytes(config.config_path, excluded=excluded)
        template_bytes = trusted_bytes(config.template_path, excluded=excluded)
        template = json.loads(template_bytes)
        _require(type(template) is list and bool(template) and all(type(x) is str for x in template), "template_invalid")
        _require(template.count("{executable}") == 1 and template[0] == "{executable}", "template_invalid")
        _require(all("{" not in item and "}" not in item for item in template[1:]), "template_invalid")
        executable = _identity(launch["executable"], tuple(settings["executable_path"]), excluded)
        wrappers = tuple(_identity(name, tuple(settings["executable_path"]), excluded) for name in launch["wrappers"])
        kind, device, inode = classify_workspace(workspace, target, tier)
        instruction = _reference(launch["instruction"], roots, settings["reference_cap"])
        baseline = _reference(launch["baseline"], roots, settings["reference_cap"])
        _require(len(instruction) + len(baseline) <= settings["aggregate_cap"], "aggregate_cap")  # MUTATION: aggregate_cap
        qualification_digest = ""
        if config.qualification_path is not None:
            qualification_bytes = trusted_bytes(config.qualification_path, excluded=excluded)
            qualification_digest = sha256(qualification_bytes)
        if tier == "provider_readonly_patch_return_audit":
            _require(bool(qualification_digest), "qualification_missing")
            qualification = _json(qualification_bytes)
            _require(qualification == {"executable": asdict(executable), "wrappers": [asdict(x) for x in wrappers],
                                      "template_digest": sha256(template_bytes), "version": settings["qualified_version"],
                                      "write_attempt_refused": True, "proposal_return": True, "audit": True},
                     "qualification_invalid")  # MUTATION: qualification
        inputs = LaunchInputs(instruction, sha256(instruction), baseline, sha256(baseline),
                              tuple([x.path for x in wrappers] + [executable.path] + template[1:]),
                              executable, wrappers, str(workspace), str(target), kind, device, inode,
                              tier, (), launch["timeout"], sha256(configuration_bytes),
                              sha256(template_bytes), qualification_digest)
        digest = _launch_digest(raw_digest, inputs, decoded["attempt_id"])
        view = EnvelopeView(envelope, envelope_digest, raw_digest, digest, inputs)
        verdict = validator(view)
        if type(verdict) is Refused:
            return verdict
        _require(type(verdict) is Admit, "admit_required")  # MUTATION: typed_admit
        _require(verdict.launch_digest == digest and verdict.attempt_id == decoded["attempt_id"],
                 "admit_binding")  # MUTATION: admit_binding
        prepared = PreparedLaunch(view, verdict)
        with _LOCK:
            _TOKENS[prepared._token] = prepared
        return prepared
    except Exception as exc:
        return Refused(str(exc) if isinstance(exc, _Refusal) else "launch_invalid")


def consume_admission(prepared: PreparedLaunch) -> LaunchInputs | Refused:
    """Atomically spend a process-local token; changed identities fail closed."""
    try:
        _require(type(prepared) is PreparedLaunch, "token_invalid")
        with _LOCK:
            registered = _TOKENS.pop(prepared._token, None)  # MUTATION: token
        _require(registered is prepared, "token_spent")
        view, inputs = prepared.view, prepared.view.inputs
        _require(prepared.admit == Admit(_launch_digest(view.raw_digest, inputs, view.envelope["attempt_id"]),
                                          view.envelope["attempt_id"]), "consume_binding")
        kind, device, inode = classify_workspace(Path(inputs.workspace), Path(inputs.target), inputs.tier)
        _require(kind == inputs.workspace_class, "workspace_changed")  # MUTATION: consume_class
        _require(device == inputs.root_device, "device_changed")  # MUTATION: consume_device
        _require(inode == inputs.root_inode, "inode_changed")  # MUTATION: consume_inode
        _require(sha256(_executable_bytes(Path(inputs.executable.path))) == inputs.executable.digest,
                 "executable_changed")  # MUTATION: consume_executable
        for wrapper in inputs.wrappers:
            _require(sha256(_executable_bytes(Path(wrapper.path))) == wrapper.digest,
                     "wrapper_changed")  # MUTATION: consume_wrapper
        return inputs
    except Exception as exc:
        return Refused(str(exc) if isinstance(exc, _Refusal) else "consume_invalid")
