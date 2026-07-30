---
phase_loop_plan_version: 1
phase: HARDEN
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 7f2590bdebf5a892cf0987b67916d2c3b95970b547117b8cbf4adc7c7220838e
automation:
  suite_command: ["bash", "-lc", "set -euo pipefail; harden_junit=\"${PHASE_LOOP_RUN_DIR:+$PHASE_LOOP_RUN_DIR/harden-compatible-suite.xml}\"; if [[ -z \"$harden_junit\" ]]; then harden_junit=\"$(mktemp \"${TMPDIR:-/tmp}/harden-bootstrap-suite.XXXXXX.xml\")\"; fi; PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import read_manifest, validate_manifest; p = Path(\"plans/manifest.json\"); v = validate_manifest(p); assert v.valid, \"; \".join(v.errors); matches = [e for e in read_manifest(Path(\".\")).plans if e.file == \"plans/phase-plan-v10-HARDEN.md\"]; assert len(matches) == 1, f\"expected one HARDEN manifest row, got {len(matches)}\"; e = matches[0]; actual = (e.phase_alias, e.roadmap_ref.file if e.roadmap_ref else None, e.lanes); expected = (\"HARDEN\", \"specs/phase-plans-v10.md\", (\"SL-0\", \"SL-1\", \"SL-2\", \"SL-3\")); assert actual == expected, f\"stale HARDEN manifest row: {actual!r}\"' && PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -m \"not dotfiles_integration\" --junitxml=\"$harden_junit\""]
---

# HARDEN: Isolation and Verification Hardening

## Context

HARDEN closes the reachable review-isolation and verification gaps tracked by
`Consiliency/agent-harness#259`, `Consiliency/agent-harness#248`,
`Consiliency/agent-harness#264`, `Consiliency/agent-harness#246`, and
`Consiliency/agent-harness#241`. Live source inspection at
`1627e3fe51d34a9b8be46fa1d9718d300a606d3c` confirms that review staging preserves
symlinks, every CLI launch still inherits `wrapped_cwd=str(request.repo)`,
review workflow text can contain live absolute paths, and
`child_executor_env` preserves the ambient environment except for Claude
self-markers. The product capability registry currently exposes sixteen
product-loop review cells: codex; Claude print, Channel, and Agent View across
solo, subagent, and agent-team modes; gemini/agy; grok; opencode; pi; command;
and manual/nonlaunch. The complete live review surface is larger: Advisor Board
adds registered homebrew and Omnigent harness lanes, subscription and opted-in
API-key auth lanes, native-host execution, and optional scoped-research routes.
The isolation checklist therefore derives normalized route identities from the
live product and advisor registries instead of treating the sixteen product
cells or the coordinated run's subscription-only panel as the whole fleet.

The roadmap prescribes two functional implementation lanes. `SL-0` is the
literal panelled RED test-only landing required by `EC-HARDEN-0`; `SL-1` and
`SL-2` are the two roadmap-owned functional lanes; and `SL-3` owns the HARDEN
evidence executable, documentation reduction, and read-only landing lifecycle.
The already-installed external v10 coordinator is the immutable bootstrap
boundary. Before dispatch it records the resolved `codex-phase-loop` console
script, installed `phase_loop_runtime` package root, version, Git identity when
available, file SHA-256 values, PID, and start nonce, and proves that this
installation is outside the HARDEN worktree. It launches the pre-change runtime
with `--closeout-mode manual`, rejects any terminal `complete` that runtime
writes after loaded runner/reducer bytes change, and alone owns candidate
commit, push, false-closeout reopening, process termination, fresh repo-local
launch, and merge. Neither the implementation child nor the already-loaded
pre-change runtime may author transition evidence or attest the candidate.

The external coordinator also owns every mandatory four-seat plan,
implementation, and post-landing review. It uses the existing
`PanelRequest.context_refs` true by-reference path over coordinator-materialized
exact-head inputs, with Fable, Sol, Gemini, and Grok all reviewing through
first-party subscription routes and API-key fallback disabled. The staged
bundle, prompt, tool context, and model-visible inputs are secret-free; existing
parent-side CLI subscription state is never copied into referenced material.
Those panels are governance evidence only. They are not product-loop or Advisor
Board route launches under test, are not checklist rows, and cannot satisfy
`EC-HARDEN-5`. Product/advisor route conformance is proved independently by the
supported/refused matrix in `SL-1`.

No already-loaded process may attest a candidate that changes any runner,
verification, or reducer surface it imported. After the external coordinator
freezes and pushes the exact candidate, it starts a new repo-local phase-loop
process at that clean fetched head. After merge, it terminates that process and
starts a second new repo-local process at the exact clean server-recorded
canonical-main head. Only those new runtimes may export
`PHASE_LOOP_RUN_DIR`, create canonical JUnit/evidence in their own run
directories, or attest their loaded heads and modules.

`SL-0` freezes a test-owned activation guard. Before implementation,
`PHASE_LOOP_TDD_EXPECT_HARDEN=1` deterministically activates every new and
opposite-behavior assertion so its intended RED result can be captured. With
that variable absent on the tests-only main, exactly the frozen new-test nodeid
set skips while the five migrated tests execute their unchanged legacy
assertion branches. `SL-2` later installs the production capability marker;
the same immutable tests then activate the HARDEN branches by default. No
production lane owns an `SL-0` test path. A correction to any frozen test or
guard returns execution to `SL-0`, creates a new tests-only commit, re-runs
every affected RED falsifier, and re-panels the new exact digest before
production resumes.

## Interface Freeze Gates

- None. The roadmap declares `Produces: (none)` for HARDEN; the contracts below
  are phase-internal proof obligations and must not be promoted into a
  cross-phase IF gate.

## Lane Index & Dependencies

SL-0 — Test contract, falsifiers, and panelled RED landing
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Review staging and fleet isolation
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-2 — Reconcile, goal-coverage, interpreter, and runner sequencing hardening
  Depends on: SL-0
  Blocks: SL-3
  Parallel-safe: yes

SL-3 — Fresh-process candidate/post-landing evidence and documentation reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Test contract, falsifiers, and panelled RED landing

- **Scope**: Land only the complete HARDEN regression/mutation test set, deterministic activation guard, and runner-owned RED evidence before any production, script, or changelog change.
- **Owned files**: `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py`, `phase-loop-runtime/tests/test_reconcile_portability_85c.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py`
- **Interfaces provided**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-node-partition-contract`, `HARDEN-RED-evidence`, `HARDEN-post-suite-sequencing-contract`
- **Interfaces consumed**: `HARDEN-roadmap-obligations` (pre-existing), `HARDEN-live-source-anchors` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Freeze the guard, all `SL-0.1`–`SL-0.5` HARDEN regression/mutation selectors, the exact 22-nodeid inventory partitioned as 11 `SL-1` nodes + 7 `SL-2` nodes + 4 `SL-3` evidence nodes, the exact 17-nodeid default skip set, the five legacy assertion branches, and the fresh-process/manifest falsifiers.
  - impl: Land the tests-only commit and runner metadata in `SL-0.6`.
  - verify: Prove default-main compatibility plus activated per-selector/per-case RED and positive controls with raw and structured evidence in `SL-0.7`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py` | guarded existing `test_panel_leg_review_dir_never_contains_the_repo`, guarded existing `test_stage_review_tree_is_gitignore_aware_working_tree_copy`, guarded existing `test_resolve_codex_review_stage_materializes_then_cleans`, `test_review_stage_rejects_every_escape_form_before_launch`, `test_review_isolation_registry_matrix_blocks_live_repo_and_privileged_side_effects`, `test_review_capability_registry_set_equality_covers_every_product_and_advisor_route`, `test_every_executable_review_route_requires_equivalent_contained_boundary_or_refuses_before_launch`, `test_review_snapshot_materializes_repo_and_context_refs_without_live_access`, `test_claude_channel_requires_matching_sidecar_review_attestation_before_send`, `test_review_stage_crash_recovery_removes_only_journaled_paths`, `test_review_prompt_argv_cwd_and_env_omit_live_repo` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py -q` |
| SL-0.2 | test | — | `phase-loop-runtime/tests/test_reconcile_portability_85c.py` | `test_reconcile_main_loop_paths_are_cwd_independent`, `test_relative_automation_artifact_is_repo_anchored_not_cwd_anchored` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_reconcile_portability_85c.py -q -k "cwd_independent or repo_anchored"` |
| SL-0.3 | test | — | `phase-loop-runtime/tests/test_goal_coverage.py` | guarded existing `test_legacy_no_ids_no_evidence_no_block`, guarded existing `test_unresolvable_plan_legacy_does_not_block`, `test_goal_coverage_enforce_blocks_every_zero_declared_phase_at_every_completion_gate`, `test_goal_coverage_all_bare_legacy_is_distinct_warns_by_default_and_blocks_under_enforce` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_goal_coverage.py -q -k "legacy_no_ids_no_evidence_no_block or unresolvable_plan_legacy_does_not_block or enforce_blocks_every_zero_declared or all_bare_legacy_is_distinct"` |
| SL-0.4 | test | — | `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py` | `test_argument_consuming_bash_options_and_profile_patch_version_fail_closed` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_verification_interpreter_guard_221.py -q -k argument_consuming_bash_options_and_profile_patch_version_fail_closed` |
| SL-0.5 | test | — | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py` | `test_harden_evidence_verifier_rejects_each_missing_or_forged_obligation`, `test_harden_evidence_verifier_rejects_pretest_target_base_and_pr_range_tests`, `test_harden_fresh_process_lifecycle_rejects_self_wrong_head_or_non_two_parent_merge`, `test_harden_manifest_gate_rejects_malformed_or_stale_phase_entry` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_harden_evidence_verifier.py -q` |
| SL-0.6 | impl | SL-0.1, SL-0.2, SL-0.3, SL-0.4, SL-0.5 | all `SL-0` owned test paths only | frozen tests-only PR and landed commit | Open and merge a tests-only PR into the exact target branch the later implementation PR will use. It changes no source, executable, changelog, roadmap, or manifest path. Record server-returned tests-PR number, target/base/head ref names and object IDs, merge commit, merged time, exact test-tree blob IDs, and commit SHA. Do not create or push the distinct implementation branch until the server reports the tests PR merged and its commit reachable from the target branch head. |
| SL-0.7 | verify | SL-0.6 | all `SL-0` owned test paths only | default skip/legacy proof, activated per-selector/per-case RED, landed-base topology, and positive controls | Fetch the server-recorded post-merge target head and prove the tests commit is its ancestor. With activation absent, require the exact five legacy nodeids to pass and the exact seventeen new nodeids—and no migrated nodeid—to skip. Then set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, collect exactly the same 22 nodeids, and run every nodeid plus every frozen `RED_CASES_BY_NODEID` case separately against that landed pre-implementation base. Require intended assertion failures with zero skip, xfail, collection, import, setup, or teardown errors; record raw stdout/stderr, asserted source anchor, applied mutation/case, exit status, and JUnit in canonical `.phase-loop/` evidence. The coordinator may create the implementation branch only after the guard's exact inventories, raw anchors, and positive controls pass this gate. |

