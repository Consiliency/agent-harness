#!/usr/bin/env python3
"""Read-only preflight for ``phase-loop fabpub-rotate-partition``.

Runs the SAME zero-write checks ``rotate_blocked_partition`` runs before it
can succeed -- by calling the real functions in the real order -- and
then reports the two drain facts the ceremony's DRAINING step will measure
(held generation leases, live pre-FABPUB writers).  It never opens the latch
lock, never calls ``begin_draining``, never writes the journal, never mkdirs.

Verdicts:

``ready``
    the attestation adjudicates the predecessor exactly as the verb will, the
    derived inventory builds, the writer latch admits a rotation, and no
    ceremony is in flight.  It does NOT mean the drain will succeed --
    ``held_leases`` counts lease FILES, and an orphaned lease blocks DRAINING
    regardless of whether its holder lives.
``ready_but_drain_will_block``
    every pre-journal check passes but a lease file or a live pre-FABPUB
    writer is present, so the ceremony will refuse at DRAINING.
``already_completed``
    the active generation is already this ceremony's successor: the verb would
    resume idempotently through its post-flip completion path (which this
    script mirrors, adjudicating the PREDECESSOR generation and requiring the
    sealed inventory to derive from THIS attestation).
``would_refuse``
    the verb would refuse; the refusal text is printed.

Exit: 0 the verb would succeed (``ready`` / ``already_completed``) / 1 the verb
would refuse or the drain will block / 2 usage.  The first-execution go-gate in
the runbook is the string ``ready``, not merely exit 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from phase_loop_runtime.convergence.broker import live as L

# Every refusal class ``phase-loop fabpub-rotate-partition`` catches and turns
# into a non-zero exit (cli.py's ``except`` list for the verb).
REFUSALS = (
    L.PartitionRotationRefused,
    L.PartitionRoutingRefused,
    L.PartitionReceiptIncompatible,
    L.LegacyCutoverConflict,
    L.WriterGenerationBlocked,
)


def _check(name: str, fn, report: dict):
    try:
        value = fn()
    except REFUSALS as error:
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
        inventory_path = ceremony / f"{cutover_id}.inventory.json"
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

        # The CLI guards the attestation's location BEFORE reading it
        # (``_load_rotation_attestation``); mirror that order, and turn an
        # unreadable or malformed document into a verdict rather than a
        # traceback -- the CLI's ``except`` list catches OSError/ValueError too.
        def _attestation():
            if (
                a.attestation.expanduser()
                .resolve()
                .is_relative_to((authority / L.ROTATION_CEREMONY_DIR).resolve())
            ):
                raise L.PartitionRotationRefused(
                    "attestation path lies under the authority's partition-rotations/"
                )
            try:
                document = json.loads(
                    a.attestation.expanduser().read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as error:
                raise L.PartitionRotationRefused(
                    f"attestation {a.attestation} is not readable JSON: {error}"
                ) from error
            if not isinstance(document, dict):
                # the CLI's own text (``_load_rotation_attestation``), so the
                # operator reads the same refusal from either tool.
                raise L.PartitionRotationRefused(
                    f"the attestation at {a.attestation} is not a JSON object"
                )
            return document

        attestation = _check("attestation_readable", _attestation, report)

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

        # -- post-flip completion (live.py's matching-successor branch) --------
        # The pointer already names THIS ceremony's successor: the verb finishes
        # idempotently, but only after adjudicating the PREDECESSOR generation
        # and requiring the sealed inventory to derive from THIS attestation.
        # Mirror the whole zero-write prefix of that branch, in its order.
        if (
            isinstance(active_receipt, L.RotatedPartitionReceipt)
            and active_receipt.cutover_id == cutover_id
        ):
            report["resume"] = "post_flip_completion"

            def _predecessor_receipt():
                predecessor = L._rotation_predecessor_root(container, generation)
                if predecessor == container:
                    return predecessor, base
                receipt = L.load_partition_receipt(predecessor)
                if receipt is None:
                    raise L.PartitionRotationRefused(
                        f"predecessor generation {generation - 1} of {identity} carries no receipt"
                    )
                return predecessor, receipt

            predecessor, predecessor_receipt = _check(
                "completion_predecessor_receipt", _predecessor_receipt, report
            )
            adjudicated = _check(
                "completion_adjudicate_predecessor",
                lambda: L._adjudicate_rotation_predecessor(
                    attestation,
                    L._snapshot_predecessor(predecessor),
                    generation - 1,
                    predecessor_receipt,
                    identity,
                ),
                report,
            )
            _check(
                "completion_sealed_inventory_derives",
                lambda: L._require_sealed_inventory_derives(
                    inventory_path,
                    cutover_id,
                    identity,
                    adjudicated.digest,
                    L._derive_rotation_inventory(
                        cutover_id=cutover_id,
                        identity=identity,
                        container=container,
                        predecessor_receipt=predecessor_receipt,
                        successor_generation=generation,
                        generation=generation - 1,
                        predecessor_digests=adjudicated.predecessor_digests,
                        attestation=attestation,
                        digest=adjudicated.digest,
                        effects=adjudicated.effects,
                        high_water=adjudicated.high_water,
                        carried=adjudicated.carried,
                    ),
                    successor_generation=generation,
                    generation=generation - 1,
                ),
                report,
            )

            # Defence in depth, not coverage: ``active_receipt`` above already
            # authenticates the successor receipt, and that authentication reads
            # the journal's own ARMED row -- so a journal without it refuses
            # there and this row can never be the one that fails.  It mirrors a
            # real verb gate (live.py:4817) and is kept for that reason.
            def _armed():
                if "ARMED" not in states:
                    raise L.PartitionRotationRefused(
                        f"generation {generation} of {identity} is routed but rotation "
                        f"{cutover_id!r} never reached ARMED: {states}"
                    )

            _check("completion_journal_armed", _armed, report)
            report["verdict"] = "already_completed"
            report["note"] = (
                f"generation {generation} is already {cutover_id!r}'s successor; the verb would "
                "finish the ACTIVE row and the latch activation idempotently under the successor's "
                "lock.  Resume with the attestation the ceremony SEALED -- a rebuilt one changes "
                "the digest and the sealed inventory will not derive from it."
            )
        else:
            if states and states[-1] == "ACTIVE":
                raise L.PartitionRotationRefused(
                    f"rotation {cutover_id!r} already completed but does not govern the "
                    "active generation"
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

            # Pre-flip resume: the ceremony already sealed an inventory, and the
            # verb requires that sealed document to be the one THIS attestation
            # derives (live.py's ``_require_sealed_inventory_derives``).  A
            # rebuilt attestation changes the digest and refuses here.
            def _sealed():
                if "INVENTORY_SEALED" in states:
                    return L._require_sealed_inventory_derives(
                        inventory_path,
                        cutover_id,
                        identity,
                        adjudicated.digest,
                        derived,
                        successor_generation=generation + 1,
                        generation=generation,
                    )
                if successor.exists():
                    raise L.PartitionRotationRefused(
                        f"successor {successor} exists but was never sealed"
                    )
                return None

            _check("sealed_inventory_derives", _sealed, report)

        # -- the writer latch ---------------------------------------------
        # Both paths gate on the SAME repository-common latch, and neither row
        # below is ever recorded without evaluating its body: a check that
        # returns early would report `ok` for a gate that never ran.
        latch = L.WriterGenerationLatch(snapshot.namespace_root)

        def _latch_state():
            if not latch.exists():
                raise L.PartitionRotationRefused(
                    f"{identity} has no writer generation latch"
                )
            try:
                return latch.read().generation_state
            except (ValueError, KeyError, TypeError) as error:
                # The verb raises the same exception from the same ``read()``,
                # so this is not a divergence in outcome -- but the docstring
                # promises a verdict rather than a traceback, and an operator
                # reading a malformed latch deserves one.
                raise L.PartitionRotationRefused(
                    f"the writer generation latch of {identity} is unreadable: "
                    f"{type(error).__name__}: {error}"
                ) from error

        if report.get("verdict") == "already_completed":
            # ``_finish_rotation_after_flip`` runs under the SUCCESSOR's lock and
            # applies its own latch gates: existence (live.py:4845) and then
            # ``activate()``, which returns for ACTIVE and refuses anything but
            # DRAINING (live.py:658-663).  Both sit AFTER the ACTIVE journal
            # append, so a refusal there has a durable write behind it and must
            # never read as a go.
            #
            # It does NOT gate on the ARMED marker: ``mark_armed()`` runs first
            # (live.py:4847) and creates it, so requiring it here would be a
            # false refusal.  Witnessed: with the marker deleted and the latch
            # DRAINING, the verb completes and recreates it.
            def _completion_latch():
                state = _latch_state()
                if state not in ("DRAINING", "ACTIVE"):
                    raise L.PartitionRotationRefused(
                        f"the post-flip finish would refuse: illegal generation transition "
                        f"{state} -> ACTIVE"
                    )

            _check("completion_writer_latch", _completion_latch, report)
        else:

            def _latch_admits():
                state = _latch_state()
                if state not in ("ACTIVE", "DRAINING"):
                    raise L.PartitionRotationRefused(
                        f"writer generation latch of {identity} is {state}; "
                        "rotation requires ACTIVE"
                    )

            _check("writer_latch_admits_rotation", _latch_admits, report)

        # -- drain facts (what DRAINING will measure; read-only, no latch lock) --
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
        if report["verdict"] is None:
            report["verdict"] = (
                "ready" if not held and not live else "ready_but_drain_will_block"
            )
        if held:
            report["drain"]["note"] = (
                f"{len(held)} lease file(s) present; await_quiescent counts FILES, so the ceremony "
                "will refuse at DRAINING (and leave a DRAINING journal row) until they are released"
            )
    except REFUSALS as error:
        report["verdict"] = "would_refuse"
        report["refusal"] = f"{type(error).__name__}: {error}"
        # a note written on the way to a verdict this refusal overwrote would
        # otherwise describe an outcome the report no longer reaches.
        report.pop("note", None)

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
        if report.get("note"):
            print("note:", report["note"])
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
    return 0 if report["verdict"] in ("ready", "already_completed") else 1


if __name__ == "__main__":
    sys.exit(main())
