# Detailed plan: report failed PROOFGATE worktree cleanup

## Task

Resolve agent-harness#858 without expanding the agent-harness#855 CI repair.
The executor must report failed cleanup, preserve the original proof outcome,
and identify retained residue. This standalone defect repair does not accept a
V10 exit criterion, repair garbage collection, or establish HARDEN custody.

## Research summary

The input is main c90b1357d65e76ef778330c3845f4410d38c9710. The unchanged installed
`verification_evidence.py` matches that input at SHA256
1e877edbe355b0587dea9299e7b8d9b05c42646081543239e7382c9563c22b47.
The actual executor, UID/EUID1000, returned `killed` for both a writable0700
control and a generated0500 directory containing a file. Control cleanup
returned0. The negative case returned255/Permission denied, left the file, and
removed its Git registration. This is normal-return failure, distinct from
agent-harness#353 killed-run garbage collection and agent-harness#854 CI export.
Both cases, complete command streams, synthetic fixture history and residue
independently restored at private831d60d6dd197ea88d2c124855c590d6c575a786.
The synthetic commit is diagnostic input, not product chronology or acceptance.

The existing executor vocabulary includes this return at
`phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py:1314`:
`{"status": "execution_failure", "reason": str(exc), "applied_replacements": 0}`.
The aggregate at line1321 classifies non-`killed`/non-`survived` results as blocked.
Keep those status literals and existing successful-result shapes unchanged.
The two frozen manifest anchors in this file are outside the executor body:
`    if count != 1:` and the `validate_verification_artifact_for_plan` signature.
Neither anchor nor any existing frozen test, guard, receipt or manifest may change.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` (modify)

- Restructure only `execute_proofgate_mutation_manifest`'s per-parameter flow so
  the proof result is available before cleanup and cleanup is assessed before
  returning. Use a nested worktree-execution helper for the existing baseline,
  mutation and observable logic; preserve its behavior and bindings.
- Run the existing native cleanup once. Capture its return code and stdout/stderr;
  catch cleanup `OSError` without replacing a previously obtained proof result.
  Do not add permission normalization, a retry, a filesystem sweep, a prune call,
  a recursive-delete fallback, or cleanup of any path beyond this invocation.
- On cleanup success, return the original proof dictionary unchanged. On failure,
  return existing status `execution_failure`, reason `worktree_cleanup_failed`,
  the original applied-replacement count and bindings, the full original result
  under `proof_result`, and a `cleanup` object containing the owned worktree path,
  nullable returncode, nullable exception type, and captured stdout/stderr.
  These are additive dictionary fields, not new status/exit-code vocabulary.
  Preserve baseline diagnostics and original error details in `proof_result`.
  Propagate uncaught `BaseException` normally; cleanup errors must not mask it.
- In the aggregate return, add `cleanup_failures` only when failures exist,
  mapping the affected parameter IDs to their failed-cleanup result dictionaries.
  Existing classifications and block counts must prevent all-killed acceptance.
  Preserve the established aggregate shape exactly when no cleanup fails.

### `phase-loop-runtime/tests/test_proofgate_cleanup.py` (create)

- Use a separate synthetic Git fixture and the actual executor. Prove baseline
  execution, actual mutation and native cleanup for writable and read-only cases.
  Require equal nonzero real/effective UIDs for permission acceptance; no root
  skip/xfail can satisfy the negative case. On workspace hosts, all fixture roots
  belong beneath a fresh owned `/mnt/workspace/worktrees/agent-harness-858-*` path.
- Cover green proof plus cleanup failure, baseline failure plus cleanup failure,
  execution exception plus cleanup failure, aggregate failure propagation, and
  unchanged normal results. Inject only the cleanup-call `OSError` for its specific
  failure-path control; never replace proof execution in the permission cases.
- Assert only the invocation's allocated path is passed to cleanup and no
  permission repair, retry or foreign-path deletion occurs. Preserve original
  outputs, diagnostic records and residue before fixture retirement. Keep native
  cleanup behavior distinct from the test harness's eventual owned-fixture cleanup.

### `CHANGELOG.md` (modify)

Add an Unreleased note for agent-harness#858: failed PROOFGATE cleanup is reported
as execution failure with the original proof outcome and residue diagnostics.
No CLI, schema, dependency or roadmap documentation changes are needed.

### Recording files

Register this detailed plan through native manifest helpers in
`plans/manifest.json`, preserving every pre-existing entry. Native ignored
handoffs/reflections carry author and evidence pointers. Record only actual
eligible review facts in the unmerged row of
`plans/decision-interim-president-ratification-20260904.md` when a PR exists;
write that row before fresh final-head review and preserve landed rows.

## Dependencies and order

1. Preserve the reproduced failure and control. Author this plan only; source
   implementation waits for native four-vendor plan convergence. Fable's current
   credit exhaustion is not permission to replace it or waive the review.
2. Land agent-harness#855 and continue the existing agent-harness#428 priority
   work. Before this implementation, integrate actual current main and reconcile
   any changes to `verification_evidence.py`; refresh plan review for changed
   plan bytes. No future SHA, commit count or topology is prescribed.
3. Add the separate regression tests, record actual RED, then implement only the
   owned runtime/changelog changes. Preserve every failed and successful native
   session, command stream and fixture; do not weaken frozen acceptance tests.
4. Complete narrow native verification and installed-wheel qualification, then
   exact-source and actual-final-head four-vendor reviews. Use current native
   publication ownership and required GitHub CI before merge. Verify/install the
   merged repair for subsequent dogfooding; archive before eligible cleanup.

## Verification

Provision an owned locked test environment through
`uv sync --project phase-loop-runtime --group test --extra visual --python 3.14 --locked`.
Use native `verification_evidence.run_verification` with the owned environment's
lexical Python pin and explicit environment refresh. Render a fresh run ID into
the JUnit and basetemp paths before each run; never reuse a destructive basetemp.

```yaml
automation:
  suite_command:
    - env
    - PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
    - phase-loop-runtime/.venv/bin/python
    - -m
    - pytest
    - -q
    - --junitxml=.phase-loop/diagnostics/proofgate-cleanup-858/RUN_ID/junit.xml
    - --basetemp=/mnt/workspace/worktrees/agent-harness-858-RUN_ID
    - phase-loop-runtime/tests/test_proofgate_cleanup.py
