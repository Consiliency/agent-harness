# Pre-admission publication ambiguity (FABPUB)

Operator note for the state Consiliency/agent-harness#789 hit: a governed FABPUB
publication that failed **before** admission, left a durable adapter-start owner
behind, and therefore permanently blocked its repository partition.

Paths below are relative to the repository root; line numbers are for
`phase-loop-runtime/src/phase_loop_runtime/` on the tree that carries this file.

## What a pre-admission ambiguity is

`BrokerService._fresh_publish` (`convergence/broker/verbs.py:518`) makes the
adapter-start owner durable **before** it allocates an admission, so that a crash
between the two cannot be mistaken for "nothing happened". On the next attempt it
reads that owner back and, if the owner is unsealed, asks
`_block_unsealed_owner` (`verbs.py:530-532`, defined at `verbs.py:375`) to
resolve it. An unsealed owner with no terminal is an **unknown provider effect**:
the runtime cannot prove the adapter was never entered, so it durably promotes
the effect key to `outcome_ambiguous_blocked`.

That record blocks the whole repository partition:
`BrokerEvidenceStore.epoch_blocked` (`convergence/broker/evidence.py:86-95`)
scans one store root, and `_fresh_publish` refuses on it with
`PermissionError("epoch permanently blocked")` (`verbs.py:533-534`). The scope is
one repository, by construction — "each repo gets its OWN admission + evidence
store … the stores are NOT shared" (the `_RoutingBrokerService` class docstring in
`convergence/broker/live.py`).

The block is permanent at the storage layer, not just by convention: no append
may transition out of an `outcome_ambiguous_blocked` record, whatever the caller
path (`evidence.py:229-230`).

## Why it stays permanent (decision: C-keep, 2026-09-06)

The tempting relaxation is to prove "no effect" from local chronology — an owner
with no intent record means the adapter was never entered — and retire the owner
as `no_effect_terminal_proven`. The maintainer rejected that (plan
`plans/detailed-789-fabpub-pre-admission-compat-20260906.md`, Workstream C):

- That proof is only as strong as the **weakest runtime version** that can write
  owners into the shared store. Consiliency/agent-harness#789 was precisely a
  version-skew incident, and a skewed writer with a different write order would
  turn intent-absence into a false no-effect proof.
