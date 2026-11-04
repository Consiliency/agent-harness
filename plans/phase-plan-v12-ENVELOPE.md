---
phase_loop_plan_version: 1
phase: ENVELOPE
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 8aea5fbcb0a8caa2b75d51ecb0147bd6f0e9e7db9bdeb9e58988d09bf12fdf2d
automation:
  suite_command: ["python3", "-m", "pytest", "-q", "phase-loop-runtime/tests", "-k", "test_supervised_launch.py or test_supervised_launch_mutations.py or test_supervised_launch_binding.py or test_supervised_launch_route.py or test_supervised_launch_receipt.py"]
---

# ENVELOPE: Admitted launch boundary

## Context

First-phase seam plan for agent-harness#1818, replacing the SCHEMA-first plan.
The roadmap EC IDs are the sole acceptance authority. ENVELOPE can be authored
now against synthetic field-name fixtures; it does not consume unpublished
schema bytes or claim public conformance. SCHEMA later pins public resources;
CLOSEOUT exercises their semantic corpus through the production boundary.

The roadmap is advisory/non-selectable, encoded as superseded because the
current registry has no advisory value. v11 stays active/selected. Manual
seam authoring does not need public publication; automatic phase-loop execution
still needs a separate lifecycle decision. This planning task authorizes no
implementation, providers, delegation, push, review dispatch or live use.

Existing code inspected: executable_dependency_startup.py supplies
refuse_unwired_dependency_route and command classification; base.py supplies
run_bounded and environment scrubbing, but cannot yet return proposals.
output_retention._directory demonstrates uid/mode and no-follow checks.
The convergence journal repairs torn tails, so JOURNAL must not reuse that
behavior. Those modules are inputs to the seam, not evidence it already exists.

## External Inputs

No external commit is required for this phase. The later SCHEMA gate requires
a protected-branch commit and maintainer blob/sha256 inventory from public
Consiliency/consiliency-contract. Do not mark that absent input pre-existing.
Only synthetic, labelled fixtures are authored here; no private schema, vector,
text, source path or revision is copied.

Production use of the provider tier additionally needs an operator-owned
qualification record matching executable/wrapper identities and the closed
template; absent evidence refuses. Injected fixture qualification proves only
boundary mechanics. The frontmatter hash pins the existing roadmap input,
never a future implementation head.

## Interface Freeze Gates

- [ ] IF-0-ENVELOPE-1 — supervised_launch.py exports prepare_launch,
  consume_admission, Validator, Admit, Refused, LaunchInputs and PreparedLaunch;
  supervised_launch_binding.py exports load_validator_binding;
  supervised_dependency.py exports classify_supervised_command and
  preflight_supervised_route. Evidence:
  plans/evidence/supervised-worker/ENVELOPE.md.

These are harness-local Python APIs, not new public wire types.
prepare_launch(envelope_bytes, *, validator, decoder, config) returns
PreparedLaunch or Refused without spawning or writing evidence. decoder is a
trusted injected codec: synthetic in offline tests, later wired to the pinned
public bundle. No production default codec/validator permits fixture launch.
The API itself calls refuse_unwired_dependency_route before decoding or
invoking the validator, so bypassing the CLI cannot bypass required-session
refusal. Catch ExecutableDependencyError and return typed Refused preserving
its reason: the direct unleased required-session test asserts task_unbound;
a bound unwired route asserts dependency_route_unwired. Do not change the
startup helper to rename either reason. CLI preflight additionally precedes
reading the envelope file.
Decode and hash once into an immutable object. Snapshot referenced instruction
and baseline bytes before validation; verify their envelope-bound digests.
Read through dir_fd/O_NOFOLLOW at every component under declared roots; refuse
traversal, symlinks and non-regular files. Trusted config sets explicit per-file,
aggregate and envelope byte caps; overflow refuses before validation. WORKER
owns envelope-file uid/mode/no-follow checks and CLI tests per the roadmap.
Reject duplicate keys, nonfinite values, missing launch bindings and side
channels. The envelope digest follows the supplied codec's digest convention;
a raw-input SHA-256 binds the exact captured bytes.

LaunchInputs carries instruction bytes/digest, closed argv, absolute executable
and wrapper identities, workspace source/baseline, tier/constraints, timeout
and trusted configuration identity. All effective values are presented to the
validator inside the immutable envelope view. Compute the harness launch digest
using the roadmap's domain-separated encoding of raw-input digest, canonical
LaunchInputs and attempt_id; include config, template and qualification digests.
Expose both codec envelope digest and launch digest to the validator;
caller_context is opaque, never an executable-input channel. These local
members do not assert that unpublished schemas already have matching fields.

