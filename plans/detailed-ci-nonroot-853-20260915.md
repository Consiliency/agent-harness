# Detailed plan: run container tests as an ordinary user

## Task

Resolve agent-harness#853, the CI execution prerequisite for the pending
agent-harness#428 venv-identity repair. Preserve privileged image preparation,
then run the existing Dagger stages as a real non-root user. This standalone CI
repair does not satisfy a V10 exit criterion or establish independent HARDEN
custody. The frozen tests and pending runtime repair belong to their own scope.

## Research summary

Input main is c90b1357d65e76ef778330c3845f4410d38c9710, the merged
agent-harness#841 dependency repair. `AgentHarnessCi._base` uses official Python
bookworm images, installs prerequisites as root and never changes the execution
user. All three suites, the Git-object probe and Gate A use that helper. Live
read-only process evidence on AI records host UID1001 mapped to container UID0;
host UID alone is insufficient. The earlier empty-process observation remains
inconclusive. No unpublished candidate CI failure is claimed.

The frozen permission-denial test requires equal real/effective UIDs and a
nonzero effective UID, proves EACCES and denied executable access, then checks
native failure evidence. Its containing file has SHA256
5d6eb77efbdbf8b7cd7f99135971960dcd30b95b9e337299917b2c81136fad4e.
The other frozen acceptance file has SHA256
a3bc122132e19cf79b086986ce706185ff90dbe7410eccbe108f4d1294dfefe5.
Neither file may change or be skipped. Dagger v0.21.7's upstream generated SDK
supports `Container.with_user`; its source snapshot is retained with SHA256
6670603b446f644cde2280e528164ffbc1a1bd0b5528dedfb42676ab9040e894.

The first plan review did not converge: three AGREE and one PARTIALLY AGREE.
Its exact plan, all four native results and 23 correlated provider files remain
retained. This revision addresses the baseline-input and retention-scope gaps;
no previous vote transfers. Agent-harness#854 separately records the existing
production artifact-loss path: `all()` raises before exporting when a stage
fails, and Gate A deletes its temporary WORK tree. This plan preserves complete
owned diagnostic/provider sessions and their fixtures, plus all actual GitHub
logs/artifacts that CI produces. It does not claim to repair that production
retention defect or recover files already deleted by an earlier execution.

The first published ordinary-user candidate's full CI run 34979555385 completed
with two identical PROOFGATE failures on each Python image; Gate A passed. The
runtime selects `/mnt/workspace/worktrees` if present, otherwise the repository's
parent. In the container the repository is `/src`, so the absent preferred path
causes attempts to create `/proofgate-mutation-*` as UID 1000. The captured errors
are EACCES before mutant execution. Revision 3 provisions that existing runtime
worktree location inside each container; it changes no runtime or frozen test.
This is a concrete CI prerequisite exposed by the full run, not a new roadmap
workstream. Previous review approvals do not transfer to this revision.
The original baseline is already retained; resume this revision at plan review
on the owned branch, preserving its existing implementation and lifecycle.

Revision 3 received two AGREE and two PARTIALLY AGREE verdicts with all native
bindings valid. Revision 4 makes the new regression criterion explicit, preserves
revision/ledger history, and specifies capture before runtime cleanup. The source
repair remains the same single setup argument. These are gaps exposed by the
full-CI failure and review, not future-history constraints or a new workstream.

## Changes

### `ci/dagger/src/agent_harness_ci/main.py` (modify)

- `AgentHarnessCi._base` — create a named `ci` user with UID1000, its own group,
  `/home/ci`, and `/bin/bash` using the image's `useradd`, while still root.
  Keep the current apt packages, interpreter graft, source mount, per-version
  and per-stage root pip cache, and dependency installation unchanged.
- After that privileged installation, assign `/src` and its contents to `ci:ci`
  so build-created files and the full Git object database are writable by the
  test owner. Create `/junit` and `/mnt/workspace/worktrees` owned by `ci:ci`;
  the new home is already user-owned. The worktree directory is container-local,
  never a host mount. Add it to the existing privileged `install -d` argv, before
  the user switch; the existing runtime then uses its preferred location.
  Comment that PROOFGATE fell back to unwritable `/` in CI run 34979555385, so
  the provisioned root and `/junit` are necessary ordinary-user prerequisites.
  These changes apply only to the container snapshot, never the host checkout.
