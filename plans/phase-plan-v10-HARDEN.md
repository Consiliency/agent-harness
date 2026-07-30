---
phase_loop_plan_version: 1
phase: HARDEN
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 7f2590bdebf5a892cf0987b67916d2c3b95970b547117b8cbf4adc7c7220838e
automation:
  suite_command: ["bash", "-lc", "set -euo pipefail; : \"${PHASE_LOOP_RUN_DIR:?}\"; PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import read_manifest, validate_manifest; p = Path(\"plans/manifest.json\"); v = validate_manifest(p); assert v.valid, \"; \".join(v.errors); matches = [e for e in read_manifest(Path(\".\")).plans if e.file == \"plans/phase-plan-v10-HARDEN.md\"]; assert len(matches) == 1, f\"expected one HARDEN manifest row, got {len(matches)}\"; e = matches[0]; actual = (e.phase_alias, e.roadmap_ref.file if e.roadmap_ref else None, e.lanes); expected = (\"HARDEN\", \"specs/phase-plans-v10.md\", (\"SL-0\", \"SL-1\", \"SL-2\", \"SL-3\")); assert actual == expected, f\"stale HARDEN manifest row: {actual!r}\"' && PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -m \"not dotfiles_integration\" --junitxml=\"$PHASE_LOOP_RUN_DIR/harden-compatible-suite.xml\""]
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
`SL-2` are the two roadmap-owned functional lanes; `SL-2` also owns the generic
fresh-process handoff and post-suite sequencing; and `SL-3` owns the HARDEN
evidence executable, documentation reduction, and read-only landing lifecycle.
No already-loaded process may attest a candidate that changes any runner,
verification, or reducer surface it imported. The implementation process may
freeze, commit, and push a candidate, but it must then exit without conducting
the implementation panel, sealing HARDEN evidence, merging, or emitting
terminal `complete`. A new repo-local phase-loop process must start at that
exact clean pushed head and perform the compatible suite, exact-head panel, and
candidate evidence. After merge, that process also exits; a second new
repo-local phase-loop process must start at the exact clean server-recorded
canonical-main head and repeat verification, exact-head review, reduction, and
the final audit before terminal completion.

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
- **Interfaces provided**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-RED-evidence`, `HARDEN-post-suite-sequencing-contract`
- **Interfaces consumed**: `HARDEN-roadmap-obligations` (pre-existing), `HARDEN-live-source-anchors` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Freeze the guard, all `SL-0.1`–`SL-0.5` HARDEN regression/mutation selectors, the exact 22-nodeid inventory, the exact 17-nodeid default skip set, the five legacy assertion branches, and the fresh-process/manifest falsifiers.
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
It freezes three literal, reviewable inventories:
`EXPECTED_PHASE_NODEIDS` (22 entries), `DEFAULT_SKIP_NODEIDS` (17 entries), and
`RED_CASES_BY_NODEID` (every parameter/case identifier and its raw source
anchor). It reports HARDEN active only when
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
| review fleet isolation | review-capable records come from `capability_registry()` plus the Advisor Board harness, compatibility, auth, backing, native-host, live Omnigent-catalog, and scoped-research registries; CLI specs use live `wrapped_cwd`, and current prompt/env anchors expose the live root/ambient environment | Every normalized product and advisor review route reaches its preflight. Each executable route—including subscription CLI, opted-in API-key, Omnigent, native-host, command-adapter, and research variants—must present an equivalent common-boundary attestation, secret-free reviewer context, and direct side-effect-probe results or be refused before launch and excluded from satisfied coverage. Manual/nonlaunch proves no child or capability is created. Removing or adding one live registry route without an equal checklist row fails set equality; restoring live CWD/env/path or allowing a failed/refused route to count also fails. |
| contained review snapshot | current review prompts either expose live paths or reduce the workspace to a bundle, while `context_refs` emits live absolute paths and instructs the reviewer to open them | The launcher materializes the exact candidate Git tree plus every approved context ref into run-owned immutable paths, rewrites all child-visible prompt/ref/workspace paths to those copies, and records each original logical label with source/destination SHA-256 provenance. Positive controls open and cite a candidate source symbol and a context-ref sentinel through the rewritten paths. Absolute/upward/chained/ancestor symlinks, special files, path races, or digest mismatches refuse before launch; negative controls cannot resolve or mutate either live original. Bundle-only remains an optional input, never the sole workspace when repository/context inspection is required. |
| crash cleanup | stage creation occurs before `launch_with_spec` cleanup and exact materialized paths are tracked | Normal return, resolver failure, timeout, interrupt, and a parent-process crash are injected separately. Recovery removes only journaled run-owned stage/config/home roots; a lookalike live directory is the positive non-removal control. |
| CWD-independent reconcile | `roadmap_paths_match` and `_normalize_automation_event` accept relative persisted paths | The same ledger bytes are reconciled from repo root and an unrelated CWD. Relative identity fields are rejected identically; relative `automation.artifact` resolves only against the absolute stored repo; relocated absolute roots with equal repo-relative roadmap subpaths remain accepted. |
| enforce goal coverage | zero/unknown declarations can reach `not_applicable()` or a confirmed-legacy skip | Preflight, canonical closeout, delegated/resume completion, and missing-plan closeout each receive every zero-declared form—including a syntactically valid all-bare legacy phase—plus ambiguous, unparseable, and missing-plan declarations under `PHASE_LOOP_ACCEPTANCE_ENFORCE=block`; every case must return a non-human `contract_bug`. The all-bare case must remain distinguishable from parse failure, but only warn/default mode is its nonblocking positive control; the same all-bare phase must never pass an enforce completion gate. |
| Bash/profile bypass | `_relogin_shell_shim` does not consume Bash argument-taking `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, or `--init-file file`/`--init-file=file`, and absent nominal minors can evade patch bounds | Every frozen argument-taking form locates the true `-c` payload only after consuming its argument; missing option names/files, ambiguous `--`, and malformed or unlocatable payloads fail closed. Under `<3.11.5`, a profile-introduced absent `python3.11 == 3.11.9` is shadowed/rejected; direct argv, non-login, satisfying-present, absolute-interpreter, and ordinary `bash -lc` controls retain their existing results. |
| evidence verifier and fresh-process lifecycle | the executable is absent, while the process that imports `runner.py`/`verification_evidence.py` can currently dispatch implementation and immediately attempt verification from those stale loaded modules | Fixture mutations separately forge server PR identity, ordered two-parent merges, target-base ancestry, actual PR range, lifecycle timestamps, process PID/nonce, loaded-head/module digests, distinct PR/branch identity, test/guard blobs and nodeid inventories, plan digest, seat count, author-vendor independence, RED anchor/result, snapshot provenance, registry/checklist equality, route refusal accounting, and either verification seal. The integration falsifier rejects any implementation-process self-attestation; candidate evidence from a process not freshly loaded at the exact pushed candidate; post-landing evidence from the candidate process or a process not freshly loaded at exact canonical main; a missing/forged candidate handoff, suite JUnit, fleet checklist, evidence file, or parent hash; and any merge or terminal `complete` before the corresponding audit. Its positive control proves the only accepted lifecycle is tests merge and activated RED; implementation freeze/commit/push and old-process exit; fresh exact-candidate suite, panel, reduction, and audit; candidate-process exit and exact two-parent merge; then fresh exact-main suite, panel, reduction, final audit, and completion. |
| phase-plan manifest gate | `plans/manifest.json` is valid today, but no scheduled command proves it and the HARDEN evidence contract merely claims manifest validation | The current-manifest command must reject malformed JSON, structural/per-entry validation errors, a missing/duplicate HARDEN row, or stale HARDEN `file`, `phase_alias`, `roadmap_ref.file`, or lane metadata. The frozen fixture drives the same phase-specific gate with one mutation at a time and requires a typed non-zero result; the unmodified current manifest is the positive control. |

