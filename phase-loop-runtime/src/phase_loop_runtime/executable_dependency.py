"""Admission and descriptor-held projection for an executable dependency.

The private deployment boundary supplies a typed requirement and one borrowed
authority descriptor.  This module deliberately knows nothing about deployment
records or activation layout: it validates only the public authority,
declaration, selected executable, and read-only projection graph.
"""

from __future__ import annotations

import fcntl
import hashlib
from importlib import resources
import json
import os
from pathlib import PurePosixPath
import posixpath
import re
import shutil
import stat
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator
import rfc8785


AUTHORITY_MAX_BYTES = 131_072
DECLARATION_MAX_BYTES = 16_777_216
ENTRY_MAX_COUNT = 1_024
FILE_MAX_BYTES = 536_870_912
AGGREGATE_MAX_BYTES = 2_147_483_648
PATH_MAX_BYTES = 4_096
SAFE_INTEGER_MAX = 9_007_199_254_740_991

_PUBLIC_BLOCKED_DESTINATIONS = (
    "/dev",
    "/proc",
    "/sys",
    "/home",
    "/root",
    "/etc",
    "/run/credentials",
    "/run/secrets",
    "/tmp",
    "/var/tmp",
    "/var/run",
)
_AUTHORITY_MODES = frozenset({0o400, 0o440, 0o444, 0o600, 0o640, 0o644})
_HEX = frozenset("0123456789abcdef")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


