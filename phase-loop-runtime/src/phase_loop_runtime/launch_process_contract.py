"""The placement launch protocol v1: packaged schema, strict codec and typed records.

The schema is the frozen planning artifact ``plans/artifacts/v13-LANEEXEC-contract-v1.schema.json``
(erratum LANEEXEC-v1-errata-1), shipped byte for byte as package data at
``contracts/placement/launch-v1.schema.json`` and read through :mod:`importlib.resources`.
Its SHA-256 is the wire identity (``LaunchVersionResponse.protocol_schema_sha256``) a client
checks with ``version``.

The launch schema reuses the placement process protocol v1 definitions (``Reservation``,
``RequestId``, ``CallerContext`` and the rest) by that schema's ``$id``. They resolve only
against the packaged ``process-v1.schema.json`` registered under its ``$id``; nothing is
fetched, so an unresolvable reference fails closed.

Decoding is side-effect free. Input bytes are captured once and checked under the PLACECLI v1
strictness rules of ``x-cli.input`` (UTF-8, one JSON object, no duplicate keys, no non-finite
or unsafe numbers, no trailing data, at most 65536 bytes), validated against the message
definition for the verb, and only then turned into immutable records. Every failure is a
:class:`~phase_loop_runtime.placement_process_contract.ProtocolError` (exit class 70) whose
``code`` is one closed diagnostic; no input value, exception chain or path reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
from importlib import resources
import json
from types import MappingProxyType
from typing import Any, Mapping, Union

import jsonschema
import referencing
import referencing.exceptions
import referencing.jsonschema

from . import placement_process_contract as _placement
from .placement_process_contract import ProtocolError, Reservation

__all__ = [
    "CLIENTS",
    "PROTOCOL_EXIT",
    "REQUEST_VERBS",
    "SCHEMA_RESOURCE",
    "TERMINAL_STATUS_STATES",
    "VERBS",
    "CancelRequest",
    "CancelResponse",
    "Command",
    "InventoryCounts",
    "Instructions",
    "LaunchEvidence",
    "LaunchProcessRequest",
    "LaunchProcessResponse",
    "LaunchRequest",
    "LaunchResponse",
    "LaunchVersionResponse",
    "PrepareRequest",
    "PrepareResponse",
    "PreparedPaths",
    "ProtocolError",
    "ReturnDescriptor",
    "SeedDeclaration",
    "SeedEntry",
    "SeedLimits",
    "SeedManifest",
    "Snapshot",
    "SnapshotEvidence",
    "StatusRequest",
    "StatusResponse",
    "TemplateSummary",
    "Termination",
    "decode_launch_request",
    "decode_launch_response",
    "encode_launch_response",
    "launch_exit_class",
    "protocol_schema_sha256",
    "schema_bytes",
    "validate_launch_message",
]

SCHEMA_RESOURCE = "contracts/placement/launch-v1.schema.json"
#: ``x-cli.argv``: the five verbs of ``agent-harness-launch``.
VERBS: tuple[str, ...] = ("prepare", "launch", "status", "cancel", "version")
#: The verbs that read one JSON object from stdin; ``version`` requires empty stdin.
REQUEST_VERBS: tuple[str, ...] = ("prepare", "launch", "status", "cancel")
#: ``x-cli.client_flag``: the same two clients as PLACECLI v1.
CLIENTS: tuple[str, ...] = _placement.CLIENTS
#: ``x-cli.exit_codes["70"]``: every :class:`ProtocolError`, stdout absent.
PROTOCOL_EXIT = 70
#: ``x-status-cancel.status``: the states whose StatusResponse nests the terminal LaunchResponse.
TERMINAL_STATUS_STATES: frozenset[str] = frozenset({"finished", "refused", "uncertain"})

_REQUEST_DEFS = MappingProxyType({
    "prepare": "PrepareRequest", "launch": "LaunchRequest",
    "status": "StatusRequest", "cancel": "CancelRequest",
})
_RESPONSE_DEFS = MappingProxyType({
    "prepare": "PrepareResponse", "launch": "LaunchResponse", "status": "StatusResponse",
    "cancel": "CancelResponse", "version": "LaunchVersionResponse",
})


# -- the packaged schema ------------------------------------------------------------------

@lru_cache(maxsize=1)
def schema_bytes() -> bytes:
    """The packaged launch protocol schema, exactly as shipped."""
    try:
        return resources.files(__package__).joinpath(SCHEMA_RESOURCE).read_bytes()
    except (OSError, ValueError):
        raise ProtocolError("schema_unavailable") from None


def protocol_schema_sha256() -> str:
    """``LaunchVersionResponse.protocol_schema_sha256``: lowercase hex of the packaged bytes."""
    return hashlib.sha256(schema_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _schema_document() -> Mapping[str, Any]:
    try:
        return json.loads(schema_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProtocolError("schema_unavailable") from None


@lru_cache(maxsize=1)
def _registry() -> referencing.Registry:
    """The packaged placement process v1 schema, registered under its own ``$id`` only."""
    try:
        placement = json.loads(_placement.schema_bytes().decode("utf-8"))
        resource = referencing.Resource.from_contents(
            placement, default_specification=referencing.jsonschema.DRAFT202012)
        return referencing.Registry().with_resource(placement["$id"], resource)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError,
            referencing.exceptions.CannotDetermineSpecification):
        raise ProtocolError("schema_unavailable") from None


@lru_cache(maxsize=None)
def _validator(definition: str) -> Any:
    document = dict(_schema_document())
    document.pop("oneOf", None)
    document["$ref"] = f"#/$defs/{definition}"
    # The placement codec's validator class and format checker: strict integers (no bool)
    # and RFC 3339 date-time, so both protocols apply one set of strictness rules.
    return _placement._Validator(  # noqa: SLF001 - one strictness definition for both codecs
        document, registry=_registry(), format_checker=_placement._FORMATS)  # noqa: SLF001


def _valid(definition: str, instance: object) -> bool:
    try:
        return _validator(definition).is_valid(instance)
    except (jsonschema.exceptions.SchemaError, referencing.exceptions.Unresolvable,
            RecursionError, TypeError, ValueError):
        return False


def validate_launch_message(definition: str, value: object) -> bool:
    """Whether ``value`` validates against ``$defs.<definition>`` of the packaged schema."""
    if not isinstance(definition, str) or definition not in _schema_document()["$defs"]:
        return False
    return _valid(definition, value)


# -- immutable records --------------------------------------------------------------------

def _context(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


def _optional(value: Any, record: Any) -> Any:
    return None if value is None else record.from_json(value)


def _json(value: Any) -> Any:
    return None if value is None else value.to_json()


@dataclass(frozen=True)
class PreparedPaths:
    """``$defs.PreparedPaths``: the attempt's run_id, scratch_path and tree_path (x-prepare)."""

    run_id: str
    scratch_path: str
    tree_path: str

    def to_json(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "scratch_path": self.scratch_path,
                "tree_path": self.tree_path}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "PreparedPaths":
        return cls(value["run_id"], value["scratch_path"], value["tree_path"])


