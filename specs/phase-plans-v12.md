# Phase roadmap v12 — Supervised patch-return worker

## Context

agent-harness#1818 commissions a bounded worker and per-attempt runtime status.
This is a separate initiative from v11. This planning artifact grants no live
execution, route qualification, merge, or release authority. Only SCHEMA is
detailed now; implementation awaits the public contract publication.

## Architecture North Star

An injected validator admits a deployment-neutral envelope before any child
process, including capability probes. A thin patch-return adapter uses
`convergence/adapters/base.py:run_bounded` and `codex.py:run_codex_adapter`.
The worker returns proposal bytes, baseline blob identities, proposal digest,
and attempt identity. The external controller owns patch, post-image, span,
grant and apply checks. The display consumer reads bounded status pages; it
does not create admission, work outcomes or evidence authority.

`ConvergenceResultEnvelope` currently holds only status, attempt_id and detail;
`run_bounded` discards stderr content and parses stdout as a convergence result.
WORKER must extend the shared bounded execution seam compatibly for proposal
capture, stream digests, timing and cancellation. Do not pretend these outputs
exist today or fork another process runner.

## Assumptions

- Consiliency/consiliency-contract publishes public-safe, language-neutral schema bytes
  and positive/negative vectors. Their exact wire keys govern implementation.
- Initial route: **standalone/undeclared**, only with no dependency requirement
  and no authority. Required sessions refuse with `dependency_route_unwired`
  before probes, credential/output effects or host execution. An envelope
  declaring a dependency cannot downgrade to standalone. A projected route
  requires separately planned integration; none is claimed here.
- Local filesystems and existing provider tooling suffice; no new service,
  database or credential is introduced. Installed-provider qualification is
  pending separate authorization; fixture success is not qualification.

## External Inputs

The new pinned input is a **future published commit** of the public repository
`Consiliency/consiliency-contract` containing only the
`admitted_launch_envelope.v1`, `supervised_run_status.v1` schemas and their
conformance vectors/resource closure. Pin that commit plus per-file sha256;
the commit and digest inventory do not exist yet. Their absence blocks SCHEMA,
not planning. These are external inputs, never pins of this roadmap's outputs.
A tag/release needs separate owner approval and is not assumed or requested.

Reuse the existing `consiliency-contract>=0.6.5,<0.7` dependency and its
package-resource path if it exposes the exact published bytes and vector closure.
The conftest floor check is a version compatibility guard, not proof of a commit
or resource digest. If the installed dependency cannot provide those exact
resources without an unapproved release, vendor them byte-identically in the
harness with provenance naming the public repository, full commit and each
file's sha256. Both routes enforce the same explicit content pin, offline.
No change inside consiliency-contract is planned. No private path, repository,
revision, dependency or source text enters public artifacts.

## Non-Goals

No OpenShell backend registration, live provider runs, autonomous merge, Stop
control, display implementation, private dependency, independent wire schema,
or controller-side patch validation. Native cancel remains in scope. No OS
sandbox claim or operational readiness claim follows from these plans.

## Cross-Cutting Principles

- Use `provider_readonly_patch_return_audit`: provider-enforced read-only,
  patch-return and post-run audit in a separate clone or copy. A git worktree
  shares refs/object storage and supports only `post_write_audit_only`.
  `os_enforced` remains reserved/unqualified. Neither same-login processes nor
  network access are contained. Post-hoc `tool_action` detection is not prevention.
- Required `write_scope`, `command_denial` and `network_denial` constraints are
  checked against demonstrated tier capabilities. Unsupported requirements
  produce `constraint_unsupported {constraint, tier}` before launch; never
  weaken constraints silently or infer span enforcement from CLI flags.
- Identity is the assignment digest, envelope digest, `run_id`, `attempt_id`,
  `target_unit_ids`, `readonly_neighbor_unit_ids` and snapshot/crosswalk reference.
  Retry requires fresh admission and a new attempt. Equal proposal digests are
  allowed with distinct, correct provenance; history is never relabelled.
