---
phase_loop_plan_version: 1
phase: HARDEN
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 1e8ea70ceae55d326cd84b092e1b9e879180d7b0e774140c3dd00e6ed63b7071
automation:
  suite_command: ["bash", "-lc", "set -euo pipefail; harden_junit=\"${PHASE_LOOP_RUN_DIR:+$PHASE_LOOP_RUN_DIR/harden-compatible-suite.xml}\"; if [[ -z \"$harden_junit\" ]]; then harden_junit=\"$(mktemp \"${TMPDIR:-/tmp}/harden-bootstrap-suite.XXXXXX.xml\")\"; fi; PYTHONPATH=phase-loop-runtime/src python3 -c 'import hashlib, json; from pathlib import Path; from phase_loop_runtime.plan_manifest import validate_manifest; p = Path(\"plans\").joinpath(\"manifest.json\"); plan_file = Path(\"plans\").joinpath(\"phase-plan-v10-HARDEN.md\"); roadmap_file = Path(\"specs\").joinpath(\"phase-plans-v10.md\"); v = validate_manifest(p); assert v.valid, \"; \".join(v.errors); doc = json.loads(p.read_text()); rows = [r for r in doc[\"plans\"] if r.get(\"slug\") == \"v10-HARDEN\" or r.get(\"file\") == plan_file.as_posix() or r.get(\"phase_alias\") == \"HARDEN\"]; assert len(rows) == 1, f\"expected one HARDEN identity row, got {len(rows)}\"; r = rows[0]; assert (r.get(\"slug\"), r.get(\"file\"), r.get(\"phase_alias\"), (r.get(\"roadmap_ref\") or {}).get(\"file\"), r.get(\"lanes\")) == (\"v10-HARDEN\", plan_file.as_posix(), \"HARDEN\", roadmap_file.as_posix(), [\"SL-0\", \"SL-1\", \"SL-2\", \"SL-3\"]); events = r.get(\"lifecycle\"); assert isinstance(events, list) and events; bearing = [e for e in events if isinstance(e, dict) and isinstance(e.get(\"metadata\"), dict) and (\"harden_plan_contract\" in e[\"metadata\"] or \"harden_plan_contract_record_id\" in e[\"metadata\"])]; assert len(bearing) == 1, f\"expected one HARDEN contract-bearing record, got {len(bearing)}\"; event = bearing[0]; assert events[0] is event and event.get(\"transition\") == \"committed\" and event.get(\"by\") == \"codex-plan-phase\"; metadata = event[\"metadata\"]; assert metadata.get(\"harden_plan_contract_record_id\") == \"v10-HARDEN.harden-plan-contract.v1\"; c = metadata.get(\"harden_plan_contract\"); assert isinstance(c, dict); transitions = [e.get(\"transition\") for e in events]; assert transitions in ([\"committed\"], [\"committed\", \"executing\"], [\"committed\", \"executing\", \"completed\"]), transitions; assert r.get(\"status\") == transitions[-1] and r.get(\"updated_at\") == events[-1].get(\"at\"); executing = [e for e in events if e.get(\"transition\") == \"executing\"]; assert len(executing) == (0 if transitions == [\"committed\"] else 1); assert not executing or (executing[0].get(\"by\") == \"codex-execute-phase\" and executing[0].get(\"metadata\", {}).get(\"phase_alias\") == \"HARDEN\" and isinstance(executing[0].get(\"metadata\", {}).get(\"run_id\"), str) and executing[0][\"metadata\"][\"run_id\"]); payload = {k: value for k, value in c.items() if k != \"plan_sha256\"}; assert hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(\",\", \":\")).encode()).hexdigest() == \"5b5c9bbe8fa97a343c831b5f4829df05305ea19f01d71fd1c5d4e9698f554982\"; digest = lambda xs: hashlib.sha256((chr(10).join(xs) + chr(10)).encode()).hexdigest(); assert c[\"plan_sha256\"] == hashlib.sha256(plan_file.read_bytes()).hexdigest(); assert c[\"roadmap_sha256\"] == hashlib.sha256(roadmap_file.read_bytes()).hexdigest() == \"1e8ea70ceae55d326cd84b092e1b9e879180d7b0e774140c3dd00e6ed63b7071\"; assert (len(c[\"owned_paths\"]), c[\"owned_paths_count\"], digest(c[\"owned_paths\"]), c[\"owned_paths_sha256\"]) == (25, 25, \"24ec10238f27645f38893625fc78f389bd6a97168d99c611f18cb2fab6a1d6d2\", \"24ec10238f27645f38893625fc78f389bd6a97168d99c611f18cb2fab6a1d6d2\"); assert (len(c[\"test_paths\"]), c[\"test_paths_count\"], digest(c[\"test_paths\"]), c[\"test_paths_sha256\"]) == (9, 9, \"c46927b02d8d3cfa41198aae1d8a3185728f8df1e8096083191976f02628fbc9\", \"c46927b02d8d3cfa41198aae1d8a3185728f8df1e8096083191976f02628fbc9\"); assert (len(c[\"checkpoint_paths\"]), c[\"checkpoint_paths_count\"], digest(c[\"checkpoint_paths\"]), c[\"checkpoint_paths_sha256\"]) == (14, 14, \"4ae07bb2a4b895f3d4a0f812b51bd3f3212d69569f1c536dff83e641470811dc\", \"4ae07bb2a4b895f3d4a0f812b51bd3f3212d69569f1c536dff83e641470811dc\"); assert (c[\"expected_nodeids\"], c[\"sl1_nodeids\"], c[\"sl2_nodeids\"], c[\"sl3_evidence_nodeids\"], c[\"default_skip_nodeids\"], c[\"nodeid_delta\"], c[\"nodeid_inventory_sha256\"]) == (24, 13, 7, 4, 19, 2, \"20f358e6a3482a773cb28ed78eb6fa8e49353e2425a5d182a282eb8d7afb4b8f\")' && PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -m \"not dotfiles_integration\" --junitxml=\"$harden_junit\""]
---

# HARDEN: Isolation and Verification Hardening

## Context

HARDEN closes the reachable review-isolation and verification gaps tracked by
`Consiliency/agent-harness#259`, `Consiliency/agent-harness#248`,
`Consiliency/agent-harness#264`, `Consiliency/agent-harness#246`, and
`Consiliency/agent-harness#241`. Live source inspection at
`9a7df7cafa651c20a9a6322e8eeaea4648de072b` confirms that review staging preserves
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

`plans/manifest.json` is a runner-owned lifecycle-control path outside every
HARDEN lane and outside the immutable 25/9/14 phase/test/checkpoint path sets.
This repaired planning package normalizes every current manifest row to the
exact sixteen-key shape emitted by `plan_manifest._entry_to_json()`: the sole
pre-repair exception, `v10-PROOFGATE`, receives only
`acceptance_criteria_count: null` and `task_summary: null`, with no lifecycle or
semantic change. That one-time normalization is part of the planning package,
not lifecycle-control PR `L` or `F`. Before dispatch, the coordinator requires
the frozen manifest pre-image to survive
`_manifest_to_json(read_manifest(repo))` with exact parsed row equality and
uses the real `update_lifecycle()` on a disposable copy to simulate the exact
`committed -> executing -> completed` HARDEN sequence. Each simulated step must
change only the API-defined HARDEN fields and must leave every parsed sibling
row exactly equal; any shape, optional-field, key, or value drift blocks before
`SL-0`.
After plan validation and before any `SL-0` write, the installed executor must
perform its normal
`update_lifecycle(repo, "v10-HARDEN", "executing", "codex-execute-phase",
{"run_id": <run-id>, "phase_alias": "HARDEN"})` call. The external coordinator
freezes the pre-image and permits exactly the API-defined delta: the unique
HARDEN row changes `status` from `committed` to `executing`, `updated_at`
equals the new event's `at`, and one `executing` event with that exact writer
and run identity is appended; every prior lifecycle event, immutable contract
record, unrelated row, and other field remains equal. While that delta is
unlanded, `plans/manifest.json` must be the only Git-visible dirty path and no
lane work may start. The coordinator commits it alone on a distinct control
branch, lands it through a manifest-only two-parent control PR, records the
server merge as `L`, fetches the exact post-`L` target, and proves the worktree
clean before the tests-only branch is created. A missing append, direct edit,
second append, wrong transition/writer/run identity, extra manifest change,
other dirty path, or failure to land `L` blocks before `SL-0`.

The immutable contract is not the latest lifecycle state. Its committed event
is located by metadata identity
`v10-HARDEN.harden-plan-contract.v1`; the lookup treats every event carrying
either that identity or `harden_plan_contract` as contract-bearing and requires
exactly one such event. Missing, duplicate, identity-conflicting, malformed, or
payload-drifted records fail closed. The frontmatter suite and the ordinary
manifest verification command use the byte-identical lookup and seal the
contract payload independently of mutable lifecycle status. A normal terminal
`completed` append, if reached after the exact-`M` final audit, is handled by
the same control-only rule on a distinct branch: the coordinator lands a
manifest-only two-parent closeout PR as `F`, proves `M..F` is exactly the
API-defined `executing -> completed` delta and that every runtime/code blob is
unchanged, and only then permits terminal `complete`. A failed execution stops
outside the successful `F` chronology and cannot claim completion.

The live standalone CLI calls `compose_review_board()` before `invoke_board()`,
and the composer can call each reachable capability record's `auth_ok()` while
selecting seats. HARDEN therefore treats pre-composition authorization as part
of the isolation boundary, not as an invoker-only concern. The CLI must obtain
an operation-bound isolation/broker authorization before it enters board
composition; `compose_review_board()` must validate that authorization—or
obtain the same authorization for a direct production caller—before it performs
an availability probe, capability-registry lookup, `auth_ok()` call, seat
construction, provider/subscription lookup, or other composition side effect.
The authorization is then carried into `invoke_board()`, which revalidates it
before artifact/context resolution, gateway/research discovery, subscription
access, provider routing, auth preflight, or launch. These invoker checks remain
defense in depth; they never substitute for the earlier CLI/composition gate.

The external coordinator also owns every mandatory four-seat plan,
implementation, and post-landing review. The pre-implementation plan and
tests-only panels necessarily predate the HARDEN boundary and are TDD/governance
preconditions only; they cannot be replayed or counted as post-implementation
isolation evidence. At exact implementation head `I` and exact canonical-main
head `M`, direct invocation of the current subscription subprocess routes is
forbidden. The coordinator instead launches the newly implemented repo-local
isolated-panel boundary from a clean worktree at that exact head. Fable, Sol,
Gemini, and Grok each run as a supported review-leg route: an untrusted
`linux_bwrap_v1` review environment sees only an immutable staged snapshot,
approved staged context refs, read-only tools, run-local scratch, and a typed
Unix inference socket; a distinct trusted parent control plane retains the
first-party subscription transport/auth and permits only the intended inference
RPC through an exact seat-specific broker adapter. API-key fallback remains
disabled.

`PanelRequest.context_refs` remains an input-routing API, not an isolation
primitive: every ref is copied and hash-verified before launch, and the review
leg sees only its contained `/review` destination. Prompts, ref names, CLI
flags, staged CWDs, and route labels cannot establish isolation. The four exact
`I`/`M` panel routes are normalized supported rows in the live route registry
and fleet checklist, carry direct mutation and credentialed-side-effect probe
attestations, and contribute to `EC-HARDEN-5`; they are not relabeled or
excepted as external governance. All other review routes satisfy the identical
boundary/transport contract or refuse before authentication lookup, session
creation, broker connection, or child launch.

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
the same immutable tests then activate the HARDEN branches by default.
`SL-1.8`, `SL-2.6`, and the clean checkpoint proof explicitly set
`PHASE_LOOP_TDD_EXPECT_HARDEN=1` so the interim lane gates are executable
independently of import timing. The final clean exact-`I` and exact-`M` proofs
remove that environment activation, require
`HARDEN_CAPABILITY_VERSION == 1`, and still require 24 passed with zero skips.
No production lane owns an `SL-0` test path. A correction to any frozen test or
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

The ownership inventory is exact and digest-bound. Each digest below is
SHA-256 over the listed repo-relative paths sorted bytewise, UTF-8 encoded, one
path per line, with a final newline:

- phase-owned paths: 25;
  `24ec10238f27645f38893625fc78f389bd6a97168d99c611f18cb2fab6a1d6d2`
- tests-only paths: 9;
  `c46927b02d8d3cfa41198aae1d8a3185728f8df1e8096083191976f02628fbc9`
- functional checkpoint `SL-1` + `SL-2` source paths: 14;
  `4ae07bb2a4b895f3d4a0f812b51bd3f3212d69569f1c536dff83e641470811dc`

The sole ownership exception is the runner-owned lifecycle-control path
`plans/manifest.json`. No `SL-*` lane owns or may edit, stage, or commit it, and
it is not added to any phase/test/checkpoint path inventory. The external
coordinator may admit only the exact `update_lifecycle` deltas above at the
explicit pre-`SL-0` and terminal control boundaries. At every lane, checkpoint,
candidate, and exact-`M` dirty-path gate the manifest must already be clean and
equal to the applicable server-landed control blob; treating arbitrary
manifest dirt as planning/control state is forbidden.

## Lanes

### SL-0 — Test contract, falsifiers, and panelled RED landing