Before `SL-0.6`, panel the exact plan digest and exact tests-only diff with
Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5. Fable and Sol must both
produce usable reviews; all four must actually review. Any material finding
changes the digest and requires a complete re-panel. The tests-only PR and the
later implementation PR must have distinct server-recorded PR numbers and head
branches. The tests-only commit must already be in the implementation PR's
server-recorded target branch before the implementation branch is created or
either production lane is dispatched.

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
| SL-1.3 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | immutable snapshot and path-isolation matrix | Before prompt/context/argv construction, the launcher resolves the declared candidate to an exact Git tree identity—server head tree for a committed/PR review or a launcher-recorded index tree for an exact staged candidate—and materializes that complete tree plus every caller-approved `context_ref` into run-owned staged paths. Preserve each original logical label, but rewrite every child-visible workspace, prompt, manifest, and ref path to the contained copy. Record source identity/path, destination-relative path, kind, bytes, and source/destination SHA-256 in launcher-owned provenance; require equality before launch. Reject lexical/resolved escapes, symlink chains/ancestors, special files, source races, collisions, and digest drift. Mount the finished snapshot immutable/read-only inside the common boundary, make it the child CWD/workspace, and refuse if any live original remains visible in CWD, argv, prompt/context, environment, mounted config, or tool policy. A review bundle may accompany the snapshot but cannot replace repository or approved-context material the review contract requires. |
| SL-1.4 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py` | credential/tool isolation matrix | Build a review-only environment and route policy from explicit allowlists. Every executable product or advisor review route uses the one OS-enforced contained boundary frozen below; route-specific flags are defense in depth, not substitutes. Put subscription tokens, API keys, gateway credentials, and provider headers only in a launcher-owned least-scope transport broker outside reviewer context; reviewer prompt, tool namespace, argv, environment, snapshot, home/config, logs, and model-visible payloads remain secret-free. Preserve only read/search/reviewer-subprocess capability plus the exact brokered first-party transport. Make the sidecar own validation and metadata-only propagation of `review_boundary_attestation.v1`, and make the launcher compare its expected snapshot/provenance digest, tool-policy digest, session identity, and boundary identity before Channel send. Return a typed non-human route refusal `review_gate_block` before launch/send when any adapter, broker, gateway, native host, or sidecar cannot prove the boundary and direct probes; if persisted in a closeout, normalize it to `blocker_class=contract_bug`, not a new blocker-class literal. A refused route cannot count toward registry coverage or `EC-HARDEN-5`. |
| SL-1.5 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | complete live review-route registry and isolation | Produce one normalized route registry from every `capability_registry()` record supporting `review` (including command/manual and Claude route/mode expansion) and every Advisor Board route expressible through the live harness/compatibility registries, auth lanes, provider backings, native-host state, scoped-research state, and live Omnigent catalog. For every executable homebrew subscription, opted-in API-key, Omnigent, command-adapter, native-host, and other reachable route, apply the same immutable snapshot, OS boundary, secret-free reviewer context, least-credential broker, and direct side-effect probes; refuse before launch when an equivalent attestation cannot be proved. Manual/nonlaunch remains an evidenced non-executable row. Compare normalized registry keys with checklist keys by exact set equality so additions, omissions, duplicates, and a refused/unproved row marked satisfied fail closed. This hardens supported dormant/other routes without authorizing them for this coordinated v10 run: its exact four-seat plan/code/advisor panels remain first-party subscription-only. |
| SL-1.6 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | crash/recovery cleanup | Journal exact run-owned stage, home, config, and context roots before child launch; clean them on normal return, resolver failure, timeout, interrupt, and next-run recovery after parent crash; never infer ownership from basename, glob, or a live path. |
| SL-1.7 | verify | SL-1.2, SL-1.3, SL-1.4, SL-1.5, SL-1.6 | all `SL-1` owned source paths | complete review matrix | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py -q` |