`SL-0` is a complete tests-only landing, not an additive-selector landing.
`phase-loop-runtime/tests/harden_tdd_guard.py` is the single test-owned guard.
It freezes six literal, reviewable inventories:
`EXPECTED_PHASE_NODEIDS` (22 entries), `SL1_NODEIDS` (the 11 review/staging
nodes), `SL2_NODEIDS` (the 7 reconcile/goal/interpreter nodes),
`SL3_EVIDENCE_NODEIDS` (the 4 evidence/lifecycle nodes),
`DEFAULT_SKIP_NODEIDS` (17 entries), and `RED_CASES_BY_NODEID` (every
parameter/case identifier and its raw source anchor). The three lane partitions
are pairwise disjoint and their union equals `EXPECTED_PHASE_NODEIDS`; no task
may run or claim a different partition. The guard reports HARDEN active only when
`PHASE_LOOP_TDD_EXPECT_HARDEN == "1"` or
`phase_loop_runtime.verification_evidence.HARDEN_CAPABILITY_VERSION == 1`.
No other environment value, branch name, Git dirtiness, import failure, or
model/runner assertion activates the new contract.
New test modules import only the guard and pre-existing seams at module scope;
any capability-specific lookup stays inside the activated test body, after the
new-nodeid skip decision, so the inactive default can never fail collection.

The five migrated nodeids are retained verbatim and never skipped. With HARDEN
inactive, they execute their byte-for-byte legacy assertion bodies; with HARDEN
active, the same nodeids execute the opposite HARDEN assertions:

- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_stage_review_tree_is_gitignore_aware_working_tree_copy`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_resolve_codex_review_stage_materializes_then_cleans`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_panel_leg_review_dir_never_contains_the_repo`
- `phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageCloseoutTest::test_legacy_no_ids_no_evidence_no_block`
- `phase-loop-runtime/tests/test_goal_coverage.py::GoalCoverageCloseoutGateTest::test_unresolvable_plan_legacy_does_not_block`

The exact inactive default skip set is the following seventeen new nodeids—no
glob, marker-wide skip, module skip, runtime-derived registry list, or future
test is admitted implicitly:

- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_stage_rejects_every_escape_form_before_launch`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_isolation_registry_matrix_blocks_live_repo_and_privileged_side_effects`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_capability_registry_set_equality_covers_every_product_and_advisor_route`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_every_executable_review_route_requires_equivalent_contained_boundary_or_refuses_before_launch`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_snapshot_materializes_repo_and_context_refs_without_live_access`
- `phase-loop-runtime/tests/test_phase_loop_injection.py::test_claude_channel_requires_matching_sidecar_review_attestation_before_send`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_stage_crash_recovery_removes_only_journaled_paths`
- `phase-loop-runtime/tests/test_review_leg_sandbox.py::test_review_prompt_argv_cwd_and_env_omit_live_repo`
- `phase-loop-runtime/tests/test_reconcile_portability_85c.py::test_reconcile_main_loop_paths_are_cwd_independent`
- `phase-loop-runtime/tests/test_reconcile_portability_85c.py::test_relative_automation_artifact_is_repo_anchored_not_cwd_anchored`
- `phase-loop-runtime/tests/test_goal_coverage.py::test_goal_coverage_enforce_blocks_every_zero_declared_phase_at_every_completion_gate`
- `phase-loop-runtime/tests/test_goal_coverage.py::test_goal_coverage_all_bare_legacy_is_distinct_warns_by_default_and_blocks_under_enforce`
- `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py::test_argument_consuming_bash_options_and_profile_patch_version_fail_closed`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_evidence_verifier_rejects_each_missing_or_forged_obligation`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_evidence_verifier_rejects_pretest_target_base_and_pr_range_tests`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_fresh_process_lifecycle_rejects_self_wrong_head_or_non_two_parent_merge`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_manifest_gate_rejects_malformed_or_stale_phase_entry`

The guard asserts that the two sets are disjoint and their union is exactly 22.
On the landed tests-only base with activation absent, the focused phase JUnit
must contain exactly five passed and seventeen skipped testcases, with the skip
set byte-for-byte equal to `DEFAULT_SKIP_NODEIDS`. With
`PHASE_LOOP_TDD_EXPECT_HARDEN=1`, collection must still equal the same 22
nodeids; all 22 execute and fail at their intended HARDEN assertion with zero
skipped, xfailed, collection, import, setup, or teardown errors. The runner then
uses `RED_CASES_BY_NODEID` to run every parameter/case separately, so aggregate
failure cannot hide a surviving case. It first asserts the frozen source anchor,
applies/selects exactly one case, runs exactly one nodeid, and retains raw
stdout/stderr plus structured JUnit. After implementation installs the
capability marker, the immutable 22-nodeid focused run must report exactly
22 passed and zero skipped; the candidate and post-landing broad JUnit files
must each contain every expected nodeid exactly once with zero skipped.
Ordinary default tests-only CI is GREEN with the marker absent: the five legacy
branches pass and only the exact seventeen-nodeid set skips. No `xfail` is
permitted. No collection/import failure is a RED result or a compatibility
escape.

The active branches preserve the settled HARDEN semantics: the two goal tests
block every all-bare/zero-ID completion route under enforce while retaining the
warn/default legacy control; the panel/staging tests assert the exact committed
or index-tree identity plus approved contained `context_refs`; and unrelated
working-tree/untracked drift cannot change that identity. No implementation PR
may edit, rename, repair, regenerate, or alter the guard, inventories, assertion
branches, docstrings/helpers, nodeids, or test blobs.

| Obligation | Required pre-implementation anchor | Per-parameter mutation and observable |
|---|---|---|
| staged-tree containment | `copytree(..., symlinks=True)` and `copy2(..., follow_symlinks=False)` are present | Absolute link, upward-relative link, chained link, symlinked directory ancestor, broken/cyclic link, non-git fallback link, `..`/absolute staged path, and special-file inputs each reach the staging seam and are rejected before child launch; an in-root regular file and an explicitly materialized in-root link remain positive controls. |
| review fleet isolation | review-capable records come from `capability_registry()` plus the Advisor Board harness, compatibility, auth, backing, native-host, live Omnigent-catalog, and scoped-research registries; CLI specs use live `wrapped_cwd`, and current prompt/env anchors expose the live root/ambient environment | Every normalized product and advisor review route reaches preflight. A credentialless command adapter may execute only inside the exact Linux bubblewrap boundary below. Every provider-backed, API-key, native-host, Omnigent, research, or otherwise broker-incompatible route is refused before credential lookup, session creation, or child launch. Manual/nonlaunch proves no child or capability is created. Removing or adding one live registry route without an equal checklist row fails set equality; executing a refused row or counting the external governance panel as route conformance also fails. |
| contained review snapshot | current review prompts either expose live paths or reduce the workspace to a bundle, while `context_refs` emits live absolute paths and instructs the reviewer to open them | The launcher materializes the exact candidate Git tree plus every approved context ref into run-owned immutable paths, rewrites all child-visible prompt/ref/workspace paths to those copies, and records each original logical label with source/destination SHA-256 provenance. Positive controls open and cite a candidate source symbol and a context-ref sentinel through the rewritten paths. Absolute/upward/chained/ancestor symlinks, special files, path races, or digest mismatches refuse before launch; negative controls cannot resolve or mutate either live original. Bundle-only remains an optional input, never the sole workspace when repository/context inspection is required. |
| crash cleanup | stage creation occurs before `launch_with_spec` cleanup and exact materialized paths are tracked | Normal return, resolver failure, timeout, interrupt, and a parent-process crash are injected separately. Recovery removes only journaled run-owned stage/config/home roots; a lookalike live directory is the positive non-removal control. |
| CWD-independent reconcile | `roadmap_paths_match` and `_normalize_automation_event` accept relative persisted paths | The same ledger bytes are reconciled from repo root and an unrelated CWD. Relative identity fields are rejected identically; relative `automation.artifact` resolves only against the absolute stored repo; relocated absolute roots with equal repo-relative roadmap subpaths remain accepted. |
| enforce goal coverage | zero/unknown declarations can reach `not_applicable()` or a confirmed-legacy skip | Preflight, canonical closeout, delegated/resume completion, and missing-plan closeout each receive every zero-declared form—including a syntactically valid all-bare legacy phase—plus ambiguous, unparseable, and missing-plan declarations under `PHASE_LOOP_ACCEPTANCE_ENFORCE=block`; every case must return a non-human `contract_bug`. The all-bare case must remain distinguishable from parse failure, but only warn/default mode is its nonblocking positive control; the same all-bare phase must never pass an enforce completion gate. |
| Bash/profile bypass | `_relogin_shell_shim` does not consume Bash argument-taking `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, or `--init-file file`/`--init-file=file`, and absent nominal minors can evade patch bounds | Every frozen argument-taking form locates the true `-c` payload only after consuming its argument; missing option names/files, ambiguous `--`, and malformed or unlocatable payloads fail closed. Under `<3.11.5`, a profile-introduced absent `python3.11 == 3.11.9` is shadowed/rejected; direct argv, non-login, satisfying-present, absolute-interpreter, and ordinary `bash -lc` controls retain their existing results. |
| evidence verifier and fresh-process lifecycle | the executable is absent, the current runtime does not export `PHASE_LOOP_RUN_DIR`, and the process that imports `runner.py`/`verification_evidence.py` can dispatch implementation and immediately attempt verification/complete from stale loaded modules | Fixture mutations separately forge external coordinator identity, server PR identity, ordered two-parent merges, target-base ancestry, actual PR range, lifecycle timestamps, process PID/nonce, loaded-head/module digests, distinct PR/branch identity, test/guard blobs and 11/7/4 node partitions, plan digest, governance-seat count, author-vendor independence, RED anchor/result, snapshot provenance, registry/checklist equality, route refusal accounting, and either verification seal. The integration falsifier rejects any child or pre-change-runtime transition/self-attestation; candidate evidence from a process not freshly loaded at exact pushed `I`; post-landing evidence from the candidate process or a process not freshly loaded at exact canonical `M`; a missing/forged external transition, governance record, suite JUnit, fleet checklist, evidence file, or parent hash; external governance evidence counted as route conformance; and any merge or terminal `complete` before the corresponding audit. Its positive control proves the only accepted lifecycle is tests merge and activated RED; 11 green + 7 green + 4 RED; verifier creation + all 22 green; old-process exit and external coordinator commit/push/transition; fresh exact-candidate suite, external by-reference panel, reduction, and audit; candidate-process exit and exact two-parent merge; then fresh exact-main suite, external panel, reduction, final audit, and completion. |
| phase-plan manifest gate | `plans/manifest.json` is valid today, but no scheduled command proves it and the HARDEN evidence contract merely claims manifest validation | The current-manifest command must reject malformed JSON, structural/per-entry validation errors, a missing/duplicate HARDEN row, or stale HARDEN `file`, `phase_alias`, `roadmap_ref.file`, or lane metadata. The frozen fixture drives the same phase-specific gate with one mutation at a time and requires a typed non-zero result; the unmodified current manifest is the positive control. |