- Set `HOME=/home/ci`, `USER=ci` and `LOGNAME=ci`, then end `_base` with
  `.with_user("ci")`. Every subsequent Git probe, suite and Gate A command must
  inherit that user. Add a short comment explaining the effective-denial reason.
  Do not switch back to root, grant capabilities, introduce sudo, use a host UID
  as proof, or make paths world-writable. Root pip's cache remains for setup;
  any test-time user cache naturally stays in the writable user home.
- Preserve `_suite`, `suite`, `gate_a`, `git_probe` and `all` stage semantics:
  Python matrix, chronology selectors/witnesses, standalone LEGIBLE handling,
  Git-history completeness, concurrency, aggregated failures and existing JUnit
  export. No workflow, offload lease, timeout, SDK/version or Gate A script edit.

### `docs/repo-validation-contract.md` (modify)

Add a short repo-specific Dagger note: package/image preparation is privileged,
but stage commands use the named ordinary user with writable source, home and
evidence directories, including `/mnt/workspace/worktrees`. This makes Unix
permission-denial tests meaningful. It
does not provide a security boundary against the host operator or independent
HARDEN evidence custody. Preserve all command/exit-code vocabulary unchanged.

### `CHANGELOG.md` (modify)

Add an Unreleased entry qualified with agent-harness#853 describing ordinary-user
Dagger stage execution and its writable worktree root. Do not claim runtime
repair, release or V10 acceptance.

### Recording files

Register this plan and its actual lifecycle through the native manifest helpers,
preserving existing entries and history. Use ignored native handoff/reflection
paths and set the tracked reflection reference to null. When an actual eligible
PR exists, record only its actual review facts in
`plans/decision-interim-president-ratification-20260904.md` under the existing
interim rule while agent-harness#752 remains open. No future SHA, commit count
or required history topology is prescribed. That row and the actual final head
need fresh four-vendor review before landing. Write the row before that final
round, recording only already completed review facts and explicitly leaving the
final round pending. Record the final round's actual result on the PR, without
another self-referential recording commit.
For this already published PR, extend its unmerged row in place after actual
revision-4 source review, keeping the R2 head, red CI run and raw log SHA256
541cab43131c45f9dda849eaa2f50550adac1be3283a5ce193aeb08ff285eb14 as history.
Do not rewrite any landed row. Keep prior plan-revision metadata in a manifest
revision-history array when replacing the current revision metadata; retain its
earlier review/archive pointers. The acceptance-criteria count is now five.

## Documentation impact

The validation-contract note and changelog explain the repository's container
execution environment. No runtime, schema, protocol, dependency or public CLI
surface changes. Existing contract exit codes 0, 2, 10, 20, 21 and 30 stay intact.

## Dependencies & order

1. Use the owned clean worktree based on freshly fetched main. Record starting
   status, committed file hashes, current board claim and the effective-UID
   evidence. Commit only the plan/owned manifest row and obtain fresh four-vendor
   native plan review before editing source. Preserve all outcomes and inputs.
2. Establish the root baseline with the unmodified frozen permission witness in
   an isolated diagnostic image built through exact input `_base` bytes. Both
   baseline and candidate use the same pending venv runtime overlay with SHA256
   41b0133662b604c3e3f16fdabb2b17f7ea4f6c07d7e3a14d085d417847ce82b0
   and the two unchanged frozen tests named above. The witness's preceding direct
   venv control must pass before reaching the intended UID assertion failure;
   an earlier identity/setup failure does not satisfy this baseline. The planned
   `_base` execution-user transition is the experimental difference, not a change
   to runtime/test bytes. Record real/effective UID, namespace UID map, CapEff,
   interpreter and the expected assertion failure. Preserve its complete output
   and fixtures; do not call the root test green.