The exact current product-loop matrix is sixteen cells, but it is only one
projection of the live review-capability registry. The test derives normalized
route keys from `capability_registry()`, Claude route/mode registries, the
Advisor Board harness/compatibility/auth/backing registries, native-host and
scoped-research state, and the live Omnigent catalog. Exact set equality with
the checklist means any newly reachable route fails closed until it has
equivalent evidence. Each table posture below is additive to the common
immutable-snapshot, OS-boundary, credential-broker, and direct-probe contract.

| Executor / surface | Current review cells | Required route posture |
|---|---|---|
| codex CLI | codex | contained snapshot as `--cd` and process CWD; `--sandbox read-only`, `--ignore-user-config`, and `--skip-git-repo-check`; no live path |
| Claude print | solo, subagent, agent-team | contained snapshot as `--add-dir` and process CWD; `permission-mode=plan`; remove Edit/MultiEdit/Write and privileged collaboration tools |
| Claude Channel | solo, subagent, agent-team | `claude_channel_sidecar.py` validates and exposes a `review_boundary_attestation.v1` bound to exact session ID, canonical snapshot/provenance digest, read-only tool-policy digest, and launcher boundary identity; the launcher compares it before send. Missing, stale, mismatched, or unverified attestation blocks before send. The bearer token remains in the parent sidecar client and never enters reviewer context/environment |
| Claude Agent View | solo, subagent, agent-team | launch against the contained snapshot with plan permission and the same read/search-only tool contract; otherwise block |
| gemini/agy | gemini | contained snapshot as `--add-dir` and process CWD; no `--dangerously-skip-permissions` |
| grok CLI | grok | contained snapshot CWD plus exact `read_file,grep,list_dir,search_tool` allowlist; no bypass permission or write/terminal tools |
| OpenCode CLI | opencode | contained snapshot as `--dir` and process CWD; explicit read-only review agent and no dangerous permission bypass |
| Pi Agent | pi | contained snapshot as `--repo`; run-owned config/home; explicit read/search/reviewer-subprocess policy; no runner-ledger/global-scheduler tools |
| command adapter | command | execute only when the typed adapter declares and proves the common boundary, immutable snapshot, secret-free transport, tool, probe, and cleanup contract; an arbitrary command template blocks |
| manual | manual/nonlaunch | remain dry-run/manual-handoff only; prove no child, credential, workspace, or side effect is created |
| Advisor Board homebrew | every registry-expressible homebrew harness/auth/native-host/research route | subscription and opted-in API-key variants use the same boundary and parent credential broker; no API key or subscription secret reaches the reviewer context |
| Advisor Board Omnigent | every registry-expressible seat whose harness is in the live Omnigent catalog, across supported auth/research variants | require gateway-issued equivalent boundary/snapshot/probe attestation bound to the exact route and provenance digest; no attestation means refusal before session creation |

`External review boundary` has one frozen meaning for every executable product
or advisor review route: a launcher-owned OS-enforced contained sandbox, or an
adapter/gateway-native boundary proven equivalent by the same attestation, not a
prompt convention or route-specific CLI flag. It gives the reviewer a private
mount view in which the immutable review snapshot is readable and only
journaled run-owned home/config/temp roots are writable; the live repository,
live context-ref originals, host home/config, credential stores/helpers, secret
sockets, and unrelated host paths are not mounted or reachable. The reviewer
CWD is the snapshot, its environment is the allowlist below, and network egress
is denied except through the parent-owned exact-provider transport broker.
Before launch or remote session creation, the launcher must verify a
`review_boundary_attestation.v1` containing the boundary ID, normalized route
key, optional session ID, canonical snapshot root and provenance digest,
process CWD, mounted-root set and modes, environment-key set, tool-policy
digest, provider-transport allowlist, direct-probe digest, and
`live_repo_absent=true`, `live_context_refs_absent=true`, and
`reviewer_context_secret_free=true`. A host, command adapter, API-key lane,
Omnigent gateway, native-host route, sidecar, or other adapter that cannot
construct and attest this boundary is refused before launch and cannot count;
it cannot degrade to staged CWD, prompt instructions, canaries, CLI permission
flags, or an existing backing contract alone.