- **Scope**: Land only the complete HARDEN regression/mutation test set, deterministic activation guard, and runner-owned RED evidence before any production, script, or changelog change.
- **Owned files**: `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_advisor_board_cli_legacy.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py`, `phase-loop-runtime/tests/test_reconcile_portability_85c.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py`
- **Interfaces provided**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-node-partition-contract`, `HARDEN-RED-evidence`, `HARDEN-post-suite-sequencing-contract`
- **Interfaces consumed**: `HARDEN-roadmap-obligations` (pre-existing), `HARDEN-live-source-anchors` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Freeze the guard, all `SL-0.1`–`SL-0.5` HARDEN regression/mutation selectors, the exact 24-nodeid inventory partitioned as 13 `SL-1` nodes + 7 `SL-2` nodes + 4 `SL-3` evidence nodes, the exact 19-nodeid default skip set, the five legacy assertion branches, and the fresh-process/manifest falsifiers.
  - impl: Land the tests-only commit and runner metadata in `SL-0.6`.
  - verify: Prove default-main compatibility plus activated per-selector/per-case RED and positive controls with raw and structured evidence in `SL-0.7`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_advisor_board_cli_legacy.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py` | guarded existing `test_panel_leg_review_dir_never_contains_the_repo`, guarded existing `test_stage_review_tree_is_gitignore_aware_working_tree_copy`, guarded existing `test_resolve_codex_review_stage_materializes_then_cleans`, `test_review_stage_rejects_every_escape_form_before_launch`, `test_review_isolation_registry_matrix_blocks_live_repo_and_privileged_side_effects`, `test_review_capability_registry_set_equality_covers_every_product_and_advisor_route`, `test_every_executable_review_route_requires_equivalent_contained_boundary_or_refuses_before_launch`, `test_review_snapshot_materializes_repo_and_context_refs_without_live_access`, `test_claude_channel_requires_matching_sidecar_review_attestation_before_send`, `test_review_stage_crash_recovery_removes_only_journaled_paths`, `test_review_prompt_argv_cwd_and_env_omit_live_repo`, `AuthAwareCompositionTests::test_harden_preflight_authorizes_before_every_capability_auth_ok`, `AdvisorBoardCliTest::test_cli_harden_preflight_authorizes_before_compose_and_invoke` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py -q` |
| SL-0.2 | test | — | `phase-loop-runtime/tests/test_reconcile_portability_85c.py` | `test_reconcile_main_loop_paths_are_cwd_independent`, `test_relative_automation_artifact_is_repo_anchored_not_cwd_anchored` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_reconcile_portability_85c.py -q -k "cwd_independent or repo_anchored"` |
| SL-0.3 | test | — | `phase-loop-runtime/tests/test_goal_coverage.py` | guarded existing `test_legacy_no_ids_no_evidence_no_block`, guarded existing `test_unresolvable_plan_legacy_does_not_block`, `test_goal_coverage_enforce_blocks_every_zero_declared_phase_at_every_completion_gate`, `test_goal_coverage_all_bare_legacy_is_distinct_warns_by_default_and_blocks_under_enforce` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_goal_coverage.py -q -k "legacy_no_ids_no_evidence_no_block or unresolvable_plan_legacy_does_not_block or enforce_blocks_every_zero_declared or all_bare_legacy_is_distinct"` |
| SL-0.4 | test | — | `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py` | `test_argument_consuming_bash_options_and_profile_patch_version_fail_closed` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_verification_interpreter_guard_221.py -q -k argument_consuming_bash_options_and_profile_patch_version_fail_closed` |
| SL-0.5 | test | — | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py` | `test_harden_evidence_verifier_rejects_each_missing_or_forged_obligation`, `test_harden_evidence_verifier_rejects_pretest_target_base_and_pr_range_tests`, `test_harden_fresh_process_lifecycle_rejects_self_wrong_head_or_non_two_parent_merge`, `test_harden_manifest_gate_rejects_malformed_or_stale_phase_entry` | `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_harden_evidence_verifier.py -q` |
| SL-0.6 | impl | SL-0.1, SL-0.2, SL-0.3, SL-0.4, SL-0.5 | all `SL-0` owned test paths only | frozen tests-only PR and landed commit | Only after the manifest-only lifecycle-control PR `L` has landed and the fetched target is clean, open and merge a tests-only PR into that exact target branch. It changes no source, executable, changelog, roadmap, manifest, or lifecycle-control path. Record server-returned tests-PR number, target/base/head ref names and object IDs, merge commit, merged time, exact test-tree blob IDs, and commit SHA; prove `L` is in the target ancestry and `plans/manifest.json` equals the landed `L` blob. Do not create or push the distinct implementation branch until the server reports the tests PR merged and its commit reachable from the target branch head. |
| SL-0.7 | verify | SL-0.6 | all `SL-0` owned test paths only | default skip/legacy proof, activated per-selector/per-case RED, landed-base topology, and positive controls | Fetch the server-recorded post-merge target head and prove the tests commit is its ancestor. With activation absent, require the exact five legacy nodeids to pass and the exact nineteen new nodeids—and no migrated nodeid—to skip. Then set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, collect exactly the same 24 nodeids, and run every nodeid plus every frozen `RED_CASES_BY_NODEID` case separately against that landed pre-implementation base. Require intended assertion failures with zero skip, xfail, collection, import, setup, or teardown errors; record raw stdout/stderr, asserted source anchor, applied mutation/case, exit status, and JUnit in canonical `.phase-loop/` evidence. The coordinator may create the implementation branch only after the guard's exact inventories, raw anchors, and positive controls pass this gate. |

`SL-0` is a complete tests-only landing, not an additive-selector landing.
`phase-loop-runtime/tests/harden_tdd_guard.py` is the single test-owned guard.
It freezes six literal, reviewable inventories:
`EXPECTED_PHASE_NODEIDS` (24 entries), `SL1_NODEIDS` (the 13 review/staging
nodes), `SL2_NODEIDS` (the 7 reconcile/goal/interpreter nodes),
`SL3_EVIDENCE_NODEIDS` (the 4 evidence/lifecycle nodes),
`DEFAULT_SKIP_NODEIDS` (19 entries), and `RED_CASES_BY_NODEID` (every
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

The exact inactive default skip set is the following nineteen new nodeids—no
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
- `phase-loop-runtime/tests/test_advisor_board_composition.py::AuthAwareCompositionTests::test_harden_preflight_authorizes_before_every_capability_auth_ok`
- `phase-loop-runtime/tests/test_advisor_board_cli_legacy.py::AdvisorBoardCliTest::test_cli_harden_preflight_authorizes_before_compose_and_invoke`
- `phase-loop-runtime/tests/test_reconcile_portability_85c.py::test_reconcile_main_loop_paths_are_cwd_independent`
- `phase-loop-runtime/tests/test_reconcile_portability_85c.py::test_relative_automation_artifact_is_repo_anchored_not_cwd_anchored`
- `phase-loop-runtime/tests/test_goal_coverage.py::test_goal_coverage_enforce_blocks_every_zero_declared_phase_at_every_completion_gate`
- `phase-loop-runtime/tests/test_goal_coverage.py::test_goal_coverage_all_bare_legacy_is_distinct_warns_by_default_and_blocks_under_enforce`
- `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py::test_argument_consuming_bash_options_and_profile_patch_version_fail_closed`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_evidence_verifier_rejects_each_missing_or_forged_obligation`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_evidence_verifier_rejects_pretest_target_base_and_pr_range_tests`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_fresh_process_lifecycle_rejects_self_wrong_head_or_non_two_parent_merge`
- `phase-loop-runtime/tests/test_harden_evidence_verifier.py::test_harden_manifest_gate_rejects_malformed_or_stale_phase_entry`

The guard asserts that the two sets are disjoint and their union is exactly 24.
On the landed tests-only base with activation absent, the focused phase JUnit
must contain exactly five passed and nineteen skipped testcases, with the skip
set byte-for-byte equal to `DEFAULT_SKIP_NODEIDS`. With
`PHASE_LOOP_TDD_EXPECT_HARDEN=1`, collection must still equal the same 24
nodeids; all 24 execute and fail at their intended HARDEN assertion with zero
skipped, xfailed, collection, import, setup, or teardown errors. The runner then
uses `RED_CASES_BY_NODEID` to run every parameter/case separately, so aggregate
failure cannot hide a surviving case. It first asserts the frozen source anchor,
applies/selects exactly one case, runs exactly one nodeid, and retains raw
stdout/stderr plus structured JUnit. After implementation installs the
capability marker, the immutable 24-nodeid focused run must report exactly
24 passed and zero skipped; the candidate and post-landing broad JUnit files
must each contain every expected nodeid exactly once with zero skipped.
Ordinary default tests-only CI is GREEN with the marker absent: the five legacy
branches pass and only the exact nineteen-nodeid set skips. No `xfail` is
permitted. No collection/import failure is a RED result or a compatibility
escape.

The active branches preserve the settled HARDEN semantics: the two goal tests
block every all-bare/zero-ID completion route under enforce while retaining the
warn/default legacy control; the panel/staging tests assert the exact committed
or index-tree identity plus approved contained `context_refs`; and unrelated
working-tree/untracked drift cannot change that identity. No implementation PR
may edit, rename, repair, regenerate, or alter the guard, inventories, assertion
branches, docstrings/helpers, nodeids, or test blobs.

The sorted newline-terminated 24-nodeid inventory has SHA-256
`20f358e6a3482a773cb28ed78eb6fa8e49353e2425a5d182a282eb8d7afb4b8f`.
Relative to the latest-panel plan, the delta is exactly two new `SL-1`
nodeids—the composition ordering test and the CLI ordering test. The nineteen
new nodeids are the default skip set; the five migrated nodeids remain the
default-green legacy set.

