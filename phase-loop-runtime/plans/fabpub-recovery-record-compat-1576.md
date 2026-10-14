# FABPUB: the recovery record across runtime versions (agent-harness#1576, ask 1)

## Defect

agent-harness#1550 (agent-harness#1310) added `disposing_generation`,
`readmitting_generation` and `intervening_rotations` to the write-once
`<transaction_id>.recovery.<generation>.json` record, always, even when no rotation
intervened. `PublishTransaction.record_recovery` compares an existing record with the
new payload by dict equality. So when one runtime version writes the record and
crashes before its owner, a retry on the other version in the same generation raises
`PublishTransactionConflict` before any owner write or provider call. The key then
waits for an unrelated rotation, or for someone to remove the record by hand. Both
directions reproduce against the real agent-harness#1296 runtime (pinned input
`a1c3937e`, main before agent-harness#1550).

## Contract

- With no intervening rotation, the disposing generation is the re-admitting one and
  the three fields add nothing. They are omitted, and the record is byte-identical
  to the agent-harness#1296 record (`_atomic_json` sorts keys). This is the only way
  an old runtime's retry can accept a new runtime's record, because old runtimes
  cannot be changed.
- With an intervening rotation the fields stay required. A runtime that predates the
  walk refuses that retry with `PublicationRecoveryRequired` before it records
  anything, so it never compares a record of that shape.
- A reader treats a record carrying all three fields with their no-rotation values
  (empty `intervening_rotations`, both generations equal to `generation`) as the
  same authorization as the record without them. This covers records the
  agent-harness#1550 runtime wrote on `main`. Any other difference still refuses.
- Every refusal from `record_recovery` is a `RecoveryRecordConflict` (a
  `PublishTransactionConflict`) that carries `record_path`. The human handoff names
  it as `conflicting_recovery_record`.

## Change

- `live.attested_not_landed_recovery`: add the three fields only when the walk
  crossed later rotations.
- `publishing.record_recovery`: compare `_recovery_record_core` of both records;
  raise `RecoveryRecordConflict`. An existing record is never rewritten.
- `publishing._human_publication_handoff`: an optional `conflicting_recovery_record`.

## Tests

`tests/test_fabpub_recovery_record_compat_1576.py` runs the historical runtimes in a
subprocess from a `git archive` of their pinned commits. It covers: 1296 record then
current retry; current record then 1296 retry; 1550 record then current retry; an
intervening rotation (the 1296 retry refuses, the current one recovers). Each
recovery makes exactly one provider call and later retries replay. It also checks
that a genuinely different record still conflicts, and that the handoff names the
record. `test_the_newest_disposition_is_the_current_word` now asserts that the fields
are absent.

## Out of scope

- A current runtime's record followed by a retry on the agent-harness#1550 runtime
  still conflicts. That runtime was never released, and it cannot be changed.
- Asks 3 to 5 of agent-harness#1576 (docs and cost).
