#!/usr/bin/env python3
"""Read-only preflight for ``phase-loop fabpub-rotate-partition``.

Runs the SAME zero-write checks ``rotate_blocked_partition`` runs before it
takes the predecessor's ``admissions.lock`` -- by calling the real functions
in the real order -- and then reports the two drain facts the ceremony's
DRAINING step will measure (held generation leases, live pre-FABPUB writers).
It never opens the latch lock, never writes the journal, never mkdirs.

A ``ready`` verdict means: the attestation adjudicates the predecessor exactly
as the verb will, the derived inventory builds, and no ceremony is in flight.
It does NOT mean the drain will succeed -- ``held_leases`` counts lease FILES,
and an orphaned lease blocks DRAINING regardless of whether its holder lives.

Exit: 0 ready / 1 the verb would refuse (reason printed) / 2 usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from phase_loop_runtime.convergence.broker import live as L


def _check(name: str, fn, report: dict):
    try:
        value = fn()
    except (
        L.PartitionRotationRefused,
        L.LegacyCutoverConflict,
        L.WriterGenerationBlocked,
    ) as error:
        report["checks"].append(
            {"check": name, "ok": False, "refusal": f"{type(error).__name__}: {error}"}
        )
        raise
    report["checks"].append({"check": name, "ok": True})
    return value


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--worktree", required=True, type=Path)
    ap.add_argument("--attestation", required=True, type=Path)
    ap.add_argument("--cutover-id", required=True)
    ap.add_argument("--authority-root", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    report: dict = {
        "schema": "FabpubRotationPreflight.v1",
        "verdict": None,
        "checks": [],
        "drain": {},
    }
    try:
        cutover_id = _check(
            "cutover_id", lambda: L._validate_cutover_id(a.cutover_id), report
        )
        attestation = json.loads(a.attestation.read_text(encoding="utf-8"))
        snapshot = _check(
            "repository_snapshot", lambda: L.repository_snapshot(a.worktree), report
        )
        container, identity, active = (
            snapshot.container,
            snapshot.identity,
            snapshot.store_root,
        )
        _root, generation = L._partition_layout(active)
        authority = L._canonical_input_path(
            a.authority_root or L.default_fabpub_authority_root(),
            label="authority root",
        )
        ceremony = authority / L.ROTATION_CEREMONY_DIR / identity
        journal = ceremony / f"{cutover_id}{L._ROTATION_JOURNAL_SUFFIX}"
        report.update(
            {
                "identity": identity,
                "container": str(container),
                "active_store_root": str(active),
                "active_generation": generation,
                "successor_generation": generation + 1,
                "authority_root": str(authority),
                "journal": str(journal),
            }
        )
        if a.attestation.resolve().is_relative_to(
            (authority / L.ROTATION_CEREMONY_DIR).resolve()
        ):
            raise L.PartitionRotationRefused(
                "attestation path lies under the authority's partition-rotations/"
            )

        def _base():
            base = L.load_partition_receipt(container)
            if base is None or isinstance(base, L.RotatedPartitionReceipt):
                raise L.PartitionRotationRefused(
                    f"no container partition receipt governs {container}"
                )
            return base

        base = _check("container_receipt", _base, report)
        report["container_receipt_schema"] = type(base).SCHEMA

        def _claim():
            claim = L._receipt_bootstrap_claim(base) if base.zero_source else None
            if claim is None or claim["authority_root"] != authority:
                raise L.PartitionRotationRefused(
                    f"{identity} is not a zero-history bootstrap partition under {authority}"
                )
            return claim

        _check("bootstrap_claim_binds_authority", _claim, report)

        def _active_auth():
            if not L._receipt_active_authority_exists(base, authority_root=authority):
                raise L.PartitionRotationRefused(
                    "the bootstrap authority is not ACTIVE"
                )

        _check("bootstrap_authority_active", _active_auth, report)

        def _not_ambiguous():
            if base.ambiguous:
                raise L.PartitionRotationRefused(
                    "container receipt is ambiguity-blocked"
                )

        _check("container_receipt_not_ambiguous", _not_ambiguous, report)

        def _active_receipt():
            if active == container:
                return base
            receipt = L.load_partition_receipt(active)
            if receipt is None:
                raise L.PartitionRotationRefused(
                    f"active generation {generation} carries no receipt"
                )
            if bool(getattr(receipt, "ambiguous", False)):
                raise L.PartitionRotationRefused(
                    f"active generation {generation} is ambiguity-blocked"
                )
            return receipt

        active_receipt = _check("active_receipt", _active_receipt, report)

        def _debris():
            for candidate in sorted(container.glob(f"{L.GENERATIONS_DIR}.tmp.*")):
                if candidate.name != f"{L.GENERATIONS_DIR}.tmp.{cutover_id}":
                    raise L.PartitionRotationRefused(
                        f"foreign rotation staging debris at {candidate}"
                    )

        _check("no_foreign_staging_debris", _debris, report)
        _check(
            "no_other_rotation_in_progress",
            lambda: L._refuse_other_rotations_in_progress(
                ceremony, journal, identity, cutover_id
            ),
            report,
        )
        states = _check(
            "own_journal", lambda: L._rotation_own_journal(journal, cutover_id), report
        )
        report["own_journal_states"] = list(states)
        if states and states[-1] == "ACTIVE":
            raise L.PartitionRotationRefused(
                f"rotation {cutover_id!r} already completed"
            )

        adjudicated = _check(
            "adjudicate_predecessor",
            lambda: L._adjudicate_rotation_predecessor(
                attestation,
                L._snapshot_predecessor(active),
                generation,
                active_receipt,
                identity,
            ),
            report,
        )
        report["adjudication"] = {
            "attestation_digest": adjudicated.digest,
            "predecessor_digests": dict(adjudicated.predecessor_digests),
            "effects": {
                k: dict(v) if isinstance(v, dict) else v
                for k, v in dict(adjudicated.effects).items()
            },
            "high_water": adjudicated.high_water,
            "carried": dict(adjudicated.carried),
        }
        derived = _check(
            "derive_inventory",
            lambda: L._derive_rotation_inventory(
                cutover_id=cutover_id,
                identity=identity,
                container=container,
                predecessor_receipt=active_receipt,
                successor_generation=generation + 1,
                generation=generation,
                predecessor_digests=adjudicated.predecessor_digests,
                attestation=attestation,
                digest=adjudicated.digest,
                effects=adjudicated.effects,
                high_water=adjudicated.high_water,
                carried=adjudicated.carried,
            ),
            report,
        )
        report["derived_inventory_schema"] = derived.get("schema")
        successor = container / L.GENERATIONS_DIR / str(generation + 1)
        if "INVENTORY_SEALED" not in states and successor.exists():
            raise L.PartitionRotationRefused(
                f"successor {successor} exists but was never sealed"
            )

        # -- drain facts (what DRAINING will measure; read-only, no latch lock) --
        latch = L.WriterGenerationLatch(snapshot.namespace_root)
        held = latch.held_leases()
        live = L.LegacyWriterQuiescence.inventory(a.worktree).live_writers()
        report["drain"] = {
            "latch_exists": latch.exists(),
            "latch": (
                {
                    "generation": latch.read().generation,
                    "generation_state": latch.read().generation_state,
                }
                if latch.exists()
                else None
            ),
            "armed_marker": latch.armed_marker.exists(),
            "held_leases": [str(p) for p in held],
            "live_pre_fabpub_writers": [w.get("process_identity") for w in live],
        }
        report["verdict"] = (
            "ready" if not held and not live else "ready_but_drain_will_block"
        )
        if held:
            report["drain"]["note"] = (
                f"{len(held)} lease file(s) present; await_quiescent counts FILES, so the ceremony "
                "will refuse at DRAINING (and leave a DRAINING journal row) until they are released"
            )
    except (
        L.PartitionRotationRefused,
        L.LegacyCutoverConflict,
        L.WriterGenerationBlocked,
    ) as error:
        report["verdict"] = "would_refuse"
        report["refusal"] = f"{type(error).__name__}: {error}"

    if a.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        for c in report["checks"]:
            print(
                ("ok   " if c["ok"] else "FAIL ")
                + c["check"]
                + ("" if c["ok"] else f"  -- {c['refusal']}")
            )
        print("verdict:", report["verdict"])
        if report.get("refusal"):
            print("refusal:", report["refusal"])
        d = report.get("drain") or {}
        if d:
            print(f"latch: {d.get('latch')} armed={d.get('armed_marker')}")
            print(
                f"held leases: {len(d.get('held_leases', []))}  live writers: {len(d.get('live_pre_fabpub_writers', []))}"
            )
            for p in d.get("held_leases", []):
                print("  lease", p)
            if d.get("note"):
                print("note:", d["note"])
    return 0 if report["verdict"] in ("ready",) else 1


if __name__ == "__main__":
    sys.exit(main())
