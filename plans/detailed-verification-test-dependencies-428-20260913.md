# Detailed plan: declare the native verification test dependencies

## Task

Repair the dependency-composition part of agent-harness#428. A locked native
test environment must contain the build prerequisites required by the existing
packaging test; the documented test launch must select the existing visual
extra. Align the contributor group and both existing pinned test-install paths
(hosted pytest and Dagger) on a non-yanked build release.
This bounded repair does not complete a V10 exit criterion or close
agent-harness#428. Seven other environment/fixture failures, the separate proven
venv-identity defect, agent-harness#797, CONFORM and publication gates remain.

## Research summary

Input main is c6b9924b414769ed45bdc3ea47a8d66ec1fe52c7. The runtime's test
dependency group declares only pytest. Its CI install also requires build==1.5.1,
setuptools>=68 and the visual extra. The retained native nine-node reproduction
fails the package-prerequisite assertion and the visual invalid-image assertion
because those dependencies are absent. The package test explicitly builds with
`--no-isolation`; its missing prerequisites cannot be supplied by a hidden build
environment. All four design consultations recommend a project-scoped manifest
repair. They are not formal plan approval and their other recommendations differ.

The first implementation reproduced native RED and passed all 66 tests in both
affected files plus the independent core-only control, with all 597 existing test
hashes unchanged. Source review still failed: Grok rejected the newly declared
yanked `build==1.5.1`; Fable required an in-tree exception and tracked upgrade.
The original plan approval, failed source review and successful checks remain
preserved for their exact inputs and do not approve this revision.