Validator(view) must return exactly Admit(launch_digest, attempt_id) or a
typed Refused; truthy strings, booleans, exceptions, missing validators and
mismatched identities refuse. The boundary issues a single-use PreparedLaunch
only after admission and capability checks; consume_admission verifies binding
against the launch digest and atomically consumes its token once, after
rechecking workspace classification/root device and inode plus executable/wrapper
digests. Refuse changes. This is process-local: JOURNAL owns durable reservation,
WORKER composes it before probes and repeats identity checks before each spawn;
EC-JOURNAL-3 and EC-WORKER-2 govern cross-process replay and crash reservations. WORKER must call it immediately before
any probe/launch sequence; its token authorizes one bounded attempt, not replay.
Retries need a new attempt and fresh validation. Probe and worker invocations
within that attempt share the immutable inputs; changed identity refuses.

The matrix and workspace definition live in the roadmap. All three required
constraint cells are unsupported for both local tiers; os_enforced always
refuses. Provider mode needs qualification evidence beyond argv. Workspace
inspection is filesystem-only here: reject external gitfiles, shared storage,
alternates, hardlinks and protected-storage symlinks for the provider tier.
Post-write-audit permits worktree/in-place with explicit detection-only posture.
Unknown workspace classifications refuse the requested tier; no downgrade.
Executable resolution is absolute before chdir, excludes empty/relative PATH
entries, paths under workspace/target/envelope-referenced roots, and any
group/world-writable component; pin wrapper realpaths/digests. Qualification
SHA-256 matches govern provider eligibility. Audit-only readiness discloses that
user-owned executables remain writable by same-login processes. Descriptor
execution is preferred where supported; otherwise disclose the residual race.
No version probe is run by ENVELOPE; WORKER owns bounded post-admission probes.

load_validator_binding reads only explicitly configured operator-owned files
outside target/workspace, verifies uid, non-writable group/world modes and
no-follow paths, then loads from a trusted absolute module location. No entry
points, environment imports, cwd imports, envelope-specified code or allow-all
default. The validator implementation remains external and unpinned here.
Apply identical trust checks to codec bindings, qualification records, closed
argv templates and configuration. WORKER uses isolated Python (-I) from the
trusted installed environment; SL-1 proves binding/transitive import behavior
with shadowed stdlib modules under isolated Python, not just validator shadowing.
For every isolated-Python test child, explicitly insert the absolute source root
of the checkout under test, assert phase_loop_runtime.__file__ resolves beneath
it, and record that resolved path in evidence before exercising the guard.
-I ignores PYTHONPATH; the shared venv's primary checkout must not satisfy these
tests. WORKER's CLI tests inherit this checkout-provenance requirement.

preflight_supervised_route runs before envelope I/O, validator loading, probes,
credentials or output effects. Namespaced classifier keys supervised-launch
and supervised-cancel are dependency-unwired; supervised-status is provider-free.
The later module CLI maps its local verbs to those keys without replacing
phase-loop status. Required sessions refuse through the existing startup
guard. A separate exec loses in-process session context; declared envelope
dependencies still refuse and cannot downgrade to standalone.

## Lane Index & Dependencies

SL-0 — Immutable admission and local capability boundary
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Trusted binding and standalone route composition
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no

SL-2 — Evidence and documentation reducer
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Immutable admission and local capability boundary

