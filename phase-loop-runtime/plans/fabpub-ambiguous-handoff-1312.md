# FABPUB: rotation handoff for an `outcome_ambiguous_blocked` publication (agent-harness#1312)

Follow-up from the board ruling on agent-harness#1298 (fixed agent-harness#1296).

## Problem

A human publication (`publish_human_invoked_from_worktree`) whose key holds an
`outcome_ambiguous_blocked` evidence record is permanently blocked in the active
partition generation until an operator rotation adjudicates the effect. Retrying it
before any rotation returns the generic `repair_publication_precheck_and_retry`
handoff, which tells the operator to fix a precheck and retry: no retry can succeed.

## Trace: how the state reaches the result dict

1. `BrokerService.execute` (convergence/broker/verbs.py) finds a non-in-flight record
   for the key and returns `_replay(...)`:
   `BrokerExecutionResult(accepted=False, evidence=BrokerTerminalEvidence(key, "outcome_ambiguous_blocked", ref), reason="")`.
2. The first attempt yields the same shape: `_fresh_publish` returns `reason=""` when
   the adapter returns an ambiguous terminal, and `reason="outcome_ambiguous"` (terminal
   state still `outcome_ambiguous_blocked`) when the adapter raises.
3. `publish_from_worktree` maps a non-accepted execution to
   `_blocked(execution.reason or execution.evidence.terminal_state, evidence_reference)`.
   The typed terminal state is lost whenever `reason` is non-empty.
4. `publish_human_invoked_from_worktree` attaches
   `repair_publication_precheck_and_retry` to every `publication_blocked` result
   without a handoff.

Replay and first attempt are indistinguishable at the result-dict level without
changing verbs.py (Lane A's file), and they need the same operator action.

## Change

- `publish_from_worktree`: the broker-blocked result also carries
  `terminal_state = execution.evidence.terminal_state` (additive key; `reason` and
  `detail` unchanged).
- `publish_human_invoked_from_worktree`: when the blocked result's `terminal_state`
  equals `TerminalOutcomeState.OUTCOME_AMBIGUOUS_BLOCKED.value`, the handoff is
  `adjudicate_publication_by_partition_rotation`; otherwise it stays generic. The
  match is on the enum value, never on message text.
- `_human_publication_handoff`: a new, self-contained
  `adjudicate_publication_by_partition_rotation` branch with `recovery_procedure`
  (runbook sections 3, 4, 7 and 8a), `rotate_command`, `rotate_requires` (either
  disposition: `observed_landed` with the observed head, or `attested_not_landed`
  with the owner's `transaction_id`), `after_rotation` and a `resume` that says a
  retry before the rotation replays the same block. The rotate argv comes from a new
  module helper. The existing `resolve_publication_recovery_refusal` branch is left
  untouched, line for line: Lane B edits its text, so moving its lines into a shared
  helper would turn a trivial rebase into a conflict. A few duplicated argv lines are
  the cheaper cost.

## Other blocked states (decision)

- `rejected_before_start` / `no_effect_terminal_proven` replays: no effect, the
  partition is not blocked, and a rotation does not carry such keys (it refuses a
  predecessor that is not `epoch_blocked`). Generic handoff stays.
- `provider_call_in_flight`: `execute` never replays it; it reaches `_fresh_publish`,
  whose unsealed-owner resolution either records the ambiguity (next retry: covered
  here) or raises `PermissionError`.
- `epoch_blocked` with a *different* key blocking the partition, and the
  unsealed-owner refusal: both surface as untyped `PermissionError` through the
  exception branch (`repair_fabpub_authority`). A rotation is also the remedy there,
  but telling them apart needs either message matching or a typed exception in
  verbs.py (Lane A). Out of scope; reported as a follow-up.

## Vocabulary

No enumerated `next_step` vocabulary exists: no schema, contract test, train runner or
review-packet code lists the values (searched `next_step`, `HumanPublicationHandoff`
and the existing step names across the repository). The values appear only in
publishing.py, tests, CHANGELOG and docs/fabpub-pre-admission-ambiguity.md.

## Docs

- docs/fabpub-partition-rotation-runbook.md 8a: the human route reports
  `adjudicate_publication_by_partition_rotation` with the rotate command before any
  rotation.
- docs/fabpub-pre-admission-ambiguity.md (the human-route sentence beside
  `resolve_publication_recovery_refusal`): the pre-rotation counterpart.
- CHANGELOG Unreleased entry.

## Tests (phase-loop-runtime/tests/test_fabpub_ambiguous_handoff_1312.py)

- Human route end to end: zero-history bootstrap and real barrier/router (pattern of
  `test_conflicted_human_publication_returns_typed_handoff`), the live GitHub adapter
  replaced by `_CountingAdapter(terminal_state="outcome_ambiguous_blocked")` imported
  from test_fabpub_shared_epoch. First call blocks; the retry replays with no second
  provider call and reports `adjudicate_publication_by_partition_rotation`, the rotate
  argv naming the worktree, both dispositions in `rotate_requires`, and the
  checkpoint root. Generation 0 evidence holds the ambiguous row.
- The adapter-exception variant (`reason == "outcome_ambiguous"`) gets the same handoff.
- A `rejected_before_start` blocked result keeps `repair_publication_precheck_and_retry`.
- Each new check is shown to fail when its code is removed.

Run from phase-loop-runtime/: test_publishing.py, every test_fabpub_* file and the new file.