Before `SL-0.6`, the external coordinator panels the exact plan digest and exact
tests-only diff by reference with Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and
Grok 4.5. Fable and Sol must both produce usable reviews; all four must actually
review. This governance panel is deliberately outside the mutable product and
advisor launch routes and supplies no `EC-HARDEN-5` evidence. Any material
finding changes the digest and requires a complete re-panel. The tests-only PR
and the later implementation PR must have distinct server-recorded PR numbers
and head branches. The tests-only commit must already be in the implementation
PR's server-recorded target branch before the implementation branch is created
or either production lane is dispatched.

### SL-1 — Review staging and fleet isolation

- **Scope**: Close every staged-tree escape and enforce one fleet-wide review boundary across all supported product-loop and advisor-board review routes.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- **Interfaces provided**: `review-isolation-boundary`, `review-fleet-checklist-evidence`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-RED-evidence`
- **Parallel-safe**: yes
- **Tasks**:
  - test: Confirm the `SL-1.1` review selectors remain frozen from `SL-0`.
  - impl: Implement contained staging, review-route isolation, and journaled cleanup in `SL-1.2`–`SL-1.6`.
  - verify: Run the complete review matrix command in `SL-1.7`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | all `SL-0` review test paths, read-only | frozen review selectors | Confirm every review selector is unchanged from the `SL-0` commit before implementation. |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | staged-tree containment | Validate every enumerated source and destination lexically and after resolution. Materialize safe in-root links as contained regular content or reject; reject every absolute/upward/chained/ancestor escape, special file, and non-git fallback escape before launch; remove the partial stage on every `BaseException`. |
| SL-1.3 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | immutable snapshot and path-isolation matrix | Before prompt/context/argv construction, resolve the declared candidate to an exact Git tree identity—server head tree for a committed/PR review or a launcher-recorded index tree for an exact staged candidate—and materialize that complete tree plus every caller-approved `context_ref` into run-owned staged paths. Preserve each original logical label, but rewrite every child-visible workspace, prompt, manifest, and ref path to the contained copy. Record source identity/path, destination-relative path, kind, bytes, and source/destination SHA-256 in launcher-owned provenance; require equality before launch. Reject lexical/resolved escapes, symlink chains/ancestors, special files, source races, collisions, and digest drift. For a supported executable route, invoke the exact bubblewrap boundary frozen below, mount the finished snapshot read-only at `/review`, make `/review` the child CWD/workspace, and refuse if any live original remains visible in CWD, argv, prompt/context, environment, mounts, or tool policy. A review bundle may accompany the snapshot but cannot replace repository or approved-context material the review contract requires. |
| SL-1.4 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py` | OS-boundary, credential-transport, and tool-isolation matrix | Add route declarations `review_boundary=linux_bwrap_v1` and `review_transport=none|parent_unix_broker_v1`. `none` is permitted only for a credentialless/no-network command adapter. `parent_unix_broker_v1` is a launcher-owned AF_UNIX socket outside the sandbox: the child sees only `/run/review-broker/socket` and a non-secret route/session identifier; the parent owns subscription authentication and provider egress, verifies `SO_PEERCRED`, exposes only the typed single-provider review RPC, and never returns credential bytes. No provider route is supported until its adapter passes the exact broker compatibility probe without a credential file, API key, OAuth token, inherited auth socket, or ambient home. Build the child environment from an allowlist and keep prompt, tool namespace, argv, environment, snapshot, home/config, logs, and model-visible payloads secret-free. Route-specific flags remain defense in depth. Return typed non-human `review_gate_block` before auth lookup/session creation/launch when a platform, boundary, transport, adapter, sidecar, or direct probe is unproved; normalize persisted closeout blockers to `blocker_class=contract_bug`. |
| SL-1.5 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | complete live review-route registry and honest support/refusal | Produce one normalized route registry from every `capability_registry()` record supporting `review` (including command/manual and Claude route/mode expansion) and every Advisor Board route expressible through the live harness/compatibility registries, auth lanes, provider backings, native-host state, scoped-research state, and live Omnigent catalog. Apply the frozen support/refusal table below literally. A refused executable row satisfies the safety invariant only by proving that no credential lookup, session, broker connection, child, or side effect occurred; it is never reported as a supported conforming route. Manual/nonlaunch remains an evidenced non-executable row. Compare normalized registry keys with checklist keys by exact set equality so additions, omissions, duplicates, executed refused rows, and governance-panel records in the checklist fail closed. API-key fallback is disabled throughout HARDEN. |
| SL-1.6 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | crash/recovery cleanup | Journal exact run-owned stage, home, config, and context roots before child launch; clean them on normal return, resolver failure, timeout, interrupt, and next-run recovery after parent crash; never infer ownership from basename, glob, or a live path. |
| SL-1.7 | verify | SL-1.2, SL-1.3, SL-1.4, SL-1.5, SL-1.6 | all `SL-1` owned source paths | exact 11-node review matrix | With `PHASE_LOOP_TDD_EXPECT_HARDEN` absent, import literal `SL1_NODEIDS` from the frozen guard and invoke pytest with exactly those 11 nodeids plus `--junitxml=<run-dir>/harden-sl1.xml`; require exactly 11 passed, zero skipped/xfailed/errors, and JUnit nodeid set equality. |

