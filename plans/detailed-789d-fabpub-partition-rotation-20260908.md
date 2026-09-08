# Detailed plan: FABPUB partition rotation — the governed recovery for a permanently blocked repository partition (ah#789 Workstream D)

status: draft 2026-09-08 — awaiting maintainer approval; no runtime edits made
owner: Claude Code session `session_01Rv2aKsUWdEKoWfB5PTpD1B`
issue: Consiliency/agent-harness#789 (Workstream D; acceptance item (5) first half)
base: `ef6a9b18a0eb47981ebf07f56e6fc3d6bbe742d8` (origin/main, 2026-09-08 — carries ah#803/#804/#805)
landing tier: `plan` — cross-vendor board under `plans/decision-interim-president-ratification-20260904.md` (Consiliency/agent-harness#773); ledger row on landing
predecessor: `plans/detailed-789-fabpub-pre-admission-compat-20260906.md` (Workstreams A/B/C; D deferred there to this document)

## Task

Restore **governed** FABPUB publication for a repository whose partition is permanently
`epoch_blocked`, without weakening the permanent-ambiguity contract and without the runtime ever
inferring effect-absence from the remote. Concretely: discharge ah#789 acceptance item (5)'s first
half — "a completed recovery can publish the exact intended branch once" — as a general capability,
and give the one partition that is blocked today an executable route back.

## Measured starting state (read-only inspection, 2026-09-08, host `claw`)

Recorded here because the plan's shape depends on it; every value was read, none inferred.

- Authority root `~/.local/state/phase-loop/fabpub/authority-v1`, bootstrap `fabpub-host-bootstrap-20260904`,
  journal `DRAINING → INVENTORY_SEALED → ARMED → ACTIVE`, pointer `ACTIVE_BOOTSTRAP` (schema
  `ZeroHistoryBootstrapAuthority.v1`).
- **Exactly one blocked partition:** `1da3e3433e00173dec7aaa5ca564038a1df5ccd64498be0506aab80b579e7681`
  = `omniagent-plus`. Its `evidence.jsonl` holds two completed effects (`…58033572`, `…0a68fc6a`, both
  `effect_terminal_observed` → omniagent-plus#17) and one blocked effect `…54771bd3`
  (`provider_call_in_flight` → `outcome_ambiguous_blocked`, reference `unsealed-adapter-start-owner`).
  `admissions.jsonl` has rows for epochs 1 and 2 only — **none** for `…54771bd3`, confirming the
  failure was pre-admission. `adapter-start-owner.json` is present with `sealed: false`,
  `transaction_id b72b68ff…`, `committed_head 076f1e5d…`.
- The partition receipt is `LegacyRepositoryPartitionReceipt.v2`, `ambiguous: false`, `zero_source: true`,
  `legacy_epoch_high_water: 0`, `legacy_completed_effect_keys: []`. **The block therefore comes from the
  canonical evidence row** (`evidence.py:86-95`), not from a legacy-carried receipt
  (`live.py:856-865`).
- The other two partitions on this host are clean: `agent-harness` `50fea8e4…` and `EZBidPro`
  `1a3e011c…`, receipts `ambiguous: false`, no blocked records, no `"ambiguous": true` receipt anywhere.
  Host `ai` carries no FABPUB broker state. The Windows host was **not** checked (its scan errored) —
  see Dependencies.
- `publish_committed_branch_idempotency_key` is `sha256(repo \0 branch \0 head_sha)`
  (`convergence/contracts.py:20-22`), where `repo` on this path is the **serialized canonical repository
  identity** — `request.repo` as `_dedup_key` passes it (`verbs.py:255-262`), i.e. the literal string
  `1da3e3433e00173dec7aaa5ca564038a1df5ccd64498be0506aab80b579e7681`. Recomputing it from that identity, branch
  `codex/audit-remediation-roadmap` and head `076f1e5d87acba21b87c188e3a70a0f319b79e60` reproduces
  `54771bd3…` exactly — so the blocked effect is the publish that the recorded 2026-09-06 operator
  override performed out of band as Consiliency/omniagent-plus#28.

## Research summary (all anchors read at base `ef6a9b18`)

- **Where a block is consulted.** `verbs.py:533-534` (`_fresh_publish`) plus three sites in
  `admission.py` (`:326`, `:515`, `:576`), wired through `epoch_blocked=lambda: evidence_store.epoch_blocked`
  at `live.py:3435`, `:3504`, `:3633`. A rotation that produces a *new, unblocked store* satisfies all
  four without touching any of them.
- **Why the block cannot be lifted in place.** `evidence.py:229-230` refuses any append that transitions
  out of `outcome_ambiguous_blocked`, on every caller path. This plan does not propose relaxing it.
- **Receipt authentication is byte-exact.** `load_partition_receipt` (`live.py:792-841`) authenticates a
  chain — identity, ARMED journal, sealed inventory digest, partition-map digest — and finally requires
  `path.read_bytes() == expected.file_bytes(...)`. A successor receipt therefore cannot simply be
  written; it must be *produced* by a sealed inventory and an ARMED journal. Rotation needs its own
  ceremony, not a file edit.
- **Unknown schema fails closed, but with the wrong story.** `load_partition_receipt:806-807` raises
  `LegacyCutoverConflict` on an unrecognised `schema`, and `partition_is_ambiguity_blocked:861-865`
  turns any such failure into `True`. So an old runtime meeting a newer receipt refuses — but reports
  "inherited permanent archived ambiguity", which is false and unactionable. ah#803 set the precedent
  for what this should be instead: a typed, named compatibility refusal.
- **`historical_evidence_roots` is a bootstrap-inventory concept**
  (`_validate_historical_evidence_root`, `live.py:2324-2340`: only `admissions.jsonl`,
  `admissions.lock`, `evidence.jsonl`, `evidence.lock` may be present; each JSONL is strict-parsed).
  The live inventory already carries two such rows. It is **sealed and digest-pinned**
  (`_validate_zero_history_inventory`, `live.py:2424-2429`) and pointed at by `ACTIVE_BOOTSTRAP`, so the
  operator note's phrase "retire the blocked partition into `historical_evidence_roots`" is a
  description of intent, not an available operation: the existing inventory cannot be appended to.
- **A second bootstrap over the same authority root is already refused.**
  `probe_zero_history_bootstrap` (`live.py:2394-2409`) rejects any authority root that is not fresh —
  anything other than `bootstrap.lock` and atomic temps of the two targets is "not fresh". The live root
  holds a sealed inventory, a journal, `ACTIVE_BOOTSTRAP` and `search-locks/`, so re-bootstrapping in
  place cannot be used to launder a block. What is **not** yet established is the same attempt against a
  *fresh* authority root pointed at a namespace that already holds a populated partition; that is a
  falsifier this plan requires (Lane D1), not an assumption.
- **Onboarding shape to copy, not call.** `onboard_zero_legacy_repository` (`live.py:2970-3022`) is the
  existing "repository first seen post-ACTIVE" route: serialized under the latch's activation lock,
  exactly one receipt, a real zero-source proof, generation drained/armed/promoted. Rotation is the same
  shape with a different proof: a successor partition is **not** zero-source — a retired predecessor
  store demonstrably exists.

## Design contract

**D1 — Rotation is a ceremony, journaled and crash-idempotent.** Its own `cutover_id`, its own sealed
inventory and journal, states `DRAINING → INVENTORY_SEALED → ARMED → ACTIVE`, mirroring
`run_legacy_broker_cutover` (`live.py:1834-1967`) and the bootstrap journal. Crash-idempotence is proven
at every state boundary, in the style of
`test_fabpub_global_legacy_cutover_partitions_multiple_repositories_crash_idempotently_before_activation`
(`test_fabpub_shared_epoch.py:2700`).

**D2 — The successor receipt is a new schema version with a new proof type.**
`LegacyRepositoryPartitionReceipt.v3` adds the rotation proof: the digest of **every** file in the retired
store (`admissions.jsonl`, `evidence.jsonl`, and `adapter-start-owner.json` when present — the owner file
is the primary artifact of the unknown effect and its digest must be pinned, not dropped), the predecessor
receipt digest, and the attestation digest (D4). `zero_source` MUST be false for a rotated partition —
claiming zero-source with a retired predecessor on disk would be a false proof. The successor's
`ambiguous` MUST be false: carrying the block forward via `receipt.ambiguous=True` would re-block the new
partition through `partition_is_ambiguity_blocked` and defeat the entire ceremony.

Two carries are not optional and are the ones a naive rotation drops:

- **Completed-effect idempotency, specified as the mechanism and not as a field.** Duplicate suppression
  for an already-published effect comes from two places only: the store-local `evidence_store.replay()`
  and the receipt-carried history through `_legacy_terminal_replay` (`verbs.py:273-291`). A successor
  starts with an empty store, so every predecessor `effect_terminal_observed` key MUST be answerable
  through that second route — and naming it on `receipt.legacy_completed_effect_keys` is **not
  sufficient**, because nothing on the publish path reads that field directly. The whole chain must line
  up, and the plan requires each link:

  1. `authenticated_legacy_records()` → `sealed_partition_effects(receipt)` reads per-key provenance from
     the **sealed rotation inventory**'s `legacy_completed_effects` for this identity, and raises unless
     that key set equals `receipt.legacy_completed_effect_keys` (`live.py:868-887`). So the rotation
     inventory MUST carry cutover-shaped provenance for every carried key, mirroring the receipt list.
  2. The provenance MUST include `serialized_repository`, absent which `_legacy_terminal_replay` raises
     "legacy terminal has no preserved repository preimage" (`verbs.py:277-279`).
  3. `promote_legacy_terminal` → `_mint_cutover_promotion_capability` re-verifies **current archive
     bytes** at `provenance["legacy_root"]/legacy-archive/<cutover_id>/<source_id>` against
     `admissions_digest` / `evidence_digest` on the replay that mints the capability
     (`live.py:936-968`). That is once per successor per key: the first legacy replay materialises intent
     + terminal rows into the successor store (`verbs.py:285-290`), and every later request for that key
     answers from `execute()`'s store replay (`:622-624`) without re-minting — so archive loss *after*
     materialisation cannot produce a second adapter call (the store answers as a duplicate), and the
     drift corollary must be fixtured against a **fresh** successor. The D7 archive is therefore not
     merely preserved evidence: it is the byte source each carried-key replay re-authenticates, and
     archive drift or deletion produces a typed `PermissionError` rather than a silent duplicate. Either
     the archive lives exactly where `mint` resolves, or Lane D2 extends `mint` — and states which.
     The same reasoning applies to the **attestation documents** of carried entries: they were sealed
     into the *prior* rotation's inventory, so a successor that only pins their digests leaves the
     documents reachable solely by walking the predecessor-receipt chain. Copy them forward alongside the
     archives, digest-verified, so every carried disposition's evidence is one hop away.
     One precision that decides that choice: the path's `<cutover_id>` component comes from the
     **loading receipt**, not from the provenance dict (`live.py:947-951`; `sealed_partition_effects`
     only `setdefault`s a provenance `cutover_id` that `mint` never reads). On a second rotation,
     provenance carried verbatim from the first therefore resolves under the *new* ceremony's
     `cutover_id` and finds nothing — so re-placing prior archives under each rotation's `cutover_id`
     (copied, digest verified) or extending `mint` is **not optional for transitivity**. Lane D2 takes the
     **copy** branch unless it records a reason not to: the provenance digests pin bytes, not paths
     (`mint` hashes whatever sits at the resolved path, `live.py:953-967`), so a byte-identical copy under
     the new ceremony's `cutover_id` authenticates identically, while extending `mint` edits shipped
     machinery that the live v2 partitions also depend on and puts anchor 7's regression surface in play.
     Copies, not links: `mint` does a plain `read_bytes`, and a future symlink-hardening pass in this
     loader family would break links. Anchor 4b arbitrates either way, and every failure mode is the typed
     refusal.

  The measured predecessor holds two completed keys (`…58033572`, `…0a68fc6a`) while its own
  `legacy_completed_effect_keys` is empty, so a rotation that copies the receipt and adds adjudications
  would let an already-completed publish call the adapter a second time. Rotation MUST NOT be weaker than
  the cutover it is modelled on. The carry is **transitive**: a later rotation carries every terminal AND
  every prior `observed_landed` disposition forward, including ones never replayed. (Note the owner-file
  digest pinned in D7 is an audit artifact only — `mint` re-verifies the two JSONLs, not the owner file.)
- **Epoch monotonicity, stated transitively.** `authenticated_partition_floor` (`live.py:845-853`) reads
  `legacy_epoch_high_water` from the receipt. The successor's value MUST be
  `max(predecessor receipt floor, predecessor maximum allocated epoch)` — 2 for the measured partition.
  The `max` is load-bearing: a second rotation of an intermediate successor that allocated no epochs would
  otherwise write a floor of 0 and let the third store reuse epochs the original already allocated.

**D3 — Every predecessor key is classified; the ambiguous ones are adjudicated.** A rotation is refused
unless **every** key the predecessor could replay has a stated classification:

| predecessor state | successor treatment |
| --- | --- |
| `effect_terminal_observed` | carried as a completed terminal (D2), zero adapter calls |
| `outcome_ambiguous_blocked` | adjudicated — one of the two dispositions below |
| anything else non-terminal (a dangling `provider_call_in_flight`, an unsealed `adapter-start-owner.json` with no terminal) | **refuse** — an unknown effect with no adjudication is exactly what must not be rotated away |

The ambiguity inventory MUST cover every source `epoch_blocked` recognises, not only canonical rows.
`evidence.py:86-95` blocks on a canonical `outcome_ambiguous_blocked` record **or** on
`_legacy_partition_blocked()`, and the comment there names the second class explicitly: an archived legacy
store whose history held a blocked record, **or an orphaned `provider_call_in_flight` whose effect is
unknown**, carried by a receipt with `ambiguous: true`. A predecessor can therefore be blocked with **no**
canonical blocked record, in which case a completeness check written only over canonical rows passes
vacuously and rotates an unresolved effect away. The inventory MUST walk the authenticated predecessor
lineage — canonical records, the receipt's `ambiguous` flag and its archived history, and any unsealed
owner — or refuse a partition whose lineage it cannot enumerate.

**Verb scope, fail-closed.** Every enforcement point cited above is `publish_committed_branch`-scoped:
`_legacy_terminal_replay` returns `None` for any other verb (`verbs.py:275-276`), and disposition
honouring lives on that same path. Non-publish verbs nevertheless write terminals and
`outcome_ambiguous_blocked` rows into the same receipt-governed store in production —
`convergence/refresh.py:63` executes `BrokerVerb.PUBLISH` through `broker.execute`, and the non-PCB path
records `EFFECT_TERMINAL_OBSERVED` or an "adapter-exception" block (`verbs.py:670-679`). A plan that
promises the carry and the adjudication for *every* key while every mechanism is publish-scoped is
promising something it cannot discharge. Therefore: **rotation refuses a predecessor whose enumerable
lineage contains any key whose verb prefix is not `publish_committed_branch`.** Extending the carry and
the dispositions to every verb is the heavier alternative and is deliberately NOT in this plan's scope;
the refusal keeps the gap fail-closed and visible. The measured partition is unaffected — all three of its
keys carry the `publish_committed_branch` prefix.

The successor receipt carries `adjudicated_effect_dispositions`: effect key →
`{disposition, observed_head, attestation_digest}`, in the shape of the existing
`legacy_completed_effect_keys`. Exactly two dispositions:

- `observed_landed` — the successor treats the key as a completed terminal: a publish request for it is
  answered as a duplicate, with **no** adapter call and no new provider effect.
- `attested_not_landed` — the successor permits **exactly one** governed publish for that key, after
  which normal idempotency applies.

Every ambiguous key MUST appear with one of the two dispositions; a rotation that leaves one undisposed is
refused. This is what discharges item (5): the `attested_not_landed` branch is the "publish the exact
intended branch once" capability, and `observed_landed` is the branch omniagent-plus needs.

**After a successful `attested_not_landed` publish, the key is a terminal, not a re-armed disposition.**
The publish it authorised leaves an `effect_terminal_observed` record in the successor store, so the next
rotation classifies that key through the completed-terminal row of the table above and carries it as
history — it is never re-armed from the receipt's disposition map. Successful publishes therefore carry forward as terminal history without another attestation; publishes
that become ambiguous require a new attempt-bound attestation before the next rotation can succeed
(anchor 4f).

**The third case is refusal, and it is the default.** An operator who cannot determine what happened — the
branch was deleted, force-pushed, or the observation is otherwise destroyed — declines to attest; the key
stays undisposed; the rotation is refused; the partition stays blocked. The two dispositions are
exhaustive only because "cannot adjudicate" resolves to fail-closed, and that must be stated rather than
implied. Note also that a force-push or a branch re-use at a different head is a **different effect key**
(the key binds repo, branch and head), so it is a separate adjudication, not a third disposition.

**D4 — The attestation is human-authored, durably stored, and re-verified; the runtime never reads the
remote.** A rotation requires an attestation document naming, per ambiguous key: the **observed head sha**
(or an explicit "branch absent at the observed time" — a bare "landed" is not falsifiable later), the
evidence a human looked at (PR/branch URL), who attested, and when. The document is **sealed into the
rotation inventory** alongside the partition map, so it is covered by the inventory digest the ceremony
already authenticates, and the ceremony re-verifies the document bytes against the digest pinned in the
receipt on every load — a hash with no stored document preserves accountability in name only.

**An attestation adjudicates one attempt, and is spent when it is used.** Naming only the effect key and a
time is not enough: an `attested_not_landed` attestation for key K would then still "fit" K after a later
attempt on K goes ambiguous, and a second rotation could reuse it to authorise another adapter call for an
attempt nobody has adjudicated. Every attestation entry MUST therefore bind to the exact state it
adjudicates — the predecessor receipt digest, the predecessor store digests, and the identity of the
unresolved attempt itself (the ambiguous record and, when present, the `adapter-start-owner.json`
`owner_nonce` and `transaction_id`, fields of `AdapterStartOwnership`, `verbs.py:51-62`). **`owner_nonce`
is the field that discriminates one attempt from another**: `attempt_id` is derived from
`sha256(b"FABPUB-PUBLISH-ATTEMPT-v1\0" + repo \0 branch \0 head_sha)` (`verbs.py:535-538`), so it is a
function of the effect key and is identical across every attempt on that key — binding to it alone would
reproduce exactly the key-only matcher this clause exists to forbid. A rotation MUST refuse an attestation **presented to adjudicate an ambiguous key
in this ceremony** whose bound predecessor digests or attempt identity are not the ones being rotated.
That refusal is scoped to adjudication and does **not** touch dispositions carried forward as history:
a prior `observed_landed` disposition on an earlier receipt is carried by D2's transitive clause and is
never re-presented for adjudication, so it is never subject to this check. Reading the refusal as applying
to carried history would make D2's transitivity and anchor 4b unsatisfiable — the two clauses are about
different things, and only adjudication is gated. An `attested_not_landed`
disposition grants **exactly one** governed publish and is consumed by it; if that publish itself ends
ambiguous, the resulting record is a **new** unresolved attempt that the old attestation cannot
adjudicate, and the next rotation needs a new one naming it.
The ceremony MUST NOT call `git ls-remote` or any network probe — "no branch on origin" and "`ls-remote`
timed out" remain the same observation to this runtime (ah#789 acceptance item 3). The distinction this
plan relies on is *who* observes: an accountable operator, recorded, not an inference by the runtime.

**D5 — Version skew, split into what can and cannot be fixed.** Three distinct obligations, because
conflating them produces an untestable requirement:

1. *Forward (implementable).* The v3-aware reader refuses an **unknown or future** receipt schema with a
   typed, named compatibility error carrying the runtime location — the ah#803
   `AdmissionStoreIncompatible` precedent — instead of routing it through
   `partition_is_ambiguity_blocked` and reporting "inherited permanent archived ambiguity". The new error
   MUST NOT subclass `LegacyCutoverConflict`: `partition_is_ambiguity_blocked` (`live.py:861-865`) catches
   that type and converts it to `True`, which would swallow the typed refusal and reproduce the very
   message this obligation exists to remove.
2. *Backward compatibility (load-bearing; anchored by Lane D1 anchor 7 and mutant m6).* The v3 reader MUST keep authenticating
   **v2** receipts byte-exactly. `agent-harness` `50fea8e4…` and `EZBidPro` `1a3e011c…` are live v2
   partitions on this host; a rotation feature that breaks a clean partition is a worse outcome than the
   block it is fixing.
3. *Retroactive (impossible, mitigated operationally).* A runtime installed **before** v3 cannot be made
   to report the typed error: its `load_partition_receipt` raises `LegacyCutoverConflict` on the unknown
   schema (`live.py:806-807`) and `partition_is_ambiguity_blocked` (`:861-865`) converts that to `True`,
   so the operator sees the misleading permanent-block message. That behaviour is frozen in shipped code
   and this plan does not pretend otherwise. Mitigation is operational: re-pin every installed
   `phase-loop-runtime` to a v3-aware build before Lane D5 — the same re-pin the predecessor plan carried,
   and a stale `uv tool` install from a worktree was ah#789's root cause.

**D6 — Fencing.** The ceremony runs under the bootstrap seal locks and the writer-generation latch: the
predecessor drains, the successor arms and promotes a fresh generation. After ACTIVE, a writer still
holding the retired store path fails closed.

**D7 — The retired store is preserved in full, and every file has a stated destination.** The measured
partition directory holds `admissions.jsonl`, `admissions.lock`, `evidence.jsonl`,
`partition-receipt.json` and `adapter-start-owner.json` — and **no** `evidence.lock`.
`_validate_historical_evidence_root` (`live.py:2324-2331`) allows exactly
`{admissions.jsonl, admissions.lock, evidence.jsonl, evidence.lock}` and raises on anything else, so
"matches the allowlist" and "preserved byte-identical" cannot both hold for the directory as it stands.
The rotation therefore uses a three-place layout, stated here so no implementer has to guess:

1. The predecessor directory moves **in full** — receipt and owner file included — to a named,
   **non-routable** archive path that is never passed to `_validate_historical_evidence_root`. Byte
   identity is required there, and the owner file's digest is pinned in the successor receipt (D2).
2. If the rotation inventory needs a `historical_evidence_roots`-shaped row, it is derived as an
   allowlist-only snapshot whose JSONL digests equal the archive's. Extending the historical
   classification itself to admit receipts and owner files would be a **contract change** and is
   explicitly out of scope for this plan.
3. The successor is written as an **empty** store at the single routable identity path — no owner file, no
   inherited evidence rows.

   **The crash window between the move and the successor write is guarded durably, not by a lock.** In
   that window the identity path has no receipt and no allocator files, which is exactly the state
   `onboard_zero_legacy_repository` (`live.py:2970-3022`) is entitled to onboard with a **zero-source**
   receipt — and the route is automatic, not operator error: `fabpub_activation_barrier` calls it
   unconditionally for a receipt-less repository once a global ACTIVE authority exists
   (`live.py:3342-3354`), and onboarding's only adoption guard — refuse when `admissions.jsonl` or
   `evidence.jsonl` exist without a receipt (`live.py:3041-3046`) — passes **vacuously** on a fully empty
   path. The result would be an unblocked zero-source successor carrying no terminals and no
   adjudications: the block laundered, and the predecessor's completed publishes free to call the adapter
   again. Seal locks cannot close this: they are `fcntl.flock` (`live.py:136-160`) and die with the
   process, which is the crash this guard exists for.

   The guard is therefore **durable state, and it is the rotation journal**: onboarding and the
   routability path refuse, with a typed error, any identity that has a rotation journal in **any**
   non-`ACTIVE` state. The predicate is deliberately state-agnostic rather than keyed on `ARMED`: a guard
   that fires only in `ARMED` would leave the window open under a completion-journalled implementation
   that performs the move and *then* records the state, and the ceremony this one mirrors sequences
   exactly that way — `_drive_cutover` writes its partition receipts (`live.py:2033`) **before** recording
   `ARMED` (`:2048`), which is safe there and would be unguarded here. Making the predicate
   sequencing-independent removes the coupling instead of documenting it. The ceremony additionally
   journals its first state **before** it touches anything, so the journal exists from the first instant
   the identity could be observed receipt-less; and `ACTIVE` is recorded only after the successor receipt
   authenticates. The journal lives under the **authority root, keyed by canonical repository identity** —
   never under the partition path or inside the archive — because onboarding receives only a worktree and
   must be able to find it when the partition path is empty. That edit to shipped onboarding machinery is in Lane D2's scope, stated here so it is not
   discovered mid-lane. The alternative — a layout that never leaves the path observably empty (a staged
   successor plus an exchange) — is rejected because POSIX offers no portable atomic directory swap, so it
   would trade a guarded window for an unguarded one. Anchors **5a** and **5b** and mutants **m15**, **m16** and **m17** cover it.

Point 3 is load-bearing beyond tidiness: `_fresh_publish` consults `_block_unsealed_owner`
(`verbs.py:530-532`) **before** it consults `epoch_blocked` (`:533-534`), so a successor that inherited
the unsealed `adapter-start-owner.json` would be blocked by the owner check before any disposition could
be honoured, and would append a fresh `outcome_ambiguous_blocked` row — re-blocking the identity the
rotation just recovered. An empty successor removes that hazard at the source.

**`_block_unsealed_owner` MUST NOT be moved, reordered, or bypassed.** It is the ah#789 property itself:
a crashed `attested_not_landed` first publish leaves an unsealed owner with an unknown effect, and that
must block exactly as it does today. No reordering is needed, because the slot already exists —
`execute()` consults `_legacy_terminal_replay` (`verbs.py:625`) **before** it dispatches to
`_fresh_publish` (`:636`). An `observed_landed` disposition resolves in that pre-dispatch slot and never
enters `_fresh_publish` at all; requests that do enter it — an `attested_not_landed` first attempt, or any
fresh key — keep `verbs.py:530-532` exactly as it is.

`evidence.py:229-230` stays untouched throughout; nothing transitions out of
`outcome_ambiguous_blocked`, and the record for `b72b68ff…` is preserved as evidence.

**Lane note (D2):** `authenticated_partition_floor`'s refusal text hardcodes
"LegacyRepositoryPartitionReceipt.v2" (`live.py:845-853`); the lane that touches the loader updates it.

**D8 — Rotation applies only to a blocked partition.** `rotate_blocked_partition` refuses a partition
that is not `epoch_blocked`. Without that precondition the ceremony is a general store-reset primitive
available against clean partitions — which, combined with the carries in D2, is a history-laundering tool
rather than a recovery.

## Lanes

Lane order is stated once, here, and repeated nowhere else: D1 → D2 → D3 → D4. D2 precedes D3 because D3
consumes the receipt field D2 adds, and D4 documents what D2/D3 landed. Nothing in this plan runs in
parallel.

### Lane D1 — falsifiers first (tests_only)

`phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py` (new). RED at this base, per the repo's
RED-first idiom (`_fabpub_tdd_guard.py` gating, `fabpub_capability_active()`, `FABPUB_SKIP_REASON`), and
registered in the frozen node-id inventory the same way the ah#789 lanes were.

Anchors:
1. A blocked partition, rotated with `observed_landed` for its ambiguous key, makes **no adapter call and
   no provider effect** for that key and answers the request as a duplicate. The property is the absent
   adapter call, not an absent evidence row: `_legacy_terminal_replay` (`verbs.py:273-291`) answers a
   receipt-carried duplicate by materialising intent + terminal rows into the store, and a disposition
   that follows that established idiom is correct. The anchor asserts the adapter counter is 0.
2. The same rotation with `attested_not_landed` permits exactly one adapter call for that key, and a
   second attempt is refused by ordinary idempotency.
3. A rotation that leaves an ambiguous key undisposed is refused before anything durable is written.
4. The retired store is byte-identical before and after, **every file included** — `admissions.jsonl`,
   `evidence.jsonl` and `adapter-start-owner.json` — and the owner file's digest appears in the successor
   receipt (mutant: drop the owner from the archive or its digest from the receipt).
4a. The successor store contains **no** `adapter-start-owner.json`, and an `observed_landed` key is
   answered in the pre-dispatch slot (`execute` → `_legacy_terminal_replay`, `verbs.py:625`) without ever
   reaching `_fresh_publish` — asserted by the absence of any owner read or owner write for that request.
   `_block_unsealed_owner` (`verbs.py:530-532`) is unchanged and still blocks a crashed
   `attested_not_landed` first attempt; an anchor pins that too, so the fix cannot be implemented by
   weakening the ah#789 property.
4b. A predecessor `effect_terminal_observed` key replayed against the successor is answered as a duplicate
   with zero adapter calls, **through the authenticated route** — the capability is minted from sealed
   inventory provenance and re-verified archive bytes (`live.py:936-968`), not by a special case that
   merely suppresses the adapter. The anchor asserts the mint path ran. Transitivity is proven with the
   fixture D8 requires: the successor is **re-blocked by a new key** before a second rotation, and the
   second successor still answers the first predecessor's terminals — and its unreplayed
   `observed_landed` dispositions — as duplicates. Corollary anchor: archive drift or deletion makes that
   replay fail with a typed `PermissionError`, never a silent second adapter call.
4e. A predecessor whose enumerable lineage contains any key whose verb prefix is not
   `publish_committed_branch` is refused by `rotate_blocked_partition` (the fail-closed verb scope).
   (Fixture note for 4b: the key that re-blocks the successor must itself be `publish_committed_branch`-
   prefixed, or 4e refuses the second rotation before transitivity can be exercised. The realistic
   re-block routes — a crashed `attested_not_landed` first attempt, an adapter exception in
   `_fresh_publish` — are publish-scoped, so a fixture built on them is correct by construction.)
5a. **The move/write crash window is guarded.** Crash the ceremony at the **first receipt-less instant**
   — immediately after the move completes, which is the point that falsifies a completion-journalled
   implementation — and again at each later boundary in the window; drive `fabpub_activation_barrier` / `onboard_zero_legacy_repository` at that identity;
   assert the typed refusal naming the journal's **recorded non-`ACTIVE` state, whatever it is** (a
   receipt-count assertion is NOT sufficient — the laundered outcome leaves exactly one routable
   receipt); then resume the rotation and assert the successor receipt authenticates and carries the
   terminals and dispositions. The oracle must not name `ARMED` specifically: under the mutate-then-arm
   ordering the mirrored `_drive_cutover` uses, the first receipt-less instant is pre-`ARMED`, and an
   `ARMED`-naming assertion would fail on a correct implementation and push a fixture author back to
   post-`ARMED` injection — reopening the very slice this anchor exists to close.
5b. **The guard is state-agnostic by construction, not by trajectory.** For **each** non-`ACTIVE` journal
   state, build an identity directly — partition path empty, rotation journal at that state, not merely
   reached by crashing — drive `fabpub_activation_barrier` / `onboard_zero_legacy_repository`, and assert
   the typed refusal naming that state. Crash injection can only reach the states one trajectory passes
   through, so it cannot test the contract the guard actually has; this anchor can, and it is what kills
   the narrowed-predicate mutant under any sequencing.
4f. **Attestation reuse is refused.** Rotate key K with an `attested_not_landed` attestation A; publish K
   once on the successor; drive that publish to a fresh ambiguity for K; attempt a second rotation
   presenting A again. It is refused, because A binds to the predecessor digests and the attempt identity
   it adjudicated, and the new ambiguity is a different unresolved attempt. The same fixture with a new
   attestation naming the new attempt succeeds.
4c. A rotation whose predecessor is blocked **only** through a receipt-carried ambiguity (`ambiguous: true`
   with empty canonical evidence, or an archived orphaned `provider_call_in_flight`) is refused unless
   that obligation is adjudicated — the vacuous-completeness negative control.
4d. A partition that is not `epoch_blocked` is refused by `rotate_blocked_partition`.
5. Crash injection at each journal boundary leaves the ceremony resumable and never leaves two routable
   receipts for one identity.
6. A v3-aware reader meeting an **unknown/future** receipt schema raises the typed compatibility refusal
   naming the schema and the runtime location, not `partition_is_ambiguity_blocked`'s ambiguity message.
7. A v3-aware reader still authenticates an untouched **v2** receipt byte-exactly, and a clean v2
   partition publishes through the governed path unchanged (regression anchor for `agent-harness` and
   `EZBidPro`).
8. **The laundering falsifier:** a fresh authority root pointed at a namespace that already holds a
   populated partition must refuse to bootstrap, and the anchor asserts **where** it refuses, not merely
   that it does — the most likely site is `LegacyRepositoryPartitionReceipt.write` (`live.py:734-750`),
   which rejects a byte-divergent overwrite of an existing receipt, so a later refactor of `write` cannot
   silently reopen the route. If it does not refuse, closing the hole joins this plan's scope and the
   finding is recorded in the PR body.

### Lane D2 — receipt schema and the rotation ceremony (production)

`convergence/broker/live.py`: `LegacyRepositoryPartitionReceipt` → v3 with the rotation proof and
`adjudicated_effect_dispositions`; a `rotate_blocked_partition(...)` entry point in the shape of
`onboard_zero_legacy_repository`; the rotation inventory/journal/seal-lock helpers; the typed pre-v3
refusal (D5); **and the non-`ACTIVE` rotation-journal guard in `onboard_zero_legacy_repository` and on the
routability path** (D7 point 3) — an edit to shipped onboarding machinery, named here rather
than discovered mid-lane.

### Lane D3 — dispositions honoured on the publish path (production)

`convergence/broker/verbs.py`, on the **pre-dispatch replay path** (`execute` → `_legacy_terminal_replay`,
`:625`) — not inside `_fresh_publish`: an `observed_landed` key resolves as a completed terminal there and
never enters `_fresh_publish`, so no owner is read or written for it; an `attested_not_landed` key falls
through and proceeds exactly once. No change to the four `epoch_blocked` consult sites, none to
`_block_unsealed_owner`, and none to `evidence.py:229-230`.

### Lane D4 — operator surface and docs

A `phase-loop fabpub rotate-partition` command that takes the attestation document and drives the
ceremony; `docs/fabpub-pre-admission-ambiguity.md` gains the rotation section (replacing "deferred");
CHANGELOG entry.

### Lane D5 — execute the omniagent-plus rotation (operational, not a PR)

After D1–D4 land: attest `…54771bd3` as `observed_landed` citing Consiliency/omniagent-plus#28 and the
2026-09-06 override comment, rotate `1da3e343…`, and demonstrate one governed publish for omniagent-plus.
Requires a separate maintainer authorisation; nothing here executes it.

## Documentation impact

- `docs/fabpub-pre-admission-ambiguity.md` — modify — replace "Partition rotation (deferred)" with the
  landed ceremony, and update the carried-item paragraph once item (5) is discharged.
- `CHANGELOG.md` `## [Unreleased]` — add — one entry per landed lane.
- `plans/manifest.json` — add — `type=detailed` entry for this plan.
- `specs/phase-plans-v10.md` — none (LEGIBLE-owned; no roadmap goal changes).
- `plans/decision-interim-president-ratification-20260904.md` — ledger row per production_code/plan landing.

## Dependencies & order

1. Maintainer approval of this document → plan-tier board → land (ledger row).
2. **Fable-seat availability is a landing risk, named up front.** The native fable sub-agent override
   produced no output for three consecutive ah#805 rounds on 2026-09-08 (a default-model sub-agent ran the
   same smoke test in seconds); Consiliency/agent-harness#806 tracks the missing policy. This plan lands
   either on four seats or on a recorded deviation of the ah#805 shape — never silently on three.
3. Lane order is as stated under Lanes; it is not repeated here.
4. D5 after all lanes land, with its own authorisation, and **only after every installed
   `phase-loop-runtime` on a host that can write FABPUB state is re-pinned to a v3-aware build**
   (`uv tool install --force "git+https://github.com/Consiliency/agent-harness@<main sha>#subdirectory=phase-loop-runtime"`,
   never from a working checkout) — see D5 part 3. The Lane D5 runbook includes a **version probe** that
   verifies each installed runtime recognises `LegacyRepositoryPartitionReceipt.v3` before the ceremony
   starts, so a stale reader is found before it meets a v3 receipt, not after. **Replacing an
   installation does not upgrade code already loaded by a running process**, and that gap is not
   theoretical during a rotation: a surviving pre-v3 process needs no writer lease to enter the automatic
   onboarding route (`live.py:3342-3354`), its allocator-file guard passes on the empty path
   (`live.py:3041-3046`), and its shipped code cannot consult a rotation journal it has never heard of —
   so it can create exactly the zero-source successor D7 forbids, in the window D7's guard closes for
   v3-aware readers. Unknown-schema refusal offers nothing here, because in that window there is no
   receipt to read. The runbook therefore gates **running processes**, not just installations: every
   FABPUB-capable process on a host that can write this authority is stopped or restarted before the
   ceremony and kept out for its duration, resumes included. Lane D1 carries the matching falsifier — a
   mixed-version fixture that keeps a pre-v3 reader alive across the installation replacement and drives
   it at the first receipt-less instant — so the crash-safety criterion is substantiated for the fleet
   state the ceremony actually runs in.
5. Unchecked precondition: the Windows host has not been scanned for blocked partitions. Before D5,
   scan every host that can write FABPUB state, so a rotation is not performed while a second blocked
   partition is unknown.

## Verification

- CI-faithful suite (source mode, `PYTHONPATH=$PWD/src:$PWD/tests`):
  `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests /mnt/workspace/venvs/ah-779-ci/bin/python -m pytest
  -p no:cacheprovider -o addopts="" -q tests/test_fabpub_partition_rotation_789d.py
  tests/test_fabpub_shared_epoch.py tests/test_fabpub_zero_history_bootstrap.py
  tests/test_fabpub_recovery_controls_789.py` — all green; frozen corpus counts unchanged
  (`test_fabpub_guard_nodeid_inventories_are_disjoint_and_counted`).
- Every falsifier in Lane D1 RUN and its observed failure text recorded in the PR body — never "should
  fail".
- Named mutants, each RUN, in the ah#805 style, every one phrased as the **detection** it produces:
  (m1) drop the undisposed-key check → the rotation anchor 3 expects to be refused is accepted, so anchor
  3 FAILS and kills the mutant;
  (m2) carry the block as `receipt.ambiguous=True` → the successor is blocked, anchors 1–2 fail;
  (m3) let `observed_landed` reach the adapter → anchor 1's adapter counter is 1;
  (m4) let `attested_not_landed` publish twice → anchor 2's second attempt succeeds;
  (m7) drop the completed-terminal carry from the successor receipt → anchor 4b's replay reaches the
  adapter; (m8) omit the owner file from the archive or its digest from the receipt → anchor 4 fails;
  (m9) allow rotation of a partition that is not blocked → anchor 4d's refusal does not fire;
  (m10) inventory ambiguity from canonical rows only → anchor 4c rotates the receipt-carried obligation
  away;
  (m11) skip the verb-scope refusal → anchor 4e's refusal does not fire;
  (m12) write the successor floor as the predecessor's allocated maximum without the `max(...)` against
  the predecessor receipt floor → the second-rotation floor anchor reads 0 and epochs become reusable;
  (m13) answer a carried key by suppressing the adapter without minting the capability → anchor 4b's
  mint-path assertion fails, catching the shortcut that would drop archive re-authentication;
  (m14) match an attestation on effect key alone, ignoring the bound predecessor digests and attempt
  identity → anchor 4f's second rotation is accepted and the unadjudicated attempt is retried;
  (m15) drop the non-`ACTIVE` rotation-journal onboarding guard → anchor 5a's onboarding inserts a
  zero-source receipt into the crash window and the block is laundered;
  (m16) narrow the guard's predicate to `ARMED` only → anchor **5b**'s refusal does not fire for the
  pre-`ARMED` states (5a alone cannot kill this: under an intent-journalled ordering every receipt-less
  instant it can reach is already `ARMED`, so the narrowed guard still refuses there and the mutant
  survives — which is why the state-construction anchor exists);
  (m17) hoist the predecessor move ahead of the journal's first recorded state → at 5a's first
  receipt-less instant there is no journal at all, the guard is silent, and 5a's refusal assertion fails;
  (m5) route an unknown schema through the ambiguity path instead of the typed refusal → anchor 6 gets the
  misleading permanent-block message; (m6) tighten the reader to accept only v3 → anchor 7's clean v2
  partition stops authenticating.
- Read-only host re-inspection after D5: the retired store's two JSONL files digest-match the values
  pinned in the successor receipt.

## Acceptance criteria

- [ ] A rotation of a blocked partition whose ambiguous key is attested `observed_landed` yields a
      successor partition that publishes a fresh, unrelated branch through the governed path, and answers
      the attested key as a duplicate with zero adapter calls (falsified by m3).
- [ ] The same rotation attested `attested_not_landed` permits exactly one governed publish of the exact
      intended branch and refuses the second by ordinary idempotency (falsified by m4). This is ah#789
      acceptance item (5)'s first half, discharged as a capability rather than restated.
- [ ] A rotation leaving any predecessor `outcome_ambiguous_blocked` key undisposed is refused before any
      durable write (falsified by m1).
- [ ] The successor receipt authenticates through `load_partition_receipt` byte-exactly, carries
      `zero_source: false` and `ambiguous: false`, and pins the predecessor digests plus the attestation
      digest (falsified by m2).
- [ ] A v3-aware reader raises a typed compatibility refusal naming the schema and the runtime location
      for an unknown/future receipt schema (falsified by m5), and still authenticates an untouched v2
      receipt byte-exactly so a clean v2 partition publishes unchanged (falsified by m6). The pre-v3
      install's misleading message is documented as unfixable retroactively, with the re-pin as its
      mitigation — not claimed as fixed.
- [ ] Every predecessor `effect_terminal_observed` key is carried onto the successor receipt with the
      provenance `_legacy_terminal_replay` requires, so replaying it against the successor is a duplicate
      with zero adapter calls — and still is after a second rotation (falsified by m7).
- [ ] The predecessor store is byte-identical after rotation, **every file included** (JSONLs, receipt,
      and `adapter-start-owner.json`), the owner digest is pinned in the successor receipt, and the
      successor carries no owner file — so its first publish is not re-blocked by
      `_block_unsealed_owner` before the disposition resolves (falsified by m8).
- [ ] A predecessor blocked only through a receipt-carried ambiguity or an archived orphaned
      `provider_call_in_flight` is refused unless that obligation is adjudicated (falsified by m10).
- [ ] `rotate_blocked_partition` refuses a partition that is not `epoch_blocked` (falsified by m9).
- [ ] The successor's `legacy_epoch_high_water` equals `max(predecessor receipt floor, predecessor
      maximum allocated epoch)`, so no successor admission reuses an allocated epoch — including after a
      second rotation through an intermediate successor that allocated none (falsified by m12).
- [ ] An `attested_not_landed` attestation is bound to the predecessor digests and the attempt identity it
      adjudicates, is spent by the one publish it authorises, and cannot adjudicate a later ambiguity of
      the same key — a second rotation presenting the original attestation is refused, and succeeds only
      with a new one naming the new attempt (falsified by m14).
- [ ] A predecessor whose lineage contains a non-`publish_committed_branch` key is refused, because the
      carry and disposition machinery is publish-scoped (falsified by m11). Extending it to every verb is
      out of scope for this plan and named as such.
- [ ] Crash injection at every rotation journal boundary is idempotent and never leaves two routable
      receipts for one canonical identity; and a crash between the predecessor move and the successor
      write cannot be onboarded as a zero-source repository, because onboarding and routability refuse a
      typed error for an identity whose rotation journal is in any non-`ACTIVE` state — proven per state
      by direct construction, not only along one crash trajectory — with that journal written before the
      first mutation (falsified by m15, m16 and m17; note a receipt-count assertion alone would pass all
      three, since the laundered outcome leaves exactly one routable receipt).
- [ ] The runtime performs no network or `git ls-remote` call anywhere in the ceremony, proven by the
      recording sentinel idiom from `test_fabpub_recovery_controls_789.py`.
- [ ] The laundering question is answered in the PR body with a RUN result: whether a fresh authority root
      can bootstrap over a populated namespace, and — if it can — the guard that closes it.

## Execution Policy

- execute: effort=high, reason=a new authority-ceremony and a receipt schema version on the fencing path;
  every anchor is a fail-closed guarantee and the failure mode is silent unblocking.