The review child environment is allowlist-built, not ambient-env-minus-a-few
keys. It may contain `PATH`, `LANG`, `LC_*`, `TERM`, `TMPDIR`, `USER`, `SHELL`,
`PHASE_LOOP_CHILD`, non-secret runner correlation IDs, run-local `HOME`,
`XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `GNUPGHOME`,
`DOCKER_CONFIG`, and a non-secret locator for the exact parent-owned provider
transport broker. Subscription tokens, API keys, gateway credentials, provider
headers, and other secrets never enter this environment.
`PHASE_LOOP_CLAUDE_CHANNEL_BEARER_TOKEN` may be consumed only by the loopback
parent-side client.

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
`curl`, `npm`, `twine`, cloud CLI, and `op` canaries. It proves each attempted
live-tree write/delete, git commit/tag/config, HTTPS/SSH push, GitHub mutation,
package publish, cloud mutation, secret retrieval, and non-provider network
side effect enters the intended probe but is denied before the canary records a
side effect. It runs those direct probes for every executable normalized route,
including API-key and Omnigent variants; a missing probe, refusal counted as
success, or route/checklist set mismatch fails. No real external mutation is
performed.

### SL-2 — Reconcile, goal-coverage, interpreter, and runner sequencing hardening

- **Scope**: Make main-loop attribution CWD-independent, enforce non-vacuous goal declarations on every completion path, close both `Consiliency/agent-harness#241` login-shell bypass classes, and add the capability marker plus fail-closed fresh-process/post-suite lifecycle.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`
- **Interfaces provided**: `path-and-verification-hardening`, `HARDEN-capability-v1`, `fresh-process-exact-head-handoff`, `runner-owned-post-suite-reduction`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-RED-evidence`, `HARDEN-post-suite-sequencing-contract`
- **Parallel-safe**: yes
- **Tasks**:
  - test: Confirm the `SL-2.1` reconcile, goal, interpreter, and runner-sequencing selectors remain frozen from `SL-0`.
  - impl: Implement CWD-independent attribution, enforced goal coverage, interpreter guards, the production capability marker, and fresh-process/post-suite sequencing in `SL-2.2`–`SL-2.5`.
  - verify: Run the immutable 22-nodeid HARDEN suite with default activation and zero skips in `SL-2.6`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | all `SL-0` reconcile, goal, interpreter, and evidence-verifier test paths, read-only | frozen non-review and runner-sequencing selectors | Confirm every selector and blob ID is unchanged from the `SL-0` commit before implementation. |
| SL-2.2 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py` | CWD-independent attribution | Require persisted repo/roadmap identity fields to be absolute before matching; retain relocated absolute-root equivalence only through identical repo-relative roadmap subpaths and existing SHA provenance. Resolve relative `automation.artifact` against the trusted absolute stored repo, never ambient CWD; reject escape, tilde, symlink-rebind, malformed, and mismatched identities without crashing the main loop. |
| SL-2.3 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py` | enforce completion matrix | Return a typed declaration state that distinguishes declared IDs, syntactically valid all-bare legacy, zero match, ambiguous match, parse failure, and missing plan. Warn/default mode is the only nonblocking legacy path. Under `PHASE_LOOP_ACCEPTANCE_ENFORCE=block`, every state with zero declared EC-IDs—including valid all-bare legacy—and every ambiguous, unparseable, or missing-plan state returns non-human `contract_bug` at preflight, canonical closeout, delegated/resume completion, and missing-plan closeout. Distinct classification must never become an enforce pass-through. |
| SL-2.4 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` | Bash/profile bypass matrix | Model and consume `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, and `--init-file file`/`--init-file=file` before locating the true `-c`; preserve combined login flags; fail closed on missing option arguments, ambiguous `--`, or an unlocatable payload. Under patch-level bounds, conservatively shadow nominal version names absent at resolve time so a profile cannot introduce an unsupported patch after shim construction; emit a clear warning for the conservative block. |
| SL-2.5 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` | capability activation, fresh-process handoff, post-suite reduction, and final audit | Install literal `HARDEN_CAPABILITY_VERSION = 1` in `verification_evidence.py`; this is the only production activation read by the frozen guard. Parse the HARDEN lifecycle/post-suite contract separately from `## Verification` and `automation.suite_command`. When the implementation child changes any runner/reducer surface loaded by the current process, that process may verify ownership, freeze one clean candidate commit, push it, and persist a runner-owned `harden_restart_handoff.v1`, but must then stop with nonterminal `awaiting_phase_closeout`. The handoff binds process PID/start nonce, startup HEAD and loaded module SHA-256 values, candidate head/tree/remote ref, plan/roadmap/manifest/test-guard/test-tree digests, and the requirement for a new process. On `resume`, fail closed unless a new process proves distinct PID/nonce, clean repo, local HEAD = fetched remote candidate head, and loaded repo-local runner/reducer module digests = that exact head. Only this candidate process may run verification, panel, reduction, and candidate audit. It must stop after a passed candidate audit; it cannot survive merge and attest canonical main. A second distinct process must prove clean local HEAD = fetched server canonical-main head and matching loaded repo-local module digests before post-landing verification. Persist both process identities, exact verifier argv/exit, and verification/log/JUnit/checklist/evidence paths and SHA-256 values in parent-owned launch/state/event metadata. Treat a same-process cycle, stale/wrong head or module, pre-seal call, missing output, forged hash/identity, non-zero reducer, or audit mismatch as non-human `repeated_verification_failure`. No child/model closeout can override these gates. |
| SL-2.6 | verify | SL-2.2, SL-2.3, SL-2.4, SL-2.5 | all `SL-2` owned source paths and frozen `SL-0` tests read-only | immutable active HARDEN suite | With `PHASE_LOOP_TDD_EXPECT_HARDEN` absent, run `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py phase-loop-runtime/tests/test_reconcile_portability_85c.py phase-loop-runtime/tests/test_goal_coverage.py phase-loop-runtime/tests/test_verification_interpreter_guard_221.py phase-loop-runtime/tests/test_harden_evidence_verifier.py -q --junitxml=<run-dir>/harden-phase-focused.xml`. The production marker must activate the exact 22-nodeid inventory automatically and JUnit must report exactly 22 passed, zero skipped, zero xfailed, and zero errors before any candidate is frozen. |