class ExecutableDependencyError(RuntimeError):
    """A stable, fail-closed dependency-admission refusal."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


@dataclass(frozen=True)
class ExecutableRequirementIdentity:
    path: str
    kind: str
    mode: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ProjectionPolicy:
    """One independent projection-allowance layer.

    ``None`` owner/mode sets mean that this layer does not further narrow that
    dimension.  Numeric values are always ceilings and are intersected with the
    public hard ceilings and the local authority.
    """

    allowed_roots: tuple[str, ...] = ("/",)
    allowed_uids: frozenset[int] | None = None
    allowed_gids: frozenset[int] | None = None
    file_modes: frozenset[str] | None = None
    directory_modes: frozenset[str] | None = None
    declaration_bytes: int = DECLARATION_MAX_BYTES
    entry_count: int = ENTRY_MAX_COUNT
    file_bytes: int = FILE_MAX_BYTES
    aggregate_file_bytes: int = AGGREGATE_MAX_BYTES
    path_bytes: int = PATH_MAX_BYTES
    link_text_bytes: int = PATH_MAX_BYTES


@dataclass(frozen=True)
class ProjectionEntry:
    kind: str
    destination: str
    mode: str
    uid: int
    gid: int
    source: str | None = None
    size: int | None = None
    sha256: str | None = None
    link_text: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class ProjectionFile:
    source: str
    destination: str
    mode: str
    size: int
    sha256: str
    fd: int


@dataclass(frozen=True)
class _HeldFile:
    source: str
    destination: str
    mode: str
    size: int
    sha256: str
    fd: int
    stat_identity: tuple[int, int, int, int, int, int, int]


class DependencyProjection:
    """One consumer-owned set of reopened projection descriptors."""

    def __init__(
        self,
        *,
        files: tuple[ProjectionFile, ...],
        entries: tuple[ProjectionEntry, ...],
        digest: str,
    ) -> None:
        self.files = files
        self.entries = entries
        self.digest = digest
        self._closed = False

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(item.fd for item in self.files)

    @property
    def destinations(self) -> tuple[str, ...]:
        return tuple(item.destination for item in self.entries)

    def mount_args(self) -> tuple[str, ...]:
        by_destination = {item.destination: item for item in self.files}
        args: list[str] = []
        for entry in sorted(self.entries, key=lambda item: (_path_depth(item.destination), item.destination)):
            if entry.kind == "directory":
                args.extend(("--perms", entry.mode, "--dir", entry.destination))
            elif entry.kind == "file":
                projected = by_destination[entry.destination]
                args.extend(("--perms", entry.mode, "--ro-bind-data", str(projected.fd), entry.destination))
            else:
                assert entry.link_text is not None
                args.extend(("--symlink", entry.link_text, entry.destination))
        return tuple(args)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for item in self.files:
            _close_quietly(item.fd)

    def __enter__(self) -> DependencyProjection:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class AdmittedExecutableDependency:
    """Immutable normalized declaration plus session-owned descriptors."""

    def __init__(
        self,
        *,
        provider: str,
        authority_id: str,
        authority_sha256: str,
        declaration_id: str,
        declaration_sha256: str,
        base_profile_sha256: str,
        exclusions_sha256: str,
        subject: _HeldFile,
        files: tuple[_HeldFile, ...],
        entries: tuple[ProjectionEntry, ...],
        authority_fd: int,
        declaration_fd: int,
        projection_digest: str,
    ) -> None:
        self.provider = provider
        self.authority_id = authority_id
        self.authority_sha256 = authority_sha256
        self.declaration_id = declaration_id
        self.declaration_sha256 = declaration_sha256
        self.base_profile_sha256 = base_profile_sha256
        self.exclusions_sha256 = exclusions_sha256
        self.subject_source = subject.source
        self.subject_destination = subject.destination
        self.subject_sha256 = subject.sha256
        self.projection_digest = projection_digest
        self.entries = entries
        self._subject = subject
        self._files = files
        self._authority_fd = authority_fd
        self._declaration_fd = declaration_fd
        authority_stat = os.fstat(authority_fd)
        declaration_stat = os.fstat(declaration_fd)
        self._authority_identity = _stat_identity(authority_stat)
        self._authority_size = authority_stat.st_size
        self._declaration_identity = _stat_identity(declaration_stat)
        self._declaration_size = declaration_stat.st_size
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def revalidate(self) -> None:
        if self._closed:
            raise ExecutableDependencyError("dependency_closed")
        _revalidate_control_file(
            self._authority_fd,
            self._authority_identity,
            self._authority_size,
            self.authority_sha256,
        )
        _revalidate_control_file(
            self._declaration_fd,
            self._declaration_identity,
            self._declaration_size,
            self.declaration_sha256,
        )
        for held in (self._subject, *self._files):
            _revalidate_held_file(held)

    def validate_provider(self, provider: str) -> None:
        if provider != self.provider:
            raise ExecutableDependencyError("subject_mismatch", "provider")
        self.revalidate()

    def validate_command(self, command: Sequence[str], *, provider: str | None = None) -> None:
        if provider is not None and provider != self.provider:
            raise ExecutableDependencyError("subject_mismatch", "provider")
        if not command:
            raise ExecutableDependencyError("subject_mismatch", "empty command")
        selected = command[0]
        if not os.path.isabs(selected):
            selected = shutil.which(selected) or selected
        try:
            selected_absolute = os.path.abspath(selected)
            resolved = os.path.realpath(selected)
        except (OSError, ValueError) as exc:
            raise ExecutableDependencyError("subject_mismatch", "unresolvable command") from exc
        if selected_absolute != self.subject_source or resolved != self.subject_source:
            raise ExecutableDependencyError("subject_mismatch", "selected executable")
        self.revalidate()

    def reopen_subject(self) -> int:
        self.revalidate()
        return _dup_cloexec(self._subject.fd)

    def reopen_projection(self) -> DependencyProjection:
        self.revalidate()
        reopened: list[ProjectionFile] = []
        try:
            for held in (self._subject, *self._files):
                reopened.append(
                    ProjectionFile(
                        source=held.source,
                        destination=held.destination,
                        mode=held.mode,
                        size=held.size,
                        sha256=held.sha256,
                        fd=_dup_cloexec(held.fd),
                    )
                )
        except BaseException:
            for item in reopened:
                _close_quietly(item.fd)
            raise
        return DependencyProjection(files=tuple(reopened), entries=self.entries, digest=self.projection_digest)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fd in (
            *(item.fd for item in self._files),
            self._subject.fd,
            self._declaration_fd,
            self._authority_fd,
        ):
            _close_quietly(fd)


def admit_executable_dependency(
    requirement: Any,
    borrowed_authority_fd: int,
    expected_authority_sha256: str,
    *,
    public_policy: ProjectionPolicy | None = None,
    host_policy: ProjectionPolicy | None = None,
) -> AdmittedExecutableDependency:
    """Admit one required executable dependency without taking the borrowed FD."""

    _validate_requirement_object(requirement)
    if type(borrowed_authority_fd) is not int or borrowed_authority_fd < 0:
        raise ExecutableDependencyError("authority_invalid", "descriptor")
    if not _is_sha256(expected_authority_sha256):
        raise ExecutableDependencyError("authority_invalid", "expected digest")
    if expected_authority_sha256 != requirement.expected_authority_sha256:
        raise ExecutableDependencyError("authority_invalid", "trusted digest disagreement")

    owned: list[int] = []
    try:
        borrowed_stat = _authority_stat_or_refuse(borrowed_authority_fd)
        authority_fd = _dup_cloexec(borrowed_authority_fd)
        owned.append(authority_fd)
        if _stat_identity(os.fstat(authority_fd)) != _stat_identity(borrowed_stat):
            raise ExecutableDependencyError("authority_invalid", "descriptor changed")
        authority_raw = _read_stable_fd(authority_fd, AUTHORITY_MAX_BYTES, "authority_invalid")
        authority_sha256 = _sha256(authority_raw)
        if authority_sha256 != expected_authority_sha256:
            raise ExecutableDependencyError("authority_invalid", "digest")
        authority = _parse_canonical(authority_raw, "executable-dependency-authority-v1.schema.json")
        _validate_derived_id(authority, "authority_id", "authority_invalid")
        if len(authority_raw) > authority["limits"]["authority_bytes"]:
            raise ExecutableDependencyError("authority_invalid", "local authority size limit")
        _bind_requirement_authority(requirement, authority)

        local = _local_policy(authority)
        public = public_policy or ProjectionPolicy()
        host = host_policy or ProjectionPolicy()
        effective = _intersect_policy(public, host, local)
        declaration_fd = _open_absolute_nofollow(authority["declaration"]["path"], directory=False)
        owned.append(declaration_fd)
        _require_host_file(
            declaration_fd,
            authority["declaration"],
            code="authority_invalid",
            allowed_uids=effective.allowed_uids,
            allowed_gids=effective.allowed_gids,
            allowed_modes=effective.file_modes,
        )
        declaration_raw = _read_stable_fd(declaration_fd, effective.declaration_bytes, "authority_invalid")
        declaration_sha256 = _sha256(declaration_raw)
        if declaration_sha256 != authority["declaration"]["sha256"]:
            raise ExecutableDependencyError("authority_invalid", "declaration digest")
        declaration = _parse_canonical(
            declaration_raw,
            "executable-dependency-declaration-v1.schema.json",
        )
        _validate_derived_id(declaration, "declaration_id", "authority_invalid")
        _bind_declaration(requirement, authority, declaration)
        _validate_graph(declaration, authority, effective)

        source_roots = _open_source_roots(authority, effective)
        try:
            subject = _open_declared_file(
                declaration["subject"],
                authority["subject"]["executable"],
                source_roots,
                effective,
                code="subject_mismatch",
            )
            owned.append(subject.fd)
            files: list[_HeldFile] = []
            try:
                for entry in declaration["entries"]:
                    if entry["kind"] != "file":
                        continue
                    held = _open_declared_file(entry, None, source_roots, effective, code="authority_invalid")
                    files.append(held)
                    owned.append(held.fd)
            except BaseException:
                raise
        finally:
            for fd in source_roots.values():
                _close_quietly(fd)

        entries = _projection_entries(declaration)
        projection_digest = _projection_digest(
            authority_sha256=authority_sha256,
            declaration_sha256=declaration_sha256,
            declaration=declaration,
        )
        admitted = AdmittedExecutableDependency(
            provider=requirement.provider,
            authority_id=authority["authority_id"],
            authority_sha256=authority_sha256,
            declaration_id=declaration["declaration_id"],
            declaration_sha256=declaration_sha256,
            base_profile_sha256=declaration["base_system"]["base_profile_sha256"],
            exclusions_sha256=declaration["base_system"]["exclusions_sha256"],
            subject=subject,
            files=tuple(files),
            entries=entries,
            authority_fd=authority_fd,
            declaration_fd=declaration_fd,
            projection_digest=projection_digest,
        )
        owned.clear()
        admitted.revalidate()
        return admitted
    except ExecutableDependencyError:
        raise
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ExecutableDependencyError("authority_invalid", type(exc).__name__) from exc
    finally:
        for fd in owned:
            _close_quietly(fd)


def _validate_requirement_object(requirement: Any) -> None:
    fields = (
        "provider",
        "selected_executable",
        "authority_id",
        "expected_authority_sha256",
        "adapter_id",
        "adapter_version",
        "policy_id",
        "policy_version",
        "base_profile_sha256",
        "mode",
    )
    if requirement is None or any(not hasattr(requirement, field) for field in fields):
        raise ExecutableDependencyError("authority_invalid", "requirement type")
    if requirement.mode != "required":
        raise ExecutableDependencyError("authority_invalid", "requirement mode")
    identity = requirement.selected_executable
    if not isinstance(identity, ExecutableRequirementIdentity):
        raise ExecutableDependencyError("authority_invalid", "selected executable type")
    if identity.kind != "file" or not _is_mode(identity.mode) or not _is_sha256(identity.sha256):
        raise ExecutableDependencyError("authority_invalid", "selected executable identity")
    _canonical_absolute(identity.path)
    if type(identity.size) is not int or not 1 <= identity.size <= FILE_MAX_BYTES:
        raise ExecutableDependencyError("authority_invalid", "selected executable size")
    for value in (requirement.authority_id, requirement.expected_authority_sha256, requirement.base_profile_sha256):
        if not _is_sha256(value):
            raise ExecutableDependencyError("authority_invalid", "requirement digest")
    for value in (
        requirement.provider,
        requirement.adapter_id,
        requirement.adapter_version,
        requirement.policy_id,
        requirement.policy_version,
    ):
        if not isinstance(value, str) or _NAME.fullmatch(value) is None:
            raise ExecutableDependencyError("authority_invalid", "requirement name")


def _authority_stat_or_refuse(fd: int) -> os.stat_result:
    try:
        observed = os.fstat(fd)
    except OSError as exc:
        raise ExecutableDependencyError("authority_invalid", "descriptor unavailable") from exc
    if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
        raise ExecutableDependencyError("authority_invalid", "authority is not a single-link regular file")
    if (
        observed.st_uid not in {0, os.geteuid()}
        or observed.st_gid not in {0, os.getegid()}
        or stat.S_IMODE(observed.st_mode) not in _AUTHORITY_MODES
    ):
        raise ExecutableDependencyError("authority_invalid", "authority owner or mode")
    if not 1 <= observed.st_size <= AUTHORITY_MAX_BYTES:
        raise ExecutableDependencyError("authority_invalid", "authority size")
    _require_safe_stat(observed, "authority_invalid")
    return observed


def _parse_canonical(raw: bytes, schema_name: str) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf") or raw.endswith(b"\n"):
        raise ExecutableDependencyError("authority_invalid", "noncanonical bytes")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ExecutableDependencyError("authority_invalid", "duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExecutableDependencyError("authority_invalid", "invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExecutableDependencyError("authority_invalid", "noncanonical bytes")
    _reject_unsafe_integers(value)
    if rfc8785.dumps(value) != raw:
        raise ExecutableDependencyError("authority_invalid", "noncanonical bytes")
    schema_raw = resources.files("phase_loop_runtime.schemas").joinpath(schema_name).read_bytes()
    schema = json.loads(schema_raw)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.path),
    )
    if errors:
        raise ExecutableDependencyError("authority_invalid", f"schema: {errors[0].message}")
    return value


def _reject_unsafe_integers(value: Any) -> None:
    if type(value) is int and not -SAFE_INTEGER_MAX <= value <= SAFE_INTEGER_MAX:
        raise ExecutableDependencyError("authority_invalid", "unsafe integer")
    if isinstance(value, dict):
        for item in value.values():
            _reject_unsafe_integers(item)
    elif isinstance(value, list):
        for item in value:
            _reject_unsafe_integers(item)


def _validate_derived_id(value: Mapping[str, Any], member: str, code: str) -> None:
    unsigned = dict(value)
    identifier = unsigned.pop(member, None)
    if identifier != _sha256(rfc8785.dumps(unsigned)):
        raise ExecutableDependencyError(code, member)


def _bind_requirement_authority(requirement: Any, authority: Mapping[str, Any]) -> None:
    expected = requirement.selected_executable
    subject = authority["subject"]
    executable = subject["executable"]
    if authority["authority_id"] != requirement.authority_id:
        raise ExecutableDependencyError("authority_invalid", "authority ID")
    if subject["provider"] != requirement.provider:
        raise ExecutableDependencyError("subject_mismatch", "provider")
    if authority["adapter"] != {"id": requirement.adapter_id, "version": requirement.adapter_version}:
        raise ExecutableDependencyError("adapter_unauthorized")
    if authority["base_profile"]["base_profile_sha256"] != requirement.base_profile_sha256:
        raise ExecutableDependencyError("authority_invalid", "base profile")
    selected = {key: executable[key] for key in ("path", "mode", "size", "sha256")}
    wanted = {"path": expected.path, "mode": expected.mode, "size": expected.size, "sha256": expected.sha256}
    if selected != wanted:
        raise ExecutableDependencyError("subject_mismatch", "identity")


def _bind_declaration(requirement: Any, authority: Mapping[str, Any], declaration: Mapping[str, Any]) -> None:
    if declaration["provider"] != requirement.provider:
        raise ExecutableDependencyError("subject_mismatch", "declaration provider")
    adapter = {"id": requirement.adapter_id, "version": requirement.adapter_version}
    if declaration["adapter"] != adapter or authority["adapter"] != adapter:
        raise ExecutableDependencyError("adapter_unauthorized")
    if declaration["policy"] != {"id": requirement.policy_id, "version": requirement.policy_version}:
        raise ExecutableDependencyError("authority_invalid", "policy")
    base = declaration["base_system"]
    if base["base_profile_sha256"] != requirement.base_profile_sha256:
        raise ExecutableDependencyError("authority_invalid", "base profile")
    if authority["base_profile"] != {
        "base_profile_sha256": base["base_profile_sha256"],
        "exclusions_sha256": base["exclusions_sha256"],
    }:
        raise ExecutableDependencyError("authority_invalid", "base profile binding")
    if _sha256(rfc8785.dumps(base["exclusions"])) != base["exclusions_sha256"]:
        raise ExecutableDependencyError("authority_invalid", "exclusions digest")
    subject = declaration["subject"]
    identity = requirement.selected_executable
    if {key: subject[key] for key in ("source", "mode", "size", "sha256")} != {
        "source": identity.path,
        "mode": identity.mode,
        "size": identity.size,
        "sha256": identity.sha256,
    }:
        raise ExecutableDependencyError("subject_mismatch", "declaration identity")
    if subject["destination"] != authority["destination_policy"]["provider_destination"]:
        raise ExecutableDependencyError("subject_mismatch", "destination")


def _local_policy(authority: Mapping[str, Any]) -> ProjectionPolicy:
    owner = authority["owner_mode_policy"]
    limits = authority["limits"]
    allowed_roots = tuple(
        _canonical_absolute(path)
        for path in authority["destination_policy"]["allowed_roots"]
    )
    _require_unique_paths(allowed_roots, "allowed destination root")
    return ProjectionPolicy(
        allowed_roots=allowed_roots,
        allowed_uids=frozenset(owner["allowed_uids"]),
        allowed_gids=frozenset(owner["allowed_gids"]),
        file_modes=frozenset(owner["file_modes"]),
        directory_modes=frozenset(owner["directory_modes"]),
        declaration_bytes=limits["declaration_bytes"],
        entry_count=limits["entry_count"],
        file_bytes=limits["file_bytes"],
        aggregate_file_bytes=limits["aggregate_file_bytes"],
        path_bytes=limits["path_bytes"],
        link_text_bytes=limits["link_text_bytes"],
    )


def _intersect_policy(*layers: ProjectionPolicy) -> ProjectionPolicy:
    for layer in layers:
        if any(_canonical_policy_root(root) != root for root in layer.allowed_roots):
            raise ExecutableDependencyError("authority_invalid", "policy root")
        for name in (
            "declaration_bytes",
            "entry_count",
            "file_bytes",
            "aggregate_file_bytes",
            "path_bytes",
            "link_text_bytes",
        ):
            value = getattr(layer, name)
            if type(value) is not int or value < 1:
                raise ExecutableDependencyError("authority_invalid", "policy limit")
    roots = tuple(
        root
        for root in layers[-1].allowed_roots
        if all(any(_path_within(root, allowed) for allowed in layer.allowed_roots) for layer in layers[:-1])
    )
    if not roots:
        raise ExecutableDependencyError("authority_invalid", "destination policy intersection")

    def intersect_set(name: str) -> frozenset[Any] | None:
        values = [getattr(layer, name) for layer in layers if getattr(layer, name) is not None]
        if not values:
            return None
        result = set(values[0])
        for value in values[1:]:
            result.intersection_update(value)
        if not result:
            raise ExecutableDependencyError("authority_invalid", f"{name} intersection")
        return frozenset(result)

    return ProjectionPolicy(
        allowed_roots=roots,
        allowed_uids=intersect_set("allowed_uids"),
        allowed_gids=intersect_set("allowed_gids"),
        file_modes=intersect_set("file_modes"),
        directory_modes=intersect_set("directory_modes"),
        declaration_bytes=min(DECLARATION_MAX_BYTES, *(layer.declaration_bytes for layer in layers)),
        entry_count=min(ENTRY_MAX_COUNT, *(layer.entry_count for layer in layers)),
        file_bytes=min(FILE_MAX_BYTES, *(layer.file_bytes for layer in layers)),
        aggregate_file_bytes=min(AGGREGATE_MAX_BYTES, *(layer.aggregate_file_bytes for layer in layers)),
        path_bytes=min(PATH_MAX_BYTES, *(layer.path_bytes for layer in layers)),
        link_text_bytes=min(PATH_MAX_BYTES, *(layer.link_text_bytes for layer in layers)),
    )


def _validate_graph(
    declaration: Mapping[str, Any],
    authority: Mapping[str, Any],
    policy: ProjectionPolicy,
) -> None:
    entries = declaration["entries"]
    if len(entries) > policy.entry_count:
        raise ExecutableDependencyError("authority_invalid", "entry count")
    subject = declaration["subject"]
    all_entries = [subject, *entries]
    sources = [
        _canonical_absolute(item["source"])
        for item in all_entries
        if item["source"] is not None
    ]
    destinations = [item["destination"] for item in all_entries]
    _require_unique_paths(sources, "source")
    _require_unique_paths(destinations, "destination")
    if subject["source"] in {item["source"] for item in entries if item["source"] is not None}:
        raise ExecutableDependencyError("subject_mismatch", "source collision")
    if subject["destination"] in {
        value
        for item in entries
        for value in (item["destination"], item.get("target"))
        if value is not None
    }:
        raise ExecutableDependencyError("subject_mismatch", "destination collision")

    total = subject["size"]
    destination_kind = {subject["destination"]: "file"}
    destination_kind.update({item["destination"]: item["kind"] for item in entries})
    for item in all_entries:
        destination = _canonical_absolute(item["destination"])
        if len(destination.encode("ascii")) > policy.path_bytes:
            raise ExecutableDependencyError("authority_invalid", "destination length")
        if not any(_path_within(destination, root, strict=True) for root in policy.allowed_roots):
            raise ExecutableDependencyError("authority_invalid", "destination outside effective roots")
        if any(_path_within(destination, blocked) for blocked in _PUBLIC_BLOCKED_DESTINATIONS):
            raise ExecutableDependencyError("authority_invalid", "protected destination")
        if item["uid"] not in (policy.allowed_uids or {item["uid"]}):
            raise ExecutableDependencyError("authority_invalid", "destination uid")
        if item["gid"] not in (policy.allowed_gids or {item["gid"]}):
            raise ExecutableDependencyError("authority_invalid", "destination gid")
        allowed_modes = policy.directory_modes if item["kind"] == "directory" else policy.file_modes
        if item["kind"] != "symlink" and item["mode"] not in (allowed_modes or {item["mode"]}):
            raise ExecutableDependencyError("authority_invalid", "destination mode")
        if item["kind"] == "file":
            if item["size"] > policy.file_bytes:
                raise ExecutableDependencyError("authority_invalid", "file size")
            total += item["size"]
        elif item["kind"] == "symlink":
            link_text = item["link_text"]
            if (
                len(link_text.encode("ascii")) > policy.link_text_bytes
                or link_text.startswith("/")
                or "\x00" in link_text
                or "//" in link_text
                or link_text.endswith("/")
                or posixpath.normpath(link_text) != link_text
            ):
                raise ExecutableDependencyError("authority_invalid", "link text")
            if item["size"] != len(link_text.encode("ascii")):
                raise ExecutableDependencyError("authority_invalid", "link size")
            target = _canonical_absolute(
                posixpath.normpath(posixpath.join(posixpath.dirname(destination), link_text))
            )
            if (
                target != _canonical_absolute(item["target"])
                or destination_kind.get(target) != "file"
                or not any(_path_within(target, root, strict=True) for root in policy.allowed_roots)
            ):
                raise ExecutableDependencyError("authority_invalid", "link target")
    if total > policy.aggregate_file_bytes:
        raise ExecutableDependencyError("authority_invalid", "aggregate size")

    declared_dirs = {item["destination"] for item in entries if item["kind"] == "directory"}
    roots = set(policy.allowed_roots)
    for destination, kind in destination_kind.items():
        parent = posixpath.dirname(destination)
        if parent not in declared_dirs and not any(parent == root or _path_within(root, parent) for root in roots):
            raise ExecutableDependencyError("authority_invalid", "undeclared destination parent")
        if kind != "directory" and any(
            other != destination and _path_within(other, destination, strict=True)
            for other in destination_kind
        ):
            raise ExecutableDependencyError("authority_invalid", "non-directory destination ancestor")

    exclusions = declaration["base_system"]["exclusions"]
    exclusion_paths = [_canonical_absolute(item["path"]) for item in exclusions]
    _require_unique_paths(exclusion_paths, "exclusion")


def _open_source_roots(authority: Mapping[str, Any], policy: ProjectionPolicy) -> dict[str, int]:
    opened: dict[str, int] = {}
    try:
        for row in authority["source_roots"]:
            path = _canonical_absolute(row["path"])
            if len(path.encode("ascii")) > policy.path_bytes:
                raise ExecutableDependencyError("authority_invalid", "source root path length")
            fd = _open_absolute_nofollow(path, directory=True)
            try:
                observed = os.fstat(fd)
                _require_safe_stat(observed, "authority_invalid")
                expected = (row["device"], row["inode"], row["uid"], row["gid"], int(row["mode"], 8))
                actual = (
                    observed.st_dev,
                    observed.st_ino,
                    observed.st_uid,
                    observed.st_gid,
                    stat.S_IMODE(observed.st_mode),
                )
                if not stat.S_ISDIR(observed.st_mode) or actual != expected:
                    raise ExecutableDependencyError("authority_invalid", "source root identity")
                if row["uid"] not in (policy.allowed_uids or {row["uid"]}):
                    raise ExecutableDependencyError("authority_invalid", "source root uid")
                if row["gid"] not in (policy.allowed_gids or {row["gid"]}):
                    raise ExecutableDependencyError("authority_invalid", "source root gid")
                if row["mode"] not in (policy.directory_modes or {row["mode"]}):
                    raise ExecutableDependencyError("authority_invalid", "source root mode")
                opened[path] = fd
            except BaseException:
                _close_quietly(fd)
                raise
        _require_unique_paths(opened, "source root")
        return opened
    except BaseException:
        for fd in opened.values():
            _close_quietly(fd)
        raise


def _open_declared_file(
    row: Mapping[str, Any],
    host_row: Mapping[str, Any] | None,
    roots: Mapping[str, int],
    policy: ProjectionPolicy,
    *,
    code: str,
) -> _HeldFile:
    source = _canonical_absolute(row["source"])
    if len(source.encode("ascii")) > policy.path_bytes:
        raise ExecutableDependencyError(code, "source path length")
    containing = [root for root in roots if _path_within(source, root, strict=True)]
    if len(containing) != 1:
        raise ExecutableDependencyError(code, "source root")
    root = containing[0]
    relative = source[len(root) + (0 if root == "/" else 1) :]
    fd = _open_relative_nofollow(roots[root], relative, directory=False)
    try:
        expected = host_row or {
            "path": source,
            "uid": row["uid"],
            "gid": row["gid"],
            "mode": row["mode"],
            "nlink": row["nlink"],
            "size": row["size"],
            "sha256": row["sha256"],
        }
        _require_host_file(
            fd,
            expected,
            code=code,
            allowed_uids=policy.allowed_uids,
            allowed_gids=policy.allowed_gids,
            allowed_modes=policy.file_modes,
            require_device_inode=host_row is not None,
        )
        if row["size"] > policy.file_bytes:
            raise ExecutableDependencyError(code, "file size")
        raw = _read_stable_fd(fd, policy.file_bytes, code, exact_size=True)
        if len(raw) != row["size"] or _sha256(raw) != row["sha256"]:
            raise ExecutableDependencyError(code, "file content")
        observed = os.fstat(fd)
        return _HeldFile(
            source=source,
            destination=row["destination"],
            mode=row["mode"],
            size=row["size"],
            sha256=row["sha256"],
            fd=fd,
            stat_identity=_stat_identity(observed),
        )
    except BaseException:
        _close_quietly(fd)
        raise


def _require_host_file(
    fd: int,
    expected: Mapping[str, Any],
    *,
    code: str,
    allowed_uids: frozenset[int] | None,
    allowed_gids: frozenset[int] | None,
    allowed_modes: frozenset[str] | None,
    require_device_inode: bool = True,
) -> None:
    observed = os.fstat(fd)
    _require_safe_stat(observed, code)
    if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
        raise ExecutableDependencyError(code, "not a single-link regular file")
    if require_device_inode and (observed.st_dev, observed.st_ino) != (expected["device"], expected["inode"]):
        raise ExecutableDependencyError(code, "host identity")
    actual = {
        "uid": observed.st_uid,
        "gid": observed.st_gid,
        "mode": f"0{stat.S_IMODE(observed.st_mode):03o}",
        "nlink": observed.st_nlink,
        "size": observed.st_size,
    }
    if any(actual[key] != expected[key] for key in actual):
        raise ExecutableDependencyError(code, "file identity")
    if observed.st_uid not in (allowed_uids or {observed.st_uid}):
        raise ExecutableDependencyError(code, "file uid")
    if observed.st_gid not in (allowed_gids or {observed.st_gid}):
        raise ExecutableDependencyError(code, "file gid")
    if actual["mode"] not in (allowed_modes or {actual["mode"]}):
        raise ExecutableDependencyError(code, "file mode")


def _projection_entries(declaration: Mapping[str, Any]) -> tuple[ProjectionEntry, ...]:
    rows = [declaration["subject"], *declaration["entries"]]
    return tuple(
        ProjectionEntry(
            kind=row["kind"],
            destination=row["destination"],
            mode=row["mode"],
            uid=row["uid"],
            gid=row["gid"],
            source=row.get("source"),
            size=row.get("size"),
            sha256=row.get("sha256"),
            link_text=row.get("link_text"),
            target=row.get("target"),
        )
        for row in rows
    )


def _projection_digest(
    *,
    authority_sha256: str,
    declaration_sha256: str,
    declaration: Mapping[str, Any],
) -> str:
    document = {
        "authority_sha256": authority_sha256,
        "base_profile_sha256": declaration["base_system"]["base_profile_sha256"],
        "declaration_sha256": declaration_sha256,
        "entries": [
            {
                "destination": row["destination"],
                "kind": row["kind"],
                "link_text": row.get("link_text"),
                "mode": row["mode"],
                "sha256": row.get("sha256"),
                "target": row.get("target"),
            }
            for row in [declaration["subject"], *declaration["entries"]]
        ],
        "exclusions_sha256": declaration["base_system"]["exclusions_sha256"],
        "schema": "org.agent-harness.executable-dependency-projection.v1",
    }
    return _sha256(rfc8785.dumps(document))


def _revalidate_held_file(held: _HeldFile) -> None:
    try:
        before = os.fstat(held.fd)
        if _stat_identity(before) != held.stat_identity:
            raise ExecutableDependencyError("source_changed", held.destination)
        raw = _read_stable_fd(held.fd, held.size, "source_changed", exact_size=True)
        if len(raw) != held.size or _sha256(raw) != held.sha256:
            raise ExecutableDependencyError("source_changed", held.destination)
    except OSError as exc:
        raise ExecutableDependencyError("source_changed", held.destination) from exc


def _revalidate_control_file(
    fd: int,
    identity: tuple[int, int, int, int, int, int, int],
    size: int,
    digest: str,
) -> None:
    try:
        if _stat_identity(os.fstat(fd)) != identity:
            raise ExecutableDependencyError("authority_invalid", "control file changed")
        raw = _read_stable_fd(fd, size, "authority_invalid", exact_size=True)
        if len(raw) != size or _sha256(raw) != digest:
            raise ExecutableDependencyError("authority_invalid", "control file changed")
    except OSError as exc:
        raise ExecutableDependencyError("authority_invalid", "control file changed") from exc


def _read_stable_fd(fd: int, limit: int, code: str, *, exact_size: bool = False) -> bytes:
    before = os.fstat(fd)
    _require_safe_stat(before, code)
    if before.st_size > limit or (not exact_size and before.st_size < 1):
        raise ExecutableDependencyError(code, "size")
    raw = bytearray()
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
        if not chunk:
            break
        raw.extend(chunk)
        offset += len(chunk)
    after = os.fstat(fd)
    if _stat_identity(before) != _stat_identity(after) or len(raw) != before.st_size:
        raise ExecutableDependencyError(code, "changed while reading")
    return bytes(raw)


def _open_absolute_nofollow(path: str, *, directory: bool) -> int:
    path = _canonical_absolute(path)
    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        if path == "/":
            if directory:
                return _dup_cloexec(root_fd)
            raise ExecutableDependencyError("authority_invalid", "root is not a file")
        return _open_relative_nofollow(root_fd, path[1:], directory=directory)
    finally:
        os.close(root_fd)


def _open_relative_nofollow(root_fd: int, relative: str, *, directory: bool) -> int:
    components = relative.split("/")
    parent = _dup_cloexec(root_fd)
    try:
        for component in components[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent,
            )
            os.close(parent)
            parent = next_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        if directory:
            flags |= os.O_DIRECTORY
        return os.open(components[-1], flags, dir_fd=parent)
    finally:
        os.close(parent)


def _canonical_absolute(path: Any) -> str:
    if not isinstance(path, str) or not path.startswith("/") or path == "/":
        raise ExecutableDependencyError("authority_invalid", "absolute path")
    try:
        encoded = path.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ExecutableDependencyError("authority_invalid", "non-ASCII path") from exc
    if len(encoded) > PATH_MAX_BYTES or "\x00" in path or "//" in path or path.endswith("/"):
        raise ExecutableDependencyError("authority_invalid", "path spelling")
    parts = PurePosixPath(path).parts
    if any(part in {"", ".", ".."} for part in parts[1:]) or posixpath.normpath(path) != path:
        raise ExecutableDependencyError("authority_invalid", "path normalization")
    return path


def _canonical_policy_root(path: Any) -> str:
    if path == "/":
        return path
    return _canonical_absolute(path)


def _path_within(path: str, root: str, *, strict: bool = False) -> bool:
    if root == "/":
        return path != "/" if strict else path.startswith("/")
    return path.startswith(root + "/") or (not strict and path == root)


def _path_depth(path: str) -> int:
    return path.count("/")


def _require_unique_paths(paths: Iterable[str], label: str) -> None:
    values = list(paths)
    if len(values) != len(set(values)) or len(values) != len({value.casefold() for value in values}):
        raise ExecutableDependencyError("authority_invalid", f"{label} collision")


def _require_safe_stat(value: os.stat_result, code: str) -> None:
    for item in (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_nlink, value.st_size):
        if type(item) is not int or not 0 <= item <= SAFE_INTEGER_MAX:
            raise ExecutableDependencyError(code, "unsupported host identity")


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        stat.S_IMODE(value.st_mode),
        value.st_nlink,
        value.st_size,
    )


def _dup_cloexec(fd: int) -> int:
    return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _is_mode(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 4 and value[0] == "0" and set(value[1:]) <= set("01234567")


def frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return an immutable shallow mapping for public evidence surfaces."""

    return MappingProxyType(dict(value))