@dataclass(frozen=True)
class Snapshot:
    root: str
    mode: str
    masks: tuple[str, ...]
    mask_dirs: tuple[str, ...]
    cwd: str

    def to_json(self) -> dict[str, Any]:
        return {"root": self.root, "mode": self.mode, "masks": list(self.masks),
                "mask_dirs": list(self.mask_dirs), "cwd": self.cwd}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "Snapshot":
        return cls(value["root"], value["mode"], tuple(value["masks"]),
                   tuple(value["mask_dirs"]), value["cwd"])


@dataclass(frozen=True)
class Instructions:
    """``$defs.Instructions``: ``none``, a snapshot ``path`` or ``inline`` base64."""

    source: str
    path: str | None = None
    base64: str | None = None

    def to_json(self) -> dict[str, Any]:
        if self.source == "snapshot":
            return {"source": "snapshot", "path": self.path}
        if self.source == "inline":
            return {"source": "inline", "base64": self.base64}
        return {"source": self.source}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "Instructions":
        return cls(value["source"], value.get("path"), value.get("base64"))


@dataclass(frozen=True)
class Command:
    template_id: str
    template_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {"template_id": self.template_id, "template_sha256": self.template_sha256}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "Command":
        return cls(value["template_id"], value["template_sha256"])


@dataclass(frozen=True)
class SeedDeclaration:
    manifest_sha256: str
    entries: int
    total_bytes: int

    def to_json(self) -> dict[str, Any]:
        return {"manifest_sha256": self.manifest_sha256, "entries": self.entries,
                "total_bytes": self.total_bytes}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "SeedDeclaration":
        return cls(value["manifest_sha256"], value["entries"], value["total_bytes"])