| Obligation | Required pre-implementation anchor | Per-parameter mutation and observable |
|---|---|---|
| staged-tree containment | `copytree(..., symlinks=True)` and `copy2(..., follow_symlinks=False)` are present | Absolute link, upward-relative link, chained link, symlinked directory ancestor, broken/cyclic link, non-git fallback link, `..`/absolute staged path, and special-file inputs each reach the staging seam and are rejected before child launch; an in-root regular file and an explicitly materialized in-root link remain positive controls. |
| pre-composition isolation authorization | `_advisor_board_command()` calls `compose_review_board()` before `invoke_board()`; bare/default and config-loaded composition can call `default_board_auth_ok()`, which calls a capability record's `auth_ok()` | The CLI, bare default composer, explicit-auth composer, and config-loaded live composer are exercised as separate frozen cases. An ordered event canary requires `preflight_started` then `preflight_authorized` before the first availability probe, capability-registry/provider lookup, `auth_ok()` call, seat construction, subscription access, or invoker entry. Denied or forged authorization returns the typed non-human block and proves zero auth/provider/subscription/composition/invoker side effects. Removing only the CLI preflight still fails the direct-composer cases; removing only the composer preflight still fails the CLI and config cases. The availability-only static preset/resolver affordance remains a positive control: it invokes no capability auth probe and performs no provider/subscription access. Invoker revalidation is independently mutated and must still fail before artifact/context, Omnigent, research, seat-env, leg-auth, provider, or spawn work. |
| review fleet isolation | review-capable records come from `capability_registry()` plus the Advisor Board harness, compatibility, auth, backing, native-host, live Omnigent-catalog, and scoped-research registries; CLI specs use live `wrapped_cwd`; `context_refs` exposes live absolute paths; and current Fable/Sol/Gemini/Grok panel legs run subscription-authenticated host subprocesses | Every normalized product and advisor review route reaches preflight. A credentialless command adapter may execute only inside the exact Linux bubblewrap boundary below. The four mandatory Fable/Sol/Gemini/Grok subscription seats must be supported through the same untrusted review-leg boundary plus seat-specific `parent_unix_broker_v1` inference adapters, and the exact-`I`/`M` panels must use those rows. Every other provider-backed, API-key, native-host, Omnigent, research, or otherwise broker-incompatible route satisfies the same contract or refuses before credential lookup, session creation, broker connection, or child launch. Manual/nonlaunch proves no child or capability is created. Removing or adding one live registry route without an equal checklist row, executing a refused row, excluding a mandatory panel seat, or counting an unisolated/legacy panel record as route conformance fails. |
| contained review snapshot | current review prompts either expose live paths or reduce the workspace to a bundle, while `context_refs` emits live absolute paths and instructs the reviewer to open them | The launcher materializes the exact candidate Git tree plus every approved context ref into run-owned immutable paths, rewrites all review-leg-visible prompt/ref/workspace paths to those copies, and records each original logical label with source/destination SHA-256 provenance. Positive controls open and cite a candidate source symbol and a context-ref sentinel through the rewritten paths. Absolute/upward/chained/ancestor symlinks, special files, path races, or digest mismatches refuse before launch; negative controls cannot resolve or mutate either live original. Bundle-only remains an optional input, never the sole workspace when repository/context inspection is required. `context_refs`, a prompt, CLI flags, a staged CWD, or a model/tool allowlist without the proved OS/broker boundary is never isolation evidence. |
| crash cleanup | stage creation occurs before `launch_with_spec` cleanup and exact materialized paths are tracked | Normal return, resolver failure, timeout, interrupt, and a parent-process crash are injected separately. Recovery removes only journaled run-owned stage/config/home roots; a lookalike live directory is the positive non-removal control. |
| CWD-independent reconcile | `roadmap_paths_match` and `_normalize_automation_event` accept relative persisted paths | The same ledger bytes are reconciled from repo root and an unrelated CWD. Relative identity fields are rejected identically; relative `automation.artifact` resolves only against the absolute stored repo; relocated absolute roots with equal repo-relative roadmap subpaths remain accepted. |
| enforce goal coverage | zero/unknown declarations can reach `not_applicable()` or a confirmed-legacy skip | Preflight, canonical closeout, delegated/resume completion, and missing-plan closeout each receive every zero-declared form—including a syntactically valid all-bare legacy phase—plus ambiguous, unparseable, and missing-plan declarations under `PHASE_LOOP_ACCEPTANCE_ENFORCE=block`; every case must return a non-human `contract_bug`. The all-bare case must remain distinguishable from parse failure, but only warn/default mode is its nonblocking positive control; the same all-bare phase must never pass an enforce completion gate. |
| Bash/profile bypass | `_relogin_shell_shim` does not consume Bash argument-taking `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, or `--init-file file`/`--init-file=file`, and absent nominal minors can evade patch bounds | Every frozen argument-taking form locates the true `-c` payload only after consuming its argument; missing option names/files, ambiguous `--`, and malformed or unlocatable payloads fail closed. Under `<3.11.5`, a profile-introduced absent `python3.11 == 3.11.9` is shadowed/rejected; direct argv, non-login, satisfying-present, absolute-interpreter, and ordinary `bash -lc` controls retain their existing results. |
| evidence verifier and fresh-process lifecycle | the executable is absent, the current runtime does not export `PHASE_LOOP_RUN_DIR`, and the ordinary implementation child writes all lanes before the coordinator can observe an intermediate tree | Fixture mutations separately forge external coordinator identity, server PR identity, ordered two-parent merges, target-base ancestry, actual PR range, lifecycle timestamps, process PID/nonce, loaded-head/module digests, distinct PR/branch identity, test/guard blobs and 13/7/4 node partitions, plan digest, GPT-5.6 Terra author-vendor independence, RED anchor/result, checkpoint/final commit trees and ancestry, snapshot provenance, pre-composition authorization traces, four mandatory isolated-seat attestations, registry/checklist equality, route refusal accounting, and either verification seal. The integration falsifier rejects a missing, forged, duplicated, dirty, or unlanded executing-control append; any child or pre-change-runtime transition/self-attestation; a synthetic or laundered checkpoint; a checkpoint containing `SL-3` or omitting changed `SL-1`/`SL-2` paths; candidate evidence from a process not freshly loaded at exact pushed `I`; post-landing evidence from the candidate process or a process not freshly loaded at exact canonical `M`; a missing/forged transition, isolated-panel record, suite JUnit, fleet checklist, evidence file, or parent hash; an auth/provider/subscription/composition event preceding authorization; an unisolated mandatory seat; and any merge or terminal `complete` before the corresponding audit and completed-control landing. Its positive control proves the only accepted lifecycle is exact executing append and manifest-only control merge `L`; tests merge and activated RED; Terra child exit without commit; coordinator-created actual `SL-1`+`SL-2` checkpoint `C` with a clean manifest; a clean exact-`C` process proving 13 green + 7 green + exact 4 RED while the verifier is absent from `C`; coordinator admission of only the quarantined `SL-3` verifier/docs as direct child `I`; a new clean exact-`I` process proving all 24 green with environment activation absent; external coordinator push/transition; fresh exact-candidate suite and isolated four-seat panel, reduction, and audit; candidate-process exit and exact two-parent implementation merge; then fresh exact-main suite and isolated four-seat panel, reduction, final audit; exact completed append and manifest-only closeout merge `F`; and only then completion. |
| phase-plan manifest gate | `update_lifecycle()` normally appends an `executing` event without copying immutable plan metadata and rewrites `plans/manifest.json` before lane work | The current-manifest command must reject malformed JSON, structural/per-entry validation errors, a missing/duplicate/conflicting HARDEN identity row, stale HARDEN `file`, `phase_alias`, `roadmap_ref.file`, or lane metadata, and any missing, duplicate, identity-conflicting, malformed, or payload-drifted contract-bearing lifecycle record. It locates the sole immutable contract by `harden_plan_contract_record_id=v10-HARDEN.harden-plan-contract.v1`, never by latest-event position; seals every contract field other than the separately checked current plan digest; and rejects any mismatch in the unchanged roadmap digest, exact 25 owned / 9 tests-only / 14 checkpoint path lists and digests, 24-node/13-7-4/19-skip/2-delta contract, or Terra/scheduler/subscription/no-release policy. The fixture must also exercise the normal committed → executing append and committed → executing → completed sequence through the byte-identical lookup. It rejects a wrong writer/run identity, an appended contract copy, a lifecycle/status/timestamp mismatch, arbitrary manifest dirt, an unlanded pre-`SL-0` control delta, or any implementation/checkpoint head whose clean manifest blob is not descended from server-landed `L`. The frozen fixture drives the same phase-specific gate with one mutation at a time and requires a typed non-zero result; committed, clean post-`L` executing, and exact terminal-control forms are the only positive controls. |

Before `SL-0.6`, the external coordinator panels the exact plan digest and exact
tests-only diff by reference with Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and
Grok 4.5. Fable and Sol must both produce usable reviews; all four must actually
review. Because these two reviews precede the implementation of the isolation
boundary, they are TDD/governance prerequisites only and supply no
`EC-HARDEN-5` evidence; they can never be reused as the exact-`I` or exact-`M`
panel. Any material finding changes the digest and requires a complete re-panel.
The tests-only PR and the later implementation PR must have distinct
server-recorded PR numbers and head branches. The tests-only commit must already
be in the implementation PR's server-recorded target branch before the
implementation branch is created or either production lane is dispatched.

### SL-1 — Review staging and fleet isolation

- **Scope**: Close every staged-tree escape and enforce one fleet-wide review boundary across all supported product-loop, advisor-board, and mandatory four-seat exact-head panel routes.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- **Interfaces provided**: `precomposition-review-authorization`, `review-isolation-boundary`, `trusted-provider-control-plane`, `four-seat-isolated-panel`, `review-fleet-checklist-evidence`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-RED-evidence`
- **Parallel-safe**: yes
- **Tasks**:
  - test: Confirm the `SL-1.1` review selectors remain frozen from `SL-0`.
  - impl: Implement contained staging, review-route isolation, pre-composition authorization, and journaled cleanup in `SL-1.2`–`SL-1.7`.
  - verify: Run the complete review matrix command in `SL-1.8`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | all `SL-0` review test paths, read-only | frozen review selectors | Confirm every review selector is unchanged from the `SL-0` commit before implementation. |
| SL-1.2 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | staged-tree containment | Validate every enumerated source and destination lexically and after resolution. Materialize safe in-root links as contained regular content or reject; reject every absolute/upward/chained/ancestor escape, special file, and non-git fallback escape before launch; remove the partial stage on every `BaseException`. |
| SL-1.3 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | immutable snapshot and path-isolation matrix | Before prompt/context/argv construction, resolve the declared candidate to an exact Git tree identity—server head tree for a committed/PR review or a launcher-recorded index tree for an exact staged candidate—and materialize that complete tree plus every caller-approved `context_ref` into run-owned staged paths. Preserve each original logical label, but rewrite every child-visible workspace, prompt, manifest, and ref path to the contained copy. Record source identity/path, destination-relative path, kind, bytes, and source/destination SHA-256 in launcher-owned provenance; require equality before launch. Reject lexical/resolved escapes, symlink chains/ancestors, special files, source races, collisions, and digest drift. For a supported executable route, invoke the exact bubblewrap boundary frozen below, mount the finished snapshot read-only at `/review`, make `/review` the child CWD/workspace, and refuse if any live original remains visible in CWD, argv, prompt/context, environment, mounts, or tool policy. A review bundle may accompany the snapshot but cannot replace repository or approved-context material the review contract requires. |
| SL-1.4 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py` | OS-boundary, credential-transport, and tool-isolation matrix | Add route declarations `review_boundary=linux_bwrap_v1` and `review_transport=none|parent_unix_broker_v1`. `none` is permitted only for a credentialless/no-network command adapter. Under `parent_unix_broker_v1`, the attacker-controlled review leg is a separate bubblewrap process with immutable `/review`, read-only tools, run-local scratch, no live repo/original ref, no ambient home/config/credential, no direct network, and no host escape. It sees only `/run/review-broker/socket` plus a non-secret route/session identifier. A distinct trusted coordinator/parent control plane owns subscription auth and provider egress, verifies `SO_PEERCRED`, accepts only a typed `ReviewInferenceRequest` binding seat, model, immutable input/provenance digest, conversation turn, and output limit, and returns only provider text/status/provenance. It rejects arbitrary URLs, provider/method substitution, host commands, tool execution, credential reads/returns, mutation operations, and all non-inference RPCs. Implement and prove exact first-party subscription adapters for Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5; the underlying transport process is parent-controlled and may perform only that intended inference. The four adapters must complete without placing a credential file, API key, OAuth token, inherited auth socket, ambient home, or provider network capability in the review-leg namespace. Build the review-leg environment from an allowlist and keep its prompt/tool namespace/argv/environment/snapshot/home/config/logs secret-free. Route-specific flags remain defense in depth. Return typed non-human `review_gate_block` before auth lookup/session creation/broker connection/child launch when any required platform, boundary, transport, adapter, sidecar, or direct probe is unproved; normalize persisted closeout blockers to `blocker_class=contract_bug`. |
| SL-1.5 | impl | SL-1.4 | `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py` | pre-composition isolation/broker authorization and pre-auth ordering | Mint an opaque, operation-bound `precomposition-review-authorization` only after the exact platform, `linux_bwrap_v1`, broker-adapter, direct-probe, and route-refusal prerequisites are proved. `_advisor_board_command()` obtains it after regular-file validation but before calling `compose_review_board()`, passes it through composition, and supplies it again to `invoke_board()`. `compose_review_board()` validates that authorization before its first availability probe, registry/provider lookup, explicit or default `auth_ok()` callback, seat construction, or other side effect; a direct bare/default/config-loaded caller must obtain the same authorization inside the composer before any such work. Injected availability-only static preset/resolver construction remains hermetic because it performs no capability auth/provider/subscription access. A denied, missing, stale, wrong-operation, or forged authorization returns typed non-human `review_gate_block`/`contract_bug` and proves every auth/provider/subscription/composition canary untouched. `invoke_board()` independently revalidates the same operation binding before artifact/context resolution, Omnigent catalog fetch, research materialization, seat-env/auth lookup, provider selection, broker/session creation, or spawn. The two frozen new nodeids run CLI, bare-default, explicit-auth, config-loaded, deny/forge, static-affordance, and invoker-defense cases separately through `RED_CASES_BY_NODEID`; each records an ordered event trace requiring `preflight_started`, `preflight_authorized`, then—and only then—the first permitted composition/auth event. |
| SL-1.6 | impl | SL-1.4, SL-1.5 | `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | complete live review-route registry and honest support/refusal | Produce one normalized route registry from every `capability_registry()` record supporting `review` (including command/manual and Claude route/mode expansion), every Advisor Board route expressible through the live harness/compatibility registries, auth lanes, provider backings, native-host state, scoped-research state, and live Omnigent catalog, and the four brokered Fable/Sol/Gemini/Grok panel-seat routes. Apply the frozen support/refusal table below literally. Candidate and canonical-main panels must invoke these same four supported rows through the exact-head repo-local boundary; their per-seat boundary/broker/probe attestations are checklist evidence, not an exclusion. A refused executable row satisfies the safety invariant only by proving that no credential lookup, session, broker connection, child, or side effect occurred; it is never reported as a supported conforming route. Manual/nonlaunch remains an evidenced non-executable row. Compare normalized registry keys with checklist keys by exact set equality so additions, omissions, duplicates, an unisolated or missing mandatory seat, an executed refused row, and a panel record without matching supported rows fail closed. API-key fallback is disabled throughout HARDEN. |
| SL-1.7 | impl | SL-1.1 | `phase-loop-runtime/src/phase_loop_runtime/launcher.py` | crash/recovery cleanup | Journal exact run-owned stage, home, config, and context roots before child launch; clean them on normal return, resolver failure, timeout, interrupt, and next-run recovery after parent crash; never infer ownership from basename, glob, or a live path. |
| SL-1.8 | verify | SL-1.2, SL-1.3, SL-1.4, SL-1.5, SL-1.6, SL-1.7 | all `SL-1` owned source paths | exact 13-node review matrix | Set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, import literal `SL1_NODEIDS` from the frozen guard, and invoke pytest with exactly those 13 nodeids plus `--junitxml=<checkpoint-run-dir>/harden-sl1.xml`; require exactly 13 passed, zero skipped/xfailed/errors, ordered pre-auth traces for every composition case, and JUnit nodeid set equality. This is an interim lane/checkpoint activation only. The authoritative result is rerun by the external coordinator's clean exact-`C` process; exact-`I` and exact-`M` remove the environment variable and prove capability-marker activation with zero skips. |

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
| mandatory Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5 panel seats | **supported on probed Linux only** | Each review leg runs inside `linux_bwrap_v1` and reaches only its seat-specific typed inference method through `parent_unix_broker_v1`; the trusted parent retains first-party subscription auth/transport. Exact-`I` and exact-`M` panels must use these four rows and all four direct-probe attestations. |
| manual/nonlaunch | **supported non-executable** | Creates no child, credential, workspace, broker, or side effect. |
| direct codex CLI product review | **refused** | `--sandbox read-only` and `--ignore-user-config` do not provide the complete review-leg/broker boundary; only the brokered Sol panel adapter above is supported. |
| direct Claude print, Channel, and Agent View across solo/subagent/agent-team | **refused** | Permission/tool flags and Channel bearer handling do not place the complete reviewer process tree behind the common boundary/broker; only the brokered Fable panel adapter above is supported. |
| direct gemini/agy and grok CLI review | **refused** | Staged CWD and tool allowlists are not an OS boundary; only the brokered Gemini and Grok panel adapters above are supported. |
| OpenCode CLI and Pi Agent | **refused** | No proved credentialless broker adapter and no equivalent attested OS boundary. |
| other Advisor Board homebrew subscription routes | **refused** | The mutable direct launch surface has no proved broker adapter; the four mandatory brokered panel rows above are the only supported subscription routes in HARDEN. |
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
route-specific fake-broker round trip in which the review-leg adapter completes
with no credential source. This credentialless boundary/fake-broker proof is
the pre-composition authorization and must finish without a capability-registry
auth call, provider process, subscription lookup, network access, session, or
seat construction. Only after that authorization exists may capability
`auth_ok()` run; only after authentication may the trusted parent perform the
exact transport probe showing that the typed intended-inference RPC reaches the
selected first-party subscription route. macOS, Windows, Linux without the
namespace smoke, and any non-mandatory route missing a proved broker adapter are
refused before authentication, snapshot disclosure to a child, or
process/session creation; a missing Fable/Sol/Gemini/Grok adapter blocks HARDEN
rather than downgrading or refusing that mandatory seat.

