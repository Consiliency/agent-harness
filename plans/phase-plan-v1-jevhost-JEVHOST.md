---
phase_loop_plan_version: 1
phase: JEVHOST
roadmap: specs/phase-plans-jevhost-v1.md
roadmap_sha256: e61a43f56bfb942231bc99749cd4d10ef05354fcdb354074d6d1c64808d603e0
automation:
  suite_command: ["bash", "-lc", "cd phase-loop-runtime && PYTHONPATH=$PWD/src:$PWD/tests timeout 1800 .venv/bin/python -m pytest -q -p no:cacheprovider -m 'not dotfiles_integration' tests/test_jevdrill_selection.py tests/test_jevdrill_runner_lanes.py tests/test_jevdrill_launch_merge.py tests/test_jevdrill_companion_workflow.py tests/test_jevdrill_adapter.py tests/test_jevdrill_diagnostics.py tests/test_jevdrill_discovery.py tests/test_jevdrill_input.py tests/test_jevdrill_queue.py tests/test_jevdrill_usage.py tests/test_launcher_liveness.py tests/test_phase_loop_launcher.py tests/test_phase_loop_work_unit_observability.py tests/test_windows_locking.py tests/test_windows_processes.py tests/test_windows_storage.py"]
---

# JEVHOST: JEV Drill host adapter on main

## Context

The owner assigned the sanitized draft agent-harness#2071 to this repository on 2026-11-22,
to be brought to a merged state on `main`. The JEV Drill project will pin one accepted
commit under conditions R1 to R6, which JEVHOST §1 quotes. This plan lands the draft
through one new integration pull request from current `main`. It does not rebase the draft
branch.

**Revision 2 (2026-11-22).** This revision applies the independent review of
agent-harness#2083, which lists B1 to B3 and N1 to N8.
- SL-4 becomes the reducer for the source inventories (JEVHOST §13).
- SL-3 refuses review on native Windows and threads the Windows recursion's keywords
  (S3).
- SL-4's selection test asserts jevdrill's eight controls exactly, with the installed
  split (JEVHOST §1, §6).
- The nominated launcher tests are no longer gated.
- §11 and the workflow details are updated.
- The two questions still open with JEV Drill each have a fallback (JEVHOST §14).

