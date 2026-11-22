---
phase_loop_plan_version: 1
phase: JEVHOST
roadmap: specs/phase-plans-jevhost-v1.md
roadmap_sha256: 79dae858f5b456625b4cb72e751fb91085d9280e7dfa87b6125d2d3b6dfc4ee7
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PHASE_LOOP_TDD_EXPECT_SCHED=1 PYTHONPATH=$PWD/src:$PWD/tests timeout 1800 .venv/bin/python -m pytest -q -p no:cacheprovider -m 'not dotfiles_integration' tests/test_jevdrill_selection.py tests/test_jevdrill_install_preflight.py tests/test_jevdrill_runner_lanes.py tests/test_jevdrill_launch_merge.py tests/test_jevdrill_companion_workflow.py tests/test_jevdrill_receipt.py tests/test_jevdrill_adapter.py tests/test_jevdrill_diagnostics.py tests/test_jevdrill_discovery.py tests/test_jevdrill_input.py tests/test_jevdrill_queue.py tests/test_jevdrill_usage.py tests/test_launcher_liveness.py tests/test_phase_loop_launcher.py tests/test_phase_loop_work_unit_observability.py tests/test_windows_locking.py tests/test_windows_processes.py tests/test_windows_storage.py tests/test_launch_audit_inventory.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py"]
---

# JEVHOST: JEV Drill host adapter on main

## Context

The owner assigned the sanitized draft agent-harness#2071 to this repository on 2026-11-22,
to be brought to a merged state on `main`. The JEV Drill project will pin one accepted
commit under conditions R1 to R6. JEVHOST §1 quotes them, and the JEV president's binding
clarification is in JEVHOST §1.1. This plan lands the draft through one new integration
pull request from current `main`. It does not rebase the draft branch.

**Revision 3 (2026-11-22).** It applies the round-2 review of agent-harness#2083 and the JEV
president's clarification. Each change carries its tag in the contract.
- [B4] The Codex probe is an owned launch.
- [B5] The test harness configures on native Windows. SL-0 now owns `conftest.py` and
  `launch_audit_hook.py`.
- [C1] to [C9]:
  - the route test's own skip is removed, and a preflight fails a broken install;
  - a receipt leg with a four-reason skip allowlist, and an installed leg with both
    variables;
  - the LEARN whole-file rule and name stability;
  - no 3.14 harness leg counts as evidence;
  - JEV Drill runs on `cpython-3.14`.
- The lanes are re-sequenced. The adapter lane (now SL-3) precedes the launcher lane (now
  SL-4), so the probe tests in `test_jevdrill_usage.py` run in the lane that owns
  `launcher.py`. SL-4 stays the inventory reducer.
- r3 goes to a president ruling, not a third review round.

**Revision 3.1 (2026-11-22).** It applies the president's ruling (merge-ready after three
in-place fixes):
- [P1] SL-3 only collects the adapter and discovery tests, because they need SL-4's
  launcher surface. SL-4 runs them.
- [P2] The usage probe never runs on review (contract S2). SL-4 adds an eighth test case,
  and EC-JEVHOST-3 gains a falsifier.
