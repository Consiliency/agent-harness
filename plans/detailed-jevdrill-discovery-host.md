# Discovery-aware JEV Drill companion (HOST-ADAPTER)

This separately owned companion consumes JEV's plans/phase-plan-v1-HOST.md and
evidence/HOST/adapter-handoff.json from the assigned route-discovery checkout.
Execute serially in this isolated codex/jevdrill-discovery-host worktree; preserve
the dirty windows-port and earlier jevdrill-host inputs. No publication, runtime
installation change, paid model call or bootstrap execution is authorized.

## Ownership and recovery

Owned source paths under phase-loop-runtime/src/phase_loop_runtime:
`jevdrill_adapter.py`, `jevdrill_queue.py`, `runner.py`, `launcher.py`,
`observability.py`, `windows_process.py`, `windows_storage.py`, `file_lock.py`,
`dispatch_lock.py`, `phase_worktree_executor.py`, `prompts.py`,
`agy_provenance.py`, `agy_qualification.py`, `convergence/broker/live.py`,
`convergence/event_log.py`, `convergence/fencing.py`.
Owned tests under phase-loop-runtime/tests: `test_jevdrill*.py`,
`test_phase_loop_launcher.py`, `test_phase_loop_work_unit_observability.py`,
`phase_loop_test_utils.py`, `test_launcher_liveness.py`, `test_windows*.py`,
`fixtures/jevdrill/**`. Also owns `docs/jevdrill-integration.md`, this plan,
`evidence/HOST-ADAPTER/**`, and required handoff/control artifacts.

Recover only these public sources/tests from windows-port, exact HEAD
56dce95a52625a58cd08911f8f623c637bf52e44 plus its inspected dirty platform/HOST
patches. The explicit platform amendment is necessary for native queue ACLs,
Windows process reaping, importability and unchanged launcher regressions. This
does not authorize its manifest, operational state or private overrides.

## Work and frozen authority

1. Copy exact content-bound schemas/fixtures from the upstream handoff, retaining
   v1 compatibility and strict v2 discovery inputs. Implement discover_objective
   through installed transport and successful status gating. Harness planning
   must consume transient discovery instructions and construct at least two
   independent task IDs; Drill never returns tasks.
2. Persist only opaque discovery/task/decision/run identities and trace digest in
   the same bounded private queue database. Add durable objective tombstones
   spanning producers. Serialize binding/preparation/final launch with deletion;
   commit local deletion before transport and retain it after lost stdout.
   Recheck installed inspect-discovery, exact reference, authorized catalog and
   revisions immediately before launch. Preserve independent task report scopes.
3. Preserve trusted callbacks, configured/runtime intersection, explicit model
   overrides, recursion bypass, five-second per-operation spawn-inclusive calls,
   cancellation reaping, report ACK identity/durability, queue bounds and native
   privacy. Task-local guidance injects once, restores the immutable parent
   prompt and reports deactivation. Retain/decline is host policy, never success.
4. Verify genuine production entrypoints, constructors and two-task route-v2
   flow plus deletion crash/race, forged/stale refs and privacy controls. Receipts
   name executed assertion IDs/outcomes and source/schema/fixture digests; no
   fixed count or constant flags substitute for observations.

## Verification

Run uv sync --project phase-loop-runtime --group test with existing versions.
Run from this root:
`uv run --project phase-loop-runtime --group test pytest phase-loop-runtime/tests/test_jevdrill_adapter.py phase-loop-runtime/tests/test_jevdrill_queue.py phase-loop-runtime/tests/test_jevdrill_discovery.py phase-loop-runtime/tests/test_phase_loop_launcher.py phase-loop-runtime/tests/test_phase_loop_work_unit_observability.py`.
Also run owned input/usage/diagnostic/platform regressions, upstream installed
conformance probes and native Linux/Darwin/Windows collection. Real subprocesses
may execute synthetic artifacts; auth/model output remains synthetic.

Historical launcher regression tests require tracked dotfiles revision
23865b61af7f3a405a37bd4984fe80d63b95797a from <home>/code/dotfiles.
Allow reads only of tracked bootstrap, harness configuration/skill source,
shared helpers/scripts required by those tests, and exact companion snapshot.
Materialize verification scratch with runtime under vendor/phase-loop-runtime;
never bootstrap or read private settings. Keep assertion semantics unchanged.
Run closeout audit, diff checks and write metadata-only receipts. Acceptance
requires upstream native reduction of all EC-HOST-1–4 and IF-0-HOST-1. No live
quality, savings, adoption or promotion claim follows from synthetic evidence.
