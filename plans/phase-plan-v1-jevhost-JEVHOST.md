---
phase_loop_plan_version: 1
phase: JEVHOST
roadmap: specs/phase-plans-jevhost-v1.md
roadmap_sha256: 46d4161ca2651598d72a73ddbbd52a08be1f6d211e54343bf2de628f8157e94c
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
| `jevdrill_installed` marker, the R4 rule, the nominated tests | JEVHOST §6 |
| R5 names: all kept, no rename table | JEVHOST §7 |
| Companion workflow, sync command, CI Python, evidence | JEVHOST §8 |
| Dropped evidence and handoffs, disclosure checks | JEVHOST §9 |
| Stop rules | JEVHOST §10 |
| Concurrent writers | JEVHOST §11 |

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

SL-4 — ADAPTER: adapter, queue, runner conflict, JEV Drill tests and selection
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
    - the sync command with `--python 3.12`, and the JEV environment synced in its own path;
    - the `-m "not dotfiles_integration"` command naming exactly the twelve files;
    - the junit skip guard and the upload;
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
    - S3: the same holds through the Windows `output` callback, driven directly.
  - test: the T1 and T2 merges of the two existing test files, and the draft's edits to `test_phase_loop_work_unit_observability.py`. `main`'s assertions are unchanged except as T1 and T2 say.
  - impl: the per-file three-way merge of `launcher.py` with L1 to L7, S2 and S3. Then S6 across SL-3's test files.
  - verify: `timeout 900 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not dotfiles_integration" tests/test_jevdrill_launch_merge.py tests/test_launcher_liveness.py tests/test_phase_loop_launcher.py tests/test_phase_loop_work_unit_observability.py tests/test_launcher_exec_supervisor.py`, then `timeout 120 python3 scripts/check_model_id_sources.py`.

### SL-4 — ADAPTER: adapter, queue, runner conflict, JEV Drill tests and selection

- **Scope**: Bring in the adapter, queue, helpers and six JEV Drill test files. Resolve R1 and S4 in the runner. Add the `jevdrill_installed` selection and the R4 and R5 checks.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/jevdrill_adapter.py`, `phase-loop-runtime/src/phase_loop_runtime/jevdrill_queue.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_jevdrill_adapter.py`, `phase-loop-runtime/tests/test_jevdrill_diagnostics.py`, `phase-loop-runtime/tests/test_jevdrill_discovery.py`, `phase-loop-runtime/tests/test_jevdrill_input.py`, `phase-loop-runtime/tests/test_jevdrill_queue.py`, `phase-loop-runtime/tests/test_jevdrill_usage.py`, `phase-loop-runtime/tests/jevdrill_fixture_values.py`, `phase-loop-runtime/tests/phase_loop_test_utils.py`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_jevdrill_selection.py`, `phase-loop-runtime/tests/test_jevdrill_runner_lanes.py`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`
- **Interfaces provided**: `IF-0-JEVHOST-1` (complete), `IF-0-JEVHOST-3`; `jevdrill_adapter.JevDrillTransport`, `JevDrillUnavailable`, `JevDrillAdapter`, `build_jevdrill_request`, `launch_jevdrill`; `jevdrill_queue.ReportQueue`; `runner.discover_jevdrill_work_units`
- **Interfaces consumed**: `IF-0-JEVHOST-2` from SL-1; SL-3's launcher interfaces; SL-0's `file_lock` and `windows_storage`; `lane_wave_executor.execute_lane_waves` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: `test_jevdrill_runner_lanes.py`, red before the impl task:
    - under the default `lane_scheduler_mode`, a planned phase with an adapter enters `prepare` once and `launch` once, and never `execute_lane_waves`;
    - with no adapter, the lane-wave path is taken as on `main`.
  - test: `test_jevdrill_selection.py` (JEVHOST §6, §7):
    - the R4 rule over the seven files and the two nominated launcher tests;
    - every R5 import;
    - an item using `installed_discovery` without `jevdrill_installed` is a collection error.
  - test: restore the six `test_jevdrill_*.py` files and `jevdrill_fixture_values.py` verbatim. Mark the installed-JEV tests `jevdrill_installed`. Three-way merge `phase_loop_test_utils.py`. Update any count or v1-only assertion that SL-1's sync moves, and report each one.
  - impl: restore `jevdrill_adapter.py` and `jevdrill_queue.py` verbatim. Do the three-way merge of `runner.py` with R1, then S4. Register the marker and its skip rule in `conftest.py` and the marker line in `pyproject.toml`. Run `uv lock --check --project .`, and touch `uv.lock` only under JEVHOST §8.
  - verify: `timeout 1200 .venv/bin/python -m pytest -q -p no:cacheprovider -m "not dotfiles_integration" tests/test_jevdrill_selection.py tests/test_jevdrill_runner_lanes.py tests/test_jevdrill_adapter.py tests/test_jevdrill_diagnostics.py tests/test_jevdrill_discovery.py tests/test_jevdrill_input.py tests/test_jevdrill_queue.py tests/test_jevdrill_usage.py tests/test_lane_wave_executor.py` (the installed-JEV tests skip here), then `timeout 1200 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_phase_loop_runner.py`.
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
    - each of R1 to R6 with its evidence;
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
- **Concurrent writers** (JEVHOST §11). K-1 SL-6, the OI-1 fence lane and
  agent-harness#2078 own no file of this phase. Rebase onto `main` immediately before the
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
- [ ] EC-JEVHOST-3 — proven by SL-0's, SL-3's and SL-4's verify commands, with `main`'s companion tests unedited, and by `test_jevdrill_launch_merge.py` and `test_jevdrill_runner_lanes.py`; falsified by an unredacted credential reaching any sink, a probe of an unvalidated binary, an adapter run entering `execute_lane_waves`, or a module-level `fcntl` reference. Path-entered control: `launch_with_spec` and `run_loop` called with production constructors.
- [ ] EC-JEVHOST-4 — proven by the companion workflow's Linux run at the merge commit with the junit skip guard green, and by the dispatched run's links; falsified by a `jevdrill_installed` test skipped or failing. Path-entered control: the twelve files run against jevdrill's installed CLI.
- [ ] EC-JEVHOST-5 — proven by `test_jevdrill_selection.py`; falsified by adding `dotfiles_integration` to any test in the seven files or to either nominated test. Path-entered control: pytest collection with `-m "not dotfiles_integration"`.
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
