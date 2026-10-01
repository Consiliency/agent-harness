# RATIFY SL-0 tests-first draft

This is a tests-only candidate dependent on the approved plan in
agent-harness#1203, reviewed at
`c4c5cb992802a5fb36d5816bea25c13fcbdbd8a6`. It does not implement or complete
RATIFY. Runtime sources, the roadmap, manifest and installed services are unchanged.

## Current RED receipt

`content-tdd-receipt.json` binds the four frozen test/adapter blobs at input
`d7f82a31a076d53cd1ff305f0a09031ab0ca0979`. Its retained stdout/stderr report
27 declared missing-capability failures and 17 passing controls, with no errors,
skips or unexpected passes. The adapter checks exact file, node and marker
inventories and compares the frozen blobs against the requested landing ref.
Adding this evidence does not change those blobs.

These failures establish missing capabilities, not executed production semantic
failures. Existing APIs and the receipt/guard fixtures are exercised by the
controls. Future contract bodies remain gated until the corresponding capability
exists. They must run without skips for lane acceptance and final strict proof.

The shared receipt primitive records its legacy GOVLEAN activation environment.
RATIFY activation is explicit in the retained `red_argv`/`red_command` as
`PHASE_LOOP_TDD_EXPECT_RATIFY=1`; the adapter validates RATIFY-specific output.
The shared primitive was not modified.

Reproduce with the test dependencies installed, from the repository root:

```sh
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 phase-loop-runtime/tests/ratify_content_tdd_adapter.py record-red --repo . --landing-ref HEAD
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 phase-loop-runtime/tests/ratify_content_tdd_adapter.py verify --repo . --landing-ref HEAD
```

Recording is an expected-RED operation; it is not the final strict GREEN check.

## Regression evidence

`sl0-verification/verification.json`, `verification.log` and `default-green.xml`
retain the actual scoped runner command, exit status and JUnit inventory:
112 passed, 28 skipped. Of those skips, 27 are this unimplemented RATIFY corpus;
one is module-level collection of `test_phase_loop_plan_manifest.py`, which
requires a dotfiles tree. No skipped case is counted as a pass or acceptance.

The command explicitly used our private Python 3.12 environment. The runner's
interpreter-discovery log also mentions Python 3.14; that does not mean these
tests ran on it. Lint via pyflakes and `git diff --check` passed. The ignored-output
audit exited zero and classified only runner outputs and tool caches.

Gate/ledger/consumer/skill fixtures are synthetic. The hermetic gate fixture
replaces Gemini image preflight; it does not launch a provider or qualify an image,
broker, sandbox or installed deployment. Real consumer functions are exercised
with injected results. Guard-proof controls use actual temporary Git histories,
runner command artifacts and JUnit, without executing commands from ledger rows.

## Retained draft boundaries

`pre-review-75add093/` retains the initial 27-failure/15-control receipt.
`pre-review-785b54af/` retains the subsequent 27-failure/16-control receipt.
The landed-marker removal correction and guard-proof fixture correction each
restarted the content boundary before production or board review. Historical
receipts describe their historical blobs, not the current candidate.

Normal exact-head board review, president disposition, required CI and guarded
landing remain outstanding for SL-0. Production lanes must not start before this
tests-first boundary lands. The one-time manual route ruling for the plan is not
an approval or route authorization for this test candidate.
