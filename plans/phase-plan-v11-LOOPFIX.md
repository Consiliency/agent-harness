---
phase_loop_plan_version: 1
phase: LOOPFIX
roadmap: specs/phase-plans-v11.md
roadmap_sha256: be453ea57c7fe77c0f16f2af0e47158440cb2b0241fa65794292464556a8fa3c
automation:
  suite_command: "uv run --quiet --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q"
---

# LOOPFIX: Closeout, Lifecycle and Plan-Validation Friction

## Context

Implement EC-LOOPFIX-0 through EC-LOOPFIX-5 from the anchored roadmap. LOOPFIX is a root phase; REFLOOP consumes its result. Four implementation lanes follow the roadmap's A–D split, preceded by a tests-only freeze and followed by one documentation/bundle reducer. This plan does not authorize destructive cleanup of live worktrees.

Research anchors: `closeout_classifier.audit_ignored_outputs` grades every unknown ignored member without a start snapshot; `plan_manifest.TRANSITIONS` has no successor edge and `_MANIFEST_IN_FLIGHT` derives from its keys; `cli.build_parser` has no validate-plan verb. The canonical validator only recognizes SL-number/em-dash stanzas while `plan_ir` accepts additional IDs, separators, inline metadata and bullet tasks. The cleanup helpers check cleanliness but lack the required activity/head/dry-run protections.

Canonical runner authority is `.phase-loop/`. The current ledger contains LOOPFIX planning dry-run events; the handoff's default TESTLOOP selection does not supersede the explicitly selected root phase. Legacy `.codex/phase-loop/` is read-only compatibility state. Source code lives under `phase-loop-runtime/`, not the historical `vendor/` prefix.

## External Inputs

The frontmatter pins the selected roadmap bytes only. Consume delivered IF-0-GOVLEAN-1, IF-0-VC-2 and IF-0-CANON-1/2. Corpus inputs are committed plans from Consiliency/spec and ViperJuice/greenfield: SL-0 records their repository, original path, observed commit and content digest in its fixture manifest. Do not prescribe future commits, commit counts or output tree shapes.

## Interface Freeze Gates

- [ ] IF-0-LOOPFIX-1 — `phase-loop validate-plan <path>` runs the existing plan-phase checks with exit 0 / 1 / 2 for valid / findings / cannot evaluate. Its installed console entrypoint works regardless of the shell's Python interpreter. Structural lane parsing delegates to the existing runtime grammar; policy checks remain distinct from structural diagnostics. Legacy helper scripts retain compatible check functions, with local enforcement wrappers called by their own `main` as specified in SL-3.
- [ ] IF-0-LOOPFIX-2 — `plan_manifest.update_lifecycle(repo, slug, "superseded", by, {"successor_plan": successor_slug})` admits only `failed → superseded`. Require a distinct existing successor entry of the same plan type and, for phases, the same phase/roadmap identity; reject missing/self/cyclic or terminal successor references without writing. Preserve the failed lifecycle history and unrelated manifest rows. `superseded` is terminal; both failed and superseded remain outside `plan_manifest._MANIFEST_IN_FLIGHT`, with classification checked through `phase_status_disagreements`. The successor follows the normal executing/completed lifecycle.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: none
- evidence paths: `docs/phase-loop/loopfix-closeout.md`, `.phase-loop/evidence/LOOPFIX/`
- redaction posture: `metadata_only`
- downstream handling: none

No roadmap goal or shared spec format changes are planned. CLI and lifecycle implementation/documentation realize the already frozen roadmap interfaces. Evidence names paths, digests, test IDs and outcomes; it never embeds ignored file contents or credentials.

## Lane Index & Dependencies

SL-0 — Test freeze
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3, SL-4, SL-5
  Parallel-safe: no

SL-1 — A: Ignored-output baseline
  Depends on: SL-0
  Blocks: SL-5
  Parallel-safe: no

SL-2 — B: Manifest successor
  Depends on: SL-0
  Blocks: SL-5
  Parallel-safe: no