### SL-3 — Fresh-process candidate/post-landing evidence and documentation reducer

- **Scope**: Add the fail-closed HARDEN chronology/evidence executable, synthesize the changelog note, freeze/push the implementation candidate, and drive the read-only fresh-process candidate and post-landing lifecycle.
- **Owned files**: `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- **Interfaces provided**: `HARDEN-closeout-evidence`, `HARDEN-no-spec-delta`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-RED-evidence`, `review-isolation-boundary`, `review-fleet-checklist-evidence`, `path-and-verification-hardening`, `HARDEN-capability-v1`, `fresh-process-exact-head-handoff`, `runner-owned-post-suite-reduction`
- **Parallel-safe**: no
- **Tasks**:
  - test: Confirm and run the frozen evidence-verifier, manifest, and fresh-process fixtures RED in `SL-3.1`.
  - impl: Add the chronology/evidence verifier and changelog note in `SL-3.2`–`SL-3.3`.
  - verify: Freeze/push the implementation candidate, terminate the stale implementation process, and complete the candidate and post-landing fresh-process gates in `SL-3.4`–`SL-3.5`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py` (read-only) | verifier, manifest, process-lifecycle, and ordered-parent fixture/mutation suite | Confirm the frozen guard/tests and blob IDs match `SL-0`; run every nodeid/case RED before creating the executable. |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/scripts/verify_harden_evidence.py` | candidate/post-landing chronology and evidence verifier | Add an executable shebang script with explicit `--lifecycle-stage candidate|post_landing`. Both stages require parent-supplied run directory, sealed `verification.json`, structured broad-suite JUnit, runner-reduced fleet checklist, output path, plan, roadmap, phase, repository, restart handoff, and exact process/head/module identities. Candidate mode writes only `harden-candidate-evidence.json`; post-landing mode additionally requires and revalidates the candidate evidence/hashes and writes only final `harden-evidence.json`. It derives Git/forge ancestry, ordered parents, PR lifecycle, path ownership, manifest state, nodeid/skip state, and evidence identity; exits non-zero with typed findings for any missing, mismatched, self-reported-only, stale-process/run/head, one-parent/squash/rebase merge, or forged obligation; and never discovers another run, trusts CLI booleans/counts, runs as an ordinary suite command, amends `verification.json`, or writes tracked files. |
| SL-3.3 | impl | SL-3.1 | `CHANGELOG.md` | Unreleased note | Add one concise Unreleased note covering contained review staging/fleet isolation, CWD-independent reconcile attribution, non-vacuous enforce goal coverage, and login-shell interpreter hardening. Do not edit roadmap/spec/contract/version/release-pin surfaces. |
| SL-3.4 | verify | SL-3.2, SL-3.3 | all phase-owned paths plus canonical runner evidence, read-only | frozen pushed candidate and fresh exact-candidate proof | The implementation process freezes one clean commit, pushes it, persists the restart handoff, and exits. A distinct repo-local process starts with `PYTHONPATH=phase-loop-runtime/src` at that exact fetched head, proves its loaded modules match it, runs every `## Verification` command and the frontmatter broad suite, seals/validates `verification.json`, and only then runs the four-vendor implementation panel against the exact candidate diff/head. With all seats usable and no material finding, it reduces fleet/candidate evidence, audits it, records nonterminal `candidate_audit=passed`, and exits. Any change or material finding creates a new candidate and repeats the entire fresh-process gate; this process never repairs and then self-attests a changed head. Merge is forbidden until this gate passes. |
| SL-3.5 | verify | SL-3.4 | all phase-owned paths plus candidate and canonical-main runner evidence, read-only | exact two-parent landing and fresh canonical-main proof | Merge the exact reviewed candidate with the required two-parent topology, terminate the candidate process, fetch the server default branch, and start another distinct repo-local process at the exact clean canonical-main head with repo-local modules loaded from it. Repeat manifest/plan/roadmap validation, focused and broad compatible suites, Ruff, exact-head four-vendor review, post-suite fleet/final reduction, and parent audit. Its structured JUnit must contain all 22 frozen phase nodeids exactly once with zero skipped. Only this process may emit terminal `complete`, and only after it verifies the ordered two-parent tests and implementation merges plus the complete lifecycle below. |

