---
phase_loop_plan_version: 1
phase: REVBOUND
roadmap: specs/phase-plans-v11.md
roadmap_sha256: be453ea57c7fe77c0f16f2af0e47158440cb2b0241fa65794292464556a8fa3c
automation:
  suite_command: ["python3", "-c", "import json, pathlib, pytest; manifest = json.loads(pathlib.Path('.phase-loop', 'evidence', 'REVBOUND', 'content-tdd-receipt.json').read_text()); paths = manifest['regression_files']; assert paths; raise SystemExit(pytest.main(['-q', *paths]))"]
---

# REVBOUND: Bounded Review Loop

## Context

Implement Phase 2 of the bound roadmap; its EC IDs are the acceptance authority.
REVBOUND has no upstream phase dependency. Preserve PANEL's composition and vendor
fallback rules, FAB authorization/equivalence checks, and EXECFIND receipt provenance.

Current construction sites are `ReviewFinding` in `closeout_validators.py`,
`_findings_from_panel` and `_gate_result_from_panel` in `governed_review.py`,
and `run_governed_premerge_loop` in `governed_premerge.py`.
Findings have no citations; the gate also holds on raw prose dissent.
The loop's counter resets per invocation, and cap exhaustion returns
`non_convergence`. `runner.governed_premerge_for_run` and
`train_runner._default_train_review` must carry durable context; production
callers currently pass `apply_fix=None`. Do not make this phase depend on
REVIEWTRUTH's future repair dispatcher: repeated invocations must resume a PR's
budget and review delta without that dispatcher.

Canonical runner state is `.phase-loop/`. At planning time it contains this
active planning launch and no state/event snapshot requiring reconciliation.
Legacy state is not an execution prerequisite. This plan defines interfaces;
implementation publishes their passing evidence.

## Interface Freeze Gates

- [ ] IF-0-REVBOUND-1 — Add `ReviewFinding.cites: tuple[str, ...] = ()`; serialize it as a JSON string array and accept absent legacy citations as empty. Empty/blank citations are non-blocking and retain the finding body and reviewed head. A substantive citation identifies an existing goal ID, a named contract anchored to a repository path, or a pytest node ID; a citation is not proof of resolution. Preserve explicitly cited unresolved blockers. Runtime-generated structural findings cite their actual governing contract at construction; never infer citations for reviewer prose from severity, a generic finding code, or another finding.
- [ ] IF-0-REVBOUND-2 — Freeze `review_round.v1` in `review_rounds.py`: `schema`, `pr` (repository-qualified PR or null for a non-PR subject), `subject` (stable local/packet identity when no PR), `head` (observed reviewed Git head; base HEAD for pre-commit subjects), `reviewed_content` (kind and digest: committed tree, pre-commit index tree from `git write-tree`, or plan/probe/packet artifact SHA-256), `round_number` (positive integer), `cap` (positive integer), `outcome` (`converged | descoped | halted`). Retain per-seat verdicts, previous head/content identity, finding identities/citations/resolutions and filed qualified issue references as versioned record metadata. PR or non-PR subject identity, never content/head/process, keys the budget. Reserve a round under a shared lock before a board launch, finalize its record on every exit, and refuse N+1 before spawning. Interrupted reservations consume budget and resume idempotently; do not invent an outcome meaning approved. A `halted` round has not approved the subject, even if a later allowed round repairs it.

IF-0-REVBOUND-2 order is: autonomous no-op → advisory-brief refusal
(`advisory_not_landing_evidence`) → missing-context admission check → composition.
The first two retain their existing results without requiring context; neither
reserves a round or dispatches providers. Admission requires canonical repository authority, a qualified PR
or explicit stable non-PR subject, and observed head/content identity. A governed
loop or gate lacking these returns `review_context_missing` (`ran=false`,
non-promotable/non-mergeable, zero rounds) with a structural finding citing this
contract, before reservation, provider dispatch or issue filing. This is a
pre-admission rejection, never a legacy-review fallback or fabricated ledger row.
Tests exercising review behavior inject temporary repository/subject context and
fake providers/issue filers; no low-level loop/gate silently selects a live filer.
Only production callers explicitly supply the real filing boundary.

SL-1 freezes `ReviewRoundContext`, `reserve_review_round`,
`finish_review_round` and `load_review_rounds` before SL-2 consumes them.
Storage is `.phase-loop/review-rounds/` under the canonical repository authority,
shared by that repository's assigned worktrees, with locks/reservations alongside
the ledger. Resolve authority before staging reviewer scratch directories.
Non-PR reviews use an explicitly separate subject; train packets retain member
PR/head bindings and consume each member's budget. No fabricated PR identifiers.

