---
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q
      phase-loop-runtime/tests/test_harden_json_depth_825.py
      phase-loop-runtime/tests/test_harden_evidence_verifier.py;
      python3 phase-loop-runtime/scripts/verify_harden_evidence.py --self-test;
      ruff check phase-loop-runtime/scripts/verify_harden_evidence.py
      phase-loop-runtime/tests/test_harden_json_depth_825.py;
      git diff --check
---

# Detailed plan: bound HARDEN verifier JSON nesting across Python versions

## Task

Repair agent-harness#825 on current main without changing frozen HARDEN tests,
historical admission, review policy or phase acceptance. Require an explicit
maximum of 512 nested JSON containers before the interpreter's decoder runs.
The limit counts arrays and objects together, including the outermost container.

## Research summary

Input main is `83f41b9a1e94b411f81af9ea5af1bf2da06b0ea9`. The verifier source
SHA256 is `6e9b1ad4858dda5bfea6516508c2c6ae243d5846a6052d9efe7f22314e8b505a`.
`strict_json_loads` bounds bytes and numeric literals but relies on native
recursion limits for container depth. `parse_canonical_json` then re-encodes the
result. The existing self-test requires rejection of a canonical 2,048-level
array. Fresh retained `baseline-r1/summary.json` shows that exact source accepts
2,048-level arrays and objects on Python 3.12.12, 3.13.12 and 3.14.7; Python
3.10.12 and 3.11.14 reject them. All five accept depth 64, 512 and 513.

The unchanged full self-test was also run on all five versions. Retained
`baseline-selftest-matrix-r1.json` records success on 3.10/3.11 and the exact
`canonical-json-deep-nesting was accepted` assertion on 3.12/3.13/3.14.
Earlier setup refusals are retained separately and are not parser RED evidence.

The 512 ceiling is an explicit compatibility tightening: formerly accepted
documents deeper than 512 will be rejected. It preserves the measured depth-512
positive controls while removing dependence on the interpreter's recursion
threshold. Existing byte, number, duplicate-key and canonical-encoding rules
continue to apply independently. No minimum acceptance depth is promised after
an external caller changes the interpreter recursion limit.

## Changes

### `phase-loop-runtime/tests/test_harden_json_depth_825.py` (create)

- Add a separate regression module before production edits. Load the real
  verifier script by its exact repository path and retain its hash. Primary
  acceptance cases do not replace the parser, decoder, depth check, exception
  type or recursion limit; the separate decoder sentinel is specified below.
- Through both `strict_json_loads` and `parse_canonical_json`, require arrays,
  objects and alternating containers at depths 64 and 512 to succeed and
  depths 513, 1,024 and 2,048 to raise `EvidenceError`. Construct canonical
  fixtures, including alternating containers, without recursive test builders.
  Before the fix, depth 513 discriminates on all five versions; rejection at
  1,024/2,048 is already green on 3.10/3.11 and must not be reported as new RED.
- Accept a root array containing two sibling chains of 511 arrays: its maximum
  depth is 512 despite 1,023 total containers. Also accept 600 empty sibling
  containers. Exercise both public entrypoints to distinguish nesting from
  total opener count and prove depth decreases when a container closes.
- In a separate decoder-entry control, replace only the loaded verifier
  module's `json` binding with a proxy that counts calls and delegates to the
  real `json.loads`, forwarding all other attributes unchanged. Do not patch
  process-wide stdlib bindings or manufacture exceptions. Depth 512 must enter
  the decoder; after the fix depths 513/1,024/2,048 must make zero decoder calls.
  Retain pre-fix evidence that depth 513 reaches it. Keep primary parser cases
  unmodified and restore the module binding after each control.
- Test large strings containing thousands of brackets, escaped quotation marks,
  odd/even backslash runs and Unicode escapes. String content must not count as
  containers. Include empty containers and a deep container after a quoted
  bracket prefix, so a quote/escape bug cannot hide the over-limit suffix.
  Explicitly include raw `\u0022`, `\u005c` and `\u005b` spellings. Scan raw
  source characters without decoding Unicode escapes. These valid spellings
  pass `strict_json_loads` but fail `parse_canonical_json` when noncanonical;
  their canonical re-encodings must pass both entrypoints. Do not weaken
  canonical encoding rules to accept noncanonical fixtures.
- Preserve malformed-input rejection for unbalanced/mismatched delimiters,
  unterminated strings and invalid UTF-8. Retain duplicate-key, non-finite number,
  byte-size and noncanonical-whitespace controls through the public parser.
  Do not assert a new message for unrelated existing rejection cases.
- Run unchanged production first. Retain actual RED node IDs, raw output and
  JUnit, together with passing controls. Freeze and review the additive tests
  before production edits; do not modify any existing frozen test/support file.

### `phase-loop-runtime/scripts/verify_harden_evidence.py` (modify)