The exact current product-loop matrix is sixteen cells, but it is only one
projection of the live review-capability registry. The test derives normalized
route keys from `capability_registry()`, Claude route/mode registries, the
Advisor Board harness/compatibility/auth/backing registries, native-host and
scoped-research state, and the live Omnigent catalog. Exact set equality with
the checklist means any newly reachable route fails closed until its posture is
declared and proved. HARDEN lands this honest matrix:

| Executor / surface | HARDEN posture | Exact reason |
|---|---|---|
| credentialless typed command adapter | **supported on probed Linux only** | Runs inside `linux_bwrap_v1` with `review_transport=none`; arbitrary/provider/networked templates refuse. |
| manual/nonlaunch | **supported non-executable** | Creates no child, credential, workspace, broker, or side effect. |
| codex CLI product review | **refused** | `--sandbox read-only` and `--ignore-user-config` do not provide a credentialless parent-broker adapter. |
| Claude print, Channel, and Agent View across solo/subagent/agent-team | **refused** | Permission/tool flags and Channel bearer handling do not place the complete reviewer process tree behind the common boundary/broker. |
| gemini/agy and grok CLI | **refused** | Staged CWD and tool allowlists are not an OS boundary, and neither route proves `parent_unix_broker_v1`. |
| OpenCode CLI and Pi Agent | **refused** | No proved credentialless broker adapter and no equivalent attested OS boundary. |
| Advisor Board homebrew subscription routes | **refused as product routes** | The mutable in-product launch surface has no proved broker adapter; external coordinator panels remain separate governance evidence. |
| every API-key fallback route | **refused** | HARDEN preserves subscription-only governance and never injects API keys. |
| Omnigent, native-host, scoped-research, gateway, and compatibility routes | **refused** | No gateway/native attestation is accepted as equivalent until it proves the same mount, transport, secret-context, probe, and cleanup observables. |

`linux_bwrap_v1` is literal, not descriptive shorthand. Preflight requires
`sys.platform == "linux"`, a realpath-resolved `bwrap` on `PATH`, successful
`bwrap --version`, readable user/mount/PID/network namespace support, and a
successful no-network smoke using `bwrap --die-with-parent --new-session
--unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-net` with
read-only binds for only the required system runtime roots, `--proc /proc`,
`--dev /dev`, a tmpfs `/tmp`, run-owned tmpfs home/config, the immutable
snapshot read-only at `/review`, and `--chdir /review`. Host `/home`, `/mnt`,
`/run`, `/var/run`, the live repository, original context refs, credential
stores, and unrelated paths are never bound. The preflight also requires
AF_UNIX plus `SO_PEERCRED` support and, for `parent_unix_broker_v1`, a
route-specific fake-broker round trip in which the CLI/adapter completes with
no credential source. macOS, Windows, Linux without the namespace smoke, and
any route missing a proved broker adapter are refused before authentication,
snapshot disclosure to a child, or process/session creation.

Before a supported command launch, direct canaries inside the exact namespace
must read the snapshot sentinel, write only run-owned home/tmp, fail to
`stat`/write the live repo and context-ref originals, fail non-broker network
connects, observe the exact allowlisted environment with no secret-shaped key,
and—when a broker is declared—connect only to the run-owned Unix socket. The
launcher records argv, resolved `bwrap` identity/version, namespace inode IDs,
mountinfo reduced to paths/modes, child CWD, environment-key set, broker
protocol/peer identity, tool-policy digest, provenance digest, probe results,
and cleanup in `review_boundary_attestation.v1`. A CLI permission flag, prompt,
staged CWD, canary without path entry, or child self-report cannot populate
these fields.

The review child environment is allowlist-built, not ambient-env-minus-a-few
keys. It may contain `PATH`, `LANG`, `LC_*`, `TERM`, `TMPDIR`, `USER`, `SHELL`,
`PHASE_LOOP_CHILD`, non-secret runner correlation IDs, run-local `HOME`,
`XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, and a non-secret
`PHASE_LOOP_REVIEW_BROKER=/run/review-broker/socket` only for a proved broker
adapter. Subscription tokens, API keys, gateway credentials, provider headers,
auth helper paths, and other secrets never enter the process namespace,
environment, argv, prompt, tool results, snapshot, or logs.
`PHASE_LOOP_CLAUDE_CHANNEL_BEARER_TOKEN` remains usable only by the external
parent-side Channel client and does not make Channel a conforming product route.

Every review route must remove API-key/auth/header/alternate-endpoint variables,
including `OPENAI_API_KEY`, the complete
`CLAUDE_SUBSCRIPTION_BLOCKED_ENV_VARS` set, `GEMINI_API_KEY`,
`GOOGLE_API_KEY`, `GOOGLE_GENERATIVE_AI_API_KEY`, `XAI_API_KEY`, and
`GROK_API_KEY`; mutation credentials and helpers including `GH_TOKEN`,
`GITHUB_TOKEN`, `GIT_ASKPASS`, `SSH_ASKPASS`, `SSH_AUTH_SOCK`,
`GIT_SSH_COMMAND`, `KUBECONFIG`, `NETRC`, `NPM_TOKEN`, `NODE_AUTH_TOKEN`,
`PYPI_API_TOKEN`, `TWINE_PASSWORD`, and `OP_*`; and the `AWS_*`, `AZURE_*`,
`GOOGLE_APPLICATION_CREDENTIALS`, `GCLOUD_*`, `VERCEL_*`, `SUPABASE_*`,
`CLOUDFLARE_*`, `DOCKER_*`, database URL/password/token, and generic
`*_API_KEY`/`*_TOKEN`/`*_SECRET`/`*_PASSWORD` families without exception in the
reviewer environment.
Shared `~/.netrc`, git credential helpers, keyrings, SSH keys/agents, gh config,
cloud configs, package-publisher configs, and 1Password sockets are absent from
the run-local home/config view.

The fleet test injects fake `git`, `gh`, `ssh`, credential-helper/keyring,
`curl`, `npm`, `twine`, cloud CLI, and `op` canaries. For the supported command
route, each attempted live-tree write/delete, git commit/tag/config, HTTPS/SSH
push, GitHub mutation, package publish, cloud mutation, secret retrieval, and
non-broker network side effect must enter the intended probe and be denied
before the canary records a side effect. For every refused route, a preflight
probe proves refusal happened before auth lookup, session/broker creation, or
child launch. A missing probe, an executed refused row, a refusal mislabeled
supported, an external governance panel inserted as a route row, or
route/checklist set mismatch fails. No real external mutation is performed.

### SL-2 — Reconcile, goal-coverage, interpreter, and runner sequencing hardening

- **Scope**: Make main-loop attribution CWD-independent, enforce non-vacuous goal declarations on every completion path, close both `Consiliency/agent-harness#241` login-shell bypass classes, and add the capability marker plus validation for the external-coordinator fresh-process/post-suite lifecycle.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`
- **Interfaces provided**: `path-and-verification-hardening`, `HARDEN-capability-v1`, `external-coordinator-transition-validation`, `runner-owned-run-dir-export`, `runner-owned-post-suite-reduction`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-node-partition-contract`, `HARDEN-RED-evidence`, `HARDEN-post-suite-sequencing-contract`
- **Parallel-safe**: yes
- **Tasks**:
  - test: Confirm the `SL-2.1` reconcile, goal, interpreter, and runner-sequencing selectors remain frozen from `SL-0`.
  - impl: Implement CWD-independent attribution, enforced goal coverage, interpreter guards, the production capability marker, coordinator-transition validation, run-directory export, and post-suite sequencing in `SL-2.2`–`SL-2.5`.
  - verify: Run only the exact 7-node `SL2_NODEIDS` partition that `SL-2` can make green in `SL-2.6`; keep all 4 `SL3_EVIDENCE_NODEIDS` RED until `SL-3.2` creates their executable.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | all `SL-0` reconcile, goal, interpreter, and evidence-verifier test paths, read-only | frozen 7-node `SL2_NODEIDS` partition and still-RED 4-node `SL3_EVIDENCE_NODEIDS` partition | Confirm every selector, partition, and blob ID is unchanged from the `SL-0` commit before implementation. |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py` | CWD-independent attribution | Require persisted repo/roadmap identity fields to be absolute before matching; retain relocated absolute-root equivalence only through identical repo-relative roadmap subpaths and existing SHA provenance. Resolve relative `automation.artifact` against the trusted absolute stored repo, never ambient CWD; reject escape, tilde, symlink-rebind, malformed, and mismatched identities without crashing the main loop. |