`verify_harden_evidence.py` accepts only the fresh parent process's canonical
current HARDEN run directory and parent-materialized inputs beneath it. It never
discovers another run or trusts a path, count, digest, boolean, process identity,
or Git/forge identity supplied only by model output. Candidate and post-landing
stages must jointly prove all of the following from Git, server-returned forge
metadata, process startup records, and sealed runner artifacts:

1. The exact plan digest received a four-vendor phase-plan review with Fable and
   Sol usable, four actual reviewing seats, and no unresolved material finding.
   The exact test/guard digest received the same panel before tests landed.
2. The unique HARDEN row in `plans/manifest.json` passes structural and
   per-entry validation and exactly names this plan, phase, roadmap, and
   `SL-0`–`SL-3`. Malformed JSON, a bad sibling row, missing/duplicate HARDEN
   row, or stale file/alias/roadmap/lane metadata is a typed failure. The
   manifest command appears in both frontmatter and `## Verification`, and its
   sealed command result is required at both exact heads.
3. `harden_tdd_guard.py` and all six phase test files have the landed tests-only
   blob IDs. The guard's literal inventories are exactly 22 expected nodeids,
   17 default skips, and 5 migrated legacy branches. The tests-only default
   JUnit is exactly 5 passed/17 skipped with the exact skip set. Activated RED
   collection is the same 22; every nodeid and every frozen case has intended
   assertion-failure raw output and JUnit with zero skip/xfail/collection/setup
   errors. Candidate and post-landing JUnit each contain the same 22 exactly
   once, all passed, zero skipped.
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
   phase-plan panel → tests/guard panel → tests PR merge `TM` → default
   5-pass/17-skip proof → activated raw RED completion → implementation branch
   creation → production commits → clean candidate `I` freeze/push →
   implementation process exit → distinct candidate process startup at `I` →
   candidate manifest/focused/broad/Ruff seal → exact-`I` implementation panel
   → candidate reduction/audit → candidate process exit → implementation PR
   merge `M` → distinct post-landing process startup at `M` → post-landing
   manifest/focused/broad/Ruff seal → exact-`M` panel → final reduction/audit →
   terminal `complete`. Each event carries parent-observed time, prior-event
   hash, plan/test/candidate digest, and server object IDs; absent, duplicate,
   out-of-order, or post-dated evidence fails.
7. The implementation, candidate-verification, and post-landing processes have
   distinct runner-recorded PID/start nonce values. The candidate process's
   startup/loaded HEAD is exactly `I`; the post-landing process's is exactly
   `M`; their repo-local `cli.py`, `runner.py`, `verification_evidence.py`, and
   verifier bytes hash to the corresponding Git blobs. The implementation
   process may only create the restart handoff. A process that changes or
   checks out a new head after startup must exit and can attest neither head.
8. All source/script/changelog changes use the one coordinator-recorded author
   vendor. The broad compatible suite and all ordinary verification commands
   seal green before either exact-head implementation panel. Author-vendor
   seats are advisory only and the non-author seats satisfy governed quorum.
   A finding/fix changes `I`, invalidates its seal/panel/audit, and forces a new
   commit/push plus a new exact-head process.
9. The launcher-owned immutable-snapshot manifest covers the exact candidate
   Git tree and every approved context ref, preserves logical labels, and proves
   source/destination path, kind, bytes, and SHA-256 equality. Positive controls
   open candidate code and context refs only through rewritten contained paths;
   negative controls prove live originals unreachable and unmodifiable.
10. Every normalized live product-plus-advisor review route has
    runner-observed executable/refused/nonlaunch status, CWD/snapshot/tool/env
    evidence, common OS-boundary and least-credential-transport attestation,
    route-specific sidecar/gateway evidence, direct probes, and cleanup.
    Checklist and registry keys are exactly equal; refused/unproved executable
    rows cannot count. The coordinated panels separately prove first-party
    subscription-only routing.

Candidate mode writes only
`.phase-loop/runs/<candidate-run-id>/harden-candidate-evidence.json`; post-landing
mode writes only `.phase-loop/runs/<main-run-id>/harden-evidence.json`. Each
fresh parent creates its own `harden-compatible-suite.xml`,
`harden-fleet-checklist.json`, verification artifact, and parent audit record.
The post-landing parent copies the candidate evidence/handoff into its run-owned
input area only after verifying the candidate parent's recorded SHA-256, then
revalidates all candidate bytes and server identities. Missing evidence is a
failed criterion, never an operational exemption.
`Consiliency/agent-harness#361` may record a standing residual but cannot turn
`EC-HARDEN-5` green.

## Fresh-Process Exact-Head Verification and Landing

This is a three-process, two-seal protocol. `automation.suite_command` and
commands extracted from `## Verification` are pass-1 verification inside each
fresh verifier process; no ordinary command may invoke
`verify_harden_evidence.py`, read an unsealed current-run artifact, or claim
post-suite output as suite evidence.

1. The implementation process finishes `SL-1`–`SL-3` writes, runs the immutable
   focused phase tests, freezes one clean candidate commit, pushes its exact
   branch/head, and atomically persists `harden_restart_handoff.v1`. Because its
   startup modules predate those bytes, it is prohibited from running the
   implementation panel/reducer/audit, merging, or completing. It exits and the
   coordinator proves its PID/lock is gone.
