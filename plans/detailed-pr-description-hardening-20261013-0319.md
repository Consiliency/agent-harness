# Detailed plan: complete PR-description lifecycle hardening

## Task

Resolve agent-harness#1558, agent-harness#1559, agent-harness#1560,
agent-harness#1561, and agent-harness#1562. Keep the existing publication
ownership and modes. The repeated edits across four provider sources implement
one instruction contract, not independent features.

## Research summary

The initial PR-writing change is on main. Its shared reference asks agents to
preserve human text, but does not define ownership or a read/compose/re-read
sequence. Detailed publication omits a concrete persistence location. The scratch
gh stub reads a hard-coded body path and records only two arguments; installation
coverage exercises the neutral source rather than the shipped package. CLI help
and earlier phase publication instructions lack the new edit step.

## Changes

- Modify `skills-src/claude/claude-execute-detailed/references/pr-writing.md`:
  an interactive agent-owned PR is the PR this session created and recorded in
  its handoff; use a delimited agent block, read title/body before composing,
  re-read immediately before editing, preserve a human-changed title, and append
  a bounded update to the latest body on concurrent change. Never automatically
  merge; report failed post-ready refresh instead of claiming freshness.
- Modify all four `skills-src/<provider>/<provider>-execute-detailed/SKILL.md`
  publication sections: persist the body in private Git-common-directory state
  `phase-loop-pr-text/<run-id>/body.md`, record its path and digest in the local
  handoff, keep it out of checked-out source, and reuse bytes on retry.
- Modify all four `skills-src/<provider>/<provider>-execute-phase/SKILL.md`
  publication sections: cross-reference the refresh step from mode (b) and early
  drafts; preserve the title unless still equal to this session's last authored
  title; conditionally omit `--title` on edit; distinguish initial-draft and
  already-ready failures.
- Modify `phase-loop-runtime/src/phase_loop_runtime/publication_mode.py` module
  documentation and `phase-loop-runtime/src/phase_loop_runtime/cli.py` help for
  push/create/edit/ready. No new modes, CLI flags, or config fields.
- Strengthen `phase-loop-runtime/tests/test_publication_mode_1392.py`: assert
  per-mode action content, help, full gh argv and actual passed body-file content;
  read-back tests cover preservation of human text/title and concurrent additions,
  lifecycle ordering, failure and none/draft-only/error limits.
- Strengthen `phase-loop-runtime/tests/test_skills_canon_parity.py`: inspect
  four authored provider requirements; install from packaged `skills_bundle`
  (stage each packaged provider's directories under neutral names in temporary
  test input, then use the existing installer), validate
  reference bytes and expanded provider references.
- Update `docs/branch-and-publication-flow.md`, regenerate both generated skill
  distributions, and refresh the launch golden only for intentional instruction
  changes. Update `plans/manifest.json` through typed lifecycle helpers.

## Documentation impact

The shared reference, execution skills, CLI help and publication-flow doc describe
the completed lifecycle. Preserve the existing security-disclosure paragraph added
on main. No broker-update mechanism or Greenfield/spec extraction is introduced.

## Dependencies & order

Write and register this plan, mark executing, edit the authored sources/tests,
regenerate, check the intentional golden delta, verify, and close out.
The companion adapter-redaction plan may share the branch but has separate scope
and acceptance. Local handoffs/reflections/verification are ignored workflow output.
The primary checkout's `.pmcp/logs/gateway.log` is unrelated and must not be staged.

## Verification

From `phase-loop-runtime/`, with its existing interpreter and `PYTHONPATH=src:tests`:

1. `python scripts/regenerate_skills_bundle.py`; `python scripts/sync_skills_bundle.py`.
2. `python -m pytest -q tests/test_publication_mode_1392.py tests/test_skills_canon_parity.py tests/test_skills_bundle_drift.py tests/test_skill_install_body_expansion.py tests/test_phase_loop_build_bundle.py`.
3. Intentional `PHASE_LOOP_REGEN_LAUNCHSPEC_GOLDEN=1` regeneration, compare non-instruction fields with the input baseline, then `python -m pytest -q tests/test_launchspec_golden.py`.
4. `git diff --check` and inspect source/generated ownership and lifecycle instructions.

## Acceptance criteria

- [x] Per-mode action/help tests fail if edit/readiness guidance disappears.
- [x] Four authored variants and package installations retain adapter arguments, explicit persistence, refresh/failure requirements and the shared reference.
- [x] Recorded full gh argv and actual body-file content prove updates precede readiness and none/errors do not mutate.
- [x] Instructions and scratch flows preserve human additions/title and append against the re-read body on change, while reporting post-ready failure honestly.
- [x] Generated bundles have parity and launch changes affect only intended instruction strings.
