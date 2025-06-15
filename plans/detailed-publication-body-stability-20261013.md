# Detailed plan: stabilize fresh publication body bytes

## Task

Repair a reproduced acceptance violation in agent-harness#1563 before the
owner-authorized merge of agent-harness#1581. Keep the shared redactor, audit
policy, wire/schema, and historical checkpoint bytes unchanged.

## Research summary

The cancelled Claude task supplied no verdict but raised repeated-redaction
stability. Local probes reproduced it with synthetic identity/path boundaries
and control-code header text. `_transaction_payload` can store a once-redacted
body which changes on the next application, so the safe-resume equality guard
can refuse otherwise valid prepared work. This contradicts the original
body-handling plan's repeated-sanitization and safe-retry requirements.

## Changes

- Modify `phase-loop-runtime/src/phase_loop_runtime/publishing.py`, the private
  `_redact_publication_body` wrapper and its existing adapter call boundaries:
  snapshot identity once and apply the shared pipeline until equality. Detect
  repeated outputs and bound attempts by initial body length plus one; this is
  a conservative work bound, not a universal convergence theorem. Refuse cycles
  or exhausted work with the existing `PublishTransactionConflict` and fixed
  metadata-only text. Never return partially normalized bytes. Move human
  sanitization before its activation barrier, and translate direct publication
  and frozen-body failures to the existing structured conflict refusal before
  staging/ref/broker effects. Preserve absolute-only paths and historical bodies.
  No fixed pass count, new checkpoint fields or migration. Astra reproduced a
  cycle and unique growth using accepted synthetic identities, so equality-only
  repetition or seen-output detection alone is insufficient.
- Modify `phase-loop-runtime/tests/test_publishing.py`: parameterized regressions
  use deterministic synthetic identities and cascading inputs to prove the
  wrapper is stable, normal/prebuilt preparation stores and hashes stable bytes,
  benign narrative/directives survive, and actual crash/resume forwards exact
  checkpoint bytes. Cycle and unique-growth cases prove structured refusal and
  no transaction identity, index/ref, checkpoint or broker effects. Preserve
  unsafe historical no-effect refusal controls.
- Update `docs/branch-and-publication-flow.md` to state that fresh body text is
  stabilized before identity binding. Register and complete this plan through
  typed `plans/manifest.json` helpers. Ignored evidence/handoffs/reflections are
  allowed; prior committed companion-plan work and unrelated primary changes
  remain intact.

## Documentation impact

The publication-flow doc names stabilization; no CLI/config or protocol change.
Public PR/commit language stays neutral and avoids sensitive evidence.

## Dependencies & order

Write/register the plan, add regressions and reproduce the failure, then repair
the wrapper. Verify, publish through the supported adapter, and obtain Sol's
final delta review (round three of the existing capped review loop). Carry prior
Astra agreement only for unchanged scope. Merge remains authorized but waits
for final review agreement and full CI on the new head. No bypass or checkpoint
rewriting is permitted.

## Verification

Use the existing interpreter with worktree `PYTHONPATH=src:tests`:

1. Run the new parameterized publishing regressions before the repair and record
   their failures; run `tests/test_publishing.py` after repair.
2. Run the combined suite for publishing, shared redaction shapes, sealed-head
   recovery, publication mode, canonical parity, generated drift/install/build,
   launch golden, and the historical guard; record runner verification evidence.
3. Pinned `uvx ruff@0.15.5 check .`, `git diff --check`, and wheel construction.
4. Independent final delta review checks stabilization/termination and frozen
   retry bytes. Require full hosted CI before merge.

## Acceptance criteria

- [x] Cascading synthetic inputs and normal bodies return stable redacted text with benign narrative retained.
- [x] Direct and prebuilt preparation hash/store the stable bytes; crash/resume sends those exact bytes.
- [x] Non-stabilizing input and unsafe historical checkpoints refuse before effects; frozen bytes remain unchanged and no schema/audit-policy changes occur.
- [x] Combined verification, lint, wheel construction and final delta review support the repair.
