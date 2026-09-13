# Detailed plan: declare the native verification test dependencies

## Task

Repair the dependency-composition part of agent-harness#428. A locked native
test environment must contain the build prerequisites required by the existing
packaging test; the documented test launch must select the existing visual
extra. This bounded repair does not complete a V10 exit criterion or close
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

## Changes

### `phase-loop-runtime/pyproject.toml` (modify)

- Extend `[dependency-groups].test` with `build==1.5.1`, `setuptools>=70.1` and
  `pip`. The unchanged packaging helper invokes `sys.executable -m pip` for
  both direct and sdist-derived wheels. The test-only setuptools floor supplies
  `bdist_wheel` for its `--no-isolation` builds without another undeclared tool;
  this command was incorporated in setuptools 70.1
  ([upstream history](https://setuptools.pypa.io/en/latest/history.html#v70-1-0)).
  Keep `pytest>=8,<9` and the existing `[project.optional-dependencies].visual`
  requirement unchanged. Select visual explicitly at launch instead of duplicating
  its requirement or relying on self-referential group behavior.
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

### Recording files

Register this plan and lifecycle through the native manifest helper; preserve
all prior manifest objects. Ignored handoffs, reflections, exact inputs, native
artifacts and every failed/successful session remain in private evidence custody.
Set this plan's tracked `reflection_ref` to null; the real reflection location
stays in ignored native planning records and encrypted recovery. Preserve the
original unpushed plan commit and its review evidence privately.
No frozen test, workflow, generic runner, interpreter guard, privacy rule, public
signature, serialized field, seal or protocol vocabulary changes in this scope.

## Documentation impact

The runtime README records the declared contributor environment. CI keeps its
existing installation command; consuming the group in CI is a separate workflow
change, not required to correct the native project's missing declarations.

## Dependencies & order

1. Obtain fresh four-vendor native plan review of these exact bytes under the
   current interim authority; recheck agent-harness#752. No consultation vote,
   historical review or president ruling transfers.
2. Record the clean starting tree, uv version, exact manifest/lock/test hashes
   and native coordinator import identity. In a new owned venv on unchanged
   main, run the declared locked sync with the existing visual extra and require
   exit zero. Record missing build/setuptools/pip with importlib discovery, then record
   native RED for the packaging node: the missing build/setuptools prerequisite
   assertion must fail. The visual node is already a positive control with the
   explicit extra and must not be claimed as a new RED falsifier. Preserve the
   earlier no-extra failure separately. No existing test needs alteration.
3. Apply only the manifest, lock and README changes. Use the native detailed-plan
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

RED on unchanged input uses this successful sync and then the packaging node
alone. Before that test, an isolated `importlib.util.find_spec` inspection must
record build, setuptools and pip as absent. Do not run or claim a successful
post-repair import probe in this stage:

```sh
uv sync --project phase-loop-runtime --group test --extra visual --python 3.14 --locked
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests phase-loop-runtime/.venv/bin/python -m pytest -q phase-loop-runtime/tests/test_outside_agent_contract_drift.py::test_sdist_and_wheel_include_only_digest_enumerated_contract_mirror
```

GREEN repeats the same successful locked sync after the reviewed manifest/lock
repair. It then runs the following import/prefix check and the complete native
suite. Record exact locked and installed versions, including setuptools, and
require them to agree; locked sync already rejects stale lockfiles, so a separate
lock --check adds no independent falsifier.

```sh
phase-loop-runtime/.venv/bin/python -I -c 'import build, setuptools, PIL, pip; import sys; from importlib.metadata import version; from packaging.version import Version; assert sys.version_info[:2] == (3, 14); assert sys.prefix != sys.base_prefix; assert Version(version("setuptools")) >= Version("70.1")'
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
```

This is the effective `automation.suite_command`, with run-specific JUnit and
basetemp arguments recorded by the native caller. It exercises both complete
affected test files. RED selects the existing packaging test alone. No full
expensive suite rerun is required for this manifest-only repair; the prior
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

## Acceptance criteria

- [ ] The preserved native RED fails the unchanged packaging assertion for
  missing build prerequisites; the declared sync and import command succeed
  after the manifest repair, with exact inputs and output retained.
- [ ] The effective native suite above passes both complete affected files;
  JUnit and native artifact validation agree and every existing test hash is
  unchanged. This does not accept the remaining agent-harness#428 failures.
- [ ] The separate successful core-only sync and positive runtime import prove
  build, setuptools, pip and PIL remain
  opt-in; project/build-system table comparison and lock-delta inspection show
  no runtime dependency, project/build-system table, Python-floor or unrelated
  upgrade changes. The README long-description and adjacent comment changes are explicit.
- [ ] Fresh plan and source reviews bind their respective exact candidates and
  include non-author ablations; all session evidence is archived and independently
  restored before eligible cleanup. No publication or V10 acceptance is inferred.