@dataclass(frozen=True)
class SeedEntry:
    """``$defs.SeedEntry``. ``executable`` is ``None`` when the member is absent (default false)."""

    relpath: str
    sha256: str
    size: int
    executable: bool | None = None

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {"relpath": self.relpath, "sha256": self.sha256, "size": self.size}
        if self.executable is not None:
            body["executable"] = self.executable
        return body

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "SeedEntry":
        return cls(value["relpath"], value["sha256"], value["size"], value.get("executable"))


@dataclass(frozen=True)
class SeedManifest:
    request_id: str
    entries: tuple[SeedEntry, ...]

    def to_json(self) -> dict[str, Any]:
        return {"schema": "laneexec.seed.manifest.v1", "request_id": self.request_id,
                "entries": [entry.to_json() for entry in self.entries]}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "SeedManifest":
        return cls(value["request_id"], tuple(SeedEntry.from_json(e) for e in value["entries"]))


@dataclass(frozen=True)
class SeedLimits:
    max_entries: int
    entry_max_bytes: int
    max_bytes: int
    manifest_max_bytes: int

    def to_json(self) -> dict[str, Any]:
        return {"max_entries": self.max_entries, "entry_max_bytes": self.entry_max_bytes,
                "max_bytes": self.max_bytes, "manifest_max_bytes": self.manifest_max_bytes}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "SeedLimits":
        return cls(value["max_entries"], value["entry_max_bytes"], value["max_bytes"],
                   value["manifest_max_bytes"])


@dataclass(frozen=True)
class Termination:
    """The pinned PLACECLI ``$defs.Termination``."""

    reason: str
    signal: str | None
    by: str

    def to_json(self) -> dict[str, Any]:
        return {"reason": self.reason, "signal": self.signal, "by": self.by}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "Termination":
        return cls(value["reason"], value["signal"], value["by"])


@dataclass(frozen=True)
class ReturnDescriptor:
    """``$defs.ReturnDescriptor``: names returned bytes; they never appear on stdout."""

    kind: str
    format: str
    path: str
    sha256: str
    byte_length: int
    base_commit: str | None

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "format": self.format, "path": self.path,
                "sha256": self.sha256, "byte_length": self.byte_length,
                "directory_mode": "0700", "file_mode": "0600", "base_commit": self.base_commit}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "ReturnDescriptor":
        return cls(value["kind"], value["format"], value["path"], value["sha256"],
                   value["byte_length"], value["base_commit"])


_COUNT_NAMES = ("tracked", "untracked", "ignored", "omitted", "masked", "special")


@dataclass(frozen=True)
class InventoryCounts:
    tracked: int
    untracked: int
    ignored: int
    omitted: int
    masked: int
    special: int

    def to_json(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in _COUNT_NAMES}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "InventoryCounts":
        return cls(**{name: value[name] for name in _COUNT_NAMES})


@dataclass(frozen=True)
class SnapshotEvidence:
    mode: str
    content_sha256: str
    base_commit: str | None
    input_commit: str | None
    overlay_sha256: str | None
    inventory_sha256: str
    masks_sha256: str
    counts: InventoryCounts
    byte_total: int

    def to_json(self) -> dict[str, Any]:
        return {"mode": self.mode, "content_sha256": self.content_sha256,
                "base_commit": self.base_commit, "input_commit": self.input_commit,
                "overlay_sha256": self.overlay_sha256, "inventory_sha256": self.inventory_sha256,
                "masks_sha256": self.masks_sha256, "counts": self.counts.to_json(),
                "byte_total": self.byte_total}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "SnapshotEvidence":
        return cls(value["mode"], value["content_sha256"], value["base_commit"],
                   value["input_commit"], value["overlay_sha256"], value["inventory_sha256"],
                   value["masks_sha256"], InventoryCounts.from_json(value["counts"]),
                   value["byte_total"])