- [P3] The coordinator dispatches Gate A on the exact head before the merge.
- The binding classifier note, the tree hashes, the `panel_invoker.py` redo trigger and the
  deferred env allowlist (agent-harness#2084) are folded in.

**Frozen input.** JEVHOST (`plans/artifacts/jevhost-v1-contract.md`, pinned by sha256 in
the roadmap's External Inputs) holds every procedure, resolution and rule this plan cites.
It is read-only during execution.

**What the plan decides, and where.**

| Decision | Where |
|---|---|
| R1 to R6, and the binding clarification | JEVHOST §1, §1.1 |
| Path-scoped replay, file classes, the preservation rule | JEVHOST §2 |
| Each conflicting hunk's resolution | JEVHOST §3 |
| Semantic rules S1 to S6, including the owned probe and Windows configuration | JEVHOST §4 |
| jevdrill SHA, byte comparison, fixture substitution, digests | JEVHOST §5 |
| Marker, preflight, eight controls, LEARN whole-file, name stability | JEVHOST §6 |
| R5 names | JEVHOST §7 |
| Receipt and installed legs, allowlist, pairing, sync command | JEVHOST §8 |
| Dropped paths, disclosure; stop rules; concurrent writers | JEVHOST §9 to §11 |
| Source inventories, owner, roles | JEVHOST §13 |
| The answered JEV questions | JEVHOST §14 |

**Shared-host rule.** Only the files a lane lists, serially without `-n`, with
`-p no:cacheprovider`, under `timeout`, after a headroom check (`free -h`,
`/proc/loadavg`, `/proc/pressure/memory`). Defer to hosted CI if headroom is short. No
full suite runs locally on a shared host. [P3] Dispatches are different: a `gh workflow run`
dispatch executes on hosted runners, not on the shared host. Gate A and the companion
dispatch of SL-5 are therefore required, not forbidden. Do not run
`tests/test_panel_invoker.py` or any test that launches a provider.

## Interface Freeze Gates

- [ ] IF-0-JEVHOST-1 — JEVHOST §2 to §4: replay by path from the draft commit over its base (both pinned in the roadmap's External Inputs); hunks A1, A2, L1 to L7, R1, T1, T2; rules S1 to S6.
- [ ] IF-0-JEVHOST-2 — JEVHOST §5: the 14 schemas and 3 fixtures at the pinned jevdrill commit or a later `main` commit under the SHA rule, the placeholder substitution, raw-bytes `digests.json`.
- [ ] IF-0-JEVHOST-3 — JEVHOST §6, §7: the `jevdrill_installed` marker and its conftest rules, `tests/jevdrill_install.py`'s `resolve_install()`, `tests/test_jevdrill_selection.py`, `tests/data/jevdrill_test_names.json`, the R5 names.
- [ ] IF-0-JEVHOST-4 — JEVHOST §8: `.github/workflows/jevdrill-companion.yml` (receipt and installed legs, dispatched legs, `jevdrill_ref`), `scripts/jevdrill_receipt.py` and its allowlist constant, the sync command, CI Python 3.12 paired with JEV Drill on CPython 3.14.

## Lane Index & Dependencies

SL-0 — PORT: platform primitives, cleanly merging modules and the Windows-safe test harness
  Depends on: (none)
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-1 — CONTRACT: fixture and schema copies at the jevdrill commit
  Depends on: (none)
  Blocks: SL-2, SL-3
  Parallel-safe: yes

SL-2 — WORKFLOW: the companion workflow, the receipt classifier and their tests
  Depends on: SL-1
  Blocks: SL-5
  Parallel-safe: yes

SL-3 — ADAPTER: adapter, queue, runner conflict, installed-JEV tests and preflight
  Depends on: SL-0, SL-1
  Blocks: SL-4
  Parallel-safe: no

SL-4 — LAUNCH: launcher conflicts, launcher and usage tests, selection and the source inventories
  Depends on: SL-0, SL-3
  Blocks: SL-5
  Parallel-safe: no

SL-5 — DOCS: integration page, changelog, dispatch and the pull request's disclosure (reducer)
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4
  Blocks: (none)
  Parallel-safe: no

## Lanes

Source paths are under `phase-loop-runtime/src/phase_loop_runtime/`. Test paths are under
`phase-loop-runtime/`. Verify commands run from `phase-loop-runtime/` after
`uv sync --project . --group test --extra visual --locked`, with
`PYTHONPATH=$PWD/src:$PWD/tests` and `PHASE_LOOP_TDD_EXPECT_SCHED=1`.

### SL-0 — PORT: platform primitives, cleanly merging modules and the Windows-safe test harness

- **Scope**: Bring in the portability modules verbatim and three-way merge the cleanly merging modules (S1, S5). Make the test harness configure on native Windows [B5]. Own the marker rules in `conftest.py` and the marker line in `pyproject.toml` (JEVHOST §6).
- **Owned files**: `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/launch_audit_hook.py`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/tests/test_phase_worktree_executor.py`, `phase-loop-runtime/src/phase_loop_runtime/file_lock.py`, `phase-loop-runtime/src/phase_loop_runtime/windows_process.py`, `phase-loop-runtime/src/phase_loop_runtime/windows_storage.py`, `phase-loop-runtime/src/phase_loop_runtime/dispatch_lock.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py`, `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`, `phase-loop-runtime/src/phase_loop_runtime/prompts.py`, `phase-loop-runtime/src/phase_loop_runtime/observability.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py`, `phase-loop-runtime/tests/test_windows_locking.py`, `phase-loop-runtime/tests/test_windows_processes.py`, `phase-loop-runtime/tests/test_windows_storage.py`
- **Interfaces provided**: `file_lock.acquire_exclusive`, `release_exclusive`, `open_generation_lease`; `windows_process.run_owned`, `process_is_live`, `start_leased_guardian`; `windows_storage.BoundDirectory`; the `jevdrill_installed` marker, its fixed skip reason and both collection errors (JEVHOST §6)
- **Interfaces consumed**: (none)
- **Parallel-safe**: yes
- **Tasks**:
  - test: restore the three `test_windows_*.py` files verbatim, plus a POSIX case in `test_windows_locking.py`: no module-level `fcntl` reference in `agy_qualification` (S1).
  - test: [B5] `tests/test_launch_audit_inventory.py` stays green, with the POSIX branch of `launch_audit_hook.install` unchanged.
  - impl: restore `file_lock.py`, `windows_process.py` and `windows_storage.py` verbatim. Do the per-file three-way merge of the other nine modules. Resolve A1 and A2, apply S1, and apply S5's `live.py` guards.
  - impl: [B5] apply the `os.name == "posix"` guards of S5 to `launch_audit_hook.py` and to any autouse fixture in `conftest.py` that needs one. Add the marker registration, the skip rule and both collection errors to `conftest.py`, and the marker line to `pyproject.toml`. Run `uv lock --check --project .`, and change `uv.lock` only under JEVHOST §8.
  - verify: `timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_windows_locking.py tests/test_windows_processes.py tests/test_windows_storage.py tests/test_launch_audit_inventory.py tests/test_dispatch_lock_helper.py tests/test_dispatch_lock_reentrancy.py tests/test_dispatch_lock_same_roadmap.py tests/test_dispatch_lock_cross_roadmap.py tests/test_agy_qci.py tests/test_agy_self_qualification.py tests/test_agy_provenance_wiring.py tests/test_convergence_event_log.py tests/test_convergence_fencing.py tests/test_convergence_broker_api.py tests/test_phase_worktree_executor.py tests/test_observability_alerting.py`, then `git diff origin/main -- tests/test_agy_qci.py` is empty. The Windows proof is SL-5's dispatched `windows-2025` legs.

### SL-1 — CONTRACT: fixture and schema copies at the jevdrill commit

- **Scope**: Create `tests/fixtures/jevdrill/` from jevdrill's own bytes under JEVHOST §5.
- **Owned files**: `phase-loop-runtime/tests/fixtures/jevdrill/**`
- **Interfaces provided**: `IF-0-JEVHOST-2`
- **Interfaces consumed**: (none)
- **Parallel-safe**: yes
- **Tasks**:
  - test: a scratch check script (not committed). It fetches the 14 schemas and 3 fixtures at the named SHA. It runs `cmp` on every schema, compares every fixture after the reverse substitution, and recomputes `digests.json`. It fails on the draft's files first.
  - impl: steps 1 to 3 of JEVHOST §5. Re-check jevdrill `main` before the push, under the SHA rule.
  - verify: the script exits 0. `grep -c 'utf8-bytes-upper-bound-v1' tests/fixtures/jevdrill/*.json` prints only zeros. Only owned files change.

### SL-2 — WORKFLOW: the companion workflow, the receipt classifier and their tests

- **Scope**: The non-required companion workflow, with its receipt and installed legs and dispatched legs [C3], and the receipt classifier with its four-reason allowlist (JEVHOST §8).
- **Owned files**: `.github/workflows/jevdrill-companion.yml`, `phase-loop-runtime/scripts/jevdrill_receipt.py`, `phase-loop-runtime/tests/test_jevdrill_companion_workflow.py`, `phase-loop-runtime/tests/test_jevdrill_receipt.py`
- **Interfaces provided**: `IF-0-JEVHOST-4`
- **Interfaces consumed**: `IF-0-JEVHOST-2` from SL-1 (the synced SHA, held as a constant)
- **Parallel-safe**: yes
- **Tasks**:
  - test: [C4] `test_jevdrill_companion_workflow.py` asserts the full shape list of JEVHOST §8 [C4].
  - test: `test_jevdrill_receipt.py` covers the classifier on synthetic junit:
    - each allowlisted reason passes only on its allowed legs;
    - an unknown reason fails;
    - a `jevdrill_installed` skip with a variable set fails;
    - an expected installed node that is missing or not passed fails;
    - a failure or an error fails.
  - impl: the classifier; then the workflow, with its receipt leg, installed leg, the dispatched macOS and Windows legs, and the labelled informational 3.14 harness leg [C8], with JEV Drill on `cpython-3.14` and its interpreter recorded [C9].
  - verify: `timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_jevdrill_companion_workflow.py tests/test_jevdrill_receipt.py tests/test_python_floor_1546.py`

### SL-3 — ADAPTER: adapter, queue, runner conflict, installed-JEV tests and preflight

- **Scope**: Bring in the adapter, queue and helpers, and the adapter, discovery and queue tests. Resolve R1 and S4 in the runner. Mark the installed-JEV tests per test. Remove the route test's own skip [C1]. Add the install preflight [C2].
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/jevdrill_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/jevdrill_queue.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_jevdrill_adapter.py`, `phase-loop-runtime/tests/test_jevdrill_discovery.py`, `phase-loop-runtime/tests/test_jevdrill_queue.py`, `phase-loop-runtime/tests/jevdrill_fixture_values.py`, `phase-loop-runtime/tests/jevdrill_install.py`, `phase-loop-runtime/tests/phase_loop_test_utils.py`, `phase-loop-runtime/tests/test_jevdrill_install_preflight.py`, `phase-loop-runtime/tests/test_jevdrill_runner_lanes.py`
- **Interfaces provided**: `jevdrill_adapter.JevDrillTransport`, `JevDrillUnavailable`, `JevDrillAdapter`, `build_jevdrill_request`, `launch_jevdrill`; `jevdrill_queue.ReportQueue`; `runner.discover_jevdrill_work_units`; `test_jevdrill_adapter.adapter_fixture`, `FIXTURES`; `jevdrill_install.resolve_install`
- **Interfaces consumed**: `IF-0-JEVHOST-2` from SL-1; SL-0's `file_lock`, `windows_storage` and the marker rules; `launcher.launch_with_spec`, `build_launch_spec`, `launch` (pre-existing); `lane_wave_executor.execute_lane_waves` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: `test_jevdrill_runner_lanes.py`, red before the impl task:
    - under the default `lane_scheduler_mode`, an adapter run enters `prepare` once and `launch` once, never `execute_lane_waves`, and records one `lane_scheduler` event with reason `jevdrill_adapter`;
    - with no adapter, the lane-wave path is as on `main`.
  - test: [C2] `test_jevdrill_install_preflight.py` uses `pytester`. A missing path, a non-executable file and a non-JEV executable, for each variable alone and both together, each report **failed**. Neither variable set reports skipped with the fixed reason.
  - test: restore the three test files and `jevdrill_fixture_values.py`. They must collect clean here and run in SL-4 [P1]. Mark the installed-JEV tests per test. [C1] Remove the route test's own `pytest.skip` and derive its CLI per JEVHOST §6. Route the fixture and the route test through `resolve_install()`. Three-way merge `phase_loop_test_utils.py`. Update any count or v1-only assertion SL-1's sync moves, and report each one.
  - impl: restore `jevdrill_adapter.py` and `jevdrill_queue.py` verbatim. Write `jevdrill_install.py` [C2] with the `usage: jevdrill` prefix check and the same-install check. Per the ruling, there is no schema or version command at the pin. Do the three-way merge of `runner.py` with R1, then S4.
  - verify: `timeout 1200 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not dotfiles_integration" tests/test_jevdrill_runner_lanes.py tests/test_jevdrill_install_preflight.py tests/test_jevdrill_queue.py tests/test_lane_wave_executor.py`, then `timeout 1200 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_phase_loop_runner.py`.
  - verify (collect only) [P1]: `timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider --collect-only tests/test_jevdrill_adapter.py tests/test_jevdrill_discovery.py`. This proves the imports, the per-test markers and both collection errors. These two files need SL-4's launcher surface (`codex_usage_capture`, `result.jevdrill_usage`, `launcher._codex_executor_input_manifest`), so SL-4 runs them.

### SL-4 — LAUNCH: launcher conflicts, launcher and usage tests, selection and the source inventories

- **Scope**: Merge the draft's launcher into `main`'s (L1 to L7, T1, T2, S2 with the owned probe [B4], S3, S6). Bring in the usage, diagnostics and input tests. Add the selection, LEARN whole-file and name-stability checks [C6] [C7]. Reconcile the source inventories for the whole phase (JEVHOST §13).
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/tests/test_launcher_liveness.py`, `phase-loop-runtime/tests/test_phase_loop_launcher.py`, `phase-loop-runtime/tests/test_phase_loop_work_unit_observability.py`, `phase-loop-runtime/tests/test_jevdrill_launch_merge.py`, `phase-loop-runtime/tests/test_jevdrill_usage.py`, `phase-loop-runtime/tests/test_jevdrill_diagnostics.py`, `phase-loop-runtime/tests/test_jevdrill_input.py`, `phase-loop-runtime/tests/test_jevdrill_selection.py`, `phase-loop-runtime/tests/data/jevdrill_test_names.json`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`
- **Interfaces provided**: `IF-0-JEVHOST-1` (complete), `IF-0-JEVHOST-3` (complete); `launcher._CodexUsageCollector`, `launcher._native_windows`, `launch(..., _codex_usage_observer=, _launch_deadline=)` alongside `main`'s `action`, `_review_profile`
- **Interfaces consumed**: SL-0's `windows_process` interfaces and marker rules; SL-3's `adapter_fixture` and `resolve_install`; `panel_invoker.launch_owned`, `SeatLaunchRole`, `SeatProfile`, `_redact_seat_credentials` (pre-existing); `executable_dependency_startup.current_dependency_for_provider` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: [N9] `test_jevdrill_launch_merge.py`, eight cases, red before the impl task:
    - S2: `validate_command` runs before the probe and again as the last call before `launch`;
    - S2: a mismatched binary is never probed;
    - [B4] with `main`'s audit hook active, the probe runs through `launch_owned` with `role=EXECUTOR_TRUSTED`, with the owned marker set;
    - S3: a seat-credential line is redacted before every sink;
    - S3: with `_native_windows()` patched true, `launch(action="review")` raises `review_unsupported_on_windows` before any spawn;
    - S3: with that seam patched true, a non-review `ephemeral_monitor` launch forwards `action`, `_review_profile` and both usage keywords;
    - L4: the review recursion forwards `_launch_deadline`, and forwards `_codex_usage_observer` as `None`;
    - [P2] a Codex `exec --json` spec with `product_action="review"` and `codex_usage_capture=True` starts no probe and records `{"capture": "disabled", "reason": "unsupported_path_or_probe"}`, with `launch_owned` and `Popen` patched to fail on `--version`.
  - test: restore `test_jevdrill_usage.py`, `test_jevdrill_diagnostics.py` and `test_jevdrill_input.py` verbatim. Apply the T1 and T2 merges and the draft's edits to `test_phase_loop_work_unit_observability.py`.
  - test: `test_jevdrill_selection.py` (JEVHOST §6, §7) asserts:
    - the eight control node IDs exactly, with the installed split;
    - collecting the seven R4 files deselects nothing;
    - [C6] the static LEARN whole-file rule;
    - [C7] collected node IDs equal `tests/data/jevdrill_test_names.json`, generated once from the draft;
    - every R5 import;
    - an informational, non-gating report of the JD-084 launcher tests.
  - test: run the five inventory tests of JEVHOST §13. They are red where new sites are unlisted.
  - impl: the per-file three-way merge of `launcher.py`, with L1 to L7, S2 including the owned probe [B4], S3 and the `_native_windows()` seam. Then S6 across the lane's tests.
  - impl: reconcile `seat_launch_references.json` and the 1147 `INVENTORY` for every site of SL-0, SL-3 and SL-4, by the role table of JEVHOST §13, including the [N10] `windows_process` rows. List each added row with its role for the PR. A site the table does not cover is a stop.
  - verify: `timeout 1800 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not dotfiles_integration" tests/test_jevdrill_adapter.py tests/test_jevdrill_discovery.py tests/test_jevdrill_launch_merge.py tests/test_jevdrill_usage.py tests/test_jevdrill_diagnostics.py tests/test_jevdrill_input.py tests/test_jevdrill_selection.py tests/test_launcher_liveness.py tests/test_phase_loop_launcher.py tests/test_phase_loop_work_unit_observability.py tests/test_launcher_exec_supervisor.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_resource_caps.py tests/test_seat_launch_helpers_trusted.py tests/test_gate_fail_open_visibility.py`.
    - Deselect any `real_seat_caps` or `host_seat_credentials` test.
    - Then run `timeout 120 python3 scripts/check_model_id_sources.py`.
    - Then run the receipt classifier over a junit of the twelve files from this lane's tree, with neither variable set. It must pass, including the [N-RC] completeness rules.
  - verify (installed, optional locally, only with headroom) [P1]:
    - check out jevdrill at the synced SHA into a scratch directory under `$HOME`;
    - run `uv sync --locked --python cpython-3.14` there;
    - set both variables;
    - rerun the discovery and adapter tests with zero skips.

    Otherwise defer to SL-2's installed leg.

### SL-5 — DOCS: integration page, changelog, dispatch and the pull request's disclosure

- **Scope**: Update the integration page and the changelog. Dispatch the companion workflow once on the integration head. Write the R-condition disclosure, and back-fill the post-dispatch results.
- **Owned files**: `docs/jevdrill-integration.md`, `CHANGELOG.md`
- **Interfaces provided**: the pull request body's R1 to R6 statement
- **Interfaces consumed**: `IF-0-JEVHOST-1`, `IF-0-JEVHOST-2`, `IF-0-JEVHOST-3`, `IF-0-JEVHOST-4`
- **Findings consumed**:
  - SL-1's synced SHA and any moved assertion;
  - SL-0's S5 and [B5] outcomes;
  - SL-3's preflight command and S4 outcome;
  - SL-4's S2, S3 and [B4] outcomes, its added inventory rows and any renames;
  - SL-2's run links.
- **Parallel-safe**: no
- **Tasks**:
  - test: `timeout 120 .venv/bin/python -m phase_loop_runtime.entry_doc_check --repo ..` and `timeout 120 .venv/bin/python -m phase_loop_runtime.cli docs-audit --repo .. --base origin/main --json`.
  - impl: restore `docs/jevdrill-integration.md` and amend it with:
    - S4;
    - the marker, its skip rule and the preflight;
    - the receipt and installed legs and the pairing;
    - review being refused on native Windows;
    - the dropped October evidence.

    Add a `CHANGELOG.md` entry.
  - impl: once, on the exact integration head, dispatch the companion workflow with the synced SHA. [P3] Alongside it, the coordinator dispatches Gate A: `gh workflow run test.yml --ref <branch> -f chronology=false`. Both run on hosted runners.
    - If GitHub refuses the companion dispatch because the workflow is not yet registered, §8's "leg not run" disclosure applies, and the post-merge dispatch on `main` is the evidence.
    - [N-TH] Record the dispatched head's tree hash (`git rev-parse <sha>^{tree}`).
  - impl: the PR body states:
    - each of R1 to R6 with its evidence, linking the pre-merge receipt and installed runs;
    - the required suite's skip of the four installed controls, reversing the draft's no-skip assertion;
    - review refused on native Windows;
    - every added inventory row with its role;
    - any rename;
    - the synced jevdrill SHA;
    - the sync command and the 3.12/CPython-3.14 pairing;
    - [C9] that if the installed leg is not run or fails, JEV HOST runs the pairing first;
    - every leg not run;
    - [P3] the Gate A run link;
    - [P2] that JEV Drill's usage record on review launches is `unknown`;
    - that JEV Drill's CLI at the pin has no schema or version command, so the installed leg's checkout comparison carries the pin check;
    - [N-TH] both tree hashes, of the dispatched head and the merge commit;
    - [N-ENV] the deferred env allowlist, agent-harness#2084;
    - the dropped paths;
    - that agent-harness#2071 is superseded.
  - impl (post-dispatch): back-fill the merge SHA, its tree hash and each leg's result into a closing PR comment and the report to Root. Dispatch the companion again only if the merge commit's tree hash differs from the dispatched head's. Close agent-harness#2071 as superseded only after the merge, with a link. No committed file carries a placeholder.
  - verify: `git diff --stat origin/main` shows no excluded path. Run the JEVHOST §9 disclosure grep over the diff and `git log origin/main..HEAD`; the only expected hit is the attribution trailer.

## Execution Notes

- **One integration pull request.** Each lane commits its own files. Lanes follow the
  DAG. No commit, count or topology is pinned.
- **Companions left untouched.** Some existing tests are run but not edited:
  `test_dispatch_lock_*`, `test_agy_*`, `test_convergence_*`,
  `test_observability_alerting.py`, `test_launcher_exec_supervisor.py`,
  `test_phase_loop_runner*.py` and `test_lane_wave_executor.py`. Also
  `test_phase_worktree_executor.py`, which SL-0 owns only for closeout. An edit to one is a
  stop (JEVHOST §2).
- **Single-writer files.**
  - `conftest.py`, `launch_audit_hook.py`, `pyproject.toml`, `uv.lock`: SL-0.
  - The inventory files: SL-4.
  - `CHANGELOG.md`: SL-5.
  - No existing workflow is written.
- **Concurrent writers** (JEVHOST §11). agent-harness#2082 shares
  `seat_launch_references.json`, and whichever lands second regenerates its own rows. If
  that is JEVHOST, SL-4 does it. The OI-1 fence lane and agent-harness#2081 are disjoint.
  Rebase onto `main` immediately before the merge. Redo any lane whose files changed, or
  SL-4 if `panel_invoker.py` changed [N-RD].
- **Hosted evidence.** The required checks gate the merge. Both Linux legs run on the PR and
  on the merge push. The single companion dispatch gives macOS and Windows evidence before
  the merge. [P3] Gate A runs on the same exact head.
- **Requalification.** Package edits move `runtime_digest()`. Window records keyed to the
  old value need requalification.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`.

- [ ] EC-JEVHOST-1 — proven by `test_jevdrill_selection.py` (R5 imports from the checkout's `src`), both Linux legs' sync steps on the PR and the merge push, and `git ls-tree` of the merge commit listing the R1 paths and none of JEVHOST §9's; falsified by a missing module, test, helper or fixture, or a `uv sync --locked` failure. Path-entered control: the workflow's `uv sync … --locked` on a fresh hosted runner.
- [ ] EC-JEVHOST-2 — proven by SL-1's check script and the installed leg's checkout comparison; falsified by one changed schema byte, a removed fixture row or a stale `digests.json` value. Path-entered control: jevdrill's raw files fetched by SHA.
- [ ] EC-JEVHOST-3 — proven by SL-0's, SL-3's and SL-4's verify commands with `main`'s companion tests unedited, the five inventory tests and `test_launch_audit_inventory.py` green, and `test_jevdrill_launch_merge.py` and `test_jevdrill_runner_lanes.py`; falsified by an unredacted credential at any sink, a review launch on native Windows, a probe outside `launch_owned` [B4], a usage probe on a review launch [P2], an unlisted launch site, an adapter run entering `execute_lane_waves`, or a module-level `fcntl` reference. Path-entered control: `launch_with_spec` and `run_loop` with production constructors, under `main`'s audit hook.
- [ ] EC-JEVHOST-4 — [C5] proven by the receipt leg's classifier (`scripts/jevdrill_receipt.py`, unit-tested by `test_jevdrill_receipt.py`) passing with every skip inside the four-reason allowlist, and by the installed leg passing every collected `jevdrill_installed` item by node ID with both variables from one CPython-3.14 install of the R2 pin, on the PR and at the merge commit; falsified by any failure or error, a skip with an unlisted reason, or an installed item skipped, missing or failing. Path-entered control: the twelve files run by the workflow, with junit read by the classifier.
- [ ] EC-JEVHOST-5 — proven by `test_jevdrill_selection.py`: the eight node IDs with the split, the static LEARN rule [C6] and name stability [C7]; and by the dispatched `windows-2025` legs passing every test of the four LEARN files [B5]; falsified by `dotfiles_integration` on any control or R4-file test, a module-level `jevdrill_installed`, a marked non-installed control, a dropped node ID, a skip mark in a cross-platform LEARN file, or an unlisted rename. Path-entered control: pytest collection with `-m "not dotfiles_integration"`.
- [ ] EC-JEVHOST-6 — proven by `test_jevdrill_selection.py`; falsified by removing any R5 name. Path-entered control: import from the checkout.
- [ ] EC-JEVHOST-7 — proven by `test_jevdrill_companion_workflow.py` (the sync template with `harness_python` `"3.12"` on every R3 leg, JEV Drill on `--python cpython-3.14`) and by the dispatched sync steps on the three operating systems (`gh run view <run> --json jobs`); falsified by a sync failure on any of them, or by a 3.14 harness leg cited as evidence [C8]. Path-entered control: the workflow's sync steps.
- [ ] EC-JEVHOST-8 — proven by the required `gitleaks` check, SL-5's disclosure grep and `test_jevdrill_companion_workflow.py` (no existing workflow changed); falsified by a planted local path or host name in the diff. Path-entered control: `git diff origin/main`.

## Verification

Per lane: the commands above. Whole phase, locally and serially after a headroom check:
the frontmatter `suite_command`. Hosted, in order:
1. the required checks;
2. both Linux legs on the PR;
3. on the exact integration head, one companion dispatch, and [P3] Gate A
   (`gh workflow run test.yml --ref <branch> -f chronology=false`);
4. both Linux legs on the merge push. No
step makes a provider call or runs on a non-hosted machine.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/jevdrill-integration.md`, `CHANGELOG.md`
- evidence paths: `phase-loop-runtime/tests/test_jevdrill_selection.py`, `phase-loop-runtime/tests/test_jevdrill_companion_workflow.py`, `phase-loop-runtime/tests/test_jevdrill_receipt.py`
- redaction posture: `metadata_only`
- downstream handling: none; the merge SHA, the synced jevdrill SHA, the sync command and the CI pairing go to the JEV Drill executive through Root