SL-3 — C: Validator and CLI
  Depends on: SL-0
  Blocks: SL-5
  Parallel-safe: no

SL-4 — D: Worktree cleanup
  Depends on: SL-0
  Blocks: SL-5
  Parallel-safe: no

SL-5 — Documentation and bundle reducer
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Test freeze

- **Scope**: Freeze the behavioral tests, downstream corpus and content-bound RED receipt before any production or skill-source edits.
- **Owned files**: `phase-loop-runtime/tests/**.py`, `phase-loop-runtime/tests/fixtures/loopfix/**`, `.phase-loop/evidence/LOOPFIX/content-tdd*`
- **Interfaces provided**: `LOOPFIX-frozen-tests`, `LOOPFIX-RED-receipt`
- **Interfaces consumed**: `IF-0-GOVLEAN-1` (pre-existing), `plan_ir.parse_phase_plan_ir` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Restrict the Python ownership envelope by predicate: SL-0 owns every file under `phase-loop-runtime/tests/**` whose collected nodes fail against the frozen LOOPFIX interface changes (`PLAN_STATUSES`/`TRANSITIONS`, in-flight/terminal sets, the four registered rule-enforcement symbols, the skills-src runtime-import inventory, and the legacy scripts' literal/contract-bug/one-error-per-violation contracts), plus the new LOOPFIX tests and their adapter/support. Collect across the test tree; resolve this set once at the observed tests-only HEAD, record the resolved file list in the content-TDD receipt's `test_files` and retain node/failure evidence. Unrelated failures do not authorize edits. Production-mirror data belongs to SL-5 under its carve-out below.
  - test: Under that predicate, `test_launchspec_golden.py` and `test_executor_exited_without_closeout_785.py` fail against the skills-src runtime-import inventory change. SL-0 adds the first canonical-text step in the 785 permitted-delta chain: assert `tests/data/launchspec_golden/pre_loopfix_ec3.json` exists, load it, assert `["current"] in canonical`, replace that span with `["pre_loopfix"]`, then run the existing deltas unchanged so the historical normalized digest at 785:151 is recovered. Freeze this test change in the receipt; SL-5 writes the delta data after SL-3 finishes.
  - test: Add `test_loopfix_closeout.py`, `test_loopfix_manifest.py`, `test_loopfix_validation.py`, `test_loopfix_worktrees.py` and `test_loopfix_receipt.py`. Use real temporary repositories, actual CLI subprocesses and production entrypoints. Assert the intended branch/removal command was reached, with accepted and rejected controls; no unconditional RED placeholder, import-error receipt or all-skipped success.
  - test: In the test freeze, rewrite `test_phase_state_disagreement_312.py`'s terminal-set and in-flight literals and transition-derived parametrization to distinguish administrative transitions from execution eligibility: admit terminal `superseded`, keep `failed` and `superseded` outside `_MANIFEST_IN_FLIGHT`, and retain disagreement coverage for `imported`, `committed` and `executing` plus `_MANIFEST_DONE == {"completed"}`. Include this file in the content-bound receipt.
  - impl: Implement only test support. Acquire at least one committed plan from each named downstream repository plus associated roadmap bytes required by frontmatter; keep the original bytes and paths in isolated fixture repositories. Add runtime grammar variants and a legacy roadmap without EC IDs. Separate structural parity from legitimate policy findings; do not rewrite real corpus plans into synthetic passing examples.
  - impl: Extend existing worktree positive controls to age their activity deterministically, retaining tests that actually remove disposable fixture worktrees. Freeze all modified test/support/corpus files in the receipt. The adapter calls `record_content_tdd_receipt` after those tests are recorded in git, using the observed tests-only HEAD as `landing_ref`, before production edits. Emit the literal RED anchor `GOVLEAN deliberate RED anchor` only when a targeted behavioral assertion fails; retain collected node IDs, pytest exit 1 and raw local RED logs. No prescribed future SHA or history topology.
  - impl: Define adapter groups by collection: acceptance = every node from `test_loopfix_*.py`; companions = every node from the other predicate-resolved test files; RED = acceptance plus companions. Freeze their resolved paths/node IDs and all modified support/corpus files through `record_content_tdd_receipt`, using `support_paths` for files outside the LOOPFIX test glob. The `verify-regressions` action derives pytest's narrow `-k` expression from the collected test-file stems in the receipt, adding `seat_reference_inventory`; the receipt-derived stems must select both `launchspec_golden` and `executor_exited_without_closeout_785`, and the action asserts those nodes, all frozen acceptance/companion nodes and the inventory nodes are selected. Do not type those two stems into the `-k` or retype file selectors.
  - verify: `uv run --project phase-loop-runtime python phase-loop-runtime/tests/loopfix_content_tdd_adapter.py record-red`, then its `verify-receipt` action. Use IF-0-GOVLEAN-1's verifier; reject test/log digest drift, missing target nodes, skips, deselections, xfails or errors in the acceptance group. Subsequent lanes verify the receipt without rewriting tests.

### SL-1 — A: Ignored-output baseline

- **Scope**: Capture a phase execution baseline before mutation and exempt only ignored members proven unchanged at closeout.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/closeout_classifier.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- **Interfaces provided**: `LOOPFIX-baseline-audit`
- **Interfaces consumed**: `LOOPFIX-frozen-tests`, `LOOPFIX-RED-receipt`, `generated_outputs.AuditContext` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Run the frozen closeout cases against `audit_ignored_outputs`, the audit console command and the runner's real pre-dispatch seam. Cases cover an unchanged unknown ignored directory, added/changed members, changed symlink targets, wrong-phase/stale or absent baselines, failed enumeration, and existing runner/cache/declared-output rules.
  - impl: In the runner, snapshot ignored members before the first execute dispatch, including before lane worktree mutation, and bind the snapshot to repository/worktree identity, phase and execution attempt under canonical `.phase-loop/`. Preserve that baseline across repair/resume of the same attempt; never re-baseline newly produced files during recovery. Capture a fresh baseline only for a distinct execution attempt. Dry-run, plan and review do not establish execution baselines.
  - impl: Compare repository-relative member identities, file types and content digests; do not follow symlinks outside the tree or treat a pre-existing directory name as blanket permission. Keep existing provenance classification for new/changed members and fail closed on unreadable/mismatched evidence. Add an additive unchanged-before-phase result bucket; no baseline retains current conservative behavior. Standalone audit use may explicitly capture a baseline before work, never lazily at closeout.
  - verify: `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_closeout.py phase-loop-runtime/tests/test_closeout_classifier.py -q`. Confirm the actual pre-dispatch hook fires before a fixture child writes an ignored file, then verify repair cannot absorb it into the baseline.

### SL-2 — B: Manifest successor

- **Scope**: Implement IF-0-LOOPFIX-2 without rewriting failed history or making failed/superseded plans appear active.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py`
- **Interfaces provided**: `IF-0-LOOPFIX-2`
- **Interfaces consumed**: `LOOPFIX-frozen-tests`, `LOOPFIX-RED-receipt`
- **Parallel-safe**: no
- **Tasks**:
  - test: Exercise the real append/update/read/validate/status-disagreement flow: failed predecessor, committed successor, supersede predecessor, then execute and complete successor with the existing required issue inventory/dispositions. Bind EC-LOOPFIX-2 classification assertions to `plan_manifest._MANIFEST_IN_FLIGHT` and `phase_status_disagreements`. Negative controls cover fabricated direct failed-to-completed transitions, missing/self/wrong-phase successors and outgoing superseded transitions.
  - impl: Add the status, edge, metadata validation and round-trip support to existing manifest functions. Decouple administrative successor eligibility from `_MANIFEST_IN_FLIGHT`; adding the failed transition must not regress status-disagreement detection. Preserve schema version 1, ordering and untouched row bytes; keep successful completion's evidence rules.
  - verify: `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_manifest.py phase-loop-runtime/tests/test_phase_loop_plan_manifest.py phase-loop-runtime/tests/test_plan_manifest_append_order_1174.py phase-loop-runtime/tests/test_manifest_per_entry_164.py phase-loop-runtime/tests/test_phase_state_disagreement_312.py -q`. Existing BAML status/metadata fields already accept this additive literal; no generated BAML changes are expected.

### SL-3 — C: Validator and CLI

- **Scope**: Ship IF-0-LOOPFIX-1 through one installed validation path and make canonical skill instructions and parser grammar agree.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/plan_validation.py`, `skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py`, `skills-src/claude/claude-execute-phase/scripts/validate_plan_doc.py`, `skills-src/*/*/SKILL.md`
- **Interfaces provided**: `IF-0-LOOPFIX-1`, `LOOPFIX-skill-sources`
- **Interfaces consumed**: `LOOPFIX-frozen-tests`, `LOOPFIX-RED-receipt`, `plan_ir.parse_phase_plan_ir` (pre-existing), `IF-0-VC-2` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Freeze tests for CLI exits 0/1/2, absent/unreadable inputs, malformed frontmatter, lane cycles/ownership/producer errors, literal validation, goal coverage, falsifiers and verification intake. Instantiate each harness's shipped plan template and compare every runtime-accepted lane grammar against validation, including non-SL IDs, letter suffixes, colon/ASCII/em-dash headings, inline/stanza indices and bullet/table tasks.
  - test: In `test_loopfix_validation.py`, discover EC-LOOPFIX-3 sites by regex over `skills-src/**/SKILL.md`: module forms `\bpython3?\s+-m\s+phase_loop_runtime\b`, import forms `\b(?:from|import)\s+phase_loop_runtime\b`, and dotted references `\bphase_loop_runtime\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*` anywhere, including prose/backticks with or without call parentheses. Every discovered hit must be migrated to an installed phase-loop route that the test invokes as a path-entered positive control, or match `EC3_EXCLUSIONS`, committed in that test during SL-0 with source location/context and a roadmap-consistent reason per exclusion. Its first entry retains the non-executable `phase_loop_runtime.reflection_corpus` mention required by `test_reflection_corpus.py`; it describes the implementation without directing a runtime import. Assert exclusions match only their declared non-executable contexts. Retained module-form or heredoc fallback alternatives are hits, not permitted fallback behavior. The skills-src scan is the EC-LOOPFIX-3 acceptance node. SL-0 freezes the packaged-copy scan under the same rule as a separate companion node outside `test_loopfix_*.py`; SL-5 runs it after regeneration, so SL-3's acceptance run needs no skips.
  - impl: Move the existing validation implementation into the runtime module and delegate structural parsing to `plan_ir`; retain policy checks and compatibility exports from both legacy scripts. Both scripts must keep top-level `def` wrappers for `_check_d_owned_files_disjoint`, `_check_c_dag_acyclic`, `_check_o_producer_dependency` and `_check_i_spec_closeout_plan`, called through their own module globals by their own `main`. Wrappers delegate check logic to the runtime; `main` must use their returned findings, so script-level kill/demote probes still change the verdict with `via_main` evidence. Keep the registry unchanged and preserve its tests' AST and kill/demote assertions under SL-0's predicate. Guard runtime imports so an isolated `python -I -S` script run fails closed with `contract_bug`, never a raw ImportError. Keep `missing_falsifier`, `vacuous_falsifier` and `missing_path_entered_control` literals in the committed scripts and generated copies. Each violation adds exactly one error to `main`; do not double-count structural diagnostics and wrapper findings. Add `validate-plan` parser/dispatch wiring with deterministic diagnostic and exit handling. Do not narrow the parser, silently skip checks when imports fail, or mistake policy rejection for grammar incompatibility.
  - impl: Update plan-phase templates and all plan-validation call sites to `phase-loop validate-plan`. Resolve every non-excluded regex-discovered site through an existing installed route or a thin forwarding route in `cli.py` to its existing runtime API. In particular, add `phase-loop publish-human-invoked` forwarding to `publishing.publish_human_invoked_from_worktree` and migrate all four execute-detailed publishing calls; these are not exclusions. Broad SKILL.md ownership permits only the discovered mechanical invocation changes, preserving arguments, lifecycle metadata and non-runtime fallback semantics; other skill rewording belongs to REFLOOP. Preserve the bare `append_entry`/`update_lifecycle`/`plan-manifest append` tokens and `### Manifest write`/`### Manifest lifecycle` headings required by `test_skill_plan_manifest_write.py:60-154`. No executor/model policy changes.
  - verify: `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_validation.py -q`. Include a temporary isolated install with a shell Python that cannot import the runtime, then invoke the installed phase-loop command. Corpus tests run offline from frozen fixtures, prove all parser-supported forms survive, and retain negative structural controls. SL-5 performs generation and validates packaged copies.

### SL-4 — D: Worktree cleanup

- **Scope**: Enforce recent-activity retention, merged-head identity and read-only cleanup previews at the real shell removal paths.
- **Owned files**: `skills-src/claude/claude-execute-phase/scripts/sweep_stale_worktrees.sh`, `skills-src/claude/claude-execute-phase/scripts/prune_merged_worktrees.sh`, `skills-src/claude/claude-execute-phase/scripts/cleanup_lane_worktrees.sh`
- **Interfaces provided**: `LOOPFIX-worktree-safety`
- **Interfaces consumed**: `LOOPFIX-frozen-tests`, `LOOPFIX-RED-receipt`
- **Parallel-safe**: no
- **Tasks**:
  - test: Reach each script's removal and branch-deletion boundary in disposable repositories with controlled activity timestamps and fake GitHub metadata. Cover a clean recently active tree, clean stale merged tree, dirty/untracked tree, primary/current/locked trees, unmerged head, branch advanced after merged PR, whitespace in paths and `--dry-run`.
  - impl: Use recent worktree Git activity and canonical runner heartbeat/activity as retention signals for the stale sweep, not commit author dates; use a documented default inactivity window of 24 hours with an explicit age option and deterministic fixture times. Preserve all existing dirty/primary/current/lock guards.
  - impl: Prove the current head is merged before removal or deletion. A GitHub MERGED result must identify the merged PR head and match the current branch head (supporting squash merges); PR state alone is insufficient. Recheck the branch ref at deletion and preserve it if advanced. Add `cleanup_lane_worktrees.sh --dry-run [branch-pattern]` with no removals/ref deletion and the same decision predicates as live execution; use checked head identity on every deletion path.
  - verify: `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_worktrees.py phase-loop-runtime/tests/test_worktree_cleanup_dirty_gate.py phase-loop-runtime/tests/test_prune_merged_worktrees_script.py -q`. Pair every KEEP case with a stale/merged disposable-tree removal control. Never invoke live sweeps on the developer's fleet.

### SL-5 — Documentation and bundle reducer

- **Scope**: Regenerate all derived skill files, document the delivered contracts and collect acceptance evidence after every producer finishes.
- **Owned files**: `phase-loop-skills/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/**`, `phase-loop-runtime/tests/data/**/*.json`, `docs/phase-loop/closeout-generated-outputs.md`, `docs/phase-loop/loopfix-closeout.md`, `phase-loop-runtime/README.md`, `plans/manifest.json`, `.phase-loop/evidence/LOOPFIX/verification*`, `.phase-loop/evidence/LOOPFIX/spec-closeout.json`
- **Interfaces provided**: `LOOPFIX-closeout-evidence`
- **Interfaces consumed**: `LOOPFIX-frozen-tests`, `LOOPFIX-RED-receipt`, `LOOPFIX-baseline-audit`, `IF-0-LOOPFIX-2`, `IF-0-LOOPFIX-1`, `LOOPFIX-skill-sources`, `LOOPFIX-worktree-safety`, `IF-0-CANON-1/2` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Verify the unchanged receipt before regeneration; run the narrow regression group, including the frozen packaged-copy scan, after generation and mirror refresh so packaged-copy and production-mirror checks see the finished producers. The post-generation receipt-derived `-k` run must show the 785 permitted-delta node green.
  - impl: Run `uv run --project phase-loop-runtime python phase-loop-runtime/scripts/regenerate_skills_bundle.py` then `uv run --project phase-loop-runtime python phase-loop-runtime/scripts/sync_skills_bundle.py`. Generated changes must be attributable to SL-3/SL-4; do not hand-edit mirrors. Existing generator scripts, lockfiles, package metadata and CI configuration stay untouched.
  - impl: SL-5 owns, under that glob, every file whose committed content (a) matches any of the three EC-LOOPFIX-3 regexes in SL-3, or (b) is the exact-equality target of a test over installed package sources (today `test_seat_reference_inventory.py`). SL-0 resolves this set once at the tests-only HEAD when recording the receipt, records it in the content-tdd evidence sidecar as the mirror set, and excludes it from the receipt's frozen `test_files`/`support_paths`; SL-5 consumes that recorded set. Refresh each resolved file only through its documented regeneration path after every producer finishes (`PHASE_LOOP_REGEN_LAUNCHSPEC_GOLDEN=1` for `launchspec_golden/`, the inventory refresh for `seat_launch_references.json`), never by hand; the resolved set must not be restated as a list elsewhere in the plan. For the inventory refresh, change only rows for LOOPFIX-touched modules and regenerated bundle copies, using existing roles; preserve all unrelated rows and the inventory test's exact-equality assertion. The JSON-only glob leaves `tests/data/**/*.py` with SL-0, keeping check (D) disjoint.
  - impl: As part of that mirror refresh, SL-5 writes `tests/data/launchspec_golden/pre_loopfix_ec3.json` from SL-3's finished text, with `current` and `pre_loopfix` spans consumed by SL-0's frozen delta step. The existing assertions at `test_executor_exited_without_closeout_785.py:102/:109/:151` check that the delta restores the exact pre-LOOPFIX spans and historical digest; SL-5 authors no new assertion.
  - impl: Document baseline lifetime/recovery, validator exits, successor metadata and worktree inactivity/dry-run behavior. Write the EC-to-test/receipt evidence index and metadata-only spec closeout. Update only LOOPFIX's manifest lifecycle row using runtime APIs, preserving other phases' rows; a planner's committed manifest status does not imply a git commit or completed phase.
  - verify: Run the Verification commands in order and record all failures. Require both produced IF gates in the final implementation closeout. Final acceptance is not established by this planning artifact; no visible-render deliverable or visual evidence is required.

## Execution Policy

- SL-0: work-unit=`lane_execute`
- SL-1: work-unit=`lane_execute`
- SL-2: work-unit=`lane_execute`
- SL-3: work-unit=`lane_execute`
- SL-4: work-unit=`lane_execute`
- SL-5: work-unit=`phase_reducer`

## Execution Notes

The four implementation lanes are disjoint. SL-0 owns all changed tests; SL-3 owns shared CLI/skill text; SL-5 alone writes generated copies and synthesis. All lanes are serialized for this plan. Parallel dispatch requires a separately machine-validated schedule and scheduler-owned worktree assignments; this document does not authorize worker fanout.

SL-1 needs the runner's pre-dispatch hook, expanding beyond the roadmap's headline classifier file. Serialize LOOPFIX against any concurrently dispatched phase owning `runner.py`, as well as the roadmap-listed `cli.py`, `plan_manifest.py` and skill-source overlaps. This is a file-conflict exclusion, not a new phase dependency or roadmap amendment. Recheck ownership against live work before dispatch.

Before production changes, finish SL-0's tests-only freeze and receipt, including predicate-resolved existing-test adjustments. Tests frozen into the receipt are immutable afterward; a discovered defect requires an explicit content-receipt repair with fresh RED evidence before continuation. Existing companion suites outside the resolved predicate remain read-only regression inputs; SL-5's production-mirror carve-out is excluded from that freeze. Further ownership or migration gaps must be fixed in the predicates, not by appending hand-maintained lists. No installation credentials or live external services are needed for behavioral tests.

Inherit operator/registry execution policy. Precedence remains CLI/operator override, phase-plan policy, roadmap policy, Dispatch Hints, registry defaults; no silent downgrade without explicit fallback/default inheritance. Plan and production review use the repository's existing review gate; this planning run does not claim ratification.

## Verification

Run narrow regressions, generated parity and installed CLI checks before the whole-suite command from `automation.suite_command`. Retain runner verification logs/JSON under canonical state. The roadmap records pre-existing team-host suite problems owned by TESTLOOP; capture concrete failures if they recur and do not label a failed required run passed.

- `uv run --quiet --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q -k loopfix`
- `uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/tests/loopfix_content_tdd_adapter.py verify-regressions` (receipt-derived `-k`, including `seat_reference_inventory`; receipt-derived stems must select both `launchspec_golden` and `executor_exited_without_closeout_785`, and this action asserts their selection without typing either into the `-k`)
- `uv run --quiet --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_skills_bundle_drift.py -q`
- `uv run --quiet --with-editable ./phase-loop-runtime phase-loop validate-plan plans/phase-plan-v11-LOOPFIX.md`
- `uv run --quiet --with-editable ./phase-loop-runtime python -m pytest phase-loop-runtime/tests -q`

IF-0-VC-2 intake validates these argv/path surfaces and the effective suite command before handoff. The new CLI verb is an SL-3 deliverable; during planning use the existing canonical script plus runtime literal/lane/intake validators. Do not run the future command as if it already existed. Verification must reject zero collected LOOPFIX acceptance nodes and any skipped acceptance target.

## Acceptance Criteria

- [ ] EC-LOOPFIX-0 — proven by `uv run --project phase-loop-runtime python phase-loop-runtime/tests/loopfix_content_tdd_adapter.py verify-receipt` and `test_loopfix_receipt.py`; falsified by changing a frozen test or RED-log byte, accepting an import/collection failure, or skipping a required target at the receipt verifier, with an unmodified valid receipt as a path-entered positive control.
- [ ] EC-LOOPFIX-1 — proven by `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_closeout.py -q`; falsified by the production audit blocking an unchanged baseline member or admitting a new/changed member after the runner's pre-dispatch snapshot, with a path-entered child-write control.
- [ ] EC-LOOPFIX-2 — proven by `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_manifest.py -q`; falsified by successor completion failing through actual lifecycle APIs, accepting an invalid successor, or `plan_manifest._MANIFEST_IN_FLIGHT` / `phase_status_disagreements` classifying failed/superseded history as in flight, with a valid successor completing through those same APIs as a path-entered control.
- [ ] EC-LOOPFIX-3 — proven by `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_validation.py -q -k "entrypoint or skill"`; falsified by the installed CLI failing under an unrelated shell Python, wrong exit codes, or a regex-discovered site lacking an invoked phase-loop route or justified `EC3_EXCLUSIONS` match; invoke each migrated route as a path-entered positive control.
- [ ] EC-LOOPFIX-4 — proven by `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_validation.py -q -k "template or grammar or corpus or legacy"`; falsified by a shipped template or frozen downstream plan receiving a structural diagnostic absent from the runtime parser, or a real invalid lane graph being accepted; assert both parser and validator paths execute using valid corpus plans as path-entered controls.
- [ ] EC-LOOPFIX-5 — proven by `uv run --project phase-loop-runtime python -m pytest phase-loop-runtime/tests/test_loopfix_worktrees.py -q`; falsified by any removal path deleting a recent/advanced/unmerged fixture or mutating during dry-run, with actual stale-merged removals as path-entered controls proving the guards are not unconditional KEEP rules.
