---
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q
      phase-loop-runtime/tests/test_runtime_procfs_identity_870.py
      phase-loop-runtime/tests/test_runtime_adapter_output_720.py;
      ruff check phase-loop-runtime/tests/test_runtime_procfs_identity_870.py
      phase-loop-runtime/tests/test_runtime_adapter_output_720.py;
      git diff --check
---

# Detailed plan: correct the procfs liveness oracle after process reaping

## Task

Repair agent-harness#870 through a separately reviewed test-oracle amendment.
Preserve production behavior, every existing assertion and the original RUNTIME
freeze. This does not complete a V10 phase or reconstruct historical evidence.

## Research summary

Input main is `31ca27c62ceaca77cca4d7abb110bc413d181c87`. Main CI35146332035
failed only the installed Gate A case
`test_runtime_adapter_output_720.py::test_timeout_reclaims_real_leader_and_descendant`:
`_assert_quiescent` called `_identity` while reading an already-open procfs file
whose child had exited. The result was `ProcessLookupError(ESRCH)`. The helper
catches only `FileNotFoundError`. A deterministic owned-child reproducer confirms
that exact race on Python3.12; an in-memory two-exception correction returns None
while permission and I/O errors still propagate. The retained original CI stays
failed. Missing JUnit export is separately tracked in agent-harness#854.

The existing test file has reviewed input SHA256
`ba89e599268437b3268e063b0591f5bd18b1c4c0d9554d054c24de3342e6df47` from
agent-harness#863. Its historical freeze and acceptance records remain immutable.
This plan explicitly amends that later regression helper, not the original eight
RUNTIME SL-0 files. No runtime vocabulary, envelope or protocol changes.

## Changes

### `phase-loop-runtime/tests/test_runtime_procfs_identity_870.py` (create)

- Import the actual existing test module and call its `_identity`/`_alive` helpers.
  Add deterministic real-procfs coverage: open an owned live child's stat file,
  kill and reap that same child before reading the open descriptor, and require
  `_identity` to return None and `_alive` to return False. Intercept only the open
  of that exact owned procfs path to schedule the exit; let the kernel produce
  ESRCH. Do not replace the helper, manufacture this primary exception, signal
  arbitrary PIDs, run providers, or add stress loops. Always reap the owned child.
- Add normal live-child and already-reaped-child controls; retain start-time
  identity checks. In separate injected negative controls, permission errors and
  non-disappearance I/O errors must propagate through both helpers. Preserve the
  existing zombie, dead-state and PID-identity semantics.
- Run these tests against the unchanged helper first, retaining actual RED node
  IDs, logs and JUnit. Commit/freeze the new regression tests before the repair.

### `phase-loop-runtime/tests/test_runtime_adapter_output_720.py` (modify)

- Change only `_identity`'s exception clause to
  `except (FileNotFoundError, ProcessLookupError):`. A disappeared process maps
  to None in either procfs race. Do not catch generic OSError, return success for
  permission failures, remove assertions, extend deadlines or add skips/retries.
- Preserve all other bytes. Keep the old file/digest and original failed CI in
  the evidence archive; record the new digest as a new amendment, never overwrite
  the original agent-harness#863 freeze event.

### `plans/manifest.json` (modify)

- Register and update only this detailed plan through native typed lifecycle
  helpers. Record exact review/input/test digests and the explicit helper
  amendment. Other plan rows, historical events and V10 phase states stay intact.

## Documentation impact

No runtime or public API changes. This plan, its native lifecycle and the
agent-harness#870 / agent-harness#766 issue evidence explain the helper amendment.
Keep agent-harness#720 and agent-harness#854 open for their remaining obligations.

## Dependencies and order

1. Obtain a fresh four-vendor native Panel review of this plan and explicit
   helper amendment. Preserve provider sessions, unsuccessful reviews and input
   bindings. The earlier historical-admission refusal is a different task and
   is not resubmitted. Apply existing round caps and provider safeguards.
2. Add and freeze discriminating tests; retain unchanged-helper RED and passing
   controls. Review the tests before modifying the older helper.
3. Apply the single exception-clause repair; run the focused native plan suite
   and the same tests on Python3.10–3.14 with actual interpreter identities.
   Existing assertions, selected node IDs and original eight frozen files must
   remain unchanged. No full expensive suite during diagnosis.
4. Review the exact final candidate through the native Panel, archive/restore
   all evidence, and publish through native ownership checks. Pass required CI
   before ordinary merge. Retain a real post-merge main suite with chronology
   enabled; a later successful run never overwrites the earlier failure.
5. Verify the installed runtime's modules still match merged production bytes
   (no runtime code changed), qualify the merged test helper, then perform
   reviewed lifecycle closeout and verified archival before normal tree cleanup.

## Verification

- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_runtime_procfs_identity_870.py phase-loop-runtime/tests/test_runtime_adapter_output_720.py`
- `git diff --exit-code 31ca27c62ceaca77cca4d7abb110bc413d181c87 -- phase-loop-runtime/src phase-loop-runtime/scripts`
- `git diff --exit-code 2f75797695ed58cbb0f8026b655d5068b23f2e88 -- phase-loop-runtime/tests/_runtime_tdd_guard.py phase-loop-runtime/tests/runtime_content_tdd_adapter.py phase-loop-runtime/tests/test_cli_train_status_45.py phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_convergence_event_log.py phase-loop-runtime/tests/test_convergence_reconcile.py phase-loop-runtime/tests/test_convergence_runtime_imports.py phase-loop-runtime/tests/test_convergence_status.py`
- Run the automation command through native verification; retain its output,
  JUnit and interpreter identity for each supported version.
- Exact amendment: compare the older test against the input Git blob with only
  the stated exception-clause replacement applied; require byte equality.
- Operational evidence: retained actual CI logs/artifacts, exact-head Panel
  results, native verification seals and authenticated private restoration.
  Native lifecycle metadata binds those artifacts; no proxy evidence is used.

## Acceptance criteria

- [ ] The real open/read process-exit race is RED on the unchanged helper and
  GREEN after the single-clause amendment, proven by focused native JUnit/logs.
- [ ] Live/reaped identity controls pass and non-disappearance errors remain
  failures on Python3.10–3.14, proven by the same focused suite and identities.
- [ ] Exact-amendment, production-boundary and original-freeze checks pass;
  existing assertions, deadlines and test selection remain unchanged.
- [ ] Fresh candidate review, required CI, actual merged qualification and
  verified private archival support bounded closeout; original failures remain
  failed and whole-phase acceptance remains unresolved.