3. Make only the declared implementation/docs edits. Provision an owned locked
   test environment and use native detailed execution/verification artifacts.
   A separate diagnostic module may expose the unchanged candidate `_base` for
   narrow real-container qualification, with byte/AST binding of that method.
   The diagnostic wrapper is not production source or an alternative CI gate.
4. Qualify all three Python images with the effective UID/EACCES probe, writable
   source/Git/home/JUnit operations, both required interpreters and stdlib
   venv/ensurepip. Run both unchanged frozen acceptance files with an explicitly
   labelled copy of the pending venv runtime repair; this overlay is a diagnostic
   input only, not a commit or proof that the repair is already on main.
5. Preserve and independently restore complete owned diagnostics and fixtures,
   then obtain exact-source four-vendor review and use the native publication
   primitive with current ownership safeguards. Final committed-candidate review,
   an actual interim ledger row and required green GitHub CI precede merge.
   The actual matrix and Gate A must pass their unchanged selections; narrow
   qualification is insufficient. Preserve any failure and diagnose its cause.

## Verification

Use distinct native run directories beneath
`.phase-loop/diagnostics/ci-nonroot-853-20260915/` and fresh named basetemps for
each run. Keep all outputs, including failures. Invoke the owned project Python
and native `verification_evidence.run_verification`, with the following locked
command as both recorded provisioning and explicit environment refresh:

`uv sync --project phase-loop-runtime --group test --extra visual --python 3.14 --locked`

Bind `UV_PROJECT_ENVIRONMENT` and the explicit lexical `python_pin` to this owned
worktree's `phase-loop-runtime/.venv`. Use this effective suite argv, rendering
fresh evidence and basetemp paths before each run:

```yaml
automation:
  suite_command:
    - env
    - PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests
    - phase-loop-runtime/.venv/bin/python
    - -m
    - pytest
    - -q
    - --junitxml=.phase-loop/diagnostics/ci-nonroot-853-20260915/local-r1/junit.xml
    - --basetemp=/tmp/ah853-local-r1-20260915
    - phase-loop-runtime/tests/test_ci_chronology_scope.py
    - phase-loop-runtime/tests/test_ci_workflow_concurrency.py
    - phase-loop-runtime/tests/test_ci_offload_lock.py
```

Also run `git diff --check`, native manifest validation and native `docs-audit`.
For revision 3, rerun the two unchanged failed nodes on each real Python image:
`phase-loop-runtime/tests/test_acceptance_falsifier_contract.py::test_mutation_manifest_requires_exact_criterion_parameter_and_command_coverage`
and
`phase-loop-runtime/tests/test_verification_evidence.py::VerificationEvidenceTest::test_proofgate_v3_matched_anchor_kill_requires_green_identical_command_baseline`.
Use the unoverlaid committed runtime for those regressions. Bind their parent
directory evidence to UID/EUID 1000, a writable container-local worktree root,
and the unchanged non-writable `/`; the observed original CI failure supplies
the pre-repair baseline. Preserve all existing root-baseline and 45-node overlay
diagnostics as historical inputs. Requalify the existing 45-node diagnostic on
all three revised images with the same labelled frozen overlay, alongside these
separate unoverlaid regressions. Complete required CI still precedes merge.
Before image dispatch, search existing tests for worktree-root/fallback-location
assumptions and record the findings. Qualification must record traversable parent
directories and actual directory creation by UID 1000, not merely path existence.

For the new unoverlaid diagnostics, capture the runtime's baseline worktree and
complete native-captured command output before its return-code branch, then the
final worktree/output before its existing cleanup. Use a diagnostic-only pytest
trace observer bound to exact runtime hashes and unique AST/code sites; do not
patch runtime functions, subprocess, frames, cleanup or frozen tests. Capture
failure makes the outer diagnostic fail while original cleanup still executes.
Observe actual executor returns for both nodes, including all ten parameter
executions, so early chronology-guard returns cannot masquerade as coverage.
The detailed capture boundary, path ownership, byte/mode/symlink verification,
success/failure/capture-error controls and retention limits are frozen in the
owned `proofgate-diagnostic-retention-design.md` under the train directory below,
SHA256 5ca596cff95f199cbe98d1d93db82b9f2bc664568f9ceafead379541250ea847.
Implement and pass those diagnostic controls before accepting real-image results.
Compile the changed Dagger module and inspect its AST: only `_base` may change.
Verify its order explicitly: privileged setup/install, source and evidence
ownership, environment variables, then user switch last. Keep privileged nesting
and insecure root capabilities at their unchanged disabled defaults.
Compare every existing test file and the workflow, offload script, Gate A script,
matrix/chronology constants and dependency files against the recorded input.
Do not add tests that merely mirror the fluent API implementation.

