---
phase_loop_plan_version: 1
phase: CLOSEOUT
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 98a5bc1994698c65a5a460872a4871a02bdd4b15ee7f0d3230891b6712640ac5
automation:
  suite_command: ["bash", "phase-loop-runtime/scripts/verify_supervised_v2.sh", "all"]
---

# CLOSEOUT: Adopt published admitted launch envelope v2 (re-plan on landed code)

## Context

Owner decision 2026-11-09: CLOSEOUT is re-planned on the landed code and keeps
its roadmap goals, EC-CLOSEOUT-1 and EC-CLOSEOUT-2. This plan replaces the
previous CLOSEOUT plan, which is replaced rather than amended. The supersession
is an appended `replan` lifecycle event on the existing `plans/manifest.json`
row `v12-CLOSEOUT`, which records the superseded plan's hash and keeps every
earlier field and seal.

Since that plan was written, SCHEMA, JOURNAL (agent-harness#1934,
agent-harness#1955), WORKER (agent-harness#1956, with the trusted launcher
agent-harness#1957 and `stamp_evidence_receipt.py`), the docs audit and release
0.7.31 (agent-harness#1916, agent-harness#1895) have landed. No work-start gate
remains. Those receipts are local and fixture-scoped: the production
`supervised_worker_cli launch` still refuses `codec_unavailable`, so every
CLOSEOUT obligation is still open.

Three frozen artifacts carry the detail. Read all three before building:

- `plans/artifacts/v12-CLOSEOUT-inputs.md`, unchanged: external pins, corpus
  accounting, the seven adopted decisions, capture/apply/evidence boundaries, the
  frozen local interfaces, trusted context and hosted verification.
- `plans/artifacts/v12-CLOSEOUT-landed-binding.md`: what is still owed (§1),
  the landed-interface table with every touchpoint at `file:line` (§2), the
  STOP decisions (§3), the bindings the landed code forces (§4), the verification
  groups (§5) and the historical receipt seals (§6).
- `plans/artifacts/v12-v13-replan-ownership.md`: the one ownership map for
  CLOSEOUT, PLACECLI and LANEEXEC, and the integration order.

The manifest row seals all three. Out of scope: panel/PTY integration, projected
dependency routes, a controller implementation, installed-tool qualification,
release and merge. Unsupported paths keep refusing.

**STOP decisions** (each recorded with its reason in the binding artifact §3):

| Item | Decision |
| --- | --- |
| C-S1 | The echo is a separate content-addressed artifact in SL-2's `supervised_echo.py`, outside the journal root. It is bound by the digest the JOURNAL index entry already reserves, written after admission and before `reserve_attempt`, and emitted byte-exact by the v2 reader view. `run_status.py`, its record schema, `REF_KINDS`, phrases and parser stay unchanged. Sweep recommendation adopted. |
| C-S2 | Historical receipts keep their bytes and outcomes and are verified historically (seal, internal digest, controls still present). CLOSEOUT evidence is published separately and pins no shared file. Adopted. |
| C-S3 | SL-2 owns the launch inventories, the worker fixtures and `_run_status_vectors.py`. The stamp tool is used unchanged, never owned. Adopted. |
| C-S4 | Acceptance stays blocked until external producer evidence exists; implementation lanes still land. Adopted. |
| X-S1 | Serial integration CLOSEOUT → PLACECLI → LANEEXEC with additive shared files. Adopted; the map is in the ownership artifact. |

## Interface Freeze Gates

- [ ] IF-0-CLOSEOUT-1 — `plans/evidence/supervised-worker/CLOSEOUT.md` binds the
  v2 input inventory, production results, external reconciliation and observed
  review/check identities; `docs/supervised-worker-readiness.md` separates offline,
  on-main, installed, external and live authority. Only its validated v2 receipt
  may assess `byte_pin_authority`, never authorize runtime launch. At this
  provisional publication it stays false, as do both bundle provenance flags and
  SCHEMA's historical receipt.

Plan-level freezes consumed downstream (no new roadmap gate): the inputs
artifact's "Frozen local interfaces" table; `AttemptBinding` carried in
`PreparedLaunch`, and `discard_admission` (binding §2, §4.1); the §4.2 controller
document for `supervised_worker_cli launch --envelope --result`; the total
`WorkerResult` to v2 status mapping (§4.3); and `supervised_echo.write_echo` /
`supervised_echo.read_echo` (§3 C-S1). LANEEXEC's work-start
gate names these. Concrete record fields come only from the pinned schemas;
exceptions translate to closed codes, and no payload, path or secret enters a
diagnostic.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/supervised-worker-contracts.md`, `docs/supervised-worker.md`, `docs/supervised-run-status.md`, `docs/supervised-worker-readiness.md`
- evidence paths: `plans/evidence/supervised-worker/CLOSEOUT.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Lane Index & Dependencies

SL-0 — Versioned intake, package preamble and historical receipts
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Public codec, capture and admission
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — Worker, journal and production CLI reconciliation
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Documentation, evidence verifier and readiness reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Versioned intake, package preamble and historical receipts

- **Scope**: Vendor the pinned v2 resources behind a versioned loader, add the V0–V3 wrapper and Gate A inputs, and introduce historical receipt verification.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v2/**`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`, `phase-loop-runtime/MANIFEST.in`, `phase-loop-runtime/tests/conftest.py`, `phase-loop-runtime/tests/test_supervised_contracts*.py`, `phase-loop-runtime/tests/historical_receipts.py`, `phase-loop-runtime/scripts/verify_supervised_contract_publication.py`, `phase-loop-runtime/scripts/verify_supervised_v2.sh`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/tests/test_gate_a_wheel_isolation.py`, `phase-loop-runtime/tests/test_ci_chronology_scope.py`, `phase-loop-runtime/tests/test_ci_offload_lock.py`, `.github/workflows/supervised-contract-intake.yml`, `.github/workflows/test.yml`, `.gitleaks.toml`
- **Interfaces provided**: `load_contract_bundle`, `validate_record`, `ContractBundle`, `ContractError`, `historical_receipts.verify_historical_receipt`, `intake_results`
- **Interfaces consumed**: `IF-0-SCHEMA-1` (pre-existing), `jsonschema` (pre-existing), `plans/artifacts/v12-CLOSEOUT-inputs.md`, `plans/artifacts/v12-CLOSEOUT-landed-binding.md`
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-0.1 | test | — | `tests/test_supervised_contracts*.py`, `tests/test_gate_a_wheel_isolation.py`, `tests/test_ci_*.py` | v1/v2 selector and `selector_invalid`; every pinned resource and version declaration, including drift, missing bytes, unlisted references and stale seals; all 255 schema expectations labelled schema-only; corpus extraction and the binary64 domain; installed-wheel resource assertions placed in `GateAConformEvidenceScopeTest`, the only class V0 runs; the wrapper's groups (binding §5); historical helper controls in which a changed receipt byte, a wrong internal digest, a removed producer node (except a node retired in binding §6) and a removed mutation control each fail; the SCHEMA receipt test converted to the helper | `V0` |
| SL-0.2 | impl | SL-0.1 | SL-0 owned files | — | — |
| SL-0.3 | verify | SL-0.2 | SL-0 owned files | all SL-0 tests | `V0` |

SL-0.2 vendors from the exact pinned commit after a fresh-fetch ancestry and
hash/blob proof, extends package data, `MANIFEST.in`, Gate A sparse inputs and
`test.yml`, and writes the source-pinned wrapper. `uv.lock` bytes stay unchanged;
no dependency or bound changes. `historical_receipts.py` implements binding §3
C-S2 with the §6 seals.

### SL-1 — Public codec, capture and admission

- **Scope**: Reconcile ENVELOPE through a distinct v2 production adapter, immutable launch capture and an `AttemptBinding` held outside the envelope.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_envelope_v2.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_capture_v2.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_launch.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_launch_binding.py`, `phase-loop-runtime/tests/test_supervised_envelope_v2.py`, `phase-loop-runtime/tests/test_supervised_capture_v2.py`, `phase-loop-runtime/tests/test_supervised_launch*.py`, `phase-loop-runtime/tests/fixtures/supervised_launch_local/**`
- **Interfaces provided**: `parse_v2`, `canonicalize_v2`, `decode_v2`, `validate_v2_admission`, `capture_launch_v2`, `recheck_launch_v2`, `load_v2_context`, `load_v2_binding`, `prepare_launch_v2`, `consume_admission`, `discard_admission`, `AttemptBinding`, `admission_results`
- **Interfaces consumed**: `load_contract_bundle`, `validate_record`, `ContractBundle`, `historical_receipts.verify_historical_receipt`, `intake_results`, `prepare_launch` (pre-existing), `trusted_bytes` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-1.1 | test | — | SL-1 test files | ENVELOPE receipt test converted to the historical helper before any SL-1 source edit; the published admission and canonical corpora through production APIs with exact first-stage diagnostics and effects; raw and in-memory domains, UTF-16 ordering, negative zero and `__proto__`; whole-envelope secret safety and same-source rotation of both digests; trusted context, suitability, record validity, revocation and duplicates; capture ancestry, links, modes, descriptors, cwd, environment and grant rechecks; `AttemptBinding` mismatch refuses; each guard has a production-entry witness and a source-copy bypass that turns it red; `discard_admission` removes the token and closes descriptors, a discarded admission cannot be consumed, and repeated prepare/discard leaves the registry empty | `V1` |
| SL-1.2 | impl | SL-1.1 | SL-1 owned files | — | — |
| SL-1.3 | verify | SL-1.2 | SL-1 owned files | all SL-1 tests | `V1` |

SL-1.2 implements the inputs artifact's seven decisions and frozen local
interfaces. `prepare_launch` stays the offline fixture seam; production never
reaches it. A null or missing public codec refuses before effects.

### SL-2 — Worker, journal and production CLI reconciliation

- **Scope**: Wire the production CLI to the v2 binding, bind worker identity and echo outside the envelope, and map local results to v2 status.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_worker_cli.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/base.py`, `phase-loop-runtime/src/phase_loop_runtime/convergence/adapters/patch_return.py`, `phase-loop-runtime/src/phase_loop_runtime/supervised_echo.py`, `phase-loop-runtime/src/phase_loop_runtime/run_status_projection.py`, `phase-loop-runtime/tests/test_supervised_worker*.py`, `phase-loop-runtime/tests/test_run_status*.py`, `phase-loop-runtime/tests/_run_status_vectors.py`, `phase-loop-runtime/tests/test_convergence_adapters.py`, `phase-loop-runtime/tests/test_executable_dependency_startup.py`, `phase-loop-runtime/tests/fixtures/supervised_worker_local/**`, `phase-loop-runtime/tests/data/seat_launch_references.json`, `phase-loop-runtime/tests/test_agent_cli_scratch_inventory_1147.py`, `phase-loop-runtime/tests/test_seat_launch_helpers_trusted.py`, `phase-loop-runtime/tests/test_seat_reference_inventory.py`
- **Interfaces provided**: `supervised_echo.write_echo`, `supervised_echo.read_echo`, `supervised_worker_cli launch --envelope --result` with the §4.2 controller document, `v2_status_mapping`, `lifecycle_results`, `external_evidence_intake`
- **Interfaces consumed**: `load_v2_binding`, `capture_launch_v2`, `prepare_launch_v2`, `consume_admission`, `recheck_launch_v2`, `canonicalize_v2`, `AttemptBinding`, `admission_results`, `historical_receipts.verify_historical_receipt`, `run_patch_return` (pre-existing), `reserve_attempt` (pre-existing), `output_retention.mark` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-2.1 | test | — | SL-2 test files, `tests/_run_status_vectors.py`, `tests/fixtures/supervised_worker_local/**`, inventory files | JOURNAL and WORKER receipt tests converted to the historical helper before any SL-2 source edit; the actual CLI, adapter and journal paths with offline subprocesses and injected providers: zero chain starts on refusal, no probes, one chain deadline, helper `failed_to_start`, exact one-shot stdin or DEVNULL, replay across processes and restarts; identity taken from `AttemptBinding`, never envelope top-level fields; a controller document that is missing, names another envelope digest, lies outside `controller_root`, is foreign-owned, not private or symlinked refuses `binding_invalid` with no effect; the landed `launch --envelope --result` argv is unchanged; all six `kind=echo` cases byte-exact through the real writer and reader, and a missing or altered sidecar refuses `echo_unavailable`; the closed `WorkerResult`-to-v2 table, including `journal_complete=False` as `unknown`; the inventory rows for every new launch site or dynamic import; each guard bypassed in a temporary source copy turns a production assertion red | `V2` |
| SL-2.2 | impl | SL-2.1 | SL-2 owned files | — | — |
| SL-2.3 | verify | SL-2.2 | SL-2 owned files | all SL-2 tests | `V2` |

SL-2.2 follows binding §3 C-S1 and §4.1–§4.3. It runs `recheck_launch_v2` inside
the landed `before_spawn` callback, keeps the reservation worker-owned and
permanent, consumes held qualification without probes and never restarts the
monotonic timer. External controller apply outcomes stay finished work outcomes;
the 13 apply cases need independently supplied evidence, which stays blocked if
absent (C-S4).

### SL-3 — Documentation, evidence verifier and readiness reducer

- **Scope**: Reconcile every producer into the CLOSEOUT receipt, the hosted evidence verifier and a truthful readiness report.
- **Owned files**: `docs/supervised-worker-contracts.md`, `docs/supervised-worker.md`, `docs/supervised-run-status.md`, `docs/supervised-worker-readiness.md`, `plans/evidence/supervised-worker/CLOSEOUT.md`, `phase-loop-runtime/tests/test_supervised_v2_readiness.py`, `phase-loop-runtime/scripts/verify_supervised_v2_evidence.py`, `.github/workflows/supervised-v2-evidence.yml`, `CHANGELOG.md`, `plans/manifest.json`
- **Interfaces provided**: `IF-0-CLOSEOUT-1`, `readiness_results`
- **Interfaces consumed**: `intake_results`, `admission_results`, `lifecycle_results`, `external_evidence_intake`, `v2_status_mapping`, `stamp_evidence_receipt.stamp` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| SL-3.1 | test | — | `tests/test_supervised_v2_readiness.py` | every corpus, rule and obligation compared with production outcomes and runner artifacts; missing or skipped-only results, changed resource identities, stale review heads, missing external proof, secret content, a shared-file pin in the CLOSEOUT receipt and an unjustified true authority each refuse; content identity, ancestry, stamp-only delta and post-landing applicability through the verifier | `V3` |
| SL-3.2 | impl | SL-3.1 | `scripts/verify_supervised_v2_evidence.py`, `.github/workflows/supervised-v2-evidence.yml`, `plans/evidence/supervised-worker/CLOSEOUT.md` | — | — |
| SL-3.3 | docs | SL-3.2 | SL-3 docs, `CHANGELOG.md`, `plans/manifest.json` | — | `V3` |
| SL-3.4 | verify | SL-3.3 | SL-3 owned files | all SL-3 tests | `V3`, then the effective suite |

SL-3.2 implements the authenticated evidence protocol of the inputs artifact and
stamps only CLOSEOUT's receipt. SL-3.3 documents offline, on-main, installed,
external and live status separately, keeps every missing item explicit with its
owner and blocked edge, records the WORKER contract §6 trusted-boot note
(binding §4.4, agent-harness#1960 item 6), adds one Unreleased changelog entry
and appends the closeout lifecycle event.

## Execution Policy

- execute: effort=high, reason=public codec capture and journal boundaries need path-entered mutation controls
- SL-3: effort=medium, reason=documentation and evidence reducer over finished producers

## Execution Notes

- **Sequencing**: lanes run in order SL-0 → SL-1 → SL-2 → SL-3. No subagents or
  writer fanout are authorized.
- **Cross-phase order**: CLOSEOUT merges before PLACECLI and LANEEXEC
  (`plans/artifacts/v12-v13-replan-ownership.md`). PLACECLI may build
  concurrently and rebases onto this landing.
- **Single-writer files**: within this phase, every shared file in the ownership
  map has the single owner shown there: SL-0 for `pyproject.toml`, `uv.lock` and
  `test_gate_a_wheel_isolation.py`; SL-2 for the four inventory files; SL-3 for
  `CHANGELOG.md` and `plans/manifest.json`.
- **Known destructive changes**: none. No file is deleted. Receipt-test
  conversions replace live-equality assertions; no recorded receipt byte or
  outcome changes.
- **Expected add/add conflicts**: none.
- **SL-0 re-exports**: none. New modules are imported by path; no `__init__`
  export is added.
- **Receipts**: CLOSEOUT's receipt follows binding §3 C-S2 and the ownership
  map's receipt rule (agent-harness#1955).
- **Shared host**: dev0 runs plan validators only. Test groups run on `ai`
  under the admission lock and PSI gates, serially, with `timeout 900`, no
  xdist and no cache provider. No full suite runs locally.
- **Stale-base guidance** (copy verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.
- **Validator (N)**: package and changelog ownership read as release-shaped.
  This phase dispatches no tag or release; SL-3 records post-verification
  evidence, so no release-dispatch reducer applies.
- **STOP rule**: an unclear interface or ownership gap stops the lane and
  reports the exact plan or artifact sentence to change.

Next phase: CLOSEOUT — blocked: advisor-board panel review of this re-plan.
Next command: none until the panel and president return; then
`claude-execute-phase plans/phase-plan-v12-CLOSEOUT.md` under separate execution authority.

## Deferred Items

Recorded, not built in this phase (coordinator ruling 4, 2026-11-09).

| Item | Owner | Effect on this phase |
| --- | --- | --- |
| SEATS public caps APIs: an expected-digest check inside `capped_popen`, typed evidence of whether a failure came before or after its helper started, and kill/collect of a capped parent by key | SEATS/JAILCORE; new issue scheduled against v13 ACTIVATE, cross-linked to agent-harness#1963 and agent-harness#1895 | None; CLOSEOUT never calls `capped_popen`. |
| Caps contract §1a tmpfs carve-out cleanup | SEATS | None. |
| Garbage collection of orphaned content-addressed echoes (capped and secret-free) | v12 supervised-worker follow-up; new parked issue | SL-2 creates echo files and deletes none (binding §3 C-S1). |
| Folding the reinterpreted sentences into the next protocol versions: the PLACECLI `launch_binding` sentence, the LANEEXEC narrowings and the wheel-shipped `x-*` prose | v13 placement protocol owner; new parked issue | None; CLOSEOUT changes no v13 artifact. |
| Production worker state root taken from trusted operator configuration | agent-harness#1960 | SL-2 keeps the landed default state root; the CLI is not repointed here. |
| A sanctioned `replan` lifecycle path in `plan_manifest.update_lifecycle` (the replan events here are hand-written and append-only) | coordinator follow-up (ruling 3) | The `v12-CLOSEOUT` row carries one hand-written `replan` event. |

## Acceptance Criteria

- [ ] EC-CLOSEOUT-1 — proven by `bash phase-loop-runtime/scripts/verify_supervised_v2.sh all` (V0–V3) on `ai` and by `plans/evidence/supervised-worker/CLOSEOUT.md` carrying runner-stamped CI, Gate A, board, separate-president and external-producer artifacts that `verify_supervised_v2_evidence.py` authenticates; falsified by a path-entered guard bypass in a temporary source copy of `supervised_launch.py`, `patch_return.py` or `run_status.py`, a missing corpus or obligation outcome, or stale or absent external evidence.
- [ ] EC-CLOSEOUT-2 — proven by V3 (`tests/test_supervised_v2_readiness.py`) against the production results and `docs/supervised-worker-readiness.md`; falsified by a receipt mutation that claims unobserved qualification, a stale head or unsupported authority, entered through the production verifier path.

## Verification

Future execution commands; none runs in this planning change. Paths in groups
are relative to `phase-loop-runtime/`; membership is binding §5.

- V0: `bash phase-loop-runtime/scripts/verify_supervised_v2.sh V0`
- V1: `bash phase-loop-runtime/scripts/verify_supervised_v2.sh V1`
- V2: `bash phase-loop-runtime/scripts/verify_supervised_v2.sh V2`
- V3: `bash phase-loop-runtime/scripts/verify_supervised_v2.sh V3`

Validate V0–V3 and `automation.suite_command` with
`verification_evidence.validate_verification_commands` (IF-0-VC-2) at execution
preflight; missing owned future files are pre-implementation findings. Require
actual outcomes, not collection, refuse exit-5 or skipped-only success, report
multiple failures and flag any node over roughly five minutes.

Acceptance also needs the live protected-main required checks, full-path
supervised contract publication (`contract=true`), a Gate A run on the observed
reviewed head, and the T3 cross-vendor board plus separate president on the
same content. The builder never dispatches Gate A: under the 2026-11-06 sprint
policy the coordinator dispatches
`gh workflow run test.yml --ref <reviewed-branch> -f chronology=false` and the
verifier records the tested head, run and artifacts. Proxy evidence requires a
roadmap amendment.