- **Scope**: Build the process-free admission boundary and synthetic behavioral corpus.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py`, `phase-loop-runtime/tests/test_supervised_launch.py`, `phase-loop-runtime/tests/test_supervised_launch_mutations.py`, `phase-loop-runtime/tests/fixtures/supervised_launch_local/**`
- **Interfaces provided**: `prepare_launch`, `consume_admission`, `Validator`, `Admit`, `Refused`, `LaunchInputs`, `PreparedLaunch`, `admission_test_evidence`
- **Interfaces consumed**: `refuse_unwired_dependency_route` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add labelled synthetic envelope fixtures using the roadmap vocabulary,
    preserving unit/snapshot/obligation identities and opaque caller_context.
    Include launch inputs in the fixture envelope, not beside it. Test every
    launch-input substitution, source-file replacement after admission, invalid
    or replayed verdict, changed attempt/digest, unknown tier/constraint,
    os_enforced, missing/mismatched qualification and unsafe workspace/PATH.
    Instrument fake worker/probe sinks to assert zero invocations on refusals.
    Test a positive one-use admitted attempt without invoking a provider, and
    direct API entry in a required session with zero decoder/validator calls.
    Add reference escape/symlink/non-regular/size cases, identity-only digest
    substitutions and workspace/executable replacement before token consumption.
  - impl: Implement the gate APIs above, immutable snapshots and closed matrix.
    No runtime schema invention, subprocess or git execution is needed.
    Inspect physical workspace storage without trusting its git configuration.
    Do not accept CLI/provider-tail overrides of trusted read-only templates.
    Preserve opaque context in the object, expose only its digest to later
    journal/evidence consumers. Missing executable/config/reference bytes
    refuse; no fallback to ambient values. Fixture bounds are local limits,
    explicitly subject to later public reconciliation.
  - verify: Run V0 and V1. Mutate the production digest/input comparison,
    exact typed-admit check, resolved-identity-only digest binding, token consumption, tier/qualification check and
    workspace classifier individually. Each negative control must enter the
    production guard and turn a previously passing assertion red. Add named
    consumption-time controls: bypass workspace-classification recheck,
    root-device recheck, root-inode recheck, executable-digest recheck and
    wrapper-digest recheck. Add named reference-read controls: bypass root
    confinement, component no-follow, regular-file restriction, per-file cap
    and aggregate cap; also bypass the envelope byte cap. Mutate each separately.
    No mutation of a test-only acceptance model counts as evidence.

### SL-1 — Trusted binding and standalone route composition

- **Scope**: Bind trusted validator configuration and dependency preflight to the admission API.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_launch_binding.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_dependency.py`, `phase-loop-runtime/src/phase_loop_runtime/executable_dependency_startup.py`, `phase-loop-runtime/tests/test_supervised_launch_binding.py`, `phase-loop-runtime/tests/test_supervised_launch_route.py`, `phase-loop-runtime/tests/test_executable_dependency_startup.py`
- **Interfaces provided**: `load_validator_binding`, `classify_supervised_command`, `preflight_supervised_route`, `route_test_evidence`
- **Interfaces consumed**: `prepare_launch`, `consume_admission`, `Validator`, `Admit`, `Refused`, `LaunchInputs`, `PreparedLaunch`
- **Parallel-safe**: no
- **Tasks**:
  - test: Exercise required-session launch/cancel with envelope-read, import,
    output and probe spies that fail if touched. Show ordinary phase-loop
    status remains provider-free; unknown commands retain current refusal.
    Standalone envelopes declaring dependencies refuse before any sink.
    Test group/world-writable, wrong-owner and symlink cases for every trusted
    input (binding, codec, qualification, template, config), workspace and stdlib shadowing,
    entry-point/environment injection, absent bindings and non-Admit returns.
    Use temporary synthetic modules, never a live/private validator.
  - impl: Reuse refuse_unwired_dependency_route, adding explicit classification
    names and a thin supervised preflight API. Keep session propagation semantics
    unchanged. Implement secure external binding, with no automatic discovery
    or default validator. The CLI executable is WORKER scope; freeze its call
    order here. Only standalone/undeclared admission can proceed.
  - verify: Run V2 and the separate required startup-regression command in
    Verification. The frontmatter suite excludes startup regressions; the
    required CI suite gate still covers them. Mutate the
    classification guard, uid/mode checks and trusted import resolution;
    require path-entered witnesses and failure of the corresponding negative
    tests. Record evidence separately from SL-0's results.

### SL-2 — Evidence and documentation reducer

- **Scope**: Synthesize both producer lanes into accurate seam documentation and evidence.
- **Owned files**: `docs/supervised-worker.md`, `plans/evidence/supervised-worker/ENVELOPE.md`, `phase-loop-runtime/tests/test_supervised_launch_receipt.py`
- **Interfaces provided**: `envelope_seam_receipt`
- **Interfaces consumed**: `admission_test_evidence`, `route_test_evidence`, `prepare_launch`, `consume_admission`, `load_validator_binding`, `preflight_supervised_route`
- **Parallel-safe**: no
- **Tasks**:
  - test: Check receipt references against actual producer results, calling the
    production boundary for a positive single-use and a negative refusal.
    Missing results, stale bindings or fixture evidence labelled authoritative
    must fail. Do not make text snapshots the behavioral oracle.
  - impl: Document the frozen APIs, matrix location, standalone guard order,
    codec injection and fixture limitations. Record per-mutant witnesses and
    pending public-schema reconciliation, installed-tool qualification and
    registry activation separately. Note same-login/on-disk credential and
    journal trust limits; WORKER/JOURNAL own their implementation obligations.
    No-doc-change decision for CHANGELOG.md: ENVELOPE freezes a local fixture
    seam; WORKER closeout owns the integrated feature's changelog update.
    README and release notes remain current because ENVELOPE introduces no
    public CLI or release; docs/supervised-worker.md documents the local APIs.
    No changelog handoff gates SL-2 completion.
  - verify: Run V3 and the whole suite. Falsify a receipt binding in a temporary
    copy after entering production and assert rejection. Finalize only actual
    observed results via runner-stamped evidence, never a fabricated pass.

## Execution Notes

All lanes are sequential, with disjoint complete file ownership. SL-2 depends
on both producers. No subagent, scheduler fanout or worktree creation is
authorized. Existing adapter, retention, journal, cli.py, package metadata,
lockfile, init modules and generated bundles stay untouched in this phase;
WORKER owns their later integration. Shared startup changes/tests belong to
SL-1. No schema loader or public schema files are needed for this first phase.

This phase neither tags nor dispatches a release; no post-dispatch lane is
required. Fixture API freeze is not authoritative contract acceptance.
When the public contract differs, amend consumers and rerun production semantic
vectors in CLOSEOUT; do not quietly reinterpret an EC.

Readiness requires all six repository CI checks, exact observed-head Gate A,
independent board and president review in CLOSEOUT. This plan does not dispatch
them. Operational receipts live at plans/evidence/supervised-worker/ENVELOPE.md;
runner-stamped amendments bind observed checks/heads later, never predicted
history. Proxy evidence requires a roadmap amendment. Record proof-cost
advisories above roughly five minutes on one node; report multiple failures.

## Verification

Use the repository's locked Python 3.12+ environment and absolute source/test
PYTHONPATH from CONTRIBUTING.md. These are future implementation commands,
not tests to execute during planning except for collection checks.
Before implementation, pytest --collect-only must find ZERO matches for each
of the five acceptance command selectors (frontmatter suite, whole-phase suite,
V0, EC-ENVELOPE-1 and EC-ENVELOPE-2) on the pre-implementation tree.
After implementation, every node selected by those commands must lie in an
SL-owned test file, and each selected owned file must contribute at least one
node; record both checks in the receipt. Zero collection, skipped-only cases
or pytest exit 5 then fail verification.
Record collected node IDs and mutation outcomes. V0 must collect new tier,
workspace and qualification cases; V2 must collect new binding and route cases.
The effective suite must include those same nodes; absent/skipped required cases
fail intake/closeout even when existing regressions pass. All tests are offline.
SL-0/SL-1 tests that create files whose modes are checked must pin umask to 077
and restore it afterward; set deliberate unsafe modes explicitly with chmod.
Operator documentation must explain that group-writable executable components
are conservatively refused even with user-private groups and umask 002.

- `python3 -m pytest -q phase-loop-runtime/tests -k "test_supervised_launch.py"` — V0.
- `python3 -m pytest -q phase-loop-runtime/tests -k supervised_launch_mutations` — V1.
- `python3 -m pytest -q phase-loop-runtime/tests -k "supervised_launch_binding or supervised_launch_route"` — V2.
- `python3 -m pytest -q phase-loop-runtime/tests -k executable_dependency_startup` — additional required startup regression.
- `python3 -m pytest -q phase-loop-runtime/tests -k supervised_launch_receipt` — V3.
- `python3 -m pytest -q phase-loop-runtime/tests -k "test_supervised_launch.py or test_supervised_launch_mutations.py or test_supervised_launch_binding.py or test_supervised_launch_route.py or test_supervised_launch_receipt.py"` — whole-phase effective suite.

Validate argv and the effective suite through IF-0-VC-2 at planning and intake;
repeat selectors after test creation. Tests use spies/synthetic files and no
external providers. Restore production code after scoped mutations.

## Acceptance Criteria

- [ ] EC-ENVELOPE-1 — proven by `python3 -m pytest -q phase-loop-runtime/tests -k "test_supervised_launch.py or test_supervised_launch_mutations.py or test_supervised_launch_binding.py or test_supervised_launch_route.py"`; falsified by typed-admit/digest/single-use bypass at prepare_launch/consume_admission with path-entered witnesses.
- [ ] EC-ENVELOPE-2 — proven by `python3 -m pytest -q phase-loop-runtime/tests -k "test_supervised_launch.py or test_supervised_launch_mutations.py or test_supervised_launch_binding.py or test_supervised_launch_route.py or test_supervised_launch_receipt.py"`; falsified by tier/workspace or route-guard removal with path-entered zero-effect assertions.
- [ ] EC-ENVELOPE-3 — proven by `python3 -m pytest -q phase-loop-runtime/tests -k "supervised_launch_mutations or supervised_launch_route or supervised_launch_binding or supervised_launch_receipt"`; falsified by surviving production mutants or falsely authoritative fixture receipts.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/supervised-worker.md`
- evidence paths: `plans/evidence/supervised-worker/ENVELOPE.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

Missing/malformed evidence routes to non-human contract_bug. Missing public
inputs later block SCHEMA as upstream_phase_unmet, not this seam's authoring.