| SL-2.3 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py` | enforce completion matrix | Return a typed declaration state that distinguishes declared IDs, syntactically valid all-bare legacy, zero match, ambiguous match, parse failure, and missing plan. Warn/default mode is the only nonblocking legacy path. Under `PHASE_LOOP_ACCEPTANCE_ENFORCE=block`, every state with zero declared EC-IDs—including valid all-bare legacy—and every ambiguous, unparseable, or missing-plan state returns non-human `contract_bug` at preflight, canonical closeout, delegated/resume completion, and missing-plan closeout. Distinct classification must never become an enforce pass-through. |
| SL-2.4 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` | Bash/profile bypass matrix | Model and consume `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, and `--init-file file`/`--init-file=file` before locating the true `-c`; preserve combined login flags; fail closed on missing option arguments, ambiguous `--`, or an unlocatable payload. Under patch-level bounds, conservatively shadow nominal version names absent at resolve time so a profile cannot introduce an unsupported patch after shim construction; emit a clear warning for the conservative block. |
| SL-2.5 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` | capability activation, external transition validation, run-dir export, post-suite reduction, and final audit | Install literal `HARDEN_CAPABILITY_VERSION = 1` in `verification_evidence.py`; this is the only production activation read by the frozen guard. Parse the HARDEN lifecycle/post-suite contract separately from `## Verification` and `automation.suite_command`. Do not make the implementation child or already-loaded parent commit, push, author a transition, reload, self-reexec, attest changed bytes, or complete. On a fresh repo-local `resume`, accept only the exact external-coordinator-authored transition path supplied in non-secret `PHASE_LOOP_HARDEN_COORDINATOR_TRANSITION`; require it beneath canonical `.phase-loop/runs/`, then recompute its coordinator executable/package identity, pre/post Git identities, remote candidate object, plan/roadmap/manifest/test digests, implementation launch PID/times/artifact hashes, rejected false-complete/reopen record, and old-process death. Fail closed unless the coordinator package root is outside the worktree, the candidate worktree is clean, local HEAD equals fetched remote `I`, loaded repo-local `cli.py`/`runner.py`/`verification_evidence.py`/verifier hashes equal Git blobs at `I`, and candidate PID/start nonce differs from coordinator and implementation processes. Before invoking any extracted command or `automation.suite_command`, set `PHASE_LOOP_RUN_DIR` explicitly in the subprocess environment to the current runner-owned artifacts root; never infer it from CWD. Candidate audit stops nonterminal; a separately launched exact-`M` process validates a coordinator-authored post-landing transition the same way. Persist process identities, transition/argv/exit data, and verification/log/JUnit/checklist/evidence paths and hashes in parent-owned metadata. Treat missing/child-authored/stale transition, same-process cycle, stale/wrong head/module, pre-seal call, missing output, forged hash/identity, non-zero reducer, or audit mismatch as non-human `repeated_verification_failure`. |
| SL-2.6 | verify | SL-2.2, SL-2.3, SL-2.4, SL-2.5 | all `SL-2` owned source paths and frozen `SL-0` tests read-only | exact 7-node non-evidence `SL-2` partition | With `PHASE_LOOP_TDD_EXPECT_HARDEN` absent, import literal `SL2_NODEIDS` from the frozen guard and invoke pytest with exactly those 7 nodeids plus `--junitxml=<run-dir>/harden-sl2.xml`. Require set equality with the two reconcile nodeids, four goal nodeids (two migrated plus two new), and one interpreter nodeid; JUnit must report exactly 7 passed, zero skipped/xfailed/errors. Do not run or require any `SL3_EVIDENCE_NODEIDS` here: all four remain intended RED because `verify_harden_evidence.py` does not exist. |

### SL-3 — Fresh-process candidate/post-landing evidence and documentation reducer

- **Scope**: Add the fail-closed HARDEN chronology/evidence executable, synthesize the changelog note, prove all 22 frozen nodes green only after that executable exists, and let the immutable external coordinator drive candidate freeze/push plus fresh candidate/post-landing verification.
- **Owned files**: `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- **Interfaces provided**: `HARDEN-closeout-evidence`, `HARDEN-no-spec-delta`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-node-partition-contract`, `HARDEN-RED-evidence`, `review-isolation-boundary`, `review-fleet-checklist-evidence`, `path-and-verification-hardening`, `HARDEN-capability-v1`, `external-coordinator-transition-validation`, `runner-owned-run-dir-export`, `runner-owned-post-suite-reduction`
- **Parallel-safe**: no
- **Tasks**:
  - test: Confirm and run the frozen evidence-verifier, manifest, and fresh-process fixtures RED in `SL-3.1`.
  - impl: Add the chronology/evidence verifier and changelog note in `SL-3.2`–`SL-3.3`.
  - verify: Run the exact all-22/zero-skip gate in `SL-3.4`, then let only the external coordinator freeze/push and complete the candidate and post-landing gates in `SL-3.5`–`SL-3.6`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | SL-1.7, SL-2.6 | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py` (read-only) | exact 4-node verifier/manifest/process-lifecycle/ordered-parent partition | Confirm the frozen guard/tests and blob IDs match `SL-0`; import literal `SL3_EVIDENCE_NODEIDS`, require exactly 4 entries, and run every nodeid/case intended RED before creating the executable. Require assertion failures with zero skip/xfail/collection/import/setup/teardown errors. The prior green gates are exactly `SL1_NODEIDS` = 11 and `SL2_NODEIDS` = 7; neither can make these four green. |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/scripts/verify_harden_evidence.py` | candidate/post-landing chronology and evidence verifier | Add an executable shebang script with explicit `--lifecycle-stage candidate|post_landing`. Both stages require parent-supplied run directory, sealed `verification.json`, structured broad-suite JUnit, runner-reduced fleet checklist, output path, plan, roadmap, phase, repository, external coordinator transition, external governance-panel record, and exact process/head/module identities. Candidate mode writes only `harden-candidate-evidence.json`; post-landing mode additionally requires and revalidates the candidate evidence/hashes and writes only final `harden-evidence.json`. It derives Git/forge ancestry, ordered parents, PR lifecycle, path ownership, manifest state, nodeid/skip state, transition authorship/identity, governance-seat evidence, and route-checklist evidence; exits non-zero with typed findings for any missing, mismatched, child/self-reported-only, stale-process/run/head, one-parent/squash/rebase merge, external-panel-as-route, or forged obligation; and never discovers another run, trusts CLI booleans/counts, runs as an ordinary suite command, amends `verification.json`, or writes tracked files. |
| SL-3.3 | impl | SL-3.1 | `CHANGELOG.md` | Unreleased note | Add one concise Unreleased note covering contained review staging/fleet isolation, CWD-independent reconcile attribution, non-vacuous enforce goal coverage, and login-shell interpreter hardening. Do not edit roadmap/spec/contract/version/release-pin surfaces. |
| SL-3.4 | verify | SL-3.2, SL-3.3 | all phase-owned paths and frozen `SL-0` tests, read-only | exact all-22 pre-freeze gate | After the implementation child and pre-change runtime exit, and before any candidate commit/freeze/push/panel/merge, the external coordinator launches a separate fresh-import test subprocess over the dirty candidate tree. With `PHASE_LOOP_TDD_EXPECT_HARDEN` absent, import literal `EXPECTED_PHASE_NODEIDS` and invoke pytest with exactly those 22 nodeids plus `--junitxml=<coordinator-run-dir>/harden-phase-focused.xml`. Require exact partition equality `11 + 7 + 4 = 22` and JUnit exactly 22 passed, zero skipped/xfailed/errors. Child closeout and the old runtime's automatic verification are diagnostic only and cannot satisfy this gate. A failed evidence node returns to `SL-3.2`; no lifecycle transition may start from a partial 18-node green. |
| SL-3.5 | verify | SL-3.4 | all phase-owned paths plus coordinator and candidate runner evidence, read-only | externally frozen/pushed candidate and fresh exact-candidate proof | After `SL-3.4` passes, the external coordinator—not the child or old runtime—checks exact owned paths/test immutability, commits one clean candidate `I`, pushes it, verifies the remote object, records/rejects any old-runtime false `complete`, reopens it with the existing `phase-loop reopen` command after the tree is clean, proves old PIDs/locks gone, and writes the run-owned external transition. It launches a distinct repo-local process with `PYTHONPATH=phase-loop-runtime/src` at exact fetched `I` and the exact transition path. That process validates and copies the transition into its run-owned input area, exports its run dir, runs every ordinary verification command and the broad suite, seals JUnit/`verification.json`, and enters a bounded fail-closed `awaiting_external_review` wait without exiting or changing HEAD. The external coordinator runs the mandatory four-seat implementation panel through true `context_refs` over its exact-`I` snapshot and writes the sealed governance record into the candidate run's declared input path; the same still-live candidate process validates that record separately from the fleet checklist, reduces/audits candidate evidence, records nonterminal `candidate_audit=passed`, and exits. Timeout, wrong writer/path/digest, process exit, or changed HEAD fails. Any change or material finding invalidates `I` and repeats `SL-3.4`–`SL-3.5`; merge is forbidden until this gate passes. |
| SL-3.6 | verify | SL-3.5 | all phase-owned paths plus candidate and canonical-main runner evidence, read-only | exact two-parent landing and fresh canonical-main proof | The external coordinator merges only exact reviewed `I` with the required two-parent topology, terminates the candidate process, fetches server canonical main `M`, prepares the exact clean worktree, and writes a post-landing transition. It starts another distinct repo-local process at `M` with modules loaded from `M`. Repeat manifest/plan/roadmap validation, exact 22-node focused and broad compatible suites, Ruff, the separate external four-seat true-by-reference governance panel, post-suite fleet/final reduction, and parent audit. Structured JUnit contains all 22 frozen nodeids exactly once with zero skipped. Only this process may emit terminal `complete`, after it verifies both ordered two-parent merges and the complete lifecycle below. |