- Absence of the branch on the remote is **not** evidence either. A `git ls-remote`
  that returns nothing, or times out, is consistent with an effect that has not
  landed yet; the runtime therefore must not consult the remote when deciding a
  refusal (Consiliency/agent-harness#789 acceptance item 3).

Under C-keep the ah#789 ambiguity record is left in place. Neither this note nor
any code in this repository rewrites transaction
`b72b68ff03f2058ff0ea29641e5f003e89fa3ca1e298079eba7b6f1ff09655f8` or unblocks
repository partition `1da3e3433e00173dec7aaa5ca564038a1df5ccd64498be0506aab80b579e7681`.

## What was done about the cause

Workstream A (Consiliency/agent-harness#803) removes the recurrence from this
cause. An admission store whose records an installed runtime cannot read now
raises a typed `AdmissionStoreIncompatible` refusal **before** durable owner
acquisition, and owner + admission are taken under one `admissions.lock`
acquisition. A stale runtime therefore refuses with an actionable compatibility
message instead of stranding an unsealed owner, so this class of pre-admission
ambiguity should not recur from a reader-schema skew.

Workstream B (Consiliency/agent-harness#804) removes the second blocker the
incident hit: a sealed bootstrap inventory whose recorded worktree has since been
pruned no longer fails the activation barrier.

## Recovery

There is **no governed recovery** for a partition that is already blocked. What
the runtime offers is a refusal, not a repair.

**What happened in ah#789, in order.** The governed publish refused and the
partition stayed blocked; the responder did not improvise a repair. The incident
record's step 5 — "no further publish was attempted … no direct push, evidence
rewrite, flag disablement, or replacement authority root was used" — describes
the state at that moment, **not** the final state.

On 2026-09-06 the maintainer authorised and recorded a **one-time manual
publication outside the governed path** (the "Operator override recorded"
comment on Consiliency/agent-harness#789): the exact durable candidate
`076f1e5d87acba21b87c188e3a70a0f319b79e60` was pushed as branch
`codex/audit-remediation-roadmap` and opened as draft Consiliency/omniagent-plus#28.
Not touched: the `outcome_ambiguous_blocked` record for transaction
`b72b68ff…`, the authority inventory and journal, the locked bootstrap
worktrees, the checkpoint root. No retry, no root rotation, no evidence rewrite.

So the intended branch **is** published, and it is published out of band. It is
still unpublished *by the governed path*, and the partition is still blocked.

**What C-keep sanctions** is exactly that shape: a documented, recorded,
**one-time** operator override outside the governed path — publish the intended
branch by hand, record what was done and against which transaction on the issue.
This note prescribes no command sequence; the ah#789 override comment is the
record of the one that was performed. Anything beyond a recorded manual
publication is a contract change and needs review.

Two consequences to plan around:

1. An out-of-band publication does **not** clear the block. The partition stays
   `epoch_blocked`; the next governed publish for that repository still refuses.
2. Do not resolve the ambiguity by reading the remote. "No branch on origin" and
   "`ls-remote` timed out" are the same observation to this runtime, and neither
   is evidence of no effect.

## Partition rotation

The supported way to restore governed publication for a permanently blocked
repository is a reviewed **partition rotation**: the blocked partition is
retired as a read-only predecessor generation and a fresh, authenticated
generation is onboarded for the same canonical repository identity. Workstream D
of the ah#789 plan (`plans/detailed-789d-fabpub-partition-rotation-20260908.md`)
landed it in Consiliency/agent-harness#816 (the ceremony, the v3 receipt, and the
generational resolver) and Consiliency/agent-harness#818 (the operator verb below).

### The verb

```
phase-loop fabpub-rotate-partition \
    --worktree <repo> \
    --attestation <operator-written attestation.json> \
    --cutover-id <rotation id> [--authority-root <dir>] [--json]
```

The verb loads the attestation document and drives
`rotate_blocked_partition(...)` (`phase_loop_runtime.convergence.broker.live`).
On success it prints one `PartitionRotationResult.v1` JSON document naming the
successor generation, its store root, the predecessor store root, the receipt's
`attestation_sha256`, and the adjudicated effect keys; every refusal is exit 1
with `phase-loop fabpub-rotate-partition: <reason>` on stderr. Re-running the
same command after a completed rotation is the idempotent resume: it answers
with the same document and creates no second generation.

What a refusal leaves behind depends on where the ceremony stopped, and the
verb does not paper over the difference:

- **Validation refusals** — an unreadable, wrong-schema, or ceremony-directory
  attestation, an undisposed blocked key, an unknown disposition, digests that
  do not match, a predecessor that is not `epoch_blocked`, or another cutover
  id already in progress — happen before the ceremony's first journal row.
  They leave **no durable rotation state**: no journal, no inventory, no
  successor directory; the writer latch is untouched.
- **Refusals after durable progress** keep the journal for that
  `--cutover-id`. The first durable step is the `DRAINING` row, written before
  the ceremony waits for predecessor writers; if they do not drain, the verb
  refuses with `predecessor writers did not drain: …`, resumes the writer
  latch to ACTIVE with its nonce preserved, and the `DRAINING` row stays. The
  same holds when the predecessor bytes changed between attestation and drain
  (`re-attest over the current bytes`): the inventory is not yet sealed, so
  the resume takes the re-written attestation. Once the rotation has reached
  the pointer flip the successor stays routed, and the finish step can stop in
  one of two states: a refusal that names the successor's authentication
  (`does not authenticate`, `carries no receipt`, `loads as a different
  receipt`) **withholds** the `ACTIVE` journal row (the journal stays at
  `ARMED`) and the latch activation; a crash or refusal *after* the row — the
  writer latch is missing, or its activation fails — leaves the `ACTIVE` row
  durable with only the latch activation owed. In every case generation 0's
  bytes are never rewritten.
- **Recovery** is the same command with the same `--cutover-id`, over the
  same attestation except after a `re-attest` refusal: the ceremony resumes
  from the journal's last durable state (a drain refusal re-waits for the
  writers; a post-flip stop re-runs the finish, which appends the `ACTIVE` row
  only when it is absent and then activates the latch). A re-run never
  repairs its inputs: the resumed step re-performs only its own writes, and
  everything it reads must still be what the ceremony left (the
  re-attestation above is the one input the verb itself asks for). After the
  flip the successor is authenticated through the real loader before the
  ceremony's resume branch, and that authentication is a chain —
  `generations/<n>/partition-receipt.json`, the container receipt, the
  ceremony journal `partition-rotations/<identity>/<id>.journal.jsonl`, the
  sealed inventory `<id>.inventory.json` beside it, and generation 0's
  digested store files (`admissions.jsonl`, `evidence.jsonl`,
  `partition-receipt.json`, `adapter-start-owner.json`) — and the finish then
  requires the writer latch to exist and to read `DRAINING` (or already
  `ACTIVE`, the idempotent re-run). Any of these damaged *after* the flip by
  something other than the ceremony is refused on
  every re-run and never repaired; the refusal identifies the failing check
  (for example `the sealed rotation inventory digest drifted`, or `has no
  writer generation latch`), not necessarily the damaged file — when it
  reports that the receipt bytes and the sealed partition disagree, either
  side may have drifted, so compare both against pre-flip copies. A sealed
  inventory that still authenticates but is no longer what re-adjudicating
  the attestation derives is refused by the resume's derivation check. There
  is no repair verb: restore the damaged bytes from outside the ceremony and
  the same command finishes (Consiliency/agent-harness#789 carries the gap). A
  **different** cutover id is refused while a journal for this
  identity is not yet `ACTIVE` — `rotation '<id>' for <identity> is still in
  progress; resume it under its own cutover_id before starting '<other>'` — so
  an operator cannot fork a second rotation over an unfinished one.

The attestation is **operator-supplied**. The verb refuses a document that lies
inside the authority root's `partition-rotations/` ceremony directory before
reading it: a sealed rotation inventory embeds a copy of the attestation it was
sealed from, and resuming from that copy would be circular. Write the
attestation somewhere else and hand the verb that path. The authority root the
guard checks against is derived once — `~` expanded, absolute, symlinks
resolved, exactly as the ceremony derives it — and the ceremony receives that
same path, so no spelling of `--authority-root` can make the guard and the
ceremony disagree about where the ceremony directory is.

### The attestation

`PartitionRotationAttestation.v1` is the reviewed human judgement the ceremony
binds into the successor receipt. Its required fields:

| field | meaning |
|---|---|
| `schema` | `PartitionRotationAttestation.v1` |
| `attested_by` | the operator making the attestation (non-empty string) |
| `predecessor_generation` | the generation being retired (0 for a never-rotated partition) |
| `predecessor_receipt_digest` | sha256 of the predecessor's `partition-receipt.json` bytes — the receipt the attestation was written against |
| `predecessor_store_digests` | the sha256 of every digested predecessor store file (`admissions.jsonl`, `evidence.jsonl`, `partition-receipt.json`, `adapter-start-owner.json`; a missing file digests as empty bytes), as the ceremony re-captures them under the predecessor's own `admissions.lock` |
| `effects` | one entry per blocked effect key, keyed by the exact FABPUB dedup key (`publish_committed_branch\0<hex>`) |

Each `effects` entry carries a `disposition`, an `evidence_url` (the
out-of-band publication or the review that established the judgement; a
non-empty string), and the `ambiguity_digest` binding it to the predecessor's
recorded ambiguity — the sha256 of the blocked row's raw JSONL line text, no
trailing newline. The owner fields bind in **both** directions: when the
predecessor's `adapter-start-owner.json` names that key (as `effect_key` or
`idempotency_key`), the entry must carry the owner's `owner_nonce` and
`transaction_id` verbatim, and when it does not name the key the entry must
carry neither — the ceremony refuses an entry that disagrees with the owner
record in either direction.
Extra fields (an `attested_at`, an `override_record` URL) are tolerated — the
attestation digest binds the whole document — so record provenance there rather
than in `attested_by`. The dispositions:

- `observed_landed` — the effect did land out of band; `observed_head` names the
  landed head. The ceremony seals the key into the successor's completed
  effects, so the pre-dispatch replay answers a later governed publish of that
  key as a duplicate: no owner is read, the adapter is never called.
- `attested_not_landed` — the effect did not land; `observed_head` must be
  absent. The key is **not** carried, so the successor publishes it afresh
  exactly once, after which ordinary idempotency holds.

A blocked key the attestation leaves undisposed, a disposition it does not know,
digests that do not match the predecessor's bytes, or a predecessor that is not
`epoch_blocked` are all typed `PartitionRotationRefused` refusals before any
durable write. A key whose latest predecessor row is `no_effect_terminal_proven`
is not carried either (the successor publishes it afresh).

### What the ceremony guarantees

- The predecessor generation is never rewritten. Its bytes are digested under
  its own lock, sealed into the rotation inventory, and left in place as
  historical evidence; the successor lives under `generations/<n>/` and the
  `generations/ACTIVE` pointer is the only thing the flip writes.
- The sealed inventory is digest-bound to the successor receipt. A later
  publish (or the ceremony's own finish) that finds inventory bytes the receipt
  does not digest refuses with `LegacyCutoverConflict: … is not the inventory
  the partition receipt digests`; a receipt that names completed keys whose
  inventory has gone missing refuses with `… is missing`; receipt bytes that are
  not JSON refuse with the same typed conflict instead of a bare `ValueError`.
- No network or `git ls-remote` call happens anywhere in the ceremony. The
  attestation is the only source of "landed"/"not landed".
- **Restart requirement.** A `phase-loop-runtime` broker process that resolved
  the repository before the flip holds a lease on the retired generation; its
  next write is a typed refusal until it restarts and resolves the successor.
  The verb's result says so (`restart_required`). Before rotating, stop every
  writer of that partition, and re-pin every installed runtime that can write
  FABPUB state to a build that recognises
  `LegacyRepositoryPartitionReceipt.v3` — a pre-v3 runtime cannot read the
  successor and is refused, never silently unblocked.

Carried items, stated so they are not mistaken for done: the omniagent-plus
partition blocked in the incident has **not** been rotated — that is Lane D5 of
the plan, an operational step under its own maintainer authorisation after the
runtime re-pin above. The step-by-step operator procedure, the read-only
preflight, and the rehearsal technique are in
`docs/fabpub-partition-rotation-runbook.md`. Until it runs, ah#789 acceptance item (5)'s first half —
"a completed recovery can publish the exact intended branch once" — is a
capability (`test_fabpub_partition_rotation_789d.py` A2) rather than an
observed outcome for that repository, and Consiliency/agent-harness#789 stays
open.

## Controls

`phase-loop-runtime/tests/test_fabpub_recovery_controls_789.py` pins the two
properties C-keep chose to keep:

- a blocked partition refuses a fresh publish of the exact intended branch with
  every `git ls-remote` route replaced by a raising sentinel, writes no owner and
  no admission, and leaves `evidence.jsonl` byte-identical;
- blocking one repository partition leaves an unrelated partition in the same
  authority root publishable exactly once — one admission, one adapter call —
  while the first stays blocked.