SL-2 freezes all production caller bindings below. Paths in subject keys are
repository-relative and normalized; aliases are canonical. Keys are scoped to
canonical repository authority and survive restart, worktree and head changes.
Artifact digests cover the exact reviewed bytes, with retained snapshots.

| Caller | Subject / PR binding | Observed head and content |
| --- | --- | --- |
| `runner._governed_planning_gate` | `plan-doc:<roadmap-path>:<alias>:<plan-path>` | Repository HEAD and SHA-256 of the plan file bytes read for review. |
| `runner._governed_premerge_review` → `runner.governed_premerge_for_run` | `local-closeout:<roadmap-path>:<alias>:<plan-path>` | Base HEAD and retained staged index tree captured before review; preserve reviewed-tree/committed-tree equality. The wrapper forwards explicit context, never invents a subject. |
| `train_runner._default_emit_native_fill_request` | Validated packet member qualified PRs under each member's canonical authority; same bindings as completion. | Each member head and packet artifact SHA-256; emission only stages the request, with no reservation or ledger round. |
| `train_runner._default_train_review` | Same member PR budgets, independent of packet digest or train invocation. | Each member head and packet artifact SHA-256, matching emission when used; revalidate before the actual board run, which atomically reserves each member once, retaining per-member committed-tree bindings. Preserve the one-round train policy. |
| `legible_evidence.observe_reviewtruth_fable_transition` (emit and completion) | `reviewtruth_fable_transition:<issue>` | Canonical repository HEAD and probe artifact SHA-256; emission and completion carry the same context. |
| `train_runner._default_delta_review` → `runner.governed_premerge_for_run` | Actual qualified PR from the admitted FAB binding, forwarded by the train caller. | Live reviewed head and committed tree, with admitted base/head for the delta; preserve FAB authorization/equivalence checks. |

Native-fill emission validates context in the same order above but is pre-admission:
no board launch or round consumption. Completion revalidates those bindings and
reserves once for the actual board run; nested gates reuse the parent reservation.

## Lane Index & Dependencies

SL-0 — Frozen behavioral tests and receipt
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no
SL-1 — Lane A: citations and persistent rounds
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no
SL-2 — Lane B: cap disposition and delta review
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no
SL-3 — Documentation and final evidence reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Frozen behavioral tests and receipt

- **Scope**: Freeze the phase's path-entered behavioral tests and record their content-bound RED evidence before production edits.
- **Owned files**: `phase-loop-runtime/tests/test_revbound_*.py`, `phase-loop-runtime/tests/revbound_content_tdd_adapter.py`, `.phase-loop/evidence/REVBOUND/content-tdd-receipt.json`, `.phase-loop/evidence/REVBOUND/content-tdd-receipt.red.stdout.log`, `.phase-loop/evidence/REVBOUND/content-tdd-receipt.red.stderr.log`
- **Interfaces provided**: `REVBOUND frozen tests`, `REVBOUND content receipt`
- **Interfaces consumed**: `record_content_tdd_receipt` (pre-existing), `verify_content_tdd_receipt` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add citation, round-ledger, cap-disposition, delta-review, production-wiring and receipt test modules under the owned glob. Drive real gate/loop/runner/train constructors with fake provider and GitHub boundaries. Include fresh-process resume, changed head, simultaneous reservations, failed issue filing, stale vote reuse, and an uncited DISAGREE versus a cited unresolved blocker. Cover the frozen admission order, every caller binding above, emit/completion single reservation, and the runner's same-HEAD staged-fix path specified under EC-REVBOUND-4. Assert entered paths and exact launch counts; no live provider or issue creation.
  - impl: Add the small phase adapter using the existing PRESROUTE adapter pattern and unchanged `tdd_receipts.py`. Require expected behavioral failures, reject collection errors and already-green recording, and expose `record-red --landing-ref <observed-test-ref> --out <receipt>`, `verify --receipt <receipt>`, and `selfcheck`. Bind SL-0's test/support bytes to the actual tests-first ref; no future SHA or commit-count requirement. Resolve predicate P below at that ref and record `ownership_predicate`, `ownership_ref` and sorted `sl2_owned_files` in the content-TDD receipt manifest. Record `regression_files` as SL-0 test modules plus all resolved `test_*.py` paths. These ownership/selection fields do not freeze SL-2's migration bytes in `test_files`. Adapter verification recomputes both sets from the recorded ref and checks them before suite execution or scheduler admission. Record before SL-1/SL-2 edits. The receipt test's verification-only assertion runs after recording, not as a circular RED prerequisite.
  - verify: `python3 phase-loop-runtime/tests/revbound_content_tdd_adapter.py selfcheck`
  - verify: `python3 phase-loop-runtime/tests/revbound_content_tdd_adapter.py verify --receipt .phase-loop/evidence/REVBOUND/content-tdd-receipt.json`