`verify_harden_evidence.py` accepts only the fresh parent process's canonical
current HARDEN run directory and parent-materialized inputs beneath it. It never
discovers another run or trusts a path, count, digest, boolean, process identity,
or Git/forge identity supplied only by model output. Candidate and post-landing
stages must jointly prove all of the following from Git, server-returned forge
metadata, process startup records, and sealed runner artifacts:

1. The exact plan digest received an external-coordinator four-vendor
   true-by-reference phase-plan review with Fable and Sol usable, four actual
   reviewing seats, API-key fallback disabled, and no unresolved material
   finding. The exact test/guard digest received the same governance panel
   before tests landed. Neither record appears in the product/advisor route
   registry or fleet checklist.
2. The unique HARDEN row in `plans/manifest.json` passes structural and
   per-entry validation and exactly names this plan, phase, roadmap, and
   `SL-0`–`SL-3`. Malformed JSON, a bad sibling row, missing/duplicate HARDEN
   row, or stale file/alias/roadmap/lane metadata is a typed failure. The
   manifest command appears in both frontmatter and `## Verification`, and its
   sealed command result is required at both exact heads.
3. `harden_tdd_guard.py` and all six phase test files have the landed tests-only
   blob IDs. The guard's literal inventories are exactly 22 expected nodeids,
   partitioned without overlap as `SL1_NODEIDS=11`, `SL2_NODEIDS=7`, and
   `SL3_EVIDENCE_NODEIDS=4`, plus 17 default skips and 5 migrated legacy
   branches. The tests-only default JUnit is exactly 5 passed/17 skipped with
   the exact skip set. Activated RED collection is the same 22; every nodeid
   and every frozen case has intended assertion-failure raw output and JUnit
   with zero skip/xfail/collection/setup errors. `SL-1.7` is exactly 11 green;
   `SL-2.6` is exactly 7 green while the evidence 4 remain RED; `SL-3.1` records
   those exact 4 RED before the executable exists; and only `SL-3.4`, after the
   executable exists, records all 22 green before candidate freeze. Candidate
   and post-landing JUnit each contain the same 22 exactly once, all passed,
   zero skipped.
4. Server-returned forge metadata identifies distinct tests-only and
   implementation PR numbers/head branches and records repository, URL,
   target/base/head refs and object IDs, reviewed heads, states, merge commits,
   and lifecycle times. The implementation remote branch did not exist before
   the tests PR merged and was created only from the fetched post-test target
   head after activated RED passed.
5. Ordered two-parent topology is exact, not merely reachability. Let `B` be the
   tests PR target object, `TH` its reviewed head, and `TM` its merge commit;
   `git cat-file`/forge metadata must prove `TM` has exactly ordered parents
   `[B, TH]`. Let `I` be the reviewed/pushed implementation candidate, `P` the
   server canonical-main object immediately before implementation merge, and
   `M` the server-recorded merge/canonical-main head; `M` must have exactly
   ordered parents `[P, I]`. Squash, rebase, octopus, synthetic replacement,
   reversed/wrong parents, or a later main head fails. `TM` is an ancestor of
   the implementation branch point, `I`, `P`, and `M`. The actual
   implementation PR range is derived from server identities; it and the
   forge file set contain no `SL-0` path or tests-only commit, and every frozen
   test/guard blob remains identical. A `base -> tests -> implementation`
   branch whose PR targets the pre-test base fails even if the tests commit is
   elsewhere in the head ancestry.
6. Lifecycle order is strict and digest-bound:
   coordinator identity freeze → external phase-plan panel → external
   tests/guard panel → tests PR merge `TM` → default 5-pass/17-skip proof →
   activated raw RED completion → implementation branch creation →
   implementation child writes with old parent in manual-closeout mode →
   11-node `SL-1` green → 7-node `SL-2` green while evidence 4 stay RED →
   evidence 4 RED → verifier creation → old process exit → external coordinator
   rejects false complete → independent exact all-22 green → coordinator-owned
   clean candidate `I` commit/push/remote proof → external transition write →
   distinct repo-local candidate process startup at `I` → candidate
   manifest/focused/broad/Ruff seal → external exact-`I` by-reference
   implementation panel → candidate reduction/audit → candidate process exit →
   coordinator-owned implementation PR merge `M` → distinct post-landing
   process startup at `M` → post-landing manifest/focused/broad/Ruff seal →
   external exact-`M` by-reference panel → final reduction/audit → terminal
   `complete`. Each event carries coordinator-observed time, prior-event hash,
   plan/test/candidate digest, and server object IDs; absent, duplicate,
   out-of-order, or post-dated evidence fails.
7. The immutable external coordinator, implementation launch, candidate
   verifier, and post-landing verifier have distinct recorded PID/start nonce
   values. The coordinator record proves its console script and imported
   package root are outside the HARDEN worktree and byte-identical from initial
   dispatch through final audit. The implementation launch record comes only
   from existing `launch.json`/terminal/event artifacts and is never a handoff.
   The candidate process's startup/loaded HEAD is exactly `I`; the post-landing
   process's is exactly `M`; their repo-local `cli.py`, `runner.py`,
   `verification_evidence.py`, and verifier bytes hash to the corresponding Git
   blobs. Any old-runtime terminal `complete` after changed imported bytes is
   explicitly rejected and reopened; a process that changes/checks out a new
   head after startup exits and can attest neither head.
8. All source/script/changelog changes use the one coordinator-recorded author
   vendor. The broad compatible suite and all ordinary verification commands
   seal green before either external exact-head implementation panel.
   Author-vendor seats are advisory only and the non-author seats satisfy
   governed quorum. A finding/fix changes `I`, invalidates its
   seal/panel/audit, and forces a new all-22 pre-freeze gate, coordinator commit
   and push, transition, and exact-head process.
9. The launcher-owned immutable-snapshot manifest covers the exact candidate
   Git tree and every approved context ref, preserves logical labels, and proves
   source/destination path, kind, bytes, and SHA-256 equality. Positive controls
   open candidate code and context refs only through rewritten contained paths;
   negative controls prove live originals unreachable and unmodifiable.
10. Every normalized live product-plus-advisor review route has exactly one
    runner-observed posture: supported executable, refused prelaunch, or
    nonlaunch. The supported credentialless command route carries the exact
    `linux_bwrap_v1` mount/namespace/env/probe/cleanup attestation; any future
    authenticated route additionally requires `parent_unix_broker_v1` with a
    proved credentialless adapter. Refused routes prove zero auth lookup,
    session, broker, child, and side effect. Checklist and registry keys are
    exactly equal. Refusal satisfies the safety invariant only because the
    route did not execute; it never counts as supported-route conformance.
    External coordinator governance panels are absent from both sets and
    separately prove first-party subscription-only routing.

Candidate mode writes only
`.phase-loop/runs/<candidate-run-id>/harden-candidate-evidence.json`; post-landing
mode writes only `.phase-loop/runs/<main-run-id>/harden-evidence.json`. Each
fresh parent creates its own `harden-compatible-suite.xml`,
`harden-fleet-checklist.json`, verification artifact, and parent audit record.
The post-landing parent copies the candidate evidence and coordinator transition
into its run-owned input area only after verifying the coordinator/candidate
recorded SHA-256 values, then revalidates all candidate bytes and server
identities. Missing evidence is a failed criterion, never an operational
exemption.
`Consiliency/agent-harness#361` may record a standing residual but cannot turn
`EC-HARDEN-5` green.

## Fresh-Process Exact-Head Verification and Landing

This is an external-coordinator plus three repo-runtime-process, two-seal
protocol. The external coordinator is the roadmap-owned v10 control process,
not a new HARDEN executable. It uses existing installed surfaces:
`codex-phase-loop --version`, `run/resume --closeout-mode manual`,
`state --json`, `monitor --once --json`, `reopen --reason`, canonical
`.phase-loop/runs/**` launch/heartbeat/terminal artifacts, Git/forge metadata,
and the Advisor Board `PanelRequest.context_refs` API. Its resolved console
script and imported package files are outside the worktree and digest-frozen
before dispatch. `automation.suite_command` and commands extracted from
`## Verification` are pass-1 verification; no ordinary command may invoke
`verify_harden_evidence.py`, read an unsealed current-run artifact, or claim
post-suite output as suite evidence.

