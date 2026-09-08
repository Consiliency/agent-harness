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

**What happened in ah#789:** nothing was published. The incident record (step 5)
states that no further publish was attempted and that no direct push, evidence
rewrite, flag disablement, or replacement authority root was used; the responder
correctly refused to improvise a recovery. The intended branch for transaction
`b72b68ff…` is still unpublished by the governed path, and the partition stays
blocked.

**What C-keep sanctions going forward (prospective policy, not yet exercised):**
a documented, recorded, **one-time** operator override outside the governed
path — the operator publishes the intended branch by hand and records what was
done, against which transaction, on the issue. No command sequence is
prescribed here, because none has been executed or reviewed. Anything beyond a
recorded manual publication is a contract change and needs review.

Two consequences to plan around:

1. An out-of-band publication does **not** clear the block. The partition stays
   `epoch_blocked`; the next governed publish for that repository still refuses.
2. Do not resolve the ambiguity by reading the remote. "No branch on origin" and
   "`ls-remote` timed out" are the same observation to this runtime, and neither
   is evidence of no effect.

## Partition rotation (deferred)

The supported way to restore governed publication for a permanently blocked
repository is a reviewed **partition rotation**: retire the blocked partition
into `historical_evidence_roots` and onboard a fresh receipt for the same
canonical repository identity. That is Workstream D of the ah#789 plan and is
deferred to its own detailed plan; it is not implemented.

Carried item, stated so it is not mistaken for done: ah#789 acceptance item (5)'s
first half — "a completed recovery can publish the exact intended branch once" —
has **no** governed path under C-keep, because partition rotation is the only
governed recovery and it is deferred. Consiliency/agent-harness#789 stays open
after Workstreams A, B and the C-keep deliverables land.

## Controls

`phase-loop-runtime/tests/test_fabpub_recovery_controls_789.py` pins the two
properties C-keep chose to keep:

- a blocked partition refuses a fresh publish of the exact intended branch with
  every `git ls-remote` route replaced by a raising sentinel, writes no owner and
  no admission, and leaves `evidence.jsonl` byte-identical;
- blocking one repository partition leaves an unrelated partition in the same
  authority root publishable exactly once — one admission, one adapter call —
  while the first stays blocked.