### SL-1 — Lane A: citations and persistent rounds

- **Scope**: Publish both freeze gates and migrate first-party structural finding constructors without weakening their holds.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/closeout_validators.py`, `phase-loop-runtime/src/phase_loop_runtime/review_rounds.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/doc_delta_validator.py`, `phase-loop-runtime/src/phase_loop_runtime/fab_gate.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence_validator.py`, `phase-loop-runtime/src/phase_loop_runtime/visual_avatar_evidence_validator.py`, `phase-loop-runtime/src/phase_loop_runtime/visual_evidence_validator.py`
- **Interfaces provided**: `IF-0-REVBOUND-1`, `IF-0-REVBOUND-2`
- **Interfaces consumed**: `REVBOUND frozen tests`, `REVBOUND content receipt`
- **Parallel-safe**: no
- **Tasks**:
  - test: Run SL-0 citation/ledger falsifiers first, including validator exceptions, missing evidence, FAB drift, grounding failures and legacy serialization. Existing-test migrations belong exclusively to SL-2.
  - impl: Extend the finding model and its normalization/JSON path; ensure empty citations cannot yield effective block severity. Add real contract citations at all first-party validator constructors in this lane. Do not turn advisory findings into blockers merely because they cite something.
  - impl: Implement the frozen ledger APIs, canonical-authority resolution, atomic reservation/finalization, PR-scoped cap and resume handling. Keep event/ledger data metadata-only. Persist non-PR subject identity separately and fail closed on malformed or conflicting ledger evidence rather than silently starting at round one. Cover multi-worktree access to the same authority.
  - verify: `python3 -m pytest phase-loop-runtime/tests -q -k 'revbound_citations or revbound_rounds'`

### SL-2 — Lane B: cap disposition and delta review

- **Scope**: Wire citations and durable budgets into production review entrypoints, then implement safe cap disposition and non-FAB delta rounds.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`, `phase-loop-runtime/src/phase_loop_runtime/legible_evidence.py`, `.phase-loop/review-rounds/**`, and every test/support file matched by predicate P below, excluding SL-0's owned files; the receipt's resolved `sl2_owned_files` is the concrete admission set.
- **Interfaces provided**: `REVBOUND governed integration`
- **Interfaces consumed**: `REVBOUND frozen tests`, `REVBOUND content receipt`, `IF-0-REVBOUND-1`, `IF-0-REVBOUND-2`
- **Parallel-safe**: no
- **Tasks**:
  - test: Run SL-0 cap/delta/wiring falsifiers before implementation; update legacy fixtures to cite real test contracts when they intend to block. Exercise both direct governed gates and loop callers so no public production entry bypasses round admission or double-counts it.
  - test: Uniform changed contract for predicate-owned tests: governed calls lacking a subject inject temporary repository/subject/head/content context or assert `review_context_missing`; uncited prose DISAGREE, including an uncounted leg, is non-blocking with a cited-blocker control; invocation-local cap/`non_convergence` expectations become persisted rounds and cited-halt/uncited-descope dispositions. Use fake providers/filers and preserve existing routing, exclusion, brief-integrity, grounding, native-fill, train authorization and structural-hold assertions. `test_fab_gate_d.py` and all other existing-test migrations have SL-2 as their single writer.
  - impl: Wire every caller in the frozen binding table and the admission order into gates/loop. Retain staged trees across held closeouts/restarts. Direct gates reserve when no parent reservation exists; train multi-member admission is atomic. Thread the persisted previous round through separate calls even when `apply_fix=None`.
  - impl: Parse per-finding citation lines `CITES <finding-id>: <reference> | <reference>` beside existing `FINDING` text, adding the instruction at the governed brief-construction seam. Bind citations to that finding only; absent or malformed lines produce non-blocking observations. Preserve EXECFIND receipt validation and add its actual node/contract references. Add contract citations for structural gate/floor failures. Remove the raw-prose-dissent promotion veto only where it would re-block an uncited finding; keep author exclusion, authorization, grounding and minimum-board checks.
  - impl: At the cap, file unresolved findings idempotently as qualified issues using the existing repository's filing convention in `docs/registers/deferred-findings.md`, retaining verbatim finding text and citations through a body file. Reuse existing qualified references on retry. File both cited and uncited residuals, but a cited unresolved blocker stays held with outcome `halted`; only a fully resolved cited set plus successfully filed non-blocking residuals yields `descoped`. Filing failure stays held, never descoped: record an explicit EC-REVBOUND-3 exception with the failed filing evidence, reason and responsible operator in round metadata and SL-3 closeout. Retry filing idempotently without another board launch. Resolve findings through current review/evidence, never by their absence from a filtered prompt. Never launch N+1 to obtain a more favorable vote.
  - impl: On non-FAB follow-ups, diff the previous/current committed trees for committed subjects, the retained previous/current index trees for staged runner subjects (even at identical HEAD), or retained artifact snapshots for packet subjects; re-dispatch only prior dissenting seat identities. Reuse agreeing votes only when prior board/scope/content provenance matches the prior record and the delta binds that content to the current review; HEAD equality alone never validates reuse. Combine retained votes with fresh votes for the existing floor. Do not reduce configured composition, change vendors or relax authorization to make a one-seat delta pass. Stage and authorize the exact delta brief; keep required president/ruling steps. Missing snapshots or stale provenance hold or require a full round within remaining budget, never an uncounted launch. FAB uses its existing path.
  - verify: Verify the receipt with SL-0's adapter, then run the effective `automation.suite_command`, selecting the resolved files without a name filter.