**Frozen input.** JEVHOST (`plans/artifacts/jevhost-v1-contract.md`, pinned by sha256 in
the roadmap's External Inputs) holds every procedure, resolution and rule this plan cites.
It is read-only during execution.

**What the plan decides, and where.**

| Decision | Where |
|---|---|
| Path-scoped replay, file classes, the preservation rule | JEVHOST §2 |
| Each conflicting hunk's resolution (2 + 7 + 1 + 2 hunks in five files) | JEVHOST §3 |
| Semantic conflicts a clean merge hides (S1 to S6) | JEVHOST §4 |
| jevdrill SHA, byte comparison, fixture substitution, digests | JEVHOST §5 |
| `jevdrill_installed` marker, the eight R4 controls, the installed split | JEVHOST §1, §6 |
| R5 names: all kept, no rename table | JEVHOST §7 |
| Companion workflow, sync command, CI Python, evidence | JEVHOST §8 |
| Dropped evidence and handoffs, disclosure checks | JEVHOST §9 |
| Stop rules | JEVHOST §10 |
| Concurrent writers | JEVHOST §11 |
| Source inventories, their owner and the role of each new row | JEVHOST §13 |
| Fallbacks for the two questions open with JEV Drill | JEVHOST §14 |

**Survey (2026-11-22).** The draft is 1 commit ahead of and 1,501 behind `main`.
- A trial merge conflicts in `agy_qualification.py`, `launcher.py`, `runner.py`,
  `test_launcher_liveness.py` and `test_phase_loop_launcher.py`.
- Against jevdrill's pinned contract commit (roadmap External Inputs), 12 of the 14 schemas match. `RouteInputs.json`
  and `DiscoveryRouteInputs.json` accept only `JudgeCandidate-v1`, and `route-inputs.json`
  has 13 of 19 rows.
- The 53 `dotfiles_integration` launcher tests are `main`'s own class mark. No R4 file
  carries the marker.

**Shared-host rule.** Only the files a lane lists, serially without `-n`, with
`-p no:cacheprovider`, under `timeout`, after a headroom check (`free -h`,
`/proc/loadavg`, `/proc/pressure/memory`). Defer to hosted CI if headroom is short. No
full suite, no Gate A run and no workflow dispatch from a shared host. Do not run
`tests/test_panel_invoker.py` or any test that launches a provider.

## Interface Freeze Gates

- [ ] IF-0-JEVHOST-1 — JEVHOST §2 to §4: replay by path from the draft commit over its base (both pinned in the roadmap's External Inputs); the hunk resolutions A1, A2, L1 to L7, R1, T1 and T2; rules S1 to S6.
- [ ] IF-0-JEVHOST-2 — JEVHOST §5: the 14 schemas and 3 fixtures at the pinned jevdrill commit or a later `main` commit under the SHA rule, the placeholder substitution, and `digests.json` as raw-bytes sha256.
- [ ] IF-0-JEVHOST-3 — JEVHOST §6 and §7: the `jevdrill_installed` marker and its conftest rule, `tests/test_jevdrill_selection.py`, and the R5 names unchanged.
- [ ] IF-0-JEVHOST-4 — JEVHOST §8: `.github/workflows/jevdrill-companion.yml` (triggers, matrix, `jevdrill_ref` input, no secrets), the sync command `uv sync --project phase-loop-runtime --group test --extra visual --locked`, CI Python 3.12.

## Lane Index & Dependencies

SL-0 — PORT: platform primitives and the cleanly merging modules
  Depends on: (none)
  Blocks: SL-3, SL-4
  Parallel-safe: yes

SL-1 — CONTRACT: fixture and schema copies at the jevdrill commit
  Depends on: (none)
  Blocks: SL-2, SL-4
  Parallel-safe: yes

SL-2 — WORKFLOW: the companion workflow and its shape test
  Depends on: SL-1
  Blocks: SL-5
  Parallel-safe: yes

SL-3 — LAUNCH: launcher conflicts and launcher tests
  Depends on: SL-0
  Blocks: SL-4
  Parallel-safe: no

SL-4 — ADAPTER: adapter, queue, runner conflict, JEV Drill tests, selection and the source inventories
  Depends on: SL-0, SL-1, SL-3
  Blocks: SL-5
  Parallel-safe: no

SL-5 — DOCS: integration page, changelog and the pull request's disclosure (reducer)
  Depends on: SL-0, SL-1, SL-2, SL-3, SL-4
  Blocks: (none)
  Parallel-safe: no

## Lanes

Source paths are under `phase-loop-runtime/src/phase_loop_runtime/`. Test paths are under
`phase-loop-runtime/`. Lane verify commands run from `phase-loop-runtime/` after
`uv sync --project . --group test --extra visual --locked`, with
`PYTHONPATH=$PWD/src:$PWD/tests`.

### SL-0 — PORT: platform primitives and the cleanly merging modules

- **Scope**: Bring in the draft's portability modules verbatim and three-way merge its edits to the modules that merge cleanly, applying S1 and S5.
- **Owned files**: `phase-loop-runtime/tests/test_phase_worktree_executor.py`, `phase-loop-runtime/src/phase_loop_runtime/file_lock.py`, `phase-loop-runtime/src/phase_loop_runtime/windows_process.py`, `phase-loop-runtime/src/phase_loop_runtime/windows_storage.py`, `phase-loop-runtime/src/phase_loop_runtime/dispatch_lock.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_qualification.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_provenance.py`, `phase-loop-runtime/src/phase_loop_runtime/phase_worktree_executor.py`, `phase-loop-runtime/src/phase_loop_runtime/prompts.py`, `phase-loop-runtime/src/phase_loop_runtime/observability.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/event_log.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/fencing.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/broker/live.py`, `phase-loop-runtime/tests/test_windows_locking.py`, `phase-loop-runtime/tests/test_windows_processes.py`, `phase-loop-runtime/tests/test_windows_storage.py`
- **Interfaces provided**: `file_lock.acquire_exclusive`, `release_exclusive`, `open_generation_lease`; `windows_process.run_owned`, `process_is_live`, `start_leased_guardian`; `windows_storage.BoundDirectory`
- **Interfaces consumed**: (none)
- **Parallel-safe**: yes
- **Tasks**:
  - test: restore the three `test_windows_*.py` files verbatim. Add a POSIX-runnable case to `test_windows_locking.py`: importing `agy_qualification` leaves no module-level `fcntl` reference (S1).
  - impl: restore `file_lock.py`, `windows_process.py` and `windows_storage.py` verbatim. Do the per-file three-way merge for the other nine owned modules. Resolve hunks A1 and A2 (JEVHOST §3). Apply S1 to the `dir_fd` lock path. Apply S5 only where a Windows test reaches the code.
  - verify: `timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_windows_locking.py tests/test_windows_processes.py tests/test_windows_storage.py tests/test_dispatch_lock_helper.py tests/test_dispatch_lock_reentrancy.py tests/test_dispatch_lock_same_roadmap.py tests/test_dispatch_lock_cross_roadmap.py tests/test_agy_qci.py tests/test_agy_self_qualification.py tests/test_agy_provenance_wiring.py tests/test_convergence_event_log.py tests/test_convergence_fencing.py tests/test_convergence_broker_api.py tests/test_phase_worktree_executor.py tests/test_observability_alerting.py`, then `git diff origin/main -- tests/test_agy_qci.py` is empty.

### SL-1 — CONTRACT: fixture and schema copies at the jevdrill commit

- **Scope**: Create `tests/fixtures/jevdrill/` from jevdrill's own bytes under JEVHOST §5, not from the draft's stale copies.
- **Owned files**: `phase-loop-runtime/tests/fixtures/jevdrill/**`
- **Interfaces provided**: `IF-0-JEVHOST-2`
- **Interfaces consumed**: (none)
- **Parallel-safe**: yes
- **Tasks**:
  - test: a scratch check script (not committed) that, for the named SHA, fetches the 14 schemas and 3 fixtures and runs `cmp` on every schema, compares every fixture after substituting the placeholder back, and recomputes `digests.json`. It fails on the draft's files before the impl task (the 2 schemas and `route-inputs.json`).
  - impl: steps 1 to 3 of JEVHOST §5. Re-check jevdrill `main` immediately before the push and apply the SHA rule.
  - verify: the check script exits 0. `grep -c 'utf8-bytes-upper-bound-v1' tests/fixtures/jevdrill/*.json` prints only zeros. `git diff --stat` touches only owned files.

### SL-2 — WORKFLOW: the companion workflow and its shape test

- **Scope**: Add the non-required companion workflow of JEVHOST §8 and a test that freezes its shape.
- **Owned files**: `.github/workflows/jevdrill-companion.yml`, `phase-loop-runtime/tests/test_jevdrill_companion_workflow.py`
- **Interfaces provided**: `IF-0-JEVHOST-4`
- **Interfaces consumed**: `IF-0-JEVHOST-2` from SL-1 (the synced SHA, which the test holds as a constant)
- **Parallel-safe**: yes
- **Tasks**:
  - test: `test_jevdrill_companion_workflow.py` asserts:
    - the triggers and the path filter;
    - `permissions: contents: read`, no `secrets` and no `pull_request_target`;
    - Linux only on `push` and `pull_request`, and the four-leg matrix on dispatch;
    - the full-SHA validation step for `jevdrill_ref`, with its default equal to the SHA SL-1 synced to;
    - `persist-credentials: false` on the second checkout;
    - the one sync template `… --locked --python ${{ matrix.harness_python }}`, with `harness_python` `"3.12"` on every `push` and `pull_request` leg and `"3.14"` only on the dispatched Linux leg;
    - the JEV environment synced in its own path with `--python` from the `jev_python` input (default `"3.14"`), and its version written to the job summary;
    - `PYTHONPATH` joined with `;` on Windows and `:` elsewhere;
    - the `-m "not dotfiles_integration"` command naming exactly the twelve files;
    - the junit guard requiring the four installed controls of JEVHOST §1 as passed by node ID, and no `jevdrill_installed` skip, then the upload;
    - and that no existing workflow file changed.
  - impl: the workflow.
  - verify: `timeout 300 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_jevdrill_companion_workflow.py tests/test_python_floor_1546.py`

### SL-3 — LAUNCH: launcher conflicts and launcher tests

- **Scope**: Merge the draft's launcher (Codex usage and input capture, Windows owned launch, deadline) into `main`'s launcher, resolving L1 to L7, T1 and T2 under S2, S3 and S6.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/launcher.py`, `phase-loop-runtime/tests/test_launcher_liveness.py`, `phase-loop-runtime/tests/test_phase_loop_launcher.py`, `phase-loop-runtime/tests/test_phase_loop_work_unit_observability.py`, `phase-loop-runtime/tests/test_jevdrill_launch_merge.py`
- **Interfaces provided**: `launcher._CodexUsageCollector`, `launch(..., _codex_usage_observer=, _launch_deadline=)` alongside `main`'s `action`, `_review_profile`
- **Interfaces consumed**: SL-0's `windows_process` interfaces; `panel_invoker._redact_seat_credentials` (pre-existing); `executable_dependency_startup.current_dependency_for_provider` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: `test_jevdrill_launch_merge.py` covers four cases, red before the impl task:
    - S2: with a fake dependency, `validate_command` is called before the usage-version probe and again as the last call before `launch`;
    - S2: a mismatched binary is never probed;
    - S3: with a live review profile, a seat-credential line is redacted before the observer, the output, the log and the stream;
    - S3: with `_native_windows()` patched true, `launch(action="review", …)` raises `review_unsupported_on_windows` before any spawn (`Popen` and `windows_process.run_owned` patched to fail);
    - S3: with the seam patched true, a non-review `launch(…, ephemeral_monitor=True)` reaches the Windows branch with `action`, `_review_profile`, `_codex_usage_observer` and `_launch_deadline` forwarded;
    - L4: `main`'s review recursion forwards the two usage keywords.
  - test: the T1 and T2 merges of the two existing test files, and the draft's edits to `test_phase_loop_work_unit_observability.py`. `main`'s assertions are unchanged except as T1 and T2 say.
  - impl: the per-file three-way merge of `launcher.py` with L1 to L7, S2 and S3, including the `_native_windows()` seam. Then S6 across SL-3's test files.
  - verify note: the source-inventory tests of JEVHOST §13 are not run here, because they stay red until SL-4 reconciles them.
  - verify: `timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not dotfiles_integration" tests/test_jevdrill_launch_merge.py tests/test_launcher_liveness.py tests/test_phase_loop_launcher.py tests/test_phase_loop_work_unit_observability.py tests/test_launcher_exec_supervisor.py`, then `timeout 120 python3 scripts/check_model_id_sources.py`.

### SL-4 — ADAPTER: adapter, queue, runner conflict, JEV Drill tests, selection and the source inventories

- **Scope**: Bring in the adapter, queue, helpers and six JEV Drill test files. Resolve R1 and S4 in the runner. Add the `jevdrill_installed` selection and the R4 and R5 checks. Reconcile the source inventories of JEVHOST §13 for the whole phase.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/jevdrill_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/jevdrill_queue.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_jevdrill_adapter.py`, `phase-loop-runtime/tests/test_jevdrill_diagnostics.py`, `phase-loop-runtime/tests/test_jevdrill_discovery.py`, `phase-loop-runtime/tests/test_jevdrill_input.py`, `phase-loop-runtime/tests/test_jevdrill_queue.py`, `phase-loop-runtime/tests/test_jevdrill_usage.py`, `phase-loop-runtime/tests/jevdrill_fixture_values.py`, `phase-loop-runtime/tests/phase_loop_test_utils.py`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_jevdrill_selection.py`, `phase-loop-runtime/tests/test_jevdrill_runner_lanes.py`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`
- **Interfaces provided**: `IF-0-JEVHOST-1` (complete), `IF-0-JEVHOST-3`; `jevdrill_adapter.JevDrillTransport`, `JevDrillUnavailable`, `JevDrillAdapter`, `build_jevdrill_request`, `launch_jevdrill`; `jevdrill_queue.ReportQueue`; `runner.discover_jevdrill_work_units`
- **Interfaces consumed**: `IF-0-JEVHOST-2` from SL-1; SL-3's launcher interfaces; SL-0's `file_lock` and `windows_storage`; `lane_wave_executor.execute_lane_waves` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: `test_jevdrill_runner_lanes.py`, red before the impl task:
    - under the default `lane_scheduler_mode`, a planned phase with an adapter enters `prepare` once and `launch` once, never `execute_lane_waves`, and records one `lane_scheduler` event with reason `jevdrill_adapter`;
    - with no adapter, the lane-wave path is taken as on `main`.
  - test: `test_jevdrill_selection.py` (JEVHOST §6, §7):
    - the eight control node IDs of JEVHOST §1, exactly: each is collected and selected under `-m "not dotfiles_integration"`, and none carries `dotfiles_integration`;
    - exactly the four installed controls carry `jevdrill_installed`, and the other four never do;
    - collecting the seven R4 files deselects nothing;
    - no module-level `pytestmark` in `test_jevdrill_discovery.py`;
    - every R5 import;
    - both conftest collection errors of JEVHOST §6, each driven by a `pytester` case;
    - an informational report of the two launcher tests, which does not gate.
  - test: restore the six `test_jevdrill_*.py` files and `jevdrill_fixture_values.py` verbatim. Mark, per test, the installed-JEV tests `jevdrill_installed`: the four installed controls, the other tests using `installed_discovery`, and the adapter's real-CLI route test. Three-way merge `phase_loop_test_utils.py`. Update any count or v1-only assertion that SL-1's sync moves, and report each one.
  - test: run the five inventory tests of JEVHOST §13. They are red where the phase's new sites are unlisted.
  - impl: reconcile `tests/data/seat_launch_references.json` and the 1147 `INVENTORY` for every site SL-0, SL-3 and SL-4 added or moved. Use the role table of JEVHOST §13, and list each added row with its role for the pull request. A site the table does not cover is a stop.
  - impl: restore `jevdrill_adapter.py` and `jevdrill_queue.py` verbatim. Do the three-way merge of `runner.py` with R1, then S4. Register the marker and its skip rule in `conftest.py` and the marker line in `pyproject.toml`. Run `uv lock --check --project .`, and touch `uv.lock` only under JEVHOST §8.
  - verify: `timeout 1200 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not dotfiles_integration" tests/test_jevdrill_selection.py tests/test_jevdrill_runner_lanes.py tests/test_jevdrill_adapter.py tests/test_jevdrill_diagnostics.py tests/test_jevdrill_discovery.py tests/test_jevdrill_input.py tests/test_jevdrill_queue.py tests/test_jevdrill_usage.py tests/test_lane_wave_executor.py tests/test_seat_reference_inventory.py tests/test_agent_cli_scratch_inventory_1147.py tests/test_seat_resource_caps.py tests/test_seat_launch_helpers_trusted.py tests/test_gate_fail_open_visibility.py` (the installed-JEV tests skip here; deselect any `real_seat_caps` or `host_seat_credentials` test, which would touch the host), then `timeout 1200 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_phase_loop_runner.py`.
  - verify (installed JEV, optional locally): only with headroom, a jevdrill checkout at the synced SHA in a scratch directory under `$HOME`, `uv sync --locked` there, and `JEVDRILL_TEST_CLI` set. Rerun `tests/test_jevdrill_discovery.py tests/test_jevdrill_adapter.py` with zero skips. Otherwise defer it to SL-2's workflow on the pull request.

### SL-5 — DOCS: integration page, changelog and the pull request's disclosure

- **Scope**: Update the integration page and the changelog after every producer lane. Write the pull request's R-condition disclosure.
- **Owned files**: `docs/jevdrill-integration.md`, `CHANGELOG.md`
- **Interfaces provided**: the pull request body's R1 to R6 statement
- **Interfaces consumed**: `IF-0-JEVHOST-1`, `IF-0-JEVHOST-2`, `IF-0-JEVHOST-3`, `IF-0-JEVHOST-4`
- **Findings consumed**: SL-1's synced SHA and any assertion it moved; SL-0's S5 outcomes; SL-3's S2 and S3 outcomes; SL-4's S4 outcome and the `uv lock --check` result; SL-2's workflow run links.
- **Parallel-safe**: no
- **Tasks**:
  - test: `timeout 120 .venv/bin/python -m phase_loop_runtime.entry_doc_check --repo ..` and `timeout 120 .venv/bin/python -m phase_loop_runtime.cli docs-audit --repo .. --base origin/main --json`.
  - impl: restore `docs/jevdrill-integration.md` from the draft and amend it:
    - lane-wave dispatch is not entered under an adapter (S4);
    - the `jevdrill_installed` marker and how to run the installed tests;
    - the sync command, CI Python and the companion workflow;
    - the October evidence is not carried (JEVHOST §9).
  - impl: add a `CHANGELOG.md` entry under `[Unreleased]`.
  - impl: the pull request body states:
    - each of R1 to R6 with its evidence, including the companion workflow's pre-merge `pull_request` run on the same tree;
    - that harness `main`'s required suite skips the four installed controls, which reverses the draft's "discovery cannot be skipped" assertion; that the companion workflow is their evidence; and the JEVHOST §14 fallback if JEV declines the marker;
    - every row added to `seat_launch_references.json`, with its role;
    - that review is refused on native Windows;
    - the synced jevdrill SHA;
    - the sync command, and CI Python 3.12;
    - that there are no renames;
    - the installed-JEV subset's skip in the required suite;
    - every leg not run;
    - the dropped paths;
    - that agent-harness#2071 is superseded.
  - impl (post-dispatch): after the merge push and the one dispatch, back-fill the merge commit's full SHA and each companion-workflow leg's result into a closing comment on the integration pull request and into the report to Root. No committed file carries a placeholder for them.
  - verify: `git diff --stat origin/main` shows no excluded path of JEVHOST §9. Then the disclosure grep of JEVHOST §9 over `git diff origin/main` and `git log origin/main..HEAD`, with the attribution trailer as the only hit.

## Execution Notes

- **One integration pull request.** Each lane commits its own owned files to the
  integration branch. The order follows the DAG. This plan pins no commit, commit count or
  topology.
- **Companions left untouched.** The existing tests of SL-0's modules
  (`test_dispatch_lock_*`, `test_agy_*`, `test_convergence_*`,
  `test_observability_alerting.py`, and `test_phase_worktree_executor.py`, which SL-0 owns
  only so a closeout sees it) and SL-3's and
  SL-4's (`test_launcher_exec_supervisor.py`, `test_phase_loop_runner*.py`,
  `test_lane_wave_executor.py`) are run, not edited. Under the preservation rule
  (JEVHOST §2) an edit to one is a stop, not a fix.
- **Single-writer files.** `conftest.py`, `pyproject.toml` and `uv.lock`: SL-4.
  `CHANGELOG.md`: SL-5. No existing workflow is written by any lane.
- **Concurrent writers** (JEVHOST §11). K-1 SL-6 (agent-harness#2082) shares
  `tests/data/seat_launch_references.json`. Whichever lands second regenerates its own
  rows; if JEVHOST lands second, SL-4 does it. The OI-1 fence lane and
  agent-harness#2081 own no file of this phase.
- **Open with JEV Drill** (JEVHOST §14). If the marker is declined, SL-4 applies the
  fixture-keyed deselection instead. If an exact Python 3.14 version is named, SL-2
  changes the workflow default to it. Neither needs a repin. Rebase onto `main` immediately before the
  merge, and redo any lane whose files changed on `main`.
- **Hosted evidence.** The required checks, including `gitleaks` and `suite gate`, gate the
  merge. The companion workflow's Linux leg runs on the pull request and again on the merge
  push. After the merge SL-5's executor dispatches the four-leg matrix once, then reports
  the run and any leg not done (EC-JEVHOST-4, EC-JEVHOST-7).
- **Requalification.** Package edits move `runtime_digest()`. Window records keyed to the
  old value need requalification, as after any runtime edit.

## Acceptance Criteria

Test paths are under `phase-loop-runtime/`.

- [ ] EC-JEVHOST-1 — proven by `test_jevdrill_selection.py` (R5 imports resolve from the checkout's `src`), the companion workflow's sync step on the merge push, and `git ls-tree` of the merge commit listing the R1 paths and none of JEVHOST §9's; falsified by a missing module, test file, helper or fixture, or a `uv sync --locked` failure. Path-entered control: the workflow's `uv sync … --locked` on a fresh hosted runner.
- [ ] EC-JEVHOST-2 — proven by SL-1's check script against the named SHA; falsified by one byte changed in any schema copy, a fixture row removed, or a stale `digests.json` value. Path-entered control: the script fetching jevdrill's raw files by SHA.
- [ ] EC-JEVHOST-3 — proven by SL-0's, SL-3's and SL-4's verify commands, with `main`'s companion tests unedited, by the five inventory tests of JEVHOST §13 green, and by `test_jevdrill_launch_merge.py` and `test_jevdrill_runner_lanes.py`; falsified by an unredacted credential reaching any sink, a review launch on native Windows, an unlisted launch site, a probe of an unvalidated binary, an adapter run entering `execute_lane_waves`, or a module-level `fcntl` reference. Path-entered control: `launch_with_spec` and `run_loop` called with production constructors.
- [ ] EC-JEVHOST-4 — proven by the companion workflow's `pull_request` run before the merge and its `push` run at the merge commit, each with the junit guard green (the four installed controls passed, by node ID), and by the dispatched run's links; falsified by a `jevdrill_installed` test skipped or failing. Path-entered control: the twelve files run against jevdrill's installed CLI.
- [ ] EC-JEVHOST-5 — proven by `test_jevdrill_selection.py` asserting the eight control node IDs of JEVHOST §1 exactly, with the installed split, and by the companion workflow's junit guard listing the four installed controls as passed; falsified by adding `dotfiles_integration` to any control or any test in the seven files, by a module-level `jevdrill_installed`, by marking a non-installed control, or by dropping one of the eight node IDs. Path-entered control: pytest collection with `-m "not dotfiles_integration"`.
- [ ] EC-JEVHOST-6 — proven by `test_jevdrill_selection.py`; falsified by removing any R5 name. Path-entered control: import from the checkout.
- [ ] EC-JEVHOST-7 — proven by `test_jevdrill_companion_workflow.py` (the sync command and `--python 3.12` are in the workflow) and by the dispatched run's sync step on each of the three operating systems (`gh run view <run> --json jobs`); falsified by a sync step failing on any of the three hosted operating systems. Path-entered control: the workflow's sync step.
- [ ] EC-JEVHOST-8 — proven by the required `gitleaks` check, SL-5's disclosure grep and `test_jevdrill_companion_workflow.py` (no existing workflow changed); falsified by a planted local path or host name in the diff. Path-entered control: `git diff origin/main`.

## Verification

Per lane: the commands above. Whole phase, locally and serially after a headroom check:
the frontmatter `suite_command`. Hosted, before the merge: the required checks and the
companion workflow's Linux leg. After the merge: the companion workflow on the merge push
and one dispatch of its matrix. No step makes a provider call or runs on a non-hosted
machine.

## Spec Closeout Plan
- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/jevdrill-integration.md`, `CHANGELOG.md`
- evidence paths: `phase-loop-runtime/tests/test_jevdrill_selection.py`, `phase-loop-runtime/tests/test_jevdrill_companion_workflow.py`
- redaction posture: `metadata_only`
- downstream handling: none; the merge SHA, the synced jevdrill SHA, the sync command and the CI Python go to the JEV Drill executive through Root
