#!/usr/bin/env python3
"""Build a ``PartitionRotationAttestation.v1`` for one blocked effect key.

Read-only against the live broker container; the only write is ``--out``.
The field shape mirrors ``live.py::_adjudicate_rotation_predecessor`` — the
adjudicator, not the docs, is the authority — and the read-only preflight
(``fabpub_rotation_preflight.py``) validates the result against it.

Only the ``observed_landed`` disposition is produced (the omniagent-plus incident
shape); an ``attested_not_landed`` entry is written by hand from the same
digests. See ``docs/fabpub-partition-rotation-runbook.md``.
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


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


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
    digests = {n: sha((c / n).read_bytes()) for n in DIGESTED}
    receipt = json.loads((c / "partition-receipt.json").read_text())
    owner = json.loads((c / "adapter-start-owner.json").read_text())
    key = PREFIX + a.effect_key_suffix

    blocked_line = None
    for raw in (c / "evidence.jsonl").read_bytes().decode("utf-8").split("\n")[:-1]:
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
    if owner.get("effect_key") != key:
        print("owner record names a different effect key", file=sys.stderr)
        return 2

    entry = {
        "disposition": "observed_landed",
        "observed_head": a.observed_head,
        "evidence_url": a.evidence_url,
        "ambiguity_digest": sha(blocked_line.encode("utf-8")),
        "owner_nonce": owner["owner_nonce"],
        "transaction_id": owner["transaction_id"],
    }
    if a.override_record:
        entry["override_record"] = a.override_record
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
            "repository_identity": owner["repository_identity"],
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
        "owner committed_head",
        owner.get("committed_head"),
        "== observed_head"
        if owner.get("committed_head") == a.observed_head
        else "!= observed_head",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