- Preserve `caller_context` opaquely; require `redaction_posture`. The journal
  contains references/digests, not prompts, source, raw streams or secrets.
  Evidence belongs to its producer, with retention via `output_retention.py`
  (agent-harness#1783). Runtime completion never means work acceptance.
- Each implementation lane needs offline tests with production-path witnesses
  and mutation controls. A green test must become red when its production
  guard is removed. Capture multiple failures; flag proof cost exceeding about
  five minutes on one node. No commit counts or future-head pins.

## Top Interface-Freeze Gates

- IF-0-SCHEMA-1 — Verified commit/sha256-pinned public schema/vector bundle and provenance.
- IF-0-ENVELOPE-1 — Injected admission and tier/route refusal boundary.
- IF-0-JOURNAL-1 — Durable journal, replay projection and bounded read API.
- IF-0-WORKER-1 — Bounded proposal-return lifecycle and evidence binding.
- IF-0-CLOSEOUT-1 — Exact-head checks, independent board and honest readiness record.

## Phases

### Phase 1 — Published schema intake (SCHEMA)

**Objective**

Establish the pinned-input gate before runtime implementation.

**Exit criteria**

- [ ] EC-SCHEMA-1 — Published schemas and all referenced resources/vectors match the pinned Consiliency/consiliency-contract commit and per-file sha256, via the existing dependency when suitable or byte-identical vendoring with public provenance; absent or altered inputs fail closed.
- [ ] EC-SCHEMA-2 — The production bundle loader validates both record families against the pinned valid/negative vectors offline, refuses unpinned or remote schema resolution, and has path-entered mutation controls for digest and validation bypasses.
- [ ] EC-SCHEMA-3 — A metadata-only freeze receipt binds the consumed inputs and conformance results, records unresolved contract questions without inventing wire fields, and permits downstream authoring only after the gate passes.

**Scope notes**

Interface-only phase; decompose into 3 lanes: public input intake and loader,
conformance/mutation tests, then dependent documentation reducer. Publication is a
prerequisite, not authorization to author or change the upstream contract.

**Non-goals**

No envelope launch, journal writer, provider process or independent schema.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`
- `phase-loop-runtime/tests/test_supervised_contracts*.py`
- `docs/supervised-worker-contracts.md`

**Depends on**

- (none)

**Produces**

- IF-0-SCHEMA-1 — Verified commit/sha256-pinned public schema/vector bundle and provenance.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/`,
`docs/supervised-worker-contracts.md`; evidence paths:
`plans/evidence/supervised-worker/SCHEMA.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

### Phase 2 — Admitted launch boundary (ENVELOPE)

**Objective**

Bind a validated envelope to an honest, explicit execution tier and route.

**Exit criteria**

- [ ] EC-ENVELOPE-1 — Envelope validation and the injected validator run before any child process; invalid, stale, refused, exceptional or unavailable validation yields typed refusal and zero worker/probe invocations.
- [ ] EC-ENVELOPE-2 — Unsupported required constraints and declared/required dependencies on the standalone route refuse before side effects; `caller_context`, obligation references and full attempt/unit identities survive unchanged.
- [ ] EC-ENVELOPE-3 — Offline mutation tests enter the production launch boundary and detect bypass of admission, capability and executable-dependency guards.

**Scope notes**

Decompose into 2 lanes: admission/tier boundary with tests; dependent route
composition and documentation with tests. No provider CLI probing before
admission. Freeze an injected Python callable protocol without importing its
implementation; CLI callers must use a trusted binding, never an import path
supplied by the envelope. Preserve workspace and repo-relative locator rules.

**Non-goals**

No interpretation of controller grants or obligation semantics.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py`
- `phase-loop-runtime/src/phase_loop_runtime/executable_dependency_startup.py`
- `phase-loop-runtime/tests/test_supervised_launch.py`
- `docs/supervised-worker.md`

**Depends on**

- SCHEMA

**Produces**

- IF-0-ENVELOPE-1 — Injected admission and tier/route refusal boundary.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `docs/supervised-worker.md`; evidence paths:
`plans/evidence/supervised-worker/ENVELOPE.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

### Phase 3 — Attempt journal and projection (JOURNAL)

**Objective**

Provide authoritative attempt history and a replaceable replay projection.

**Exit criteria**

- [ ] EC-JOURNAL-1 — A locked single-writer per-attempt journal in mode-0700 per-user local state outside the target repository drains writes, fsyncs data/directory entries, rotates chained segments, and enforces gapless `seq` from 0 and full attempt/writer identity on every line.
- [ ] EC-JOURNAL-2 — Torn lines, unknown versions, foreign writers and sequence defects return `journal_torn_line`, `journal_unknown_version`, `journal_foreign_writer` or `attempt_overwritten`; readers never repair or truncate, and ambiguous attempts are unknown.
- [ ] EC-JOURNAL-3 — Replay builds per-assignment latest status with each attempt's `seq` and segment digest; stale projections report `projection_behind_journal`, and absent/reused owner pid/start-time reports `owner_not_live`, never a live-running assertion.
- [ ] EC-JOURNAL-4 — Offline mutation tests prove bounded event/attempt pages, `has_more` and omitted counts, retention disclosure, sanitized capped `untrusted_display_text`, and separation of runtime references from work-outcome/evidence joins.

**Scope notes**

Decompose into 2 lanes: durable writer/reader plus tests; dependent projection,
paging and liveness plus tests. Reuse `convergence/event_log.py` durability
discipline, **not** its torn-tail truncation/ignore policy. Reuse
`convergence/status.py` replay-only pattern, not its train event types.
Segments `<attempt>/<nnnn>.jsonl` begin with previous-segment sha256 and last
seq; every `header`, `event`, `state`, `terminal` line carries `schema`,
`version`, `line_kind`, `seq`, identity and writer identity (harness id/version,
writer instance id, owner pid/process start time). `observed_at` is informational.
Freeze numeric bounds from the pinned public contract; proposed limits are not facts.
Journal retention must preserve verifiable chains or explicitly report omitted
history without presenting a truncated chain as complete. No new listener/watch.

**Non-goals**

No display implementation or authority inferred from a cached projection.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/run_status.py`
- `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py`
- `phase-loop-runtime/tests/test_run_status*.py`

**Depends on**

- SCHEMA

**Produces**

- IF-0-JOURNAL-1 — Durable journal, replay projection and bounded read API.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `docs/supervised-run-status.md`; evidence paths:
`plans/evidence/supervised-worker/JOURNAL.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

### Phase 4 — Bounded patch-return worker (WORKER)

**Objective**

Compose admission and journals with the existing bounded adapter lifecycle.

**Exit criteria**

- [ ] EC-WORKER-1 — A thin adapter returns bounded proposal bytes and baseline/proposal/attempt identities from a separate clone or copy, leaves application to the external controller, and keeps existing convergence adapter callers compatible.
- [ ] EC-WORKER-2 — Evidence binds argv, exit, stdout/stderr digests and timing to the envelope digest; standalone identity records executable realpath/sha256/version and wrapper-chain realpaths/sha256, explicitly excluding proof of a wrapper's entire loaded closure.
- [ ] EC-WORKER-3 — Timeout and native idempotent cancel reclaim the owned process group; retries preserve earlier evidence under new admission/attempt identity. States `queued`, `running`, `cancelling`, `finished`, `refused` obey the pinned lifecycle; `refused` never follows launch. `finished` has `termination {reason, signal, by}` with `completed`, `cancelled`, `timed_out`, `failed_to_start`, nullable signal and `worker`, `harness` or `operator` attribution. A nonzero natural exit remains runtime `completed`, not acceptance.
- [ ] EC-WORKER-4 — Offline fake-provider tests and mutation controls cover zero-spawn refusal, malformed/oversized output, process descendants, cancel races, failed start, post-run audit, retries, evidence retention and required-session refusal without live tooling qualification.

**Scope notes**

Decompose into 3 lanes: shared bounded seam and regressions; dependent adapter
and lifecycle integration; dependent CLI/documentation reducer. Use a bounded
execution action, not review mode (review currently has different timeout and
isolation behavior). Capture proposal transport without changing the frozen
convergence status meaning or introducing a third evidence format. Whole-file
`{path, content}` output is not the proposal contract. Capability probes must
bind the same resolved executable as launch; all probes are bounded and occur
after admission. Native CLI surface: `launch --envelope <path> --result <path>`,
`status --run <id>|--attempt <id>`, `cancel --run <id>|--attempt <id>`; confirm
exit codes against the published contract before freezing the public command.

**Non-goals**

No OS isolation, OpenShell registration, live run or controller scope checks.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/codex.py`
- `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py`
- `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py`
- `phase-loop-runtime/tests/test_supervised_worker*.py`
- `phase-loop-runtime/tests/test_convergence_adapters.py`

**Depends on**

- ENVELOPE
- JOURNAL

**Produces**

- IF-0-WORKER-1 — Bounded proposal-return lifecycle and evidence binding.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: canonical_spec_update;
target surfaces: `docs/supervised-worker.md`, `CHANGELOG.md`; evidence paths:
`plans/evidence/supervised-worker/WORKER.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

### Phase 5 — Review and readiness closeout (CLOSEOUT)

**Objective**

Collect independently reviewable evidence without implying permission to run.

**Exit criteria**

- [ ] EC-CLOSEOUT-1 — The reviewed head passes all six required CI checks and dispatched Gate A, with exact observed head/run identities, and a T3 cross-vendor board covering correctness, red-team and adversarial review plus a separate president; unresolved findings block closeout.
- [ ] EC-CLOSEOUT-2 — A metadata-only readiness report distinguishes implemented/offline-tested capabilities, on-main evidence, installed-tool qualification, external conformance and live-use authority; unsupported/unknown items remain explicit with owners and blocked edges.

**Scope notes**

Interface-only evidence reducer phase; decompose into 2 lanes: offline regression
and mutation evidence, then dependent review/readiness reducer. Landing is
maintainer-owned. H1–H9 mapping must distinguish admission, workspace/proposal,
tier, execution evidence, cancellation/tool qualification, journal, reviewed
main, local dependencies and shared-vector conformance. External controller
and display consumer reconciliation cannot be manufactured by harness fixtures.

**Non-goals**

No live qualification, live monitoring acceptance, dispatch of a release or merge.

**Key files**

- `plans/evidence/supervised-worker/CLOSEOUT.md`
- `docs/supervised-worker-readiness.md`

**Depends on**

- WORKER

**Produces**

- IF-0-CLOSEOUT-1 — Exact-head checks, independent board and honest readiness record.

**Spec closeout policy**

schema: spec_delta_closeout.v1; decision: no_spec_delta;
target surfaces: `docs/supervised-worker-readiness.md`; evidence paths:
`plans/evidence/supervised-worker/CLOSEOUT.md`; redaction_posture: metadata_only.
Missing/malformed evidence routes to blocker_class=contract_bug, human_required=false.

## Phase Dependency DAG

SCHEMA → ENVELOPE → WORKER → CLOSEOUT; SCHEMA → JOURNAL → WORKER.

## Execution Notes

SCHEMA may be planned now but cannot execute before the pinned public commit and digest inventory exist. ENVELOPE
and JOURNAL may be planned/executed together only after IF-0-SCHEMA-1, with
machine-verified disjoint ownership and scheduler-assigned worktrees if fanout
is later authorized. WORKER consumes both frozen APIs; CLOSEOUT consumes every
producer's evidence. This task authorizes no delegated execution.

Schema changes require consumer reconciliation, never local schema invention.
Readiness separates work-start, integration, completion and live-use edges:
commissioned authoring after schema freeze is not route qualification; reviewed
main plus external conformance precede qualification; journal proof precedes
monitoring acceptance; fresh admission and owner authorization precede live use.
The roadmap may complete its scoped offline delivery while external/live edges
remain blocked and explicitly recorded. No fixture is a live receipt.

## Verification

Future plans must supply lane commands, negative controls and an effective
`automation.suite_command`, validated through IF-0-VC-2. Offline tests use fake
providers and no network. Proposed whole-feature command after implementation:

```bash
python3 -m pytest -q phase-loop-runtime/tests/test_supervised_contracts.py phase-loop-runtime/tests/test_supervised_contracts_mutations.py phase-loop-runtime/tests/test_supervised_launch.py phase-loop-runtime/tests/test_run_status.py phase-loop-runtime/tests/test_run_status_projection.py phase-loop-runtime/tests/test_supervised_worker.py phase-loop-runtime/tests/test_convergence_adapters.py phase-loop-runtime/tests/test_output_retention.py phase-loop-runtime/tests/test_executable_dependency_startup.py
```

Use the repository's locked test environment and absolute source/test PYTHONPATH
per CONTRIBUTING.md. These future tests are not run during planning. Required
CI: `suite gate`, `lint (pyflakes)`, `chronology retention guard`,
`docs-freshness audit`, `gitleaks`, `check`. Maintainer dispatch:
`gh workflow run test.yml --ref <reviewed-branch> -f chronology=false`; verify
the run actually tested the observed reviewed head, including Gate A. Any
subsequent change invalidates that evidence. T3 board and president review the
same content/head. Runner-stamped evidence/amendments record external check
and review identities under `plans/evidence/supervised-worker/`; no prose proxy
can satisfy a gate without an explicit roadmap amendment. None is dispatched here.