@dataclass(frozen=True)
class LaunchEvidence:
    snapshot: SnapshotEvidence | None
    launch_digest: str | None
    template_sha256: str
    image_digest: str
    policy_digest: str
    egress_sha256: str
    transport_id: str
    caps_sha256: str | None
    bridge_attached: bool
    stdout_sha256: str | None
    stderr_sha256: str | None
    exit_status: int | None
    duration_ms: int
    renewals: int

    def to_json(self) -> dict[str, Any]:
        return {"snapshot": _json(self.snapshot), "launch_digest": self.launch_digest,
                "template_sha256": self.template_sha256, "image_digest": self.image_digest,
                "policy_digest": self.policy_digest, "egress_sha256": self.egress_sha256,
                "transport_id": self.transport_id, "caps_sha256": self.caps_sha256,
                "bridge_attached": self.bridge_attached, "stdout_sha256": self.stdout_sha256,
                "stderr_sha256": self.stderr_sha256, "exit_status": self.exit_status,
                "duration_ms": self.duration_ms, "renewals": self.renewals}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "LaunchEvidence":
        return cls(_optional(value["snapshot"], SnapshotEvidence), value["launch_digest"],
                   value["template_sha256"], value["image_digest"], value["policy_digest"],
                   value["egress_sha256"], value["transport_id"], value["caps_sha256"],
                   value["bridge_attached"], value["stdout_sha256"], value["stderr_sha256"],
                   value["exit_status"], value["duration_ms"], value["renewals"])


@dataclass(frozen=True)
class TemplateSummary:
    template_id: str
    template_sha256: str
    workload: str

    def to_json(self) -> dict[str, Any]:
        return {"template_id": self.template_id, "template_sha256": self.template_sha256,
                "workload": self.workload}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "TemplateSummary":
        return cls(value["template_id"], value["template_sha256"], value["workload"])


# -- messages -----------------------------------------------------------------------------

@dataclass(frozen=True)
class PrepareRequest:
    request_id: str
    reservation: Reservation
    snapshot_root: str
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))
    #: The reservation member exactly as the caller sent it, for the echo comparison.
    reservation_json: Mapping[str, Any] = field(default_factory=lambda: _context({}),
                                                repr=False, compare=False)

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.prepare.request.v1", "request_id": self.request_id,
                "reservation": self.reservation.to_json(), "snapshot_root": self.snapshot_root,
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "PrepareRequest":
        return cls(value["request_id"], Reservation.from_json(value["reservation"]),
                   value["snapshot_root"], _context(value["caller_context"]),
                   _context(value["reservation"]))


@dataclass(frozen=True)
class PrepareResponse:
    request_id: str
    reservation_id: str
    state: str
    code: str | None
    paths: PreparedPaths | None
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.prepare.response.v1", "request_id": self.request_id,
                "reservation_id": self.reservation_id, "state": self.state, "code": self.code,
                "paths": _json(self.paths), "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "PrepareResponse":
        return cls(value["request_id"], value["reservation_id"], value["state"], value["code"],
                   _optional(value["paths"], PreparedPaths), _context(value["caller_context"]))


@dataclass(frozen=True)
class LaunchRequest:
    request_id: str
    reservation: Reservation
    workload: str
    image_digest: str
    policy_vector: str
    providers: tuple[str, ...]
    command: Command
    action: str
    result_kind: str
    snapshot: Snapshot
    instructions: Instructions
    seed: SeedDeclaration | None
    paths: PreparedPaths | None
    timeout_seconds: int
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))
    #: The reservation member exactly as the caller sent it, for the echo comparison.
    reservation_json: Mapping[str, Any] = field(default_factory=lambda: _context({}),
                                                repr=False, compare=False)

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.request.v1", "request_id": self.request_id,
                "reservation": self.reservation.to_json(), "workload": self.workload,
                "image_digest": self.image_digest, "policy_vector": self.policy_vector,
                "providers": list(self.providers), "command": self.command.to_json(),
                "action": self.action, "result_kind": self.result_kind,
                "snapshot": self.snapshot.to_json(), "instructions": self.instructions.to_json(),
                "seed": _json(self.seed), "paths": _json(self.paths),
                "timeout_seconds": self.timeout_seconds,
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "LaunchRequest":
        return cls(value["request_id"], Reservation.from_json(value["reservation"]),
                   value["workload"], value["image_digest"], value["policy_vector"],
                   tuple(value["providers"]), Command.from_json(value["command"]),
                   value["action"], value["result_kind"], Snapshot.from_json(value["snapshot"]),
                   Instructions.from_json(value["instructions"]),
                   _optional(value["seed"], SeedDeclaration),
                   _optional(value["paths"], PreparedPaths), value["timeout_seconds"],
                   _context(value["caller_context"]), _context(value["reservation"]))


