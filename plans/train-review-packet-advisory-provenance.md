# Approved narrow implementation scope addition

Parent authorized this addition after the frozen full suite on `6eb8f507a2da2744db9fc60b79e2571a0ebffcb5` exposed an omitted existing behavior. No code edits until ordering R3 converges. Include this with R3 and final implementation CR; it does not alter earlier immutable proposals.

Own only `SupervisorProvenanceTest::test_coordinator_review_bundle_records_supervise_provenance` in `phase-loop-runtime/tests/test_model_tier_taxonomy.py`, alongside the already owned packet builder/rendering.

The removed link-only helper carried advisory coordinator supervise-tier/model provenance. Restore that existing advisory information in the complete frozen packet metadata/rendering. Retain the test's `Coordinator supervise tier` text and current heavy model assertion (`claude-opus-5`) through the real new packet builder; do not retain a disconnected legacy helper merely to satisfy its obsolete import.

The field describes configured advisory provenance only. The coordinator remains the ambient session; no launch request consumes this field and no actual coordinator model binding is claimed. Snapshot it before model effects so preparation/finalization byte equality and digest binding still hold. Do not change launcher, provider route, model selection, author filtering or review policy.

Retain the full-suite ImportError as RED evidence. New test shape must also fail on the current builder because advisory provenance is absent, then pass after restoring it. Final CR should identify the narrow test migration and unchanged launch semantics explicitly.
