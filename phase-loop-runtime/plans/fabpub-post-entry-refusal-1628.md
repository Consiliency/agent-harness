# FABPUB: a generation refusal after provider entry

Addresses agent-harness#1628, plus agent-harness#1640 asks 1–4 in the same PR.
Builds on the refusal table in `plans/fabpub-typed-handoffs.md`.

## Problem

In `BrokerService._fresh_publish`, the provider has been entered
(`provider_entered = True`) and `adapter.execute` raises. The except arm then
writes `outcome_ambiguous_blocked` with `record_terminal` (and `record_intent` if
the row is missing). Both writes go through `_append` → `_require_generation`,
which refuses strictly. If the latch is DRAINING, or the shared lease has been
revoked, that write raises `WriterGenerationBlocked`. It escapes as a plain
`PermissionError`, and `publish_human_invoked_from_worktree` answers
`repair_fabpub_authority`.

The store is left with the key `provider_call_in_flight` and the owner unsealed.
The adapter's own pre-push check (`credsep._revalidate_generation_before_effect`)
raises inside `execute`, after entry, so it reaches this arm today. The planned
agent-harness#820 fence adds a second site between push and PR create.

## Why the answer is "retry once", not "rotate"

A rotation refuses a predecessor that has an intent with no terminal ("predecessor
evidence has intents without a terminal"). This key has exactly that until a fresh
publish's `_block_unsealed_owner` promotes the owner to `outcome_ambiguous_blocked`.
So sending the operator straight to rotation sends them to a step that refuses.
The stored shape is the same one agent-harness#1594 handles before entry. The
handoff is the same, `retry_once_before_partition_rotation`. The one difference is
that the provider *was* entered.

## Contract

1. **New type.** `live.ProviderEffectGenerationRefused(WriterGenerationBlocked)`
   carries `effect_key` and `transaction_id`, and keeps the original message.
   It is deliberately **not** a `ProviderEntryRefused`. That type means "never
   entered", and the attestation guidance relies on it.
2. **Where it is raised.** It is raised only in the `_fresh_publish` except arm, with
   `provider_entered` true and no observation, when the ambiguous-terminal write
   (`record_intent` or `record_terminal`) raises `WriterGenerationBlocked`. The
   refusal chains from the write error, whose `__context__` is the adapter error.
   Nothing else is written. The broker does not invent a state. The row stays
   `provider_call_in_flight` and the owner stays unsealed.
3. **Unchanged paths:**
   - When the terminal write succeeds, the result is the existing
     `outcome_ambiguous` one, which routes to rotation.
   - Any other error from that write, such as `OSError`, `ValueError` or
     `*StoreIncompatible`, propagates as today.
   - Pre-entry refusals still report `provider_call_made: false`.
4. **Human route.** Add a row to `_typed_refusal_handoffs` that maps
   `ProviderEffectGenerationRefused` to `retry_once_before_partition_rotation`.
   The refusal fields are `effect_key`, `transaction_id` and
   `provider_call_made: true`. The `provider_call_made = False` that is hardcoded
   after the typed dispatch becomes per-handler. Every existing handler stays false.
5. **Handoff wording when `provider_call_made` is true:**
   - `next_step_source` says that the provider was entered, that the outcome is
     unknown, and that the generation fence refused the ambiguity record.
   - `rotate_requires` drops the "attested_not_landed by construction" guidance.
     The disposition is the operator's judgement:
     - `observed_landed` if the head is on the remote branch or a PR exists;
     - otherwise `attested_not_landed`, with the usual warning that remote absence
       is not proof.
   - `resume` says to retry once after any rotation ceremony in progress has
     finished or rolled back, then follow the handoff the retry returns.
6. **agent-harness#820** inherits this route without new code. Any
   `WriterGenerationBlocked` raised inside `adapter.execute` reaches the same arm.

## Things the implementer must check (record the answers in the PR)

- **A ceremony that refuses on the dangling intent.** Does it leave the latch
  ACTIVE (rolled back) or DRAINING? If it stays DRAINING, the retry's
  `_block_unsealed_owner` is refused untyped. In that case, either type it with the
  same class (only if that is a small change) or file it as a deferred finding. Do
  not widen this PR to the ceremony.
- **Releasing the service-generation lease.** The inner `finally` releases it
  before the except arm runs. Confirm this does not change which write refuses.

## Tests, at the `publish_human_invoked_from_worktree` level

- **DRAINING.** The adapter raises `WriterGenerationBlocked` after entry, and the
  terminal write is refused. Check that:
  - the next step is `retry_once_before_partition_rotation`;
  - `provider_call_made` is true;
  - the row is still `provider_call_in_flight` and the owner is unsealed;
  - no new evidence lines were written.

  Then restore ACTIVE and retry. The retry returns
  `adjudicate_publication_by_partition_rotation` with this key in
  `blocking_effect_keys`.
- **Revoked shared lease.** The same assertions.
- **The terminal write succeeds.** The behaviour is unchanged (rotation handoff).
- **A non-generation error from the terminal write.** It propagates unchanged.
- **A generic adapter that raises `WriterGenerationBlocked` mid-call.** This is the
  agent-harness#820 shape, and it routes the same way.

## agent-harness#1640 asks in this PR

1. Pin the generation half of `validate_lease` with a test that rewrites the lease
   file's `generation`. Cover both the strict path and the `allow_draining` path.
2. When `strict` is set, a declared `None` lease is refused under DRAINING as well as
   ACTIVE. An undeclared lease (`strict=False`) is unchanged.
3. Add a test pinning that a terminal lands after a ceremony that held the lock
   aborts.
4. Runbook changes:
   - §8a: guidance for a torn line that names the key but not the outcome.
   - §7: a pointer to §8a for the key the successor refuses after a sealed resume.
   - The `retry_once` paragraph: the post-entry variant from contract item 5.

Asks 5 and 6 stay parked: they fail closed and cannot be fixed in this runtime.

## Findings

- **A ceremony that refuses on the dangling intent leaves the latch ACTIVE.** The
  "intents without a terminal" check runs in the ceremony's zero-write adjudication of
  the predecessor snapshot, before it takes `admissions.lock` and before
  `begin_draining`. Nothing is journalled. Pinned by the DRAINING test, which runs a
  real `rotate_blocked_partition` over the refused key and asserts the refusal, an
  `ACTIVE` latch and no ceremony files. So the retry's `_block_unsealed_owner` is not
  refused, and nothing needed typing. A latch that stays `DRAINING` for another reason
  (a ceremony that crashed after journalling `DRAINING`) refuses the retry earlier, at
  the activation barrier ("has no ACTIVE writer generation", `repair_fabpub_authority`),
  with nothing written. That is unchanged, and the handoff's "after any ceremony in
  progress has finished or rolled back" covers it.
- **Releasing the service-generation lease does not change which write refuses.** On
  the routing path the adapter carries the router's shared lease, so
  `_acquire_service_generation_lease` returns `None` and the release is a no-op. On the
  compatibility path the temporary lease is the adapter's own. Either way, the
  ambiguity write validates the evidence store's lease (or the latch alone when
  undeclared), which the release does not touch. The tests show the refusal detail is
  the write's own: "entered DRAINING" for the latch and "lease was revoked" for the
  revoked shared lease.