Official [PyPI metadata](https://pypi.org/project/build/1.6.1/) identifies 1.6.1
as non-yanked, with Python >=3.10 and the same declared dependency requirements
as 1.5.1. Its [changelog](https://build.pypa.io/en/stable/changelog.html)
retains the no-isolation path and fixes a Windows symlink regression from 1.6.0.
The r3 plan review found its CI inventory incomplete. The retained search under
`.github`, `ci` and `scripts` confirms the same withdrawn pin and setuptools>=68
in `AgentHarnessCi._base` in `ci/dagger/src/agent_harness_ci/main.py`.
`ci/offload-gate.sh` delegates to that module; it does not install build itself.
The cleanroom step and both publication workflows install build unpinned;
`ci/dagger/pyproject.toml` uses the separate uv_build backend. Those paths stay
unchanged. This revision admits the two existing pinned test-install commands.
The repeated amendments came from copying one CI install line without checking
upstream yank status or the offload installer. The complete inventory and its
raw search output now remain review inputs; no previous vote transfers.
Recheck the selected release metadata before installation;
a changed yank status blocks execution rather than silently choosing another pin.

## Changes

### `phase-loop-runtime/pyproject.toml` (modify)

- Extend `[dependency-groups].test` with `build==1.6.1`, `setuptools>=70.1` and
  `pip`. The unchanged packaging helper invokes `sys.executable -m pip` for
  both direct and sdist-derived wheels. The test-only setuptools floor supplies
  `bdist_wheel` for its `--no-isolation` builds without another undeclared tool;
  this command was incorporated in setuptools 70.1
  ([upstream history](https://setuptools.pypa.io/en/latest/history.html#v70-1-0)).
  Keep `pytest>=8,<9` and the existing `[project.optional-dependencies].visual`
  requirement unchanged. Select visual explicitly at launch instead of duplicating
  its requirement or relying on self-referential group behavior.
- Add an adjacent comment naming the hosted pytest and Dagger install pins that
  must move with this test-group build pin.
- Correct the adjacent visual-extra comment: missing Pillow blocks in opt-in
  blocking mode; warning mode intentionally stays silent. Preserve that behavior.
- Preserve the parsed `[project]` and build-system tables, runtime dependencies,
  Python floor, scripts and pytest configuration. The README change below does
  change the built package's long description, as intended.

### `phase-loop-runtime/uv.lock` (modify)

- Regenerate with `uv lock --project phase-loop-runtime` using the recorded
  installed uv version, without upgrade flags. Accept only the added test-group
  dependency closure and necessary lock metadata. Inspect every other change;
  unrelated package upgrades require correction or re-review, not acceptance.
  Relative to the preserved first candidate, only the build version/artifacts and
  corresponding test requirement should change; compare against both that lock
  and the original input-main lock, retaining all other resolved package objects.

### `phase-loop-runtime/README.md` (modify)

- Add a short contributor test-environment example, run from the repository root:
  `uv sync --project phase-loop-runtime --group test --extra visual --python 3.14 --locked`.
  Follow it with `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
  phase-loop-runtime/.venv/bin/python -m pytest` and the explicit target files.
  Explain that the native repository-wide interpreter guard currently
  includes the dagger subproject's Python 3.14 floor; this is separate from the
  runtime package's Python 3.10 minimum and CI's interpreter matrix.
- State that the group supplies test build/install tools, including pip, and the extra enables image
  decoding. This does not establish complete CI equivalence, visual behavior
  without Pillow, full-suite acceptance or production readiness.

### `.github/workflows/test.yml` (modify)

- In the existing phase-loop-runtime install step, replace `build==1.5.1` with
  `build==1.6.1` and align its explicit setuptools floor to `setuptools>=70.1`.
  Update the adjacent comment to say CI installs test tools explicitly while the
  contributor dependency group is declared in pyproject.toml. Keep the visual
  extra and every other command argument unchanged.
- The comment names the contributor group and Dagger pin as coordinated inputs.
- Preserve every job, matrix, trigger, permission, action version and test command.
  Do not change CI to consume the uv group or claim local tests execute hosted CI.

### `ci/dagger/src/agent_harness_ci/main.py` (modify)

- In `AgentHarnessCi._base`, replace only the install-list requirements
  `build==1.5.1` and `setuptools>=68` with `build==1.6.1` and
  `setuptools>=70.1`. Add an adjacent comment naming the contributor group and
  hosted pytest pin that must move together.
- Preserve every other install argument, image, Python version, cache, stage,
  chronology selection and exported evidence operation. Do not invoke the
  remote offload script as local verification or change its routing/locks.

### Recording files

Register this plan and lifecycle through the native manifest helper; preserve
all prior manifest objects. Ignored handoffs, reflections, exact inputs, native
artifacts and every failed/successful session remain in private evidence custody.
Set this plan's tracked `reflection_ref` to null; the real reflection location
stays in ignored native planning records and encrypted recovery. Preserve the
original unpushed plan commit and its review evidence privately.
No frozen test, other workflow behavior, generic runner, interpreter guard, privacy rule, public
signature, serialized field, seal or protocol vocabulary changes in this scope.

## Documentation impact

The runtime README records the declared contributor environment. The named CI
installation step and Dagger installer keep their form while aligning the build
pin and setuptools floor. Nearby comments name all three coordinated pins. Consuming
the group in CI remains a separate workflow change.

## Dependencies & order

1. Obtain fresh four-vendor native plan review of these exact bytes under the
   current interim authority; recheck agent-harness#752. No consultation vote,
   historical review or president ruling transfers.
2. Record the current owned dirty boundary, uv version, manifest/lock/test hashes
   and native coordinator identity. Reverify the preserved original native RED
   artifact, log seal, successful locked sync and missing build/setuptools/pip
   probe against their independently restored archive and original source/test
   hashes. This already witnesses the missing-prerequisite assertion on unchanged
   main; do not reconstruct clean history or relabel the first candidate's GREEN
   as RED. Preserve both original results. The visual node remains a positive
   control with the explicit extra, not a new RED falsifier. No test is altered.
3. Apply only the manifest, lock, README and the two named CI installer changes. Use the native detailed-plan
   executor's lifecycle and call `verification_evidence.run_verification` directly
   for GREEN. Explicitly provide the reviewed project-scoped sync argv as
   `env_refresh` and the absolute lexical venv path as `python_pin`; the
   generic changed-manifest installer currently infers a root-level bare uv sync
   and must not be substituted or modified by this plan.
4. Obtain fresh four-vendor source review of the exact candidate and its evidence.
   Publication remains held by the shared agent-harness#827 owner. Do not direct
   push, seal, rotate authority or create an approval ledger row before an actual
   eligible PR exists. This plan grants no service/fleet mutation or deployment.

## Verification

All native runs use separate retained run directories inside this owned worktree,
with short, fresh, real `/tmp` pytest basetemps. Preserve complete logs, JUnit and
temporary fixtures. Never reuse a failed run directory or clear session files.

Provision before resolving the explicit interpreter pin because native
`run_verification` resolves that pin before executing `env_refresh`. Record this
initial locked sync and its exit status; then use the identical command as the
explicit native refresh. In this isolated native caller, bind
`UV_PROJECT_ENVIRONMENT` to the absolute lexical path of this owned worktree's
`phase-loop-runtime/.venv` for both calls. The core control uses its own different
environment selector. Neither sync may target an inherited or shared environment.

The RED procedure below describes the preserved original unchanged-input run.
Reverify that evidence; this revision does not repeat it by undoing the owned
implementation. The revised GREEN uses new retained run directories and fresh
basetemps. The prior 66-passed GREEN remains separate evidence for build1.5.1.

RED on unchanged input uses this successful sync and then the packaging node
alone. Before that test, an isolated `importlib.util.find_spec` inspection must
record build, setuptools and pip as absent. Do not run or claim a successful
post-repair import probe in this stage:

```sh
uv sync --project phase-loop-runtime --group test --extra visual --python 3.14 --locked
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror
```

Record the test venv's installed build version before sync so replacement of the
preserved 1.5.1 environment is witnessed. GREEN repeats the same successful locked sync after the reviewed manifest/lock
repair. It then runs the following import/prefix check and the complete native
suite. Record exact locked and installed versions, including setuptools, and
require them to agree; locked sync already rejects stale lockfiles, so a separate
lock --check adds no independent falsifier.

```sh
phase-loop-runtime/.venv/bin/python -I -c 'import build, setuptools, PIL, pip; import sys; from importlib.metadata import version; from packaging.version import Version; assert sys.version_info[:2] == (3, 14); assert sys.prefix != sys.base_prefix; assert version("build") == "1.6.1"; assert Version(version("setuptools")) >= Version("70.1")'
```

Use the absolute lexical path of `phase-loop-runtime/.venv/bin/python` as
`python_pin`, and execute the suite with the explicit relative path below. The
known bare-python shim venv defect is preserved separately, not hidden by a
claim that it passed. No PATH stripping or guard change is needed. Set
`PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests` and `TMPDIR=/tmp`
in the test process. Record actual sys.executable/sys.prefix privately and verify
the imported runtime source matches the candidate. Set cwd to this worktree root
and verify the suite's relative executable names exactly the lexical absolute
pin. Use repo-relative JUnit output paths. The retained native redaction probe
accepted this env-assignment argv and rejected a private-path control; no privacy
exception is needed. Native privacy redaction stays enabled in public-shaped diagnostics.

```yaml
automation:
  suite_command:
    - env
    - TMPDIR=/tmp
    - PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
    - phase-loop-runtime/.venv/bin/python
    - -m
    - pytest
    - -q
    - phase-loop-runtime/tests/test_outside_agent_contract_drift.py
    - phase-loop-runtime/tests/test_visual_avatar_evidence_validator.py
    - phase-loop-runtime/tests/test_ci_chronology_scope.py
```

This is the effective `automation.suite_command`, with run-specific JUnit and
basetemp arguments recorded by the native caller. It exercises both complete
affected test files and the existing CI chronology-scope controls because the
Dagger module is a chronology-selection consumer. RED selects the existing
packaging test alone. No full expensive suite rerun is required for this repair; the prior
5400-passed/53-failed broad result remains FAILED and is not superseded here.

Use a second fresh owned control venv selected by `UV_PROJECT_ENVIRONMENT` and
the same Python 3.14 pin for `uv sync --project phase-loop-runtime --no-default-groups
--no-group test --no-extra visual --python 3.14 --locked`. Require sync exit zero,
then execute that control venv's Python with `-I`: positively import
`phase_loop_runtime`, verify its selected venv prefix, and require importlib
discovery to find none of build, setuptools, pip or PIL. Record the installed
distributions, including setuptools absence. An empty/failed sync or imports
from the test environment cannot satisfy this control. This proves opt-in scope.
Do not use the test venv as this control or let sync prune another agent's env.
Compare the parsed original and candidate project/build-system tables and the
complete old-test hash inventory. Validate native artifact seals and statuses,
check `git diff --check`, and inspect the exact lock delta before source review.

Include the isolated GREEN import/version check as a native `commands` entry so
its exit status is sealed with the suite. Require installed build==1.6.1, its
locked version, the test-group specifier and both parsed CI install pins to agree.
Record the official release's current non-yanked metadata and artifact hashes.
Require lock stderr to contain no yank warning and require the locked build
sdist/wheel hashes to match the official release-file hashes. Retain the SHA256
of every executed check script in the run inputs; native argv seals alone do not
bind script bytes. Recheck that inventory after verification.
For the CI delta, parse both original and candidate YAML, identify the existing
runtime install step, verify only the two declared requirement arguments changed,
then normalize that one `run` value and require the complete documents equal.
The adjacent comment change is visible in the exact diff. This structural and
pin-consistency check also parses the original and candidate Dagger module AST:
identify the unique `_base` pip-install list, verify its complete argv changes
only those two requirements, normalize just those two constants, then require
the entire AST equal without source-location attributes. Preserve offload,
cleanroom and publication file hashes; rerun the retained pin search and require
no remaining build==1.5.1 in the actual CI installer trees. These checks run as
another sealed native `commands` entry. They do not
claim hosted CI or the unrun interpreter matrix passed. Record both owned venvs'
Git ignore status and the complete untracked-file inventory before closeout.

## Acceptance criteria

- [ ] The preserved native RED fails the unchanged packaging assertion for
  missing build prerequisites; the declared sync and import command succeed
  after the manifest repair, with exact inputs and output retained.
- [ ] The effective native suite above passes both complete affected files and
  the existing chronology-scope controls;
  JUnit and native artifact validation agree and every existing test hash is
  unchanged. This does not accept the remaining agent-harness#428 failures.
- [ ] The separate successful core-only sync and positive runtime import prove
  build, setuptools, pip and PIL remain
  opt-in; project/build-system table comparison and lock-delta inspection show
  no runtime dependency, project/build-system table, Python-floor or unrelated
  upgrade changes. The README long-description and adjacent comment changes are explicit.
- [ ] The selected build release is non-yanked; native group, lock, installed tool
  and both CI pins agree on 1.6.1. Both CI setuptools floors agree with the group;
  YAML/AST normalization proves only the two declared installer argv changes.
  Official artifact hashes agree with the lock and its stderr has no yank warning.
  Hosted and offloaded CI remain unclaimed until an eligible actual candidate
  receives those checks; point-in-time agreement is not a permanent drift guard.
- [ ] Fresh plan and source reviews bind their respective exact candidates and
  include non-author ablations; all session evidence is archived and independently
  restored before eligible cleanup. No publication or V10 acceptance is inferred.
