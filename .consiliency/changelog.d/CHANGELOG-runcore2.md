<!-- POST070FIX Phase RUNCORE2 — runner/reconcile single-writer correctness batch.
     Assembled into CHANGELOG.md by the RELEASE phase; one entry per fix. -->

- **Roadmap amendments no longer make a completed phase look "genuinely unplanned"
  (agent-harness#85).** When a roadmap is amended in-flight and the edit churns a
  COMPLETED phase's own section, that phase's `phase_sha256` drifts and its stored
  completion is (correctly, by the completion-invalidation invariant) no longer
  trusted, so it reclassifies to `unplanned`. Reconcile now stamps the resulting
  provenance-mismatch warning with a repairable `gold_record_amendment` marker —
  carrying the drifted vs current `phase_sha256` and a repair hint — so `status`
  can distinguish "an amendment changed this completed phase's hashes" (repair by
  restoring the section wording or re-attesting) from a phase that was genuinely
  never planned (which gets no marker). The invalidation itself is unchanged; only
  its observability is fixed. Follow-ups (not in this change): #85's runner
  active-run closeout phase-alias preservation on in-flight amendment, and
  worktree/repo path-portability replay.

- **Standalone closeout prompt no longer drops the active plan's owned files
  (agent-harness#58).** The non-governed closeout prompt built by
  `injection.build_prompt_bundle` hardcoded an empty `plan_owned_files`, so the
  executor saw a blank "Active plan owned files" section, reported empty
  `phase_owned_dirty_paths`, and the runner refused closeout with
  `missing_phase_owned_dirty_paths` even for a plan with explicit lane ownership.
  The prompt now sources the plan's declared owned patterns via
  `parse_plan_ownership`, mirroring the governed `build_lane_prompt_bundle` path.