```

Run the existing verification-evidence and PROOFGATE reducer/anchor checks under
their unchanged native guard/chronology inputs, recording executed nodes so a
guard's early return cannot count as coverage. Run docs/manifest/diff checks.
Compare all pre-existing tests and frozen manifest bytes with the planning input.
Build/install a wheel into a fresh owned environment; run copied regression
inputs outside the source checkout with `PYTHONPATH` unset and assert imported
runtime hashes match that wheel. Required CI matrix and Gate A must pass on the
actual published head; narrow checks never substitute for those gates.

## Acceptance criteria

- [ ] The native suite's ordinary-user writable control cleans up successfully
  and returns its unchanged proof result. Falsified by failed cleanup, residual
  files or altered success fields in that control.
- [ ] The native suite's read-only-directory case reaches the real mutation and
  returns `execution_failure` with its original proof outcome and actual cleanup
  diagnostics. Falsified by unqualified `killed`, missing result/diagnostics, or
  a root skip/xfail replacing the permission failure.
- [ ] Native failure/exception and aggregate controls retain original outcomes,
  report cleanup errors, and block all-killed acceptance without modifying any
  foreign path. Falsified by lost evidence, masked exceptions, false aggregate
  success, permission normalization or cleanup outside the allocated path.
- [ ] Source and installed-wheel native checks, unchanged frozen inputs and
  required exact-head CI pass. Falsified by import shadowing, changed frozen
  bytes, unexecuted guard claims, or any failed required gate.
- [ ] Plan/source/final-head reviews and native publication satisfy existing
  four-vendor/interim rules; evidence independently restores before cleanup.
  Falsified by missing review, stale candidate bindings, bypassed ownership or
  removal before verified recovery.
