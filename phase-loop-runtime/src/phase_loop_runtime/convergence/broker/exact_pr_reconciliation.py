"""Bounded administrative reconciliation of one exact, already-existing PR.

This module does not add a broker terminal transition.  Raw ambiguity remains
permanent; an authenticated, immutable per-key settlement supplies an effective
read overlay and a compatibility observation for runtimes that predate it.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from phase_loop_runtime.convergence.contracts import publish_committed_branch_idempotency_key
from phase_loop_runtime.convergence.provider_contracts import TerminalOutcomeState


DISPOSITION_SCHEMA = "ExactPRReconciliationDisposition.v1"
SETTLEMENT_SCHEMA = "ExactPRSettlement.v1"
SETTLEMENT_DIRECTORY = "exact-pr-settlements"
SETTLEMENT_DOMAIN = b"ExactPRSettlement.v1\0"
DISPOSITION_DOMAIN = b"ExactPRReconciliationDisposition.v1\0"
AUTHORIZATION_KIND = "operator_procedural"
CREATOR_ATTRIBUTION = "not_proven_broker"
CORRECTION_KIND = "assertion_count_correction"
ORIGINAL_ASSERTION_TEXT = "31 pool, 40 Codex, 96 Claude assertions"
OBSERVED_ASSERTION_TEXT = "31 pool, 38 Codex, 94 Claude assertions; 163 total"

EXACT_PR_CRASH_STEPS = (
    "partial_observation_temp",
    "before_observation_replace",
    "after_observation_replace",
    "partial_settlement_temp",
    "before_settlement_link",
    "after_settlement_link_before_directory_fsync",
    "after_settlement_directory_fsync_before_response",
)
_EXACT_PR_CRASH_STEP: str | None = None


class ExactPRReconciliationRefused(PermissionError):
    """The exact-PR request failed closed before changing authoritative state."""


class _ExactPRCrash(RuntimeError):
    """Test-only process-crash seam."""


def crash_at_exact_pr_step(step: str | None) -> None:
    global _EXACT_PR_CRASH_STEP
    if step is not None and step not in EXACT_PR_CRASH_STEPS:
        raise ValueError(f"unknown exact-PR crash step {step!r}")
    _EXACT_PR_CRASH_STEP = step


def _maybe_crash(step: str) -> None:
    if _EXACT_PR_CRASH_STEP == step:
        raise _ExactPRCrash(step)


@dataclass(frozen=True)
class ExactPRSettlementAbsent:
    key: str
    reason: str = "settlement_absent"


@dataclass(frozen=True)
class ExactPRTypedRefusal:
    key: str
    reason: str
    path: Path | None = None


@dataclass(frozen=True)
class ValidExactPRSettlement:
    key: str
    payload: dict
    settlement_digest: str
    disposition_digest: str
    path: Path | None
    carried: bool = False

    @property
    def result(self) -> dict:
        return settlement_result(self)


@dataclass(frozen=True)
class ExactPRStoreSnapshot:
    root: Path
    receipt: object | None
    receipt_bytes: bytes | None
    evidence_bytes: bytes | None
    observation_bytes: bytes | None
    settlement_files: Mapping[str, bytes]
    temporary_files: tuple[str, ...]
    generation: int

    @property
    def receipt_sha256(self) -> str:
        return _sha256(self.receipt_bytes or b"")


@dataclass(frozen=True)
class _ReconciliationInputs:
    snapshot: ExactPRStoreSnapshot
    checkpoint_path: Path
    checkpoint_bytes: bytes
    pointer_path: Path
    pointer_bytes: bytes
    owner_path: Path
    owner_bytes: bytes
    ambiguity_line: bytes


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _canonical(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ExactPRReconciliationRefused(f"value is not canonical JSON: {error}") from error


def _strict_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def strict_json_bytes(body: bytes, *, label: str) -> dict:
    try:
        decoded = body.decode("utf-8")
        value = json.loads(decoded, object_pairs_hook=_strict_object_pairs)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ExactPRReconciliationRefused(f"{label} is not strict UTF-8 JSON: {error}") from error
    if not isinstance(value, dict):
        raise ExactPRReconciliationRefused(f"{label} is not a JSON object")
    return value


def load_strict_json_file(path: Path | str, *, label: str) -> dict:
    candidate = Path(path)
    return strict_json_bytes(_read_regular(candidate, label=label), label=label)


def _read_regular(path: Path, *, label: str) -> bytes:
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        raise ExactPRReconciliationRefused(f"{label} is missing: {path}") from None
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise ExactPRReconciliationRefused(f"{label} is not a regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise ExactPRReconciliationRefused(f"{label} is unreadable: {path}: {error}") from error


def _read_optional_regular(path: Path, *, label: str) -> bytes | None:
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise ExactPRReconciliationRefused(f"{label} is not a regular file: {path}")
    return _read_regular(path, label=label)


def _require_exact_keys(value: dict, expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ExactPRReconciliationRefused(
            f"{label} schema differs: missing={missing!r}, unknown={unknown!r}"
        )


def _reject_floats(value: object, *, label: str) -> None:
    if isinstance(value, float):
        raise ExactPRReconciliationRefused(f"{label} contains a floating-point value")
    if isinstance(value, dict):
        for nested in value.values():
            _reject_floats(nested, label=label)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_floats(nested, label=label)


def _require_string(value: dict, key: str, *, nonempty: bool = True) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or (nonempty and not candidate):
        raise ExactPRReconciliationRefused(f"{key} must be a{' non-empty' if nonempty else ''} string")
    return candidate


def _require_sha256(value: dict, key: str) -> str:
    candidate = _require_string(value, key)
    if len(candidate) != 64 or any(character not in "0123456789abcdef" for character in candidate):
        raise ExactPRReconciliationRefused(f"{key} must be a lower-case SHA-256 digest")
    return candidate


_DISPOSITION_KEYS = {
    "schema",
    "canonical_repository_identity",
    "repository_common_dir",
    "authority_root",
    "generation",
    "partition_receipt_sha256",
    "transaction_id",
    "checkpoint_path",
    "checkpoint_sha256",
    "active_transaction_pointer_path",
    "effect_key",
    "ambiguity_digest",
    "owner_nonce",
    "owner_transaction_id",
    "owner_bytes_sha256",
    "pr_host",
    "pr_repository",
    "pr_number",
    "pr_url",
    "head_repository",
    "head_ref",
    "head_sha",
    "base_repository",
    "base_ref",
    "draft",
    "expected_title",
    "observed_title",
    "original_body",
    "observed_body",
    "original_body_sha256",
    "observed_body_sha256",
    "correction_kind",
    "correction_reason",
    "authorization_kind",
    "owner_instruction_reference",
    "owner_instruction_sha256",
    "creator_attribution",
}


def validate_exact_pr_disposition(disposition: object) -> dict:
    if not isinstance(disposition, dict):
        raise ExactPRReconciliationRefused("disposition is not a JSON object")
    _require_exact_keys(disposition, _DISPOSITION_KEYS, label=DISPOSITION_SCHEMA)
    if disposition.get("schema") != DISPOSITION_SCHEMA:
        raise ExactPRReconciliationRefused(f"unsupported disposition schema {disposition.get('schema')!r}")
    for key in _DISPOSITION_KEYS - {"generation", "pr_number", "draft"}:
        _require_string(
            disposition,
            key,
            nonempty=key not in {"correction_reason"},
        )
    if not isinstance(disposition.get("generation"), int) or isinstance(disposition.get("generation"), bool):
        raise ExactPRReconciliationRefused("generation must be an integer")
    if disposition["generation"] < 0:
        raise ExactPRReconciliationRefused("generation must be non-negative")
    if not isinstance(disposition.get("pr_number"), int) or isinstance(disposition.get("pr_number"), bool):
        raise ExactPRReconciliationRefused("pr_number must be an integer")
    if disposition["pr_number"] < 1:
        raise ExactPRReconciliationRefused("pr_number must be positive")
    if not isinstance(disposition.get("draft"), bool):
        raise ExactPRReconciliationRefused("draft must be a boolean")
    for key in (
        "partition_receipt_sha256", "checkpoint_sha256", "ambiguity_digest",
        "owner_bytes_sha256", "original_body_sha256", "observed_body_sha256",
        "owner_instruction_sha256",
    ):
        _require_sha256(disposition, key)
    head = disposition["head_sha"]
    if len(head) not in (40, 64) or any(character not in "0123456789abcdef" for character in head):
        raise ExactPRReconciliationRefused("head_sha is not a full lower-case Git object id")
    if disposition["authorization_kind"] != AUTHORIZATION_KIND:
        raise ExactPRReconciliationRefused("authorization_kind must be operator_procedural")
    if disposition["creator_attribution"] != CREATOR_ATTRIBUTION:
        raise ExactPRReconciliationRefused("creator_attribution must be not_proven_broker")
    if disposition["owner_transaction_id"] != disposition["transaction_id"]:
        raise ExactPRReconciliationRefused(
            "owner transaction must equal the frozen publication transaction"
        )
    if disposition["expected_title"] != disposition["observed_title"]:
        raise ExactPRReconciliationRefused("the observed title differs from the frozen commit subject")
    original = disposition["original_body"]
    observed = disposition["observed_body"]
    if _sha256(original.encode("utf-8")) != disposition["original_body_sha256"]:
        raise ExactPRReconciliationRefused("original body digest does not bind the retained original body")
    if _sha256(observed.encode("utf-8")) != disposition["observed_body_sha256"]:
        raise ExactPRReconciliationRefused("observed body digest does not bind the retained observed body")
    if original == observed:
        if disposition["correction_kind"] != "none" or disposition["correction_reason"]:
            raise ExactPRReconciliationRefused("equal bodies require no correction exception")
    else:
        if disposition["correction_kind"] != CORRECTION_KIND or not disposition["correction_reason"]:
            raise ExactPRReconciliationRefused("body inequality requires the exact procedural correction")
        if original.count(ORIGINAL_ASSERTION_TEXT) != 1:
            raise ExactPRReconciliationRefused("original body does not contain the one frozen assertion-count phrase")
        if original.replace(ORIGINAL_ASSERTION_TEXT, OBSERVED_ASSERTION_TEXT, 1) != observed:
            raise ExactPRReconciliationRefused("body correction contains changes beyond the one count substitution")
    expected_url = (
        f"https://{disposition['pr_host']}/{disposition['pr_repository']}/pull/"
        f"{disposition['pr_number']}"
    )
    if disposition["pr_url"] != expected_url:
        raise ExactPRReconciliationRefused("pr_url is not canonical for the bound host/repository/number")
    if disposition["head_repository"] != disposition["pr_repository"]:
        raise ExactPRReconciliationRefused("cross-repository heads are not reconcilable")
    if disposition["base_repository"] != disposition["pr_repository"]:
        raise ExactPRReconciliationRefused("base repository differs from the pull-request repository")
    return dict(disposition)


def disposition_digest(disposition: Mapping[str, Any]) -> str:
    validated = validate_exact_pr_disposition(dict(disposition))
    return _sha256(DISPOSITION_DOMAIN + _canonical(validated))


def settlement_digest(payload: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in dict(payload).items() if key != "settlement_digest"}
    return _sha256(SETTLEMENT_DOMAIN + _canonical(unsigned))


def settlement_filename(key: str) -> str:
    if not isinstance(key, str) or not key:
        raise ExactPRReconciliationRefused("effect key must be a non-empty string")
    return f"{_sha256(key.encode('utf-8'))}.json"


def settlement_path(root: Path, key: str) -> Path:
    return Path(root) / SETTLEMENT_DIRECTORY / settlement_filename(key)


def _generation_of(root: Path) -> int:
    return int(root.name) if root.parent.name == "generations" and root.name.isdigit() else 0


def snapshot_exact_pr_store(root: Path | str) -> ExactPRStoreSnapshot:
    """Read the effective-reader inputs without locks, mkdir, leases, or network."""
    from . import live

    root = Path(root)
    receipt_path = root / live.RECEIPT_FILENAME
    receipt_bytes = _read_optional_regular(receipt_path, label="partition receipt")
    try:
        receipt = live.load_partition_receipt(root) if receipt_bytes is not None else None
    except (live.LegacyCutoverConflict, OSError, PermissionError, ValueError) as error:
        raise ExactPRReconciliationRefused(
            f"partition receipt does not authenticate: {error}"
        ) from error
    if receipt_bytes is not None and _read_optional_regular(
        receipt_path, label="partition receipt"
    ) != receipt_bytes:
        raise ExactPRReconciliationRefused(
            "partition receipt changed while the exact-PR snapshot was captured"
        )
    evidence_bytes = _read_optional_regular(root / "evidence.jsonl", label="broker evidence")
    observation_bytes = _read_optional_regular(
        root / "post-ambiguity-observations.jsonl",
        label="post-ambiguity observations",
    )
    files: dict[str, bytes] = {}
    temporary: list[str] = []
    directory = root / SETTLEMENT_DIRECTORY
    try:
        directory_status = os.lstat(directory)
    except FileNotFoundError:
        directory_status = None
    if directory_status is not None:
        if stat.S_ISLNK(directory_status.st_mode) or not stat.S_ISDIR(directory_status.st_mode):
            raise ExactPRReconciliationRefused(f"settlement directory is not a regular directory: {directory}")
        for candidate in sorted(directory.iterdir(), key=lambda item: item.name):
            if candidate.name.startswith(".") and candidate.name.endswith(".tmp"):
                temporary.append(candidate.name)
                continue
            if not candidate.name.endswith(".json"):
                raise ExactPRReconciliationRefused(f"unknown settlement-directory entry: {candidate}")
            files[candidate.name] = _read_regular(candidate, label="exact-PR settlement")
    return ExactPRStoreSnapshot(
        root=root,
        receipt=receipt,
        receipt_bytes=receipt_bytes,
        evidence_bytes=evidence_bytes,
        observation_bytes=observation_bytes,
        settlement_files=files,
        temporary_files=tuple(temporary),
        generation=_generation_of(root),
    )


def exact_pr_settlement_snapshot_sha256(snapshot_or_root: ExactPRStoreSnapshot | Path | str) -> str:
    snapshot = (
        snapshot_or_root
        if isinstance(snapshot_or_root, ExactPRStoreSnapshot)
        else snapshot_exact_pr_store(snapshot_or_root)
    )
    return exact_pr_side_snapshot_sha256(
        snapshot.settlement_files, snapshot.observation_bytes
    )


def exact_pr_side_snapshot_sha256(
    settlement_files: Mapping[str, bytes], observation_bytes: bytes | None
) -> str:
    payload = {
        "schema": "ExactPRSettlementSnapshot.v1",
        "files": {name: _sha256(body) for name, body in sorted(settlement_files.items())},
        "post_ambiguity_observations_sha256": _sha256(observation_bytes or b""),
    }
    return _sha256(_canonical(payload))


def _decode_b64(value: object, *, label: str) -> bytes:
    if not isinstance(value, str):
        raise ExactPRReconciliationRefused(f"{label} is not base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ExactPRReconciliationRefused(f"{label} is not canonical base64") from error


_SETTLEMENT_KEYS = {
    "schema", "settlement_digest", "disposition", "disposition_digest",
    "frozen_owner_bytes_b64", "frozen_owner_sha256", "ambiguity_row_b64",
    "ambiguity_digest", "observation", "observation_sha256", "provider_witness",
    "observation_time_utc", "committed_at_utc", "runtime_provenance", "frozen_checkpoint",
}
_FROZEN_CHECKPOINT_KEYS = {
    "checkpoint_bytes_b64", "checkpoint_sha256", "active_pointer_bytes_b64",
    "active_pointer_sha256", "partition_receipt_bytes_b64", "partition_receipt_sha256",
    "evidence_sha256", "observation_prefix_sha256",
}


def _validate_observation_row(observation: object, disposition: dict) -> dict:
    from .evidence import POST_AMBIGUITY_OBSERVATION_SCHEMA

    expected_keys = {
        "idempotency_key", "observed_state", "evidence_reference", "head_sha", "branch",
        "transaction_id", "owner_nonce", "ambiguity_digest", "schema",
    }
    if not isinstance(observation, dict):
        raise ExactPRReconciliationRefused("settlement observation is not an object")
    _require_exact_keys(observation, expected_keys, label=POST_AMBIGUITY_OBSERVATION_SCHEMA)
    expected = {
        "idempotency_key": disposition["effect_key"],
        "observed_state": TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED.value,
        "evidence_reference": disposition["pr_url"],
        "head_sha": disposition["head_sha"],
        "branch": disposition["head_ref"],
        "transaction_id": disposition["transaction_id"],
        "owner_nonce": disposition["owner_nonce"],
        "ambiguity_digest": disposition["ambiguity_digest"],
        "schema": POST_AMBIGUITY_OBSERVATION_SCHEMA,
    }
    if observation != expected:
        raise ExactPRReconciliationRefused("settlement observation does not bind the disposition")
    return dict(observation)


def _observation_line(observation: Mapping[str, Any]) -> bytes:
    # This is the existing agent-harness#1591 writer's stable spelling.
    return (json.dumps(dict(observation), sort_keys=True) + "\n").encode("utf-8")


def _validate_settlement_payload(
    payload: object,
    *,
    key: str,
    current_observation_bytes: bytes | None,
    require_current_observation: bool,
) -> ValidExactPRSettlement:
    if not isinstance(payload, dict):
        raise ExactPRReconciliationRefused("settlement is not a JSON object")
    _reject_floats(payload, label=SETTLEMENT_SCHEMA)
    _require_exact_keys(payload, _SETTLEMENT_KEYS, label=SETTLEMENT_SCHEMA)
    if payload.get("schema") != SETTLEMENT_SCHEMA:
        raise ExactPRReconciliationRefused(f"unsupported settlement schema {payload.get('schema')!r}")
    disposition = validate_exact_pr_disposition(payload["disposition"])
    if disposition["effect_key"] != key:
        raise ExactPRReconciliationRefused("settlement effect key differs from the lookup key")
    if payload["disposition_digest"] != disposition_digest(disposition):
        raise ExactPRReconciliationRefused("settlement disposition digest drifted")
    if payload["settlement_digest"] != settlement_digest(payload):
        raise ExactPRReconciliationRefused("settlement digest drifted")
    owner = _decode_b64(payload["frozen_owner_bytes_b64"], label="frozen owner bytes")
    if _sha256(owner) != payload["frozen_owner_sha256"] or payload["frozen_owner_sha256"] != disposition["owner_bytes_sha256"]:
        raise ExactPRReconciliationRefused("settlement frozen owner digest drifted")
    ambiguity_line = _decode_b64(payload["ambiguity_row_b64"], label="ambiguity row")
    if _sha256(ambiguity_line) != payload["ambiguity_digest"] or payload["ambiguity_digest"] != disposition["ambiguity_digest"]:
        raise ExactPRReconciliationRefused("settlement ambiguity digest drifted")
    ambiguity = strict_json_bytes(ambiguity_line, label="settlement ambiguity row")
    if (
        ambiguity.get("idempotency_key") != key
        or ambiguity.get("state") != TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value
    ):
        raise ExactPRReconciliationRefused("settlement ambiguity row is not the exact blocked key")
    observation = _validate_observation_row(payload["observation"], disposition)
    observation_line = _observation_line(observation)
    if payload["observation_sha256"] != _sha256(observation_line):
        raise ExactPRReconciliationRefused("settlement observation digest drifted")
    if require_current_observation and observation_line not in (current_observation_bytes or b"").splitlines(keepends=True):
        raise ExactPRReconciliationRefused("settlement has no exact durable compatibility observation")
    frozen = payload["frozen_checkpoint"]
    if not isinstance(frozen, dict):
        raise ExactPRReconciliationRefused("frozen checkpoint input is not an object")
    _require_exact_keys(frozen, _FROZEN_CHECKPOINT_KEYS, label="frozen checkpoint input")
    for encoded, digest_key in (
        ("checkpoint_bytes_b64", "checkpoint_sha256"),
        ("active_pointer_bytes_b64", "active_pointer_sha256"),
        ("partition_receipt_bytes_b64", "partition_receipt_sha256"),
    ):
        if _sha256(_decode_b64(frozen[encoded], label=encoded)) != frozen[digest_key]:
            raise ExactPRReconciliationRefused(f"{digest_key} does not bind its retained bytes")
    if frozen["checkpoint_sha256"] != disposition["checkpoint_sha256"]:
        raise ExactPRReconciliationRefused("frozen checkpoint digest differs from the disposition")
    if frozen["partition_receipt_sha256"] != disposition["partition_receipt_sha256"]:
        raise ExactPRReconciliationRefused("frozen receipt digest differs from the disposition")
    if not isinstance(payload["provider_witness"], dict) or payload["provider_witness"].get("schema") != "ExactPRProviderWitness.v1":
        raise ExactPRReconciliationRefused("settlement provider witness is absent or unsupported")
    if not isinstance(payload["runtime_provenance"], dict) or not payload["runtime_provenance"]:
        raise ExactPRReconciliationRefused("settlement runtime provenance is absent")
    for key_name in ("observation_time_utc", "committed_at_utc"):
        _require_string(payload, key_name)
    return ValidExactPRSettlement(
        key=key,
        payload=dict(payload),
        settlement_digest=payload["settlement_digest"],
        disposition_digest=payload["disposition_digest"],
        path=None,
    )


def _carried_settlement(snapshot: ExactPRStoreSnapshot, key: str) -> tuple[dict, str] | None:
    if snapshot.receipt is None:
        return None
    from .live import LegacyCutoverConflict, sealed_partition_effects

    try:
        carried = sealed_partition_effects(snapshot.receipt).get(key)
    except LegacyCutoverConflict as error:
        raise ExactPRReconciliationRefused(f"carried settlement inventory does not authenticate: {error}") from error
    adjudicated = getattr(snapshot.receipt, "adjudicated_effect_dispositions", {}).get(key)
    if not isinstance(carried, dict) or "exact_pr_settlement" not in carried:
        if isinstance(adjudicated, dict) and "settlement_digest" in adjudicated:
            raise ExactPRReconciliationRefused(
                "receipt names an exact-PR settlement digest but omits its embedded proof"
            )
        if _predecessor_direct_settlement_exists(snapshot, key):
            raise ExactPRReconciliationRefused(
                "predecessor exact-PR settlement proof was omitted from the rotated carry"
            )
        return None
    payload = carried.get("exact_pr_settlement")
    digest = carried.get("settlement_digest")
    if not isinstance(payload, dict) or not isinstance(digest, str):
        raise ExactPRReconciliationRefused("carried settlement proof is malformed")
    disposition = payload.get("disposition") if isinstance(payload, dict) else None
    if (
        not isinstance(disposition, dict)
        or carried.get("disposition") != "observed_landed"
        or carried.get("evidence_reference") != disposition.get("pr_url")
        or carried.get("observed_head") != disposition.get("head_sha")
    ):
        raise ExactPRReconciliationRefused(
            "carried settlement URL, head or disposition differs from its embedded proof"
        )
    if isinstance(adjudicated, dict) and adjudicated.get("settlement_digest", digest) != digest:
        raise ExactPRReconciliationRefused(
            "receipt adjudication digest differs from its carried settlement"
        )
    return payload, digest


def _predecessor_direct_settlement_exists(snapshot: ExactPRStoreSnapshot, key: str) -> bool:
    """Detect a provenance-losing older rotation without trusting it to unblock.

    A legacy rotation can authenticate its ordinary files while omitting the
    settlement overlay.  The predecessor is immutable once the successor is
    active, so the continued presence of the direct proof is sufficient to
    fail closed; it is never treated as a valid carried settlement here.
    """
    receipt = snapshot.receipt
    generation = getattr(receipt, "generation", 0)
    predecessor_generation = getattr(receipt, "predecessor_generation", -1)
    if not isinstance(generation, int) or generation <= 0:
        return False
    if predecessor_generation != generation - 1:
        return False
    container = snapshot.root.parents[1] if snapshot.root.parent.name == "generations" else snapshot.root
    predecessor = (
        container
        if predecessor_generation == 0
        else container / "generations" / str(predecessor_generation)
    )
    path = settlement_path(predecessor, key)
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise ExactPRReconciliationRefused(
            "predecessor exact-PR settlement path is not a regular file"
        )
    return True


def read_exact_pr_settlement(
    snapshot: ExactPRStoreSnapshot,
    key: str,
) -> ExactPRSettlementAbsent | ValidExactPRSettlement | ExactPRTypedRefusal:
    """Validate a direct or receipt-carried settlement with no lock or write."""
    name = settlement_filename(key)
    body = snapshot.settlement_files.get(name)
    try:
        if body is not None:
            payload = strict_json_bytes(body, label=f"settlement {name}")
            if body != _canonical(payload) + b"\n":
                raise ExactPRReconciliationRefused(
                    "settlement file is not canonical JSON with one trailing newline"
                )
            valid = _validate_settlement_payload(
                payload,
                key=key,
                current_observation_bytes=snapshot.observation_bytes,
                require_current_observation=True,
            )
            return ValidExactPRSettlement(
                **{**valid.__dict__, "path": snapshot.root / SETTLEMENT_DIRECTORY / name}
            )
        carried = _carried_settlement(snapshot, key)
        if carried is None:
            return ExactPRSettlementAbsent(key)
        payload, expected_digest = carried
        valid = _validate_settlement_payload(
            payload,
            key=key,
            current_observation_bytes=None,
            require_current_observation=False,
        )
        if valid.settlement_digest != expected_digest:
            raise ExactPRReconciliationRefused("carried settlement digest differs from its inventory binding")
        return ValidExactPRSettlement(**{**valid.__dict__, "carried": True})
    except (ExactPRReconciliationRefused, OSError, ValueError, TypeError) as error:
        return ExactPRTypedRefusal(key, str(error), snapshot.root / SETTLEMENT_DIRECTORY / name)


def _raw_evidence_records(body: bytes | None) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if body is None:
        return records
    if body and not body.endswith(b"\n"):
        raise ExactPRReconciliationRefused("evidence log has a torn tail")
    for index, line in enumerate(body.split(b"\n")[:-1] if body else (), start=1):
        raw = strict_json_bytes(line, label=f"evidence row {index}")
        key = raw.get("idempotency_key")
        if not isinstance(key, str):
            raise ExactPRReconciliationRefused(f"evidence row {index} has no string key")
        records[key] = raw
    return records


def effective_publication(
    snapshot: ExactPRStoreSnapshot,
    key: str,
) -> ExactPRSettlementAbsent | ExactPRTypedRefusal | dict:
    settlement = read_exact_pr_settlement(snapshot, key)
    if isinstance(settlement, ValidExactPRSettlement):
        return settlement_result(settlement)
    return settlement


def effective_blocking_keys(snapshot: ExactPRStoreSnapshot) -> tuple[str, ...]:
    blocked = {
        key
        for key, row in _raw_evidence_records(snapshot.evidence_bytes).items()
        if row.get("state") == TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value
    }
    for key in tuple(blocked):
        settlement = read_exact_pr_settlement(snapshot, key)
        if isinstance(settlement, ExactPRTypedRefusal):
            raise ExactPRReconciliationRefused(settlement.reason)
        if isinstance(settlement, ValidExactPRSettlement):
            blocked.remove(key)
    return tuple(sorted(blocked))


def owner_is_settlement_retired(
    owner_bytes: bytes,
    key: str,
    validated_settlements: Mapping[str, ValidExactPRSettlement] | tuple[ValidExactPRSettlement, ...],
) -> bool:
    values = (
        validated_settlements.values()
        if isinstance(validated_settlements, Mapping)
        else validated_settlements
    )
    digest = _sha256(owner_bytes)
    return any(
        settlement.key == key
        and settlement.payload["disposition"]["owner_bytes_sha256"] == digest
        for settlement in values
    )


def current_owner_is_settlement_retired(root: Path, owner_bytes: bytes, key: str) -> bool:
    snapshot = snapshot_exact_pr_store(root)
    settlement = read_exact_pr_settlement(snapshot, key)
    if isinstance(settlement, ExactPRTypedRefusal):
        raise ExactPRReconciliationRefused(settlement.reason)
    return isinstance(settlement, ValidExactPRSettlement) and owner_is_settlement_retired(
        owner_bytes, key, (settlement,)
    )


def settlement_result(settlement: ValidExactPRSettlement) -> dict:
    disposition = settlement.payload["disposition"]
    return {
        "schema": "ExactPRReconciliationResult.v1",
        "status": "exact_pr_reconciled",
        "raw_terminal_state": TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value,
        "effective_publication": True,
        "settlement_digest": settlement.settlement_digest,
        "disposition_digest": settlement.disposition_digest,
        "settlement_provenance": "receipt_carried" if settlement.carried else "immutable_per_key_file",
        "pr_url": disposition["pr_url"],
        "head_sha": disposition["head_sha"],
        "branch": disposition["head_ref"],
        "title": disposition["observed_title"],
        "title_equal": disposition["expected_title"] == disposition["observed_title"],
        "original_body_sha256": disposition["original_body_sha256"],
        "observed_body_sha256": disposition["observed_body_sha256"],
        "body_equal": disposition["original_body_sha256"] == disposition["observed_body_sha256"],
        "authorization_kind": disposition["authorization_kind"],
        "creator_attribution": disposition["creator_attribution"],
        "broker_created_pr": False,
        "independently_approved": False,
    }


def _find_checkpoint(authority_root: Path, transaction_id: str) -> tuple[Path, Path]:
    if not authority_root.is_absolute() or not authority_root.exists():
        raise ExactPRReconciliationRefused("authority root must be an existing absolute directory")
    candidates = sorted(authority_root.glob(f"publish-transactions/*/{transaction_id}.json"))
    if len(candidates) != 1:
        raise ExactPRReconciliationRefused(
            f"authority root contains {len(candidates)} exact checkpoints for transaction {transaction_id}"
        )
    checkpoint = candidates[0]
    return checkpoint, checkpoint.parent / "active.json"


def _ambiguity_line(evidence: bytes | None, key: str) -> bytes:
    latest = None
    for line in (evidence or b"").split(b"\n"):
        if not line:
            continue
        raw = strict_json_bytes(line, label="evidence ambiguity row")
        if (
            raw.get("idempotency_key") == key
            and raw.get("state") == TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value
        ):
            latest = line
    if latest is None:
        raise ExactPRReconciliationRefused("the exact effect key has no raw ambiguity row")
    return latest


def _capture_inputs(
    generation_root: Path,
    disposition: dict,
    checkpoint_path: Path,
    pointer_path: Path,
) -> _ReconciliationInputs:
    snapshot = snapshot_exact_pr_store(generation_root)
    checkpoint = _read_regular(checkpoint_path, label="publish checkpoint")
    pointer = _read_regular(pointer_path, label="active transaction pointer")
    owner_path = generation_root / "adapter-start-owner.json"
    owner = _read_regular(owner_path, label="adapter-start owner")
    ambiguity = _ambiguity_line(snapshot.evidence_bytes, disposition["effect_key"])
    return _ReconciliationInputs(
        snapshot, checkpoint_path, checkpoint, pointer_path, pointer, owner_path, owner, ambiguity
    )


def _subject(final_message: bytes) -> str:
    try:
        text = final_message.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExactPRReconciliationRefused("frozen final commit message is not UTF-8") from error
    return text.splitlines()[0] if text.splitlines() else ""


def _validate_local_inputs(inputs: _ReconciliationInputs, disposition: dict, worktree: Path) -> dict:
    from . import live

    checkpoint = strict_json_bytes(inputs.checkpoint_bytes, label="publish checkpoint")
    pointer = strict_json_bytes(inputs.pointer_bytes, label="active transaction pointer")
    owner = strict_json_bytes(inputs.owner_bytes, label="adapter-start owner")
    snapshot = inputs.snapshot
    expected_paths = {
        "authority_root": Path(disposition["authority_root"]),
        "checkpoint_path": Path(disposition["checkpoint_path"]),
        "active_transaction_pointer_path": Path(disposition["active_transaction_pointer_path"]),
    }
    if inputs.checkpoint_path != expected_paths["checkpoint_path"] or inputs.pointer_path != expected_paths["active_transaction_pointer_path"]:
        raise ExactPRReconciliationRefused("disposition paths do not name the resolved transaction inputs")
    repository = live.repository_snapshot(worktree)
    if repository.identity != disposition["canonical_repository_identity"]:
        raise ExactPRReconciliationRefused("worktree canonical identity differs from the disposition")
    if repository.common_dir != Path(disposition["repository_common_dir"]):
        raise ExactPRReconciliationRefused("worktree common directory differs from the disposition")
    if snapshot.root != getattr(repository, "store_" + "root"):
        raise ExactPRReconciliationRefused("store root is not the worktree's active canonical generation")
    if snapshot.receipt is None:
        raise ExactPRReconciliationRefused("active store has no authenticated partition receipt")
    if snapshot.generation != disposition["generation"]:
        raise ExactPRReconciliationRefused("active generation differs from the disposition")
    if snapshot.receipt_sha256 != disposition["partition_receipt_sha256"]:
        raise ExactPRReconciliationRefused("partition receipt digest differs from the disposition")
    if _sha256(inputs.checkpoint_bytes) != disposition["checkpoint_sha256"]:
        raise ExactPRReconciliationRefused("checkpoint digest differs from the disposition")
    if checkpoint.get("transaction_id") != disposition["transaction_id"]:
        raise ExactPRReconciliationRefused("checkpoint transaction differs from the disposition")
    if pointer.get("transaction_id") != disposition["transaction_id"]:
        raise ExactPRReconciliationRefused("active pointer differs from the transaction")
    bindings = {
        "canonical_repository_identity": disposition["canonical_repository_identity"],
        "branch": disposition["head_ref"],
        "committed_head_sha": disposition["head_sha"],
        "base": disposition["base_ref"],
        "draft": disposition["draft"],
        "pr_body": disposition["original_body"],
    }
    for key, expected in bindings.items():
        if checkpoint.get(key) != expected:
            raise ExactPRReconciliationRefused(f"checkpoint {key} differs from the disposition")
    if _sha256(str(checkpoint.get("pr_body", "")).encode("utf-8")) != disposition["original_body_sha256"]:
        raise ExactPRReconciliationRefused("checkpoint body digest differs from the disposition")
    try:
        final_message = base64.b64decode(checkpoint["final_message_b64"], validate=True)
    except (KeyError, ValueError, binascii.Error) as error:
        raise ExactPRReconciliationRefused("checkpoint final commit message is absent or malformed") from error
    if _subject(final_message) != disposition["expected_title"]:
        raise ExactPRReconciliationRefused("expected title is not the frozen final commit subject")
    if _sha256(inputs.owner_bytes) != disposition["owner_bytes_sha256"]:
        raise ExactPRReconciliationRefused("owner bytes differ from the disposition")
    owner_bindings = {
        "repository_identity": disposition["canonical_repository_identity"],
        "effect_key": disposition["effect_key"],
        "idempotency_key": disposition["effect_key"],
        "transaction_id": disposition["owner_transaction_id"],
        "owner_nonce": disposition["owner_nonce"],
        "committed_head": disposition["head_sha"],
        "sealed": False,
    }
    for key, expected in owner_bindings.items():
        if owner.get(key) != expected:
            raise ExactPRReconciliationRefused(f"adapter-start owner {key} differs from the disposition")
    if _sha256(inputs.ambiguity_line) != disposition["ambiguity_digest"]:
        raise ExactPRReconciliationRefused("raw ambiguity digest differs from the disposition")
    return checkpoint


def _validate_witness(witness: object, disposition: dict) -> dict:
    if not isinstance(witness, dict) or witness.get("schema") != "ExactPRProviderWitness.v1":
        raise ExactPRReconciliationRefused("provider witness is absent or unsupported")
    if witness.get("origin_repository") != f"{disposition['pr_host']}/{disposition['pr_repository']}":
        raise ExactPRReconciliationRefused("provider origin differs from the disposition")
    view = witness.get("view")
    listed = witness.get("all_state_branch_prs")
    remote = witness.get("remote_refs")
    if not isinstance(view, dict) or not isinstance(listed, list) or not isinstance(remote, list):
        raise ExactPRReconciliationRefused("provider witness has malformed observations")
    if len(listed) != 1:
        raise ExactPRReconciliationRefused("branch does not have exactly one all-state pull request")
    one = listed[0]
    expected_view = {
        "url": disposition["pr_url"],
        "number": disposition["pr_number"],
        "state": "OPEN",
        "isDraft": disposition["draft"],
        "mergedAt": None,
        "baseRefName": disposition["base_ref"],
        "headRefName": disposition["head_ref"],
        "headRefOid": disposition["head_sha"],
        "isCrossRepository": False,
        "title": disposition["observed_title"],
        "body": disposition["observed_body"],
    }
    for key, expected in expected_view.items():
        if view.get(key) != expected:
            raise ExactPRReconciliationRefused(f"provider view {key} differs from the disposition")
    if not isinstance(one, dict) or any(
        one.get(key) != expected
        for key, expected in {
            "number": disposition["pr_number"],
            "url": disposition["pr_url"],
            "headRefName": disposition["head_ref"],
            "headRefOid": disposition["head_sha"],
        }.items()
    ):
        raise ExactPRReconciliationRefused("all-state branch enumeration differs from the requested PR")
    head_repository = view.get("headRepository")
    head_name = (
        head_repository.get("nameWithOwner")
        if isinstance(head_repository, dict)
        else head_repository
    )
    if head_name != disposition["head_repository"]:
        raise ExactPRReconciliationRefused("provider head repository differs from the disposition")
    owner = view.get("headRepositoryOwner")
    expected_owner = disposition["head_repository"].split("/", 1)[0]
    if not isinstance(owner, dict) or owner.get("login") != expected_owner:
        raise ExactPRReconciliationRefused("provider head repository owner differs from the disposition")
    if remote != [{"head_sha": disposition["head_sha"], "ref": f"refs/heads/{disposition['head_ref']}"}]:
        raise ExactPRReconciliationRefused("provider remote ref differs from the frozen head")
    if witness.get("body_sha256") != disposition["observed_body_sha256"]:
        raise ExactPRReconciliationRefused("provider body digest differs from the disposition")
    return dict(witness)


def _existing_observation(inputs: _ReconciliationInputs, observation: dict) -> bool:
    from .evidence import UNREADABLE, _parse_post_ambiguity_observations

    parsed = _parse_post_ambiguity_observations(inputs.snapshot.observation_bytes or b"")
    if parsed is UNREADABLE:
        raise ExactPRReconciliationRefused("preexisting post-ambiguity observation file is unreadable")
    existing = parsed.get(observation["idempotency_key"], ())
    for row in existing:
        if row.row() != observation:
            raise ExactPRReconciliationRefused("preexisting observation for the key conflicts with the settlement")
    return bool(existing)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, body: bytes) -> None:
    view = memoryview(body)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write while staging exact-PR state")
        view = view[written:]


def _atomic_install_observation(root: Path, observation: dict) -> None:
    from .evidence import UNREADABLE, _parse_post_ambiguity_observations

    path = root / "post-ambiguity-observations.jsonl"
    existing = _read_optional_regular(path, label="post-ambiguity observations") or b""
    parsed = _parse_post_ambiguity_observations(existing)
    if parsed is UNREADABLE:
        raise ExactPRReconciliationRefused("preexisting post-ambiguity observation file is unreadable")
    line = _observation_line(observation)
    rows = parsed.get(observation["idempotency_key"], ())
    if rows:
        if any(row.row() != observation for row in rows):
            raise ExactPRReconciliationRefused("preexisting observation for the key conflicts with the settlement")
        return
    body = existing + line
    mode = stat.S_IMODE(os.lstat(path).st_mode) if path.exists() else 0o600
    temp = root / f".{path.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        if _EXACT_PR_CRASH_STEP == "partial_observation_temp":
            _write_all(descriptor, body[: max(1, len(body) // 2)])
            os.fsync(descriptor)
            _maybe_crash("partial_observation_temp")
        _write_all(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _maybe_crash("before_observation_replace")
    os.replace(temp, path)
    _fsync_directory(root)
    _maybe_crash("after_observation_replace")


def _install_settlement(root: Path, key: str, payload: dict) -> Path:
    directory = root / SETTLEMENT_DIRECTORY
    created = False
    try:
        os.mkdir(directory, 0o700)
        created = True
    except FileExistsError:
        status = os.lstat(directory)
        if stat.S_ISLNK(status.st_mode) or not stat.S_ISDIR(status.st_mode):
            raise ExactPRReconciliationRefused("settlement path is not a directory")
    if created:
        _fsync_directory(root)
    final = directory / settlement_filename(key)
    body = _canonical(payload) + b"\n"
    temp = directory / f".{final.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp"
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        if _EXACT_PR_CRASH_STEP == "partial_settlement_temp":
            _write_all(descriptor, body[: max(1, len(body) // 2)])
            os.fsync(descriptor)
            _maybe_crash("partial_settlement_temp")
        _write_all(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _maybe_crash("before_settlement_link")
    try:
        os.link(temp, final, follow_symlinks=False)
    except FileExistsError:
        winner = strict_json_bytes(_read_regular(final, label="existing exact-PR settlement"), label="existing exact-PR settlement")
        valid = _validate_settlement_payload(
            winner,
            key=key,
            current_observation_bytes=_read_optional_regular(
                root / "post-ambiguity-observations.jsonl", label="post-ambiguity observations"
            ),
            require_current_observation=True,
        )
        if valid.disposition_digest != payload["disposition_digest"]:
            raise ExactPRReconciliationRefused("a conflicting immutable settlement already won")
        os.unlink(temp)
        _fsync_directory(directory)
        return final
    _maybe_crash("after_settlement_link_before_directory_fsync")
    _fsync_directory(directory)
    try:
        os.unlink(temp)
    except FileNotFoundError:
        pass
    return final


def _durably_reaffirm_existing(settlement: ValidExactPRSettlement) -> None:
    """Finish durability after a possible response loss at the link seam."""
    if settlement.path is None:
        return
    descriptor = os.open(
        settlement.path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(settlement.path.parent)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _runtime_provenance() -> dict:
    import phase_loop_runtime

    source = Path(__file__)
    return {
        "phase_loop_runtime_version": phase_loop_runtime.__version__,
        "module": __name__,
        "module_sha256": _sha256(source.read_bytes()),
    }


def _build_settlement(
    inputs: _ReconciliationInputs,
    disposition: dict,
    witness: dict,
    observation: dict,
    *,
    observation_time: str,
) -> dict:
    payload = {
        "schema": SETTLEMENT_SCHEMA,
        "disposition": disposition,
        "disposition_digest": disposition_digest(disposition),
        "frozen_owner_bytes_b64": base64.b64encode(inputs.owner_bytes).decode("ascii"),
        "frozen_owner_sha256": _sha256(inputs.owner_bytes),
        "ambiguity_row_b64": base64.b64encode(inputs.ambiguity_line).decode("ascii"),
        "ambiguity_digest": _sha256(inputs.ambiguity_line),
        "observation": observation,
        "observation_sha256": _sha256(_observation_line(observation)),
        "provider_witness": witness,
        "observation_time_utc": observation_time,
        "committed_at_utc": _utc_now(),
        "runtime_provenance": _runtime_provenance(),
        "frozen_checkpoint": {
            "checkpoint_bytes_b64": base64.b64encode(inputs.checkpoint_bytes).decode("ascii"),
            "checkpoint_sha256": _sha256(inputs.checkpoint_bytes),
            "active_pointer_bytes_b64": base64.b64encode(inputs.pointer_bytes).decode("ascii"),
            "active_pointer_sha256": _sha256(inputs.pointer_bytes),
            "partition_receipt_bytes_b64": base64.b64encode(inputs.snapshot.receipt_bytes or b"").decode("ascii"),
            "partition_receipt_sha256": inputs.snapshot.receipt_sha256,
            "evidence_sha256": _sha256(inputs.snapshot.evidence_bytes or b""),
            "observation_prefix_sha256": _sha256(inputs.snapshot.observation_bytes or b""),
        },
    }
    payload["settlement_digest"] = settlement_digest(payload)
    return payload


def _observation_for(disposition: dict) -> dict:
    from .evidence import POST_AMBIGUITY_OBSERVATION_SCHEMA

    return {
        "idempotency_key": disposition["effect_key"],
        "observed_state": TerminalOutcomeState.EFFECT_TERMINAL_OBSERVED.value,
        "evidence_reference": disposition["pr_url"],
        "head_sha": disposition["head_sha"],
        "branch": disposition["head_ref"],
        "transaction_id": disposition["transaction_id"],
        "owner_nonce": disposition["owner_nonce"],
        "ambiguity_digest": disposition["ambiguity_digest"],
        "schema": POST_AMBIGUITY_OBSERVATION_SCHEMA,
    }


def _inputs_equal(left: _ReconciliationInputs, right: _ReconciliationInputs) -> bool:
    return (
        left.checkpoint_bytes == right.checkpoint_bytes
        and left.pointer_bytes == right.pointer_bytes
        and left.owner_bytes == right.owner_bytes
        and left.ambiguity_line == right.ambiguity_line
        and left.snapshot.receipt_bytes == right.snapshot.receipt_bytes
        and left.snapshot.evidence_bytes == right.snapshot.evidence_bytes
        and left.snapshot.observation_bytes == right.snapshot.observation_bytes
        and dict(left.snapshot.settlement_files) == dict(right.snapshot.settlement_files)
        and left.snapshot.generation == right.snapshot.generation
    )


def _existing_identical(snapshot: ExactPRStoreSnapshot, disposition: dict):
    existing = read_exact_pr_settlement(snapshot, disposition["effect_key"])
    if isinstance(existing, ExactPRTypedRefusal):
        raise ExactPRReconciliationRefused(existing.reason)
    if isinstance(existing, ValidExactPRSettlement):
        if existing.disposition_digest != disposition_digest(disposition):
            raise ExactPRReconciliationRefused("the exact effect key has a conflicting settlement request")
        return existing
    return None


def _read_witness_twice(adapter, disposition: dict) -> tuple[dict, str]:
    first = _validate_witness(
        adapter.read_exact_pr_witness(
            pr_url=disposition["pr_url"], branch=disposition["head_ref"]
        ),
        disposition,
    )
    second = _validate_witness(
        adapter.read_exact_pr_witness(
            pr_url=disposition["pr_url"], branch=disposition["head_ref"]
        ),
        disposition,
    )
    if _canonical(first) != _canonical(second):
        raise ExactPRReconciliationRefused("provider witness changed between the two complete reads")
    return second, _utc_now()


def _result_with_mode(settlement: ValidExactPRSettlement, *, check: bool) -> dict:
    result = settlement_result(settlement)
    result.update(
        check=check,
        commit_authorized=False if check else True,
        point_in_time=bool(check),
        point_in_time_limit=(
            "provider and local bytes may change after this check; commit repeats every validation"
            if check else None
        ),
    )
    return result


def reconcile_exact_pr(
    worktree: Path | str,
    *,
    authority_root: Path | str,
    transaction_id: str,
    pr_url: str,
    disposition: Mapping[str, Any],
    check: bool = False,
    run: Callable | None = None,
) -> dict:
    """Validate or durably install one exact-PR settlement.

    ``check`` opens no lock, takes no lease, and creates no path.  Commit mode
    holds a generation lease and the exact owner's inode exclusion across both
    complete provider observations, then compare-and-sets under admissions.lock.
    """
    import fcntl

    from . import live
    from .credsep import GitHubBrokerAdapter
    from .verbs import AdapterStartOwnerLive, _hold_owner_liveness

    disposition = validate_exact_pr_disposition(dict(disposition))
    worktree = Path(worktree).resolve()
    authority = Path(authority_root).expanduser()
    if not authority.is_absolute():
        raise ExactPRReconciliationRefused("authority root must be absolute")
    authority = authority.resolve()
    if Path(disposition["authority_root"]) != authority:
        raise ExactPRReconciliationRefused("disposition authority root differs from the requested authority")
    if transaction_id != disposition["transaction_id"] or pr_url != disposition["pr_url"]:
        raise ExactPRReconciliationRefused("command inputs differ from the disposition bindings")
    checkpoint_path, pointer_path = _find_checkpoint(authority, transaction_id)
    repository = live.repository_snapshot(worktree)
    generation_root = getattr(repository, "store_" + "root")
    initial_snapshot = snapshot_exact_pr_store(generation_root)
    existing = _existing_identical(initial_snapshot, disposition)
    if existing is not None:
        if not check:
            _durably_reaffirm_existing(existing)
        return _result_with_mode(existing, check=check)
    adapter = (
        GitHubBrokerAdapter(worktree)
        if run is None
        else GitHubBrokerAdapter(worktree, run=run)
    )

    if check:
        before = _capture_inputs(generation_root, disposition, checkpoint_path, pointer_path)
        checkpoint = _validate_local_inputs(before, disposition, worktree)
        _validate_commit_and_scope(adapter, checkpoint, disposition)
        _existing_observation(before, _observation_for(disposition))
        witness, observed_at = _read_witness_twice(adapter, disposition)
        after = _capture_inputs(generation_root, disposition, checkpoint_path, pointer_path)
        if not _inputs_equal(before, after):
            raise ExactPRReconciliationRefused("local authority changed during the point-in-time check")
        payload = _build_settlement(
            before, disposition, witness, _observation_for(disposition), observation_time=observed_at
        )
        preview = _validate_settlement_payload(
            payload,
            key=disposition["effect_key"],
            current_observation_bytes=_observation_line(_observation_for(disposition)),
            require_current_observation=True,
        )
        result = _result_with_mode(preview, check=True)
        result["status"] = "exact_pr_reconciliation_check_ready"
        result["temporary_files"] = list(before.snapshot.temporary_files)
        return result

    latch = live.WriterGenerationLatch.for_store_root(generation_root)
    if not latch.exists() or latch.read().generation_state != "ACTIVE":
        raise ExactPRReconciliationRefused("exact-PR commit requires the ACTIVE writer generation latch")
    lease = latch.acquire(generation=latch.read().generation)
    owner_descriptor: int | None = None
    owner_contended = False
    try:
        lock_path = generation_root / "admissions.lock"
        if _read_optional_regular(lock_path, label="admissions lock") is None:
            raise ExactPRReconciliationRefused("active store has no existing admissions lock")
        with lock_path.open("r+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                live.require_current_generation(generation_root, lease, strict=True)
                first = _capture_inputs(generation_root, disposition, checkpoint_path, pointer_path)
                existing = _existing_identical(first.snapshot, disposition)
                if existing is not None:
                    return _result_with_mode(existing, check=False)
                checkpoint = _validate_local_inputs(first, disposition, worktree)
                _validate_commit_and_scope(adapter, checkpoint, disposition)
                _existing_observation(first, _observation_for(disposition))
                try:
                    owner_descriptor = _hold_owner_liveness(generation_root)
                except AdapterStartOwnerLive:
                    owner_contended = True
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

        if owner_contended:
            # Another identical reconciler holds the exact owner's inode while
            # it observes the provider and installs the immutable winner.  Give
            # that bounded operation a chance to publish; an ordinary live
            # publisher still yields the established typed refusal.
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                existing = _existing_identical(
                    snapshot_exact_pr_store(generation_root), disposition
                )
                if existing is not None:
                    _durably_reaffirm_existing(existing)
                    return _result_with_mode(existing, check=False)
                time.sleep(0.025)
            raise AdapterStartOwnerLive(
                "adapter-start owner inode is locked by another live writer; retry"
            )

        witness, observed_at = _read_witness_twice(adapter, disposition)

        with lock_path.open("r+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                live.require_current_generation(generation_root, lease, strict=True)
                final_inputs = _capture_inputs(generation_root, disposition, checkpoint_path, pointer_path)
                existing = _existing_identical(final_inputs.snapshot, disposition)
                if existing is not None:
                    _durably_reaffirm_existing(existing)
                    return _result_with_mode(existing, check=False)
                if not _inputs_equal(first, final_inputs):
                    raise ExactPRReconciliationRefused("local authority changed between witness and commit")
                observation = _observation_for(disposition)
                _atomic_install_observation(generation_root, observation)
                payload = _build_settlement(
                    first, disposition, witness, observation, observation_time=observed_at
                )
                final_path = _install_settlement(generation_root, disposition["effect_key"], payload)
                installed_snapshot = snapshot_exact_pr_store(generation_root)
                installed = read_exact_pr_settlement(installed_snapshot, disposition["effect_key"])
                if not isinstance(installed, ValidExactPRSettlement):
                    reason = installed.reason if isinstance(installed, ExactPRTypedRefusal) else "settlement absent"
                    raise ExactPRReconciliationRefused(f"installed settlement did not validate: {reason}")
                if installed.path != final_path:
                    raise ExactPRReconciliationRefused("installed settlement resolved from an unexpected path")
                _maybe_crash("after_settlement_directory_fsync_before_response")
                return _result_with_mode(installed, check=False)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        if owner_descriptor is not None:
            os.close(owner_descriptor)
        lease.release()


def _validate_commit_and_scope(adapter, checkpoint: dict, disposition: dict) -> None:
    completed = adapter.run(
        ["git", "-C", str(adapter.repo_path), "cat-file", "commit", disposition["head_sha"]],
        capture_output=True,
        text=False,
    )
    if getattr(completed, "returncode", 1) != 0:
        raise ExactPRReconciliationRefused("frozen commit object cannot be read")
    body = getattr(completed, "stdout", None)
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, bytes) or _sha256(body) != checkpoint.get("final_commit_object_sha256"):
        raise ExactPRReconciliationRefused("frozen commit object digest differs from the checkpoint")
    subject_completed = adapter.run(
        ["git", "-C", str(adapter.repo_path), "log", "-1", "--format=%s", disposition["head_sha"]],
        capture_output=True,
        text=False,
    )
    if getattr(subject_completed, "returncode", 1) != 0:
        raise ExactPRReconciliationRefused("frozen commit subject cannot be read")
    subject = getattr(subject_completed, "stdout", b"")
    if isinstance(subject, str):
        subject = subject.encode("utf-8")
    try:
        actual_subject = subject.decode("utf-8").removesuffix("\n")
    except (AttributeError, UnicodeDecodeError) as error:
        raise ExactPRReconciliationRefused("frozen commit subject is not UTF-8") from error
    if actual_subject != disposition["expected_title"]:
        raise ExactPRReconciliationRefused("commit object subject differs from the disposition")
    changed = adapter._branch_diff_paths(disposition["base_ref"], disposition["head_sha"])
    if changed is None or not changed:
        raise ExactPRReconciliationRefused("frozen branch diff cannot be authenticated")
    owned = checkpoint.get("owned_paths")
    if not isinstance(owned, list) or any(
        not adapter._covered_by_owned(path, owned) for path in changed
    ):
        raise ExactPRReconciliationRefused("frozen branch diff exceeds the checkpoint's owned paths")


def inspect_exact_pr(
    worktree: Path | str,
    *,
    authority_root: Path | str,
    transaction_id: str,
) -> dict:
    """Inspect raw and effective state without creating authority or calling a provider."""
    from . import live

    worktree = Path(worktree).resolve()
    authority = Path(authority_root).expanduser()
    if not authority.is_absolute() or not authority.exists():
        raise ExactPRReconciliationRefused("authority root is absent or not absolute")
    authority = authority.resolve()
    checkpoint_path, pointer_path = _find_checkpoint(authority, transaction_id)
    checkpoint_bytes = _read_regular(checkpoint_path, label="publish checkpoint")
    checkpoint = strict_json_bytes(checkpoint_bytes, label="publish checkpoint")
    pointer = strict_json_bytes(_read_regular(pointer_path, label="active transaction pointer"), label="active transaction pointer")
    if checkpoint.get("transaction_id") != transaction_id or pointer.get("transaction_id") != transaction_id:
        raise ExactPRReconciliationRefused("transaction checkpoint and active pointer do not agree")
    repository = live.repository_snapshot(worktree)
    if checkpoint.get("canonical_repository_identity") != repository.identity:
        raise ExactPRReconciliationRefused("transaction belongs to another canonical repository")
    key = "publish_committed_branch\0" + publish_committed_branch_idempotency_key(
        repository.identity,
        checkpoint.get("branch", ""),
        checkpoint.get("committed_head_sha", ""),
    )
    snapshot = snapshot_exact_pr_store(getattr(repository, "store_" + "root"))
    raw = _raw_evidence_records(snapshot.evidence_bytes).get(key)
    effective = effective_publication(snapshot, key)
    result = {
        "schema": "ExactPRInspection.v1",
        "transaction_id": transaction_id,
        "effect_key": key,
        "store_root": str(snapshot.root),
        "generation": snapshot.generation,
        "raw_evidence": raw,
        "raw_state": raw.get("state") if isinstance(raw, dict) else None,
        "raw_blocked": bool(
            raw and raw.get("state") == TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value
        ),
        "effective_blocking_keys": list(effective_blocking_keys(snapshot)),
        "temporary_files": list(snapshot.temporary_files),
        "zero_write": True,
        "provider_called": False,
        "commit_authorized": False,
    }
    if isinstance(effective, dict):
        result["effective_result"] = effective
        result.update(
            effective_publication=bool(effective.get("effective_publication")),
            pr_url=effective.get("pr_url"),
            title_equal=effective.get("title_equal"),
            body_equal=effective.get("body_equal"),
            settlement_digest=effective.get("settlement_digest"),
            settlement_provenance=effective.get("settlement_provenance"),
        )
    elif isinstance(effective, ExactPRTypedRefusal):
        result["effective_refusal"] = effective.reason
        result["effective_publication"] = False
    else:
        result["effective_result"] = None
        result["effective_publication"] = False
    return result
