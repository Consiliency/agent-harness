# Detailed plan: publication confirmation repair (agent-harness#789)

## Task

Land the confirmation contract and its bounded-read implementation together in
the single fix PR allowed by the operator's generation-2 publication hold:
https://github.com/Consiliency/agent-harness/issues/789#issuecomment-5668140934

This is a revision of the existing contract plan, not a competing roadmap.
Input main is `bb7627fd5126b6ebf9b4df0b3934a4c2d921fe9b`. The earlier contract
work at `e6d6a72c848758f6d77513792e8260a04ed2f35e` and adapter experiment at
`6e2b2a2901aaa225b39d986deab5927fbbbce909` are retained inputs, not transferable
approvals. This revision replaces the earlier requirement to publish and merge
a contract-only PR before planning adapter integration. Review this combined
plan, then review the exact combined implementation before publishing its PR.

## Research summary

Current main successfully pushes the exact head and recognizes an existing PR,
but makes only one confirmation observation before permanently blocking. Two
incidents exposed that fragile confirmation policy. Neither original PR-list
payload survives, so empty versus stale read and any server-side visibility
cause remain unproven. This repair addresses premature terminalization of two
well-defined, nonterminal observations; it does not claim historical causality
or a GitHub visibility SLA. Do not remove fail-closed terminal permanence.

