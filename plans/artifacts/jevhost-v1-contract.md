# JEVHOST v1 contract: integrating the JEV Drill host adapter (agent-harness#2071)

Frozen planning artifact for `plans/phase-plan-v1-jevhost-JEVHOST.md`. It is read-only
during execution. A change needs a reviewed repin in `specs/phase-plans-jevhost-v1.md`.
Sections are cited as JEVHOST §N.

**Revision 2 (2026-11-22).** This revision applies the independent plan review of
agent-harness#2083:
- B1: the launch-reference inventory gets an owner and a role rule (§13).
- B2: review is refused on native Windows, and the Windows recursion threads its keywords
  (S3).
- B3: jevdrill's eight controls are now named exactly, with the installed split (§1, §6).
- N1: the nominated launcher tests are no longer an acceptance condition.
- N2 to N8: §11 is updated, the usage keywords are forwarded on review, the S4 bypass is
  logged, `docs/jevdrill-integration.md` is reclassified, R4 marks its editorial
  substitution, and the workflow details are fixed.
- §14 gives a fallback for each of the two questions still open with JEV Drill.

## §0 Inputs

| Input | Value |
| --- | --- |
| Draft commit (agent-harness#2071 head) | `784d1595a08f42519862ae5f9336f20186d83c4b` |
| Draft base (its only parent) | `56dce95a52625a58cd08911f8f623c637bf52e44` |
| jevdrill contract commit (R2) | `Consiliency/jevdrill` `main` at `998912b1e0195464e6f3aa048c5421c2bed57491`, which was jevdrill `main`'s tip when this contract was written (2026-11-22) |
| Counter substitution (R2) | placeholder `<jev-token-counter-revision>` stands for `utf8-bytes-upper-bound-v1` |

The draft is one commit, 1,501 commits behind `main` when surveyed. A trial merge against
`main` conflicts in exactly five files (§3). Every other draft path either is new or
merges without conflict. A clean textual merge does not mean the result is correct: §4
lists the semantic conflicts the survey found.

## §1 Acceptance conditions (external input)

The JEV Drill executive set these conditions, and the owner assigned the work to this
repository on 2026-11-22. They are quoted. The one editorial substitution, in R4, is
shown in square brackets. jevdrill will pin the accepted
commit by its full SHA and will not review it.

> - **R1.** A commit on that repository's `main`, merged under its own rules. It holds the five modules, the twelve JEV Drill test files with their helpers, `tests/fixtures/jevdrill/`, and a `pyproject.toml` and `uv.lock` that sync locked. Nothing needs to match October's digests or version 0.7.20; jevdrill regenerates its own records from the commit.
> - **R2.** The 14 schema copies are byte-identical to jevdrill's `schemas/` at a named jevdrill `main` commit at or after `998912b1e`. The 3 fixtures equal jevdrill's once `<jev-token-counter-revision>` is replaced by `utf8-bytes-upper-bound-v1`. `digests.json` agrees.
> - **R3.** The twelve files pass in that repository's own GitHub Actions on Linux at that commit. Also asked for: the tests that need an installed JEV Drill run there against jevdrill at the commit of R2, on Python 3.14; and the twelve files run there on hosted macOS and Windows runners (a dispatched workflow is enough). Where either is not done, jevdrill's own workflow is the first such run, and a failure there means a new commit from that repository.
> - **R4.** No selected test needs [the private dotfiles repository] or a secret. jevdrill deselects exactly the marker `dotfiles_integration`, as that repository's CI does, and tolerates no other skip. So none of the eight controls jevdrill names, and none of the four LEARN files, may carry that marker.
> - **R5.** The names jevdrill's tests import are kept, or the pull request lists what replaced them: `launcher`, `runner`, `models`, `JevDrillTransport`, `JevDrillUnavailable`, `ReportQueue`; `test_jevdrill_discovery.installed_discovery`, `.linked_task`, `.test_installed_discovery_decomposition_two_task_launch`; `test_jevdrill_adapter.FIXTURES`, `.adapter_fixture`; `test_jevdrill_usage.records`, `.synthetic_spec`, `.values`; `phase_loop_test_utils.make_repo`, `.write_phase_plan`.
> - **R6.** The pull request states the sync command and the Python version that repository's CI tests (3.12 today), and that command works on GitHub's hosted Linux, macOS and Windows runners.

**The eight controls of R4.** jevdrill's HOST board named them as these node IDs, relative
to `phase-loop-runtime/tests/`. Each was verified in the draft. The marker column is §6's
rule.

| Control | Installed JEV | `jevdrill_installed` |
| --- | --- | --- |
| `test_jevdrill_discovery.py::test_installed_discovery_decomposition_two_task_launch[alpha]` | yes | yes |
| `test_jevdrill_discovery.py::test_installed_discovery_decomposition_two_task_launch[beta]` | yes | yes |
| `test_jevdrill_discovery.py::test_entered_discovery_requires_harness_decomposition` | yes | yes |
| `test_jevdrill_discovery.py::test_objective_tombstone_survives_restart_and_preserves_reports` | yes | yes |
| `test_jevdrill_discovery.py::test_native_unsupported_observer_records_unknown_capture` | no | never |
| `test_jevdrill_adapter.py::test_guidance_is_verified_injected_once_and_deactivated` | no | never |
| `test_jevdrill_queue.py::test_objective_guard_reuses_anchored_transaction_and_bounds_admission` | no | never |
| `test_jevdrill_queue.py::test_objective_guard_bounds_other_thread_contention` | no | never |

The four LEARN files are `test_windows_locking.py`, `test_launcher_liveness.py`,
`test_windows_processes.py` and `test_windows_storage.py`.

Two launcher tests were nominated earlier:
`test_phase_loop_launcher.py::test_launcher_accepts_explicit_nonserialized_lease_authority`
and `::test_supervised_launch_drains_retained_stdout_before_returning`. The HOST president
ruled that they add no acceptance condition here. They are not gated. §6 only reports
whether they are selected, as information.

**Terms.** The *five modules* are `jevdrill_adapter.py`, `jevdrill_queue.py`, `runner.py`,
`launcher.py` and `observability.py`. The *twelve files* are the six `test_jevdrill_*.py`
files (adapter, diagnostics, discovery, input, queue, usage), the four LEARN files,
`test_phase_loop_launcher.py` and `test_phase_loop_work_unit_observability.py`. The
*helpers* are `tests/jevdrill_fixture_values.py` and `tests/phase_loop_test_utils.py`.
All paths in this contract are under `phase-loop-runtime/` unless they start with `.github/`,
`docs/` or `plans/`.

## §2 Integration method: path-scoped replay

The draft is not rebased as one commit, and its branch is not force-pushed. Its head stays
as the reviewable input. The work lands through a new pull request from a branch cut from
current `main`. agent-harness#2071 is closed as superseded when that pull request merges,
with a link to it.

Each lane brings in only the draft paths it owns:

- **New paths** are taken byte-for-byte with
  `git restore --source=784d1595a08f42519862ae5f9336f20186d83c4b -- <path>`, then
  amended only as this contract says.
- **Modified paths** are merged one file at a time with a three-way merge. Base: the file
  at `56dce95a5`. Ours: the file at the lane's `main` base. Theirs: the file at `784d1595a`.
  Use `git merge-file -p <ours> <base> <theirs>` on blobs exported to a scratch directory.
  Conflicts are resolved by §3, and the semantic rules of §4 are then applied.
- **Excluded paths** are not brought in (§9).

Classification of the draft's 59 paths:

| Class | Paths |
| --- | --- |
| New, verbatim | `src/phase_loop_runtime/{file_lock,windows_process,windows_storage,jevdrill_adapter,jevdrill_queue}.py`; `tests/test_jevdrill_{adapter,diagnostics,input,queue,usage}.py`; `tests/test_windows_{locking,processes,storage}.py`; `tests/jevdrill_fixture_values.py` |
| New, then amended | `tests/test_jevdrill_discovery.py` (per-test markers, §6); `docs/jevdrill-integration.md` (SL-5) |
| New, then re-synced (§5) | the 18 files under `tests/fixtures/jevdrill/` |
| Modified, conflicting (§3) | `agy_qualification.py`, `launcher.py`, `runner.py`, `tests/test_launcher_liveness.py`, `tests/test_phase_loop_launcher.py` |
| Modified, clean textual merge (§4 applies) | `agy_provenance.py`, `convergence/broker/live.py`, `convergence/event_log.py`, `convergence/fencing.py`, `dispatch_lock.py`, `observability.py`, `phase_worktree_executor.py`, `prompts.py`, `tests/phase_loop_test_utils.py`, `tests/test_phase_loop_work_unit_observability.py` |
| Excluded (§9) | `evidence/HOST-ADAPTER/*` (7), `.dev-skills/handoffs/codex-execute-phase/*` (2), `plans/detailed-jevdrill-discovery-host.md` |

**Preservation rule.** With no adapter passed (`jevdrill_adapter=None`, the default),
every existing `main` behaviour is unchanged. The existing tests of each touched module
stay green with no assertion weakened. A `main` test may change only where §3 says so.

## §3 Conflict resolutions

Hunks are named by the trial merge's conflict markers, in file order.

### `agy_qualification.py` (2 hunks)

| Hunk | `main` side | Draft side | Resolution |
| --- | --- | --- | --- |
| A1 `Store.lock` head | `dir_fd=` parameter and relative `os.open` (the HOLD cache anchor) | `sys.platform != "linux"` refusal, absolute `os.open` | Keep `main`'s signature, docstring and `dir_fd`-relative open. Put the draft's platform refusal first in the body. |
| A2 `lookup` head | `image = data if isinstance(data, gh.VerifiedImage) else None` | platform refusal, `self_qualification_enabled()` check, `VerifiedImage.from_bytes` | Keep `main`'s body. Add only the platform refusal before it. Do not re-add the enabled check or `from_bytes` if `main` moved them: check `main`'s `lookup` before editing. |

### `launcher.py` (7 hunks)

| Hunk | `main` side | Draft side | Resolution |
| --- | --- | --- | --- |
| L1 `launch_with_spec` preamble | executable-dependency admission and `_refuse_unwired_executor_spec` | `launch_started = time.monotonic()` | `launch_started` first, then `main`'s block unchanged. |
| L2 before `launch(` | `dependency.validate_command(command, …)` immediately before the process boundary | timeout budget, Codex input manifest, usage-version probe, observer | Union under §4 S2: validate before the draft's block, and again as the last statement before `launch(`. |
| L3 supervised-run signature | `action: str, review_profile: object | None` | `_codex_usage_observer=None, _launch_deadline=None` | Both, `main`'s first. |
| L4 `launch` signature | `action: str = "execute", _review_profile=None` | the same two draft keywords | Both, `main`'s first. `main`'s review recursion inside `launch()` also forwards `_codex_usage_observer` and `_launch_deadline`, so usage capture is not lost on a Codex review. |
| L5 supervised call-through | passes `action`, `review_profile` | passes the two draft keywords | Pass all four. |
| L6 live line loop | `redact_seat(line)`, then append, log, stream | `consume(line)` | Keep `consume(line)`. Move `main`'s redaction into `consume` (§4 S3). |
| L7 final drain loop | the same as L6 | `consume(line)` | The same as L6. |

### `runner.py` (1 hunk)

| Hunk | `main` side | Draft side | Resolution |
| --- | --- | --- | --- |
| R1 `_dispatch_phase` | the lane-wave block (`execute_lane_waves`, lane events, lane closeout), then `launch_with_spec(prep.spec, …)` | `launch_jevdrill(jevdrill_adapter, launch_with_spec, prep.spec, …)` | Keep `main`'s whole block. Change only the final call to the draft's `launch_jevdrill(…)` form. Then apply §4 S4. |

### Tests (1 hunk each)

| Hunk | Resolution |
| --- | --- |
| T1 `test_launcher_liveness.py` | Keep `main`'s test name (`…_uses_the_launch_seam`), comment and POSIX body. Add the draft's `os.name == "nt"` branch at the top. |
| T2 `test_phase_loop_launcher.py` | Keep `main`'s model literal (`gemini-4-neon-high`). Use the draft's portable `str(Path("/repo"))`. |

## §4 Semantic conflicts and rules

- **S1. `agy_qualification.py` loses `fcntl`.** The draft removes the module-level
  `import fcntl` and routes its one `flock` through `file_lock.acquire_exclusive`. `main`
  later added a second module-level `fcntl.flock` (the `dir_fd` HOLD-cache path). After the
  merge that call has no import. It must also go through
  `acquire_exclusive(fd, blocking=False)`. The two function-local `import fcntl`
  (`ioctl`, `F_GET_SEALS`) stay. Check: no module-level `fcntl.` reference remains, and
  `tests/test_agy_qci.py` and `tests/test_agy_self_qualification.py` pass with no literal
  bumped.
- **S2. No unvalidated executable runs.** The draft's Codex usage-version probe runs
  `command[0]`. `main` binds that path to the admitted dependency inode. So the probe runs
  only after `dependency.validate_command`, and validation runs again immediately before
  `launch(`.
- **S3. Redaction reaches every sink, and review does not run on native Windows.**
  - **POSIX.** In `consume`, `rendered = redact_seat(rendered)` comes before the usage
    observer, `output_parts`, the log and the stream. Redaction stays per line, as on
    `main` (agent-harness#1282).
  - **Native Windows: review is refused.** At its top, `launch()` raises the existing
    unavailable-executor `ValueError` with a new reason, `review_unsupported_on_windows`,
    when `_native_windows()` is true, `action == "review"` and `dry_run` is false. This
    happens before any spawn and before the ephemeral-monitor recursion.
    - Review cannot qualify on Windows today: the isolated egress network is Linux-only.
    - The draft's Windows owned path has no profile parameter.
    - It returns `windows_process` output unredacted, and its `output` callback sees
      arbitrary byte chunks, which per-chunk redaction cannot make sound.
    - Refusing is therefore the sound rule. Threading a profile through is not chosen.
  - **The `_native_windows()` seam.** It is a new one-line launcher function returning
    `os.name == "nt"`, and the draft's `os.name == "nt"` launch branch uses it. Tests patch
    the seam, never `os.name`.
  - **The Windows recursion.** `launch()`'s Windows-branch re-entry forwards `action`,
    `_review_profile`, `_codex_usage_observer` and `_launch_deadline`. A non-review call
    therefore keeps its action inside `_launch_windows_owned`'s caller.
  - **Tests.**
    - `main`'s redaction tests stay green.
    - A unit test drives `consume` with a seat-credential line and a live profile, and
      asserts that no sink sees it.
    - With the seam patched true, `launch(action="review", …)` raises
      `review_unsupported_on_windows` and no process starts (`Popen` and
      `windows_process.run_owned` are patched to fail).
    - With the seam patched true, `launch(action="execute", ephemeral_monitor=True, …)`
      reaches the Windows branch with `action` forwarded (a recording fake for
      `_launch_windows_owned`).
    - The same refusal test runs unpatched on the dispatched `windows-2025` leg.
- **S4. The adapter is never bypassed.** `main` added lane-wave dispatch to `run_loop`.
  Its lanes build their own launch requests (a fourth `build_launch_request` site) and do
  not pass through the adapter. With `jevdrill_adapter is not None`, `run_loop` does not
  enter the lane-wave branch, whatever `lane_scheduler_mode` is. It takes the whole-phase
  path through `launch_jevdrill`, as the draft did. It records the bypass with `main`'s
  existing `lane_event(None, {"reason": "jevdrill_adapter", "requested_mode":
  lane_scheduler_mode})`, so it is never silent. The draft's existing refusal of
  parallel dispatch and of any phase scheduler other than `off` stays. Test: under the
  default `lane_scheduler_mode`, a planned phase with an adapter enters `prepare` once and
  `launch` once, and the event log holds one `lane_scheduler` event with reason
  `jevdrill_adapter`. With no adapter, the lane-wave path is unchanged.
- **S5. Post-base POSIX code.** Since the draft's base, `main` added POSIX-only calls
  (`os.uname`, `os.getuid`) to `convergence/broker/live.py`, and the Windows tests import
  from it. Fix a call within the owned file only when a Windows test reaches it and the fix
  is a platform guard with no change on POSIX. Otherwise record it under §8 as not done.
- **S6. Model-identifier guard.** The new tests must pass
  `scripts/check_model_id_sources.py`, which CI runs. Replace a flagged literal with the
  central constant, or with a value from the test's own fixture, without changing what the
  test asserts.

## §5 Contract sync (R2)

Survey at §0, comparing the draft's files with jevdrill `998912b1e`:

- 12 of the 14 schemas are byte-identical. `RouteInputs.json` and
  `DiscoveryRouteInputs.json` differ: the draft's copies accept only `JudgeCandidate-v1`,
  and jevdrill's accept v1 or v2.
- `discovery.json` and `host.json` are equal after the substitution.
- `route-inputs.json` has 13 rows. jevdrill's has 19.

Procedure:

1. For each of the 14 names in `tests/fixtures/jevdrill/` other than the three fixtures
   and `digests.json`, fetch the raw bytes:
   `gh api "repos/Consiliency/jevdrill/contents/schemas/<name>?ref=<SHA>" -H 'Accept: application/vnd.github.raw' > <scratch>/<name>`.
   Then copy each one over the harness file. Do not reformat or re-serialize.
2. For each fixture, fetch `tests/contracts/fixtures/<name>` the same way. Replace every
   occurrence of the exact string `utf8-bytes-upper-bound-v1` with
   `<jev-token-counter-revision>`, as a byte substitution, and write the result. Do not
   re-serialize. The harness keeps the placeholder: `jevdrill_fixture_values.py` and its
   test require it.
3. Regenerate `digests.json` as `{"<name>": sha256(file bytes)}` for the 14 schemas, with
   sorted keys, two-space indent and a trailing newline, as the draft wrote it. The draft's
   values are raw-bytes sha256 (checked on two files).
4. Check: `cmp` of each schema against the jevdrill bytes gives 0 differences. For each
   fixture, substituting the placeholder back gives bytes equal to jevdrill's. Every
   `digests.json` value recomputes. No literal remains in the three harness fixtures.
5. Run the adapter, discovery and input tests. A test that pins a fixture row count or a
   v1-only schema shape is updated to the synced contract. Report each such edit.

**SHA rule.** The pull request names the jevdrill SHA it synced to. If jevdrill `main`
changes `schemas/` or the three fixtures before the merge, the lane re-syncs to the newer
`main` commit and names that one. A newer commit with no change to those files needs no
re-sync. Either way the name stays `998912b1e` or later.

## §6 Test selection (R3, R4)

- **Installed-JEV tests.** `test_jevdrill_discovery.py`'s `installed_discovery` fixture
  fails without `JEVDRILL_TEST_CLI` or `JEVDRILL_TEST_PYTHON`, and the real-CLI route test
  in `test_jevdrill_adapter.py` (the draft's line 365) skips without them. The required
  suite installs no JEV Drill.
- **The `jevdrill_installed` marker.** It is registered in `conftest.py` and in
  `pyproject.toml` `[tool.pytest.ini_options] markers`.
  - **Granularity.** The marker is applied per test, as a decorator, to each test that
    uses `installed_discovery` and to the adapter's real-CLI route test. It is **never** a
    module-level `pytestmark` or a class mark. A module mark would suppress the four
    controls that run without JEV Drill.
  - **Skip rule.** `conftest.py` skips a marked item only when neither variable is set, as
    it already does for `dotfiles_integration`.
  - **Collection errors** in `conftest.py`:
    - an item that uses `installed_discovery` without the marker;
    - an item that carries the marker, does not use `installed_discovery`, and is not the
      adapter's real-CLI route test.
  - The fixture's own assertion stays.
  - jevdrill sets the variable, so nothing skips there, and its rule of no other skip
    holds.
- **The reversal.** The draft asserted "Installed JEV CLI is required; discovery cannot be
  skipped". Under this rule, harness `main`'s required suite **skips** the four installed
  controls of §1, because it installs no JEV Drill. The companion workflow (§8) is their
  harness evidence. The pull request says this plainly. The marker is pending JEV's
  acknowledgement (§14).
- **`tests/test_jevdrill_selection.py`.** It asserts the eight control node IDs of §1
  exactly:
  - each is collected, and selected under `-m "not dotfiles_integration"`;
  - none carries `dotfiles_integration`, by function, class or module mark;
  - exactly the four marked "yes" carry `jevdrill_installed`, and the other four do not.

  It also asserts that collecting the seven R4 files under `-m "not dotfiles_integration"`
  deselects nothing. It reports, without gating, whether the two launcher tests of §1 are
  selected. The 53 marked launcher tests are `main`'s own (`PhaseLoopLauncherTest`) and
  stay as they are.
- **No secret.** None of the twelve files reads a credential, a token or the private
  dotfiles repository. The companion workflow (§8) has no `secrets` context.

## §7 Interface preservation (R5)

Every name of R5 exists at the accepted commit under its R5 spelling. **There are no
renames, so there is no rename table.** If a lane must rename one, it stops (§10), because
a rename moves a declared R5 surface. `tests/test_jevdrill_selection.py` imports each name:
`phase_loop_runtime.{launcher,runner,models}`,
`jevdrill_adapter.{JevDrillTransport,JevDrillUnavailable}`, `jevdrill_queue.ReportQueue`,
and the test-module names of R5. It fails on any missing name.

## §8 CI (R3, R6)

- **Required checks are not weakened.** No job, step, `-m` expression, `--ignore` or
  `needs:` of an existing workflow is changed. The twelve files run in the existing
  `suite gate` paths (offloaded or hosted fallback) like any other test. The installed-JEV
  subset skips there under §6, and the pull request says so.
- **New workflow `.github/workflows/jevdrill-companion.yml`.** It is not a required check.
  - Triggers: `push` to `main`, `pull_request` with a path filter (the five modules, the
    portability modules, the twelve files, the helpers, the fixtures, `conftest.py`,
    `pyproject.toml`, `uv.lock`, the workflow itself), and `workflow_dispatch`.
  - `permissions: contents: read`. No `secrets` reference. No `pull_request_target`.
  - Matrix on `push` and `pull_request`: `ubuntu-24.04` only.
  - Matrix on `workflow_dispatch`: `ubuntu-24.04`, `macos-15` and `windows-2025`, each with
    `harness_python: "3.12"`, plus an `ubuntu-24.04` leg with `harness_python: "3.14"`.
  - Inputs:
    - `jevdrill_ref` must be a full 40-hex SHA, checked in the first step. Its default is
      the SHA the pull request synced to (§5).
    - `jev_python` defaults to `"3.14"` (§14).
  - Steps:
    1. `actions/checkout@v4`.
    2. `astral-sh/setup-uv@v6`.
    3. The sync command (below), as
       `uv sync --project phase-loop-runtime --group test --extra visual --locked --python ${{ matrix.harness_python }}`.
       The shape test asserts this one template string. It also asserts that
       `harness_python` is `"3.12"` on every `push` and `pull_request` leg.
    4. A second checkout of `Consiliency/jevdrill` at `jevdrill_ref` into a separate path,
       with `persist-credentials: false`.
    5. `uv sync --locked --python ${{ inputs.jev_python || '3.14' }}` in that path. JEV
       Drill's own `requires-python` is `>=3.14`. The step writes that environment's
       `python --version` to the job summary.
    6. Set `JEVDRILL_TEST_CLI` to that environment's `jevdrill` script
       (`.venv/bin/jevdrill`, or `.venv\Scripts\jevdrill.exe` on Windows).
    7. Run the twelve files with
       `uv run --project phase-loop-runtime --locked --no-sync python -m pytest -p no:cacheprovider -m "not dotfiles_integration" --junitxml=… <twelve files>`,
       with `PYTHONPATH` set to the checkout's `src` and `tests` as absolute paths. The two
       paths are joined with the OS path separator: `;` on Windows, `:` elsewhere. They are
       computed in a `shell: bash` step from `runner.os`.
    8. A step reads the junit file. It fails unless each of the four installed controls of
       §1 appears **by node ID** with outcome passed. It also fails if any
       `jevdrill_installed` test skipped. It writes every other skip, with its reason, to
       the job summary. Platform skips
       such as the native-Windows proofs on Linux are expected. Their per-platform lists
       are jevdrill's to rebuild, and this workflow does not freeze them.
    9. Upload the junit file.
  - `tests/test_jevdrill_companion_workflow.py` asserts this shape.
  - `tests/test_python_floor_1546.py` must still pass.
- **Sync command (R6):**
  `uv sync --project phase-loop-runtime --group test --extra visual --locked`, with
  `--python 3.12` in CI. This is the command `CONTRIBUTING.md` already documents. The
  dispatched matrix is the evidence that it works on hosted Linux, macOS and Windows.
- **CI Python (R6):** 3.12, the floor and the only lane of the required suite
  (agent-harness#1546). JEV Drill runs on 3.14 in its own environment. The dispatched
  3.14 leg runs the harness itself on 3.14, in case R3's "on Python 3.14" means the
  companion too.
- **`pyproject.toml` and `uv.lock`.** The draft needs no new dependency: `jsonschema` and
  `PyYAML` are already runtime dependencies. Only the marker line is added.
  `uv lock --check --project phase-loop-runtime` must pass. `uv.lock` changes only if that
  check fails, and the change is then regenerated, never hand-edited.
- **Evidence and disclosure.** Before the merge, the pull request links the companion
  workflow's `pull_request` run at its head, on the same tree. That is the pre-merge R1
  and R3 evidence. After the
  merge it links the `push` run at the merge commit and, when dispatched, the
  macOS/Windows/3.14 run. Any leg not run, or failing, is disclosed with its reason.
  Under R3 that is a fallback jevdrill accepts, not a reason to hold the merge.
- **Dispatch.** Only the lane executor, after the merge, dispatches the workflow, once,
  with the synced SHA. Planning dispatches nothing.

## §9 Excluded paths and sanitization

- The seven `evidence/HOST-ADAPTER/*.json` receipts record digests of unredacted October
  originals and a source tree this commit does not have. Nothing reads them: jevdrill
  reads none, and no harness code or test names the path. **They are dropped.** Updating
  them would mean fabricating receipts for runs that did not happen. The two
  `.dev-skills/handoffs/codex-execute-phase/*` handoffs and
  `plans/detailed-jevdrill-discovery-host.md` describe the October run and own the
  evidence path. **They are dropped too.** This phase plan supersedes them. Dropping is the
  sanitization-preserving choice, because no redacted text is carried forward.
- `docs/jevdrill-integration.md` is kept and updated (SL-5).
- Disclosure checks before each push:
  - The required `gitleaks` check, which runs the pinned image with the repository's
    `.gitleaks.toml`. No allowlist or `.gitleaks.toml` change is made.
  - A grep of the outgoing diff and commit messages for home and workspace paths, account
    names, machine and tailnet host names, email addresses and private repository names.
    Expected hits: the attribution trailer only.
  - No test fixture holds the counter literal (§5).

## §10 Stop rules

A lane stops and reports, rather than proceeding, if:

- a resolution needs to change a file another lane owns, a file outside the phase's key
  files (the §13 inventory files are key files), `panel_invoker.py`, any `seat_window*.py`, `seat_jail_qualification.py`, a file in
  `SDK_PROOF_FILES`, or an existing workflow's job;
- preserving `main` behaviour (§2) and the draft's behaviour cannot both hold in a hunk;
- an R5 name must be renamed or removed;
- a test in the seven R4 files would need `dotfiles_integration`;
- a contract re-sync (§5) changes a schema in a way the adapter's validation rejects;
- `uv lock --check` fails and regenerating the lock moves a pin that is not in a
  dependency the draft added;
- any step would need a secret, a provider or model call, a live JEV run outside the
  loopback mock, a host other than hosted runners, or the full suite locally.

## §11 Concurrent writers

| Writer | Files it writes | Overlap with JEVHOST | Rule |
| --- | --- | --- | --- |
| K-1 SL-6, agent-harness#2082 | `panel_invoker.py`, `seat_window.py`, `seat_window_supply_codex.py`, `tests/data/seat_launch_references.json`, three `test_seat_window_*` files, `CHANGELOG.md` | **`tests/data/seat_launch_references.json`** (§13). `launcher.py` imports `panel_invoker._redact_seat_credentials`, which agent-harness#2082 does not change. | Whichever lands second rebases and regenerates its own rows of the inventory, then reruns `test_seat_reference_inventory.py`. If JEVHOST is second, SL-4 does it. |
| OI-1 fence lane (after SL-6) | `seat_window_supply_codex.py`, `panel_invoker.py` (`_open_window_launch` only), two `test_seat_window_*codex*` files | None | No ordering. |
| agent-harness#2081 (the agent-harness#2078 fix) | `panel_invoker.py` (the `seat_profile` `credential(source=)` helper), `tests/test_seat_profile_codex_home.py`, `CHANGELOG.md` | None. It does not touch `_redact_seat_credentials`, `_seat_command_profile` or `SeatProfile` as `launcher.py` uses them. | No ordering. |
| Any writer | `CHANGELOG.md`, `plans/manifest.json`, `conftest.py`, `pyproject.toml` | Append or edit conflicts | Rebase and re-resolve. Rerun the owning lane's verify. |

Every package `.py` edit moves `runtime_digest()` and `release_identity()`. Window
records keyed to the old value need requalification after any of these writers lands, as
after any runtime edit. JEVHOST adds no pin to either. Immediately before merging, the
integration pull request is rebased onto `main`. If any of the five conflict files, §4's
files or `conftest.py` changed on `main` since a lane's base, that lane's per-file merge
and verify are redone.

## §12 What this phase may not claim

- No JEV Drill model quality, effectiveness, savings or live-provider claim.
- A dispatched macOS or Windows pass is software conformance on hosted runners only.
- The `claude-sdk-audit` failure on agent-harness#2071 (a landing "removes the auditor")
  comes from the draft's September base predating those files. Expect it to pass on a
  `main`-based branch, but it is not claimed until it does.

## §13 Source inventories (B1)

Several exhaustive tests scan the whole runtime package and assert a closed inventory.
The draft's new and merged modules move them.

| Test | What it pins | What JEVHOST adds |
| --- | --- | --- |
| `tests/test_seat_reference_inventory.py` with `tests/data/seat_launch_references.json` | every `(module, function, primitive)` count of launch, IO and `ctypes` primitives, each with a role | 38 mismatched rows across `file_lock`, `windows_process`, `windows_storage`, `jevdrill_adapter`, `jevdrill_queue`, `phase_worktree_executor` and `launcher`. Recount `agy_qualification` and `dispatch_lock` too. |
| `tests/test_agent_cli_scratch_inventory_1147.py` (`INVENTORY`) | each launch site with an opaque program or an agent CLI needs an entry with a reason | the Codex `--version` probe (`launcher._codex_usage_version`), the JEV CLI spawn (`jevdrill_adapter`), and the `windows_process` child spawn |
| `tests/test_seat_resource_caps.py` (`test_only_ruled_nonseat_callers_select_the_uncapped_probe_context`) | callers of `_uncapped_nonseat_probe` | expected unchanged; run it |
| `tests/test_seat_launch_helpers_trusted.py` | package helpers never launched with `-m`; trusted argv | expected unchanged. The JEV CLI is launched as the installed `jevdrill` script, or on Windows as the installed interpreter with `-m jevdrill.cli`. That is JEV's package, not a harness helper. Confirm the scan agrees, else stop. |
| `tests/test_gate_fail_open_visibility.py` | gates that fail open are visible | expected unchanged; run it |

**Owner.** SL-4 is the inventory reducer. It runs after SL-0 and SL-3, and alone it owns
`tests/data/seat_launch_references.json`, `test_agent_cli_scratch_inventory_1147.py` and
any edit the other three tests need. SL-0 and SL-3 do not run these five tests, because
the tree is incomplete until SL-4. SL-4 runs all five.

**Role rule** for each new or changed row of `seat_launch_references.json`. These are
security decisions, and the pull request lists every added row.

| Site | Role |
| --- | --- |
| `windows_process` executor child spawn (`subprocess.Popen` or `CreateProcess` under the Job Object) and its Job and handle `ctypes` calls | `supervisor` (the Windows twin of `launcher`'s supervised `Popen`) |
| `windows_storage` and `file_lock` IO, `ctypes` and locking | `host-io` |
| `jevdrill_adapter` JEV CLI spawn and the `git check-ignore` call | `host-helper`. JEV Drill is a separately installed host tool, not a provider. |
| `jevdrill_adapter` and `jevdrill_queue` file and SQLite IO | `host-io` |
| `launcher._codex_usage_version` (`codex --version`) | `host-helper`, admissible only under S2: it runs after `validate_command`, with `child_executor_env`, stdin closed and a bounded timeout. Its 1147 entry states that reason. |
| new rows in `launcher` or `phase_worktree_executor` IO | `host-io`, as their existing rows |
| any site that launches a provider or agent CLI without S2's validation or a decided env | none: **stop** (§10) |

A row the table does not cover stops the lane for a ruling, not a guess.

## §14 Questions open with JEV Drill, and fallbacks

Both questions are pending through Root. This contract holds under either answer.

- **Q1. Does JEV accept the `jevdrill_installed` marker?**
  - **Yes:** §6 as written.
  - **No:** the marker is removed, and no new marker is added. `conftest.py` instead
    *deselects*, without skipping, the items that use `installed_discovery`, plus the
    adapter's real-CLI route test. It does this only when neither JEV variable is set.
    jevdrill always sets them, so jevdrill sees no marker and no deselection. The selection
    test then asserts the same eight-control split, keyed on fixture use instead of the
    marker.
  - **No, and JEV objects to any harness-side deselection too:** stop and escalate to the
    owner. The only other route is installing JEV Drill in the required suite, which
    changes a required check (§8).
- **Q2. What is the exact Python 3.14 target?**
  - The workflow's `jev_python` input defaults to `"3.14"`. If JEV names an exact version
    or a patch floor, that default and the 3.14 harness leg's `harness_python` change to
    it. That change is allowed without a repin, and the shape test is updated with it.
  - If JEV means the companion must also run on 3.14 in its required runs, that is the
    dispatched 3.14 harness leg. The required suite stays on 3.12 (agent-harness#1546).