1. **Reachable first landing.** The external coordinator launches the
   implementation process through the already-installed pre-change runtime
   with `--closeout-mode manual`. That runtime does not export
   `PHASE_LOOP_RUN_DIR`, so the frontmatter command's explicit `mktemp` fallback
   is bootstrap-only and its JUnit is never lifecycle evidence. The child
   changes only phase-owned files and does not commit, push, write a transition,
   panel, merge, or complete. The coordinator invokes separate short-lived test
   subprocesses at the lane gates: `SL-1.7` proves exactly 11 nodes green;
   `SL-2.6` proves exactly 7 green while the evidence 4 remain RED; `SL-3.1`
   records the exact 4 RED; then `SL-3.2` creates the executable. This sequence
   needs no new pre-change handoff, no self-reload, and no pre-change run-dir
   export.
2. The external coordinator waits for the installed runtime and implementation
   child to exit and proves their recorded
   PID/process-group/locks are gone. Any old-runtime terminal `complete` is
   classified `false_complete_rejected` because its imported runner/reducer
   identities predate the dirty output. It then runs the authoritative `SL-3.4`
   exact all-22/zero-skip gate in a fresh-import subprocess; child output and
   old-runtime verification cannot substitute. Only after that passes does the
   coordinator validate phase-owned paths and frozen test blobs, commit exact
   candidate `I`, push the explicit branch, verify `git ls-remote` equals `I`,
   then invoke the existing
   `phase-loop reopen --phase HARDEN --reason
   "pre-change runtime cannot attest HARDEN candidate"` on the now-clean tree
   if reconciliation still says complete.
3. The coordinator writes
   `.phase-loop/runs/<transition-id>/harden-coordinator-transition.json` from
   its own process. The sealed record contains coordinator executable/package
   realpaths, version/Git identity/file hashes/PID/start nonce; implementation
   launch artifact paths and hashes; rejected false-complete/reopen event;
   pre/post heads/trees; candidate branch/`I`/remote proof; plan, roadmap,
   manifest, guard/test blob digests; exact 11/7/4/22 results; and old-process
   death. A child/model-produced record, a coordinator root inside the
   worktree, an unsealed/mutable coordinator identity, or a value not
   recomputable from Git/forge/process/run artifacts fails.
4. The coordinator prepares the exact clean fetched `I` worktree and launches:

   `PHASE_LOOP_HARDEN_COORDINATOR_TRANSITION=<absolute-coordinator-transition> PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli resume --repo . --roadmap specs/phase-plans-v10.md --phase HARDEN --governed --closeout-mode manual --max-phases 1`

   The new repo-local runtime validates the transition and loaded module/Git
   identities before dispatch, then copies those exact bytes into its run-owned
   input area and records the source/destination hashes. Only after that check
   does its new
   `SL-2.5` path export `PHASE_LOOP_RUN_DIR=<candidate-run-dir>` to verification
   subprocesses, record `verification_stage=pre_seal`, run dependency refresh,
   exact 22-node focused, every ordinary command, and the broad compatible
   suite under `not dotfiles_integration`, then seal/validate
   `verification.json` and both JUnit files. The bootstrap fallback is forbidden
   in candidate/post-landing evidence: canonical JUnit must be under the
   exported runner-owned directory.
5. The candidate runtime enters a bounded `awaiting_external_review` wait while
   remaining alive at unchanged `I`; it accepts only the declared run-owned
   governance-record path written by the immutable external coordinator. The
   coordinator invokes the four subscription seats with
   `allow_api_key_fallback=False` and true `PanelRequest.context_refs` pointing
   at coordinator-owned exact-`I` read-only material. The governance record
   binds each reviewed ref/hash, exact `I`, plan digest, four seat identities,
   reviewed status/verdict/anchors, and author-vendor independence. It is stored
   separately from `harden-fleet-checklist.v1` and the verifier rejects it if
   any governance seat appears as an `EC-HARDEN-5` route row. A wait timeout,
   candidate exit, wrong writer/path/digest, or changed HEAD fails closed.
6. After a clean governance panel, the fresh candidate runtime validates the
   coordinator panel record, reduces the honest supported/refused fleet
   checklist, invokes:

   `phase-loop-runtime/scripts/verify_harden_evidence.py --lifecycle-stage candidate --repo . --roadmap specs/phase-plans-v10.md --plan plans/phase-plan-v10-HARDEN.md --phase HARDEN --run-dir <candidate-run-dir> --verification-json <candidate-run-dir>/verification.json --junit-xml <candidate-run-dir>/harden-compatible-suite.xml --fleet-checklist <candidate-run-dir>/harden-fleet-checklist.json --coordinator-transition <candidate-run-dir>/harden-coordinator-transition.json --governance-panel <candidate-run-dir>/harden-governance-panel.json --output <candidate-run-dir>/harden-candidate-evidence.json`

   and performs a parent-owned candidate audit. Passed candidate audit records
   `awaiting_phase_closeout`, never `complete`, then exits. A fix invalidates
   `I` and all seals/panels and restarts at `SL-3.4`.
7. The external coordinator merges only exact `I` with ordered parents `[P,I]`,
   proves the candidate process gone, fetches server canonical main `M`,
   prepares a clean exact-`M` worktree, and writes a new post-landing transition.
   It launches the same repo-local command shape with the new exact transition.
   Startup fails closed unless local/remote `M`, ordered parents, coordinator
   identity, and loaded repo-local module hashes all match and the PID/nonce is
   distinct from implementation and candidate processes.
8. The post-landing runtime repeats manifest, plan, roadmap, exact 22-node
   focused, broad compatible, Ruff, exported-run-dir seal/JUnit validation, and
   the separate external exact-`M` four-seat true-by-reference governance panel.
   It reduces a new fleet checklist and invokes:

   `phase-loop-runtime/scripts/verify_harden_evidence.py --lifecycle-stage post_landing --repo . --roadmap specs/phase-plans-v10.md --plan plans/phase-plan-v10-HARDEN.md --phase HARDEN --run-dir <main-run-dir> --verification-json <main-run-dir>/verification.json --junit-xml <main-run-dir>/harden-compatible-suite.xml --fleet-checklist <main-run-dir>/harden-fleet-checklist.json --coordinator-transition <main-run-dir>/harden-coordinator-transition.json --governance-panel <main-run-dir>/harden-governance-panel.json --candidate-evidence <main-run-dir>/harden-candidate-evidence.json --output <main-run-dir>/harden-evidence.json`

9. The parent-owned `_audit_harden_post_suite_outputs()` re-opens both seals,
   all focused/broad JUnit files, both checklists/evidence records, both external
   transition records, both external governance records, and server metadata;
   recomputes every hash, exact digest, coordinator/process/head/module
   identity, ordered parent, registry set, node partition/count/status, and
   lifecycle edge; and matches them to parent state. Missing outputs return
   `post_suite_output_missing`; changed bytes/hashes return
   `post_suite_hash_mismatch`; stale coordinator/process/run/head/plan/roadmap/
   manifest/test/registry/cross-file identity returns
   `post_suite_identity_mismatch`; child-authored/self verification returns
   `self_verification_cycle`; wrong merge parents return
   `harden_merge_parent_mismatch`; and early completion returns
   `terminal_complete_before_final_audit`. These normalize to non-human
   `blocker_class=repeated_verification_failure`. Only the fresh exact-`M`
   process with `final_audit.status=passed` may emit terminal `complete`; every
   failure retains the run-owned artifacts for diagnosis.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`inherit_default`, inherit-default=`true`, reason=`the coordinator supplies the one author executor required by the v10 rotation policy`
