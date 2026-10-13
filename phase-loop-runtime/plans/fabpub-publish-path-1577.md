# FABPUB publish path: provider entry, post-provider failures, restore window

Issues: agent-harness#1577 (primary), agent-harness#1574 ask 1 (SG-F1),
agent-harness#1578 ask 1 (option i plus docs), agent-harness#1576 ask 2 (test
only). Split out: agent-harness#1591 (window (a), promotion during the provider
call). Design ratified by the maintainer on 2026-10-13. All code is in
`BrokerService._fresh_publish` and two new helpers in
`phase-loop-runtime/src/phase_loop_runtime/convergence/broker/verbs.py`, with a
one-line addition in `publishing.py`.

## Contract

The broker returns the state the store holds. It never invents a terminal state,
and it never calls the provider for a key whose record is no longer this attempt's
in-flight record.

## Maintainer decisions

- **D1.** Window (a) is split out to agent-harness#1591. Today's outcome is pinned
  by a test: one provider call, and the key stays ambiguous.
- **D2.** Option (i), a safe restore, plus (iii), documentation. Option (ii) is not
  done: `record_intent` is not moved into the section, and checkpoint states and
  crash seams are unchanged.
- **D3.** `provider_call_made` (true or false) is added to broker-blocked publish
  results and to `BrokerExecutionResult`.

## Changes, in implementation order

1. **Item 3 (agent-harness#1574).** `provider_entered` is set immediately before
   `adapter.execute`. In the `except`, crash injections are still re-raised.
   - Not entered: re-raise and record nothing.
   - Entered: re-read the row. A terminal row (`effect_terminal_observed` or
     `no_effect_terminal_proven`) is returned in the `_replay` shape. An in-flight
     row is recorded ambiguous as before. An already-ambiguous row is returned as
     stored.
   - `advance("TERMINAL_SEALED")` is skipped when the seal failed.
2. **Item 1 (agent-harness#1577).** `_provider_entry_guard` replaces the
   `validate_adapter_start_owner` call site. The function itself is kept as a
   frozen seam. The guard runs after the `after_broker_intent_before_adapter_started`
   crash seam and before `ADAPTER_STARTED`, outside the inner `try`, under one
   `admissions.lock` acquisition. It checks owner equality (nonce included), that
   the owner is unsealed, and that the row is `provider_call_in_flight`.
   - On a mismatch it writes nothing. It returns the stored row with reason
     `outcome_ambiguous` and `provider_call_made=False`.
   - A missing row raises a typed `PermissionError`.
3. **Item 2(i) (agent-harness#1578).** `_restore_unadmitted_owner` runs only when
   `advance("ADMISSION_DURABLE")` raises, and restores the owner bytes the section
   recorded through `prior_owner_holder`. All of these must hold:
   - the durable checkpoint is still `COMMITTED_HEAD_RESOLVED`;
   - in a fresh lock acquisition, `_authorize()` and the admission store's
     generation check pass;
   - the owner is exactly this attempt's;
   - the key has no evidence row.

   Anything else leaves the state as it is. The helper never raises.
4. **D3.** The field is set on every `BrokerService` return path, and
   `publish_from_worktree` copies it into the blocked result.

The docs are `docs/fabpub-pre-admission-ambiguity.md` ("Provider entry and failures
around it") and runbook §8a. Until every writer is upgraded, `attested_not_landed`
needs provider-side evidence. The docs reference agent-harness#1591.

## Tests

In `test_fabpub_ambiguous_handoff_1312.py`:

- `test_post_provider_seal_failure_returns_stored_terminal` (human route) and its
  broker twin `test_post_provider_checkpoint_failure_returns_stored_terminal`;
- `test_lease_refusal_before_provider_records_no_ambiguity`;
- D3 assertions in `test_retry_of_an_ambiguous_key_gets_the_rotation_handoff`.

In `test_fabpub_owner_section_1314_1313_1311.py`:

- `test_promotion_before_provider_entry_refuses_without_call`;
- `test_promotion_during_provider_call_is_documented_residual`;
- `test_admission_durable_failure_restores_owner[absent|sealed]`;
- `test_evidence_generation_loss_leaves_owner_for_rotation`;
- `test_admission_durable_written_then_failing_leaves_owner_for_rotation`;
- `test_recovery_path_epoch_block_restores_owner[False|True]` (item 4).

The window-(a) test, the two "leaves owner" tests and the item-4 test pin current
behaviour, so they pass before the change. The others failed before it.

Mutation checks. Each was reverted after it ran.

| Mutation | Test that fails |
|---|---|
| Drop the in-flight check from the guard | The before-entry promotion test (a provider call is made) |
| Replace the `except` with a constant ambiguous result | Both post-provider tests |
| Drop the `provider_entered` check | The lease test (an ambiguity is recorded) |
| Restore the owner regardless of checkpoint state | The written-then-failing test |
| Drop the restore's in-lock authorization | The generation-loss test |

Run serially from `phase-loop-runtime/`, without xdist:

```
PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider \
  tests/test_fabpub_*.py tests/test_train_runner.py tests/test_publishing.py \
  tests/test_convergence_broker_*.py tests/test_seat_reference_inventory.py
```

`tests/data/seat_launch_references.json` gains the two helpers' host-I/O rows.