### SL-3 — Documentation and final evidence reducer

- **Scope**: Document the delivered contracts and synthesize acceptance evidence after every producer.
- **Owned files**: `docs/phase-loop/bounded-review.md`, `plans/evidence/v11-REVBOUND-closeout.json`
- **Interfaces provided**: `REVBOUND closeout evidence`
- **Interfaces consumed**: `REVBOUND frozen tests`, `REVBOUND content receipt`, `IF-0-REVBOUND-1`, `IF-0-REVBOUND-2`, `REVBOUND governed integration`
- **Parallel-safe**: no
- **Tasks**:
  - test: Check that the receipt verifier and all EC-linked nodes pass against the integrated production tree; test the negative controls, not merely schema snapshots.
  - impl: Write the bounded-review guide covering citations, qualified issue filing, cap/restart semantics, non-PR subjects, delta vote provenance and operator recovery. Explain that unreferenced `git write-tree` objects can be pruned by `git gc`; retain snapshots durably, and hold or require a full round within remaining budget if lost. Record observed commands/results, receipt location, both produced IF gates, EC-to-node mapping, filing-failure exceptions and `spec_delta_closeout.v1` evidence in the owned JSON. Report no public spec delta; do not tick or restate roadmap goals.
  - verify: Verify the receipt with SL-0's adapter, then run the effective `automation.suite_command` against the integrated tree.

## Execution Policy

- SL-3: work-unit=`phase_reducer`, unsupported=`inherit_default`, inherit-default=`true`, policy-source=`phase plan`

## Execution Notes

No lane fanout is authorized by this plan. Ownership is disjoint, and the DAG is
SL-0 → SL-1 → SL-2 → SL-3 with explicit producer edges. New sources are limited to
the ledger; reuse existing gate, staging and issue-filing patterns.

Predicate P is the following content search over tracked Python files under
`phase-loop-runtime/tests/`, evaluated at the observed tests-first ref, excluding
SL-0's owned files. It covers direct calls, imported/mocked references, finding
constructors and runner/train/validator consumers:

```bash
git grep -l -E 'governed_(board_gate|planning_gate|premerge)|_gate_result_from_panel|_findings_from_panel|ReviewFinding|phase_loop_runtime[.]runner|train_runner|legible_evidence|closeout_validat|doc_delta_validator|fab_gate|verification_evidence_validator|visual_avatar_evidence_validator|visual_evidence_validator' <observed-test-ref> -- ':(glob)phase-loop-runtime/tests/**/*.py'
```

SL-0 strips the ref prefix and sorts/deduplicates paths. Publish its resolved
ownership manifest to scheduler admission before SL-1/SL-2 dispatch; do not treat
predicate prose as a runtime glob. Newly matched files are absorbed by the same
rule without another plan amendment. On rebase, re-run P, refresh the recorded
resolution through the receipt amendment mechanism, and re-admit ownership before
editing or verifying. Only SL-0 test/support bytes are frozen by this receipt;
existing tests owned by another phase require that phase's recorded receipt repair.

