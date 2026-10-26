"""Offline, manifest-bound fleet-map artifacts; legacy scanning stays opt-in separate."""
from __future__ import annotations

from datetime import datetime
import hashlib
from importlib.resources import files
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from .fleet_map import (
    FleetEdge, FleetMapResult, SetupDiagnostic, _CONTRACT_EXTENSIONS,
    _GIT_PIN_RE, _HOST_PATH_RE, _SKIP_DIR_NAMES, _SOURCE_EXTENSIONS,
    _dedupe_and_sort, build_fleet_map,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+\Z")
_REF = re.compile(r"^(?![-/])(?!.*\.\.)(?!.*//)(?!.*@\{)(?!.*(?:^|/)\.)(?!.*\.lock(?:/|$))(?!.*[/.]$)[^\x00-\x20\x7f~^:?*\[\\]+$")
_HINT = re.compile(r"[A-Za-z0-9_.-]{1,256}\Z")


class ArtifactError(ValueError):
    """Bounded diagnostics: never include a source value or filesystem exception."""


def _schema_validator(definition: str | None = None) -> Draft202012Validator:
    schema = json.loads(files("phase_loop_runtime").joinpath("schemas/fleet_map.v1.schema.json").read_text())
    if definition:
        schema = {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate(value: Any, definition: str | None = None) -> None:
    if not _schema_validator(definition).is_valid(value):
        raise ArtifactError("invalid artifact input or schema")


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or value.startswith("/") or "\\" in value or ":" in value
            or any(part in {".", "..", ""} for part in value.split("/"))
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ArtifactError("invalid relative path")
    return str(path)


def _safe_ref(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or value == "@" or not _REF.fullmatch(value):
        raise ArtifactError("invalid pin declaration")
    return value


def _pin_locator(value: Any) -> tuple[str, str | None]:
    if not isinstance(value, str):
        raise ArtifactError("invalid pin declaration")
    if _NAME.fullmatch(value):
        return value, None
    raw = value.removeprefix("git+")
    try:
        url = urlsplit(raw)
        if (url.scheme != "https" or url.hostname != "github.com" or url.port is not None
                or url.username is not None or url.password is not None or url.query
                or (url.fragment and not url.fragment.startswith("subdirectory="))):
            raise ArtifactError("invalid pin declaration")
        target, sep, revision = url.path.removeprefix("/").partition("@")
        target = target.removesuffix(".git")
        if not _NAME.fullmatch(target):
            raise ArtifactError("invalid pin declaration")
        return target, _safe_ref(revision) if sep else None
    except ValueError:
        raise ArtifactError("invalid pin declaration") from None


def _is_pin(path: PurePosixPath) -> bool:
    return (path.parent.name == "tools" and path.name in {
        "agent-harness.pin.json", "fleet-map-producer.pin.json",
    }) or path.name.endswith("greenfield-contract.lock.json")


def _open_directory(path: Path) -> int:
    flags = os.O_DIRECTORY | os.O_NOFOLLOW
    traversal = getattr(os, "O_PATH", os.O_RDONLY)
    fd = os.open(path.anchor, flags | (traversal if len(path.parts) > 1 else os.O_RDONLY))
    try:
        for index, part in enumerate(path.parts[1:], 1):
            mode = os.O_RDONLY if index == len(path.parts) - 1 else traversal
            child = os.open(part, flags | mode, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _walk(directory_fd: int, prefix: str = ""):
    """Read through directory descriptors, retaining the no-follow boundary."""
    for name in sorted(os.listdir(directory_fd)):
        if name in _SKIP_DIR_NAMES:
            continue
        relative = _relative(f"{prefix}/{name}" if prefix else name)
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactError("repository scan incomplete")
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            try:
                yield from _walk(child, relative)
            finally:
                os.close(child)
        elif stat.S_ISREG(info.st_mode):
            path = PurePosixPath(relative)
            pin = _is_pin(path)
            contract = (path.suffix in _CONTRACT_EXTENSIONS and not pin and
                        ("contracts" in path.parts or "schemas" in path.parts
                         or "contract" in path.stem or "schema" in path.stem))
            if not (pin or contract or path.suffix in _SOURCE_EXTENSIONS | {".bash"}):
                continue
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ArtifactError("repository scan incomplete")
                yield relative, stream.read(), pin, contract
        else:
            raise ArtifactError("repository scan incomplete")


def _pin_fields(payload: Any) -> tuple[str, dict[str, str]]:
    if not isinstance(payload, dict):
        raise ArtifactError("invalid pin declaration")
    locators = [_pin_locator(payload[key]) for key in ("repo", "url", "source") if key in payload]
    if not locators or len({name.casefold() for name, _ in locators}) != 1:
        raise ArtifactError("invalid pin declaration")
    immutable = [payload[key] for key in ("sha", "source_commit") if key in payload]
    if any(not isinstance(value, str) or not _SHA.fullmatch(value) for value in immutable):
        raise ArtifactError("invalid pin declaration")
    if len(set(immutable)) > 1:
        raise ArtifactError("invalid pin declaration")
    refs = [ref for _, ref in locators if ref is not None]
    if "ref" in payload:
        refs.append(_safe_ref(payload["ref"]))
    if len(set(refs)) > 1:
        raise ArtifactError("invalid pin declaration")
    if "version" in payload and not isinstance(payload["version"], str):
        raise ArtifactError("invalid pin declaration")
    fields = {}
    if immutable:
        fields["immutable_pin"] = immutable[0]
    if refs:
        fields["declared_ref"] = refs[0]
        if not immutable and _SHA.fullmatch(refs[0]):
            fields["immutable_pin"] = refs[0]
            fields.pop("declared_ref")
    effective = immutable[0] if immutable else refs[0] if refs else None
    if effective:
        fields["effective_ref"] = effective
        fields["pinned_ref"] = refs[0] if refs else effective
    return locators[0][0], fields


def _build_strict_fleet_map(resolved: dict[str, Path], diagnostics: list[SetupDiagnostic]) -> FleetMapResult:
    edges: list[FleetEdge] = []
    copies: dict[str, list[tuple[str, str, str]]] = {}
    failed = []
    for name, root in sorted(resolved.items()):
        local_edges = []
        local_copies = []
        try:
            fd = _open_directory(root)
            try:
                for relative, data, pin, contract in _walk(fd):
                    path = PurePosixPath(relative)
                    evidence = f"{relative}:1"
                    if pin:
                        target, fields = _pin_fields(json.loads(data))
                        local_edges.append(FleetEdge(name, target, "pin", evidence, "presence-only", fields))
                    elif contract:
                        local_copies.append((path.name, relative, hashlib.sha256(data).hexdigest()))
                    if path.suffix in _SOURCE_EXTENSIONS | {".bash"}:
                        for line, text in enumerate(data.decode("utf-8").splitlines(), 1):
                            evidence = f"{relative}:{line}"
                            if path.suffix in {".sh", ".bash"}:
                                for match in _GIT_PIN_RE.finditer(text):
                                    target, ref = _pin_locator(match.group())
                                    fields = {"effective_ref": ref, "pinned_ref": ref} if ref else {}
                                    if ref and _SHA.fullmatch(ref):
                                        fields["immutable_pin"] = ref
                                    local_edges.append(FleetEdge(name, target, "pin", evidence, "presence-only", fields))
                            for match in _HOST_PATH_RE.finditer(text):
                                hint = match.group(1)
                                if not _HINT.fullmatch(hint):
                                    raise ArtifactError("repository scan incomplete")
                                local_edges.append(FleetEdge(name, hint, "host-path", evidence, "presence-only"))
            finally:
                os.close(fd)
            declarations = {}
            for edge in local_edges:
                if edge.kind == "pin":
                    key = (edge.evidence, edge.to_repo.casefold())
                    value = edge.artifact_fields
                    if key in declarations and declarations[key] != value:
                        raise ArtifactError("conflicting pin declarations")
                    declarations[key] = value
        except (OSError, UnicodeError, ValueError):
            failed.append(name)
            continue
        edges.extend(local_edges)
        for basename, relative, digest in local_copies:
            copies.setdefault(basename, []).append((name, relative, digest))
    for occurrences in copies.values():
        ordered = sorted(occurrences, key=lambda item: (item[0].casefold(), item[1], item[2]))
        for (left, left_path, left_hash), (right, right_path, right_hash) in itertools.combinations(ordered, 2):
            if left != right and left_hash != right_hash:
                edges.append(FleetEdge(left, right, "copied-literal", f"{left_path}:1", "hash-checked",
                                       {"paired_evidence_path": f"{right_path}:1"}))
    return FleetMapResult(
        repos=tuple(sorted(set(resolved) - set(failed))), edges=_dedupe_and_sort(edges),
        setup_diagnostics=tuple(diagnostics),
    )


def _local_repositories(manifest: dict[str, Any]) -> dict[Path, str]:
    root = Path(manifest["clone_root"])
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ArtifactError("invalid clone root")
    paths = {}
    for repo in manifest["repositories"]:
        if repo["scan_state"] != "scanned":
            if repo["local_path"] is not None:
                raise ArtifactError("invalid collection result")
            continue
        if repo["local_path"] is None:
            raise ArtifactError("invalid collection result")
        relative = _relative(repo["local_path"])
        path = root
        for part in PurePosixPath(relative).parts:
            path = path / part
            if path.is_symlink():
                raise ArtifactError("invalid repository path")
        if not path.resolve().is_relative_to(root) or path in paths:
            raise ArtifactError("invalid repository path")
        paths[path] = repo["full_name"]
    return paths


def _target(raw: str, repos: dict[str, dict[str, Any]]) -> tuple[str | None, str, str | None]:
    if "/" in raw:
        found = repos.get(raw.casefold())
        if found:
            state = "not_found_or_inaccessible" if found.get("failure_code") == "not_found_or_inaccessible" else "known"
            return found["full_name"], state, None
        return raw, "outside_scope", None
    candidates = [row for row in repos.values() if row["full_name"].split("/")[1].casefold() == raw.casefold()]
    if len(candidates) == 1:
        found = candidates[0]
        state = "not_found_or_inaccessible" if found.get("failure_code") == "not_found_or_inaccessible" else "known"
        return found["full_name"], state, None
    return None, "ambiguous" if candidates else "unmatched", raw


def _comparison(edge: FleetEdge, target: dict[str, Any] | None, observation: dict[str, Any] | None) -> dict[str, Any]:
    fields = edge.artifact_fields
    result: dict[str, Any] = {"comparison": "unresolvable"}
    if "pinned_ref" in fields:
        result["pinned_ref"] = fields["pinned_ref"]
    head = target["head_sha"] if target else None
    if head:
        result["target_head_sha"] = head
    immutable = fields.get("immutable_pin")
    if observation:
        resolved = observation["resolved_pin_sha"]
        if observation["target_head_sha"] != head:
            raise ArtifactError("pin observation does not match scan")
        if immutable and resolved is not None and resolved != immutable:
            raise ArtifactError("pin observation does not match declaration")
        if resolved:
            result["resolved_pin_sha"] = resolved
        declared = fields.get("declared_ref")
        literal = fields.get("pinned_ref")
        if literal and _SHA.fullmatch(literal) and observation.get("declared_ref_sha") not in (None, literal):
            raise ArtifactError("pin observation does not match declaration")
        if immutable and declared:
            if (_SHA.fullmatch(declared) and declared != immutable) or observation.get("declared_ref_sha") != immutable:
                return result
        relation = observation["relation"]
        if relation != "unresolvable":
            if not resolved or not head or ((relation == "equal") != (resolved == head)):
                raise ArtifactError("invalid pin observation relation")
            result["comparison"] = {"equal": "up_to_date", "ancestor": "behind", "off_default_branch": "off_default_branch"}[relation]
    elif immutable:
        result["resolved_pin_sha"] = immutable
        if immutable == head and not fields.get("declared_ref"):
            result["comparison"] = "up_to_date"
    return result


def build_artifact(manifest: Any, producer_commit: str, generated_at: str) -> dict[str, Any]:
    """Build from explicit observations only; neither git nor provider APIs run here."""
    _validate(manifest, "fleet_scan_input.v1")
    if not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")):
        raise ArtifactError("artifact mode requires descriptor-based no-follow access")
    if not _SHA.fullmatch(producer_commit):
        raise ArtifactError("invalid producer commit")
    try:
        if not generated_at.endswith(("Z", "+00:00")):
            raise ValueError
        datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ArtifactError("invalid observation time") from None
    rows = manifest["repositories"]
    for row in rows:
        if row["default_branch"] is not None:
            _safe_ref(row["default_branch"])
    ids = [row["github_repository_id"] for row in rows]
    names = [row["full_name"].casefold() for row in rows]
    scope = manifest["scope"]
    accounts = scope["accounts"]
    if (len(set(ids)) != len(ids) or len(set(names)) != len(names)
            or len(rows) != scope["expected_repos"]
            or sum(account["enumerated_count"] for account in accounts) != len(rows)
            or len({account["login"].casefold() for account in accounts}) != len(accounts)
            or len({account["installation_id"] for account in accounts}) != len(accounts)):
        raise ArtifactError("inconsistent enumeration")
    for account in accounts:
        if sum(row["full_name"].split("/")[0].casefold() == account["login"].casefold() for row in rows) != account["enumerated_count"]:
            raise ArtifactError("inconsistent enumeration")
    if any(not any(row["full_name"].split("/")[0].casefold() == account["login"].casefold() for account in accounts) for row in rows):
        raise ArtifactError("inconsistent enumeration")
    paths = _local_repositories(manifest)
    scanned = build_fleet_map(paths, identity_adapter=paths.__getitem__, strict=True)
    output_rows = []
    for row in rows:
        item = {key: value for key, value in row.items() if key != "local_path"}
        if row["scan_state"] == "scanned" and row["full_name"] not in scanned.repos:
            item.update(scan_state="scan_failed", failure_code="scan_failed")
        output_rows.append(item)
    repos = {row["full_name"].casefold(): row for row in output_rows}
    observations = {}
    for observed in manifest.get("pin_observations", []):
        key = (observed["from"].casefold(), observed["evidence_path"], observed["to"].casefold(), observed["effective_ref"])
        if key in observations or observed["to"].casefold() not in repos:
            raise ArtifactError("invalid pin observation binding")
        observations[key] = observed
    edges = []
    matched = set()
    for edge in scanned.edges:
        target, state, hint = _target(edge.to_repo, repos)
        if target and target.casefold() == edge.from_repo.casefold():
            continue
        item = {"from": edge.from_repo, "to": target, "kind": edge.kind,
                "maturity_label": edge.maturity_label, "evidence_path": edge.evidence, "target_state": state}
        if hint:
            item["target_hint"] = hint
        target_row = repos.get(target.casefold()) if target else None
        if edge.kind != "copied-literal" and target_row and target_row["scan_state"] == "scanned":
            item["maturity_label"] = "realized-edge-observed"
        if edge.kind == "pin":
            key = (edge.from_repo.casefold(), edge.evidence, (target or "").casefold(), edge.artifact_fields.get("effective_ref"))
            observation = observations.get(key)
            if observation:
                matched.add(key)
            item.update(_comparison(edge, target_row, observation))
        elif edge.kind == "copied-literal":
            item["paired_evidence_path"] = edge.artifact_fields["paired_evidence_path"]
        edges.append(item)
    if matched != set(observations):
        raise ArtifactError("unmatched pin observation")
    result = {
        "schema": "fleet_map.v1", "source_commit": producer_commit, "generated_at": generated_at,
        "scope": {**scope, "accounts": sorted(accounts, key=lambda a: a["login"].casefold())},
        "repositories": sorted(output_rows, key=lambda row: row["full_name"].casefold()),
        "scanned_repos": sorted((row["full_name"] for row in output_rows if row["scan_state"] == "scanned"), key=str.casefold),
        "edges": sorted({json.dumps(item, sort_keys=True): item for item in edges}.values(), key=lambda item: json.dumps(item, sort_keys=True)),
    }
    _validate(result)
    return result


def write_artifact(manifest_path: Path, producer_commit: str, generated_at: str, output: Path) -> None:
    try:
        manifest = json.loads(manifest_path.read_bytes())
        artifact = build_artifact(manifest, producer_commit, generated_at)
        content = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.replace(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except ArtifactError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise ArtifactError("artifact input/output failed") from None
