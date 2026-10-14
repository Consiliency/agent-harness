#!/usr/bin/env python3
"""Build a ``PartitionRotationAttestation.v1`` for one blocked effect key.

Read-only against the live broker container; the only write is ``--out``, and
that destination is refused when it lands inside a broker namespace, a
generational store, or an authority's ``partition-rotations/`` ceremony state
(the CLI's ``_load_rotation_attestation`` refuses to READ such a path; this
refuses to WRITE one, so a mistyped ``--out`` cannot land on a sealed
inventory).  The field shape mirrors
``live.py::_adjudicate_rotation_predecessor`` -- the adjudicator, not the docs,
is the authority -- and the read-only preflight
(``fabpub_rotation_preflight.py``) validates the result against it.

Only the ``observed_landed`` disposition is produced (the omniagent-plus incident
shape); an ``attested_not_landed`` entry is written by hand from the same
digests.  Only a generation-0 container is accepted: the digested bytes are
read at the container root, so pointing this at a rotated store would build an
attestation whose ``predecessor_generation`` and digests disagree.  See
``docs/fabpub-partition-rotation-runbook.md``.

It also prints any post-ambiguity observation the broker recorded for the key
(agent-harness#1591) and warns when ``--observed-head`` or ``--evidence-url``
disagree with an observed effect; it never refuses on one.

Stdlib only, on purpose: it must run under any python, including one with no
``phase_loop_runtime`` on its path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

DIGESTED = (
    "admissions.jsonl",
    "evidence.jsonl",
    "partition-receipt.json",
    "adapter-start-owner.json",
)
PREFIX = "publish_committed_branch\0"
# agent-harness#1591: provider outcomes recorded after the key became ambiguous.
# Not digested; read here only to show the operator what the broker saw.
OBSERVATIONS = "post-ambiguity-observations.jsonl"
# Path names that mean "live broker or ceremony state, never an operator file".
# ``generations`` is deliberately NOT here: a generational store only exists
# inside a ``phase-loop-fabpub-broker-v1`` namespace, which this already catches,
# and listing it would refuse an operator directory that merely uses the word.
FORBIDDEN_PARTS = frozenset({"phase-loop-fabpub-broker-v1", "partition-rotations"})
# ``LegacyRepositoryPartitionReceipt``'s schema -- the generation-0 container
# receipt.  A rotated generation carries ``...v3`` (``RotatedPartitionReceipt``);
# refuse anything that is not the container shape rather than digest the wrong
# generation's bytes.
CONTAINER_RECEIPT_SCHEMA = "LegacyRepositoryPartitionReceipt.v2"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _read_digested(container: Path, name: str) -> bytes:
    """Read one digested file, or ``b""`` when it is absent.

    ``_snapshot_predecessor`` digests a missing file as ``sha256(b"")``; a
    container with no admitted publish yet has no ``admissions.jsonl``, and the
    attestation must agree with the ceremony rather than crash.
    """
    try:
        return (container / name).read_bytes()
    except FileNotFoundError:
        return b""


def _refuse_live_destination(out: Path, container: Path) -> str | None:
    """Return a refusal reason when ``--out`` is not an operator-owned path."""
    resolved = out.resolve()
    parts = set(resolved.parts)
    hit = parts & FORBIDDEN_PARTS
    if hit:
        return f"--out {resolved} lies under {sorted(hit)[0]}/ (live broker or ceremony state)"
    namespace = container.resolve().parent.parent
    if resolved == namespace or resolved.is_relative_to(namespace):
        return f"--out {resolved} lies under the broker namespace {namespace}"
    return None


def _post_ambiguity_observations(container: Path, key: str):
    """Rows for ``key``, or ``None`` when the side file cannot be read."""
    body = _read_digested(container, OBSERVATIONS)
    if body and not body.endswith(b"\n"):
        return None
    rows = []
    try:
        for raw in body.decode("utf-8").split("\n")[:-1] if body else []:
            row = json.loads(raw)
            if not isinstance(row, dict):
                return None
            if row.get("idempotency_key") == key:
                rows.append(row)
    except ValueError:
        return None
    return rows


def _print_observations(observations, entry: dict, a) -> None:
    """Show what the broker recorded and warn where this attestation disagrees with it."""
    if observations is None:
        print(
            f"WARNING: {OBSERVATIONS} is unreadable; the ceremony refuses attested_not_landed "
            "for every key while it is"
        )
        return
    if not observations:
        print("post-ambiguity observation none recorded for this key")
        return
    for row in observations:
        print(
            "post-ambiguity observation",
            row.get("observed_state"),
            row.get("evidence_reference"),
            "head",
            row.get("head_sha"),
            "binds this blocked row"
            if row.get("ambiguity_digest") == entry["ambiguity_digest"]
            else "does NOT bind this blocked row",
        )
        if row.get("observed_state") != "effect_terminal_observed":
            continue
        if row.get("head_sha") != a.observed_head:
            print(
                f"WARNING: --observed-head {a.observed_head} differs from the observed head "
                f"{row.get('head_sha')}"
            )
        if row.get("evidence_reference") != a.evidence_url:
            print(
                f"WARNING: --evidence-url {a.evidence_url} differs from the observed evidence "
                f"{row.get('evidence_reference')}"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--attested-by", required=True)
    ap.add_argument("--observed-head", required=True)
    ap.add_argument("--evidence-url", required=True)
    ap.add_argument("--override-record", default=None)
    ap.add_argument(
        "--effect-key-suffix", required=True, help="hex effect id after the NUL prefix"
    )
    a = ap.parse_args()

    c = a.container
    refusal = _refuse_live_destination(a.out, c)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    digests = {n: sha(_read_digested(c, n)) for n in DIGESTED}
    receipt_bytes = _read_digested(c, "partition-receipt.json")
    if not receipt_bytes:
        print(f"--container {c} carries no partition-receipt.json", file=sys.stderr)
        return 2
    receipt = json.loads(receipt_bytes)
    if receipt.get("schema") != CONTAINER_RECEIPT_SCHEMA:
        print(
            f"--container {c} carries {receipt.get('schema')!r}, not "
            f"{CONTAINER_RECEIPT_SCHEMA!r}: this builder digests the generation-0 bytes "
            "at the container root only",
            file=sys.stderr,
        )
        return 2
    owner_bytes = _read_digested(c, "adapter-start-owner.json")
    owner = json.loads(owner_bytes) if owner_bytes else {}
    key = PREFIX + a.effect_key_suffix

    blocked_line = None
    for raw in _read_digested(c, "evidence.jsonl").decode("utf-8").split("\n")[:-1]:
        if not raw.strip():
            continue
        row = json.loads(raw)
        if (
            row.get("idempotency_key") == key
            and row.get("state") == "outcome_ambiguous_blocked"
        ):
            blocked_line = raw
    if blocked_line is None:
        print("no outcome_ambiguous_blocked row for key", repr(key), file=sys.stderr)
        return 2

    entry = {
        "disposition": "observed_landed",
        "observed_head": a.observed_head,
        "evidence_url": a.evidence_url,
        "ambiguity_digest": sha(blocked_line.encode("utf-8")),
    }
    # The adjudicator requires ``owner_nonce``/``transaction_id`` when the owner
    # record names THIS key, and refuses an entry that carries them when it does
    # not.  Emit exactly the half that matches the owner on disk.
    # ``_rotation_owner_identity`` accepts either spelling of the owner's key.
    owner_names_key = key in (owner.get("effect_key"), owner.get("idempotency_key"))
    if owner_names_key:
        for field in ("owner_nonce", "transaction_id"):
            if owner.get(field) is not None:
                entry[field] = owner[field]
    if a.override_record:
        entry["override_record"] = a.override_record
    observations = _post_ambiguity_observations(c, key)
    doc = {
        "schema": "PartitionRotationAttestation.v1",
        "attested_by": a.attested_by,
        "attested_at": dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "predecessor_generation": 0,
        "predecessor_receipt_digest": digests["partition-receipt.json"],
        "predecessor_store_digests": digests,
        "effects": {key: entry},
        "notes": {
            "repository_identity": owner.get("repository_identity"),
            "predecessor_receipt_schema": receipt.get("schema"),
            "predecessor_cutover_id": receipt.get("cutover_id"),
            "owner_committed_head": owner.get("committed_head"),
        },
    }
    body = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(body)
    print(a.out)
    print("sha256", sha(body.encode()))
    print("blocked-row sha256", entry["ambiguity_digest"])
    print(
        "owner record",
        "names this key (owner_nonce/transaction_id emitted)"
        if owner_names_key
        else f"names {owner.get('effect_key') or owner.get('idempotency_key')!r}, not this key (owner fields omitted)",
    )
    _print_observations(observations, entry, a)
    print(
        "owner committed_head",
        owner.get("committed_head"),
        "== observed_head"
        if owner.get("committed_head") == a.observed_head
        else "!= observed_head",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
