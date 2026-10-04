# BAML v1 release-cut checks (agent-harness#1135)

A release cut that ships `phase_loop_runtime` with the BAML v1 worker runs these
checks on the release commit, in addition to the release handoff:

1. **agy requalification.** The worker is `phase_loop_runtime/_baml_worker.py`
   and the client lives in `baml_modular.py`; both are in agy's `source_sha256` pin
   set, so both agy images requalify at the cut (see the CHANGELOG entry for
   agent-harness#1135). Record the `baml-bridge` and `protobuf` versions in the
   release notes.
2. **Full I1 interrupt sweep.** Dispatch `.github/workflows/baml-i1-sweep.yml` on
   the release commit and require a green run on py3.10 and py3.12. Pull requests
   run only the fixed regression subset (`test_i1_boundary_subset`); the full
   sweep (every instruction boundary, ~40 min per Python) runs weekly, on dispatch
   and here.
3. **Pin-bump checklist**, for any `baml-bridge` change: re-run the `baml describe`
   builtin `spawn` audit, the release-notes review and Step 0-style parity against
   `phase-loop-runtime/tests/data/baml_v0_baseline/`.
