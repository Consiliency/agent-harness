---
phase_loop_plan_version: 1
phase: CLOSEOUT
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 98a5bc1994698c65a5a460872a4871a02bdd4b15ee7f0d3230891b6712640ac5
automation:
  suite_command: ["bash", "phase-loop-runtime/scripts/verify_supervised_v2.sh", "all"]
---

# CLOSEOUT: Adopt published admitted launch envelope v2

## Context

Follow-up for agent-harness#1818 after ENVELOPE (agent-harness#1828). CLOSEOUT
already owns fixture-to-public consumer code/tests/docs and codec reconciliation;
its existing EC-CLOSEOUT goals govern this plan. No new phase is needed. The
roadmap amendment makes its v2 intake and version-window scope explicit, preserves
the DAG/advisory status and SCHEMA v1 history. The supported worker is explicitly
probe-free; ENVELOPE's future WORKER handoff and roadmap seal are reconciled.

Work-start gate: SCHEMA implementation agent-harness#1839 must land with the
reviewed agent-harness#1838 plan and IF-0-SCHEMA-1 receipt; a plan merge alone is
insufficient. Also require IF-0-WORKER-1 and IF-0-JOURNAL-1. They are upstream
interfaces, not claims about today's tree. Until then status is blocked,
blocker_class=upstream_phase_unmet, human_required=false. Reconcile actual landed
APIs and file ownership before execution; amend this plan if they differ. Do not
freeze a predicted merge SHA or mutate SCHEMA's receipt to accelerate adoption.

No implementation, tests, provider runs, external review dispatch, upstream edit,
release or merge is performed by this planning PR. Execution stays sequential.
Panel/PTY integration, projected dependency routes, controller implementation and
installed-tool qualification are outside scope. Existing unsupported paths refuse.

## External Inputs

The sole new contract revision is the untagged Consiliency/consiliency-contract
publication pinned by full commit in the artifact below. Per-file SHA-256/blob IDs,
independent verification, corpus counts and detailed requirements are frozen in
`plans/artifacts/v12-CLOSEOUT-inputs.md`; the manifest frozen_inputs extension
seals that artifact. Read it in full before implementation. Publication ACK is
not runtime evidence. SCHEMA's original v1 inputs remain separately pinned.

Vendor the eleven approved v2 resources, retaining all five frozen v1 payloads
and the extended manifest; upstream provenance is hash-inventoried only. Preserve
the separate v1 bundle. Vendor the three pinned version declaration files too.
Enforce >=0.7.0,<0.8.0 against those hash-verified declarations, with exact agreement,
not installed package metadata. Refuse version/hash/source drift. No pip/uv
contract-package install, dependency-bound/lock change, URL/source override or
registry release is planned; existing unrelated dependency bounds stay unchanged.

The seven adopted decisions and capture/apply/evidence rules in the artifact are
mandatory. External controller/display reconciliation receipts are required input
evidence, not fabricated here. Their absence blocks acceptance, not the initial
consumer implementation lanes after upstream gates land.

## Interface Freeze Gates

- [ ] IF-0-CLOSEOUT-1 — `plans/evidence/supervised-worker/CLOSEOUT.md` binds the
  v2 input inventory, production results, external reconciliation and observed
  review/check identities; `docs/supervised-worker-readiness.md` separates offline,
  on-main, installed, external and live authority. Only its validated v2 receipt
  may assess byte_pin_authority, never authorize runtime launch. This provisional
  publication keeps it false; a separately reviewed non-provisional pin and
  authenticated evidence publisher bindings are prerequisites for any future true.
  SCHEMA's historical receipt and both bundle provenance flags remain false.

The artifact's Frozen local interfaces, Trusted context, Corpus parsing and
Hosted verification sections freeze exact signatures, immutable types, lifetime,
closed diagnostics and evidence protocols for all lanes. load_contract_bundle(*,
version="v1") accepts only v1/v2 (selector_invalid otherwise). v1 remains default;
validate_record adds the v2 family without semantic evaluation. Corpus-container
extraction preserves negative fixture tokens separately from strict record intake.

SL-1 provides the public codec and capture APIs, load_v2_context and
prepare_launch_v2; legacy injection remains test-only. The production binding
always selects verified v2 implementation bytes, never an envelope-selected path.
Independent trusted context carries expected authority, complete route records
and caller-context suitability; missing/invalid inputs refuse. CapturedLaunch
owns one-attempt snapshots/descriptors, with secret delivery held separately
outside both digests, validator views, repr and evidence. consume_admission
retains its signature and returns the same secret-free inputs after full recheck.

Result evidence groups are intake_results, admission_results, lifecycle_results,
external_evidence_intake and readiness_results. Each has case/control IDs, resource
digest, production path witness, outcome and runner artifact digest/run identity.
The reducer checks completeness against verified schemas/corpora and SCHEMA's
named obligations, including zero-vector obligations; it never infers success
from collection or schema pass alone.

