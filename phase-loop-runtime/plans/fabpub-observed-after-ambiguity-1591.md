# FABPUB: keep a provider outcome observed after the key became ambiguous

Issue: agent-harness#1591 (window (a) of agent-harness#1577). Design ratified by the
maintainer on 2026-10-14; the decisions below are that ratification, not a restatement.
Code is in `convergence/broker/{evidence,verbs,live}.py`, `publishing.py` and the two
rotation scripts.

## Invariant

A provider call that returns a definite outcome is never discarded. If the key's row is
already `outcome_ambiguous_blocked`, the outcome is stored durably outside the evidence
log and bound to that exact ambiguity and to this attempt's owner. The store stays
ambiguous and the epoch blocked; only an operator rotation clears it, and new runtimes
refuse to clear an observed effect as `attested_not_landed`.

## Maintainer decisions

- **D1.** A new append-only side file, `post-ambiguity-observations.jsonl`
  (`PostAmbiguityObservation.v1`): not in memory only, not the evidence log. Owner,
  evidence and admission schemas are unchanged (agent-harness#789).
- **D2.** Enforce: new runtimes refuse `attested_not_landed` for a key with a recorded
  effect observation, or any key while the side file is unreadable: the ceremony
  (zero-write after the adjudication, and in-lock after the drain, before
  `INVENTORY_SEALED`), the preflight, and the re-admission (`PublicationRecoveryRequired`,
  escalate to the maintainer). The handoff names `observed_landed`.
- **D3.** Record the terminal or the observation before releasing the
  service-generation lease.
- **D4.** Record no-effect observations; surface them as supporting evidence only.
- **D5.** Keep `next_step="adjudicate_publication_by_partition_rotation"`; add
  `required_disposition` / `forbidden_disposition` / `attestation_inputs`.
- **D6.** Do not move `_provider_entry_guard`.
- **D7.** Never auto-resolve a key as landed (C-keep).

## Changes

1. `evidence.py`: the observation dataclass (`durable` is in-memory only), the reader
   (`UNREADABLE` on a torn or malformed file, never raises), the appender (fsync, a
   directory fsync on create, skip-if-identical, nothing appended after an unreadable
   file), `ambiguity_digest` (the attestation's digest of the blocked row).
2. `verbs.py`: `_record_terminal_and_seal_owner` returns `(row, observation)`; on an
   ambiguous row with an effect or no-effect outcome it appends the observation in the
   same lock acquisition only while the owner equals this attempt's (nonce included)
   and is unsealed. `_fresh_publish` records inside the lease `try` (D3) and returns
   the observed result; `_replay` answers an ambiguous publish key from the side file;
   `_recovery_authority` refuses (D2). Crash seams `after_provider_return_before_terminal`
   and `after_post_ambiguity_observation` live in a separate tuple, because the train
   runner pins the four existing anchors.
3. `live.py`: `post_ambiguity_effect_refusal`, `generation_store_root`,
   `_refuse_attested_not_landed_over_observations` and its two ceremony call sites. The
   file is not added to `ROTATION_DIGESTED_FILES`; it is listed in
   `ROTATION_STORE_FILES`, which nothing consumes.
4. `publishing.py`: `blocked["observed_after_ambiguity"]` and the observed handoff
   fields; a pre-filled builder argv only for a generation-0 container.
5. Scripts: the preflight's `no_attested_not_landed_over_observed_effect` check; the
   builder prints observations and warns on disagreement.

Tree inventories: `_tree_file_inventory` walks a namespace for bootstrap
classification, but a receipt-owned (`bootstrap_owned`) namespace's file list is never
compared, and canonical stores already hold growing files; historical evidence roots
are legacy, not canonical. No change was needed.

## Board round 1 (agent-harness#1633)

- **D3, as it actually holds.** A rotation that starts during the provider call holds
  `admissions.lock` across its drain. On the post-ambiguity branch only, the
  observation's authorization does not refuse for a `DRAINING` latch alone, so the
  write waits on that lock; the writer's held lease makes the ceremony refuse
  "predecessor writers did not drain" (latch back to `ACTIVE`, retried). A revoked or
  stale lease and a superseded generation root still refuse; the ordinary terminal
  append and owner seal keep the strict `DRAINING` refusal. Only a writer with no held
  lease, or a cleared one, loses the observation.
- **Sealed pre-flip resume.** Both ceremony refusals are skipped when the cutover's own
  journal already holds `INVENTORY_SEALED`; refusing there would strand the partition.
  As on the post-flip arm, `_recovery_authority` refuses the observed effect instead.
- **Runbook §8a:** the procedure for an unreadable side file.

| Crash point | Result |
|---|---|
| Provider returned, before the side-file write | URL lost (residual). |
| Mid-append (torn line) | `UNREADABLE`: ceremony, preflight and recovery refuse `attested_not_landed`. |
| After the write | A retry replays the observation. |
| Rotation started during the call | The write waits on `admissions.lock`; the ceremony does not drain and is retried. |
| Lease cleared by the operator, then the generation rotated | Refused (revoked lease or superseded generation): nothing written, URL lost. |

## Outcomes on an already-ambiguous row

| Provider outcome | Store | Side file | Result |
|---|---|---|---|
| success | stays ambiguous | effect row | `effect_observed_after_ambiguity` + PR URL |
| no-effect | stays ambiguous | no-effect row | `no_effect_observed_after_ambiguity` |
| ambiguous | stays ambiguous | none | `outcome_ambiguous` (as before) |
| raises | stays ambiguous | none | `outcome_ambiguous`, `provider_call_made: true` (as before) |

Residuals (documented): an older writer records nothing; a crash between the provider's
return and the side-file write loses the URL; an older ceremony plus an older re-admitter
can still publish twice.

## Tests

New file `tests/test_fabpub_observed_after_ambiguity_1591.py` (design items 2-11, the
in-lock ceremony refusal, the builder warning, the Q5 lease-release case) and the two
window-(a) tests in `test_fabpub_owner_section_1314_1313_1311.py`, re-pinned and renamed
`*_surfaces_observed_effect` (item 1). Item 10 runs real subprocesses from two
historical `main` trees extracted with `git archive`: a prober without
agent-harness#1313 and a reader without the side file (skipped when the commits are not
in the checkout).

Mutation checks, each reverted after it ran: dropping the side-file write, the owner
binding, the ceremony refusal, the recovery refusal, the observed handoff; writing after
the lease release; marking the result accepted; sealing the owner. Each fails the
tests the design names.

Run serially from `phase-loop-runtime/`:

```
PYTHONPATH=src:tests python -m pytest -q -p no:cacheprovider \
  tests/test_fabpub_*.py tests/test_train_runner.py tests/test_publishing.py \
  tests/test_convergence_broker_verbs.py tests/test_convergence_broker_evidence.py \
  tests/test_broker_evidence_schema_drift_789.py tests/test_seat_reference_inventory.py
```

`tests/data/seat_launch_references.json` gains the new evidence helpers' host-I/O rows.
