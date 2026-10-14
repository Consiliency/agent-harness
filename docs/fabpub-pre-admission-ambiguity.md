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

## Owner section refusals and liveness

Two narrowings of what becomes `outcome_ambiguous_blocked`. Neither relaxes C-keep:
an unsealed owner whose writer is gone, and that has no known terminal, is still
promoted exactly as before.

- **A refused section leaves no owner (agent-harness#1314).** Inside the one
  `admissions.lock` acquisition, `_owner_and_admission_under_one_lock` reads the raw
  bytes of `adapter-start-owner.json` (absent, or a sealed owner), writes this
  attempt's owner, and calls `admit_next`. If anything refuses after the owner write
  (generation lease, partition floor, `epoch_blocked`, policy, the request build, the
  admission append), it puts those exact bytes back, or removes the file if there
  were none, before the refusal propagates. The owner never reached the provider, so
  no effect is possible, and no other writer can observe it, because the restore
  happens under the same acquisition. Only an owner this attempt wrote is ever
  restored. A simulated crash (`PublishCrashInjected`) gets no cleanup, as a real
  crash would not.
- **A live writer's owner is not promoted (agent-harness#1313).** From the owner write
  until its attempt ends, the writer holds an advisory `flock` on the owner file's
  inode. Before `_block_unsealed_owner` appends `provider_call_in_flight` or
  `outcome_ambiguous_blocked` for an owner with no known terminal, it probes that
  lock non-blocking. If it is held, the publish refuses with `AdapterStartOwnerLive`
  (a `PermissionError` whose message says to retry), and nothing is written. The
  kernel releases the lock when the writer process dies, so a crashed writer's owner
  is promoted as before. No file and no owner field were added, so mixed versions are
  unchanged: an older writer never takes the lock and its owner is promoted as
  before, and an older reader ignores the lock. The lock relies on the same `flock`
  coherence that `admissions.lock` already does. On NFS, where Linux emulates `flock`
  with per-process POSIX locks, a probe from the writer's own process can read the
  writer as dead (today's behaviour), and a crashed client's lock lasts until its
  lease expires (a retryable refusal meanwhile).

## Provider entry and failures around it

The broker returns the state the store holds. It never invents a terminal state. It
enters the provider only after, within one `admissions.lock` acquisition, the on-disk
owner equalled this attempt's (nonce included) and was unsealed and the key's row was
`provider_call_in_flight`. A promotion landing at any point from that lock's release
through the provider call is not covered (agent-harness#1591).

- **A guard right before the provider call (agent-harness#1577).** Under one
  `admissions.lock` acquisition, `BrokerService._provider_entry_guard` checks that the
  on-disk owner is exactly this attempt's owner (nonce included) and unsealed, and
  that the key's evidence row is `provider_call_in_flight`. If not, the attempt makes
  no provider call and writes nothing. It returns the stored row (normally
  `outcome_ambiguous_blocked`) with reason `outcome_ambiguous` and
  `provider_call_made: false`, and the checkpoint stays `BROKER_INTENT_DURABLE`.
  This covers an older-runtime prober that promotes a live writer's owner after the
  owner section and before the guard. Such a prober does not honour the
  agent-harness#1313 liveness lock.
- **Promotion from the guard's lock release through the provider call is not covered
  (agent-harness#1591).** The guard releases `admissions.lock` before the
  `ADAPTER_STARTED` projection, request finalization, the service-generation lease
  acquisition and the call itself, and nothing re-checks after it. A promotion
  landing anywhere in that interval still makes one provider call, reported with
  `provider_call_made: true`, and the key stays ambiguous.
- **Mixed versions.** The agent-harness#1313 liveness lock and this guard protect a
  partition only once every runtime that writes it is upgraded. An older writer
  has neither. The window from the guard's lock release through the provider call remains
  regardless. Until every writer
  is upgraded, an `attested_not_landed` attestation needs provider-side evidence,
  such as the provider showing no pull request and no branch for the head. Absence of
  local evidence is not enough. Provider-side absence is still the operator's
  judgement, not proof (see the runbook's §3).
- **A failure after the provider returned is not ambiguity when the terminal is
  durable (agent-harness#1574).** If the owner seal or the `TERMINAL_SEALED`
  projection fails after the terminal was recorded, the broker returns that
  terminal. The owner may stay unsealed with a known terminal. The next fresh
  publish's `_block_unsealed_owner` seals it, and a retry replays the terminal. A
  failure inside the provider call is still recorded as `outcome_ambiguous_blocked`.
- **A failure before the provider was entered is not ambiguity either.** A refused
  service-generation lease (a `DRAINING` writer latch) is re-raised as
  `ProviderEntryRefused`, with the same message. Nothing is recorded beyond the
  `provider_call_in_flight` intent (see "Human-route handoffs for broker refusals").
- **Failures between the owner section and the provider call (agent-harness#1578).**
  If the `ADMISSION_DURABLE` checkpoint projection itself fails while the checkpoint
  is still `COMMITTED_HEAD_RESOLVED`, the broker restores the owner bytes the
  section found. The restore takes a fresh `admissions.lock` acquisition. It runs
  only if the generation still authorizes this writer, the owner is exactly this
  attempt's, and the key has no evidence row. The admission line it leaves is
  harmless, because `admit_next` dedups the retry by attempt id. Every other failure
  in this window leaves the owner and the checkpoint as they are. That covers a
  projection that became durable and then reported failure, `record_intent`, the
  later projections, the guard's own authorization, and the lease refusal above.
  Those failures fail closed and a rotation recovers them. The next attempt promotes
  the owner, and `attested_not_landed` is truthful there because the provider was
  never entered. Restoring the owner there would be wrong. Once the checkpoint is
  admitted, a retry without an owner is refused by the already-admitted recovery
  check, and no rotation can dispose a key that has no evidence.
- A blocked publish result from `publish_from_worktree` now carries
  `provider_call_made`. It is true only when this call entered the provider adapter.
  A replay of stored evidence reports false.

## Human-route handoffs for broker refusals

The human route (`publish_human_invoked_from_worktree`) picks its handoff by the
type of the broker refusal, never by its message. Every type below is a
`PermissionError` subclass, so existing `except PermissionError` callers are
unaffected, and its message is unchanged. Each refusal is raised before provider
entry, and the result carries `provider_call_made: false`. Any other
`PermissionError` keeps `repair_fabpub_authority`.

| Refusal | Type | `next_step` |
|---|---|---|
| A routing client was built before a rotation moved the ACTIVE generation (agent-harness#1315) | `RoutingClientGenerationRetired` (a `WriterGenerationBlocked`) | `rebuild_broker_client_and_retry`: close the client and build a new one, or restart the broker process |
| The owner's writer is still running, or the section was contended twice | `AdapterStartOwnerLive`, `AdapterStartOwnerContended` | `retry_after_inflight_publication`: retry shortly; no rotation |
| An unsealed owner was promoted, or the epoch is blocked by a key in this generation | `UnsealedOwnerBlocksPartition`, `PartitionEpochBlocked` | `adjudicate_publication_by_partition_rotation`, with `blocking_effect_keys` (and `blocking_transaction_id` for an owner); the attestation disposes the blocking key, which may not be this publication's |
| A refusal after the admission is durable and before provider entry: `record_intent`, the guard's authorization, a refused service-generation lease | `ProviderEntryRefused` (`effect_key`, `transaction_id`; the original is `__cause__`) | `retry_once_before_partition_rotation`: retry once, then follow the handoff the retry returns |

A `PartitionEpochBlocked` that names no key in the store keeps
`repair_fabpub_authority`. In that case the block is the partition receipt's
carried legacy ambiguity, which a rotation does not adjudicate.

Why retry once (agent-harness#1594 SA-F2). After a pre-provider refusal, the key's
row is still `provider_call_in_flight` and the owner is unsealed. A rotation refuses
that state with "intents without a terminal". The retry promotes the owner to
`outcome_ambiguous_blocked`, refuses with `UnsealedOwnerBlocksPartition` and returns
the rotation handoff for this key and transaction. Keep the first result: its
`provider_call_made: false` and refusal detail are the only record that the provider
was never entered. The ambiguous row cannot be told apart from a crash during the
call.

Every rotation handoff cites runbook §§1, 3, 4, 6, 7 and 8a. It also says the
rotation must use the route's `FABPUB_AUTHORITY_ROOT` (or `--authority-root`), and
it repeats the warning against a second `attested_not_landed` without new evidence
(agent-harness#1574 ask 2).

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

  A failed publication leaves its publish transaction past
  `COMMITTED_HEAD_RESOLVED`: `TERMINAL_SEALED` when the provider returned an
  ambiguous terminal (for example `push-unconfirmed`), or `ADAPTER_STARTED` or
  earlier after an adapter exception or crash. A retry of the same, unchanged
  head resumes that transaction, and the successor re-admits it as-is
  (agent-harness#1296): same transaction, commit, ref, owned paths and
  plan/verification digests. It does so only when a receipt in the partition's
  authenticated chain disposes the key `attested_not_landed` **and** the
  sealed attestation's `transaction_id` (bound from the predecessor's
  adapter-start owner) equals the transaction being admitted. The retry's `base`,
  `draft` and PR body must also equal the transaction's frozen values, because the
  provider request is built from them. The broker never moves the checkpoint during
  a recovery; the SDK closeout in `publish_from_worktree` seals it after the observed
  terminal, which releases the active pointer for the next head. Before any owner or
  admission is written, the authorization is recorded once beside the checkpoint as
  `<transaction_id>.recovery.<generation>.json` (`PublishTransactionRecovery.v1`:
  rotation, attestation and inventory digests, predecessor owner nonce, ambiguity
  digest, the state the transaction was recovered from, commit, ref, paths,
  plan/proof digests, and the frozen base, draft and PR-body digest). The record is
  owner-only (0600), written atomically through an exclusive no-follow temporary file,
  and read back no-follow; an existing record that is not a regular JSON file refuses
  typed. The outcome lives in that generation's evidence.

  The disposing rotation need not be the latest one (agent-harness#1310). The
  recovery walks the authenticated receipt chain from the active generation back to
  the first receipt that adjudicates the key. That newest adjudication is the current
  word: a newer `observed_landed`, or a newer re-attestation, hides an older one. When
  a rotation intervened, the record also names the `disposing_generation`, the
  `readmitting_generation` (its `generation`) and the `intervening_rotations`. With no
  intervening rotation it carries none of them and is byte-for-byte the
  agent-harness#1296 record, so a runtime of either version that retries in the same
  generation computes the same record (agent-harness#1576). A reader also accepts a
  record that carries the three fields with their no-rotation values (empty
  `intervening_rotations`, both generations equal to `generation`), the shape the
  agent-harness#1550 runtime wrote. Any other difference refuses with
  `PublishTransactionConflict` before any owner write, and the human handoff names the
  record as `conflicting_recovery_record`. A disposition authorizes one
  re-admission. Every generation from the disposing one up to the active one must hold
  no evidence and no adapter-start owner for the key, and no receipt on the walk may
  carry it as completed. Sealed generations are checked against the bytes their
  successor receipts sealed. The active generation is checked under the admissions
  lock, because the broker leaves the checkpoint where it is. If the recovered attempt
  is ambiguous again, that generation blocks like any partition.

  Any other already-admitted current-head transaction is refused with
  `PublicationRecoveryRequired` before any owner, admission or evidence write. The
  message names what did not bind and the next step for that case. In particular, when
  no receipt in the chain disposes the key and the active generation holds no
  evidence for it, **no rotation can help**: an attestation disposes only keys that
  are blocked in the active generation. That case needs the maintainer. The human route reports these
  refusals as `publication_recovery_required` with next step
  `resolve_publication_recovery_refusal`.

  Before any rotation, the key's evidence is `outcome_ambiguous_blocked` and the
  broker replays it on every retry. The human route reports that block, on the first
  attempt and on every retry, with next step
  `adjudicate_publication_by_partition_rotation` and the rotate command, not the
  generic `repair_publication_precheck_and_retry`; it matches the typed
  `terminal_state` that `publish_from_worktree` now returns on a broker-blocked
  result (agent-harness#1312).

  Separately, the broker now checks the transaction-state precondition **before** it
  writes the adapter-start owner, so a refusal of that precondition no longer leaves
  an unsealed owner that the next attempt would promote to permanent ambiguity. Every
  other refusal inside admission restores the owner path to the exact bytes it held
  (see "Owner section refusals and liveness" below, agent-harness#1314).

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