For actual image qualification, retain a diagnostic driver with explicit
`baseline` and `candidate` invocations. It must use the pinned Dagger module/SDK,
an isolated complete Git snapshot, current existing AI offload lease protocol,
fresh correlation IDs, and the exact hashed `_base` implementation. Preserve
the command, container-side UID/GID and namespace maps, CapEff from
`/proc/self/status`, selected Python/ensurepip,
test collection/results, native artifacts, and all owned fixture bytes/modes
before tearing down the diagnostic. Export failure data from that same executed
container (for example using Dagger's ANY exit policy plus a captured real exit
code); never convert a failed test into a passing native result. Do not edit or
bypass the frozen witness. Retain the raw root failure, then require non-root
positive controls and all frozen acceptance nodes without skips/xfails on
3.10, 3.11 and 3.12. A missing prerequisite blocks that image's acceptance.
Record setup and test-time pip timings against the existing offload budget.
Do not grant write access to system interpreters to fix an out-of-venv install.
Any login-shell or other cross-image identity failure remains an owning runtime
finding, not permission to alter the frozen test or image profiles.

Required GitHub `test.yml` remains the authoritative full matrix/Gate A gate.
Its offload entrypoint is `bash ci/offload-gate.sh` with the workflow's existing
source/head and chronology arguments. Do not invent different selections, run a
second heavy export session, or queue a redundant full local suite. Record actual
workflow head, all stage results, chronology witnesses and exported JUnit. The
existing postmerge run for agent-harness#841 is a different input and its result
does not approve this change. Any upstream advance requires actual integration
and fresh affected verification/review, not manufactured candidate history.

Private/evidence read/write scope: this worktree's ignored diagnostic and native
handoff paths; `/mnt/workspace/trains/agent-harness-runtime-repairs-20260910/ci-nonroot-853-20260915/**`;
the existing venv integration's `integration-inputs`, `source-review-r1` and
installed qualification/UID records; read-only copies of its runtime file and
the two frozen tests; owned `/tmp/ah853-*` fixtures; declared owned AI diagnostic
directories recorded before use; and correlated native provider-retention files.
Existing private recovery tooling and its claimed branch retain encrypted data.
Read/write no foreign session, shared service configuration, host launcher,
publication owner or locked worktree except through its existing native owner.
No VM is needed. No source or fixture may be removed before verified recovery.

## Acceptance criteria

- [ ] Native image baseline records the root UID and the unchanged witness's
  intended UID assertion failure; the diagnostic input hashes remain exact.
- [ ] The real candidate images for Python 3.10, 3.11 and 3.12 execute with
  equal nonzero real/effective UIDs, effective EACCES, writable owned directories,
  usable required interpreters/ensurepip and all unchanged frozen acceptance
  nodes passing without skips; diagnostic artifacts and fixtures prove this.
- [ ] Native local CI-control suite, AST/hash boundaries, docs/manifest checks
  and diff checks pass. All pre-existing tests and non-owned CI behavior remain
  unchanged; complete required CI matrix/Gate A and chronology/JUnit gates pass.
- [ ] Both original failed PROOFGATE nodes pass on all three real Python images
  using the unoverlaid committed runtime. Evidence proves actual executor and
  mutation coverage, UID/EUID 1000, unwritable `/`, and run-directory bindings
  beneath the provisioned writable root. Pre-cleanup snapshots and full captured
  outputs pass the declared retention controls and independent restore checks.
- [ ] Exact-source and final committed-candidate reviews satisfy the existing
  four-vendor/interim rules; native publication confirms the actual PR/head.
  Complete private evidence independently restores before eligible cleanup.