2. The candidate verifier is launched as a new repo-local phase-loop process
   with this command shape after checking out the exact fetched pushed head:

   `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli resume --repo . --roadmap specs/phase-plans-v10.md --phase HARDEN --governed --closeout-mode manual --max-phases 1`

   Startup fails closed unless the worktree is clean, local HEAD equals the
   handoff and remote candidate object `I`, repo-local module hashes equal `I`,
   and PID/start nonce differs from the implementation process.
3. The candidate parent sets `PHASE_LOOP_RUN_DIR`, records
   `verification_stage=pre_seal`, runs dependency refresh, every ordinary
   command, and the exact frontmatter manifest-plus-broad suite. The broad gate
   is every compatible `phase-loop-runtime/tests` test under
   `not dotfiles_integration`; it has no HARDEN `-k` or nodeid exclusion.
   Only post-landing operational evidence wrappers—not compatible unit or
   integration tests—remain for the post-merge stage. The parent seals and
   validates `verification.json` and JUnit before running the exact-`I`
   four-vendor implementation panel. Any suite or panel failure blocks merge.
4. After a clean panel, the candidate parent reduces
   `harden-fleet-checklist.v1`, invokes:

   `phase-loop-runtime/scripts/verify_harden_evidence.py --lifecycle-stage candidate --repo . --roadmap specs/phase-plans-v10.md --plan plans/phase-plan-v10-HARDEN.md --phase HARDEN --run-dir <candidate-run-dir> --verification-json <candidate-run-dir>/verification.json --junit-xml <candidate-run-dir>/harden-compatible-suite.xml --fleet-checklist <candidate-run-dir>/harden-fleet-checklist.json --restart-handoff <candidate-run-dir>/harden-restart-handoff.json --output <candidate-run-dir>/harden-candidate-evidence.json`

   and performs a parent-owned candidate audit. Passed candidate audit records
   `awaiting_phase_closeout`, never `complete`. A fix requires a new candidate,
   invalidates all old exact-head evidence, and restarts at step 1.
5. After the candidate process exits, merge only exact `I` with the ordered
   two-parent topology above. Fetch server canonical main and prepare a clean
   worktree at exact `M`; do not reuse a process or interpreter that loaded `I`.
   Launch the same repo-local `resume` command shape as a new process. Startup
   fails closed unless local HEAD and loaded modules equal fetched server `M`,
   the merge parents are `[P, I]`, and PID/nonce differs from both earlier
   processes.
6. The post-landing parent repeats manifest, plan, roadmap, focused, broad
   compatible, Ruff, seal/JUnit validation, and a four-vendor exact-`M` panel.
   It reduces a new fleet checklist and invokes:

   `phase-loop-runtime/scripts/verify_harden_evidence.py --lifecycle-stage post_landing --repo . --roadmap specs/phase-plans-v10.md --plan plans/phase-plan-v10-HARDEN.md --phase HARDEN --run-dir <main-run-dir> --verification-json <main-run-dir>/verification.json --junit-xml <main-run-dir>/harden-compatible-suite.xml --fleet-checklist <main-run-dir>/harden-fleet-checklist.json --restart-handoff <main-run-dir>/harden-restart-handoff.json --candidate-evidence <main-run-dir>/harden-candidate-evidence.json --output <main-run-dir>/harden-evidence.json`

7. The parent-owned `_audit_harden_post_suite_outputs()` re-opens both seals,
   both JUnit files, both checklists/evidence records, the restart handoff, and
   server metadata; recomputes every hash, exact digest, process/head/module
   identity, ordered parent, registry set, nodeid count/status, and lifecycle
   edge; and matches them to parent state. Missing outputs return
   `post_suite_output_missing`; changed bytes/hashes return
   `post_suite_hash_mismatch`; stale process/run/head/plan/roadmap/manifest/
   test/registry/cross-file identity returns `post_suite_identity_mismatch`;
   one-process verification returns `self_verification_cycle`; wrong merge
   parents return `harden_merge_parent_mismatch`; and early completion returns
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

- Before any test work, panel the exact SHA-256 of this plan with Fable 5,
  GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5. Fable and Sol are mandatory
  reviewing seats; a degraded 3-of-4 result blocks.
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
- The implementation process is only a candidate producer. Once it commits and
  pushes any changed runner/reducer byte, it must write the restart handoff and
  exit. The fresh exact-candidate process runs the complete compatible suite
  before the implementation panel or merge. The candidate process exits before
  merge, and a second fresh exact-canonical-main process repeats the gate after
  merge. A repair, checkout, or commit in either verifier process invalidates
  its evidence and requires another fresh process.
- Execute, repair, plan, roadmap, and maintain-skills behavior are positive
  controls. Review-only CWD/environment/tool/auth changes must not leak into
  another product action.
- A reviewer subprocess or shell inside the external review boundary is
  permitted. A live-repo mutation, credentialed/privileged side effect,
  live-root reachability, ambient credential source, or unjournaled cleanup
  path is forbidden.
