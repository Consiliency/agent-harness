# Detailed plan: publication-body sanitization before identity binding

## Task

Resolve agent-harness#1563 by applying the shared text-redaction pipeline to
publication-body input before persistent transaction identity is constructed.
This is separate from PR-writing style, interactive editing, train narrative
generation, and the frozen-body recovery contract.

## Research summary

`credential_redaction.redact_text` already handles credential shapes, known
identity/home paths, explicit known paths, and metadata-forbidden shapes.
`publishing._transaction_payload` hashes and stores the body verbatim.
`publish_from_worktree` then passes its caller's body to the broker.
Fresh/direct/prebuilt preparation and resume need compatible treatment so the
adapter never substitutes different text after an identity has been frozen.

## Changes

- Modify `phase-loop-runtime/src/phase_loop_runtime/publishing.py`: add a thin
  private adapter helper over `credential_redaction.redact_text`, with lexical
  and resolved repository/checkpoint paths as known local paths. Use it before
  `_transaction_payload` binds/stores a fresh body and before the legacy
  non-FABPUB publication request. Fresh FABPUB requests use the transaction's
  already-sanitized body, not a second independently composed string.
- On resume, leave the frozen body unchanged. If it would require redaction,
  refuse before ref mutation/broker execution using the existing
  `publication_transaction_conflicted` refusal and a metadata-only explanation.
  Otherwise pass those exact checkpointed bytes. Do not rewrite historical
  checkpoints or introduce a recovery bypass.
- Modify `phase-loop-runtime/tests/test_publishing.py`: synthetic credentials
  and local paths are absent from prepared payloads and outgoing requests;
  `pr_body_sha256` matches the sanitized body; benign markdown, qualified
  references and directives survive; repeated sanitization is stable; direct,
  prebuilt, human and inactive-FABPUB paths are covered; safe retry bytes remain
  identical and legacy unsafe resume has no mutation or broker call.
- Modify `phase-loop-runtime/src/phase_loop_runtime/credential_redaction.py`:
  include Markdown backticks in the shared known-path start matcher. Only absolute
  lexical paths and resolved paths are supplied by the publication wrapper; relative
  repository names must not erase qualified references or command arguments.
  Cover the shared matcher in `tests/test_credential_redaction_shapes.py` and the
  publication wrapper in `tests/test_publishing.py`. This follows Astra's reproduced
  round-one failures on relative repository names and backtick-quoted paths.
- Update `docs/branch-and-publication-flow.md` with the adapter behavior and
  refusal boundary. Update this plan's `plans/manifest.json` lifecycle.

## Documentation impact

Body identity for newly prepared input is over sanitized text. Existing safe
checkpoint bytes remain unchanged. No wire/schema, authority-field vocabulary,
publication-mode, dependency, or title-ownership change is made.

## Dependencies & order

Use the existing shared redactor, implement and test before publication.
Perform independent advisory review of the completed diff and fix grounded
findings, capped at three review rounds. No merge is authorized.
The companion lifecycle plan has disjoint runtime scope except the shared
publication-flow doc. Preserve prior user work.

## Verification

With the existing interpreter and `PYTHONPATH=src:tests` from `phase-loop-runtime/`:

1. `python -m pytest -q tests/test_publishing.py tests/test_credential_redaction_shapes.py tests/test_fabpub_sealed_head_recovery_1296.py`.
2. Repeat the combined focused suite only after fixes/new changes; record the
   final result through `verification_evidence.run_verification`.
3. `git diff --check`; inspect that no raw body is stored/logged by the new code.
4. Independent review checks the sanitization/identity/retry boundary against
   this plan. Findings without a regressed invariant or acceptance item are suggestions.

## Acceptance criteria

- [x] Fresh direct/prebuilt transactions persist and hash only sanitized body bytes.
- [x] Human, FABPUB and legacy adapter publication forward sanitized text, preserving benign narrative and required metadata.
- [x] Safe resume forwards identical frozen bytes; unsafe historical resume refuses before effects instead of rewriting identity.
- [x] Existing redaction/recovery tests remain green and the new tests observe outgoing requests, checkpoint content and no-effect refusal.