Agent-harness#834 already distinguishes `pr-list-empty` from
`pr-head-unconfirmed` and provides typed evidence-store refusals. The old adapter
experiment loses the former on exhaustion and must not be transplanted unchanged.
Agent-harness#828 is merged; agent-harness#842 and agent-harness#843 are separate
follow-ups, outside this plan. No authority crypto, fence, schema or lease change.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/convergence/provider_contracts.py` (modify)

For `_SUPPORTED_GITHUB_PUBLISH`, carry the earlier reviewed values of only
`guaranteed_processing_horizon` and `stabilization_drain_interval`. They specify
defensive confirmation observations without a visibility SLA, at most three
rounds and added sleeps of one then two seconds, with no mutation retry or
terminal recovery. Update adjacent comments to describe the implementation in
this same candidate, not a future separate PR. All other dataclass fields,
provider pairs and executable contract behavior remain unchanged.

The exact two proposed strings and the prior complete documentation amendment
are included from that input commit in the review packet. Inspection of the full
`test_convergence_provider_contracts.py` on input main confirms that it does not
pin either old string; leave that file and every existing assertion unchanged.

Frozen `TerminalOutcomeState` vocabulary (lines 25-33 of the input file):
`rejected_before_start`, `provider_call_in_flight`, `effect_terminal_observed`,
`no_effect_terminal_proven`, `outcome_ambiguous_blocked`. No new state, schema,
transition, classification or enum is introduced.

### `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/credsep.py` (modify)

Change only post-create confirmation in `GitHubBrokerAdapter.execute`, plus
standard-library imports needed for sleep and diagnostic logging. Leave push,
PR-create, request preflight, generation revalidation and terminal storage intact.

1. Attempt at most one push and one PR create, as today. After they reach the
   existing confirmation path, allow at most three observation rounds in this
   uninterrupted adapter invocation. No terminal result is written between rounds.
2. Every round first rereads the exact remote branch and requires the requested
   head. Remote read failure, absence or mismatch terminates immediately with
   its existing reason. Read the same PR-list fields as today.
3. Require valid JSON with a list root. Blank output is not a valid empty list.
   More than one PR is immediately `pr-list-ambiguous`; malformed shapes are
   immediately `pr-read-unparsable`. No sleep follows an invalid/error read.
4. An empty JSON list is eligible for another observation. For a nonempty list,
   require one object; a mismatching head is eligible only if it is a string of
   full lowercase hexadecimal digits (40 or 64, matching request head length).
   Missing/malformed mismatching heads fail immediately as `pr-read-unparsable`.
   Preserve the existing exact-head successful path and its identity predicates.
5. Even for a well-formed differing head, validate base, repository owner,
   `isCrossRepository is False`, origin URL predicate, and equality with the
   recognized existing-PR diagnostic URL. Any identity mismatch terminates
   immediately with its existing specific reason. No weakening of these checks.
6. Only after a valid empty or otherwise identity-validated differing-head
   observation, and only when another round remains, sleep one then two seconds.
   Success requires exact remote and PR head equality and all identity checks.
   On exhaustion, preserve `pr-list-empty` or `pr-head-unconfirmed` according to
   the final observation, including mixed sequences. Never sleep after round 3.
7. Emit a bounded, metadata-only diagnostic for each eligible observation:
   round index, classification (`pr-list-empty` / `pr-head-unconfirmed`), and
   whether another round will occur. Use a module logger at WARNING so the
   default Python stderr handler receives it without an INFO configuration.
   Prove this with a subprocess under the normal publisher logging setup, using
   fake provider reads and captured stderr, not just caplog. Do not log raw payloads, credentials,
   URLs, repository names, paths, headers or account identities. These logs are
   diagnostics, not new sealed evidence or substitutes for terminal records.

### `phase-loop-runtime/tests/test_pr_readback_789.py` (create)

Add sequence-driven fake-provider tests before implementation. The existing
`_FakeRun` is stateless: use its request/response fixtures plus a new per-call
sequence runner in this test file, with full hexadecimal heads and a captured
sleep function. Assert exact command order, remote/PR read counts, sleeps, one push
and one PR create, and final terminal classification. Cover success on rounds
1/2/3; empty and stale exhaustion; both mixed final outcomes; malformed/blank
payloads; missing/malformed heads; wrong base/owner/fork/URL/diagnostic URL on a
stale head; errors or remote mismatch after a wait; and 40/64-character heads.
For every immediate-failure case assert its exact reason, zero further sleeps,
one push/create, and exact remote/PR counts up to the failing round. Append a
success response that must remain unconsumed, so reason-only tests cannot mask
an invalid observation being retried. Base failure is `pr-base-unconfirmed`,
owner/fork failure `pr-head-repository-unconfirmed`, origin URL failure
`pr-url-unconfirmed`, and recognized diagnostic URL inequality
`pr-url-readback-mismatch`. Validate metadata fields with caplog and with a
fresh subprocess that forces empty/stale sequences at normal WARNING logging;
assert exact diagnostic lines and absence of synthetic sensitive markers.

Exercise the broker's existing replay/ambiguity path: repeat after exhaustion
and prove no adapter call or further push/read occurs and the terminal remains
blocking. Add a wait-boundary interruption case using the existing
`PublishCrashInjected` seam and activated generation fixture: inspect the actual
held lease and unsealed owner during sleep, interrupt, then prove a restarted
or competing publication refuses without another adapter mutation. Assert the
existing finally-release behavior after the injected Python exception; do not
claim it models an OS crash or leaves a lease orphan. Keep owner/fence/storage
implementations unchanged. Tests must fail
against current main for new observation behavior, not for incidental imports.

### `phase-loop-runtime/tests/test_convergence_broker_credsep.py` (modify narrowly)

Replace only the abbreviated shared head fixture and `other-sha` stale-head
fixture with distinct full hexadecimal heads, so the existing stale diagnostic
test exercises eligible stale data rather than malformed data. Retain all
assertions, including both independent empty-list fail-closed controls from
agent-harness#834. Correct the nearby comment that asserts an empty list proves
a race: it proves only the observed empty shape. Add a local captured-sleep
monkeypatch in just the stale-head test and those two empty-list controls, and
assert `[1, 2]`; this prevents nine seconds of real waits and explicitly changes
their witness from single-read refusal to exhausted-read refusal. Retain their
terminal assertions. Freeze these test edits with the new tests before source
implementation; no global sleep patch or deletion/weakening of tests.

### `docs/phase-loop/convergence-contracts.md` (modify)

Carry the earlier contract amendment's complete ownership, classification,
confirmation and lease boundaries. Say this candidate implements the described
bounded observations; remove its old separate-implementation prerequisite.
Document final-observation exhaustion reasons and metadata-only diagnostics.
More reads extend the unsealed owner and generation lease interval; the lease
has no TTL/renewal. Counts and added sleeps do not bound command durations or
establish an overall lease deadline. Competing publication retains its existing
permanent-block behavior. No terminal reversal, new admission, owner seal,
lease reset, restart/resume, provider drain or asynchronous mutation guarantee.
Document intentional reason refinements: blank stdout is `pr-read-unparsable`
instead of `pr-list-empty`; a missing/malformed differing head is
`pr-read-unparsable` instead of `pr-head-unconfirmed`; identity-invalid stale
objects receive the specific identity reason above. Terminal ambiguity is
unchanged. Metadata diagnostics are WARNING records, not durable evidence.

### Planning and recording metadata (modify/create)

This existing plan path, its single entry in `plans/manifest.json`, and
`.dev-skills/handoffs/codex-plan-detailed/` / `codex-execute-detailed/` records
are owned. Preserve every prior manifest entry. After an actual fix PR exists,
append its real four-column row to the existing interim ratification ledger
`plans/decision-interim-president-ratification-20260904.md`, then include that
recording row in fresh exact-head review before landing. No invented PR number
or approval. The initial publication is a draft; no unreviewed source is added
by the recording step. No package version or unrelated roadmap edits.

## Dependencies and order

1. Freeze this plan and its bounded source inputs; obtain fresh native
   Fable/Codex/Gemini/Grok review with a non-author counterexample/ablation.
   Under the interim decision, require four usable AGREE verdicts and no
   unresolved finding. Fetch main and inspect the actual president operation
   and expiry ledger, plus agent-harness#752 and its linked landing PRs, before
   relying on the interim decision. Issue-open status alone is insufficient:
   the exception expires when the operation lands on main. Repeat immediately
   before landing; use the required president route if it has landed. No
   historical votes transfer.
2. Add and freeze new tests; retain native RED on unchanged production. Make
   the narrowly described fixture and captured-sleep changes explicit, then implement only
   owned source/docs and retain GREEN against that frozen test inventory.
3. Run all verification below. Retain actual commands, runtime/module hashes,
   source/head binding and raw results. Obtain fresh exact-source four-seat
   review and independent preservation/restore of private review evidence.
4. Publish only this fix's draft through the already-qualified main native broker
   in generation 2. Do not switch the live publisher to this unmerged repair or
   change the global runtime. This first live publication therefore proves
   admission/confirmation/sealing by the existing publisher, NOT execution of
   the new bounded-read code. The isolated test subprocess and reviewed wheel
   supply the new implementation evidence before landing. No direct git push
   or fabricated admission. Retain native publication result and stderr.
5. If publication returns `pr-head-unconfirmed`, stop/report, with no retry or
   third rotation. Any other ambiguous terminal also remains fail-closed; do
   not infer authority to bypass it. Success alone does not authorize a release.
6. After the draft publication seals successfully, record the real PR in the
   interim ledger, then run fresh exact-head review and publish the recording
   head to that SAME fix PR through a distinct native admission for its new
   `(repo, branch, head_sha)` triple. The exception is one fix PR, not one push
   across all its heads. Each invocation remains one push/create at most. Never
   start the next admission until the predecessor is successfully sealed;
   never reuse or retry an ambiguous terminal. Check remote final head and
   required CI, then merge only under standing operator authorization. Keep the
   publication hold until this fix is landed. No standalone contract/cleanup PR.

## Verification

Use Python 3.14 for the repository's aggregated native guard (including
`ci/dagger/pyproject.toml`); executable pin is `python3.14`, not `3.14`.
Run the focused sequence tests first, then the complete bounded regression set:

```bash
uv run --project phase-loop-runtime --group test --python 3.14 python -m pytest -q phase-loop-runtime/tests/test_pr_readback_789.py
uv run --project phase-loop-runtime --group test --python 3.14 python -m pytest -q phase-loop-runtime/tests/test_pr_readback_789.py phase-loop-runtime/tests/test_convergence_broker_credsep.py phase-loop-runtime/tests/test_convergence_provider_contracts.py phase-loop-runtime/tests/test_convergence_broker_evidence.py phase-loop-runtime/tests/test_convergence_live_enable.py phase-loop-runtime/tests/test_broker_evidence_schema_drift_789.py phase-loop-runtime/tests/test_fabpub_recovery_controls_789.py
git diff --check
```

Run the same combined command through the native verification runner and retain
its verification artifact, not just a standalone pytest summary. Use the existing
build/wheel verification and required CI for the actual publication candidate.
Before source review, compare the contract AST with input main after removing
only the two permitted field values; assert other values match. Check owned-path
scope and hash the frozen new tests before/after GREEN. Cross-vendor review must
challenge third-round success, each exhaustion reason, and in-flight-owner
exposure; passing fixtures are not a proof of historical GitHub causality.

```yaml
automation:
  suite_command:
    - uv
    - run
    - --project
    - phase-loop-runtime
    - --group
    - test
    - --python
    - "3.14"
    - python
    - -m
    - pytest
    - -q
    - phase-loop-runtime/tests/test_pr_readback_789.py
    - phase-loop-runtime/tests/test_convergence_broker_credsep.py
    - phase-loop-runtime/tests/test_convergence_provider_contracts.py
    - phase-loop-runtime/tests/test_convergence_broker_evidence.py
    - phase-loop-runtime/tests/test_convergence_live_enable.py
    - phase-loop-runtime/tests/test_broker_evidence_schema_drift_789.py
    - phase-loop-runtime/tests/test_fabpub_recovery_controls_789.py