@dataclass(frozen=True)
class LaunchResponse:
    request_id: str
    reservation_id: str
    attempt_id: str | None
    state: str
    code: str | None
    snapshot_reason: str | None
    seed_reason: str | None
    admission_diagnostic: str | None
    termination: Termination | None
    worker_invocations: int
    envelope_digest: str | None
    scratch_path: str | None
    tree_path: str | None
    #: The schema member ``return`` (a Python keyword).
    return_: ReturnDescriptor | None
    evidence: LaunchEvidence | None
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.response.v1", "request_id": self.request_id,
                "reservation_id": self.reservation_id, "attempt_id": self.attempt_id,
                "state": self.state, "code": self.code, "snapshot_reason": self.snapshot_reason,
                "seed_reason": self.seed_reason,
                "admission_diagnostic": self.admission_diagnostic,
                "termination": _json(self.termination),
                "worker_invocations": self.worker_invocations,
                "envelope_digest": self.envelope_digest, "scratch_path": self.scratch_path,
                "tree_path": self.tree_path, "return": _json(self.return_),
                "evidence": _json(self.evidence), "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "LaunchResponse":
        return cls(value["request_id"], value["reservation_id"], value["attempt_id"],
                   value["state"], value["code"], value["snapshot_reason"], value["seed_reason"],
                   value["admission_diagnostic"], _optional(value["termination"], Termination),
                   value["worker_invocations"], value["envelope_digest"], value["scratch_path"],
                   value["tree_path"], _optional(value["return"], ReturnDescriptor),
                   _optional(value["evidence"], LaunchEvidence),
                   _context(value["caller_context"]))


@dataclass(frozen=True)
class StatusRequest:
    request_id: str
    reservation_id: str
    launch_request_id: str
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.status.request.v1", "request_id": self.request_id,
                "reservation_id": self.reservation_id,
                "launch_request_id": self.launch_request_id,
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "StatusRequest":
        return cls(value["request_id"], value["reservation_id"], value["launch_request_id"],
                   _context(value["caller_context"]))


@dataclass(frozen=True)
class StatusResponse:
    request_id: str
    reservation_id: str
    launch_request_id: str
    state: str
    launch: LaunchResponse | None
    run_id: str | None
    scratch_path: str | None
    tree_path: str | None
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.status.response.v1", "request_id": self.request_id,
                "reservation_id": self.reservation_id,
                "launch_request_id": self.launch_request_id, "state": self.state,
                "launch": _json(self.launch), "run_id": self.run_id,
                "scratch_path": self.scratch_path, "tree_path": self.tree_path,
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "StatusResponse":
        return cls(value["request_id"], value["reservation_id"], value["launch_request_id"],
                   value["state"], _optional(value["launch"], LaunchResponse), value["run_id"],
                   value["scratch_path"], value["tree_path"], _context(value["caller_context"]))


@dataclass(frozen=True)
class CancelRequest:
    request_id: str
    reservation_id: str
    launch_request_id: str
    deadline_ms: int
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.cancel.request.v1", "request_id": self.request_id,
                "reservation_id": self.reservation_id,
                "launch_request_id": self.launch_request_id, "deadline_ms": self.deadline_ms,
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "CancelRequest":
        return cls(value["request_id"], value["reservation_id"], value["launch_request_id"],
                   value["deadline_ms"], _context(value["caller_context"]))


@dataclass(frozen=True)
class CancelResponse:
    request_id: str
    reservation_id: str
    launch_request_id: str
    state: str
    caller_context: Mapping[str, Any] = field(default_factory=lambda: _context({}))

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.cancel.response.v1", "request_id": self.request_id,
                "reservation_id": self.reservation_id,
                "launch_request_id": self.launch_request_id, "state": self.state,
                "caller_context": dict(self.caller_context)}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "CancelResponse":
        return cls(value["request_id"], value["reservation_id"], value["launch_request_id"],
                   value["state"], _context(value["caller_context"]))


