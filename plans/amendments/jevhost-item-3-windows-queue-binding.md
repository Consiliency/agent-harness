# JEVHOST amendment for the item-3 Windows queue binding

Status: **Proposal for review. JEV Drill's agreement is requested.**
This amendment records the frozen test edit in agent-harness#2162 for
agent-harness#2161. The JEVHOST contract and host-gaps artifact remain as written
while the request is pending.

## Frozen-file edit

| File | Exact change | Reason |
| --- | --- | --- |
| `phase-loop-runtime/tests/test_jevdrill_queue.py`, `test_objective_guard_reuses_anchored_transaction_and_bounds_admission` | The in-guard binding lookup and post-guard cleanup assertion both read `q._objective_directory` in place of `getattr(q._objective_storage, "directory", None)`. The in-guard Windows assertion still requires a binding and now checks `binding.deadline is None` in place of `0 < binding.deadline - time.monotonic() <= 5`. | The thread-local slot is removed so hook threads can borrow the Windows binding from the same queue instance. Admission still has a five-second deadline, which ends once the guard is acquired so later reports can flush. The old test inspects a removed field and expects the admission deadline to stay attached after acquisition. |

No frozen test name, parameter ID, or collection entry changes. The existing
admission-contention checks remain in the frozen test. The storage model and new
binding tests live in `test_jevdrill_host_gaps.py`, outside the twelve frozen
files. The [C7] names manifest, `tests/data/jevdrill_test_names.json`, is unchanged.
