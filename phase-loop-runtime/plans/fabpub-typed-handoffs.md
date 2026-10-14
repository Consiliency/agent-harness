# FABPUB: typed publication handoffs for broker refusals

Addresses agent-harness#1573 ask 4, agent-harness#1578 ask 5 (SA-F5), agent-harness#1594
ask 1 (SA-F2) and the handoff wording of agent-harness#1574 ask 2.

## Problem

`publish_human_invoked_from_worktree` maps every `PermissionError` that escapes the
broker to `next_step="repair_fabpub_authority"`. Several of those refusals are not
authority problems. An operator who follows that handoff does the wrong thing.

## Contract

- The broker keeps its semantics. Some refusals change type, each to a
  `PermissionError` subclass, so every caller and test that catches
  `PermissionError` (or `WriterGenerationBlocked`) behaves as before. Message texts
  are unchanged.
- The human route chooses the handoff by exception type, never by message text.
  An unrelated `PermissionError` still gets `repair_fabpub_authority`.
- The typed handoffs add `provider_call_made: false` to the result. Each of these
  refusals is raised before the provider is entered. Results that already carry
  `provider_call_made` (agent-harness#1593) are unchanged.
- The governed/train route is out of scope. It does not attach handoffs.

## Refusals on the publish path

| Raised in | Refusal | Type today | Type now | next_step |
|---|---|---|---|---|
| `live._RepositoryRoutingBrokerService._stores_for` (cache hit) | client bound to a retired generation (agent-harness#1552) | `WriterGenerationBlocked` | `RoutingClientGenerationRetired(WriterGenerationBlocked)` | `rebuild_broker_client_and_retry` |
| `verbs._hold_owner_liveness`, `BrokerService._block_unsealed_owner` | owner held by a live writer (agent-harness#1551) | `AdapterStartOwnerLive` | unchanged | `retry_after_inflight_publication` |
| `BrokerService._fresh_publish` | owner contended twice in one publish | `PermissionError` | `AdapterStartOwnerContended` | `retry_after_inflight_publication` |
| `BrokerService._fresh_publish` (both entries) | unsealed owner promoted, blocks the partition | `PermissionError` | `UnsealedOwnerBlocksPartition` (`effect_key`, `transaction_id`) | `adjudicate_publication_by_partition_rotation` |
| `BrokerService._fresh_publish`, `BrokerService.execute` (x2) | `epoch permanently blocked` (another key's ambiguity) | `PermissionError` | `PartitionEpochBlocked` (`blocking_keys`) | rotation when `blocking_keys` is non-empty, else `repair_fabpub_authority` |
| `BrokerService._fresh_publish`, after `ADMISSION_DURABLE` and before provider entry | `record_intent`/guard authorization, guard "no evidence row", refused service-generation lease (agent-harness#1593) | `PermissionError` or `WriterGenerationBlocked` | `ProviderEntryRefused` (`effect_key`, `transaction_id`, cause chained) | `retry_once_before_partition_rotation` |
| `BrokerService._recovery_authority` | already-admitted transaction | `PublicationRecoveryRequired` | unchanged | `resolve_publication_recovery_refusal` (unchanged) |
| `_validated_envelope`, owner section (`admit_next` policy/epoch/precondition, generation), store probes, `_stores_for` latch/receipt, `repository_snapshot` routing, barrier | binding, admission or authority refusals | `PermissionError` family / `LegacyCutoverConflict` | unchanged | `repair_fabpub_authority` (unchanged) |

## Handoff fields

- **`rebuild_broker_client_and_retry`**: `next_step_source` says that a rotation
  moved the ACTIVE generation after the client was built and that nothing was
  written. `resume` says to close the client and build a new one (or restart the
  broker process), then retry. `recovery_procedure` cites runbook §8 step 1.
- **`retry_after_inflight_publication`**: `next_step_source` says that another
  publication's attempt is still running for this partition and that this is
  contention, not ambiguity. `resume` says to retry shortly and not to rotate or
  repair authority.
- **`adjudicate_publication_by_partition_rotation`**: the existing fields, plus
  `blocking_effect_keys` and, for an unsealed owner, `blocking_transaction_id`. The
  attestation disposes the blocking key, which is not necessarily this
  publication's key. The agent-harness#1574 ask 2 wording applies to every
  rotation handoff:
  - `recovery_procedure` cites §§1, 3, 4, 6, 7 and 8a;
  - `authority_root` says that the rotation must use the publish route's
    `FABPUB_AUTHORITY_ROOT`/`--authority-root`;
  - `rotate_requires` names the transaction_id source and repeats the warning
    against a second `attested_not_landed` without new evidence.
- **`retry_once_before_partition_rotation`** (agent-harness#1594 SA-F2): carries
  `effect_key` and `transaction_id`. `resume` says to retry once and then follow
  the handoff the retry returns. The retry promotes the owner, so it is the
  rotation handoff in the normal case. `next_step_source` explains that a direct
  rotation is refused with "intents without a terminal". `attestation_evidence`
  says to keep this result, because the ambiguous row the retry leaves cannot be
  told apart from a crash during the call (agent-harness#1594 ask 5).

## Tests

`tests/test_fabpub_typed_handoffs.py` drives each refusal through
`publish_human_invoked_from_worktree`. The provider adapter is replaced. The stale
client is a pre-rotation client returned by a patched `build_routing_broker_client`.
Each test asserts the `next_step` and the key fields. A control asserts that an
unrelated typed `PermissionError` (`AdmissionStoreIncompatible`) still gets
`repair_fabpub_authority`. The lease case follows up with a retry and asserts the
rotation handoff for its own key.

Mutation check: remove each row of the publishing mapping and run its test. The
PR records the results.

## Not changed

- The `epoch_blocked` branch of `admit_next` ("broker admission denied") stays
  untyped. It shares its message with a policy denial, and the owner is restored.
- `OSError` in the post-admission window keeps the environment handoff.
- agent-harness#1574 ask 3 (an end-to-end "retry after rotation" test).
