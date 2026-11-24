# JEVHOST amendment for the item-3 Windows queue binding

Status: **Agreement in principle. JEV Drill's final agreement is requested
after review of the final bytes.** This amendment records the frozen test edits
in agent-harness#2162 for agent-harness#2161.

## Frozen-file edits

| File | Exact changes | Reason |
| --- | --- | --- |
| `phase-loop-runtime/tests/test_jevdrill_queue.py`, `test_objective_guard_reuses_anchored_transaction_and_bounds_admission` | Read the binding from `q._objective_directory` at line 183 and change two assertions as listed below. | Hook threads borrow the Windows binding from the same queue instance. The admission deadline ends once the guard is acquired so later reports can flush. |
| `phase-loop-runtime/tests/test_jevdrill_companion_workflow.py` | Add `phase-loop-runtime/tests/test_jevdrill_host_gaps.py` to `REQUIRED_PATHS`. Restrict the first-step `Validate jevdrill_ref` loop to `receipt` and `installed`. Add `host-gaps` to the expected job set and exempt it from the `${{ matrix.job_name }}` assertion. For `host-gaps`, use the sync template with literal `3.12` in place of `${{ matrix.harness_python }}`. Include `host-gaps` in the `PYTHONPATH` separator test's job loop. Add `test_host_gaps_run_and_upload_are_independent_of_receipts` to check the matrices, standalone pytest invocation, independence and JUnit upload. | Cover the separate host-gaps job. This preserves every existing assertion about the `receipt` and `installed` jobs, the R3/R6 receipt invocation and the twelve-file list. |

The queue test changes these two old assertions.

- `assert binding is not None and 0 < binding.deadline - time.monotonic() <= 5`
  becomes `assert binding is not None and binding.deadline is None` at line
  186. The guard still publishes a binding. The deadline check now proves that
  the five-second deadline ends on acquisition.
- `assert getattr(q._objective_storage, "directory", None) is None` becomes
  `assert q._objective_directory is None` at line 195. The cleanup check
  reads the shared field where the binding is now published.

Lines 199–205 exercise acquisition under contention. Line 202 expects
`TimeoutError` matching `"lock deadline"` and line 205 asserts
`5 <= clock[0] - 100 < 5.02`. The checks against reopening the bound
directory and for enqueue and record count still run in the same test.

## Collection comparison

Serial `pytest --collect-only -q` on CPython 3.12.14 compared the twelve
files in the companion workflow plus `test_jevdrill_selection.py` and
`test_jevdrill_companion_workflow.py`. The merge base
`5f7e23dc76832cd9b2b27dbcf8131a0298728e01` collected 392 node IDs and the
PR head collected 393. The node-ID diff has one added line.

```diff
+tests/test_jevdrill_companion_workflow.py::test_host_gaps_run_and_upload_are_independent_of_receipts
```

All 392 existing cases retain their node IDs and counts, including the queue
control's single unparametrized case. The storage model and new binding tests
live in `test_jevdrill_host_gaps.py`. A byte comparison against the merge base
confirmed that the [C7] names manifest
`phase-loop-runtime/tests/data/jevdrill_test_names.json` is identical.

## Plan rows that rely on the control

| Source | Rows |
| --- | --- |
| `plans/artifacts/jevhost-v1-contract.md` | §1 R4 names this exact node as a non-installed control. §6 checks the eight control node IDs, the installed split and [C7] name stability. §8 [N-RC] requires the non-installed controls to appear by node ID and pass. |
| `plans/artifacts/jevhost-host-gaps-v1.md` | §6's SL-9 freeze and repin rule covers both edits. The continuity table cites EC-JEVHOST-4 for the companion legs and EC-JEVHOST-5 for the selection and LEARN checks. |
| `plans/phase-plan-v1-jevhost-JEVHOST.md` | SL-4's exact-control and [C7] collection checks and [N-RC] receipt verification cover this node. The acceptance rows are EC-JEVHOST-4 and EC-JEVHOST-5. |

A search of `plans/` for the node and the changed assertions found no HOST
plan row that requires the old remaining-deadline check or the thread-local
cleanup assertion. The rows above depend on the control's identity, selection
or result.
