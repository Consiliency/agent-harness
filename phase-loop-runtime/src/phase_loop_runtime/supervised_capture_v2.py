"""One-attempt local capture, with held descriptors and separate secret delivery."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from .supervised_launch import AttemptBinding, Refused, _Refusal, _require, classify_workspace
from .supervised_envelope_v2 import _freeze, _plain, _relative, _strings, canonicalize_v2


@dataclass(frozen=True, slots=True)
class SourceSpec:
    wire: object
    path: Path | None = None
    descriptor: int | None = None
    inline: bytes | None = field(default=None, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "wire", _freeze(_plain(self.wire)))


@dataclass(frozen=True, slots=True)
class TrustedLaunchSpec:
    workspace: Path
    target: Path
    reference_roots: tuple[Path, ...]
    argv: tuple[str, ...]
    cwd: Path
    cwd_locator: object
    instructions: SourceSpec
    references: tuple[tuple[str, SourceSpec], ...]
    executable_chain: tuple[tuple[object, Path], ...]
    config_path: Path
    template_path: Path
    qualification_path: Path
    environment_policy_path: Path
    environment_policy_id: str
    non_secret_environment: tuple[tuple[str, str], ...]
    secret_sources: tuple[tuple[str, str, Path], ...]
    timeout_seconds: int
    deadline_action: str
    tier: str
    base_commit: str | None
    target_map: tuple[object, ...]
    grants: tuple[tuple[str, str, object], ...] = ()
    envelope_cap: int = 1048576
    reference_cap: int = 1048576
    aggregate_cap: int = 16777216
    stdin: str = "input"
    declared_roots: tuple[tuple[str, Path], ...] = ()
    view_roots: tuple[tuple[str, Path], ...] = ()
    template_slots: tuple[tuple[str, str], ...] = ()
    discovery_names: tuple[str, ...] = ()
    action: str = "execution"
    transport_id: str = "local"

    def __post_init__(self):
        object.__setattr__(self, "cwd_locator", _freeze(_plain(self.cwd_locator)))
        object.__setattr__(self, "target_map", tuple(_freeze(_plain(row)) for row in self.target_map))
        object.__setattr__(self, "executable_chain", tuple((_freeze(_plain(row)), path) for row, path in self.executable_chain))
        object.__setattr__(self, "grants", tuple((name, form, _freeze(_plain(value)) if form == "rfc8785" else value)
                                               for name, form, value in self.grants))


class _Delivery:
    __slots__ = ("environment", "values")

    def __init__(self, environment, values):
        self.environment = environment
        self.values = values

    def __repr__(self):
        return "<secret delivery>"

    def close(self):
        self.environment.clear()
        self.values.clear()


class CapturedLaunch:
    __slots__ = ("spec", "attempt", "context", "commitments", "diagnostics", "credential_sources",
                 "instruction", "references", "workspace_identity", "local_digest", "_snapshots", "_fds",
                 "_delivery", "_tree_digest", "_closed", "_spent", "uncheckable",
                 "_executable_fds", "_descriptor_snapshots", "_spawn_cwd", "_discoveries", "_sealed")

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False) and not name.startswith("_"):
            raise AttributeError("capture_immutable")
        object.__setattr__(self, name, value)

    def __repr__(self):
        return "<one-attempt launch capture>"

    def __reduce__(self):
        raise TypeError("capture_not_serializable")

    def close(self):
        if not self._closed:
            self._closed = True
            for descriptor in self._fds:
                os.close(descriptor)
            self._fds.clear()
            self._delivery.close()

    def contains_secret(self, value):
        if self._closed:
            return True
        strings = tuple(_strings(value))
        for secret in self._delivery.values:
            for spelling in (secret, sha256(secret.encode()).hexdigest()):
                if spelling and any(spelling in text for text in strings):
                    return True
        return False

    def suitable(self, value, context, attempt):
        if not value:
            return True
        attestation = context.caller_context_suitability
        expected = dict(sha256=sha256(canonicalize_v2(value)).hexdigest(), assignment_digest=attempt.assignment_digest,
                        run_id=attempt.run_id, attempt_id=attempt.attempt_id, policy_epoch=context.policy_epoch)
        if not all(attestation.get(key) == item for key, item in expected.items()):
            return False
        issuer = attestation.get("issuer_id")
        records = context.policy.get("caller_context_records", {}).get(issuer, {})
        return (attestation.get("record_id") not in context.revoked_record_ids
                and records.get(attestation.get("record_id")) == sha256(canonicalize_v2(attestation)).hexdigest())


def _open_snapshot(path, cap, *, trusted=False, executable=False, excluded=()):
    _require(path.is_absolute() and ".." not in path.parts, "launch_input_unbound")
    excluded_ids = {(root.stat().st_dev, root.stat().st_ino) for root in excluded}
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, part in enumerate(path.parts[1:]):
            child = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC |
                            (os.O_DIRECTORY if index < len(path.parts) - 2 else 0), dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            _require((info.st_dev, info.st_ino) not in excluded_ids, "launch_input_unbound")
            if trusted:
                owners = {0, os.getuid()} if executable or index < len(path.parts) - 2 else {os.getuid()}
                _require(info.st_uid in owners and not info.st_mode & 0o022, "launch_input_unbound")
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= cap, "launch_input_unbound")
        if executable:
            _require(bool(info.st_mode & 0o111), "launch_input_unbound")
        data, size = [], 0
        while size <= cap:
            chunk = os.read(fd, min(65536, cap + 1 - size))
            if not chunk:
                break
            data.append(chunk)
            size += len(chunk)
        _require(size <= cap, "launch_input_unbound")
        result = fd, b"".join(data), (info.st_dev, info.st_ino, info.st_mode)
        fd = None
        return result
    finally:
        if fd is not None:
            os.close(fd)


def _tree_manifest(entries):
    """The same listing reducer is used by real tree walks and corpus adapters."""
    rows, kinds = [], {}
    for entry in entries:
        path = entry["path"]
        _require(type(path) is str, "launch_input_unbound")
        if path == ".git" or path.startswith(".git/"):
            continue
        _require(_relative(path) and path not in kinds, "launch_input_unbound")
        path.encode("utf-8")
        kind = entry["type"]
        kinds[path] = kind
        if kind == "dir":
            continue
        if kind == "file":
            _require(type(entry.get("mode")) is int, "launch_input_unbound")
            raw = entry["bytes"] if "bytes" in entry else entry["content"].encode()
            wire_kind = "executable_file" if entry["mode"] & 0o111 else "file"
        elif kind == "symlink":
            raw = bytes.fromhex(entry["target_hex"])
            wire_kind = "symlink"
        else:
            raise _Refusal("launch_input_unbound")
        rows.append([path, wire_kind, sha256(raw).hexdigest()])
    for path in kinds:
        pieces = path.split("/")
        _require(all(kinds.get("/".join(pieces[:index]), "dir") == "dir" for index in range(1, len(pieces))),
                 "launch_input_unbound")
    rows.sort(key=lambda row: row[0].encode())
    return rows


def _walk_tree(root, cap, *, with_entries=False):
    entries, total = [], 0
    def walk(directory, prefix=""):
        nonlocal total
        for name in os.listdir(directory):
            if not prefix and name == ".git":
                continue
            relative = prefix + name
            _require(_relative(relative), "launch_input_unbound")
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                entries.append(dict(path=relative, type="dir"))
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    walk(child, relative + "/")
                finally:
                    os.close(child)
            elif stat.S_ISLNK(info.st_mode):
                target = os.readlink(os.fsencode(name), dir_fd=directory)
                entries.append(dict(path=relative, type="symlink", target_hex=target.hex()))
            else:
                _require(stat.S_ISREG(info.st_mode), "launch_input_unbound")
                file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                try:
                    observed = os.fstat(file)
                    _require((observed.st_dev, observed.st_ino) == (info.st_dev, info.st_ino), "launch_input_unbound")
                    chunks = []
                    while total <= cap:
                        chunk = os.read(file, min(65536, cap + 1 - total))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                    _require(total <= cap, "launch_input_unbound")
                    entries.append(dict(path=relative, type="file", mode=observed.st_mode, bytes=b"".join(chunks)))
                finally:
                    os.close(file)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(directory)
    finally:
        os.close(directory)
    manifest = _tree_manifest(entries)
    return (manifest, entries) if with_entries else manifest


def capture_launch_v2(*, spec: TrustedLaunchSpec, context, attempt: AttemptBinding):
    """Snapshot declared material without launching helpers or consulting ambient env."""
    from .supervised_launch import trusted_bytes
    capture = CapturedLaunch()
    capture._fds, capture._snapshots = [], []
    capture._executable_fds, capture._descriptor_snapshots, capture._discoveries = [], [], []
    capture._delivery = _Delivery({}, [])
    capture._closed, capture._spent = False, False
    try:
        _require(type(spec) is TrustedLaunchSpec and type(attempt) is AttemptBinding, "launch_input_unbound")
        _require(attempt.assignment_digest == context.expected_assignment_digest, "authority_foreign")
        _require(all(type(limit) is int and limit > 0 for limit in
                     (spec.envelope_cap, spec.reference_cap, spec.aggregate_cap)), "launch_input_unbound")
        capture.spec, capture.context, capture.attempt = spec, context, attempt
        capture._snapshots.extend((path, data, True, False) for path, data in context.snapshots)
        capture.workspace_identity = classify_workspace(spec.workspace, spec.target, spec.tier)
        excluded = (spec.workspace, spec.target, *spec.reference_roots)
        documents = {}
        for name, path in (("config", spec.config_path), ("template", spec.template_path),
                           ("qualification", spec.qualification_path), ("environment", spec.environment_policy_path)):
            raw = dict(context.snapshots).get(path)
            _require(type(raw) is bytes, "launch_input_unbound")
            documents[name] = raw
            capture._snapshots.append((path, raw, True, False))
        environment = dict(spec.non_secret_environment)
        _require(len(environment) == len(spec.non_secret_environment), "launch_input_unbound")
        secret_names, credential_sources = [], []
        policy = json.loads(documents["environment"])
        classification = policy["classification"]
        _require(all(classification.get(name) == "non_secret" for name in environment), "launch_input_unbound")
        for name, source, path in spec.secret_sources:
            _require(name not in environment and classification.get(name) == {"secret": source}, "launch_input_unbound")
            raw = trusted_bytes(path, excluded=excluded)
            secret = raw.decode("utf-8")
            _require(bool(secret) and "\x00" not in secret, "launch_input_unbound")
            environment[name] = secret
            capture._delivery.values.append(secret)
            secret_names.append(name)
            credential_sources.append(source)
        _require(all(type(name) is str and name and "=" not in name and "\x00" not in name
                     and type(value) is str and "\x00" not in value for name, value in environment.items()), "launch_input_unbound")
        canonicalize_v2(environment)
        capture._delivery.environment = environment
        capture.credential_sources = tuple(credential_sources)
        _require(environment.get("PHASE_LOOP_SCRATCH_DECIDED") == "frozen_capture", "launch_input_unbound")
        total = 0
        def source_bytes(source):
            nonlocal total
            if source.wire is None:
                _require(type(source.inline) is bytes and source.path is None and source.descriptor is None,
                         "launch_input_unbound")
                raw = source.inline
            elif source.descriptor is not None:
                _require(source.wire["namespace"] == "descriptor" and source.path is None, "launch_input_unbound")
                import fcntl
                _require(fcntl.fcntl(source.descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY, "launch_input_unbound")
                fd = os.dup(source.descriptor)
                capture._fds.append(fd)
                _require(stat.S_ISREG(os.fstat(fd).st_mode), "launch_input_unbound")
                raw = os.pread(fd, spec.reference_cap + 1, 0)
                capture._descriptor_snapshots.append((source.descriptor, fd, raw))
            else:
                _require(source.path is not None and _relative(source.wire["path"]), "launch_input_unbound")
                if source.wire["namespace"] == "workspace":
                    _require(source.path == spec.workspace / source.wire["path"], "launch_input_unbound")
                else:
                    # A declared root has one operator-bound name and physical path.
                    roots = dict(spec.declared_roots)
                    root = roots.get(source.wire.get("root"))
                    _require(root is not None and Path(root) in spec.reference_roots
                             and source.path == Path(root) / source.wire["path"], "launch_input_unbound")
                fd, raw, _info = _open_snapshot(source.path, spec.reference_cap)
                capture._fds.append(fd)
                capture._snapshots.append((source.path, raw, False, False))
            _require(len(raw) <= spec.reference_cap, "launch_input_unbound")
            total += len(raw)
            _require(total <= spec.aggregate_cap, "launch_input_unbound")
            return raw
        capture.instruction = source_bytes(spec.instructions)
        reference_bytes, references = [], []
        for role, source in spec.references:
            raw = source_bytes(source)
            reference_bytes.append((role, raw))
            references.append(dict(role=role, source=_plain(source.wire), sha256=sha256(raw).hexdigest(), byte_length=len(raw)))
        capture.references = tuple(reference_bytes)
        chain = []
        for _name, root in (*spec.declared_roots, *spec.view_roots):
            _require(root in spec.reference_roots, "launch_input_unbound")
        for declared, path in spec.executable_chain:
            fd, raw, _info = _open_snapshot(path, spec.reference_cap, trusted=True, executable=True, excluded=excluded)
            capture._fds.append(fd)
            capture._executable_fds.append(fd)
            capture._snapshots.append((path, raw, True, True))
            chain.append({**_plain(declared), "sha256": sha256(raw).hexdigest()})
        _require(bool(chain) and spec.argv and spec.argv[0] == str(spec.executable_chain[0][1]), "launch_input_unbound")
        _require(all(type(word) is str and "\x00" not in word for word in spec.argv), "launch_input_unbound")
        template = json.loads(documents["template"])
        import string
        slots = dict(spec.template_slots)
        expanded = []
        for word in template["argv"]:
            for _literal, field_name, format_spec, conversion in string.Formatter().parse(word):
                _require(field_name is None or (field_name in slots and not format_spec and conversion is None), "launch_input_unbound")
            expanded.append(word.format_map(slots))
        _require(expanded == list(spec.argv), "launch_input_unbound")
        def local_cwd(locator):
            _require(_relative(locator["path"], cwd=True), "launch_input_unbound")
            root = spec.workspace if locator["namespace"] == "workspace" else dict(spec.view_roots).get(locator.get("root"))
            _require(root is not None, "launch_input_unbound")
            path = root / locator["path"]
            _require(path.is_dir() and all(not parent.is_symlink() for parent in (path, *path.parents)), "launch_input_unbound")
            return path
        spawn_locator = template["spawn_cwd"]
        capture._spawn_cwd = local_cwd(spawn_locator)
        worker_argv, worker_environment, worker_cwd = list(spec.argv), dict(environment), spawn_locator
        _require(len(template.get("helpers", ())) == len(chain) - 1, "launch_input_unbound")
        for index, helper in enumerate(template.get("helpers", ())):
            _require(helper["chain_index"] == index and type(helper["argv_shift"]) is int
                     and 0 < helper["argv_shift"] < len(worker_argv), "launch_input_unbound")
            worker_argv = worker_argv[helper["argv_shift"]:]
            for name, value in helper.get("env_consumed", {}).items():
                _require(worker_environment.pop(name, None) == value, "launch_input_unbound")
            worker_environment.update(helper.get("env_set", {}))
            worker_cwd = helper.get("cwd", worker_cwd)
        _require(local_cwd(worker_cwd) == spec.cwd and _plain(worker_cwd) == _plain(spec.cwd_locator), "launch_input_unbound")
        _require(spec.stdin in ("input", "devnull") and spec.deadline_action == "terminate_process_group", "launch_input_unbound")
        manifest, tree_entries = _walk_tree(spec.workspace, spec.aggregate_cap, with_entries=True)
        capture._tree_digest = sha256(canonicalize_v2(manifest)).hexdigest()
        for entry in tree_entries:
            data = entry.get("bytes", bytes.fromhex(entry.get("target_hex", "")))
            for secret in capture._delivery.values:
                _require(secret.encode() not in data and sha256(secret.encode()).hexdigest().encode() not in data,
                         "launch_input_unbound")
        grants = {}
        for name, form, value in spec.grants:
            _require(name not in grants and form in ("raw_bytes", "rfc8785"), "launch_input_unbound")
            if form == "raw_bytes":
                raw = dict(context.snapshots).get(value)
                _require(type(raw) is bytes, "launch_input_unbound")
                capture._snapshots.append((value, raw, True, False))
                grants[name] = dict(canonical_form=form, text=raw)
            else:
                grants[name] = dict(canonical_form=form, value=_plain(value))
        discovered = []
        for name in spec.discovery_names:
            _require(_relative(name), "launch_input_unbound")
            path = spec.cwd / name
            exists = path.exists() or path.is_symlink()
            capture._discoveries.append((path, exists))
            if exists:
                match = next((source for _role, source in spec.references if source.path == path), None)
                _require(match is not None, "launch_input_unbound")
                discovered.append(_plain(match.wire))
        material = dict(instructions=dict(source=_plain(spec.instructions.wire), content=capture.instruction, within_root=True),
            references=[dict(role=role, source=_plain(source.wire), content=data, within_root=True)
                        for (role, source), (_captured_role, data) in zip(spec.references, capture.references)],
            stdin=dict(mode="pipe" if spec.stdin == "input" else "devnull",
                       writes=[dict(after="start", text=capture.instruction)] if spec.stdin == "input" else []),
            process=dict(spawn=dict(argv=list(spec.argv), env=environment, cwd=spawn_locator),
                         worker=dict(argv=worker_argv, env=worker_environment, cwd=worker_cwd),
                         cwd_resolution=dict(within_root=True, discovered=discovered),
                         deadline=dict(origin="first_chain_process", seconds=spec.timeout_seconds, restarted_at_helper=False), probes=[]),
            executable_chain=chain, workspace=dict(base_commit=spec.base_commit, capture=tree_entries, target_map=_plain(spec.target_map)),
            environment=dict(policy_id=spec.environment_policy_id, policy=documents["environment"]),
            policy=dict(**{name: data for name, data in documents.items() if name != "environment"}, grants=grants), unbound_inputs=[])
        capture.commitments, capture.diagnostics, capture.credential_sources, capture.uncheckable = _commit_material(
            material, timeout_seconds=spec.timeout_seconds, deadline_action=spec.deadline_action)
        _require(not capture.diagnostics and not capture.uncheckable, "launch_input_unbound")
        capture.commitments = _freeze({**_plain(capture.commitments), "action": spec.action, "transport_id": spec.transport_id})
        _require(not capture.contains_secret(spec.argv) and not capture.contains_secret(capture.commitments), "launch_input_unbound")
        for raw in (capture.instruction, *(row[1] for row in capture._snapshots)):
            for secret in capture._delivery.values:
                _require(secret.encode() not in raw and sha256(secret.encode()).hexdigest().encode() not in raw, "launch_input_unbound")
        capture.local_digest = sha256(b"agent-harness:supervised-launch:v2\0" + canonicalize_v2(dict(
            commitments=capture.commitments, assignment_digest=attempt.assignment_digest, run_id=attempt.run_id,
            attempt_id=attempt.attempt_id, workspace=str(spec.workspace), target=str(spec.target),
            secret_sources=[(name, source, str(path)) for name, source, path in spec.secret_sources],
            authority=dict(expected_snapshot_ref=context.expected_snapshot_ref, expected_crosswalk_ref=context.expected_crosswalk_ref,
                           policy_epoch=context.policy_epoch, revoked_record_ids=context.revoked_record_ids,
                           qualified_routes=context.qualified_routes),
            argv=spec.argv, cwd=str(spec.cwd), credential_sources=capture.credential_sources))).hexdigest()
        capture._sealed = True
        return capture
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, _Refusal) as error:
        reason = str(error) if isinstance(error, _Refusal) else "launch_input_unbound"
    capture.close()
    return Refused(reason)


def recheck_launch_v2(capture: CapturedLaunch, *, context):
    """Recheck every captured public input; secret values are never compared or hashed."""
    from .supervised_launch import trusted_bytes
    try:
        _require(type(capture) is CapturedLaunch and not capture._closed and context is capture.context, "launch_input_unbound")
        spec = capture.spec
        _require(classify_workspace(spec.workspace, spec.target, spec.tier) == capture.workspace_identity, "launch_input_unbound")
        _require(sha256(canonicalize_v2(_walk_tree(spec.workspace, spec.aggregate_cap))).hexdigest() == capture._tree_digest,
                 "launch_input_unbound")
        excluded = (spec.workspace, spec.target, *spec.reference_roots)
        for path, expected, trusted, executable in capture._snapshots:
            if trusted and not executable:
                raw = trusted_bytes(path, excluded=excluded)
            else:
                fd, raw, _info = _open_snapshot(path, spec.reference_cap, trusted=trusted, executable=executable,
                                                excluded=excluded if trusted else ())
                os.close(fd)
            _require(raw == expected, "launch_input_unbound")
        for original, fd, expected in capture._descriptor_snapshots:
            original_info, held_info = os.fstat(original), os.fstat(fd)
            _require((original_info.st_dev, original_info.st_ino, original_info.st_mode) ==
                     (held_info.st_dev, held_info.st_ino, held_info.st_mode)
                     and os.pread(fd, spec.reference_cap + 1, 0) == expected
                     and os.pread(original, spec.reference_cap + 1, 0) == expected, "launch_input_unbound")
        for path, existed in capture._discoveries:
            _require((path.exists() or path.is_symlink()) == existed, "launch_input_unbound")
        for _name, _source, path in spec.secret_sources:
            # Presence and source remain bound; a same-source value rotation is allowed.
            trusted_bytes(path, excluded=excluded)
        return None
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, _Refusal):
        if type(capture) is CapturedLaunch:
            capture.close()
        return Refused("launch_input_unbound")


def _commit_material(material, *, timeout_seconds, deadline_action):
    """Reduce captured material to public commitments without returning secret values."""
    from collections.abc import Mapping
    errors, unavailable, credentials = set(), set(), set()
    commitments = {}
    import re
    config = material["policy"]["config"]
    if isinstance(config, bytes):
        config = config.decode("utf-8")
    root_names = set(re.findall(r"^root ([A-Za-z0-9._-]+) = .+$", config, re.M))
    try:
        root_names.update(json.loads(config).get("declared_roots", {}))
    except (ValueError, TypeError):
        pass
    applied = material["policy"].get("grants", {})
    if any(row.get("terminal") or row.get("purpose") == "terminal"
           for row in applied.get("descriptor_capabilities_sha256", {}).get("value", {}).get("descriptors", ())):
        errors.add("launch_input_unbound")
    descriptor_names = {row["id"] for row in applied.get("descriptor_capabilities_sha256", {}).get("value", {}).get("descriptors", ())}
    view_names = {row["id"] for row in applied.get("filesystem_view_sha256", {}).get("value", {}).get("roots", ())}
    def digest(value):
        return sha256(canonicalize_v2(value)).hexdigest()
    def raw(value):
        return value if type(value) is bytes else value.encode("utf-8")
    def bound_source(source, code, tree):
        wire = source["source"]
        if not source.get("within_root", False):
            errors.add("launch_input_unbound")
        if wire is not None and ((wire["namespace"] == "declared_root" and wire.get("root") not in root_names)
                                 or (wire["namespace"] == "descriptor" and wire.get("descriptor") not in descriptor_names)):
            errors.add("launch_input_unbound")
        if type(source["content"]) not in (str, bytes):
            errors.add(code)
        _require(type(source["content"]) in (str, bytes), "launch_input_unbound")
        content = raw(source["content"])
        if wire is not None and wire["namespace"] == "workspace" and "workspace_state" not in unavailable:
            entry = tree.get(wire["path"])
            if entry is None or entry[1] not in ("file", "executable_file") or entry[2] != sha256(content).hexdigest():
                errors.add(code)
        return dict(source=_plain(wire), sha256=sha256(content).hexdigest(), byte_length=len(content))
    try:
        manifest = _tree_manifest(material["workspace"]["capture"])
        tree = {row[0]: row for row in manifest}
        commitments["workspace_state"] = dict(base_commit=material["workspace"]["base_commit"],
            content_form="rfc8785_tree_manifest", content_sha256=digest(manifest),
            target_map=_plain(material["workspace"]["target_map"]), cwd=_plain(material["process"]["worker"]["cwd"]))
    except (ValueError, TypeError, KeyError, UnicodeError, _Refusal):
        tree = {}
        unavailable.add("workspace_state")
        errors.add("launch_input_unbound")
    process, stdin = material["process"], material["stdin"]
    instruction = material["instructions"]
    try:
        commitments["instructions"] = bound_source(instruction, "launch_instructions_mismatch", tree)
        commits = [dict(role=source["role"], **bound_source(source, "launch_reference_mismatch", tree)) for source in material["references"]]
        commitments["references"] = commits
    except (ValueError, TypeError, KeyError, UnicodeError, _Refusal):
        unavailable.update(("instructions", "references"))
        errors.add("launch_input_unbound")
    spawn, worker = process["spawn"], process["worker"]
    try:
        argv = spawn["argv"]
        _require(isinstance(argv, (list, tuple)) and argv and all(type(word) is str and "\x00" not in word for word in argv), "launch_input_unbound")
        commitments["argv"] = dict(canonical_form="rfc8785_array_of_strings", sha256=digest(argv), element_count=len(argv))
    except (ValueError, TypeError, UnicodeError, _Refusal):
        unavailable.add("argv")
        errors.add("launch_input_unbound")
    template = json.loads(material["policy"]["template"])
    derived_argv, derived_env, derived_cwd = list(spawn["argv"]), dict(spawn["env"]), spawn["cwd"]
    if _plain(template.get("spawn_cwd")) != _plain(derived_cwd):
        errors.add("launch_input_unbound")
    for index, helper in enumerate(template.get("helpers", ())):
        if (helper.get("chain_index") != index or type(helper.get("argv_shift")) is not int
                or not 0 < helper["argv_shift"] < len(derived_argv)):
            errors.add("launch_input_unbound")
            continue
        derived_argv = derived_argv[helper["argv_shift"]:]
        for name, value in helper.get("env_consumed", {}).items():
            if derived_env.pop(name, None) != value:
                errors.add("launch_input_unbound")
        derived_env.update(helper.get("env_set", {}))
        if "cwd" in helper:
            derived_cwd = helper["cwd"]
    if derived_argv != list(worker["argv"]):
        errors.add("launch_argv_mismatch")
    environment_policy = json.loads(material["environment"]["policy"])
    unknown_spawn = any(name not in environment_policy["classification"] for name in spawn["env"])
    if unknown_spawn:
        errors.add("launch_input_unbound")
    elif derived_env != dict(worker["env"]):
        errors.add("launch_environment_mismatch")
    if _plain(derived_cwd) != _plain(worker["cwd"]):
        errors.add("launch_workspace_mismatch")
    if not process["cwd_resolution"].get("within_root", False):
        errors.add("launch_input_unbound")
    sources = [_plain(row["source"]) for row in material["references"]]
    if any(_plain(source) not in sources for source in process["cwd_resolution"].get("discovered", ())):
        errors.add("launch_input_unbound")
    if stdin["mode"] == "pipe":
        writes = stdin.get("writes", ())
        if len(writes) != 1 or writes[0].get("after") != "start":
            errors.add("launch_input_unbound")
        elif writes[0].get("text") != instruction["content"]:
            errors.add("launch_instructions_mismatch")
        delivery = "input"
    elif stdin["mode"] == "devnull":
        delivery = "devnull"
        if stdin.get("writes"):
            errors.add("launch_input_unbound")
    else:
        delivery = None
        errors.add("launch_input_unbound")
    if instruction["source"] is None and delivery == "devnull" and list(worker["argv"]).count(instruction["content"]) != 1:
        errors.add("launch_instructions_mismatch")
    if worker["cwd"]["namespace"] == "view_root" and worker["cwd"].get("root") not in view_names:
        errors.add("launch_input_unbound")
    commitments["executable_chain"] = _plain(material["executable_chain"])
    for entry in material["executable_chain"]:
        if entry["locator_kind"] == "repo_relative" and "workspace_state" not in unavailable:
            actual = tree.get(entry["locator"])
            if actual is None or actual[1] not in ("file", "executable_file") or actual[2] != entry["sha256"]:
                errors.add("launch_executable_mismatch")
    environment_policy = json.loads(material["environment"]["policy"])
    non_secret, secret_names, secrets = {}, [], []
    try:
        for name, value in worker["env"].items():
            _require(type(name) is str and name and "=" not in name and "\x00" not in name
                     and type(value) is str and "\x00" not in value, "launch_input_unbound")
            canonicalize_v2({name: value})
            classification = environment_policy["classification"].get(name)
            if classification == "non_secret":
                non_secret[name] = value
            else:
                _require(isinstance(classification, Mapping) and set(classification) == {"secret"}, "launch_input_unbound")
                credentials.add(classification["secret"])
                secret_names.append(name)
                secrets.append(value)
        redacted = dict(non_secret=non_secret, secret_names=sorted(secret_names, key=lambda name: name.encode("utf-16-be")))
        commitments["environment"] = dict(canonical_form="rfc8785_redacted_environment", map_sha256=digest(redacted),
            policy=dict(id=material["environment"]["policy_id"], sha256=sha256(raw(material["environment"]["policy"])).hexdigest()))
    except (ValueError, TypeError, KeyError, UnicodeError, _Refusal):
        unavailable.add("environment")
        errors.add("launch_input_unbound")
    policy = material["policy"]
    commitments["trusted_policy"] = {name + "_sha256": sha256(raw(policy[name])).hexdigest() if policy[name] is not None else None
                                      for name in ("config", "template", "qualification")}
    grants = {}
    for name, grant in policy.get("grants", {}).items():
        form = grant["canonical_form"]
        if form == "raw_bytes":
            data = raw(grant.get("text", grant.get("value")))
        elif form == "rfc8785":
            data = canonicalize_v2(grant["value"])
        else:
            errors.add("launch_input_unbound")
            continue
        grants[name] = dict(canonical_form=form, sha256=sha256(data).hexdigest())
    if grants:
        commitments["grants"] = grants
    deadline = process["deadline"]
    commitments["stop"] = dict(timeout_seconds=timeout_seconds, deadline_action=deadline_action)
    if (deadline.get("origin") != "first_chain_process" or deadline.get("restarted_at_helper")
            or deadline.get("seconds") != (timeout_seconds if deadline_action == "terminate_process_group" else None)):
        errors.add("launch_timeout_mismatch")
    if material.get("unbound_inputs") or any(probe.get("mutated_captured") or probe.get("phase") != "before_admission"
                                            or probe.get("is_worker") or list(probe.get("argv", ()))[1:] != ["--version"]
                                            for probe in process.get("probes", ())):
        errors.add("launch_input_unbound")
    # Scan every committed public string, including decoded member names. Secret
    # delivery values themselves are excluded from the scan's public view.
    public_material = {key: value for key, value in material.items() if key != "process"}
    public_strings = list(_strings(public_material)) + list(_strings(spawn["argv"])) + list(_strings(non_secret))
    for secret in secrets:
        if secret and any(spelling in text for spelling in (secret, sha256(secret.encode()).hexdigest()) for text in public_strings):
            errors.add("launch_input_unbound")
    commitments["stdin"] = delivery
    return _freeze(commitments), tuple(sorted(errors)), tuple(sorted(credentials)), tuple(sorted(unavailable))