@dataclass(frozen=True)
class LaunchVersionResponse:
    client: str
    protocol_schema_sha256: str
    placement_protocol_schema_sha256: str
    config_sha256: str
    seat_caps_sha256: str
    local_pi_runner_launcher: str
    local_link_root: str | None
    seed_root: str | None
    seed_limits: SeedLimits | None
    templates: tuple[TemplateSummary, ...]

    def to_json(self) -> dict[str, Any]:
        return {"schema": "placement.launch.version.response.v1", "client": self.client,
                "protocol_schema_sha256": self.protocol_schema_sha256,
                "placement_protocol_schema_sha256": self.placement_protocol_schema_sha256,
                "config_sha256": self.config_sha256, "seat_caps_sha256": self.seat_caps_sha256,
                "local_pi_runner_launcher": self.local_pi_runner_launcher,
                "local_link_root": self.local_link_root, "seed_root": self.seed_root,
                "seed_limits": _json(self.seed_limits),
                "templates": [template.to_json() for template in self.templates]}

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "LaunchVersionResponse":
        return cls(value["client"], value["protocol_schema_sha256"],
                   value["placement_protocol_schema_sha256"], value["config_sha256"],
                   value["seat_caps_sha256"], value["local_pi_runner_launcher"],
                   value["local_link_root"], value["seed_root"],
                   _optional(value["seed_limits"], SeedLimits),
                   tuple(TemplateSummary.from_json(t) for t in value["templates"]))


LaunchProcessRequest = Union[PrepareRequest, LaunchRequest, StatusRequest, CancelRequest]
LaunchProcessResponse = Union[PrepareResponse, LaunchResponse, StatusResponse, CancelResponse,
                              LaunchVersionResponse]

_REQUEST_TYPES: Mapping[str, Any] = MappingProxyType({
    "prepare": PrepareRequest, "launch": LaunchRequest,
    "status": StatusRequest, "cancel": CancelRequest,
})
_RESPONSE_TYPES: Mapping[type, str] = MappingProxyType({
    PrepareResponse: "PrepareResponse", LaunchResponse: "LaunchResponse",
    StatusResponse: "StatusResponse", CancelResponse: "CancelResponse",
    LaunchVersionResponse: "LaunchVersionResponse",
})
_RESPONSE_RECORDS: Mapping[str, Any] = MappingProxyType({
    "prepare": PrepareResponse, "launch": LaunchResponse, "status": StatusResponse,
    "cancel": CancelResponse, "version": LaunchVersionResponse,
})


# -- cross-member rules JSON Schema cannot state ------------------------------------------

def _status_echo_consistent(definition: str, value: Mapping[str, Any]) -> bool:
    """``x-status-cancel.status``: for every terminal state the top-level run_id, scratch_path
    and tree_path equal the nested launch's attempt_id, scratch_path and tree_path."""
    if definition != "StatusResponse" or value.get("state") not in TERMINAL_STATUS_STATES:
        return True
    launch = value.get("launch")
    if not isinstance(launch, Mapping):
        return False
    return (value.get("run_id") == launch.get("attempt_id")
            and value.get("scratch_path") == launch.get("scratch_path")
            and value.get("tree_path") == launch.get("tree_path"))


# -- the codec ----------------------------------------------------------------------------

def decode_launch_request(verb: str, raw: bytes) -> LaunchProcessRequest:
    """Decode one request for ``prepare``, ``launch``, ``status`` or ``cancel``.

    The bytes are captured once; the record is built only from that capture after it passed
    the input rules and the verb's schema. Raises :class:`ProtocolError` (exit class 70)."""
    definition = _REQUEST_DEFS.get(verb) if isinstance(verb, str) else None
    if definition is None:
        raise ProtocolError("verb_unknown")
    value = _placement.load_strict_object(raw)
    if not _valid(definition, value):
        raise ProtocolError("schema_invalid")
    try:
        return _REQUEST_TYPES[verb].from_json(value)
    except (KeyError, TypeError, ValueError):
        raise ProtocolError("schema_invalid") from None