Before every supported review-leg launch, direct canaries inside the exact namespace
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

The review-leg environment is allowlist-built, not ambient-env-minus-a-few
keys. It may contain `PATH`, `LANG`, `LC_*`, `TERM`, `TMPDIR`, `USER`, `SHELL`,
`PHASE_LOOP_CHILD`, non-secret runner correlation IDs, run-local `HOME`,
`XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, and a non-secret
`PHASE_LOOP_REVIEW_BROKER=/run/review-broker/socket` only for a proved broker
adapter. Subscription tokens, API keys, gateway credentials, provider headers,
auth helper paths, and other secrets never enter the process namespace,
environment, argv, prompt, tool results, snapshot, or logs.
Provider subscription state and
`PHASE_LOOP_CLAUDE_CHANNEL_BEARER_TOKEN` remain usable only inside the trusted
parent control plane and never enter a review-leg process; Channel becomes a
conforming seat only through the Fable broker adapter, not through its direct
product route.

`provider_control_plane_v1` is the other side of that boundary. For each seat,
the immutable coordinator starts a fixed-digest adapter in a run-owned empty
CWD with no repository, snapshot, context-ref, shell/tool namespace, GitHub,
SSH, package-publish, cloud, database, or 1Password capability. Its allowlisted
inputs are the validated `ReviewInferenceRequest`, that seat's parent-only
subscription handle, the exact provider/model route, and correlation limits;
its only outputs are provider text/status/provenance. The adapter invokes an
inference-only, tool-disabled provider transport and rejects any provider tool
request, arbitrary command, alternate endpoint/model/provider, auth export, or
non-inference operation. Provider egress is coordinator-owned and constrained
to the exact intended subscription inference route. The untrusted review leg
can request another inference turn only through the typed broker; it cannot
address the transport process, auth store, endpoint, or host directly. A route
whose current subscription CLI cannot be driven under this exact adapter must
be repaired in `SL-1`; for a mandatory seat it blocks HARDEN rather than
falling back to the unsafe direct CLI.

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
route and separately for each of Fable, Sol, Gemini, and Grok, a direct
review-leg probe attempts live-tree write/delete, git commit/tag/config,
HTTPS/SSH push, GitHub mutation, package publish, cloud mutation, secret
retrieval, arbitrary broker method/provider/URL substitution, and non-broker
network/host escape. Every attempt must enter its intended probe and be denied
before any canary records a side effect; the only positive credentialed action
is the parent-recorded intended inference RPC for that exact seat. Each
mandatory seat also proves it can read/cite the immutable snapshot through
read-only tools and return a usable provider response without credential or
network capability in the review-leg namespace. For every refused route, a
preflight probe proves refusal happened before auth lookup, session/broker
creation, or child launch. A missing direct probe for any of the four seats, an
executed refused row, a refusal mislabeled supported, a mandatory panel record
without the four matching supported checklist rows, or route/checklist set
mismatch fails. No real external mutation is performed.

### SL-2 — Reconcile, goal-coverage, interpreter, and runner sequencing hardening

- **Scope**: Make main-loop attribution CWD-independent, enforce non-vacuous goal declarations on every completion path, close both `Consiliency/agent-harness#241` login-shell bypass classes, and add the capability marker plus validation for the external-coordinator checkpoint/fresh-process/post-suite lifecycle.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`
- **Interfaces provided**: `path-and-verification-hardening`, `HARDEN-capability-v1`, `external-coordinator-checkpoint-validation`, `external-coordinator-transition-validation`, `runner-owned-run-dir-export`, `runner-owned-post-suite-reduction`
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
| SL-2.5 | impl | SL-2.1 | `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py` | capability activation, external checkpoint/transition validation, run-dir export, post-suite reduction, and final audit | Install literal `HARDEN_CAPABILITY_VERSION = 1` in `verification_evidence.py`; this is the only production activation read by the frozen guard. Parse the HARDEN lifecycle/post-suite contract separately from `## Verification` and `automation.suite_command`. Do not make the implementation child or already-loaded parent commit, push, author a checkpoint/transition, reload, self-reexec, attest changed bytes, or complete. On a fresh repo-local `resume`, accept only the exact external-coordinator-authored transition path supplied in non-secret `PHASE_LOOP_HARDEN_COORDINATOR_TRANSITION`; require it beneath canonical `.phase-loop/runs/`, then recompute its coordinator executable/package identity, actual checkpoint `C`, direct-child candidate `I`, exact staged path sets and residual hashes, clean checkpoint/final worktree/process results, pre/post Git identities, remote candidate object, plan/roadmap/manifest/test digests, implementation launch PID/times/artifact hashes, rejected false-complete/reopen record, and old-process death. Fail closed unless the coordinator package root is outside the worktree, `C` and `I` have the required ancestry/tree/path shapes, the candidate worktree is clean, local HEAD equals fetched remote `I`, loaded repo-local `cli.py`/`advisor_board/composition.py`/`panel_invoker.py`/`runner.py`/`verification_evidence.py`/verifier/launcher hashes equal Git blobs at `I`, and candidate PID/start nonce differs from coordinator, implementation, and checkpoint processes. Before invoking any extracted command or `automation.suite_command`, set `PHASE_LOOP_RUN_DIR` explicitly in the subprocess environment to the current runner-owned artifacts root; never infer it from CWD. Candidate audit stops nonterminal; a separately launched exact-`M` process validates a coordinator-authored post-landing transition the same way. Persist process identities, transition/argv/exit data, and verification/log/JUnit/checklist/panel/evidence paths and hashes in parent-owned metadata. Treat missing/child-authored/stale checkpoint or transition, synthetic/laundered ancestry, same-process cycle, stale/wrong head/module, pre-seal call, missing output, forged hash/identity, non-zero reducer, or audit mismatch as non-human `repeated_verification_failure`. |
| SL-2.6 | verify | SL-2.2, SL-2.3, SL-2.4, SL-2.5 | all `SL-2` owned source paths and frozen `SL-0` tests read-only | exact 7-node non-evidence `SL-2` partition | Set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, import literal `SL2_NODEIDS` from the frozen guard, and invoke pytest with exactly those 7 nodeids plus `--junitxml=<checkpoint-run-dir>/harden-sl2.xml`. Require set equality with the two reconcile nodeids, four goal nodeids (two migrated plus two new), and one interpreter nodeid; JUnit must report exactly 7 passed, zero skipped/xfailed/errors. Do not run or require any `SL3_EVIDENCE_NODEIDS` in this command: the external coordinator's clean exact-`C` process runs those four separately and requires intended RED because `verify_harden_evidence.py` is absent from `C`. Exact-`I` and exact-`M` remove the environment variable and prove production-marker activation. |

### SL-3 — Fresh-process candidate/post-landing evidence and documentation reducer

