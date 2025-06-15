# Detailed plan: make redaction sources compatible with publication auditing

## Task

Repair the publication blocker encountered while completing agent-harness#1558,
agent-harness#1559, agent-harness#1560, agent-harness#1561, agent-harness#1562,
and agent-harness#1563. The owner chose a separate bounded repair, independent
review, and a retry through the supported publication adapter.

## Research summary

The pinned built-in detectors used by `publishing._source_path_evidence` reject
an existing explanatory URL comment and synthetic fixtures in two tracked Python
files. Metadata-only scans found the same findings in the input baseline and
staged source. The actual URL regex is not flagged. Source scanning and publication
policy stay unchanged; this repair makes comments and fixture construction clear
to that existing audit. The open template-file issue agent-harness#899 is a
different case and is outside this plan.

## Changes

- Modify `phase-loop-runtime/src/phase_loop_runtime/credential_redaction.py`:
  reword the URL-userinfo comment as prose without a credential-shaped URL.
  Do not change the regex or any executable redaction behavior.
- Modify `phase-loop-runtime/tests/test_credential_redaction_shapes.py`:
  construct the letters-only fixture with `string.ascii_lowercase[:24]`, the
  user/password URL template with `urllib.parse.urlunsplit`, and the two flagged
  fixed cases from the existing `_SECRET[:4]` prefix and an explicitly named
  quoting placeholder. Preserve the exact
  runtime `VALUES`, `SHAPES`, and `_FIXED_CASES`; leave other fixtures unchanged.
- Modify `phase-loop-runtime/tests/test_publishing.py`: add a two-case regression
  that stages each actual redaction source file in a scratch tracked module and
  invokes the real governed staged audit. Require accepted source evidence to
  bind to the staged blob and existing scanner-policy identifier. Run the existing
  secret-content, new-source, artifact, suppression, and scanner-failure negatives.
- Register and complete this plan in `plans/manifest.json` through typed helpers.
  Ignored handoffs, reflections, baseline fingerprints and verification artifacts
  are workflow output. Preserve all earlier plan-owned staged work.

The audit policy identifier remains `tracked-python-detect-secrets-1.5.0-v1`.
No detector exclusions, allowlists, bypass arguments, new source classification,
checkpoint edits, vocabulary changes, or scanner-policy changes are permitted.

## Documentation impact

No public behavior or policy changes. The corrected source comment and this plan
document the repair; existing publication documentation remains accurate.

## Dependencies & order

Write and register the plan, fingerprint the current runtime fixtures and regex
patterns in ignored local evidence, then make the three-file repair. Verify exact
runtime equivalence, existing audit negatives, and the prior hardening suites.
Obtain Astra delta review before retrying publication. Opus's earlier provider
rate limit is recorded as unavailable, not a review verdict. Retry with all three
plans and the exact persisted PR body through `publish_human_invoked_from_worktree`.
Keep the PR draft and do not merge.

## Verification

Use the existing interpreter with `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests`.

1. Compare a SHA-256 of normalized `VALUES`, `SHAPES`, `_FIXED_CASES`, and redaction
   regex patterns with the pre-edit fingerprint; record the equality result.
2. Run `python -m pytest -q` from `phase-loop-runtime/` for
   `tests/test_publishing.py`, `tests/test_credential_redaction_shapes.py`,
   `tests/test_fabpub_sealed_head_recovery_1296.py`,
   `tests/test_publication_mode_1392.py`, `tests/test_skills_canon_parity.py`,
   `tests/test_skills_bundle_drift.py`, `tests/test_skill_install_body_expansion.py`,
   `tests/test_phase_loop_build_bundle.py`, and `tests/test_launchspec_golden.py`.
   Record the final suite through `verification_evidence.run_verification`.
3. Regenerate and sync skills; `git diff --check`; repeat the wheel build because
   source inputs changed. Independent review checks this plan and the final delta.
4. Invoke the supported publication adapter with the plan-owned paths and final
   verification artifact. Record its result without bypassing a refusal.

## Acceptance criteria

- [x] Fixture values, URL template bytes, fixed cases, and regex patterns match the pre-edit fingerprint.
- [x] Actual redaction source files pass the governed staged audit with blob-bound evidence; existing refusal controls still pass.
- [x] The combined hardening/redaction/recovery suite and wheel build pass, with independent delta review recorded.
- [x] No audit-policy, detector, privilege, or publication-route changes are introduced by this repair; source scanner refusals remain fail closed.

Publication is a closeout action after implementation acceptance. Its actual
result is recorded in the ignored execution handoff; a refusal preserves the
work and is never reported as a published PR.