- SL-3: work-unit=`phase_reducer`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`, reason=`candidate and post-landing fresh-process evidence plus changelog synthesis after both functional lanes`

Policy precedence is CLI/operator override, this phase-plan policy, roadmap
policy, Dispatch Hints, then registry defaults. This plan does not select an
author vendor: the coordinator must assign exactly one of Claude Sonnet 5 or
Opus 5, GPT-5.6 Terra, Gemini 3.6 Flash (3.5 Flash compatibility fallback), or
Grok 4.5 for the entire code-writing phase and record it before `SL-0`. The same
author vendor owns every implementation lane; cross-vendor lane rotation and
the runtime lane scheduler remain disabled. Same-vendor native workers are
allowed only with runner-owned worktrees and the disjoint ownership above.

## Execution Notes

- Before any test work, the external coordinator records its immutable
  out-of-worktree identity and panels the exact SHA-256 of this plan by true
  `context_refs` with Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5.
  Fable and Sol are mandatory reviewing seats; API-key fallback is disabled and
  a degraded 3-of-4 result blocks. This is governance evidence, never
  `EC-HARDEN-5` route evidence.
- `SL-0` lands literally as tests only. No production source, executable,
  changelog, roadmap, manifest, or closeout implementation may share that
  commit. Land the test-owned guard and immutable tests through their own
  two-parent tests-only PR into the exact target branch. On the fetched
  post-merge target, prove the marker-absent 5-pass/17-skip default and then the
  activated 22-nodeid/per-case intended RED results. Only after that may the
  coordinator create a distinct implementation branch from that head and later
  open the distinct implementation PR. Server-recorded PR target/base/head
  identities, ordered parents, lifecycle, actual PR range, and PR file set are
  evidence; local branch shape or a user-supplied base SHA is not.
- `SL-1` and `SL-2` are write-disjoint. Lane order does not waive the single
  author-vendor policy or authorize scheduler fanout.
- The implementation child only writes phase-owned paths and returns; it may
  not commit, push, transition, attest, panel, merge, or complete. The
  pre-change runtime runs with manual closeout, its missing
  `PHASE_LOOP_RUN_DIR` uses only the non-evidence bootstrap fallback, and any
  stale-module `complete` is rejected. After verifier creation, the external
  coordinator waits for old processes to die, independently proves exact
  all-22 green, then alone commits/pushes `I`, reopens any false closeout, and
  writes the transition.
  The fresh exact-candidate runtime exports its run directory and runs the
  complete compatible suite before the external implementation panel or merge.
  It exits before coordinator merge, and a second fresh exact-canonical-main
  runtime repeats the gate. A repair, checkout, or commit in either verifier
  process invalidates its evidence and requires another all-22/fresh-process
  cycle.
- Execute, repair, plan, roadmap, and maintain-skills behavior are positive
  controls. Review-only CWD/environment/tool/auth changes must not leak into
  another product action.
- A reviewer subprocess or shell inside `linux_bwrap_v1` is permitted. A
  provider-backed product/advisor route is refused until it proves
  `parent_unix_broker_v1`; route-specific CLI flags/prompts cannot substitute.
  A live-repo mutation, credentialed/privileged side effect, live-root
  reachability, ambient credential source, non-broker egress, or unjournaled
  cleanup path is forbidden.
- The phase produces no visible avatar/browser-media render;
  `visual_render_declared` remains false and image evidence is not required.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`, `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-HARDEN.md`, `plans/manifest.json`, `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py`, `phase-loop-runtime/tests/test_reconcile_portability_85c.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py`, `.phase-loop/events.jsonl`, `.phase-loop/runs/**/verification.json`, `.phase-loop/runs/**/harden-phase-focused.xml`, `.phase-loop/runs/**/harden-compatible-suite.xml`, `.phase-loop/runs/**/launch.json`, `.phase-loop/runs/**/terminal-summary.json`, `.phase-loop/runs/**/harden-coordinator-transition.json`, `.phase-loop/runs/**/harden-governance-panel.json`, `.phase-loop/runs/**/harden-fleet-checklist.json`, `.phase-loop/runs/**/harden-candidate-evidence.json`, `.phase-loop/runs/**/harden-evidence.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-HARDEN.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import read_manifest, validate_manifest; p = Path("plans").joinpath("manifest.json"); v = validate_manifest(p); assert v.valid, "; ".join(v.errors); plan_file = Path("plans").joinpath("phase-plan-v10-HARDEN.md").as_posix(); roadmap_file = Path("specs").joinpath("phase-plans-v10.md").as_posix(); matches = [e for e in read_manifest(Path(".")).plans if e.file == plan_file]; assert len(matches) == 1, f"expected one HARDEN manifest row, got {len(matches)}"; e = matches[0]; actual = (e.phase_alias, e.roadmap_ref.file if e.roadmap_ref else None, e.lanes); expected = ("HARDEN", roadmap_file, ("SL-0", "SL-1", "SL-2", "SL-3")); assert actual == expected, f"stale HARDEN manifest row: {actual!r}"'`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -c 'import os, subprocess, sys, tempfile; from pathlib import Path; from harden_tdd_guard import EXPECTED_PHASE_NODEIDS, SL1_NODEIDS, SL2_NODEIDS, SL3_EVIDENCE_NODEIDS; assert len(EXPECTED_PHASE_NODEIDS) == 22 and len(SL1_NODEIDS) == 11 and len(SL2_NODEIDS) == 7 and len(SL3_EVIDENCE_NODEIDS) == 4; assert set(EXPECTED_PHASE_NODEIDS) == set(SL1_NODEIDS) | set(SL2_NODEIDS) | set(SL3_EVIDENCE_NODEIDS); assert not (set(SL1_NODEIDS) & set(SL2_NODEIDS) or set(SL1_NODEIDS) & set(SL3_EVIDENCE_NODEIDS) or set(SL2_NODEIDS) & set(SL3_EVIDENCE_NODEIDS)); root = os.environ.get("PHASE_LOOP_RUN_DIR"); junit = Path(root).joinpath("harden-phase-focused.xml") if root else Path(tempfile.mkdtemp(prefix="harden-bootstrap-focused-")).joinpath("harden-phase-focused.xml"); raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", *EXPECTED_PHASE_NODEIDS, "-q", f"--junitxml={junit}"]))'`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `ruff check phase-loop-runtime/src/phase_loop_runtime phase-loop-runtime/scripts`
- `git diff --check`
- `git diff --cached --check`

The frontmatter `automation.suite_command` is an executable fail-fast composite:
it first validates the entire phase-plan manifest and unique HARDEN row, then
runs the broad compatible suite with structured JUnit. The pre-change bootstrap
runtime does not export `PHASE_LOOP_RUN_DIR`, so that first pass uses `mktemp`
and is explicitly non-evidence. Candidate and post-landing runtimes contain the
new export path and must write JUnit beneath their parent-owned run directory;
the evidence verifier rejects the fallback there. The exact 22-node command
runs after verifier creation and before the broad suite. Both fresh runtimes
seal before the external exact-head panel. HARDEN chronology, raw RED, author
independence, crash cleanup, and fleet evidence become decidable only through
the two post-suite reductions and fresh-parent audits above; they must never be
represented as pre-seal suite evidence.

## Acceptance Criteria

- [ ] EC-HARDEN-0 — proven by the frozen guard's default 5-pass/17-skip JUnit, activated 22-nodeid and per-case raw intended-RED/JUnit records, exact 11-green + 7-green + 4-RED sequencing, exact all-22 green only after verifier creation and old-process exit but before freeze, external coordinator transition, candidate `--lifecycle-stage candidate` evidence, post-landing `--lifecycle-stage post_landing` evidence, and passed fresh-parent `_audit_harden_post_suite_outputs()`; the audit must prove immutable tests/guard, exact manifest validation, ordered two-parent tests and implementation merges, implementation PR range excluding every `SL-0` path and tests-only commit, immutable out-of-worktree coordinator identity, rejected/reopened old-runtime false complete, coordinator-only commit/push/merge, distinct implementation/candidate/main process identities and exact loaded heads/modules, exported run dirs only in new runtimes, broad compatible suite before each external exact-head panel, and the lifecycle tests merge → activated RED → 11/7/4 partition → verifier → old-process exit → independent all 22 green → coordinator freeze/push/transition → fresh candidate suite/external panel/audit → merge → fresh canonical-main suite/external panel/final audit → terminal complete
- [ ] EC-HARDEN-1 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py -q -k review_stage_rejects_every_escape_form_before_launch`
- [ ] EC-HARDEN-2 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_reconcile_portability_85c.py -q -k "cwd_independent or repo_anchored"`
- [ ] EC-HARDEN-3 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_goal_coverage.py -q -k "enforce_blocks_every_zero_declared or all_bare_legacy_is_distinct"`; both selected tests must pass, and the all-bare test must prove warn/default is nonblocking while every enforce completion gate returns non-human `contract_bug`
- [ ] EC-HARDEN-4 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_verification_interpreter_guard_221.py -q -k argument_consuming_bash_options_and_profile_patch_version_fail_closed`; the selector must enumerate `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, and `--init-file file`/`--init-file=file`
- [ ] EC-HARDEN-5 — proven jointly by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py -q -k "review_isolation_registry_matrix or review_capability_registry_set_equality or every_executable_review_route or review_snapshot_materializes or review_prompt_argv_cwd_and_env or crash_recovery"` and the passed runner-owned post-suite final audit; the credentialless command adapter executes only after exact Linux/bubblewrap/namespace/probe success, every provider/API-key/native/gateway/research route is refused before auth lookup/session/broker/child launch until a credentialless `parent_unix_broker_v1` adapter exists, and manual remains nonlaunch; refusal satisfies the safety invariant only through non-execution and is never mislabeled supported conformance; checklist/live-registry set equality and parent-recorded hashes/identities are exact; the external subscription-only four-seat governance panels are absent from the route registry/checklist and cannot satisfy this EC; no CLI flag/prompt, residual register, pre-seal suite result, or self-reported closeout field is a satisfaction route
