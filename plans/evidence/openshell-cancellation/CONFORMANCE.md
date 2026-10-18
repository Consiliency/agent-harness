# OpenShell destruction-confirmed cancellation: implementation r2

Status: foundational server ledger implemented; endpoint NOT conforming or ready.
No activation, deployment, guest patch, provider run, or public push is authorized by
this artifact. Owner approval on 2026-10-18 authorizes the amended C6 semantics and
implementation; live qualification remains separate.

## Required barrier (owner-approved text)

**OpenShell launch barrier.** One lease per sandbox generation. The barrier is
confirmed destruction of every generation bound to the lease: the supervisor and
VMM have exited and its state is removed, every create issued for the lease is
settled and anything it produced is destroyed, and no fenced sandbox identity is
ever reused, restarted or recovered. An absent record while a create is unresolved
does not confirm the barrier. A lease's execute claim and its fence are one record,
changed by compare-and-set, so exactly one of them is first.

Only an execute claimed before the durable fence may start during pending
cancellation. Neither authenticated receipt nor the durable fence proves that a
previously dispatched command cannot start. Success requires the barrier; timeout
keeps obligations and reports release unconfirmed. No request is retried to restore
execution. No result from a cancelled run is imported.

## Implemented unit

Private NVIDIA/OpenShell checkout, base
`5a7728c304b5528e954e9ae900cf21f84e1a12b1`, branch `fix/cancellation-foundation-r2`.
Source: `crates/openshell-server/src/cancellation_lease.rs` and its tests, declared
from the existing server library. The final private report records commit and
patch hashes and exact executed checks.

The ledger uses the existing Store's durable `put_if`, `MustCreate`, and
`MatchResourceVersion`, following the existing reconciler lease's JSON-object
pattern. It adds no database, public protocol, service, or timer. Records retain
principal class/provider/subject, workspace, owner, lease, create request and
sandbox identity, generation, terminal fence and one-shot execute claim. No
credential, stdin, command or replayable request body is stored. Tombstones have
no expiration or deletion path.

Unseen kill inserts a terminal row. Reservation precedes any create dispatch and
cannot replace an existing row. Claim and fence contend on one revision. A lost
claim reply never authorizes another claim. Late terminal create results can be
recorded after fencing, retaining cleanup until exact sandbox/generation evidence
is supplied. Absent lookup is not a create-settlement operation. Recovery predicates
refuse missing, unresolved, fenced or previously claimed leases. Full keyset listing
retains unresolved reservations and propagates page/decode/authentication errors.

This module is intentionally **not called by current RPCs or compute lifecycle**.
Its destruction method is an internal evidence sink, not verified VM destruction.
Its barrier boolean covers only the represented create/generation obligations;
it must not become kill success until all remaining obligations below are wired.
Its listing is a recovery inventory, not a cross-page snapshot/release certificate.

## Remaining integration and acceptance gates

1. Enroll owner IDs under authorized authenticated principals/workspaces at ingress;
   reject sandbox/peer/anonymous/local-development principals. Preserve principal
   binding across approved identity rotation. The constructor and per-row checks
   are implemented; enrollment and workspace authorization are not.
2. Bind each generated immutable sandbox UUID to one lease globally, without reuse.
   Wire reservation before create, terminal completion after create, claim before
   exec, and fence before cancellation effects. Prevent direct create/exec/transfer,
   restart, supervisor attachment, and recovery from bypassing lease authority.
3. Wire compute deletion to generation-specific supervisor/VMM exit and state
   removal. `DeletionOutcome::Accepted`, `AlreadyAbsent`, a missing store row, or
   a caller-supplied generation string is not proof. Retain all uncertain creates;
   reconcile without replaying a fenced create or any execute. Test crash/lost-reply
   boundaries at the actual driver, including old envelopes across VMM exit.
4. Account for transfer publication/partial files, artifacts and every cleanup
   obligation before clean listing or acknowledgement. Implement complete consistent
   owner listing and reconciliation, including unknown resources and store-loss
   refusal. The foundational scan is not sufficient for this endpoint contract.
5. Apply existing caller bounds with timeout/unconfirmed mapping and endpoint-owned
   cleanup. Load fences before recovery. Add validated administrator defaults and
   allowed user/repo overrides through the authoritative settings files; do not
   invent timing constants. The separate driver/settings worker owns that work.
6. Run real endpoint falsifiers with child-start witnesses, source/image/driver
   digests, fixed-end enforcement, credential-path and isolation evidence, and
   live remote implementation acceptance. SQLite ledger tests and fake transports
   cannot certify these properties. PostgreSQL CAS/restart qualification remains.

## Deterministic evidence scope

The server tests exercise the actual SQLite-backed Store, including a file-backed
reopen, stale revision rejection in both claim/fence orderings, concurrent claim
writers, unseen kill, unresolved create, exact create-request settlement, sandbox
and generation mismatch, retained listing, principal spoofing and malformed
later-page records. Pending claims and late-create obligations are also exercised
across database reopen. They do not spawn a guest or VMM and do not demonstrate a
physical no-start barrier. A claim-first test explicitly keeps cancellation pending;
its comment is not a child-side execution witness.

Harness tests cover matching C6 copies and the rendered pending-risk notice,
alongside existing placement/lease/launchspec regressions as recorded in REPORT.md.
