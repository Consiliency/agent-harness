# JEVHOST amendment for the item-3 Windows queue binding

Status: **Agreement in principle. JEV Drill's final agreement is requested
after review of the final bytes.** This amendment records the frozen test edit
in agent-harness#2162 for agent-harness#2161.

## Frozen-file edit

| File | Exact change | Reason |
| --- | --- | --- |
| `phase-loop-runtime/tests/test_jevdrill_queue.py`, `test_objective_guard_reuses_anchored_transaction_and_bounds_admission` | The in-guard binding lookup and post-guard cleanup assertion both read `q._objective_directory` in place of `getattr(q._objective_storage, "directory", None)`. The in-guard Windows assertion still requires a binding and now checks `binding.deadline is None` in place of `0 < binding.deadline - time.monotonic() <= 5`. | The thread-local slot is removed so hook threads can borrow the Windows binding from the same queue instance. Admission still has a five-second deadline, which ends once the guard is acquired so later reports can flush. The old test inspects a removed field and expects the admission deadline to stay attached after acquisition. |

The old Windows deadline assertion had two parts. The binding must still
exist after admission. The remaining-deadline check is replaced by
`binding.deadline is None` because admission has ended. The old post-guard
assertion still checks that the binding was withdrawn, now through the shared
field because the thread-local slot no longer exists. All other assertions
remain, including the prohibition on reopening a bound directory, the enqueue
and record checks, and the controlled-clock check that a busy admission raises
`TimeoutError` after five seconds and before 5.02 seconds.

The control keeps its name, node ID and single unparametrized case. The storage
model and new binding tests live in `test_jevdrill_host_gaps.py`, outside the
twelve frozen files. The [C7] names manifest,
`phase-loop-runtime/tests/data/jevdrill_test_names.json`, is byte-unchanged.

## Plan rows that rely on the control

| Source | Rows |
| --- | --- |
| `plans/artifacts/jevhost-v1-contract.md` | §1 R4 names this exact node as a non-installed control. §6 checks the eight control node IDs, the installed split and [C7] name stability. §8 [N-RC] requires the non-installed controls to appear by node ID and pass. |
| `plans/artifacts/jevhost-host-gaps-v1.md` | §6's twelve-frozen-files rule covers this body edit. Its continuity table cites EC-JEVHOST-4 for the companion legs and EC-JEVHOST-5 for the selection and LEARN checks. |
| `plans/phase-plan-v1-jevhost-JEVHOST.md` | SL-4's exact-control and [C7] collection checks and [N-RC] receipt verification cover this node. The acceptance rows are EC-JEVHOST-4 and EC-JEVHOST-5. |

These rows depend on the control's identity, selection or result. The
post-admission deadline expression appears only in the test body among those
requirements.
