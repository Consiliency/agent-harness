---
plan_kind: detailed
issue: agent-harness#1310
origin: advisor-board ruling on agent-harness#1298 (grok F1, option a)
---

# FABPUB: carry an `attested_not_landed` disposition across later rotations

## Context

agent-harness#1296 lets the successor of a rotation re-admit an already-admitted
publish transaction once, when the rotation's authenticated attestation disposes
its effect key `attested_not_landed` and binds its `transaction_id`.
`attested_not_landed_recovery(store_root, key)` (`convergence/broker/live.py`)
reads only the ACTIVE generation's receipt. A rotation forced by an unrelated
blocked key, run before the retry, therefore loses the disposition. The retry is
refused with `PublicationRecoveryRequired`, and no rotation can fix it, because
the key is not blocked in the active generation.

Fix: walk the authenticated receipt chain from the active generation back to the
rotation that disposed the key. Authorize only when no generation since then holds
evidence for the key and no later receipt adjudicates or carries it.

## Facts this relies on (verified in code)

- **Chaining.** Generation `g >= 1` lives at `<container>/generations/<g>`; generation 0
  is the container. `_load_rotated_partition_receipt` authenticates a v3 receipt against
  its ARMED journal and sealed inventory (exact bytes), requires
  `predecessor_generation == g - 1` (`_require_rotation_receipt_binds`), requires the
  predecessor's `ROTATION_DIGESTED_FILES` (`admissions.jsonl`, `evidence.jsonl`,
  `partition-receipt.json`, `adapter-start-owner.json`) to equal the digests sealed at
  rotation, and then recursively loads the predecessor's receipt. So
  `load_partition_receipt(gen g)` authenticates the whole chain below `g`, and every
  sealed generation's evidence bytes are digest-bound by its successor's receipt.
- **What a rotation needs.** `_adjudicate_rotation_predecessor` needs at least one
  `outcome_ambiguous_blocked` key, refuses dangling intents and an unsealed owner with no
  terminal, and requires the attestation to cover exactly the blocked keys. It carries
  `effect_terminal_observed` keys and `observed_landed` dispositions into
  `legacy_completed_effect_keys`, and drops `attested_not_landed` keys from the carry.
- **Replay.** `execute` replays any record that the active generation's evidence holds
  for the key, and promotes carried legacy completed effects, before `_fresh_publish`
  runs.

## Design

### 1. The walk (`attested_not_landed_recovery`, plus private helpers in live.py)

Let `A` be the active generation (taken from `store_root`).

1. `receipt[A] = load_partition_receipt(store_root)`. If it is not a
   `RotatedPartitionReceipt`, return `None` (as today).
2. For `g = A, A-1, …, 1`:
   - `receipt[g]` is authenticated: for `g = A` by step 1; for `g < A` by
     `load_partition_receipt(gen g)`, whose receipt bytes must also equal the
     `partition-receipt.json` digest sealed in `receipt[g+1].predecessor_digests`.
     That ties the walked object to the chain the active receipt authenticated.
   - If `key` is in `receipt[g].legacy_completed_effect_keys`, refuse
     (`RecoveryChainSuperseded`): a later rotation carried the key as landed.
   - If `key` is in `receipt[g].adjudicated_effect_dispositions`, stop here.
     **The first disposition met is the current word.** If it is not
     `attested_not_landed` (for example `observed_landed`), return `None`. An older
     `attested_not_landed` below it must not be reachable. Otherwise
     `d = g`, and the attestation is verified exactly as today against
     `receipt[d]`'s sealed inventory.
   - Otherwise continue to `g - 1`.