- The phase produces no visible avatar/browser-media render;
  `visual_render_declared` remains false and image evidence is not required.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`, `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-HARDEN.md`, `plans/manifest.json`, `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py`, `phase-loop-runtime/tests/test_reconcile_portability_85c.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py`, `.phase-loop/events.jsonl`, `.phase-loop/runs/**/verification.json`, `.phase-loop/runs/**/harden-compatible-suite.xml`, `.phase-loop/runs/**/launch.json`, `.phase-loop/runs/**/terminal-summary.json`, `.phase-loop/runs/**/harden-restart-handoff.json`, `.phase-loop/runs/**/harden-fleet-checklist.json`, `.phase-loop/runs/**/harden-candidate-evidence.json`, `.phase-loop/runs/**/harden-evidence.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-HARDEN.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import read_manifest, validate_manifest; p = Path("plans").joinpath("manifest.json"); v = validate_manifest(p); assert v.valid, "; ".join(v.errors); plan_file = Path("plans").joinpath("phase-plan-v10-HARDEN.md").as_posix(); roadmap_file = Path("specs").joinpath("phase-plans-v10.md").as_posix(); matches = [e for e in read_manifest(Path(".")).plans if e.file == plan_file]; assert len(matches) == 1, f"expected one HARDEN manifest row, got {len(matches)}"; e = matches[0]; actual = (e.phase_alias, e.roadmap_ref.file if e.roadmap_ref else None, e.lanes); expected = ("HARDEN", roadmap_file, ("SL-0", "SL-1", "SL-2", "SL-3")); assert actual == expected, f"stale HARDEN manifest row: {actual!r}"'`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -k "stage_review_tree_is_gitignore_aware_working_tree_copy or resolve_codex_review_stage_materializes_then_cleans or panel_leg_review_dir_never_contains_the_repo or legacy_no_ids_no_evidence_no_block or unresolvable_plan_legacy_does_not_block or review_stage_rejects_every_escape_form_before_launch or review_isolation_registry_matrix or review_capability_registry_set_equality or every_executable_review_route or review_snapshot_materializes or claude_channel_requires_matching_sidecar_review_attestation or review_stage_crash_recovery or review_prompt_argv_cwd_and_env or reconcile_main_loop_paths_are_cwd_independent or relative_automation_artifact_is_repo_anchored or goal_coverage_enforce_blocks_every_zero_declared or goal_coverage_all_bare_legacy_is_distinct or argument_consuming_bash_options_and_profile_patch_version_fail_closed or harden_evidence_verifier or harden_fresh_process_lifecycle or harden_manifest_gate"`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `ruff check phase-loop-runtime/src/phase_loop_runtime phase-loop-runtime/scripts`
- `git diff --check`
- `git diff --cached --check`

The frontmatter `automation.suite_command` is an executable fail-fast composite:
it first validates the entire phase-plan manifest and unique HARDEN row, then
runs the broad compatible suite with structured JUnit in the parent-supplied
run directory. It runs after extracted commands and before the fresh parent
creates that run's seal. Candidate and post-landing processes both run it before
their exact-head panel. HARDEN chronology, raw RED, author independence,
crash cleanup, and fleet evidence become decidable only through the two
post-suite reductions and fresh-parent audits above; they must never be
represented as pre-seal suite evidence.

## Acceptance Criteria

- [ ] EC-HARDEN-0 — proven by the frozen guard's default 5-pass/17-skip JUnit, activated 22-nodeid and per-case raw intended-RED/JUnit records, candidate `--lifecycle-stage candidate` evidence, post-landing `--lifecycle-stage post_landing` evidence, and passed fresh-parent `_audit_harden_post_suite_outputs()`; the audit must prove immutable tests/guard, exact manifest validation, the ordered two-parent tests and implementation merges, implementation PR range excluding every `SL-0` path and tests-only commit, distinct implementation/candidate/main process identities and exact loaded heads/modules, broad compatible suite before each exact-head panel, and the lifecycle tests merge → activated RED → candidate freeze/push → old-process exit → fresh candidate suite/panel/audit → merge → fresh canonical-main suite/panel/final audit → terminal complete
- [ ] EC-HARDEN-1 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py -q -k review_stage_rejects_every_escape_form_before_launch`
- [ ] EC-HARDEN-2 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_reconcile_portability_85c.py -q -k "cwd_independent or repo_anchored"`
- [ ] EC-HARDEN-3 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_goal_coverage.py -q -k "enforce_blocks_every_zero_declared or all_bare_legacy_is_distinct"`; both selected tests must pass, and the all-bare test must prove warn/default is nonblocking while every enforce completion gate returns non-human `contract_bug`
- [ ] EC-HARDEN-4 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_verification_interpreter_guard_221.py -q -k argument_consuming_bash_options_and_profile_patch_version_fail_closed`; the selector must enumerate `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, and `--init-file file`/`--init-file=file`
- [ ] EC-HARDEN-5 — proven jointly by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py -q -k "review_isolation_registry_matrix or review_capability_registry_set_equality or every_executable_review_route or review_snapshot_materializes or review_prompt_argv_cwd_and_env or crash_recovery"` and the passed runner-owned post-suite final audit; every executable product/advisor route must prove the equivalent common boundary, immutable candidate/context-ref snapshot, secret-free credential transport, and direct probes or be refused before launch and excluded from satisfaction; checklist/live-registry set equality and parent-recorded hashes/identities are exact, and no residual register, pre-seal suite result, or self-reported closeout field is a satisfaction route