```

Private read/write allowlist for this operation: this worktree's
`.phase-loop/diagnostics/confirmation-fix-789-20260914/**`; the prior contract
plan's named handoff and diagnostic review/verification records; the reviewed
runtime qualification records and executables under
`/mnt/workspace/trains/agent-harness-runtime-repairs-20260910/`; native review
retention in `/mnt/workspace/forensics/agent-harness/confirmation-contract-source-review-20260913/`.
The prior qualified review-instrument controls `forensic-r58-controls.json`,
`print-retention-r58-controls.json`, and
`readback-contract-review-20260913/grok-isolated-launch-provenance.json` under
the existing agent-harness-734-diagnostic-wait worktree's diagnostic directory
are read-only qualification inputs, not authority to change that runtime.
Do not read secrets or host-probe payloads. Live FABPUB state is read-only except
the authorized native publications of reviewed heads of this same fix PR,
each only after its predecessor has sealed successfully; no rotation here.

## Acceptance criteria

- [ ] Fresh four-seat plan review and exact-source review agree; all material
  findings reconciled and actual input/transport/retention bindings verified.
- [ ] Native RED discriminates missing observation behavior; frozen tests and
  the combined native GREEN verification artifact prove the sequence matrix,
  terminal permanence, single mutation attempts and diagnostic privacy.
- [ ] Contract AST scope, unchanged fences/storage, test inventory, owned-path
  checks and `git diff --check` pass; docs state implemented policy honestly.
- [ ] The qualified main publisher admits, confirms and seals the reviewed
  fix PR heads in generation 2, with retained terminal evidence. New code is
  proved separately by isolated verification, not claimed as live exercised; a
  failure is reported as blocked, never cleared by another rotation.
- [ ] The actual final PR head includes its truthful ledger row, fresh review
  and required green CI before authorized landing. No package release or fleet
  acceptance is inferred. Preserve worktree/evidence until safe merged cleanup.
