# Detailed plan: FABPUB partition rotation — the governed recovery for a permanently blocked repository partition (ah#789 Workstream D)

status: draft 2026-09-08 — round-14 clean rewrite from the settled contract (supersedes the round 1–13 text in full), round-15 and round-16 amendments folded in; awaiting maintainer approval; no runtime edits made
owner: Claude Code session `session_01Rv2aKsUWdEKoWfB5PTpD1B`
issue: Consiliency/agent-harness#789 (Workstream D; acceptance item (5) first half)
base: `ef6a9b18a0eb47981ebf07f56e6fc3d6bbe742d8` (origin/main, 2026-09-08 — carries ah#803/#804/#805; every anchor below was re-read at this base, and the broker files are unchanged between it and this branch)
landing tier: `plan` — cross-vendor board under `plans/decision-interim-president-ratification-20260904.md` (Consiliency/agent-harness#773); ledger row on landing
predecessor: `plans/detailed-789-fabpub-pre-admission-compat-20260906.md` (Workstreams A/B/C; D deferred there to this document)

## Task

Restore **governed** FABPUB publication for a repository whose partition is permanently
`epoch_blocked`, without weakening the permanent-ambiguity contract and without the runtime ever
inferring effect-absence from the remote. Concretely: discharge ah#789 acceptance item (5)'s first
half — "a completed recovery can publish the exact intended branch once" — as a general capability,
and give the one partition that is blocked today an executable route back.

## Measured starting state (read-only inspection, 2026-09-08, host `claw`)

Every value was read, none inferred.

- Authority root `~/.local/state/phase-loop/fabpub/authority-v1`, bootstrap `fabpub-host-bootstrap-20260904`,
  journal `DRAINING → INVENTORY_SEALED → ARMED → ACTIVE`, pointer `ACTIVE_BOOTSTRAP` (schema
  `ZeroHistoryBootstrapAuthority.v1`).
- **Exactly one blocked partition:** `1da3e3433e00173dec7aaa5ca564038a1df5ccd64498be0506aab80b579e7681`
  = `omniagent-plus`. Its `evidence.jsonl` holds two completed effects (`…58033572`, `…0a68fc6a`, both
  `effect_terminal_observed` → omniagent-plus#17) and one blocked effect `…54771bd3`
  (`provider_call_in_flight` → `outcome_ambiguous_blocked`, reference `unsealed-adapter-start-owner`).
  `admissions.jsonl` has rows for epochs 1 and 2 only — none for `…54771bd3`: the failure was
  pre-admission. `adapter-start-owner.json` is present with `sealed: false`, `transaction_id b72b68ff…`,
  `committed_head 076f1e5d…`.
- The partition receipt is `LegacyRepositoryPartitionReceipt.v2`, `ambiguous: false`, `zero_source: true`,
  `legacy_epoch_high_water: 0`, `legacy_completed_effect_keys: []`. The block comes from the canonical
  evidence row (`evidence.py:86-95`), not from a legacy-carried receipt (`live.py:856-865`).
- The other two partitions on this host are clean: `agent-harness` `50fea8e4…` and `EZBidPro`
  `1a3e011c…`, receipts `ambiguous: false`, no blocked records. Host `ai` carries no FABPUB broker state.
  The Windows host was **not** checked (its scan errored) — see Dependencies.
- `publish_committed_branch_idempotency_key` is `sha256(repo \0 branch \0 head_sha)`
  (`convergence/contracts.py:20-22`), where `repo` is the serialized canonical identity as `_dedup_key`
  passes it (`verbs.py:255-262`). Recomputing it from `1da3e343…`, branch `codex/audit-remediation-roadmap`
  and head `076f1e5d87acba21b87c188e3a70a0f319b79e60` reproduces `54771bd3…` exactly — the blocked effect
  is the publish that the recorded 2026-09-06 operator override performed out of band as
  Consiliency/omniagent-plus#28.

## Research summary (all anchors read at base `ef6a9b18`)

- **Where a block is consulted.** `verbs.py:533-534` (`_fresh_publish`) plus three sites in
  `admission.py` (`:326`, `:515`, `:576`), wired through `epoch_blocked=lambda: evidence_store.epoch_blocked`
  at `live.py:3435`, `:3504`, `:3633`. A rotation that produces a new, unblocked store satisfies all four
  without touching any of them.
- **The block cannot be lifted in place.** `evidence.py:229-230` refuses any append that transitions out
  of `outcome_ambiguous_blocked`, on every caller path. This plan does not relax it.
- **Receipt authentication is byte-exact.** `load_partition_receipt` (`live.py:792-841`) authenticates a
  chain — identity, ARMED journal, sealed inventory digest, partition-map digest — and finally requires
  `path.read_bytes() == expected.file_bytes(...)`. A successor receipt cannot be written; it must be
  produced by a sealed inventory and an ARMED journal. Rotation is a ceremony, not a file edit.
- **Unknown schema fails closed with the wrong story.** `load_partition_receipt:806-807` raises
  `LegacyCutoverConflict` on an unrecognised schema and `partition_is_ambiguity_blocked:861-865` turns that
  into `True` — a stale runtime reports "inherited permanent archived ambiguity", which is false and
  unactionable. ah#803's typed `AdmissionStoreIncompatible` is the precedent for what it should be.
- **The sealed bootstrap inventory cannot be appended to** (`_validate_zero_history_inventory`,
  `live.py:2424`, digest-pinned and pointed at by `ACTIVE_BOOTSTRAP`), so "retire the partition into
  `historical_evidence_roots`" is a description of intent, not an operation. Under D7 it is not needed:
  the predecessor is retired in place as a non-routable generation.
- **A second bootstrap over the same authority root is refused** (`probe_zero_history_bootstrap`,
  `live.py:2394-2409`, non-fresh root). The same attempt against a *fresh* authority root pointed at a
  populated namespace is not yet established — a falsifier this plan requires (anchor A22), not an
  assumption.
- **Onboarding is the shape to copy, not call.** `onboard_zero_legacy_repository` (`live.py:2970-3022`):
  serialized under the latch's activation lock, exactly one receipt, a real proof, generation
  drained/armed/promoted. Rotation is that shape with a different proof — a successor is not zero-source,
  because a retired predecessor demonstrably exists.
- **The activation barrier is the consumer the successor must satisfy.** `fabpub_activation_barrier`
  (`live.py:3324-3365`) loads the receipt, checks the seal-lock subset (`:3330-3336`), requires
  `_receipt_active_authority_exists` (`:3338-3341`), and only a receipt-less identity reaches the
  zero-source onboarding route (`:3342-3354`). Both authority helpers (`:3187-3217`, `:3232-3242`)
  consult the bootstrap claim **only when `receipt.zero_source`**, and otherwise fall to
  `legacy_root_inventory`, which is empty for every partition on this host — so a successor with
  `zero_source: false` is refused at `:3338` unless v3 carries its own authority binding (D9).
- **Bootstrap-row revalidation walks every partition.** `_active_bootstrap_inventory` (`live.py:2662-2686`)
  calls `_revalidate_bootstrap_sources` (`:2593-2629`), which classifies each sealed worktree row through
  `_classify_repository_namespace` (`:2213-2245`); that reads the receipt at `snapshot.store_root` and
  raises unless it is a zero-source receipt owned by the bootstrap. Nothing catches that exception, and it
  runs for **every** repository's barrier — so a resolver that points `store_root` at a v3 successor would
  take down the two clean partitions with it (D9-A).
- **The latch is the fence.** `require_current_generation` (`live.py:645-666`) validates every in-lock
  append against the namespace latch; `validate_lease` refuses a DRAINING latch, a strict `None` lease, and
  any lease whose nonce/generation is not the current one. An UNDECLARED lease (`admission.py:222-229`,
  `strict=False`) passes latch validation, so on that path the canonical-store predicate is the only
  receipt gate (D6, D7 item 5). `WriterGenerationLatch.for_store_root` (`:434-436`) is
  `Path(store_root).parent.parent` — correct for the container, wrong under `generations/<n>/` (resolves to
  the identity directory, not the namespace root), and named in the derivation sweep (A0).

## Design contract

**D1 — Rotation is a ceremony, journaled and crash-idempotent.** Its own `cutover_id`, its own sealed
inventory and journal, states `DRAINING → INVENTORY_SEALED → ARMED → ACTIVE`, mirroring
`run_legacy_broker_cutover` (`live.py:1834`) and the bootstrap journal. Both files live under the authority
root at `<authority_root>/partition-rotations/<identity>/<cutover_id>.{inventory.json,journal.jsonl}` — a
directory no validator of an **ACTIVE** bootstrap enumerates (A18d proves the bootstrap's own results are
unchanged by its presence; the only walk of the authority root is `probe_zero_history_bootstrap`,
`live.py:2392-2406`, which runs for a *new* bootstrap over the same root — refused anyway — and is not on
any barrier). Crash-idempotence is proven at every state boundary in the style of
`test_fabpub_global_legacy_cutover_partitions_multiple_repositories_crash_idempotently_before_activation`
(`test_fabpub_shared_epoch.py:2700`). A journal that is torn, out of order, or carries a foreign
`cutover_id` at resume is a typed refusal — the ceremony never restarts over it. The seal locks serialise
*concurrent* ceremonies only; so a **new** ceremony for an identity refuses, typed, while any journal under
`partition-rotations/<identity>/` is not `ACTIVE` (an abandoned ceremony is resumed under its own id or
removed by an operator, never started over), and refuses if the `generations/<n>/` it would build already
exists and is not named by the journal it is resuming (A11, A13, m29).

**D2 — The successor receipt is `LegacyRepositoryPartitionReceipt.v3`.** It keeps every v2 field
(`live.py:673-700`) and adds:

- `generation` (integer ≥ 1) and `target_namespace` = the **container** path
  `repositories/<identity>` — never the generation path — so every shipped `parent.parent` derivation
  from `target_namespace` (`_inventory_row_namespace_root`, `live.py:2482-2490`; `_receipt_bootstrap_claim`,
  `:2179-2200`) keeps resolving the namespace root. The loader binds the receipt's `generation` to the
  physical path it was read from: an otherwise valid generation-1 receipt found under `generations/2/`
  is refused (A14c).
- the rotation proof: digest of **every** predecessor file (`admissions.jsonl`, `evidence.jsonl`,
  `partition-receipt.json`, and `adapter-start-owner.json` when present — the owner file is the primary
  artifact of the unknown effect), `predecessor_generation`, and the attestation digest (D4).
- `adjudicated_effect_dispositions` (D3), and the authority binding (D9-B).
- `zero_source: false` and `ambiguous: false`, both mandatory: zero-source with a predecessor on disk is a
  false proof; `ambiguous: true` would re-block the successor through `partition_is_ambiguity_blocked`.

Two carries are the ones a naive rotation drops:

- **Completed-effect idempotency, as the mechanism.** A successor starts with an empty store, so every
  predecessor `effect_terminal_observed` key must be answerable through `_legacy_terminal_replay`
  (`verbs.py:273-291`), and naming it on `legacy_completed_effect_keys` is not sufficient because nothing
  on the publish path reads that field directly. Each link is required: (1)
  `sealed_partition_effects` (`live.py:868-887`) reads per-key provenance from the sealed rotation
  inventory's `legacy_completed_effects` and requires that key set to equal the receipt list; (2) the
  provenance carries `serialized_repository`, without which `_legacy_terminal_replay` raises
  (`verbs.py:277-279`); (3) `_mint_cutover_promotion_capability` (`live.py:936-968`) re-verifies current
  bytes at the path it resolves from the provenance. Today it reconstructs that path as
  `legacy_root/legacy-archive/<loading receipt's cutover_id>/<source_id>` (`:947-951`), which would find
  nothing under a rotation; **Lane D2 extends `mint` to resolve the byte source from the sealed
  provenance** — under D7 that is the predecessor generation, in place, so the path never changes across
  rotations. Minting happens once per successor per key (`verbs.py:285-290`); later requests answer from
  the store replay (`:622-624`). Drift or deletion of the predecessor generation is a typed
  `PermissionError` at replay, never a silent second adapter call. The measured predecessor holds two
  completed keys while its own `legacy_completed_effect_keys` is empty, so a rotation that copied the
  receipt would let a completed publish call the adapter again. The carry is **transitive**: a later
  rotation carries every terminal and every prior `observed_landed` disposition forward, replayed or not.
- **Epoch monotonicity, transitively.** `legacy_epoch_high_water` (read by `authenticated_partition_floor`,
  `live.py:845-853`) is `max(predecessor receipt floor, predecessor maximum allocated epoch)` — 2 for the
  measured partition. The `max` matters when an intermediate successor allocated nothing.

**D3 — Every predecessor key is classified; the ambiguous ones are adjudicated.**

| predecessor state | successor treatment |
| --- | --- |
| `effect_terminal_observed` | carried as a completed terminal (D2), zero adapter calls |
| `outcome_ambiguous_blocked` | adjudicated — one of the two dispositions below |
| anything else non-terminal (dangling `provider_call_in_flight`, unsealed `adapter-start-owner.json` with no terminal) | **refuse** |

The inventory covers every source `epoch_blocked` recognises (`evidence.py:86-95`): canonical rows, the
receipt's `ambiguous` flag and archived history, and any unsealed owner — or refuses a partition whose
lineage it cannot enumerate. A completeness check over canonical rows only passes vacuously (A8).

**Verb scope, fail-closed.** `_legacy_terminal_replay` returns `None` for any verb other than
`publish_committed_branch` (`verbs.py:275-276`), yet non-publish verbs write terminals and blocks into the
same store (`convergence/refresh.py:63` → `BrokerVerb.PUBLISH`; `verbs.py:670-679`). Rotation therefore
**refuses a predecessor whose enumerable lineage contains any key whose verb prefix is not
`publish_committed_branch`**. Extending the carry to every verb is out of scope; the refusal keeps the gap
visible. The measured partition's three keys are all publish-prefixed.

Exactly two dispositions, carried as `adjudicated_effect_dispositions`: effect key →
`{disposition, observed_head, attestation_digest}`:

- `observed_landed` — answered as a duplicate, **no** adapter call, no provider effect.
- `attested_not_landed` — **exactly one** governed publish for that key; then ordinary idempotency.

A rotation that leaves any ambiguous key undisposed is refused. "Cannot adjudicate" (branch deleted,
force-pushed, observation destroyed) resolves to refusal — the default, stated. A force-push or re-use at
a different head is a different effect key, hence a separate adjudication. After a successful
`attested_not_landed` publish the key is an `effect_terminal_observed` row in the successor and the next
rotation carries it as history — it is never re-armed from a disposition.

**D4 — The attestation is human-authored, sealed, re-verified; the runtime never reads the remote.** Per
ambiguous key it names the observed head sha (or an explicit "branch absent at the observed time"), the
evidence a human looked at (PR/branch URL), who attested, and when. The document is sealed into the
rotation inventory and its digest pinned in the receipt; the ceremony re-verifies the bytes on every
load. **An attestation adjudicates one attempt and is spent by it**: every entry binds to the predecessor
receipt digest, the predecessor store digests, and the attempt identity — the ambiguous record and, when
present, the owner file's `owner_nonce` and `transaction_id` (`AdapterStartOwnership`, `verbs.py:51-62`).
`owner_nonce` is the discriminator; `attempt_id` (`verbs.py:535-538`) is a function of the effect key and
is identical across attempts, so binding to it alone reproduces a key-only matcher. The refusal is scoped
to adjudication: a prior `observed_landed` disposition carried as history by D2 is never re-presented and
never re-checked. The ceremony makes no `git ls-remote` or network call — "no branch on origin" and
"`ls-remote` timed out" are the same observation to this runtime (ah#789 item 3); the distinction is
*who* observes.

**D5 — Version skew, three obligations.**

1. *Forward.* The v3-aware reader refuses an unknown or future receipt schema with a typed, named
   compatibility error carrying the runtime location, which **must not subclass `LegacyCutoverConflict`**
   — `partition_is_ambiguity_blocked` (`live.py:861-865`) catches that type and converts it to `True`.
2. *Backward (load-bearing).* The v3 reader authenticates **v2** receipts byte-exactly; `agent-harness`
   and `EZBidPro` are live v2 partitions (A16, A21, m6).
3. *Retroactive (impossible; mitigated operationally).* A runtime installed before v3 cannot report the
   typed error, cannot be fenced by code it does not run, and cannot *use* a rotated partition — it
   resolves to the container (`live.py:301-303`), finds generation 0's receipt, and refuses on the
   permanent block. It never observes a receipt-less identity, so laundering through the zero-source
   onboarding route (`:3342-3354`, `:3041-3046`) is impossible by construction (A15). What a surviving
   pre-v3 **process** holding a fresh namespace lease could still do is append into generation 0 by two
   routes: `promote_legacy_terminal` for a key the generation-0 v2 receipt lists as legacy-completed
   (none, for the measured partition), and `record_terminal` for a non-`publish_committed_branch` verb
   through the path D3 cites (`verbs.py:672-680` / `refresh.py:63`), which never consults `epoch_blocked`.
   Neither launders: a post-flip generation-0 append drifts generation 0 from the digests the successor
   receipt pins, and the next carried-key replay refuses fail-closed on the byte-exact chain (A4 asserts
   the refusal, never silence). It is Dependencies 3(a)/(b) — not this enumeration — that keep
   generation 0 byte-identical. The Lane D5 runbook's running-process gate is therefore a **mutation
   fence** for the ceremony's duration, not a laundering fence; re-pinning every installed runtime is a
   **liveness** requirement (a pre-v3 install cannot publish through a rotated partition), never a
   safety one. A second liveness fact: `_stores_for` caches stores **per identity for the process
   lifetime** (`live.py:3614`, resolver consulted only on a miss) — a v3-aware process that routed the
   identity before the flip keeps its generation-0 stores, every later write is refused by the
   active-generation predicate (D6), and nothing re-resolves. The runbook's process gate therefore ends
   with a **restart** of every process that routed the identity, not only an exclusion for the ceremony's
   duration; Lane D2 may alternatively evict the identity from `_stores` on the typed active-generation
   refusal, in which case the plan's restart step becomes a verification step.

**D6 — Fencing, with its enforcement sites named.** The ceremony runs under the bootstrap seal locks, the
container's `admissions.lock` (the one lock a pre-v3 writer shares with it), and the namespace
writer-generation latch. For v3-aware writers two mechanisms fence the retired generation:

- **The resolver.** After the flip no v3-aware derivation names generation 0 as the writable store (D7
  item 3; A0 proves every derivation goes through it).
- **The latch generation bump.** Rotation drains, arms and promotes a **fresh** namespace latch generation,
  exactly as onboarding does, so `require_current_generation` (`live.py:645-666`) → `validate_lease`
  refuses every pre-flip lease on every in-lock append (generation/nonce mismatch), and refuses everything
  while DRAINING. Anchor A17: a lease acquired before the flip is refused with `WriterGenerationBlocked` on
  a generation-0 append after it; `promote_legacy_terminal` under a fresh post-flip lease writes only into
  the successor and generation 0's bytes are unchanged.
- **The active-generation predicate, at the in-lock re-check sites.** The latch validates the
  namespace lease, not store selection: a v3-aware writer whose snapshot resolved generation 0 before the
  flip (and memoised it, D7 item 3), then acquired a **fresh** post-flip lease — or one holding an
  UNDECLARED lease — passes `require_current_generation` and would append into the retired generation. So
  the layout-aware canonical-store predicate (D7 item 5) also requires, for any store under a
  `generations/` layout, that the store **is** the generation `generations/ACTIVE` names **now**, re-read
  from the pointer with D7 item 3's refusal set (a torn or absent pointer refuses, never admits). Its
  enforcement point is the **in-lock** re-check — `evidence.py:219` and `admission.py:325`, the same
  program points that re-run `_require_generation` after `fcntl.flock` — because `_authorize`
  (`evidence.py:65-83`, `admission.py:204-219`) runs **before** the lock is taken (`evidence.py:212-214`,
  `admission.py:318-321`): a writer that passes `_authorize` pre-flip, blocks on the container's
  `admissions.lock` while the ceremony holds it (D9-C), and resumes after the flip must be refused
  in-lock. `_authorize` also runs the predicate pre-lock as an early refusal, but that placement alone
  satisfies nothing. `promote_legacy_terminal` (`evidence.py:119-160`) today takes the lock at `:132`
  with **no** in-lock re-check at all and gains the same one. A store with no `generations/` keeps the
  exact v2 check. This runs for every lease kind, UNDECLARED included. Anchors A17b/c/e; mutant m26.

An UNDECLARED lease bypasses latch validation by design (`admission.py:222-229`); on that path the
layout-aware canonical-store predicates (D7 item 5) — the active-generation predicate above included — are
the only receipt gate. The latch bypass is the pre-existing SL-0 compatibility shape and this plan neither
widens nor closes it; the active-generation predicate is a store-layout check, not a latch check, and
applies on that path.

**D7 — The predecessor is never moved: rotation adds a generation.** Rounds 6–11 established that
retiring the predecessor by moving it produces a receipt-less window that every added guard merely
relocates. The maintainer's decision (2026-09-08) removes the hazard by construction.

1. **Generations; generation 0 is the container root.** `repositories/<identity>/` is generation 0,
   exactly the shape every partition has today. Later generations are
   `repositories/<identity>/generations/<n>/` for `n ≥ 1`, each a complete store (`admissions.jsonl`,
   `evidence.jsonl`, their locks, `partition-receipt.json`, any `adapter-start-owner.json`). Nothing is
   ever moved into or out of generation 0.
2. **The pointer and its initialisation.** `generations/ACTIVE` is a small regular file holding one
   generation number; `0` means the container. `generations/` is prepared at
   `repositories/<identity>/generations.tmp.<cutover_id>/` **already containing `ACTIVE` = `0`** and
   renamed into place, so "`generations/` present, `ACTIVE` absent" is unreachable. The flip is a second
   atomic rename of `ACTIVE` alone. The successor number `n` is `ACTIVE + 1`, read under the seal locks
   when the ceremony starts and recorded in the sealed rotation inventory; a resume uses the recorded `n`
   and never re-derives it. Debris left by a crash is enumerated in A11 and A13: at the temp path
   (first rotation) or as a receipt-less, non-`ACTIVE` `generations/<n>/` (later rotations — safe for
   routing under item 4), resume under the journal's own `cutover_id` may reuse or remove it; debris a
   ceremony does not own — a temp directory or a `generations/<n>/` under any other id — is a typed
   refusal (D1).
3. **Resolution lazily, memoised per snapshot, with a closed refusal set.** `RepositorySnapshot.store_root`
   is today a pure-path `@property` on a frozen dataclass (`live.py:301-303`), re-evaluated on every access
   with no I/O. It becomes a lazily evaluated, memoised read: the first access on a snapshot resolves the
   pointer, later accesses on that snapshot return the same result, and `repository_snapshot()`
   (`:284-295`) performs no pointer I/O — so classification and inventory (D9-A) never reach the resolver,
   and a refusal-state pointer refuses only the process that routes through *that* repository, never the
   barrier for the clean partitions (A18a's refusal-state leg, m23). The memoised value is a routing
   decision; the authorize-time predicate (D6) re-reads the pointer under the store lock. Resolution is:
   no `generations/` → the container (every never-rotated partition, the
   whole compatibility story, A16); `generations/ACTIVE` naming a complete, authenticated generation →
   that generation (`0` → the container). Everything else is a typed refusal, never a fall-back and never
   "no store": `ACTIVE` missing, torn, unreadable or non-integer; `ACTIVE` naming a generation directory
   that does not exist; `ACTIVE` naming a generation without an authenticated receipt; `generations`
   present as a non-directory; `ACTIVE` or any ancestor a symlink (`_require_no_ancestor_symlink`,
   `live.py:207`). Two members of that set — a symlink anywhere under the namespace, and an unreadable
   or unsupported-type file — are refused **earlier and host-wide** by the pre-existing bootstrap
   inventory walk: `_classify_repository_namespace` calls `_tree_file_inventory(snapshot.namespace_root)`
   (`live.py:2220`, `:2105-2125`) on every sealed worktree row of every barrier, before it branches on
   the receipt, and that walk `rglob`s `generations/` too, raising on any symlink (`:2111-2112`) or
   unsupported type (`:2115-2116`) and reading every file uncaught (`:2117`). That walk is stricter and
   fail-closed, and D9-A's byte-for-byte promise **keeps it**: Lane D2 neither exempts `generations/`
   from it nor catches its refusal, so the resolver's own refusal for those two members is reachable only
   when the walk is not on the path (a routing without a barrier). The per-repository isolation this item
   claims therefore holds for the resolver-only members — missing, torn or non-integer `ACTIVE`; a
   nonexistent or receipt-less generation; `generations` present as a regular file (A18a lists exactly
   these). `repository_broker_namespace` (`:331-339`), `_stores_for` (`:3608-3620`, the consumer
   that makes the resolved store the writable one; it caches per identity for the process lifetime, D5
   part 3), the barrier reads (`:3326`, `:3355`) and `credsep.py:229-242` read `snapshot.store_root`
   and inherit the resolution.
4. **The invariant.** At every instant — during the build, during either rename, after any crash, during a
   resume — the resolver names exactly one complete, authenticated store: generation 0 before the flip,
   the successor after. No reader ever observes a receipt-less identity.
5. **Layout-aware authentication is part of this change.** Three shipped checks assume the store *is*
   the identity directory and are made layout-aware in Lane D2, keeping their v2 behaviour byte-for-byte:
   `load_partition_receipt` compares `canonical_repository_identity` to `store_root.name`
   (`live.py:808-812`) — under `generations/<n>/` the identity is the containing repository directory's
   name; and the twin canonical-store predicates in `evidence.py:69-83` and `admission.py:211-214`
   (`root.parent.name == "repositories"`) — a numbered generation must still be recognised as canonical on
   **both** stores, or a receipt-less generation store is fail-open (A14b, m21) — and the same predicate
   carries the active-generation requirement (D6, m26). The `WriterGenerationLatch`
   derivation (`:434-436`) is the fourth: it takes the namespace root from the resolver (or an explicit
   argument), never `parent.parent` of the store (A17, m22).
6. **The predecessor is evidence, in place, byte-identical.** Nothing is archived, copied or re-placed;
   `mint`'s byte source never moves. A carried-key replay writes through `promote_legacy_terminal`
   (`evidence.py:119-134`) — into the successor — so A4 asserts predecessor bytes after a replay, not only
   after the ceremony.
7. **`_block_unsealed_owner` is immobile.** It is the ah#789 property. `execute()` consults
   `_legacy_terminal_replay` (`verbs.py:625`) before `_fresh_publish` (`:636`), so an `observed_landed`
   disposition resolves pre-dispatch; requests that enter `_fresh_publish` keep `verbs.py:530-548` exactly.
   The successor starts with no owner file.
8. **The journal is for resume only.** It is no longer a safety guard for any reader — the pointer makes
   the unsafe state unreachable.

**D8 — Rotation applies only to a blocked partition.** `rotate_blocked_partition` refuses a partition that
is not `epoch_blocked`; without that precondition the ceremony is a store-reset primitive.

**D9 — Authority binding (two contract decisions, settled here rather than in the lane).**

- **A. Bootstrap-row revalidation binds to generation 0.** `_classify_repository_namespace` (called from
  `_revalidate_bootstrap_sources` for every sealed worktree row, on every barrier) classifies **the store
  the sealed row recorded** — the container, `namespace_root/"repositories"/identity` — and never the
  resolved active generation. Generation 0 keeps its zero-source bootstrap receipt byte-identical forever,
  so the row stays `bootstrap_owned` after any number of rotations. Anchor A18a: with one partition rotated
  under the same sealed bootstrap authority, both clean v2 partitions still pass
  `fabpub_activation_barrier` and publish; mutant m23 (classify via the resolved root) fails it for every
  repository on the host.
- **B. The v3 receipt carries its own authority binding.** Fields: `bootstrap_claim` =
  `{authority_root, bootstrap_cutover_id, inventory_sha256}` chained from the predecessor (its bootstrap
  claim if zero-source, its own `bootstrap_claim` if v3), plus the rotation's `cutover_id` and
  `global_journal_path` (the D1 journal). `_receipt_active_authority_exists` (`live.py:3187-3217`) gains a
  v3 branch, not gated on `zero_source`: `_active_bootstrap_inventory(authority_root)` must exist with
  `cutover_id == bootstrap_cutover_id` and matching `inventory_sha256`, **and** the rotation journal must be
  `ACTIVE` for exactly the rotation `cutover_id`. `_receipt_seal_lock_paths` (`:3232-3242`) returns the
  bootstrap seal-lock paths for that authority. `_receipt_bootstrap_claim` (`:2179-2200`) is gated at its
  two authority-helper callers (`:3192`, `:3235`) and stays so; it is inert for v3 by construction.
  Anchor A18b/c: the successor enters the barrier and publishes; drop either half of the binding (m24) →
  refused at `live.py:3338`.
  **Predecessor authority chain.** `bootstrap_claim` is mandatory, so the rotation refuses, typed, a
  predecessor whose authority is not a zero-history bootstrap: a traditional-authority v2 receipt
  (`zero_source=False`, authenticated through `legacy_root_inventory`, `live.py:3209-3216`) or a v3 receipt
  whose chain does not terminate in a bootstrap claim. No partition of that shape exists on any scanned
  host; inheriting traditional authority is out of scope and named as such — it gets its own decision if
  a blocked partition of that shape ever appears. Anchor A25; mutant m27.
- **C. Lock placement.** The ceremony's seal-lock set is the bootstrap seal locks (`_bootstrap_seal_lock_paths`,
  `live.py:2459-2475`), the container's `admissions.lock` (`_target_store_lock_paths`, `:1295-1301`,
  applied to `target_namespace` = the container), **the predecessor generation's own `admissions.lock`**
  when the predecessor is not generation 0 (`EvidenceStore.lock_path` is per store, `evidence.py:58`; a
  generation-`k` writer never takes the container's lock, so without this a writer could pass authorize,
  take its own lock, pause, and append after the ceremony captured the predecessor digests), and the namespace
  latch activation lock — all held across final predecessor validation, digest capture, sealing and the
  flip. The successor generation's own `admissions.lock` is created with the generation and is not part of
  the ceremony set. Anchor A26; mutant m28.

**Lane note (D2):** `authenticated_partition_floor`'s refusal text hardcodes
"LegacyRepositoryPartitionReceipt.v2" (`live.py:845-853`); the lane that touches the loader updates it.

## Lanes

Lane order: D1 → D2 → D3 → D4, serial. D2 precedes D3 because D3 consumes the receipt field D2 adds.

### Lane D1 — falsifiers first (tests_only)

`phase-loop-runtime/tests/test_fabpub_partition_rotation_789d.py` (new). RED at this base per the repo's
RED-first idiom (`_fabpub_tdd_guard.py`, `fabpub_capability_active()`, `FABPUB_SKIP_REASON`), registered in
the frozen node-id inventory the same way the ah#789 lanes were.

**First obligation — A0, the derivation sweep.** Every store-path derivation goes through one resolver,
and the list is proven complete by a test, not by prose: an AST/grep sweep of
`convergence/broker/*.py` for `store_root`, `.parent.parent`, the `"repositories"` literal, and
`target_namespace` must report exactly the allow-listed sites, each tagged with how it is layout-aware
(resolver, container-bound, or inert). **The sweep's output is authoritative, not this list, and the
count is the test's — prose counts of this list have been wrong three times in review.** Partial seed,
each site read at this base: `RepositorySnapshot.store_root` (`live.py:301-303`, the resolver);
`repository_broker_namespace` (`:331-339`); `_stores_for` (`:3608-3620`, resolver — the consumer that
makes the resolved store writable); the barrier reads `:3326` / `:3355` (resolver; `:3360-3365` must see
the bumped latch, D6); `load_partition_receipt` (`:808-812`);
`evidence.py:69-83`; `admission.py:211-214`; `WriterGenerationLatch.for_store_root` (`:434-436`);
`_classify_repository_namespace` / `_revalidate_bootstrap_sources` / `_active_bootstrap_inventory`
(`:2213-2245`, `:2593-2629`, `:2662-2686`, container-bound per D9-A) and the inventory walk it opens
with, `_tree_file_inventory` at `:2220` (`:2105-2125`, container-bound: it *observes* the `generations/`
tree — records and refuses files, never resolves — and is kept unchanged, D7 item 3); `_receipt_active_authority_exists` /
`_receipt_seal_lock_paths` (`:3187-3217`, `:3232-3242`); `_receipt_bootstrap_claim` (`:2179-2200`, inert for
v3); `_inventory_row_namespace_root` (`:2482-2490`, container-bound via `target_namespace`);
`_target_store_lock_paths` (`:1295-1301`); `authenticated_partition_floor` / `partition_is_ambiguity_blocked`
/ `_CutoverPromotionCapability.mint` (`:845-853`, `:856-865`, `:936-968`, take a `store_root`; D8 relies
on the first two, D2 rewrites the third); the onboarding reads `:2850` and `:3040` (resolver-reaching —
must resolve to the container and refuse on receipt-present, A15) and the onboarding inventory row
`:3092` (writes the resolved root as `target_namespace`; container-bound only because onboarding is
unreachable post-rotation); `_is_onboarding_atomic_temp` (`:2153`, container-bound);
`_drive_cutover` (`:2029-2033`, mkdir + receipt write at `target_namespace`; container-bound after D2)
and the legacy-cutover partition map `:1511` with its readers (`:1583`, `:1773`, `:1786-1787`) and
`:2916` (`cutover_dir.parent.parent`) — all inert on this host (legacy cutover is not the bootstrap
route) and tagged so, not assumed; `credsep.py:229` and `:240-242` (read the snapshot). A new derivation
that is not on the list fails the sweep.

Anchors:

- **A1** `observed_landed` → the key is answered as a duplicate, adapter counter 0, no provider effect
  (rows materialised per the `_legacy_terminal_replay` idiom are correct).
- **A2** `attested_not_landed` → exactly one adapter call; the second attempt is refused by idempotency.
- **A3** an undisposed ambiguous key → refused before anything durable is written.
- **A4** predecessor generation byte-identical, every file (`admissions.jsonl`, `evidence.jsonl`,
  `partition-receipt.json`, `adapter-start-owner.json`), asserted **after a carried-key replay**; the owner
  digest appears in the successor receipt; and a post-flip generation-0 append by a foreign writer (a
  pre-v3 process, D5 part 3) makes the next carried-key replay refuse with the typed byte-exact-chain
  error — fail-closed, never silent.
- **A5** the successor has no `adapter-start-owner.json`; an `observed_landed` key is answered pre-dispatch
  with no owner read or write; `_block_unsealed_owner` still blocks a crashed `attested_not_landed` first
  attempt.
- **A6** a predecessor terminal replayed against the successor is a duplicate through the mint path
  (`live.py:936-968`), asserted by the mint having run; after a second rotation (fixture re-blocked by a
  publish-prefixed key) the second successor still answers the first predecessor's terminals and its
  unreplayed `observed_landed` dispositions; predecessor-generation drift or deletion → typed
  `PermissionError`, never a second adapter call.
- **A7** attestation reuse: rotate K with attestation A, publish K once, drive it to a fresh ambiguity,
  present A again → refused; a new attestation naming the new attempt succeeds.
- **A8** a predecessor blocked only through a receipt-carried ambiguity (`ambiguous: true` with empty
  canonical evidence, or an archived orphaned `provider_call_in_flight`) is refused unless adjudicated.
- **A9** a partition that is not `epoch_blocked` is refused by `rotate_blocked_partition`.
- **A10** a lineage containing a non-`publish_committed_branch` key is refused.
- **A11** crash sweep: before `generations.tmp.<id>` is renamed into place, between that and the first
  successor file, between successor files, after the successor receipt but before the flip — at each
  point generation 0 is the routable store, an ordinary publish refuses on the permanent block, and
  `onboard_zero_legacy_repository` at that identity refuses because a receipt is present; then resume
  succeeds and the successor authenticates and carries terminals and dispositions. Temp-path debris under
  the journal's id is consumed by resume; debris under a foreign id is a typed refusal; a resume rebuilds
  the recorded `n`; a new ceremony started while the crashed one's journal is not `ACTIVE` is a typed
  refusal.
- **A12** pointer states are total: `generations/` arrives already containing `ACTIVE=0` by rename; the
  flip replaces `ACTIVE` by rename so a crash leaves exactly one complete generation named; every member of
  D7 item 3's refusal set is a typed refusal, never a fall-back to the container or to onboarding. The
  "unreadable `ACTIVE`" leg cannot be constructed by permissions when the suite runs as root (CI's Dagger
  container does): it is exercised by patching the pointer read to raise `OSError`, and a leg that is
  skipped for lack of a construction is a failure, not a skip.
- **A13** second rotation: re-block the successor, rotate again, repeat A11 against generation 2 —
  including a crash that leaves a receipt-less, non-`ACTIVE` `generations/2/`: routing still names
  generation 1, resume under the same id completes it, and a ceremony under a different id refuses the
  existing `generations/2/`; generations 0 and 1 untouched; carried terminals and dispositions still
  answer through the mint path; the epoch floor still rises (`max(...)`, m12).
- **A14** layout-aware authentication: (a) a receipt under `generations/<n>/` naming a different identity
  is refused; (b) a numbered generation with no receipt is refused by the canonical-store predicate on
  **both** the evidence and the admission store under an UNDECLARED lease; (c) an otherwise valid
  generation-1 receipt placed under `generations/2/` is refused; (d) all three keep exact v2 behaviour for
  a store with no `generations/`.
- **A15** pre-v3 reader (this head's code): driven at every A11 crash point it resolves to the container,
  finds generation 0's receipt, refuses on the permanent block; creates no successor receipt, makes no
  adapter call; after the flip it still cannot use the successor (D5 part 3).
- **A16** the two live v2 partitions are byte-for-byte unaffected: a store with no `generations/` resolves
  to exactly today's path and publishes through the governed path unchanged.
- **A17** write fencing: (a) a lease acquired before the flip is refused with `WriterGenerationBlocked`
  on a generation-0 append after the flip; (b) a writer whose snapshot resolved generation 0 **before** the
  flip and acquires a **fresh** post-flip lease is refused at authorize time by the active-generation
  predicate on both the evidence and the admission store, generation 0 unchanged; (c) the same writer
  under an UNDECLARED lease is refused the same way; (d) `promote_legacy_terminal` under a fresh post-flip
  lease and a post-flip snapshot writes only into the successor (the store *is* the successor by
  construction — this leg pins that nothing else is written); (e) a writer that passed authorize
  **before** the flip and was blocked on the store lock across it is refused **in-lock** after the flip —
  under an UNDECLARED lease through `_append` / the admission path, and under a declared lease through
  `promote_legacy_terminal` — generation 0 unchanged.
- **A18** authority binding: (a) after one rotation, both clean v2 partitions pass
  `fabpub_activation_barrier` and publish — and still do with the rotated partition's pointer placed in
  each **resolver-only** refusal state in turn (`ACTIVE` missing, torn, non-integer; naming a nonexistent
  generation; naming a generation without an authenticated receipt; `generations` present as a regular
  file), the refusal surfacing only when the rotated repository itself is snapshotted for routing; the
  symlink and unreadable members are asserted the other way — the barrier refuses **host-wide** from the
  inventory walk (`live.py:2111-2117`), before any resolver runs, exactly as it does today; (b) the successor passes the barrier and publishes; (c) a
  successor missing either half of D9-B's binding is refused at `live.py:3338`; (d) the presence of the
  D1 rotation directory under the authority root changes no bootstrap validation result.
- **A19** crash injection at every journal boundary is resumable; a torn or foreign-id journal at resume
  is a typed refusal, never a restart.
- **A20** an unknown/future receipt schema → the typed compatibility refusal naming schema and runtime
  location, not `partition_is_ambiguity_blocked`'s message.
- **A21** an untouched v2 receipt authenticates byte-exactly; a clean v2 partition publishes unchanged.
- **A22** laundering falsifier: a fresh authority root pointed at a namespace holding a populated
  partition must refuse to bootstrap, asserting **where** it refuses — expected at
  `_classify_repository_namespace` (`live.py:2228-2239`: a receipt is present whose `cutover_id` and
  bootstrap claim are not the fresh authority's), which fires before any write; if the run shows a later
  site (`LegacyRepositoryPartitionReceipt.write`, `:734-750`) the PR body records that instead. If it does
  not refuse, closing the hole joins this plan's scope and the PR body records it.
- **A23** successor floor = `max(predecessor receipt floor, predecessor max allocated epoch)`, including
  through an intermediate successor that allocated none.
- **A24** no network or `git ls-remote` call anywhere in the ceremony (recording sentinel idiom from
  `test_fabpub_recovery_controls_789.py`).
- **A25** a predecessor whose authority is not a zero-history bootstrap — a traditional-authority v2
  receipt (`zero_source=False`, `legacy_root_inventory` populated) or a v3 receipt with no bootstrap claim
  in its chain — is refused by `rotate_blocked_partition` with the typed out-of-scope error before any
  durable write (D9-B).
- **A26** predecessor-generation lock: during a generation 1 → 2 rotation a generation-1 writer that has
  authorized inside `generations/1/admissions.lock` and paused cannot append after the ceremony captured
  the predecessor digests — the ceremony holds that lock across validation, digest capture, sealing and
  the flip, so the writer's append lands before the digests are taken or is refused after the flip by the
  active-generation predicate; the successor receipt's predecessor digests match generation 1's final
  bytes.

### Lane D2 — receipt schema, resolver, and the rotation ceremony (production)

`convergence/broker/live.py`: `LegacyRepositoryPartitionReceipt` → v3 (D2, D9-B);
`rotate_blocked_partition(...)` in the shape of `onboard_zero_legacy_repository`; the rotation
inventory/journal/seal-lock helpers (D1, D9-C); the typed pre-v3 refusal (D5); the generational resolver
and `generations/ACTIVE` pointer (D7 items 2–3); the latch-derivation and layout-aware checks (D7 item 5,
across `live.py`, `evidence.py`, `admission.py`); `mint`'s provenance-resolved byte source (D2); the
container-bound classification (D9-A); the v3 branches of the two authority helpers (D9-B). The A0 sweep
is re-run green at the end of the lane.

### Lane D3 — dispositions honoured on the publish path (production)

`convergence/broker/verbs.py`, on the pre-dispatch replay path (`execute` → `_legacy_terminal_replay`,
`:625`) — not inside `_fresh_publish`: `observed_landed` resolves as a completed terminal there;
`attested_not_landed` falls through and proceeds exactly once. No change to the four `epoch_blocked`
consult sites, to `_block_unsealed_owner`, or to `evidence.py:229-230`.

### Lane D4 — operator surface and docs

`phase-loop fabpub rotate-partition` taking the attestation document and driving the ceremony;
`docs/fabpub-pre-admission-ambiguity.md` gains the rotation section (replacing "deferred"); CHANGELOG.

### Lane D5 — execute the omniagent-plus rotation (operational, not a PR)

After D1–D4 land: attest `…54771bd3` as `observed_landed` citing Consiliency/omniagent-plus#28 and the
2026-09-06 override comment, rotate `1da3e343…`, demonstrate one governed publish for omniagent-plus.
Separate maintainer authorisation; nothing here executes it.

## Documentation impact

- `docs/fabpub-pre-admission-ambiguity.md` — modify — replace "Partition rotation (deferred)" with the
  landed ceremony; update the carried-item paragraph once item (5) is discharged.
- `CHANGELOG.md` `## [Unreleased]` — add — one entry per landed lane.
- `plans/manifest.json` — add — `type=detailed` entry for this plan.
- `specs/phase-plans-v10.md` — none (LEGIBLE-owned; no roadmap goal changes).
- `plans/decision-interim-president-ratification-20260904.md` — ledger row per production_code/plan landing.

## Dependencies & order

1. Maintainer approval → plan-tier board → land (ledger row). Four seats or a recorded deviation of the
   ah#805 shape — never silently on three.
2. Lanes serial as stated under Lanes.
3. D5 after all lanes land, with its own authorisation, after: (a) every installed `phase-loop-runtime` on a
   host that can write FABPUB state is re-pinned to a v3-aware build (`uv tool install --force
   "git+https://github.com/Consiliency/agent-harness@<main sha>#subdirectory=phase-loop-runtime"`, never from
   a working checkout — ah#789's root cause), verified by a version probe that checks the installed
   runtime recognises `LegacyRepositoryPartitionReceipt.v3`; (b) no pre-v3 **process** with a namespace
   lease on the target repository is running for the ceremony's duration (the D5 part 3 mutation fence);
   (c) every host that can write FABPUB state has been scanned — the Windows host has not — so a rotation
   is not performed while a second blocked partition is unknown.

## Verification

- CI-faithful suite (source mode, with the CI-faithful interpreter — an installed-venv build of
  `phase-loop-runtime`, never a working checkout's `python`):
  `cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests <ci-venv>/bin/python -m pytest
  -p no:cacheprovider -o addopts="" -q tests/test_fabpub_partition_rotation_789d.py
  tests/test_fabpub_shared_epoch.py tests/test_fabpub_zero_history_bootstrap.py
  tests/test_fabpub_recovery_controls_789.py` — green; frozen corpus counts unchanged
  (`test_fabpub_guard_nodeid_inventories_are_disjoint_and_counted`).
- Every Lane D1 falsifier RUN with its observed failure text in the PR body — never "should fail".
- Named mutants, each RUN, phrased as the detection it produces:
  (m1) drop the undisposed-key check → A3 accepts; (m2) carry the block as `ambiguous=True` → A1/A2
  blocked; (m3) let `observed_landed` reach the adapter → A1 counter is 1; (m4) let `attested_not_landed`
  publish twice → A2's second attempt succeeds; (m5) route an unknown schema through the ambiguity path →
  A20 gets the permanent-block message; (m6) accept only v3 → A21's v2 partition stops authenticating;
  (m7) drop the terminal carry → A6 reaches the adapter; (m8) omit the owner digest → A4; (m9) allow
  rotation of an unblocked partition → A9; (m10) inventory ambiguity from canonical rows only → A8 rotates
  the obligation away; (m11) skip the verb-scope refusal → A10; (m12) drop the `max(...)` → A23/A13 floor
  reads 0; (m13) suppress the adapter without minting → A6's mint assertion fails; (m14) match an
  attestation on key alone → A7's reuse is accepted; (m15) flip `ACTIVE` before the successor receipt
  authenticates → A11 finds an incomplete generation routable; (m16) write `ACTIVE` in place, or create
  `generations/` before seeding `ACTIVE=0` → A12 observes an absent or torn pointer; (m17) treat a missing,
  torn or unreadable `ACTIVE`, an `ACTIVE` naming a generation directory that does not exist, or
  `generations` present as a non-directory as "no generation" → A12's fail-closed legs admit an
  unauthenticated store;
  (m18) resolve to the container when `generations/` exists → A11's resume fails, successor never
  routable; (m19) resolve through `generations/` for a store that has none → A16 regresses; (m20) rewrite
  the predecessor generation during the ceremony → A4; (m21) keep either canonical-store predicate
  parent-shaped, or compare identity to `store_root.name` under a generation → A14a/b; (m22) keep
  `WriterGenerationLatch.for_store_root` as `parent.parent` → every successor append is
  `WriterGenerationBlocked`, A17 and A18b fail; (m23) classify the bootstrap row via the resolved root →
  A18a refuses every repository on the host; (m24) drop either half of the v3 authority binding → A18c
  is not refused / A18b is refused at `live.py:3338`; (m25) bind the receipt to no physical generation →
  A14c accepts the misplaced receipt; (m26) drop the `ACTIVE` re-read from either
  canonical-store predicate → A17b/c append into generation 0, or keep it **pre-lock only** (in `_authorize`
  but not at `evidence.py:219` / `admission.py:325` / inside `promote_legacy_terminal`) → A17e appends
  into generation 0; (m27) accept a traditional-authority
  predecessor → A25 rotates it; (m28) omit the predecessor generation's `admissions.lock` from the
  ceremony set → A26's paused writer appends after digest capture; (m29) skip the existing-`generations/<n>`
  or non-`ACTIVE`-journal check → A11/A13's foreign-id ceremony overwrites debris.
- Read-only host re-inspection after D5: generation 0's files are byte-identical to their pre-rotation
  state and digest-match the successor receipt.

## Acceptance criteria

- [ ] A rotation of a blocked partition whose ambiguous key is attested `observed_landed` yields a successor
      that publishes a fresh, unrelated branch through the governed path and answers the attested key as a
      duplicate with zero adapter calls (m3).
- [ ] The same rotation attested `attested_not_landed` permits exactly one governed publish of the exact
      intended branch and refuses the second by ordinary idempotency (m4) — ah#789 item (5)'s first half,
      discharged as a capability.
- [ ] A rotation leaving any predecessor `outcome_ambiguous_blocked` key undisposed is refused before any
      durable write (m1).
- [ ] The successor receipt authenticates through `load_partition_receipt` byte-exactly, carries
      `zero_source: false`, `ambiguous: false`, an explicit `generation` bound to its physical path, and
      pins the predecessor digests plus the attestation digest (m2, m25).
- [ ] A v3-aware reader raises the typed compatibility refusal for an unknown/future schema (m5) and still
      authenticates an untouched v2 receipt byte-exactly so a clean v2 partition publishes unchanged (m6);
      the pre-v3 install's misleading message is documented as unfixable, with the re-pin as its liveness
      mitigation.
- [ ] Every predecessor `effect_terminal_observed` key is carried with the provenance
      `_legacy_terminal_replay` requires and answered through the mint path, still after a second rotation
      (m7, m13).
- [ ] The predecessor store is byte-identical after rotation and after a carried-key replay, every file
      included; the owner digest is pinned; the successor carries no owner file (m8, m20).
- [ ] A predecessor blocked only through a receipt-carried ambiguity or an archived orphaned
      `provider_call_in_flight` is refused unless adjudicated (m10).
- [ ] `rotate_blocked_partition` refuses a partition that is not `epoch_blocked` (m9).
- [ ] The successor's `legacy_epoch_high_water` equals `max(predecessor receipt floor, predecessor maximum
      allocated epoch)`, including after a second rotation through a successor that allocated none (m12).
- [ ] An `attested_not_landed` attestation is bound to the predecessor digests and the attempt identity, is
      spent by the one publish it authorises, and cannot adjudicate a later ambiguity of the same key (m14).
- [ ] A predecessor whose lineage contains a non-`publish_committed_branch` key is refused (m11); extending
      the machinery to every verb is out of scope and named as such.
- [ ] At every instant of the ceremony and of any crash, the resolver names exactly one complete,
      authenticated store — generation 0 before the flip, the successor after; every member of the pointer
      refusal set is a typed refusal, never a fall-back (m15, m16, m17, m18, m21); the successor number is
      read once under the seal locks and recorded, and a ceremony never starts over an abandoned one or
      over a `generations/<n>/` it does not own (m29).
- [ ] Every store-path derivation in `convergence/broker/*.py` is on the A0 allow-list and tagged
      layout-aware; the sweep test fails on an unlisted derivation, and the latch derives the namespace root
      through the resolver (m22).
- [ ] Bootstrap-row revalidation binds to generation 0: after one rotation under the sealed bootstrap
      authority, every clean v2 partition on the host still passes `fabpub_activation_barrier` and publishes
      (m23); the successor passes the barrier through its v3 authority binding and is refused at
      `live.py:3338` without it (m24).
- [ ] A lease acquired before the flip is refused on a generation-0 append after it; a writer that resolved
      generation 0 before the flip is refused under a fresh post-flip lease and under an UNDECLARED lease,
      and a writer that passed authorize pre-flip and was blocked on the store lock across the flip is
      refused **in-lock** afterwards, including through `promote_legacy_terminal`; a post-flip
      `promote_legacy_terminal` writes only into the successor (m22, m26, and A17 under m18).
- [ ] A predecessor whose authority is not a zero-history bootstrap is refused before any durable write
      (m27); inheriting traditional authority is out of scope and named as such.
- [ ] The ceremony holds the predecessor generation's own `admissions.lock` across validation, digest
      capture, sealing and the flip, so a paused in-lock writer cannot append after the digests are taken
      (m28).
- [ ] The runtime performs no network or `git ls-remote` call anywhere in the ceremony, proven by the
      recording sentinel idiom.
- [ ] The laundering question is answered in the PR body with a RUN result: whether a fresh authority root
      can bootstrap over a populated namespace, and — if it can — the guard that closes it.

## Execution Policy

- execute: effort=high, reason=a new authority-ceremony and a receipt schema version on the fencing path;
  every anchor is a fail-closed guarantee and the failure mode is silent unblocking.

## Amendments

### A1 — Lane D3 disposition (2026-09-09, recorded from Consiliency/agent-harness#789 comment 5605551240)

Lane D3 predicted an edit to `convergence/broker/verbs.py` on the pre-dispatch replay path. The
property it named is delivered on `main` by Lane D2 (Consiliency/agent-harness#816, merge `55e9ba89`)
without touching `verbs.py`: `_rotation_carried_effects` seals every `observed_landed` disposition into the
successor's `legacy_completed_effects` and pops `attested_not_landed` from the carry, so the unchanged
`execute` → `_legacy_terminal_replay` answers an `observed_landed` key as a duplicate pre-dispatch and an
`attested_not_landed` key proceeds into `_fresh_publish` exactly once. RUN on a detached `55e9ba89`
checkout: D1 anchors A1, A2, A5, A11b, A13b pass; plan mutants m3 and m4 red A1/A5 and A2/A5 respectively.
Lane D3 is closed with no PR — the plan pinned its own output (the edit location), which `AGENTS.md`
names as the stalling class; this amendment records the delivered mechanism in place of the prediction.
`_block_unsealed_owner`, the four `epoch_blocked` consult sites, and `evidence.py:229-230` are untouched.

### A2 — Lane D4 verb spelling and scope (2026-09-09, Consiliency/agent-harness#818)

- The verb is spelled `phase-loop fabpub-rotate-partition` (one flat argparse subcommand, mirroring the
  existing `fabpub-bootstrap`), not the plan's `phase-loop fabpub rotate-partition`. Same surface; the
  spelling follows the CLI's existing shape rather than introducing a nested `fabpub` group.
- The verb refuses an attestation path at or under `<authority-root>/partition-rotations/` before reading
  it (fable r9 O3: the resume is never sourced from the copy a sealed inventory embeds).
- Its output (`PartitionRotationResult.v1`) carries `restart_required` with the reason: a broker process
  that resolved the repository before the flip holds a retired generation lease (`_stores_for` caches
  stores per router instance), so its next write is a typed refusal until it restarts.

### A3 — Items carried out of the D2 boards (Consiliency/agent-harness#789 comment 5605496788), dispositions in D4

Closed in Consiliency/agent-harness#818:

- **fable r10 O2** — closed at the loader as a class: `load_partition_receipt` raises
  `LegacyCutoverConflict` for receipt bytes that are not JSON or not an object (every fail-closed
  `except LegacyCutoverConflict` site is covered at once), and both ceremony re-read sites name a successor
  that "carries no receipt" instead of falling into the `!= receipt` comparison.
- **fable r12 O2** — `sealed_partition_effects` raises `LegacyCutoverConflict("… is missing …")` when the
  inventory is absent behind a receipt that names completed keys; a receipt naming no keys keeps `{}`.
- **fable r12 O1 / gemini r12 nit** — A11t pins the exact read multiset `[Path.open, Path.read_bytes]` of
  the sealed inventory.
- **Publish-path inventory TOCTOU** (closed by D2 r12) — the refusal is named in the operator note.

Carried, not D4 work (plan spellings or no-action notes, verbatim in the comment): D9-C container-lock
alternative; fable r1 F4; fable r2 O1 (ancestor symlink parity); fable r5 O3 (unreachable-false receipt
check, keep as defense in depth); fable r8 O3 (A11n fixture floor); fable r10 O3 (a finish refused with the
honest inventory lost is repaired by re-running the verb with the operator-supplied attestation — the D5
runbook step); fable r11 O5; fable r6 O4 (a `no_effect_terminal_proven` key is NOT carried; the successor
publishes afresh — D4 keeps the D2 anchor, A8 leg (v)). Filed: Consiliency/agent-harness#817 (v2 container
loader trusts `global_journal_path`), Consiliency/agent-harness#811 (order-dependent
`test_fabpub_shared_epoch` import).

### A4 — Lane D5 preconditions restated (no change)

D5 stays operational and unauthorised here. Its preconditions are the three in "Dependencies & order" item
3 plus: every writer of the omniagent-plus partition stopped for the ceremony's duration (the verb's
`restart_required` is the same fact from the other side), and the attestation written outside the
authority's `partition-rotations/` directory.