3. If `g` reaches 0 (the container's v2 receipt has no dispositions), return `None`.
4. **Evidence sweep over `[d, A]`.** The re-admission that `receipt[d]` authorizes
   happens in generation `d` or later. Generation `d-1` legitimately holds the
   blocked row and is excluded. For each sealed generation `g` in `[d, A-1]`, read
   `evidence.jsonl` and `adapter-start-owner.json` once each. Require their sha256 to
   equal `receipt[g+1].predecessor_digests[...]`, then strict-parse
   (`_parse_strict_jsonl`). Any evidence row for `key`, or an owner naming `key`,
   refuses `RecoveryChainSuperseded` with the generation named. Generation `A` (live)
   is checked by the caller: `execute` replays it, and it is re-checked under the
   admissions lock (§2).

`RecoveryChainSuperseded` subclasses `LegacyCutoverConflict` (a `RuntimeError`), so
every caller that already fails closed on authentication failures also fails closed on
this. `_recovery_authority` catches it first and gives it its own refusal text.

**Tampering.** Any intermediate receipt, journal or inventory drift raises in
`load_partition_receipt` (`LegacyCutoverConflict` / `PartitionRoutingRefused`).
Evidence or owner drift fails the digest comparison. Both are refused typed before
any write, through the existing `except (RuntimeError, PermissionError, OSError,
ValueError)` in `_recovery_authority`.

### 2. "Once" across generations

The invariant: **at most one re-admission per disposition, i.e. evidence for `key`
in at most one generation of `[d, A]`**. A re-admission writes the owner and the
admission and then `record_intent(key)` into its generation's evidence. If the
attempt crashed before the intent, its unsealed owner is promoted to a blocked row
by `_block_unsealed_owner` before any rotation can proceed (a rotation refuses an
unsealed owner without a terminal). So any attempt in a sealed generation `g` leaves
an evidence row in `g` that the sweep sees. An attempt in the active generation is
caught by the existing in-lock check, `self.evidence_store.replay().get(recovery_key)`.

Sealed generations are digest-frozen: changing them breaks the authentication of the
active receipt. So the only bytes that can race the authority check are the active
generation's. Those are what the in-lock check reads. **The in-lock branch of
`_owner_and_admission_under_one_lock` therefore needs no logic change.** Only the
refusal text changes ("this generation" becomes "the re-admitting generation").
Nothing else in that function is touched (Lane A owns it).

A second ambiguous attempt in generation `g >= d` blocks `g`. The next rotation must
adjudicate the key again: the first disposition the walk then meets is that new one.
This is the existing "do not re-attest without evidence" runbook case. It is
unchanged.

### 3. Bound and cost

The walk ends after at most `A` steps, because each receipt enforces
`predecessor_generation == generation - 1` and generation 0 ends it. It stops early
at the disposing generation. Each `load_partition_receipt(gen g)` re-authenticates
the chain below `g`, so the cost is O(A · (A − d)) small file reads, only on the
recovery path (an already-admitted transaction). No arbitrary cap is added: a cap
would turn a valid long chain into an unrecoverable refusal. Partitions rotate only
on operator-attested ambiguity, so `A` stays small in practice.

### 4. Provenance

The returned dict keeps every current field. The authority fields (`cutover_id`,
`attestation_sha256`, `inventory_sha256`, `attested_by`, `predecessor_generation`)
come from the **disposing** receipt `receipt[d]`. `generation` becomes the
**re-admitting** (active) generation `A`. That keeps
`<tid>.recovery.<generation>.json` meaning "the generation whose evidence holds the
outcome". New fields:

- `disposing_generation: d`
- `readmitting_generation: A`
- `intervening_rotations`: the `cutover_id`s of `receipt[d+1..A]`, oldest first

With no intervening rotation, `d == A`, and `generation` / `predecessor_generation`
equal today's values.

### 5. Tests: new `tests/test_fabpub_recovery_chain_1310.py`

These reuse the fixtures in `test_fabpub_sealed_head_recovery_1296.py`
(`_failed_sealed_publish`, `_owner`) and `test_fabpub_partition_rotation_789d.py`
(`_rotate`, `_attestation`, `_block_key`, `_routed_service`,
`_publish_on_successor`, `ROTATION_ID_2`) by import.

- **C1, the positive case.** R1 disposes K; an unrelated key blocks generation 1; R2
  rotates it. The retry makes one provider call and publishes. Its record is
  `.recovery.2.json` with `disposing_generation 1`, `readmitting_generation 2`,
  `intervening_rotations [R2]`, and `cutover_id R1`. A second retry replays with no
  provider call.
- **C2, two intervening rotations** (generations 1→2→3). Recovery succeeds in
  generation 3.
- **C3, a later generation holds evidence for K.** After R1, seed an evidence row for
  K in generation 1 (a terminal-proven/no-effect row, so the rotation can still
  proceed) and block an unrelated key. R2 rotates. Call `_fresh_publish` directly,
  bypassing `execute`'s replay. Expect `PublicationRecoveryRequired` naming
  generation 1, and no owner, admission or provider call. Mutation check: drop the
  sweep, and the test fails.
- **C4, a later receipt re-adjudicates K differently.** Drive it directly through
  `attested_not_landed_recovery` on a chain whose newer receipt disposes K
  `observed_landed`, or carries it. Expect `None` / refusal. Mutation check: continue
  past the first disposition, and the test fails.
- **C5, tampered intermediate receipt** (generation 1 receipt bytes changed after R2).
  Expect a typed refusal, no write, and no provider call.
- **C6, tampered intermediate evidence**, with the digest check alone exercised by
  monkeypatching the loader. Expect a typed refusal. Mutation check: drop the digest
  comparison, and the test fails.
- **C7, transaction id mismatch across an intervening rotation.** Still refused,
  naming the bound transaction.

The existing 1296 assertions on the old text change with it.
`test_intervening_rotation_refuses_without_promising_a_rotation_fix` becomes C1's
predecessor and is removed there. Both are disclosed in the PR.

### 6. Messages and docs

- `_recovery_authority`: the `None` refusal no longer cites agent-harness#1310. It says
  no rotation in the authenticated chain disposes the key and that the key is not
  blocked in the active generation. A new branch handles `RecoveryChainSuperseded`:
  the disposition was used or superseded in generation N; inspect that generation's
  evidence with the maintainer.
- `publishing.py` `_human_publication_handoff`, recovery branch only: "a rotation
  disposes only keys blocked in the active generation; an earlier disposition is
  honoured until the key gains evidence".
- Runbook §8a: replace "retry straight after the rotation" with "retry before the key
  gains new evidence; later rotations for other keys no longer supersede the
  disposition". Keep the "do not re-attest without evidence" paragraph.
- `docs/fabpub-pre-admission-ambiguity.md`: the same correction, plus the single-use
  statement over `[d, A]`.

## Registration

- `tests/data/seat_launch_references.json`: add `host-io` rows for new `read_bytes`
  sites in the new live.py helper(s).
- The 789d A0 sweep: avoid new `.store_root` / `.parent.parent` attribute sites in the
  helpers (use `_partition_layout`). If one is unavoidable, add it to `A0_ALLOW_LIST`
  and `A0_CLASSIFICATION`.

## Verification

From `phase-loop-runtime/`:
`PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider tests/test_fabpub_*.py tests/test_seat_reference_inventory.py`
plus `ruff check` on the touched files. Each mutation named in §5 is run by hand and
must turn its test red.

## Open questions

- A `no_effect_terminal_proven` row for K in a later generation refuses too. That is
  fail-closed, and this plan does not resolve whether it should instead allow.
- Records written by the agent-harness#1296 code for the same generation lack the new
  fields, so a re-write conflicts (typed `PublishTransactionConflict`). That needs a
  record written but no owner, an upgrade, and then a retry, which is narrow and fails
  closed.
