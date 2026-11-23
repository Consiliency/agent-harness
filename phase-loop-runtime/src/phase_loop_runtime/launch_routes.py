"""LaneExec routes, templates and template registration (LANEEXEC SL-7, binding §7 E3-3).

Three pure pieces, each a closed function over the frozen wire artifact
(``plans/artifacts/v13-LANEEXEC-contract-v1.schema.json``, read here only through the packaged
copy :func:`phase_loop_runtime.launch_process_contract.schema_bytes`):

* the L-S7 route mapping (:func:`route_refusal`), with the ``x-client-routes`` writer routes
  and the ``x-activation`` values decoded by :mod:`phase_loop_runtime.launch_settings`;
* template registration (:func:`register_templates`), the one registration function: the
  ``x-argv-templates.template_hash_rule`` bytes, the record and slot rules, image links, and
  for agent-toolkit the ``x-contract-pins.toolkit_pins`` manifest, role and closure checks
  (obligation C2), plus the frozen pi-runner forms, the local one in its
  LANEEXEC-v1-errata-1 form;
* template selection and argv expansion (:func:`select_template`, :func:`expand_argv`).

Nothing here starts a process, reads a snapshot, uploads, or builds an envelope. Registration
reads host files only through :class:`HostFiles` (no-follow, read-only), and only for a local
template's executable chain, read-only trees and host symlinks. Every refusal is
:class:`TemplateRefused` with code ``sandbox_launch_template_refused`` and one closed
``reason``; no input value reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
import os
import posixpath
import re
import stat
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

import rfc8785

from .launch_process_contract import Command, TemplateSummary, schema_bytes
from .launch_settings import ImageEntry, LaunchSettings
from .openshell_artifacts import Refused as _PathRefused, safe_path

__all__ = [
    "PI_RUNNER_TEMPLATE_IDS",
    "PI_RUNNER_POLICY_VECTORS",
    "ROUTE_TABLE",
    "TEMPLATE_CODE",
    "HostFiles",
    "RegisteredTemplate",
    "TemplateRefused",
    "TemplateRegistry",
    "ToolkitManifest",
    "ToolkitPin",
    "FixtureImageRuntime",
    "check_toolkit_manifest",
    "expand_argv",
    "frozen_pi_runner_template",
    "manifest_digest_argument",
    "pi_policy_refusal",
    "recheck_template",
    "register_templates",
    "relay_endpoint_argument",
    "route_refusal",
    "select_template",
    "template_summaries",
]

TEMPLATE_CODE = "sandbox_launch_template_refused"
_ROUTE_DISABLED = "sandbox_launch_route_disabled"
_LOCAL_INTERIM = "sandbox_launch_local_route_interim"
_WRITER_ROUTE = "sandbox_launch_writer_route_refused"
_REFUSED = "sandbox_launch_refused"
_INPUT_MISMATCH = "sandbox_launch_input_mismatch"

#: ``x-argv-templates.pi_runner_templates.rule``: one template per supported target kind.
PI_RUNNER_TEMPLATE_IDS: Mapping[str, str] = MappingProxyType({
    "openshell": "pi-runner.openshell.v1", "local": "pi-runner.local.v1",
})
#: ``x-launch-inputs.binding``: the PLACECLI v1 pi-runner target binding.
PI_RUNNER_POLICY_VECTORS: Mapping[str, str] = MappingProxyType({
    "openshell": "full-remote-pi-runner", "local": "minimal-without-app",
})

#: ``x-client-routes``: (client, workload) -> (action, result_kind) of its one writer route.
_CLIENT_ROUTES: Mapping[tuple[str, str], tuple[str, str]] = MappingProxyType({
    ("agent-toolkit", "pi-runner"): ("execution", "none"),
    ("agent-harness", "implementation"): ("execution", "patch"),
    ("agent-harness", "leg"): ("review", "result"),
    ("agent-harness", "qualification"): ("review", "result"),
})

#: Binding §3 L-S7, as a closed table: (workload, target_kind) -> the activation that governs
#: it. ``lane_placement`` and ``local_pi_runner_launcher`` are ``x-activation`` values,
#: ``route`` is a ``launch_settings.REMOTE_ROUTES`` key, and ``never`` is always disabled.
ROUTE_TABLE: Mapping[tuple[str, str], str] = MappingProxyType({
    ("implementation", "local"): "lane_placement",
    ("pi-runner", "local"): "local_pi_runner_launcher",
    ("pi-runner", "openshell"): "route",
    ("leg", "openshell"): "route",
    ("qualification", "openshell"): "route",
    ("leg", "local"): "never",
    ("qualification", "local"): "never",
})

_RECORD_MEMBERS = ("template_id", "workload", "target_kind", "policy_vectors", "action",
                   "result_kinds", "image_digest", "argv", "executable_chain", "ro_trees",
                   "image_links", "link", "environment_policy", "references",
                   "max_timeout_seconds", "result_schema_id")
_WORKLOADS = ("leg", "qualification", "implementation", "pi-runner")
_POLICY_VECTORS = ("minimal-with-app", "minimal-without-app", "full-remote-pi-runner")
_ACTIONS = ("execution", "review")
_RESULT_KINDS = ("patch", "result", "none")
_TEMPLATE_ID = re.compile(r"[a-z][a-z0-9._-]{0,63}")
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
#: ``x-argv-templates.slots``, with the target kinds each is valid for.
_SLOTS: Mapping[str, frozenset[str]] = MappingProxyType({
    "tree": frozenset({"local", "openshell"}),
    "tree_dest": frozenset({"local"}),
    "home": frozenset({"local", "openshell"}),
    "out": frozenset({"local", "openshell"}),
    "scratch": frozenset({"local", "openshell"}),
    "run_id": frozenset({"local", "openshell"}),
    "relay_port": frozenset({"openshell"}),
    "relay_endpoint": frozenset({"openshell"}),
    "manifest": frozenset({"openshell"}),
    "manifest_digest": frozenset({"openshell"}),
})
#: ``x-argv-templates.pi_runner_templates.local.argv_rule``: the host symlinks, in order.
_HOST_SYMLINKS = ("/bin", "/sbin", "/lib32", "/lib64")
#: The fixed mounts of the frozen local pi-runner argv (``argv_rule``) and the host symlink
#: links. A read-only tree bind at, under or above one of them could replace it, the
#: LANEEXEC-v1-errata-1 ``/var/log`` empty read-only directory included, so it refuses.
_PROTECTED_MOUNTS = ("/proc", "/dev", "/tmp", "/etc", "/lib", "/usr", "/var/log") + _HOST_SYMLINKS
#: Reasons that are a ``x-contract-pins.toolkit_pins`` check failure (``file_check`` and the
#: closure): any of them leaves the whole agent-toolkit registry unregistered (``when``).
_TOOLKIT_INTEGRITY = frozenset({"file_mismatch", "file_unlisted", "closure_mismatch"})
_MAX_ARGV = 512
_MAX_CHAIN = 16
_MAX_TREES = 32
_MAX_TREE_ENTRIES = 500000
_READ_CHUNK = 1 << 20
_TOOLKIT_SCHEMA = "toolkit_pins.v1"
_CLOSURE_PREFIX = "remote_inner_closure:"
#: ``x-contract-pins.toolkit_pins.remote_inner_closure``: the named roles of the closure.
_CLOSURE_ROLES = frozenset({"toolkit_remote_inner", "toolkit_link", "toolkit_exec_clean",
                            "toolkit_landlock_manifest", "snapshot_limits_reference",
                            "writer_snapshot_reference"})


class TemplateRefused(Exception):
    """A template refusal, ``sandbox_launch_template_refused``, with one closed reason."""

    code = TEMPLATE_CODE

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    def __str__(self) -> str:
        return self.code


# -- the frozen wire artifact ---------------------------------------------------------------

@lru_cache(maxsize=1)
def _contract() -> Mapping[str, Any]:
    return json.loads(schema_bytes())


def frozen_pi_runner_template(target_kind: str) -> Mapping[str, Any]:
    """``x-argv-templates.pi_runner_templates.<target_kind>`` as frozen (errata-1 for local)."""
    return _contract()["x-argv-templates"]["pi_runner_templates"][target_kind]


@dataclass(frozen=True)
class ToolkitPin:
    """``x-contract-pins.toolkit_pins`` and its required roles (role -> manifest path).

    The production pin is :meth:`from_contract`. A test configuration may pin a fixture
    manifest so a case reaches its own check past the digest (obligation C2).
    """

    toolkit_commit: str
    sha256: str
    byte_length: int
    roles: Mapping[str, str]

    @classmethod
    def from_contract(cls) -> "ToolkitPin":
        return _contract_pin()


@lru_cache(maxsize=1)
def _contract_pin() -> ToolkitPin:
    pins = _contract()["x-contract-pins"]
    pin = pins["toolkit_pins"]
    roles = {name: entry["path"] for name, entry in pins.items()
             if isinstance(entry, dict) and entry.get("pinned_by") == "toolkit_pins"}
    return ToolkitPin(pin["toolkit_commit"], pin["sha256"], pin["byte_length"],
                      MappingProxyType(roles))


# -- strict JSON bytes ----------------------------------------------------------------------

class _Duplicate(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _Duplicate()
        out[key] = value
    return out


def _reject_constant(_: str) -> Any:
    raise ValueError()


def _canonical_object(raw: bytes, not_json: str, not_canonical: str) -> dict[str, Any]:
    """Parse strictly and require ``raw`` to be the RFC 8785 serialization of the value."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                           parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise TemplateRefused(not_json) from None
    if not isinstance(value, dict):
        raise TemplateRefused(not_json)
    try:
        canonical = rfc8785.dumps(value)
    except Exception:  # noqa: BLE001 - any value RFC 8785 cannot serialize refuses
        raise TemplateRefused(not_canonical) from None
    if canonical != raw:
        raise TemplateRefused(not_canonical)
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