In particular, `runner.py` overlaps PARSCHED/ROUTE/PANEL,
`governed_review.py` overlaps ROUTE/PANEL and `train_runner.py` overlaps
INTEG/RELEASE/PANEL. Exclude overlapping writers using the existing coordinator's
worktree/ownership mechanism; do not manufacture upstream phase dependencies.
Rebase and re-check current function locations when those phases land.
`test_panel_lanes.py` is predicate-owned but its governed-gate cases are latent
until PANEL slice 1 lands. Coordinate its edits through the same overlap exclusion;
after rebasing onto PANEL, re-check ownership/receipts and run those cases activated.

Predicate ownership permits only the changed-contract migrations, not unrelated
test changes. Tests outside the predicate and SL-0 sets, panel modules, skill sources,
generated bundles, snapshots, dependency manifests/lockfiles, and roadmap bytes
remain untouched; no regeneration is needed. Validator suppliers are changed only
to carry contract citations. No visible-render deliverable is introduced by
touching visual-evidence validators. Runner-owned logs/evidence use the canonical
state root and must be accounted for by closeout; SL-0's frozen tests are not edited by
later lanes. A necessary receipt repair uses the existing content-bound amendment
mechanism and records the reason, never silently rewrites evidence.

README, CHANGELOG and release notes: no-doc-change in this phase; the bounded-review
guide owns the behavior documentation, and no installation or release interface
changes. SL-3 checks that decision against its producers.

Plan review follows the roadmap's current full-board-plus-president gate before
ratified execution, including cross-vendor ablation for a Sol-authored plan.
This artifact does not claim review or ratification occurred. No external issues
are filed during planning or hermetic tests.

## Verification

Run from the repository root with the importable local runtime and pytest.
The effective `automation.suite_command` reads the receipt's `regression_files`
and passes every resolved test file directly to pytest, including
`test_agy_self_qualification.py`; no growing `-k` list can omit new matches.
Run focused lane selections first, then this cluster after integration. Capture the
runner's verification evidence and preserve failing node IDs. IF-0-VC-2 intake
uses `validate_plan_verification_commands_for_intake` and validates the effective
suite argv through `validate_verification_commands`; command validity does not
claim the future implementation passes.

- `python3 -m pytest phase-loop-runtime/tests -q -k revbound`

After SL-0 creates its artifact, run the adapter's explicit receipt verifier from
that lane before the effective suite command. Missing/stale selection evidence
fails closed; never fall back to an empty selection. Full repository CI remains
required for landing; do not
reinterpret unrelated host-dependent failures as REVBOUND acceptance. No proxy
operational evidence substitutes for behavioral tests.

## Acceptance Criteria

- [ ] EC-REVBOUND-0 — proven by `python3 phase-loop-runtime/tests/revbound_content_tdd_adapter.py verify --receipt .phase-loop/evidence/REVBOUND/content-tdd-receipt.json`, falsified by a frozen-test byte mutation accepted by `tdd_receipts.verify_content_tdd_receipt`; path-entered control records and verifies a real receipt before corrupting its input.
- [ ] EC-REVBOUND-1 — proven by `python3 -m pytest phase-loop-runtime/tests -q -k revbound_citations`, falsified by restoring the uncited block/pure-prose veto at `closeout_validators.ReviewFinding` or `governed_review._gate_result_from_panel`; path-entered control invokes the real reduction and proves a cited unresolved counterpart still holds.
- [ ] EC-REVBOUND-2 — proven by `python3 -m pytest phase-loop-runtime/tests -q -k 'revbound_rounds or revbound_wiring'`, falsified by resetting admission in `governed_premerge.run_governed_premerge_loop` and observing an N+1 provider launch after restart/head change; path-entered control proves N was reserved, launched and recorded through runner/train callers.
- [ ] EC-REVBOUND-3 — proven by `python3 -m pytest phase-loop-runtime/tests -q -k revbound_cap`, falsified by bypassing qualified issue filing or allowing a cited unresolved blocker through the cap branch in `governed_premerge.run_governed_premerge_loop`; path-entered control reaches the cap with both residual classes and asserts filing receipts before any descoped return.
- [ ] EC-REVBOUND-4 — proven by `python3 -m pytest phase-loop-runtime/tests -q -k revbound_delta`, falsified by restoring full-artifact/all-seat dispatch at `governed_review.governed_board_gate` or the runner's `governed_planning_gate` / `invoke_panel` path, or substituting HEAD equality for content provenance. Controls enter both paths; the runner control holds a staged review, fixes and restages one file without committing, resumes at the same HEAD, and asserts a nonempty exact tree delta, only dissenting-seat launches, and rejection of mismatched carried-content identities.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `none`
- evidence paths: `plans/evidence/v11-REVBOUND-closeout.json`
- redaction posture: `metadata_only`
- downstream handling: `none`