- **Scope**: Admit the quarantined HARDEN chronology/evidence executable and changelog only after an actual clean `SL-1`+`SL-2` checkpoint proves 13 + 7 green and exact 4 RED, then prove all 24 frozen nodes green at a new clean direct-child head and let the immutable external coordinator drive push plus fresh candidate/post-landing verification.
- **Owned files**: `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- **Interfaces provided**: `HARDEN-closeout-evidence`, `HARDEN-no-spec-delta`
- **Interfaces consumed**: `HARDEN-test-freeze`, `HARDEN-TDD-activation-contract`, `HARDEN-node-partition-contract`, `HARDEN-RED-evidence`, `review-isolation-boundary`, `trusted-provider-control-plane`, `four-seat-isolated-panel`, `review-fleet-checklist-evidence`, `path-and-verification-hardening`, `HARDEN-capability-v1`, `external-coordinator-checkpoint-validation`, `external-coordinator-transition-validation`, `runner-owned-run-dir-export`, `runner-owned-post-suite-reduction`
- **Parallel-safe**: no
- **Tasks**:
  - test: After the implementation child exits without committing, let only the external coordinator create actual checkpoint `C` from the exact `SL-1`+`SL-2` staging set and prove 13 + 7 green plus the exact 4 evidence nodes RED from a separate clean exact-`C` worktree/process in `SL-3.1`.
  - impl: After that checkpoint proof, admit only the already-written, digest-quarantined verifier and changelog into direct-child commit `I` in `SL-3.2`–`SL-3.3`; do not let the coordinator rewrite their bytes.
  - verify: From a new clean exact-`I` worktree/process with environment activation absent, run the exact all-24/zero-skip gate in `SL-3.4`, then let only the external coordinator push and complete the candidate and post-landing gates—including the isolated exact four-seat panels—in `SL-3.5`–`SL-3.6`.

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | SL-1.8, SL-2.6 | `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py` (read-only) | exact checkpoint 13-green + 7-green + 4-RED proof | After the GPT-5.6 Terra implementation child has written every `SL-1`–`SL-3` owned path and the pre-change runtime/child have exited without a commit, the external coordinator records the complete dirty path/digest set. It first proves `plans/manifest.json` is clean, equals the server-landed executing-control blob descended from `L`, and is absent from the dirty and cached sets. It stages only the literal fourteen `SL-1`+`SL-2` source paths enumerated below, proves the cached path set equals the recorded changed subset and excludes all `SL-0`, `SL-3`, lifecycle-control, and unowned paths, and creates actual checkpoint commit `C` directly atop the fetched post-tests target `T`. The original implementation worktree must then retain exactly the two unchanged, digest-matched `SL-3` residual paths and no other Git-visible dirt; `plans/manifest.json` is not a third residual. In a separate clean detached exact-`C` worktree and fresh process, set `PHASE_LOOP_TDD_EXPECT_HARDEN=1`; run exact `SL1_NODEIDS` and require 13 passed/0 skipped, exact `SL2_NODEIDS` and require 7 passed/0 skipped, then exact `SL3_EVIDENCE_NODEIDS` and every frozen case and require intended assertion RED with zero skip/xfail/collection/import/setup/teardown errors. The `SL-1` result must include both pre-composition ordering nodeids and their complete CLI/bare-default/explicit-auth/config/denial/static/invoker case traces. Prove `verify_harden_evidence.py` is absent from tree `C`. Child checks, the dirty original worktree, and the already-loaded pre-change runtime cannot satisfy this gate. |
| SL-3.2 | impl | SL-3.1 | `phase-loop-runtime/scripts/verify_harden_evidence.py` | candidate/post-landing chronology and evidence verifier | Preserve the child-written script bytes and pre-checkpoint digest without coordinator edits. After the clean exact-`C` proof passes, stage this path together with `CHANGELOG.md` and create direct-child commit `I`. The executable has an explicit `--lifecycle-stage candidate|post_landing`; both stages require parent-supplied run directory, sealed `verification.json`, structured broad-suite JUnit, runner-reduced fleet checklist, output path, plan, roadmap, phase, repository, external coordinator transition, isolated four-seat panel record, exact checkpoint/final commit trees, and exact process/head/module identities. Candidate mode writes only `harden-candidate-evidence.json`; post-landing mode additionally requires and revalidates candidate evidence/hashes and writes only final `harden-evidence.json`. It derives Git/forge ancestry, exact `L -> T -> C -> I` commit/path shapes, the normal executing lifecycle event and clean landed manifest blob, ordered control/tests/implementation PR-merge parents, path ownership, manifest state, nodeid/skip state, transition authorship/identity, all four isolated-seat attestations, and route-checklist evidence; exits non-zero with typed findings for any missing, mismatched, child/self-reported-only, stale-process/run/head, synthetic/laundered checkpoint, one-parent/squash/rebase merge, unisolated/excluded panel seat, or forged obligation; and never discovers another run, trusts CLI booleans/counts, runs as an ordinary suite command, amends `verification.json`, or writes tracked files. |
| SL-3.3 | impl | SL-3.1 | `CHANGELOG.md` | Unreleased note | Preserve the child-written changelog bytes and pre-checkpoint digest without coordinator edits; stage it only with `verify_harden_evidence.py` after `SL-3.1`. Its concise Unreleased note covers contained review staging/fleet isolation, isolated four-seat subscription panels, CWD-independent reconcile attribution, non-vacuous enforce goal coverage, and login-shell interpreter hardening. Do not edit roadmap/spec/contract/version/release-pin surfaces. |
| SL-3.4 | verify | SL-3.2, SL-3.3 | all phase-owned paths and frozen `SL-0` tests, read-only | exact all-24 pre-push gate | Require `I` to be an actual commit with sole parent `C`, cached/residual admission exactly `{phase-loop-runtime/scripts/verify_harden_evidence.py, CHANGELOG.md}`, and no amendment, rebase, squash, cherry-pick, stash/patch replay, replacement ref, synthetic `commit-tree`, or history rewrite. In a new clean detached exact-`I` worktree/process—not the dirty original, child, pre-change runtime, or exact-`C` process—remove `PHASE_LOOP_TDD_EXPECT_HARDEN`, assert `HARDEN_CAPABILITY_VERSION == 1`, import literal `EXPECTED_PHASE_NODEIDS`, and invoke pytest with exactly those 24 nodeids plus `--junitxml=<coordinator-run-dir>/harden-phase-focused.xml`. Require exact partition equality `13 + 7 + 4 = 24` and JUnit exactly 24 passed, zero skipped/xfailed/errors. Only this clean exact-head result authorizes push/transition. A failure returns to the GPT-5.6 Terra child for a fresh dirty output and restarts the actual `C`/`I` chronology; no partial 20-node green or reused worktree/process is admissible. |
| SL-3.5 | verify | SL-3.4 | all phase-owned paths plus coordinator and candidate runner evidence, read-only | externally pushed candidate and fresh exact-candidate proof | After `SL-3.4` passes, the external coordinator—not the child or old runtime—pushes exact `I`, verifies the remote object, records/rejects any old-runtime false `complete`, reopens it with the existing `phase-loop reopen` command after the tree is clean, proves old PIDs/locks gone, and writes the run-owned external transition binding `T`, `C`, and `I`. It launches a distinct repo-local process with `PYTHONPATH=phase-loop-runtime/src` at exact clean fetched `I` and the exact transition path. That process validates and copies the transition into its run-owned input area, exports its run dir, runs every ordinary verification command and the broad suite, seals JUnit/`verification.json`, and enters a bounded fail-closed `awaiting_external_review` wait without exiting or changing HEAD. The coordinator then starts the exact-`I` repo-local isolated-panel boundary: all four Fable/Sol/Gemini/Grok seats receive only immutable staged exact-`I` inputs, run their direct mutation/credentialed-side-effect probes, and perform intended inference only through their supported parent-broker adapters. The sealed panel record cross-links the four supported fleet-checklist rows and is written into the candidate run's declared input path. The same still-live candidate process validates it, reduces/audits candidate evidence, records nonterminal `candidate_audit=passed`, and exits. Timeout, wrong writer/path/digest, process exit, changed HEAD, direct legacy panel launch, missing/refused/excepted seat, or failed boundary/broker/probe attestation fails. Any change or material finding invalidates `I` and restarts the actual `C`/`I` chronology; merge is forbidden until this gate passes. |
| SL-3.6 | verify | SL-3.5 | all phase-owned paths plus candidate and canonical-main runner evidence, read-only | exact two-parent landing and fresh canonical-main proof | The external coordinator merges only exact reviewed `I` with the required two-parent topology, proves the candidate process exited, fetches server canonical main `M`, prepares an exact clean worktree, and writes a post-landing transition. It starts another distinct repo-local process at `M` with modules loaded from `M`. Repeat manifest/plan/roadmap validation, environment-activation-absent exact 24-node focused and broad compatible suites, Ruff, and the mandatory exact-`M` four-seat panel through the exact-`M` repo-local isolated-panel boundary with four direct mutation/credentialed-side-effect probes and supported broker rows. Then run post-suite fleet/final reduction and parent audit. Structured JUnit contains all 24 frozen nodeids exactly once with zero skipped. Only this process may authorize the normal completed lifecycle append after it verifies the lifecycle-control, tests-only, and implementation ordered two-parent PR merges, actual `L -> T -> C -> I` ancestry, both isolated exact-head panels, and the complete lifecycle below. Terminal `complete` remains withheld until the external coordinator lands the exact manifest-only completed-control PR `F` and proves every non-manifest blob is identical to audited `M`. |

The coordinator's checkpoint staging command names exactly these fourteen
`SL-1`+`SL-2` source paths and no glob:

- `phase-loop-runtime/src/phase_loop_runtime/cli.py`
- `phase-loop-runtime/src/phase_loop_runtime/launcher.py`
- `phase-loop-runtime/src/phase_loop_runtime/injection.py`
- `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`
- `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`
- `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`
- `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`
- `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`
- `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`

Before staging, the coordinator records the changed subset and SHA-256 for every
phase-owned dirty path. It separately proves `plans/manifest.json` is clean,
matches the server-landed `L` descendant blob, and is absent from both dirty
and cached sets. It invokes `git add --` with only the fourteen literals, then
requires the cached name set to equal the previously recorded changed subset
within that exact list. It refuses an empty checkpoint, a cached
`SL-0`/`SL-3`/lifecycle-control/unowned path, an unstaged changed
`SL-1`/`SL-2` path, or any manifest delta. Commit
`C` has sole parent `T`, the fetched target head containing the two-parent tests
merge. After `C`, porcelain status in the implementation worktree must name
exactly `phase-loop-runtime/scripts/verify_harden_evidence.py` and
`CHANGELOG.md`; their bytes and hashes must equal the child-exit record, and the
manifest must remain clean. Ignored
run-owned `.phase-loop/` evidence stays outside Git and is bound separately.
The detached checkpoint worktree is created from commit `C`, is clean before
and after its proof, cannot see the original worktree's two residual paths, and
is removed only after its process exits and evidence is sealed.

Only after `SL-3.1` passes may the coordinator invoke `git add --` with exactly
the verifier and changelog literals. The cached name set must equal those two
paths, the bytes must still match the child-exit hashes, and direct-child commit
`I` must have sole parent `C`. The coordinator never amends either commit and
never uses rebase, squash, cherry-pick, stash/patch replay, replacement refs,
`commit-tree`, or another synthetic-history mechanism to manufacture the
intermediate state. Both clean proof worktrees are materialized from real
commits; no dirty-tree checkout, index-only tree, file hiding, or post-hoc
history rewrite can satisfy the chronology.

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
   before tests landed. These pre-implementation records precede the HARDEN
   boundary and therefore do not appear in the route registry/checklist or
   satisfy `EC-HARDEN-5`; they cannot substitute for either isolated exact-head
   panel.
2. The unique HARDEN row in `plans/manifest.json` passes structural and
   per-entry validation and exactly names this plan, phase, roadmap, and
   `SL-0`–`SL-3`. It searches every lifecycle event for either
   `harden_plan_contract_record_id` or `harden_plan_contract`, requires exactly
   one contract-bearing event, and requires identity
   `v10-HARDEN.harden-plan-contract.v1`; it never reads the contract by latest
   event position. The sealed immutable payload binds the current plan and
   unchanged roadmap digests; 25 owned, 9 tests-only, and 14 checkpoint paths
   plus their sorted-newline SHA-256 values; the 24-node inventory digest and
   exact 13/7/4 partition; the two pre-auth ordering nodeids; Terra whole-phase
   authorship; both schedulers off; subscription-only auth; and no release/tag.
   The normal `executing` event is later, carries only the exact executor run
   metadata, and is landed in `L` before tests branch creation. Malformed JSON,
   a bad sibling row, missing/duplicate/conflicting HARDEN row, a missing,
   duplicate, malformed, identity-conflicting, or payload-drifted
   contract-bearing record, stale file/alias/roadmap/lane metadata,
   count/digest drift, an invalid lifecycle sequence/status/timestamp, or a
   plan digest still bound to the latest-panel `DISAGREE` bytes is a typed
   failure. The byte-identical contract lookup appears in both frontmatter and
   `## Verification`; its sealed result is required at the clean checkpoint,
   pre-push, candidate, exact-`M`, and terminal-control heads.
3. `harden_tdd_guard.py` and all eight phase test modules have the landed
   tests-only blob IDs. The guard's literal inventories are exactly 24 expected
   nodeids, partitioned without overlap as `SL1_NODEIDS=13`,
   `SL2_NODEIDS=7`, and `SL3_EVIDENCE_NODEIDS=4`, plus 19 default skips and 5
   migrated legacy branches. The tests-only default JUnit is exactly 5
   passed/19 skipped with the exact skip set. Activated RED collection is the
   same 24; every nodeid
   and every frozen case has intended assertion-failure raw output and JUnit
   with zero skip/xfail/collection/setup errors. A clean exact-`C` process with
   `PHASE_LOOP_TDD_EXPECT_HARDEN=1` records `SL-1.8` as exactly 13 green,
   `SL-2.6` as exactly 7 green, and `SL-3.1` as the exact 4 RED while the
   executable is absent from tree `C`. Only a distinct clean exact-`I` process,
   after direct-child commit `I` introduces the executable, records all 24 green
   with the environment activation absent. Candidate and post-landing JUnit
   each repeat the same 24 exactly once, all passed, zero skipped, with the
   environment activation absent and production marker present.
4. Server-returned forge metadata identifies distinct tests-only and
   implementation PR numbers/head branches, plus the distinct runner-owned
   lifecycle-control PR, and records repository, URL,
   target/base/head refs and object IDs, reviewed heads, states, merge commits,
   and lifecycle times. The lifecycle-control PR changes only
   `plans/manifest.json` by the exact `update_lifecycle` executing delta and
   lands as `L` before the tests branch exists. The tests branch is created
   from the fetched post-`L` target. The implementation remote branch did not
   exist before the tests PR merged and was created only from the fetched
   post-test target head after activated RED passed.
5. Ordered two-parent topology is exact, not merely reachability. Let `B` be the
   lifecycle-control PR target object, `LH` its manifest-only reviewed head,
   and `L` its merge commit; `git cat-file`/forge metadata must prove `L` has
   exactly ordered parents `[B, LH]`, `B..LH` changes only
   `plans/manifest.json`, and that blob is exactly the allowed committed →
   executing API delta. Let `TH` be the tests PR reviewed head and `TM` its
   merge commit;
   `git cat-file`/forge metadata must prove `TM` has exactly ordered parents
   `[L, TH]`. Let `T` be the fetched post-tests target/implementation branch
   point, `C` the actual checkpoint whose sole parent is `T`, and `I` the
   reviewed/pushed direct child whose sole parent is `C`. Tree `C` contains
   exactly the changed `SL-1`+`SL-2` paths and no `SL-0`/`SL-3` change; the
   `C..I` range contains exactly the verifier and changelog. Let `P` be the
   server canonical-main object immediately before implementation merge and
   `M` the server-recorded merge/canonical-main head; `M` must have exactly
   ordered parents `[P, I]`. Squash, rebase, octopus, synthetic replacement,
   rewritten checkpoint, reversed/wrong parents, or a later main head fails.
   After the exact-`M` final audit, let `FH` be the closeout-control branch
   commit whose sole change from `M` is the exact executing → completed
   `update_lifecycle` delta, and `F` the server closeout-control merge; `F` has
   exactly ordered parents `[M, FH]`, differs from `M` only in
   `plans/manifest.json`, and preserves every runtime, test, plan, roadmap, and
   phase-owned blob from `M`.
   `L` and `TM` are ancestors of `T`, `C`, `I`, `P`, and `M`. The actual
   implementation PR range is derived from server identities; it and the forge
   file set contain no `SL-0` path, tests-only commit, or manifest-control
   change, and every frozen test/guard blob remains identical. A
   `base -> tests -> implementation`
   branch whose PR targets the pre-test base fails even if the tests commit is
   elsewhere in the head ancestry.
6. Lifecycle order is strict and digest-bound:
   coordinator identity freeze → external phase-plan panel → external
   manifest pre-image freeze → normal executor `executing` append → exact
   manifest-only control PR merge `L` → clean post-`L` target → external
   tests/guard panel → tests PR merge `TM` → default 5-pass/19-skip proof →
   activated raw RED completion → implementation branch creation →
   GPT-5.6 Terra implementation child writes all owned paths under manual
   closeout and exits without commit → old runtime exit/false-complete rejection
   → coordinator records dirty paths/hashes → coordinator stages the exact
   `SL-1`+`SL-2` set and commits actual checkpoint `C` → clean exact-`C` process
   records 13-node `SL-1` green, including pre-auth ordering → 7-node `SL-2`
   green → exact evidence 4 RED
   with verifier absent → coordinator stages only unchanged verifier/docs and
   commits direct-child `I` → distinct clean exact-`I` process records all 24
   green with environment activation absent → coordinator push/remote proof and
   external transition write → distinct repo-local candidate process startup at
   `I` → candidate manifest/focused/broad/Ruff seal → isolated exact-`I`
   Fable/Sol/Gemini/Grok panel with four supported checklist rows and direct
   probes → candidate reduction/audit → candidate process exit →
   coordinator-owned implementation PR merge `M` → distinct post-landing
   process startup at `M` → post-landing manifest/focused/broad/Ruff seal →
   isolated exact-`M` four-seat panel with the same boundary → final
   reduction/audit → exact manifest-only completed-control PR merge `F` →
   terminal `complete`. Each event carries
   coordinator-observed time, prior-event hash, plan/test/checkpoint/candidate
   digest, and server object IDs; absent, duplicate, out-of-order, or post-dated
   evidence fails.