# -- the toolkit pins manifest --------------------------------------------------------------

@dataclass(frozen=True)
class ToolkitManifest:
    """An accepted ``toolkit_pins.v1`` manifest: path -> sha256, role -> path, the closure."""

    sha256: str
    files: Mapping[str, str]
    roles: Mapping[str, str]
    closure: frozenset[str]


def check_toolkit_manifest(raw: bytes, pin: ToolkitPin | None = None) -> ToolkitManifest:
    """``x-contract-pins.toolkit_pins.manifest_check`` and ``role_mapping``, in that order."""
    pin = pin or ToolkitPin.from_contract()
    if len(raw) != pin.byte_length:
        raise TemplateRefused("manifest_length")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pin.sha256:
        raise TemplateRefused("manifest_digest")
    document = _canonical_object(raw, "manifest_not_json", "manifest_not_canonical")
    if set(document) != {"schema", "toolkit_commit", "files"} or document["schema"] != _TOOLKIT_SCHEMA:
        raise TemplateRefused("manifest_schema")
    if document["toolkit_commit"] != pin.toolkit_commit:
        raise TemplateRefused("manifest_commit")
    files = document["files"]
    if not isinstance(files, list):
        raise TemplateRefused("manifest_schema")
    for entry in files:
        if (not isinstance(entry, dict) or set(entry) != {"path", "role", "sha256"}
                or not all(isinstance(entry[key], str) for key in ("path", "role", "sha256"))):
            raise TemplateRefused("manifest_entry_malformed")
        if not _HEX64.fullmatch(entry["sha256"]):
            raise TemplateRefused("manifest_hash_malformed")
    paths = [entry["path"].encode("utf-8") for entry in files]
    if paths != sorted(paths):
        raise TemplateRefused("manifest_unsorted")
    if len(set(paths)) != len(paths):
        raise TemplateRefused("manifest_duplicate_path")
    roles_seen = [entry["role"] for entry in files]
    if len(set(roles_seen)) != len(roles_seen):
        raise TemplateRefused("role_duplicated")
    by_role = {entry["role"]: entry["path"] for entry in files}
    for role, path in pin.roles.items():
        if role not in by_role:
            raise TemplateRefused("role_missing")
        if by_role[role] != path:
            raise TemplateRefused("role_path")
    for role, path in by_role.items():
        if role in pin.roles:
            continue
        if not role.startswith(_CLOSURE_PREFIX) or role[len(_CLOSURE_PREFIX):] != path:
            raise TemplateRefused("role_unknown")
    closure = frozenset(path for role, path in by_role.items()
                        if role in _CLOSURE_ROLES or role.startswith(_CLOSURE_PREFIX))
    return ToolkitManifest(digest, MappingProxyType({e["path"]: e["sha256"] for e in files}),
                           MappingProxyType(by_role), closure)