## Lane Index & Dependencies

SL-0 — Versioned intake and package preamble
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Public codec, capture and admission
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — Worker and journal reconciliation
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Documentation and readiness reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Versioned intake and package preamble

- **Scope**: Extend the landed SCHEMA loader with separately pinned v2 resources and exact-commit vendored provenance.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v2/**`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/MANIFEST.in`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_supervised_contracts*.py`, `phase-loop-runtime/scripts/verify_supervised_contract_publication.py`, `.github/workflows/supervised-contract-intake.yml`, `.github/workflows/test.yml`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/scripts/verify_supervised_v2.sh`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`, `phase-loop-runtime/tests/test_ci_chronology_scope.py`, `phase-loop-runtime/tests/test_ci_offload_lock.py`, `.gitleaks.toml`
- **Interfaces provided**: `load_contract_bundle`, `validate_record`, `ContractBundle`, `ContractError`, `intake_results`
- **Interfaces consumed**: `IF-0-SCHEMA-1` (upstream), `jsonschema` (pre-existing), frozen input inventory
- **Parallel-safe**: no
- **Tasks**:
  - test: Extend production loader/selector/resource and receipt controls for both
    versions; preserve v1 regressions without treating the old receipt as v2.
    Verify all 255 schema expectations and complete canonical/apply/status
    inventory, correctly labelled schema-only. Missing bytes, changed manifest,
    altered metadata/pin table, unlisted references and stale artifact seals
    fail. Require the base-ref input-amendment policy and full publication proof
    defined in the artifact. Cover vendored-version bounds/agreement, corpus
    extraction, every schema pattern, binary64 domain and installed resources.
    Gate A must receive mandatory inputs without skip; test its sparse allowlist
    and wheel provenance, plus source-wrapper environment and CI path selection.
  - impl: Fresh-fetch protected main and prove ancestry/hash/blob identity from
    expected pins. Extend package-data/MANIFEST and hosted path detection for the
    explicit artifact detector set and both manifest seals. Preserve read-once
    buffers, offline references and sanitized errors. Add vendored declaration
    checks, not package installs. Extend Gate A sparse inputs and test.yml for
    in-environment byte/version proof. Implement the source-pinned V0–V3 wrapper.
    Update SCHEMA historical-module, exact-import-allowlist and signature tests
    as frozen in the artifact, retaining original receipt/provenance bytes.
    uv.lock is owned as a companion guard only: its bytes remain unchanged;
    pyproject edits are package-data only, with no dependency change.
    Any inert corpus exception must name an exact path and exact gitleaks rule.
  - verify: V0; hosted publication comparison and installed wheel/source-byte
    proof. Store observed artifacts in intake_results, never prefilled verdicts.

### SL-1 — Public codec, capture and admission

- **Scope**: Reconcile ENVELOPE through a distinct v2 production adapter and immutable launch capture.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_envelope_v2.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_capture_v2.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_launch_binding.py`, `phase-loop-runtime/tests/test_supervised_envelope_v2.py`, `phase-loop-runtime/tests/test_supervised_capture_v2.py`, `phase-loop-runtime/tests/test_supervised_launch*.py`, `phase-loop-runtime/tests/fixtures/supervised_launch_local/**`
- **Interfaces provided**: `parse_v2`, `canonicalize_v2`, `decode_v2`, `validate_v2_admission`, `capture_launch_v2`, `recheck_launch_v2`, `load_v2_context`, `prepare_launch_v2`, `consume_admission`, `admission_results`
- **Interfaces consumed**: `load_contract_bundle`, `validate_record`, `ContractBundle`, `intake_results`, ENVELOPE typed Admit/local identity trust checks (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Run published admission and canonical corpora through production APIs,
    checking exact first-stage diagnostics/effects, raw and in-memory domain
    boundaries, UTF-16 ordering, negative zero, __proto__, whole-envelope secret
    safety at every normative location and same-source rotation of both public
    and local digests. Exercise trusted-file authority/snapshot, suitability,
    record validity/revocation/duplicates and production v2-only entry controls,
    including missing inputs and secret-free views/errors/repr. Exercise capture
    ancestors, raw links, mode bits, external-root and descriptor capture,
    independent cwd and discovered config, mutable env/reference/grant rechecks,
    duplicate qualification and credential-source coverage. Each guard has a
    production-entry witness and source-copy bypass that turns a passing assertion
    red; do not mutate a test-side oracle to manufacture proof.
  - impl: Implement the frozen artifact's seven decisions, source/cwd mappings,
    redacted classified environment and effective grant forms. Keep local trust,
    ownership and dependency preflight; no public path/FD/attempt fields. Both
    tiers require exactly one held matching route record; unsupported constraints,
    os_enforced, interactive stdin and unwired dependencies stay refused. Preserve
    caller_context only after trusted suitability and generic checks. Record
    contract and supported-route results separately for every control; provider
    write_scope needs authenticated apply evidence, and dependency routes remain
    closed. Bind final outer argv and
    declared helper transformations, not an earlier command. Extend consume-time
    recheck to all committed material. Never replace JCS with Python sort_keys or
    the old review-tree hash. Null/missing public codec refuses before effects.
  - verify: V1 and existing ENVELOPE controls; emit admission_results with input
    digests and guard witnesses. Synthetic qualification proves mechanics only.

### SL-2 — Worker and journal reconciliation

- **Scope**: Apply admitted v2 inputs at the shared worker boundary and reconcile runtime status/evidence.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/codex.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py`, `phase-loop-runtime/src/phase_loop_runtime/run_status.py`, `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py`, `phase-loop-runtime/tests/test_supervised_worker*.py`, `phase-loop-runtime/tests/test_run_status*.py`, `phase-loop-runtime/tests/test_convergence_adapters.py`, `phase-loop-runtime/tests/test_executable_dependency_startup.py`
- **Interfaces provided**: `lifecycle_results`, `external_evidence_intake`
- **Interfaces consumed**: `prepare_launch_v2`, `consume_admission`, `recheck_launch_v2`, `admission_results`, `IF-0-WORKER-1` (upstream), `IF-0-JOURNAL-1` (upstream), `output_retention.mark/prune` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Enter actual CLI/adapter/journal paths using offline subprocesses and
    injected providers. Assert zero auxiliary/chain/worker starts on refusal,
    no worker-path probes at any time, one chain deadline, helper failed_to_start, exact one-shot stdin,
    empty DEVNULL, replay across processes/restarts and reservation failure.
    Reconcile v1 status and v2 journal cases, copied evidence, equal proposals
    with distinct attempts, baseline identities, crosswalk, cancellation,
    retention and bounded projections. Own all six echo cases at the actual
    JOURNAL writer, with exact JCS numeric and __proto__ preservation. Preserve
    convergence caller regressions.
    Bypass each recheck/reservation/lifecycle/evidence guard in separate temporary
    source copies and require a failing production assertion.
  - impl: Consume/recheck immutable capture immediately at the final spawn
    boundary with no ambient inputs. Consume held qualification, never run
    probes, and never restart the monotonic timer. Preserve durable attempt reservation,
    native cancellation and explicit descendant limits. Bind actual stream,
    process, proposal, baseline and run/attempt evidence. External controller
    apply outcomes, including rejected proposals, remain finished work outcomes;
    provider write_scope applies even with empty constraints. Obtain independent
    production controller evidence for all 13 apply cases without implementing
    controller checks here; missing evidence remains blocked. Reconcile the full
    SCHEMA obligation union, never treating opaque echo as identity authority.
  - verify: V2, installed isolated CLI tests and external evidence validation;
    preserve unsupported-route diagnostics and emit lifecycle_results. No live
    provider qualification or operational route expansion occurs.

### SL-3 — Documentation and readiness reducer

- **Scope**: Reconcile every producer into a truthful v2 authority and readiness report.
- **Owned files**: `docs/supervised-worker-contracts.md`, `docs/supervised-worker.md`, `docs/supervised-run-status.md`, `docs/supervised-worker-readiness.md`, `plans/evidence/supervised-worker/CLOSEOUT.md`, `phase-loop-runtime/tests/test_supervised_v2_readiness.py`, `phase-loop-runtime/scripts/verify_supervised_v2_evidence.py`, `.github/workflows/supervised-v2-evidence.yml`, `CHANGELOG.md`
- **Interfaces provided**: `IF-0-CLOSEOUT-1`, `readiness_results`
- **Interfaces consumed**: `intake_results`, `admission_results`, `lifecycle_results`, `external_evidence_intake`
- **Parallel-safe**: no
- **Tasks**:
  - test: Compare every required corpus/rule/obligation to actual production
    outcomes and runner artifacts. Reject missing/skipped-only results, changed
    resource identities, stale review heads, missing external proofs, secret
    content and an unjustified true receipt. Test authenticated evidence lookup,
    exact content-identity/exclusion rules, ancestry and stamp-only delta,
    post-landing applicability and governing-content change invalidation through
    the verifier. Offline V3 cannot establish hosted evidence authenticity.
  - impl: Implement the hosted network verifier and artifact evidence protocol.
    Resolve the live required checks plus full-path publication (contract=true),
    Gate A, board, separate president and external producer evidence through
    authenticated sources. Record provisional publisher status and keep authority
    false; future true requires a reviewed successor pin and publisher-binding
    amendment as well as every semantic/identity/lifecycle/evidence obligation.
    Apply the exact content identity and post-landing validity rules; provenance
    metadata remains false and runtime admission never consumes this boolean.
    Preserve SCHEMA's historical receipt. Document
    separate offline, on-main, installed qualification, external and live-use
    status; missing on-main/live evidence stays explicit with owner/blocked edge.
    Record corrections to stale v2/caller_context/corpus assumptions. Add an
    Unreleased changelog entry; no release or merge claim follows.
  - verify: V3, the effective suite, required CI, dispatched Gate A and the
    roadmap's T3 cross-vendor correctness/red-team/adversarial board plus separate
    president on the observed reviewed content. Any unresolved finding blocks
    closeout. These are future execution gates, not dispatches in this task.

## Verification

Future commands only. The owner prohibits test suites on this shared host;
run them on hosted CI or an explicitly authorized isolated executor. Check uptime
before allowed local metadata validators. Use locked Python 3.12+ and absolute
source/test PYTHONPATH per CONTRIBUTING.md through the explicitly owned
verify_supervised_v2.sh runner, whose environment/provenance contract is frozen
in the artifact. It performs no installs. No make check or parallel local suites.

- V0: `bash phase-loop-runtime/scripts/verify_supervised_v2.sh V0`
- V1: `bash phase-loop-runtime/scripts/verify_supervised_v2.sh V1`
- V2: `bash phase-loop-runtime/scripts/verify_supervised_v2.sh V2`
- V3: `bash phase-loop-runtime/scripts/verify_supervised_v2.sh V3`

Validate V0–V3 and automation.suite_command using
verification_evidence.validate_verification_commands (IF-0-VC-2). Missing owned
future files are pre-implementation findings; repeat after upstream landing and
file creation, requiring zero findings before execution verification. Collect
all newly created parameterized nodes; require actual outcomes, not collection
alone, and prohibit exit-5/skipped-only success. Report multiple failures and
flag proof cost over roughly five minutes per node.

The artifact enumerates each wrapper group; all is their deduplicated union.
Hosted publication proves exact upstream/vendored wheel bytes. Require the live
protected-main check set plus full-path supervised contract publication, Gate A
and the authenticated evidence assessment. Authorized maintainer dispatches
`gh workflow run test.yml --ref <reviewed-branch> -f chronology=false` and records
Gate A's actual tested head, run/job and artifacts. Board/president and external
consumer receipts use the same observed content; never pin predicted hashes.
The reducer validates their identities; proxy evidence requires roadmap amendment.
Validator check (N) recognizes package/changelog ownership as release-shaped;
this phase dispatches only verification, not a tag or release. SL-3 records
post-verification evidence, so no separate release-dispatch reducer is applicable.

## Acceptance Criteria

- [ ] EC-CLOSEOUT-1 — proven by V0–V3, the effective suite and `plans/evidence/supervised-worker/CLOSEOUT.md` runner-stamped CI/Gate A/board/separate-president/consumer artifacts; falsified by path-entered guard bypass, missing corpus/obligation outcomes, stale or absent external evidence.
- [ ] EC-CLOSEOUT-2 — proven by V3 against the production results and `docs/supervised-worker-readiness.md`; falsified by path-entered receipt mutation claiming unobserved qualification, a stale head or unsupported authority.

## Execution Notes

All lane paths are disjoint; reducers explicitly consume every producer. No
subagents or writer fanout are authorized. output_retention.py and its test stay
unchanged regression inputs; integration call sites belong to SL-2. Existing
panel/launcher/review_stage and dependency-routing code remain unchanged; their
routes are not adopted. New modules are auto-discovered; no __init__ export is
needed. No skill text/bundle is edited. If upstream WORKER/JOURNAL introduces
additional companions or snapshots, enumerate them by amendment before work.
The archived SCHEMA artifact/receipt retain their original input hashes. Rebase
integration must refresh its plan's roadmap_sha256 against the final roadmap
and validate it before execution; it is absent on this branch. ENVELOPE's plan
seal and probe handoff are repaired here. CLOSEOUT owns a new path-keyed input
seal; historical receipt verification uses its recorded module blob.

Next phase: CLOSEOUT — blocked pending landed SCHEMA and WORKER/JOURNAL gates.
Next command: none until upstream gates are verified; then
`codex-execute-phase plans/phase-plan-v12-CLOSEOUT.md` under separate execution authority.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/supervised-worker-contracts.md`, `docs/supervised-worker.md`, `docs/supervised-run-status.md`, `docs/supervised-worker-readiness.md`
- evidence paths: `plans/evidence/supervised-worker/CLOSEOUT.md`
- redaction posture: `metadata_only`
- downstream handling: `none`