7. The immutable external coordinator, implementation launch, checkpoint
   verifier, exact-`I` pre-push verifier, candidate verifier, and post-landing
   verifier have distinct recorded PID/start nonce values. The coordinator
   record proves its console script and imported
   package root are outside the HARDEN worktree and byte-identical from initial
   dispatch through final audit. The implementation launch record comes only
   from existing `launch.json`/terminal/event artifacts and is never a handoff.
   The checkpoint process starts/ends clean at exactly `C`; the pre-push and
   candidate processes start/end clean at exactly `I`; the post-landing process
   starts/ends clean at exactly `M`. Their repo-local `cli.py`, `runner.py`,
   `verification_evidence.py`, verifier, launcher, capability registry, Advisor
   Board composition, and panel-invoker boundary bytes hash to the corresponding
   Git blobs. Any old-runtime terminal `complete` after
   changed imported bytes is explicitly rejected and manually reopened; a
   process that changes/checks out a new head after startup exits and can attest
   neither head.
8. All test/source/script/changelog changes use the one coordinator-recorded
   Codex GPT-5.6 Terra author vendor. The broad compatible suite and all ordinary
   verification commands
   seal green before either isolated exact-head implementation panel.
   Author-vendor seats are advisory only and the non-author seats satisfy
   governed quorum. A finding/fix invalidates `C`, `I`, their clean-process
   results, seal/panel/audit, and forces the Terra child plus the full
   actual checkpoint/direct-child chronology to restart.
9. The launcher-owned immutable-snapshot manifest covers the exact candidate or
   canonical-main Git tree and every approved context ref, preserves logical
   labels, and proves source/destination path, kind, bytes, and SHA-256 equality.
   Positive controls for every mandatory seat open candidate code and context
   refs only through rewritten contained `/review` paths; negative controls
   prove live originals unreachable and unmodifiable. The review-leg namespace
   has read-only tools, no direct network, credentials, privileged side-effect
   capability, or host escape. `context_refs`, prompts, CLI flags, staged CWD,
   naming, and tool allowlists cannot populate the boundary attestation.
10. Every normalized live product-plus-advisor review route has exactly one
    runner-observed posture: supported executable, refused prelaunch, or
    nonlaunch. The supported credentialless command route carries the exact
    `linux_bwrap_v1` mount/namespace/env/probe/cleanup attestation. Fable, Sol,
    Gemini, and Grok are four mandatory supported executable rows; each carries
    the same review-leg attestation, its exact `parent_unix_broker_v1` adapter
    proof, direct mutation/credentialed-side-effect probes, intended-inference
    RPC evidence, and candidate/main panel cross-link. The provider
    subscription auth/transport stays in the trusted coordinator/parent control
    plane and is never review-leg capability. Refused routes prove zero auth
    lookup, session, broker connection, child, and side effect. Checklist and
    registry keys are exactly equal. Refusal satisfies the safety invariant
    only because the route did not execute; it never counts as supported-route
    conformance. A mandatory seat that is refused, excepted, relabeled, absent,
    or launched directly through the legacy subprocess route leaves
    `EC-HARDEN-5` UNMET.

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

This is an immutable external-coordinator protocol with one pre-change
implementation runtime, one clean exact-`C` checkpoint verifier process, one
clean exact-`I` pre-push verifier process, and two sealed repo-runtime processes
at exact `I` and exact `M`. The external coordinator is the roadmap-owned v10
control process, not a new HARDEN executable. It uses existing installed
surfaces: `codex-phase-loop --version`, `run/resume --closeout-mode manual`,
`state --json`, `monitor --once --json`, `reopen --reason`, canonical
`.phase-loop/runs/**` launch/heartbeat/terminal artifacts, ordinary Git
commits/worktrees, Git/forge metadata, and the Advisor Board
`PanelRequest.context_refs` API. No current runner pause is assumed: current
ordinary execution writes all lanes before phase verification, so the
coordinator creates and verifies the real intermediate commit after the child
exits. Its resolved console script and imported package files are outside the
worktree and digest-frozen before dispatch. `automation.suite_command` and
commands extracted from `## Verification` are pass-1 verification; no ordinary
command may invoke `verify_harden_evidence.py`, read an unsealed current-run
artifact, or claim post-suite output as suite evidence.

0. **Land the normal lifecycle append before lane work.** After validating the
   plan, proving the clean manifest pre-image is row-stable under the production
   serializer, and passing the disposable exact
   `committed -> executing -> completed` simulation with zero sibling drift, the
   installed executor calls
   `update_lifecycle()` once for slug `v10-HARDEN`, transition `executing`,
   writer `codex-execute-phase`, and exact metadata
   `{"run_id": <run-id>, "phase_alias": "HARDEN"}`. Before any `SL-0` file is
   written, the coordinator requires `plans/manifest.json` to be the sole dirty
   path and validates the parsed/canonical delta against the API: only the
   unique HARDEN row status, updated timestamp, and one appended event may
   differ; the previous lifecycle prefix, stable contract-bearing record, all
   other HARDEN fields, and every sibling row are unchanged. It commits only
   that path on a separate control branch, opens and merges a distinct
   two-parent manifest-only PR as `L`, fetches the exact target, and proves a
   clean tree whose manifest blob equals `L`. The tests branch is created only
   from that post-`L` target. No lane or Terra child owns this transition, and
   no allowlisting of later manifest dirt is permitted.

1. **One child, no self-attestation.** The external coordinator launches exactly
   one GPT-5.6 Terra implementation process through the already-installed
   pre-change runtime with `--closeout-mode manual`, `--lane-scheduler off`, and
   `--phase-scheduler off`.
   That runtime does not export `PHASE_LOOP_RUN_DIR`, so the frontmatter
   command's explicit `mktemp` fallback is bootstrap-only and never lifecycle
   evidence. The child writes all `SL-1`, `SL-2`, and `SL-3` owned paths, runs
   useful diagnostic checks, and exits. It must not commit, stage for the
   coordinator, push, transition, attest, panel, merge, or complete. Neither its
   checks nor the already-loaded runtime can satisfy the 13/7/4 chronology.
2. The coordinator waits for the installed runtime and implementation child to
   exit and proves their PID/process-group/locks are gone. Any old-runtime
   terminal `complete` is classified `false_complete_rejected` because its
   imported runner/reducer identities predate the dirty output. It validates
   frozen `SL-0` blobs, proves the manifest is clean and equal to the landed
   `L`-descended executing blob, and records the exact phase-owned dirty
   path/digest set. Using only
   the fourteen literal source paths above, it stages the recorded changed
   `SL-1`+`SL-2` subset and creates actual checkpoint commit `C` with sole parent
   `T`; all `SL-3` bytes remain unchanged and dirty in the original worktree.
   It creates a separate clean detached exact-`C` worktree and starts a fresh
   process there. With `PHASE_LOOP_TDD_EXPECT_HARDEN=1`, that process runs exact
   13 green, exact 7 green, and exact 4 intended RED, proves the verifier absent
   from `C`, seals results, and exits. The original dirty tree, implementation
   child, and old runtime are never evidence sources for this gate.
3. Only after the exact-`C` proof passes, the coordinator verifies that the
   original worktree's only Git-visible dirt is the unchanged verifier and
   changelog and that `plans/manifest.json` is clean at the landed executing
   blob. It stages exactly those two literals and creates actual commit `I`
   with sole parent `C`. A new clean detached exact-`I` worktree and new process
   remove `PHASE_LOOP_TDD_EXPECT_HARDEN`, assert the production capability
   marker, and prove exact all-24/zero-skip. The coordinator then pushes exact
   `I`, verifies `git ls-remote` equals `I`, and invokes the existing
   `phase-loop reopen --phase HARDEN --reason
   "pre-change runtime cannot attest HARDEN candidate"` on the now-clean tree if
   reconciliation still reports the rejected false completion. No amend,
   rebase, squash, cherry-pick, stash/patch replay, replacement ref,
   `commit-tree`, dirty-worktree proof, or reused process is admissible.
4. The coordinator writes
   `.phase-loop/runs/<transition-id>/harden-coordinator-transition.json` from
   its own process. The sealed record contains coordinator executable/package
   realpaths, version/Git identity/file hashes/PID/start nonce; manifest
   pre/post blobs, exact executing event, lifecycle-control PR/merge `L`, and
   the clean post-`L` target identity; implementation
   launch artifact paths/hashes and child-exit dirty manifest; rejected
   false-complete/manual-reopen event; exact `L`/`T`/`C`/`I` parents, trees, staged
   path sets, residual hashes, clean worktree/process identities and 13/7/4/24
   results; candidate branch/remote proof; plan, roadmap, manifest, guard/test
   blob digests; and old-process death. A child/model-produced record, a
   coordinator root inside the worktree, an unsealed/mutable coordinator
   identity, synthetic/laundered history, or a value not recomputable from
   Git/forge/process/run artifacts fails.
5. The coordinator prepares the exact clean fetched `I` worktree and launches:

   `PHASE_LOOP_HARDEN_COORDINATOR_TRANSITION=<absolute-coordinator-transition> PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli resume --repo . --roadmap specs/phase-plans-v10.md --phase HARDEN --governed --executor codex --model gpt-5.6-terra --effort high --lane-scheduler off --phase-scheduler off --closeout-mode manual --max-phases 1`

   The new repo-local runtime validates the transition and loaded module/Git
   identities before dispatch, then copies those exact bytes into its run-owned
   input area and records the source/destination hashes. Only after that check
   does its new
   `SL-2.5` path export `PHASE_LOOP_RUN_DIR=<candidate-run-dir>` to verification
   subprocesses, record `verification_stage=pre_seal`, run dependency refresh,
   exact 24-node focused, every ordinary command, and the broad compatible
   suite under `not dotfiles_integration`, then seal/validate
   `verification.json` and both JUnit files. The bootstrap fallback is forbidden
   in candidate/post-landing evidence: canonical JUnit must be under the
   exported runner-owned directory. The focused command removes
   `PHASE_LOOP_TDD_EXPECT_HARDEN`, requires marker activation, and reports exact
   24 passed/zero skipped.
6. The candidate runtime enters a bounded `awaiting_external_review` wait while
   remaining alive at unchanged `I`; it accepts only the declared run-owned
   panel-record path written by the immutable external coordinator. The
   coordinator launches a fresh exact-`I` repo-local isolated-panel boundary,
   not the legacy installed panel subprocess path. It sets
   `allow_api_key_fallback=False`; materializes the exact `I` tree and every
   approved `PanelRequest.context_refs` input into immutable `/review` paths;
   starts separate no-network/no-credential `linux_bwrap_v1` review legs for
   Fable, Sol, Gemini, and Grok; and keeps subscription auth/transport in the
   trusted parent control plane behind each exact typed broker adapter. Each
   seat must pass its direct mutation/credentialed-side-effect probes before
   returning a usable review. The sealed panel record binds each reviewed
   ref/hash, exact `I`, loaded boundary-module digests, plan digest, four
   supported route/checklist identities, boundary/broker/probe attestations,
   reviewed status/verdict/anchors, and author-vendor independence. A wait
   timeout, candidate exit, wrong writer/path/digest, changed HEAD, direct legacy
   route, refused/excepted/missing seat, or failed probe fails closed.
7. After a clean isolated panel, the fresh candidate runtime validates the
   coordinator panel record, reduces the honest supported/refused fleet
   checklist with the four panel-seat rows included, invokes:

   `phase-loop-runtime/scripts/verify_harden_evidence.py --lifecycle-stage candidate --repo . --roadmap specs/phase-plans-v10.md --plan plans/phase-plan-v10-HARDEN.md --phase HARDEN --run-dir <candidate-run-dir> --verification-json <candidate-run-dir>/verification.json --junit-xml <candidate-run-dir>/harden-compatible-suite.xml --fleet-checklist <candidate-run-dir>/harden-fleet-checklist.json --coordinator-transition <candidate-run-dir>/harden-coordinator-transition.json --governance-panel <candidate-run-dir>/harden-governance-panel.json --output <candidate-run-dir>/harden-candidate-evidence.json`

   and performs a parent-owned candidate audit. Passed candidate audit records
   `awaiting_phase_closeout`, never `complete`, then exits. A fix invalidates
   `C`, `I`, all clean-process results, seals, and panels and restarts with a new
   GPT-5.6 Terra child at step 1.
8. The external coordinator merges only exact `I` with ordered parents `[P,I]`,
   proves the candidate process gone, fetches server canonical main `M`,
   prepares a clean exact-`M` worktree, and writes a new post-landing transition.
   It launches the same repo-local command shape with the new exact transition.
   Startup fails closed unless local/remote `M`, the lifecycle-control,
   tests-only, and implementation ordered two-parent PR merges, actual
   `L -> T -> C -> I` ancestry, coordinator identity, and loaded
   repo-local module hashes all match and the PID/nonce is distinct from every
   earlier process.