# -- host files (local registration only) ---------------------------------------------------

class HostFiles:
    """Read-only, no-follow access to the host files a local template binds.

    ``root`` maps every absolute template path below it (``/`` in production); tests pass a
    private directory. Nothing is executed and nothing is written.
    """

    def __init__(self, root: str = "/") -> None:
        self._root = root

    def _host(self, path: str) -> str:
        return os.path.join(self._root, path.lstrip("/"))

    def sha256(self, path: str) -> str | None:
        """The SHA-256 of a regular file's bytes; ``None`` when absent, a link or special."""
        try:
            fd = os.open(self._host(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        except OSError:
            return None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            digest = hashlib.sha256()
            while chunk := os.read(fd, _READ_CHUNK):
                digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None
        finally:
            os.close(fd)

    def readlink(self, path: str) -> str | None:
        try:
            return os.readlink(self._host(path))
        except OSError:
            return None

    def resolve(self, path: str) -> str | None:
        """``path`` with every symlink component resolved inside this host view, as the
        kernel would; a missing component ends resolution lexically. ``None`` on a loop."""
        parts = [part for part in path.split("/") if part]
        resolved: list[str] = []
        hops = 0
        while parts:
            name = parts.pop(0)
            if name == ".":
                continue
            if name == "..":
                if resolved:
                    resolved.pop()
                continue
            target = self.readlink("/" + "/".join(resolved + [name]))
            if target is None:
                resolved.append(name)
                continue
            hops += 1
            if hops > 40:
                return None
            if target.startswith("/"):
                resolved = []
            parts = [part for part in target.split("/") if part] + parts
        return "/" + "/".join(resolved)

    def tree_rows(self, path: str) -> list[list[str]] | None:
        """The ``rfc8785_tree_manifest`` rows ``[path, kind, sha256]`` of a directory, ``.git``
        at its top excluded and directories implied, as the envelope defines them; ``None``
        for a missing tree, a special file or an unreadable entry."""
        rows: list[list[str]] = []
        try:
            top = os.open(self._host(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError:
            return None
        stack = [(top, "")]
        try:
            while stack:
                dir_fd, prefix = stack.pop()
                try:
                    for name in sorted(os.listdir(dir_fd)):
                        if not prefix and name == ".git":
                            continue
                        if len(rows) >= _MAX_TREE_ENTRIES:
                            return None
                        rel = prefix + name
                        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            stack.append((os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                                                  | os.O_CLOEXEC, dir_fd=dir_fd), rel + "/"))
                        elif stat.S_ISLNK(info.st_mode):
                            target = os.fsencode(os.readlink(name, dir_fd=dir_fd))
                            rows.append([rel, "symlink", hashlib.sha256(target).hexdigest()])
                        elif stat.S_ISREG(info.st_mode):
                            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
                            digest = hashlib.sha256()
                            try:
                                while chunk := os.read(file_fd, _READ_CHUNK):
                                    digest.update(chunk)
                            finally:
                                os.close(file_fd)
                            kind = "executable_file" if info.st_mode & 0o111 else "file"
                            rows.append([rel, kind, digest.hexdigest()])
                        else:
                            return None
                finally:
                    os.close(dir_fd)
        except OSError:
            return None
        finally:
            for dir_fd, _ in stack:
                os.close(dir_fd)
        rows.sort(key=lambda row: row[0].encode("utf-8"))
        return rows


def _tree_sha256(rows: Sequence[Sequence[str]]) -> str:
    return hashlib.sha256(rfc8785.dumps([list(row) for row in rows])).hexdigest()


# -- records --------------------------------------------------------------------------------

@dataclass(frozen=True)
class RegisteredTemplate:
    """One registered template: its exact bytes, ``template_sha256`` and frozen record."""

    raw: bytes = field(repr=False)
    template_sha256: str
    record: Mapping[str, Any] = field(repr=False)

    @property
    def template_id(self) -> str:
        return self.record["template_id"]

    @property
    def workload(self) -> str:
        return self.record["workload"]

    @property
    def target_kind(self) -> str:
        return self.record["target_kind"]


@dataclass(frozen=True)
class TemplateRegistry:
    """The registry of one client: registered templates by id, and the refusals by position."""

    client: str
    templates: Mapping[str, RegisteredTemplate]
    refused: Mapping[int, str]
    toolkit: ToolkitManifest | None


def _require(condition: bool, reason: str = "record_invalid") -> None:
    if not condition:
        raise TemplateRefused(reason)


def _absolute_normalized(path: object) -> bool:
    """Absolute, no '.' or '..' segment, no empty segment, no trailing slash."""
    if not isinstance(path, str) or not path.startswith("/") or path == "/" or "\x00" in path:
        return False
    return all(part not in ("", ".", "..") for part in path[1:].split("/"))


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _check_record_shape(record: Mapping[str, Any]) -> None:
    _require(tuple(sorted(record)) == tuple(sorted(_RECORD_MEMBERS)))
    _require(isinstance(record["template_id"], str) and bool(_TEMPLATE_ID.fullmatch(record["template_id"])))
    _require(record["workload"] in _WORKLOADS)
    _require(record["target_kind"] in ("local", "openshell"))
    vectors = record["policy_vectors"]
    _require(isinstance(vectors, list) and vectors and all(v in _POLICY_VECTORS for v in vectors)
             and len(set(vectors)) == len(vectors))
    _require(record["action"] in _ACTIONS)
    kinds = record["result_kinds"]
    _require(isinstance(kinds, list) and kinds and all(k in _RESULT_KINDS for k in kinds)
             and len(set(kinds)) == len(kinds))
    _require(isinstance(record["image_digest"], str) and bool(_SHA256_DIGEST.fullmatch(record["image_digest"])))
    argv = record["argv"]
    _require(isinstance(argv, list) and 0 < len(argv) <= _MAX_ARGV)
    for item in argv:
        if isinstance(item, dict):
            _require(set(item) == {"slot"} and isinstance(item["slot"], str), "slot_invalid")
        else:
            _require(isinstance(item, str) and "\x00" not in item)
    chain = record["executable_chain"]
    _require(isinstance(chain, list) and 0 < len(chain) <= _MAX_CHAIN)
    for entry in chain:
        _require(isinstance(entry, dict) and set(entry) == {"role", "locator_kind", "locator", "sha256"})
        _require(entry["role"] in ("wrapper", "worker") and entry["locator_kind"] == "declared")
        _require(_absolute_normalized(entry["locator"]))
        _require(isinstance(entry["sha256"], str) and bool(_HEX64.fullmatch(entry["sha256"])))
    _require([e["role"] for e in chain].count("worker") == 1 and chain[-1]["role"] == "worker")
    trees = record["ro_trees"]
    _require(isinstance(trees, list) and len(trees) <= _MAX_TREES)
    for tree in trees:
        _require(isinstance(tree, dict) and set(tree) == {"path", "tree_sha256"})
        _require(_absolute_normalized(tree["path"]))
        _require(isinstance(tree["tree_sha256"], str) and bool(_HEX64.fullmatch(tree["tree_sha256"])))
    _require(len({t["path"] for t in trees}) == len(trees))
    _require(isinstance(record["image_links"], list)
             and all(isinstance(link, str) for link in record["image_links"]))
    link = record["link"]
    if link is not None:
        _require(isinstance(link, dict) and set(link) == {"mode", "guest_port"})
        if link["mode"] == "listen":
            port = link["guest_port"]
            _require(type(port) is int and 0 < port < 65536 and record["target_kind"] == "openshell")
        else:
            _require(link["mode"] == "stdio" and link["guest_port"] is None
                     and record["target_kind"] == "local")
    _require(isinstance(record["environment_policy"], str) and 0 < len(record["environment_policy"]) <= 1024)
    refs = record["references"]
    _require(isinstance(refs, list) and len(refs) <= 16
             and all(isinstance(r, str) and 0 < len(r) <= 1024 for r in refs))
    timeout = record["max_timeout_seconds"]
    _require(type(timeout) is int and 0 < timeout <= 86400)
    schema_id = record["result_schema_id"]
    _require(schema_id is None or (isinstance(schema_id, str) and 0 < len(schema_id) <= 256))


def _check_slots(record: Mapping[str, Any]) -> None:
    """``x-argv-templates.rules``: a slot outside the slots, or not valid for the target, refuses."""
    listen = record["link"] is not None and record["link"]["mode"] == "listen"
    for item in record["argv"]:
        if not isinstance(item, dict):
            continue
        name = item["slot"]
        _require(name in _SLOTS and record["target_kind"] in _SLOTS[name], "slot_invalid")
        if name == "relay_endpoint":
            _require(listen, "slot_invalid")
        if name == "relay_port":
            _require(listen and record["workload"] == "leg", "slot_invalid")


def _check_image_links(record: Mapping[str, Any], trees: Iterable[str],
                       host: HostFiles | None = None) -> None:
    """``x-argv-templates.image_links``, at registration. On local the image path must also
    resolve, through every symlink of the host view, inside a resolved read-only tree."""
    links = record["image_links"]
    if record["workload"] != "pi-runner":
        _require(links == [], "image_link")
        return
    roots = list(trees)
    for link in links:
        _require(_absolute_normalized(link), "image_link")
        try:
            safe_path(link[1:])
        except _PathRefused:
            raise TemplateRefused("image_link") from None
        _require(any(_inside(link, root) for root in roots), "image_link")
        if host is not None:
            resolved = host.resolve(link)
            resolved_roots = [host.resolve(root) for root in roots]
            _require(resolved is not None and any(
                r is not None and _inside(resolved, r) for r in resolved_roots), "image_link")
    for i, link in enumerate(links):
        for j, other in enumerate(links):
            _require(i == j or not _inside(link, other), "image_link")


def _host_symlink_entries(host: HostFiles) -> list[str]:
    """``<host symlink entries>``: ``--symlink <target> <link>`` for each host link into /usr."""
    out: list[str] = []
    for link in _HOST_SYMLINKS:
        target = host.readlink(link)
        if target is None:
            continue
        lexical = posixpath.normpath(posixpath.join("/", target))
        resolved = host.resolve(link)
        if (resolved is not None and _inside(lexical, "/usr") and _inside(resolved, "/usr")
                and host.resolve("/usr") == "/usr"):
            out.extend(["--symlink", target, link])
    return out


def _expected_pi_argv(record: Mapping[str, Any], host: HostFiles | None) -> list[Any]:
    """The frozen pi-runner argv with its per-registration values filled in."""
    frozen = frozen_pi_runner_template(record["target_kind"])
    chain = record["executable_chain"]
    fills: dict[str, list[Any]] = {"<node>": [chain[1]["locator"]], "<remote_inner>": [chain[2]["locator"]]}
    if record["target_kind"] == "local":
        assert host is not None
        fills["<host symlink entries>"] = _host_symlink_entries(host)
        binds: list[Any] = []
        for tree in record["ro_trees"]:
            binds.extend(["--ro-bind", tree["path"], tree["path"]])
        fills["<ro_trees binds>"] = binds
    out: list[Any] = []
    for token in frozen["argv"]:
        if isinstance(token, str) and token in fills:
            out.extend(fills[token])
        else:
            out.append(_thaw(token) if isinstance(token, Mapping) else token)
    return out


def _check_pi_form(record: Mapping[str, Any], host: HostFiles | None) -> None:
    """The frozen pi-runner template of ``x-argv-templates.pi_runner_templates``."""
    kind = record["target_kind"]
    frozen = frozen_pi_runner_template(kind)
    _require(record["template_id"] == PI_RUNNER_TEMPLATE_IDS[kind], "pi_form")
    for name in ("policy_vectors", "result_kinds", "link"):
        _require(record[name] == _thaw(frozen[name]), "pi_form")
    for name in ("action", "max_timeout_seconds", "result_schema_id"):
        _require(record[name] == frozen[name], "pi_form")
    if kind == "openshell":
        _require(record["ro_trees"] == [], "pi_form")
    else:
        _require(record["references"] == [], "pi_form")
        assert host is not None
        for tree in record["ro_trees"]:
            for path in (tree["path"], host.resolve(tree["path"])):
                _require(path is not None and not any(
                    _inside(path, mount) or _inside(mount, path) for mount in _PROTECTED_MOUNTS),
                    "tree_protected")
    chain = record["executable_chain"]
    _require([e["role"] for e in chain] == [e["role"] for e in frozen["executable_chain"]], "pi_form")
    _require(chain[0]["locator"] == frozen["executable_chain"][0]["locator"], "pi_form")
    _require(record["argv"] == _expected_pi_argv(record, host), "argv_form")


def _check_local_trees(record: Mapping[str, Any], host: HostFiles) -> dict[str, list[list[str]]]:
    """Read-only tree digests against the host bytes; returns each tree's rows."""
    rows_by_tree: dict[str, list[list[str]]] = {}
    for tree in record["ro_trees"]:
        rows = host.tree_rows(tree["path"])
        _require(rows is not None and _tree_sha256(rows) == tree["tree_sha256"], "tree_mismatch")
        rows_by_tree[tree["path"]] = rows  # type: ignore[assignment]
    return rows_by_tree


def _check_local_chain(record: Mapping[str, Any], host: HostFiles) -> None:
    """Chain digests against the host bytes."""
    for entry in record["executable_chain"]:
        _require(host.sha256(entry["locator"]) == entry["sha256"], "chain_mismatch")
    if record["workload"] == "pi-runner":
        # node and remote_inner: absolute paths inside an ro_trees entry.
        for entry in record["executable_chain"][1:]:
            _require(any(_inside(entry["locator"], t["path"]) for t in record["ro_trees"]), "pi_form")


def _check_toolkit_local(record: Mapping[str, Any], manifest: ToolkitManifest,
                         rows_by_tree: Mapping[str, list[list[str]]]) -> None:
    """``file_check`` and the local bound closure of ``remote_inner_closure``."""
    worker = record["executable_chain"][-1]
    remote_inner = manifest.roles["toolkit_remote_inner"]
    _require(worker["sha256"] == manifest.files[remote_inner], "file_mismatch")
    toolkit = next((t["path"] for t in record["ro_trees"]
                    if worker["locator"] == t["path"].rstrip("/") + "/" + remote_inner), None)
    _require(toolkit is not None, "closure_mismatch")
    for entry in record["executable_chain"]:
        if _inside(entry["locator"], toolkit):  # type: ignore[arg-type]
            rel = entry["locator"][len(toolkit.rstrip("/")) + 1:]  # type: ignore[union-attr]
            _require(rel in manifest.files, "file_unlisted")
            _require(entry["sha256"] == manifest.files[rel], "file_mismatch")
    bound = {row[0]: row[2] for row in rows_by_tree[toolkit]}  # type: ignore[index]
    for path, digest in bound.items():
        _require(path in manifest.files, "file_unlisted")
        _require(digest == manifest.files[path], "file_mismatch")
    _require(set(bound) == set(manifest.closure), "closure_mismatch")


#: A test-only source of an openshell image's runtime record (see :func:`register_templates`).
FixtureImageRuntime = Callable[[ImageEntry], "Mapping[str, Any] | None"]


def _runtime_record(value: object) -> Mapping[str, Any]:
    """The normalized runtime record a test fixture supplies, checked for shape:
    ``{"version": 3, "helper": {"path", "version", "sha256"}, "node": {"path", "sha256"},
    "launcher": {"path", "files": {<manifest path>: <hex sha256>}}, "trees": [<image path>]}``.
    """
    def closed(item: object, keys: set[str]) -> Mapping[str, Any]:
        _require(isinstance(item, Mapping) and set(item) == keys, "image_unregistered")
        return item  # type: ignore[return-value]

    def hex64(item: object) -> bool:
        return isinstance(item, str) and bool(_HEX64.fullmatch(item))

    record = closed(value, {"version", "helper", "node", "launcher", "trees"})
    helper = closed(record["helper"], {"path", "version", "sha256"})
    node = closed(record["node"], {"path", "sha256"})
    launcher = closed(record["launcher"], {"path", "files"})
    files = launcher["files"]
    _require(type(record["version"]) is int and record["version"] == 3
             and helper["path"] == frozen_pi_runner_template("openshell")["executable_chain"][0]["locator"]
             and type(helper["version"]) is int and helper["version"] == 1 and hex64(helper["sha256"])
             and _absolute_normalized(node["path"]) and hex64(node["sha256"])
             and _absolute_normalized(launcher["path"])
             and isinstance(files, Mapping) and 0 < len(files) <= 512
             and all(isinstance(k, str) and not k.startswith("/") and _absolute_normalized("/" + k)
                     and hex64(v) for k, v in files.items())
             and isinstance(record["trees"], (list, tuple))
             and all(_absolute_normalized(t) for t in record["trees"]), "image_unregistered")
    return record


def _check_openshell_image(record: Mapping[str, Any], settings: LaunchSettings,
                           manifest: ToolkitManifest | None,
                           fixture_image_runtime: FixtureImageRuntime | None) -> list[str]:
    """Chain digests against the registered image's runtime record; returns its trees.

    Production registration has no source for the node path, node digest, helper digest
    and launcher closure that ``x-argv-templates.pi_runner_templates`` reads from the
    registered image's runtime manifest: the pinned toolkit's RUNTIME_VERSION 3 manifest
    does not record them in that form, and no reviewed, image-bound evidence supplies them
    yet. So without the test-only fixture seam every openshell template refuses
    ``runtime_unavailable`` (routes are ``sandbox_launch_route_disabled`` anyway).
    """
    image = settings.image(record["workload"], "openshell", record["image_digest"])
    _require(image is not None, "image_unregistered")
    _require(fixture_image_runtime is not None, "runtime_unavailable")
    runtime = _runtime_record(fixture_image_runtime(image))  # type: ignore[misc, arg-type]
    launcher_root = runtime["launcher"]["path"].rstrip("/")
    chain = record["executable_chain"]
    if record["workload"] == "pi-runner":
        assert manifest is not None
        remote_inner = manifest.roles["toolkit_remote_inner"]
        _require(chain[2]["sha256"] == manifest.files[remote_inner], "file_mismatch")
        recorded = runtime["launcher"]["files"]
        for path, digest in recorded.items():
            _require(path in manifest.files, "file_unlisted")
            _require(digest == manifest.files[path], "file_mismatch")
        _require(set(recorded) == set(manifest.closure), "closure_mismatch")
        _require(chain[1]["locator"] == runtime["node"]["path"], "chain_mismatch")
        _require(chain[2]["locator"] == launcher_root + "/" + remote_inner, "chain_mismatch")
    known = {runtime["helper"]["path"]: runtime["helper"]["sha256"],
             runtime["node"]["path"]: runtime["node"]["sha256"]}
    for rel, digest in runtime["launcher"]["files"].items():
        known[launcher_root + "/" + rel] = digest
    for entry in chain:
        _require(known.get(entry["locator"]) == entry["sha256"], "chain_mismatch")
    return list(runtime["trees"])


def _register_one(raw: bytes, settings: LaunchSettings, manifest: ToolkitManifest | None,
                  host: HostFiles, fixture_image_runtime: FixtureImageRuntime | None) -> RegisteredTemplate:
    record = _canonical_object(raw, "record_bytes", "record_bytes")
    _check_record_shape(record)
    _check_slots(record)
    pi = record["workload"] == "pi-runner"
    _require(pi == (record["template_id"] in PI_RUNNER_TEMPLATE_IDS.values()), "pi_form")
    if pi:
        _require(settings.client == "agent-toolkit" and manifest is not None, "pi_form")
        _check_pi_form(record, host if record["target_kind"] == "local" else None)
    if record["target_kind"] == "local":
        rows_by_tree = _check_local_trees(record, host)
        if pi:
            _check_toolkit_local(record, manifest, rows_by_tree)  # type: ignore[arg-type]
        _check_local_chain(record, host)
        trees = [t["path"] for t in record["ro_trees"]]
        _check_image_links(record, trees, host)
    else:
        trees = _check_openshell_image(record, settings, manifest, fixture_image_runtime)
        _check_image_links(record, trees)
    return RegisteredTemplate(raw, hashlib.sha256(raw).hexdigest(), _freeze(record))


def register_templates(settings: LaunchSettings, *, host: HostFiles | None = None,
                       pin: ToolkitPin | None = None,
                       fixture_image_runtime: FixtureImageRuntime | None = None) -> TemplateRegistry:
    """Register one client's template registry (``x-argv-templates``, obligation C2).

    For agent-toolkit the toolkit pins manifest is checked first. A manifest failure, a
    missing manifest, or a toolkit file or closure failure of any template
    (``x-contract-pins.toolkit_pins.when``) leaves the whole registry unregistered, so every
    launch naming one of its templates refuses at the template step. Any other failure
    leaves only that template unregistered. Two templates with one id are both unregistered.

    ``fixture_image_runtime`` is a test-only seam that supplies an openshell image's
    normalized runtime record; production callers never pass it, so production openshell
    registration stays closed (``runtime_unavailable``).
    """
    host = host or HostFiles()
    manifest: ToolkitManifest | None = None
    count = len(settings.templates)
    if settings.client == "agent-toolkit" and count:
        try:
            if settings.toolkit_pins is None:
                raise TemplateRefused("pins_missing")
            manifest = check_toolkit_manifest(settings.toolkit_pins.encode("utf-8"), pin)
        except TemplateRefused as refusal:
            return TemplateRegistry(settings.client, MappingProxyType({}),
                                    MappingProxyType({i: refusal.reason for i in range(count)}), None)
    registered: dict[int, RegisteredTemplate] = {}
    refused: dict[int, str] = {}
    for index, text in enumerate(settings.templates):
        try:
            registered[index] = _register_one(text.encode("utf-8"), settings, manifest, host,
                                              fixture_image_runtime)
        except TemplateRefused as refusal:
            refused[index] = refusal.reason
    if settings.client == "agent-toolkit" and _TOOLKIT_INTEGRITY & set(refused.values()):
        reasons = {i: refused.get(i, "toolkit_unregistered") for i in range(count)}
        return TemplateRegistry(settings.client, MappingProxyType({}),
                                MappingProxyType(reasons), None)
    ids = [t.template_id for t in registered.values()]
    for index, template in list(registered.items()):
        if ids.count(template.template_id) > 1:
            refused[index] = "duplicate_template"
            del registered[index]
    return TemplateRegistry(
        settings.client,
        MappingProxyType({t.template_id: t for t in registered.values()}),
        MappingProxyType(dict(sorted(refused.items()))),
        manifest,
    )


def recheck_template(template: RegisteredTemplate, registry: TemplateRegistry,
                     settings: LaunchSettings, *, host: HostFiles | None = None,
                     pin: ToolkitPin | None = None,
                     fixture_image_runtime: FixtureImageRuntime | None = None) -> None:
    """``recheck_before_start``: recompute every digest registration checked.

    Refuses when the template's bytes, the toolkit manifest bytes, a chain or tree digest or
    a closure file differs from what registration accepted.
    """
    again = register_templates(settings, host=host, pin=pin, fixture_image_runtime=fixture_image_runtime)
    current = again.templates.get(template.template_id)
    if current is None or current.template_sha256 != template.template_sha256:
        raise TemplateRefused("recheck_mismatch")
    before = None if registry.toolkit is None else registry.toolkit.sha256
    after = None if again.toolkit is None else again.toolkit.sha256
    if before != after:
        raise TemplateRefused("recheck_mismatch")


# -- route mapping and selection -------------------------------------------------------------

def route_refusal(settings: LaunchSettings, *, client: str, workload: str, action: str,
                  result_kind: str, target_kind: str) -> str | None:
    """The L-S7 route mapping as a closed function; ``None`` means the route may proceed.

    Order: the ``x-client-routes`` client/workload pairing (``sandbox_launch_refused``), the
    writer route (``sandbox_launch_writer_route_refused``), then the activation that governs
    ``(workload, target_kind)``. Openshell routes additionally pass the activation check of
    ``sandbox_placement.openshell_launch_refusal`` at the launch entry point (binding §6 E2-2).
    """
    route = _CLIENT_ROUTES.get((client, workload))
    if route is None or settings.client != client:
        return _REFUSED
    if route != (action, result_kind):
        return _WRITER_ROUTE
    governed = ROUTE_TABLE.get((workload, target_kind))
    if governed == "lane_placement":
        return None if settings.lane_placement == "enabled" else _ROUTE_DISABLED
    if governed == "local_pi_runner_launcher":
        return None if settings.local_pi_runner_launcher == "laneexec" else _LOCAL_INTERIM
    if governed == "route":
        return None if settings.route_enabled(workload, target_kind) else _ROUTE_DISABLED
    return _ROUTE_DISABLED


def pi_policy_refusal(workload: str, target_kind: str, policy_vector: str) -> str | None:
    """``x-launch-inputs.binding``: a crossed pi-runner policy/target pair refuses
    ``sandbox_launch_input_mismatch`` before template resolution."""
    if workload != "pi-runner":
        return None
    return None if PI_RUNNER_POLICY_VECTORS.get(target_kind) == policy_vector else _INPUT_MISMATCH


def select_template(registry: TemplateRegistry, command: Command, *, workload: str,
                    target_kind: str, policy_vector: str, action: str, result_kind: str,
                    image_digest: str) -> RegisteredTemplate:
    """``x-argv-templates.rules``: resolve the named template or refuse before any effect."""
    if workload == "pi-runner" and command.template_id != PI_RUNNER_TEMPLATE_IDS.get(target_kind):
        raise TemplateRefused("template_target")
    template = registry.templates.get(command.template_id)
    if template is None:
        raise TemplateRefused("template_unregistered")
    if command.template_sha256 != template.template_sha256:
        raise TemplateRefused("template_digest")
    record = template.record
    if (record["workload"] != workload or record["target_kind"] != target_kind
            or policy_vector not in record["policy_vectors"] or record["action"] != action
            or result_kind not in record["result_kinds"] or record["image_digest"] != image_digest):
        raise TemplateRefused("template_unregistered")
    return template


def relay_endpoint_argument(template: RegisteredTemplate) -> str:
    """``x-argv-templates.slots.relay_endpoint``: ``127.0.0.1:<guest_port>``."""
    link = template.record["link"]
    if link is None or link["mode"] != "listen":
        raise ValueError("relay_endpoint_unavailable")
    return f"127.0.0.1:{link['guest_port']}"


def manifest_digest_argument(manifest_bytes: bytes) -> str:
    """``x-argv-templates.slots.manifest_digest``: ``sha256:<64 lowercase hex>``."""
    return "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()


def expand_argv(template: RegisteredTemplate, values: Mapping[str, str]) -> tuple[str, ...]:
    """Expand the template's argv: literals unchanged, each slot exactly one argument.

    ``values`` come only from LaneExec. A slot without a value, or a value that is empty or
    holds NUL, raises ``ValueError`` (a LaneExec defect, never a client input).
    """
    out: list[str] = []
    for item in template.record["argv"]:
        if isinstance(item, Mapping):
            value = values.get(item["slot"])
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError("slot_value_invalid")
            out.append(value)
        else:
            out.append(item)
    return tuple(out)


def template_summaries(registry: TemplateRegistry) -> list[TemplateSummary]:
    """The registered templates as ``version`` reports them, sorted by id."""
    return [TemplateSummary(t.template_id, t.template_sha256, t.workload)
            for _, t in sorted(registry.templates.items())]