def encode_launch_response(message: LaunchProcessResponse) -> bytes:
    """One compact UTF-8 JSON object followed by LF, validated before it is returned."""
    definition = _RESPONSE_TYPES.get(type(message))
    if definition is None:
        raise ProtocolError("response_invalid")
    try:
        value = message.to_json()
    except (AttributeError, TypeError, ValueError):
        raise ProtocolError("response_invalid") from None
    if not _valid(definition, value) or not _status_echo_consistent(definition, value):
        raise ProtocolError("response_invalid")
    try:
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return text.encode("utf-8") + b"\n"
    except (TypeError, ValueError, RecursionError):  # UnicodeEncodeError is a ValueError
        raise ProtocolError("response_invalid") from None


def _load_response_line(raw: bytes) -> dict[str, Any]:
    """Parse one UTF-8 JSON object followed by exactly one LF.

    The request bounds of ``x-cli.input`` (65536 bytes, safe integers) are not applied,
    because responses carry members the schema leaves unbounded (``duration_ms``, counts).
    Duplicate keys, non-finite numbers, invalid UTF-8 and lone surrogates still refuse."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ProtocolError("input_not_bytes")
    captured = bytes(raw)
    if not captured.endswith(b"\n"):
        raise ProtocolError("input_trailing_data")
    body = captured[:-1]
    if b"\n" in body or b"\r" in body or body[:1].isspace() or body[-1:].isspace():
        raise ProtocolError("input_trailing_data")
    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ProtocolError("input_not_utf8") from None
    if text.startswith("\ufeff"):
        raise ProtocolError("input_not_utf8")
    decoder = json.JSONDecoder(
        object_pairs_hook=_placement._unique_object,  # noqa: SLF001 - shared strictness
        parse_constant=_placement._reject_constant,  # noqa: SLF001
        parse_float=_placement._finite_float,  # noqa: SLF001
    )
    try:
        value, end = decoder.raw_decode(text)
    except ProtocolError:
        raise
    except (ValueError, RecursionError):
        raise ProtocolError("input_invalid_json") from None
    if end != len(text):
        raise ProtocolError("input_trailing_data")
    if not isinstance(value, dict):
        raise ProtocolError("input_not_object")
    try:
        encodable = _placement._encodable(value)  # noqa: SLF001
    except RecursionError:
        raise ProtocolError("input_invalid_json") from None
    if not encodable:
        raise ProtocolError("input_not_utf8")
    return value


def decode_launch_response(verb: str, raw: bytes) -> LaunchProcessResponse:
    """Decode one schema-valid response object followed by exactly one LF. Inter-token spaces
    and tabs are accepted."""
    definition = _RESPONSE_DEFS.get(verb) if isinstance(verb, str) else None
    if definition is None:
        raise ProtocolError("verb_unknown")
    value = _load_response_line(raw)
    if not _valid(definition, value) or not _status_echo_consistent(definition, value):
        raise ProtocolError("schema_invalid")
    try:
        return _RESPONSE_RECORDS[verb].from_json(value)
    except (KeyError, TypeError, ValueError):
        raise ProtocolError("schema_invalid") from None


_EXIT_CLASSES: Mapping[tuple[type, str], int] = MappingProxyType({
    (PrepareResponse, "prepared"): 0, (PrepareResponse, "refused"): 10,
    (PrepareResponse, "timeout"): 20,
    (LaunchResponse, "finished"): 0, (LaunchResponse, "refused"): 10,
    (LaunchResponse, "uncertain"): 20,
    (StatusResponse, "queued"): 0, (StatusResponse, "running"): 0,
    (StatusResponse, "cancelling"): 0, (StatusResponse, "finished"): 0,
    (StatusResponse, "refused"): 0, (StatusResponse, "uncertain"): 0,
    (StatusResponse, "unknown_attempt"): 10,
    (CancelResponse, "cancelled"): 0, (CancelResponse, "already_terminal"): 0,
    (CancelResponse, "unknown_attempt"): 10, (CancelResponse, "cancel_pending"): 20,
})


def launch_exit_class(message: LaunchProcessResponse) -> int:
    """``x-cli.exit_codes`` for a schema-valid outcome: 0 settled, 10 nothing started by this
    call, 20 an effect may remain. A :class:`ProtocolError` is :data:`PROTOCOL_EXIT`."""
    if isinstance(message, LaunchVersionResponse):
        return 0
    try:
        return _EXIT_CLASSES[(type(message), message.state)]
    except (KeyError, AttributeError):
        raise ProtocolError("response_invalid") from None