9. The post-landing runtime repeats manifest, plan, roadmap, environment-
   activation-absent exact 24-node focused, broad compatible, Ruff, and
   exported-run-dir seal/JUnit validation. The coordinator then runs the
   mandatory exact-`M` Fable/Sol/Gemini/Grok panel through a fresh exact-`M`
   repo-local isolated-panel boundary with the same four supported rows,
   immutable staged inputs, parent-controlled subscription inference adapters,
   and direct mutation/credentialed-side-effect probes. It reduces a new fleet
   checklist and invokes:

   `phase-loop-runtime/scripts/verify_harden_evidence.py --lifecycle-stage post_landing --repo . --roadmap specs/phase-plans-v10.md --plan plans/phase-plan-v10-HARDEN.md --phase HARDEN --run-dir <main-run-dir> --verification-json <main-run-dir>/verification.json --junit-xml <main-run-dir>/harden-compatible-suite.xml --fleet-checklist <main-run-dir>/harden-fleet-checklist.json --coordinator-transition <main-run-dir>/harden-coordinator-transition.json --governance-panel <main-run-dir>/harden-governance-panel.json --candidate-evidence <main-run-dir>/harden-candidate-evidence.json --output <main-run-dir>/harden-evidence.json`

   The parent-owned `_audit_harden_post_suite_outputs()` re-opens both seals, all
   checkpoint/pre-push/focused/broad JUnit files, both checklists/evidence
   records, both external transition records, both isolated-panel records and
   their eight seat attestations, and server metadata; recomputes every hash,
   exact digest, coordinator/process/head/module identity, checkpoint/final
   commit tree/path/ancestry, ordered PR-merge parent, registry set, node
   partition/count/status, boundary/broker/probe result, and lifecycle edge; and
   matches them to parent state. Missing outputs return
   `post_suite_output_missing`; changed bytes/hashes return
   `post_suite_hash_mismatch`; stale coordinator/process/run/head/plan/roadmap/
   manifest/test/registry/cross-file identity returns
   `post_suite_identity_mismatch`; child-authored/self verification returns
   `self_verification_cycle`; synthetic or wrong checkpoint history returns
   `harden_checkpoint_history_mismatch`; wrong PR merge parents return
   `harden_merge_parent_mismatch`; an unisolated panel seat returns
   `review_boundary_attestation_failed`; and early completion returns
   `terminal_complete_before_final_audit`. These normalize to non-human
   `blocker_class=repeated_verification_failure`. Only the fresh exact-`M`
   process with `final_audit.status=passed` may authorize the terminal
   lifecycle-control landing; every failure retains the run-owned artifacts for
   diagnosis.
10. After that exact-`M` audit passes, the executor performs its normal
    `update_lifecycle(..., "completed", "codex-execute-phase", ...)` in a
    separate clean control worktree rooted at `M`. The coordinator applies the
    same exact-delta validator, commits only `plans/manifest.json` as `FH`, and
    lands a distinct manifest-only two-parent closeout PR as `F`. It proves
    ordered parents `[M, FH]`, a clean server tree, the byte-identical unique
    contract lookup, and equality of every non-manifest blob with audited `M`.
    The still-fresh exact-`M` parent may emit terminal `complete` only after
    this server proof; its loaded runtime modules are exact because `M` and `F`
    have identical code blobs. Any extra delta, failed/duplicate transition,
    merge race, or changed non-manifest blob blocks and requires a new clean
    exact-head audit rather than relabeling `F`.

## Execution Policy

- work-unit defaults: work-unit=`lane_execute`, effort=`high`, unsupported=`inherit_default`, inherit-default=`true`
- execute: executor=`codex`, model=`gpt-5.6-terra`, effort=`high`, work-unit=`lane_execute`, unsupported=`fallback`, fallback=`gpt-5.6-terra`, reason=`HARDEN is the Terra whole-phase authorship slot`
- SL-3: executor=`codex`, model=`gpt-5.6-terra`, work-unit=`phase_reducer`, effort=`high`, unsupported=`fallback`, fallback=`gpt-5.6-terra`, reason=`Terra-authored checkpoint/direct-child reduction plus candidate and post-landing fresh-process evidence after both functional lanes`

Policy precedence is CLI/operator override, this phase-plan policy, roadmap
policy, Dispatch Hints, then registry defaults. HARDEN is explicitly assigned
to Codex GPT-5.6 Terra for the whole code-writing phase: Terra authors the
tests-only RED lane and every implementation/reducer lane. No other vendor may
author a HARDEN code or test path. Cross-vendor lane rotation, the runtime lane
scheduler, and the runtime phase scheduler remain off. Terra-native workers are
allowed only with coordinator-owned independent worktrees and the disjoint
ownership above; the external coordinator alone performs the governed
commit/push/merge operations.

## Execution Notes

- Before any test work, the external coordinator records its immutable
  out-of-worktree identity and panels the exact SHA-256 of this plan by true
  `context_refs` with Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5.
  Fable and Sol are mandatory reviewing seats; API-key fallback is disabled and
  a degraded 3-of-4 result blocks. Because the boundary does not exist yet,
  this pre-implementation record is a TDD/governance prerequisite, never
  `EC-HARDEN-5` route evidence and never a substitute for the isolated exact-`I`
  or exact-`M` panel. The prior exact-digest `DISAGREE` record remains immutable
  historical evidence bound to its reviewed predecessor digest; it is not
  relabeled as approval, and this repaired digest requires a fresh unanimous
  panel before dispatch.
- After that exact-plan panel and before any test write, the installed executor
  first proves the checked-in manifest is production-serializer row-stable and
  that disposable real-API simulations of both HARDEN transitions preserve
  every sibling row exactly, then performs its normal `committed -> executing`
  manifest lifecycle update. The
  external coordinator treats `plans/manifest.json` as a single runner-owned
  control path, not a HARDEN lane path: it accepts only the exact API delta,
  lands it alone through the distinct two-parent control PR `L`, fetches the
  post-`L` target, and requires a clean tree. The tests-only and implementation
  PRs may not contain or repair the manifest. At checkpoint `C`, direct-child
  `I`, candidate, and exact-`M`, any manifest dirt is an ownership failure, not
  a planning/control exemption. After the exact-`M` audit, the normal completed
  append must likewise land alone as `F` before terminal `complete`.
- `SL-0` lands literally as tests only. No production source, executable,
  changelog, roadmap, manifest, or closeout implementation may share that
  commit. Land the test-owned guard and immutable tests through their own
  two-parent tests-only PR into the exact clean post-`L` target branch. On the fetched
  post-merge target, prove the marker-absent 5-pass/19-skip default and then the
  activated 24-nodeid/per-case intended RED results. Only after that may the
  coordinator create a distinct implementation branch from that head and later
  open the distinct implementation PR. Server-recorded PR target/base/head
  identities, ordered parents, lifecycle, actual PR range, and PR file set are
  evidence; local branch shape or a user-supplied base SHA is not.
- `SL-1` and `SL-2` are write-disjoint. Lane order does not waive the Terra
  whole-phase author policy or authorize lane/phase scheduler fanout.
- HARDEN is not write-disjoint from the current `CONFORM`, `FABPUB`, `LEGIBLE`,
  `PROOFGATE`, and `REVIEWTRUTH` phase plans. The overlapping phase-owned paths
  are `CHANGELOG.md`,
  `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`,
  `phase-loop-runtime/src/phase_loop_runtime/cli.py`,
  `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`,
  `phase-loop-runtime/src/phase_loop_runtime/launcher.py`,
  `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`,
  `phase-loop-runtime/src/phase_loop_runtime/runner.py`,
  `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`,
  `phase-loop-runtime/tests/test_goal_coverage.py`, and
  `phase-loop-runtime/tests/test_review_leg_sandbox.py`. The external
  coordinator must serialize HARDEN execution and merge against those phases,
  fetch the exact target, and rebase or regenerate the tests-only baseline
  before `SL-0`; scheduler-off status alone is not collision evidence.
- The GPT-5.6 Terra implementation child writes all phase-owned implementation
  paths and returns once; it may not stage for the coordinator, commit, push,
  transition, attest, panel, merge, or complete. The pre-change runtime runs
  with manual closeout, its missing `PHASE_LOOP_RUN_DIR` uses only the
  non-evidence bootstrap fallback, and any stale-module `complete` is rejected.
  After both old processes exit, the external coordinator alone creates actual
  checkpoint `C` from the exact `SL-1`+`SL-2` path list while retaining only the
  unchanged verifier/docs as dirty residuals. A separate clean exact-`C`
  worktree/process proves activated 13 + 7 green and exact 4 RED with the
  verifier absent. The coordinator then stages exactly the residual two paths
  into direct-child `I`; a new clean exact-`I` process removes the environment
  activation and proves marker-driven all-24 green. Only then may the
  coordinator push `I`, manually reopen a rejected false closeout, and write
  the transition. No loaded parent or child attestation is accepted, and no
  synthetic/re-written history can replace the two real commits.
  The fresh exact-candidate runtime exports its run directory and runs the
  complete compatible suite before its four-seat panel or merge. That panel
  runs through the exact-`I` isolation boundary and all four supported brokered
  seats. It exits before coordinator merge, and a second fresh
  exact-canonical-main runtime repeats both the suite and isolated exact-`M`
  panel. A repair, checkout, commit, direct legacy panel launch, or failed
  boundary/broker probe in either verifier process invalidates its evidence and
  restarts the `C`/`I` chronology.
- Both phase-loop scheduler controls are literal `off` for every HARDEN launch:
  `--lane-scheduler off --phase-scheduler off`. HARDEN performs no version
  bump, release dispatch, package publication, tag creation, or tag push.
- Execute, repair, plan, roadmap, and maintain-skills behavior are positive
  controls. Review-only CWD/environment/tool/auth changes must not leak into
  another product action.
- A reviewer subprocess or shell inside `linux_bwrap_v1` is permitted. A
  provider-backed route is supported only when the attacker-controlled
  review-leg process proves the common boundary and reaches a typed intended-
  inference-only method through `parent_unix_broker_v1`; otherwise it refuses
  before auth/session/broker/child. The trusted parent may retain first-party
  subscription auth and provider transport for intended inference only. It may
  not expose arbitrary provider methods, URLs, host commands, tools,
  credentials, or side-effect RPCs to the review leg. Fable, Sol, Gemini, and
  Grok must all be supported and directly probed at exact `I` and `M`; none may
  be refused, excepted, or relabeled. `context_refs`, route-specific CLI flags,
  prompts, CWDs, tool allowlists, and names cannot substitute. A live-repo
  mutation, credentialed/privileged side effect, live-root reachability,
  ambient credential source, direct/non-broker egress, host escape, or
  unjournaled cleanup path is forbidden.
- The phase produces no visible avatar/browser-media render;
  `visual_render_declared` remains false and image evidence is not required.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/src/phase_loop_runtime/injection.py`, `phase-loop-runtime/src/phase_loop_runtime/harness_env_signatures.py`, `phase-loop-runtime/src/phase_loop_runtime/capability_registry.py`, `phase-loop-runtime/src/phase_loop_runtime/claude_channel_sidecar.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/runtime_paths.py`, `phase-loop-runtime/src/phase_loop_runtime/reconcile.py`, `phase-loop-runtime/src/phase_loop_runtime/goal_coverage.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/src/phase_loop_runtime/verification_evidence.py`, `phase-loop-runtime/scripts/verify_harden_evidence.py`, `CHANGELOG.md`
- evidence paths: `plans/phase-plan-v10-HARDEN.md`, `plans/manifest.json`, `phase-loop-runtime/tests/harden_tdd_guard.py`, `phase-loop-runtime/tests/test_advisor_board_cli_legacy.py`, `phase-loop-runtime/tests/test_advisor_board_composition.py`, `phase-loop-runtime/tests/test_review_leg_sandbox.py`, `phase-loop-runtime/tests/test_phase_loop_injection.py`, `phase-loop-runtime/tests/test_reconcile_portability_85c.py`, `phase-loop-runtime/tests/test_goal_coverage.py`, `phase-loop-runtime/tests/test_verification_interpreter_guard_221.py`, `phase-loop-runtime/tests/test_harden_evidence_verifier.py`, `.phase-loop/events.jsonl`, `.phase-loop/runs/**/verification.json`, `.phase-loop/runs/**/harden-checkpoint-evidence.json`, `.phase-loop/runs/**/harden-prepush-evidence.json`, `.phase-loop/runs/**/harden-sl1.xml`, `.phase-loop/runs/**/harden-sl2.xml`, `.phase-loop/runs/**/harden-sl3-red.xml`, `.phase-loop/runs/**/harden-phase-focused.xml`, `.phase-loop/runs/**/harden-compatible-suite.xml`, `.phase-loop/runs/**/launch.json`, `.phase-loop/runs/**/terminal-summary.json`, `.phase-loop/runs/**/harden-coordinator-transition.json`, `.phase-loop/runs/**/harden-governance-panel.json`, `.phase-loop/runs/**/review-boundary-attestation*.json`, `.phase-loop/runs/**/harden-fleet-checklist.json`, `.phase-loop/runs/**/harden-candidate-evidence.json`, `.phase-loop/runs/**/harden-evidence.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