- Add `MAX_JSON_NESTING = 512` beside the existing JSON limits.
- In `strict_json_loads`, scan the decoded UTF-8 string before `json.loads`.
  Track container depth, string state and backslash escaping in one pass.
  Count `[`/`{` and `]`/`}` only outside strings. Raise `EvidenceError` through
  the existing `fail` helper as soon as the depth exceeds 512. Keep lexical
  validation, duplicate-key handling, numeric rules and canonical validation
  with the existing decoder/encoder; do not add a second JSON parser.
  The existing byte cap bounds the scan; sibling containers reduce the current
  depth, and escaped characters inside strings do not alter lexical state.
- Preserve all verifier authority, historical evidence, CI, isolation, reuse,
  schema and self-test behavior outside this bounded pre-decoding check. Do
  not change recursion limits, catch unrelated exceptions or edit the producer.

### Planning and review records (modify)

- Maintain this detailed plan and only its native `plans/manifest.json` row.
- Append the eventual landing's evidence row to
  `plans/decision-interim-president-ratification-20260904.md` and cite that
  interim authority in the PR body. Preserve existing rows and policy text;
  record actual review and landing identities when known, never future SHAs.

## Documentation impact

`no_doc_delta`: no CLI option, schema field or public signature changes. This
plan and the agent-harness#825 record explicitly document the tightened limit.
The append-only interim review ledger is part of the expected tracked diff.
No general HARDEN security or completion claim is made.

## Dependencies & order

Use this clean owned worktree and the installed native typed plan registration.
Obtain four usable exact-plan Panel approvals under the current interim policy.
Then retain and review the additive RED tests, implement only the parser bound,
and run native verification with explicit interpreter identity. Require fresh
source and final-candidate reviews and required CI before native publication
and ordinary guarded merge. Preserve successful and unsuccessful sessions.

The protected pending HARDEN source and historical-plan trees remain byte-for-byte
unchanged. Their prior review votes do not apply here. This is a separate parser
defect repair, not a retry or reformulation of the declined historical-admission
review. It grants no authority to execute SL-7/v2, issue checkpoints, seal evidence,
close agent-harness#742 or agent-harness#770, or mark a V10 phase accepted.

## Verification

- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_harden_json_depth_825.py`
- `python3 phase-loop-runtime/scripts/verify_harden_evidence.py --self-test`
- `ruff check phase-loop-runtime/scripts/verify_harden_evidence.py phase-loop-runtime/tests/test_harden_json_depth_825.py`
- `git diff --exit-code 83f41b9a1e94b411f81af9ea5af1bf2da06b0ea9 -- phase-loop-runtime/tests ':!phase-loop-runtime/tests/test_harden_json_depth_825.py' phase-loop-runtime/scripts/build_harden_evidence.py`
- `git diff --check`

Run the regression command and unchanged self-test under Python 3.10, 3.11,
3.12, 3.13 and 3.14, preserving each exact interpreter/version and raw/JUnit
results. Use installed interpreters and owned environments with locked test
dependencies, including dependencies imported by repository `conftest.py`.
Target the runtime package for its declared Python floor; keep native artifacts
inside that target. Do not weaken interpreter guards or disable existing test
configuration. Run the frontmatter suite through native `run_verification` and
retain its validated artifact; required CI supplies broader regression coverage.
Do not rerun unrelated expensive historical suites as a substitute for this matrix.

After merge, export the actual merged verifier with its required sibling layout
to an owned operational location. Verify every exported byte against merged Git
objects and repeat the parser matrix and self-test there. The standalone verifier
is not supplied by the runtime wheel: an unchanged wheel installation alone is
not adoption of this fix. Record the operational verifier path and use it for
subsequent eligible checks. The existing installed runtime may remain only after
its module inventory is verified equal to merged runtime source. This export is
operational code, not an independently administered N1 issuer.

## Acceptance criteria

- [ ] All five interpreter versions enforce the same 512-container ceiling for
  arrays, objects and mixed nesting, with unmodified positive controls and RED
  evidence proving that the tests discriminate against the input implementation.
- [ ] Quoted and escaped data remains valid, malformed/canonical/duplicate/numeric
  rejection rules remain enforced, and over-limit input is stopped before the
  decoder, proven by the new controls and unchanged full self-test.
- [ ] Existing frozen tests, producer and protected pending work remain exact;
  only the planned parser source and additive regression test change, verified
  by Git diffs, protected hashes and fresh exact-candidate review. The complete
  tracked diff also includes this plan, its native manifest row and the
  append-only interim review ledger entry, all included in candidate review.
- [ ] Native verification, required CI and four-seat reviews pass; the merged
  standalone verifier is exported, hash-verified and exercised from its adopted
  operational location before evidence-preserving cleanup. No phase acceptance
  or historical evidence is inferred from this bounded repair.
