"""Process-free, fixture-frozen admission seam. Not a public wire codec.

All callers supply an explicitly trusted codec, validator and operator config.
This module never launches children, probes tools or writes evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from copy import deepcopy
import hashlib
import json
import math
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

    def finite_float(value):
        parsed = float(value)
        _require(math.isfinite(parsed), "nonfinite")
        return parsed

    result = json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite, parse_float=finite_float)
    _require(type(result) is dict, "object_required")
    return result


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _same_json(left, right) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        return left.keys() == right.keys() and all(_same_json(left[key], right[key]) for key in right)
    if isinstance(left, tuple):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right))
    return left == right


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _parts(path: Path) -> tuple[str, ...]:
    _require(path.is_absolute() and ".." not in path.parts, "absolute_path_required")
    _require(str(path) == os.path.normpath(str(path)) and path.anchor == "/", "canonical_path_required")
    return path.parts[1:]


def _path(value: str) -> Path:
    _require(type(value) is str and value == os.path.normpath(value), "canonical_path_required")
    path = Path(value)
    _parts(path)
    return path


def _beneath(path: Path, root: Path) -> bool:
    identity = _inode(root.stat())
    return any(_inode(parent.stat()) == identity for parent in (path, *path.parents))


def _inode(info) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _read_file(path: Path, *, cap: int, trusted: bool = False,
               excluded: tuple[Path, ...] = (), nofollow: bool = True,
               regular: bool = True, bounded: bool = True, operator_owned: bool = True,
               single_link: bool = False) -> bytes:
    """Walk from / with held dir fds; never resolve away a symlink first."""
    parts = _parts(path)
    _require(bool(parts), "file_required")
    for root in excluded:
        _parts(root)
    excluded_info = [root.lstat() for root in excluded]
    _require(all(stat.S_ISDIR(info.st_mode) for info in excluded_info), "excluded_root_invalid")
    excluded_ids = {_inode(info) for info in excluded_info}
    fd = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        _require(_inode(os.fstat(fd)) not in excluded_ids, "untrusted_location")
        for index, part in enumerate(parts):
            flags = os.O_PATH | os.O_CLOEXEC
            if nofollow:
                flags |= os.O_NOFOLLOW
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            _require(not stat.S_ISLNK(info.st_mode), "path_symlink")
            _require(_inode(info) not in excluded_ids, "untrusted_location")
            if trusted:
                _require(info.st_uid in ({os.getuid()} if operator_owned else {0, os.getuid()}) if index == len(parts) - 1 else
                         info.st_uid in {0, os.getuid()}, "trusted_uid")  # MUTATION: trusted_uid
                _require(not info.st_mode & 0o022, "trusted_mode")  # MUTATION: trusted_mode
        if regular:
            _require(stat.S_ISREG(info.st_mode), "reference_regular")  # MUTATION: reference_regular
        if single_link:
            _require(info.st_nlink == 1, "reference_links")
        reader = os.open(f"/proc/self/fd/{fd}", os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC)
        try:
            _require(_inode(os.fstat(reader)) == _inode(info), "file_changed")
            chunks, size = [], 0
            while size <= cap:
                chunk = os.read(reader, min(65536, cap + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            data = b"".join(chunks)
        finally:
            os.close(reader)
        if bounded:
            _require(len(data) <= cap, "file_cap")
        return data
    finally:
        os.close(fd)


def trusted_bytes(path: Path, *, excluded: tuple[Path, ...] = ()) -> bytes:
    return _read_file(path, cap=1024 * 1024, trusted=True, excluded=excluded, single_link=True)


def _executable_bytes(path: Path, *, excluded: tuple[Path, ...] = ()) -> bytes:
    return _read_file(path, cap=1024 * 1024, trusted=True, excluded=excluded, operator_owned=False, single_link=True)


@dataclass(frozen=True, slots=True)
class AttemptBinding:
    assignment_digest: str
    run_id: str
    attempt_id: str


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
    spawn_capability: object = field(default=None, repr=False, compare=False)


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
    attempt_binding: AttemptBinding | None = None
    _capture: object = field(default=None, repr=False, compare=False)
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Admission:
    owner_id: int
    digest: str
    attempt: str
    raw_digest: str
    inputs: LaunchInputs
    attempt_key: tuple[str, str, str]


_TOKENS: dict[object, _Admission] = {}
_CONSUMED: set[tuple[str, str, str]] = set()
_LOCK = threading.Lock()


def _identity(name: str, search: tuple[str, ...], excluded: tuple[Path, ...]) -> ExecutableIdentity:
    if Path(name).is_absolute():
        candidates = [_path(name)]
    else:
        _require("/" not in name and bool(name), "executable_path")
        _require(all(entry and Path(entry).is_absolute() for entry in search), "unsafe_path")
        candidates = [_path(entry) / name for entry in search]
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
        _require(_inode(info) not in protected, "workspace_root_shared")
        for parent, dirs, files in os.walk(workspace, followlinks=False, onerror=unreadable):
            _require(Path(parent) == workspace / ".git" or
                     not ("HEAD" in files and {"objects", "refs"} <= set(dirs)), "workspace_gitdir")
            for name in dirs + files:
                path = Path(parent) / name
                item = path.lstat()
                _require(not stat.S_ISLNK(item.st_mode), "workspace_storage")
                _require(stat.S_ISDIR(item.st_mode) or
                         (stat.S_ISREG(item.st_mode) and item.st_nlink == 1), "workspace_storage")
                _require(name != ".git" or (Path(parent) == workspace and stat.S_ISDIR(item.st_mode)),
                         "workspace_gitfile")
                _require(name not in {"alternates", "http-alternates", "commondir"}, "workspace_storage")
                _require((item.st_dev, item.st_ino) not in protected, "workspace_shared")
                if Path(parent) == workspace / ".git" and name in {"config", "config.worktree"}:
                    _check_git_config(_read_file(path, cap=1024 * 1024))
    _require(kind != "unknown", "workspace_unknown")
    return kind, info.st_dev, info.st_ino


def _check_git_config(data: bytes) -> None:
    # Accept only the deliberately small clean-clone grammar, as data.
    import re
    keys = {"core": {"repositoryformatversion", "filemode", "bare", "logallrefupdates"},
            "remote": {"url", "fetch"}, "branch": {"remote", "merge"},
            "extensions": {"objectformat"}}
    section = ""
    for line in data.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        _require("\\" not in line, "workspace_gitconfig")
        if line.startswith("["):
            # Standard remote/branch subsections are distinct from quoted
            # section names. Escapes and quoted values are outside this grammar.
            match = re.fullmatch(r'\[([A-Za-z]+)(?: "([^"\\]+)")?\]', line)
            _require(match is not None, "workspace_gitconfig")
            section = match[1].lower()
            _require(section in keys and (bool(match[2]) == (section in {"remote", "branch"})),
                     "workspace_gitconfig")
        else:
            match = re.fullmatch(r'([A-Za-z]+)\s*=\s*([^"\\]*)', line)
            _require(match is not None and match[1].lower() in keys.get(section, set()),
                     "workspace_gitconfig")


def _reference(spec: dict, roots: tuple[Path, ...], cap: int) -> bytes:
    _require(set(spec) == {"root", "path", "digest"}, "reference_fields")
    root, relative = _path(spec["root"]), Path(spec["path"])
    _require(root in roots and not relative.is_absolute() and ".." not in relative.parts,
             "reference_root")  # MUTATION: reference_root
    data = _read_file(root / relative, cap=cap,
                      nofollow=True, regular=True, bounded=False, single_link=True)  # MUTATION: reference_nofollow
    _require(len(data) <= cap, "reference_cap")  # MUTATION: reference_cap
    _require(sha256(data) == spec["digest"], "reference_digest")
    return data


def _launch_digest(raw_digest: str, inputs: LaunchInputs, attempt: str) -> str:
    payload = asdict(inputs)
    # Bytes are represented by their bound hashes in the canonical input encoding.
    payload.pop("instruction")
    payload.pop("baseline")
    payload.pop("spawn_capability", None)
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
        try:
            decoded, envelope_digest = decoder(capture)
        except BaseException:
            return Refused("codec_exception")
        _require(isinstance(decoded, Mapping) and type(envelope_digest) is str and bool(envelope_digest), "codec_invalid")
        envelope = _freeze(decoded)
        _require(_same_json(envelope, capture.envelope), "codec_changed_envelope")
        decoded = envelope
        required = {"schema", "version", "assignment_digest", "run_id", "attempt_id",
                    "target_unit_ids", "readonly_neighbor_unit_ids", "snapshot_reference",
                    "obligation_references", "dependency_declaration", "caller_context",
                    "redaction_posture", "launch_inputs"}
        _require(set(decoded) == required, "envelope_fields")
        _require(not decoded["dependency_declaration"], "dependency_route_unwired")
        _require(type(decoded["attempt_id"]) is str and bool(decoded["attempt_id"]), "attempt_invalid")
        _require(all(type(decoded[key]) is str and bool(decoded[key]) for key in ("assignment_digest", "run_id")),
                 "attempt_invalid")
        launch = decoded["launch_inputs"]
        _require(set(launch) == {"instruction", "baseline", "executable", "wrappers", "workspace",
                                 "target", "tier", "constraints", "timeout"}, "launch_fields")
        tier = launch["tier"]
        _require(tier in {"provider_readonly_patch_return_audit", "post_write_audit_only"}, "tier_unsupported")
        _require(launch["constraints"] in ([], ()), "constraints_unsupported")
        _require(type(launch["timeout"]) is int and 0 < launch["timeout"] <= settings["timeout_max"], "timeout_invalid")
        workspace, target = _path(launch["workspace"]), _path(launch["target"])
        roots = tuple(_path(root) for root in settings["reference_roots"])
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
        try:
            verdict = validator(view)
        except BaseException:
            return Refused("validator_exception")
        if type(verdict) is Refused:
            return verdict
        _require(type(verdict) is Admit, "admit_required")  # MUTATION: typed_admit
        _require(type(verdict.launch_digest) is str and type(verdict.attempt_id) is str, "admit_fields")
        _require(verdict.launch_digest == digest and verdict.attempt_id == decoded["attempt_id"],
                 "admit_binding")  # MUTATION: admit_binding
        prepared = PreparedLaunch(view, verdict)
        with _LOCK:
            _TOKENS[prepared._token] = _Admission(id(prepared), digest, decoded["attempt_id"], raw_digest,
                                                 deepcopy(inputs), tuple(decoded[key] for key in
                                                 ("assignment_digest", "run_id", "attempt_id")))
        return prepared
    except BaseException as exc:
        return Refused(str(exc) if isinstance(exc, _Refusal) else "launch_invalid")


def consume_admission(prepared: PreparedLaunch) -> LaunchInputs | Refused:
    """Atomically spend a process-local token; changed identities fail closed."""
    try:
        _require(type(prepared) is PreparedLaunch, "token_invalid")
        with _LOCK:
            registered = _TOKENS.pop(prepared._token, None)  # MUTATION: token
        _require(registered is not None and registered.owner_id == id(prepared), "token_spent")
        view, inputs = prepared.view, prepared.view.inputs
        _require(inputs == registered.inputs and view.raw_digest == registered.raw_digest and
                 prepared.admit == Admit(registered.digest, registered.attempt), "consume_binding")
        if prepared.attempt_binding is not None:
            from .supervised_capture_v2 import recheck_launch_v2
            capture = prepared._capture
            _require(prepared.attempt_binding == capture.attempt and view.launch_digest == capture.local_digest,
                     "consume_binding")
            refusal = recheck_launch_v2(capture, context=capture.context)
            if isinstance(refusal, Refused):
                return refusal
            with _LOCK:
                _require(registered.attempt_key not in _CONSUMED, "attempt_replayed")
                _CONSUMED.add(registered.attempt_key)
            return registered.inputs
        else:
            _require(prepared.admit == Admit(_launch_digest(view.raw_digest, inputs, view.envelope["attempt_id"]),
                                              view.envelope["attempt_id"]), "consume_binding")
        with _LOCK:
            _require(registered.attempt_key not in _CONSUMED, "attempt_replayed")
            _CONSUMED.add(registered.attempt_key)
        kind, device, inode = classify_workspace(Path(inputs.workspace), Path(inputs.target), inputs.tier)
        _require(kind == inputs.workspace_class, "workspace_changed")  # MUTATION: consume_class
        _require(device == inputs.root_device, "device_changed")  # MUTATION: consume_device
        _require(inode == inputs.root_inode, "inode_changed")  # MUTATION: consume_inode
        _require(sha256(_executable_bytes(Path(inputs.executable.path))) == inputs.executable.digest,
                 "executable_changed")  # MUTATION: consume_executable
        for wrapper in inputs.wrappers:
            _require(sha256(_executable_bytes(Path(wrapper.path))) == wrapper.digest,
                     "wrapper_changed")  # MUTATION: consume_wrapper
        return registered.inputs
    except BaseException as exc:
        if type(prepared) is PreparedLaunch and prepared._capture is not None:
            prepared._capture.close()
        return Refused(str(exc) if isinstance(exc, _Refusal) else "consume_invalid")


class _SpawnCapability:
    __slots__ = ("_capture", "_taken")

    def __init__(self, capture):
        self._capture, self._taken = capture, False

    def __repr__(self):
        return "<one-use spawn capability>"

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        raise TypeError("capability_not_serializable")

    @property
    def stdin_mode(self):
        return self._capture.spec.stdin

    def take(self):
        capture = self._capture
        _require(not self._taken and not capture._closed, "token_spent")
        self._taken = True
        return dict(capture._delivery.environment), capture._spawn_cwd, capture._executable_fds[0], tuple(fd for fd, _raw in capture._descriptor_snapshots)

    def close(self):
        self._capture.close()


def discard_admission(prepared: PreparedLaunch) -> None:
    if type(prepared) is not PreparedLaunch:
        return
    with _LOCK:
        _TOKENS.pop(prepared._token, None)
    if prepared._capture is not None:
        prepared._capture.close()


def prepare_launch_v2(raw: bytes, *, binding, capture, attempt: AttemptBinding):
    """Admit only a public v2 record against an agreed, activated trusted binding."""
    from .supervised_capture_v2 import CapturedLaunch, recheck_launch_v2
    from .supervised_contracts import ContractError
    try:
        refuse_unwired_dependency_route("supervised-launch")
        _require(type(attempt) is AttemptBinding and type(capture) is CapturedLaunch
                 and not capture._closed and capture.attempt == attempt and capture.context is binding.context,
                 "launch_input_unbound")
        _require(binding.agreement is not None and binding.agreement[0] == attempt
                 and binding.codec is not None and binding.validator is not None, "binding_unavailable")
        _require(len(raw) <= capture.spec.envelope_cap, "envelope_cap")
        envelope = binding.codec.decode_v2(raw, bundle=binding.bundle)
        decision = binding.codec.validate_v2_admission(envelope, context=binding.context, capture=capture, attempt=attempt)
        if not decision.admitted:
            capture.close()
            return Refused(decision.diagnostics[0])
        _require(not envelope.value["executable_dependencies"]["declared"], "dependency_route_unwired")
        tier = envelope.value["enforcement"]["tier"]
        _require(tier == capture.spec.tier, "launch_input_unbound")
        _require(not (tier == "post_write_audit_only" and envelope.value["enforcement"]["required_constraints"]), "constraints_unsupported")
        baseline = [data for role, data in capture.references if role == "baseline"]
        _require(len(baseline) == 1, "baseline_reference_required")
        identities = tuple(ExecutableIdentity(str(path), capture.commitments["executable_chain"][index]["sha256"])
                           for index, (_wire, path) in enumerate(capture.spec.executable_chain))
        kind, device, inode = capture.workspace_identity
        policy = capture.commitments["trusted_policy"]
        capability = _SpawnCapability(capture)
        inputs = LaunchInputs(capture.instruction, sha256(capture.instruction), baseline[0], sha256(baseline[0]),
            capture.spec.argv, identities[-1], identities[:-1], str(capture.spec.workspace), str(capture.spec.target),
            kind, device, inode, tier, tuple(envelope.value["enforcement"]["required_constraints"]),
            capture.spec.timeout_seconds, policy["config_sha256"], policy["template_sha256"], policy["qualification_sha256"], capability)
        view = EnvelopeView(envelope.value, envelope.public_digest, envelope.raw_digest, capture.local_digest, inputs)
        verdict = binding.validator(view)
        _require(type(verdict) is Admit, "admit_required")
        _require(verdict == Admit(view.launch_digest, attempt.attempt_id), "admit_binding")
        _require(recheck_launch_v2(capture, context=binding.context) is None, "launch_input_unbound")
        prepared = PreparedLaunch(view, verdict, attempt_binding=attempt, _capture=capture, diagnostics=decision.diagnostics)
        with _LOCK:
            _TOKENS[prepared._token] = _Admission(id(prepared), view.launch_digest, attempt.attempt_id, envelope.raw_digest,
                                                 inputs, (attempt.assignment_digest, attempt.run_id, attempt.attempt_id))
        return prepared
    except BaseException as error:
        if type(capture) is CapturedLaunch:
            capture.close()
        return Refused(error.code if isinstance(error, ContractError) else str(error) if isinstance(error, _Refusal)
                       else "binding_invalid")