- `PYTHONPATH=phase-loop-runtime/src python3 skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-HARDEN.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.plan_manifest import read_manifest, validate_manifest; p = Path("plans").joinpath("manifest.json"); v = validate_manifest(p); assert v.valid, "; ".join(v.errors); plan_file = Path("plans").joinpath("phase-plan-v10-HARDEN.md").as_posix(); roadmap_file = Path("specs").joinpath("phase-plans-v10.md").as_posix(); matches = [e for e in read_manifest(Path(".")).plans if e.file == plan_file]; assert len(matches) == 1, f"expected one HARDEN manifest row, got {len(matches)}"; e = matches[0]; actual = (e.phase_alias, e.roadmap_ref.file if e.roadmap_ref else None, e.lanes); expected = ("HARDEN", roadmap_file, ("SL-0", "SL-1", "SL-2", "SL-3")); assert actual == expected, f"stale HARDEN manifest row: {actual!r}"'`
- `PYTHONPATH=phase-loop-runtime/src python3 -c 'import hashlib, json; from pathlib import Path; from phase_loop_runtime.plan_manifest import validate_manifest; p = Path("plans").joinpath("manifest.json"); plan_file = Path("plans").joinpath("phase-plan-v10-HARDEN.md"); roadmap_file = Path("specs").joinpath("phase-plans-v10.md"); v = validate_manifest(p); assert v.valid, "; ".join(v.errors); doc = json.loads(p.read_text()); rows = [r for r in doc["plans"] if r.get("slug") == "v10-HARDEN" or r.get("file") == plan_file.as_posix() or r.get("phase_alias") == "HARDEN"]; assert len(rows) == 1, f"expected one HARDEN identity row, got {len(rows)}"; r = rows[0]; assert (r.get("slug"), r.get("file"), r.get("phase_alias"), (r.get("roadmap_ref") or {}).get("file"), r.get("lanes")) == ("v10-HARDEN", plan_file.as_posix(), "HARDEN", roadmap_file.as_posix(), ["SL-0", "SL-1", "SL-2", "SL-3"]); events = r.get("lifecycle"); assert isinstance(events, list) and events; bearing = [e for e in events if isinstance(e, dict) and isinstance(e.get("metadata"), dict) and ("harden_plan_contract" in e["metadata"] or "harden_plan_contract_record_id" in e["metadata"])]; assert len(bearing) == 1, f"expected one HARDEN contract-bearing record, got {len(bearing)}"; event = bearing[0]; assert events[0] is event and event.get("transition") == "committed" and event.get("by") == "codex-plan-phase"; metadata = event["metadata"]; assert metadata.get("harden_plan_contract_record_id") == "v10-HARDEN.harden-plan-contract.v1"; c = metadata.get("harden_plan_contract"); assert isinstance(c, dict); transitions = [e.get("transition") for e in events]; assert transitions in (["committed"], ["committed", "executing"], ["committed", "executing", "completed"]), transitions; assert r.get("status") == transitions[-1] and r.get("updated_at") == events[-1].get("at"); executing = [e for e in events if e.get("transition") == "executing"]; assert len(executing) == (0 if transitions == ["committed"] else 1); assert not executing or (executing[0].get("by") == "codex-execute-phase" and executing[0].get("metadata", {}).get("phase_alias") == "HARDEN" and isinstance(executing[0].get("metadata", {}).get("run_id"), str) and executing[0]["metadata"]["run_id"]); payload = {k: value for k, value in c.items() if k != "plan_sha256"}; assert hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == "5b5c9bbe8fa97a343c831b5f4829df05305ea19f01d71fd1c5d4e9698f554982"; digest = lambda xs: hashlib.sha256((chr(10).join(xs) + chr(10)).encode()).hexdigest(); assert c["plan_sha256"] == hashlib.sha256(plan_file.read_bytes()).hexdigest(); assert c["roadmap_sha256"] == hashlib.sha256(roadmap_file.read_bytes()).hexdigest() == "1e8ea70ceae55d326cd84b092e1b9e879180d7b0e774140c3dd00e6ed63b7071"; assert (len(c["owned_paths"]), c["owned_paths_count"], digest(c["owned_paths"]), c["owned_paths_sha256"]) == (25, 25, "24ec10238f27645f38893625fc78f389bd6a97168d99c611f18cb2fab6a1d6d2", "24ec10238f27645f38893625fc78f389bd6a97168d99c611f18cb2fab6a1d6d2"); assert (len(c["test_paths"]), c["test_paths_count"], digest(c["test_paths"]), c["test_paths_sha256"]) == (9, 9, "c46927b02d8d3cfa41198aae1d8a3185728f8df1e8096083191976f02628fbc9", "c46927b02d8d3cfa41198aae1d8a3185728f8df1e8096083191976f02628fbc9"); assert (len(c["checkpoint_paths"]), c["checkpoint_paths_count"], digest(c["checkpoint_paths"]), c["checkpoint_paths_sha256"]) == (14, 14, "4ae07bb2a4b895f3d4a0f812b51bd3f3212d69569f1c536dff83e641470811dc", "4ae07bb2a4b895f3d4a0f812b51bd3f3212d69569f1c536dff83e641470811dc"); assert (c["expected_nodeids"], c["sl1_nodeids"], c["sl2_nodeids"], c["sl3_evidence_nodeids"], c["default_skip_nodeids"], c["nodeid_delta"], c["nodeid_inventory_sha256"]) == (24, 13, 7, 4, 19, 2, "20f358e6a3482a773cb28ed78eb6fa8e49353e2425a5d182a282eb8d7afb4b8f")'`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -c 'import os, subprocess, sys, tempfile; from pathlib import Path; from harden_tdd_guard import EXPECTED_PHASE_NODEIDS, SL1_NODEIDS, SL2_NODEIDS, SL3_EVIDENCE_NODEIDS; assert len(EXPECTED_PHASE_NODEIDS) == 24 and len(SL1_NODEIDS) == 13 and len(SL2_NODEIDS) == 7 and len(SL3_EVIDENCE_NODEIDS) == 4; assert set(EXPECTED_PHASE_NODEIDS) == set(SL1_NODEIDS) | set(SL2_NODEIDS) | set(SL3_EVIDENCE_NODEIDS); assert not (set(SL1_NODEIDS) & set(SL2_NODEIDS) or set(SL1_NODEIDS) & set(SL3_EVIDENCE_NODEIDS) or set(SL2_NODEIDS) & set(SL3_EVIDENCE_NODEIDS)); root = os.environ.get("PHASE_LOOP_RUN_DIR"); junit = Path(root).joinpath("harden-phase-focused.xml") if root else Path(tempfile.mkdtemp(prefix="harden-bootstrap-focused-")).joinpath("harden-phase-focused.xml"); raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", *EXPECTED_PHASE_NODEIDS, "-q", f"--junitxml={junit}"]))'`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_advisor_board_composition.py -q -k "test_cli_harden_preflight_authorizes_before_compose_and_invoke or test_harden_preflight_authorizes_before_every_capability_auth_ok"`
- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests -q -m "not dotfiles_integration"`
- `ruff check phase-loop-runtime/src/phase_loop_runtime phase-loop-runtime/scripts`
- `git diff --check`
- `git diff --cached --check`

The frontmatter `automation.suite_command` is an executable fail-fast composite:
it first runs the same stable-identity HARDEN contract lookup listed in
`## Verification`, then runs the broad compatible suite with structured JUnit.
That lookup validates the entire manifest, selects one row across the stable
slug/file/phase identities, requires exactly one contract-bearing event with
record id `v10-HARDEN.harden-plan-contract.v1`, validates the lifecycle
sequence/status/timestamps, seals the complete contract payload other than the
separately recomputed plan digest, and never assumes the contract event is
latest. Thus committed planning, clean post-`L` executing, candidate/exact-`M`
executing, and terminal completed-control commands consume the same lookup;
missing, duplicate, conflicting, or drifted records fail before tests. The
pre-change bootstrap
runtime does not export `PHASE_LOOP_RUN_DIR`, so that first pass uses `mktemp`
and is explicitly non-evidence. Candidate and post-landing runtimes contain the
new export path and must write JUnit beneath their parent-owned run directory;
the evidence verifier rejects the fallback there. The exact-`C` process first
proves activated 13 + 7 green and exact 4 RED with the verifier absent; a
different clean exact-`I` process then removes the environment activation and
proves all 24 green after direct-child `I` introduces the verifier. Candidate
and post-landing exact 24-node commands also run with environment activation
absent before the broad suite. Both fresh runtimes seal before their isolated
exact-head panel. HARDEN chronology, raw RED, author independence, crash
cleanup, four-seat boundary/broker probes, and fleet evidence become decidable
only through the two post-suite reductions and fresh-parent audits above; they
must never be represented as pre-seal suite evidence.

## Acceptance Criteria

- [ ] EC-HARDEN-0 — proven by the frozen guard's default 5-pass/19-skip JUnit, activated 24-nodeid and per-case raw intended-RED/JUnit records, and passed fresh-parent `_audit_harden_post_suite_outputs()` plus terminal lifecycle-control audit; the audits must prove immutable tests/guard; exact manifest validation through the stable unique contract record, including fail-closed missing/duplicate/conflict/drift cases, canonical sixteen-key current-row normalization, production-serializer parsed-row stability, disposable real-API `committed -> executing -> completed` simulation with zero sibling drift, 25/9/14 path counts and SHA-256 values, and the 24-node inventory digest; the normal executing append as the sole pre-lane dirty path; exact manifest-only ordered two-parent control merge `L` before tests branch creation; ordered two-parent tests and implementation PR merges; implementation PR range excluding every `SL-0` path, the tests-only commit, and `plans/manifest.json`; immutable out-of-worktree coordinator identity; manual closeout plus rejected/manually reopened old-runtime false completion; whole-phase GPT-5.6 Terra child exit without commit; both runtime schedulers off; coordinator-only commits/push/merge; no release/tag/publish action; actual direct ancestry `L -> T -> C -> I`; checkpoint `C` containing exactly changed `SL-1`+`SL-2` paths while the manifest is clean; unchanged two-path `SL-3` residual containment with no hidden third manifest residual; no synthetic/history-laundering mechanism; a distinct clean exact-`C` process proving activated exact 13 green + 7 green + 4 RED with verifier absent; a distinct clean exact-`I` process proving environment-activation-absent all 24 green only after verifier/docs commit `I`; distinct candidate/main processes and exact loaded heads/modules; exported run dirs only in new runtimes; broad compatible suite before each isolated exact-head four-seat panel; candidate `--lifecycle-stage candidate` evidence; post-landing `--lifecycle-stage post_landing` evidence; exact completed append and manifest-only ordered two-parent closeout merge `F` preserving every non-manifest blob from audited `M`; and the lifecycle normal executing append → control merge `L` → tests merge → activated RED → Terra child exit → real checkpoint `C` → clean 13/7/4 proof → real direct-child `I` → clean all-24 proof → push/transition → fresh candidate suite/isolated four-seat panel/audit → ordered two-parent implementation merge → fresh canonical-main suite/isolated exact-head four-seat panel/final audit → completed-control merge `F` → terminal complete
- [ ] EC-HARDEN-1 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_review_leg_sandbox.py -q -k review_stage_rejects_every_escape_form_before_launch`
- [ ] EC-HARDEN-2 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_reconcile_portability_85c.py -q -k "cwd_independent or repo_anchored"`
- [ ] EC-HARDEN-3 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_goal_coverage.py -q -k "enforce_blocks_every_zero_declared or all_bare_legacy_is_distinct"`; both selected tests must pass, and the all-bare test must prove warn/default is nonblocking while every enforce completion gate returns non-human `contract_bug`
- [ ] EC-HARDEN-4 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_verification_interpreter_guard_221.py -q -k argument_consuming_bash_options_and_profile_patch_version_fail_closed`; the selector must enumerate `-o option-name`, `+o option-name`, `-O shopt-option`, `+O shopt-option`, `--rcfile file`/`--rcfile=file`, and `--init-file file`/`--init-file=file`
- [ ] EC-HARDEN-5 — proven jointly by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest phase-loop-runtime/tests/test_advisor_board_cli_legacy.py::AdvisorBoardCliTest::test_cli_harden_preflight_authorizes_before_compose_and_invoke phase-loop-runtime/tests/test_advisor_board_composition.py::AuthAwareCompositionTests::test_harden_preflight_authorizes_before_every_capability_auth_ok phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_phase_loop_injection.py -q -k "harden_preflight_authorizes or review_isolation_registry_matrix or review_capability_registry_set_equality or every_executable_review_route or review_snapshot_materializes or review_prompt_argv_cwd_and_env or crash_recovery"` and the passed runner-owned post-suite final audit; for CLI, bare-default, explicit-auth, and config-loaded composition, the credentialless isolation/broker preflight must run and authorize the operation before the first availability/registry/provider lookup, capability `auth_ok()` invocation, subscription access, seat construction, or other composition side effect, while denial/forgery proves none of those canaries fires; `invoke_board()` independently revalidates the authorization before artifact/context, gateway/research, seat-env/auth, provider/broker/session, or spawn work; the credentialless command adapter executes only after exact Linux/bubblewrap/namespace/probe success; Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5 are all mandatory supported subscription-only routes whose exact-`I` and exact-`M` panel legs receive only immutable staged snapshots/context refs, read-only tools, no live repo, mutation credentials, privileged side-effect capability, direct network, or host escape, and whose parent-controlled first-party subscription transport/auth exposes only the typed intended-inference RPC through exact `parent_unix_broker_v1` adapters; all four carry direct live-tree mutation and credentialed-side-effect probe attestations at both heads; every other executable provider/API-key/native/gateway/research route satisfies the same isolation or refuses before auth/session/broker/child; manual remains nonlaunch; refusal satisfies the invariant only through non-execution and is never mislabeled supported conformance; checklist/live-registry set equality includes and cross-links the four mandatory panel rows; no `context_refs`, CLI flag, prompt, naming distinction, residual register, pre-seal result, invoker-only preflight, or self-reported closeout field is a satisfaction route
