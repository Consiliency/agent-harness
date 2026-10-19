---
phase_loop_plan_version: 1
phase: RCONTRACT
roadmap: docs/proposals/typed-review-roadmap.md
roadmap_sha256: 45b6faac632fcdf47fc5605389826d256126ab6f4c2a2b44859f2a3088f2e3e8
automation:
  suite_command: ["uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--extra", "visual", "--locked", "python", "-m", "pytest", "phase-loop-runtime/tests", "-q", "-k", "review_contract or phase_loop_baml or export_schema or phase_loop_skill_baml_closeout or phase_loop_terminal_summary_mirrors_baml_closeout or phase_loop_closeout_schema or phase_loop_schema_flow or pkg_layout_freeze or launchspec_golden or v22_principles"]
---

# RCONTRACT: Freeze BAML review contracts and gateway

## Context

Explicitly selected roadmap; v11 remains the global active selection. The user's
2026-10-19 whole-roadmap execution authorization supersedes the proposal's
historical planning-only scope. Preserve the three staged proposal inputs and
their design-review history. The president accepted the corrected design for
planning; Claude's round-three PARTIALLY AGREE and carried votes remain as recorded.
Neither this plan nor that ruling claims runtime ratification.

Work only in `/home/viperjuice/workspace/worktrees/agent-harness-typed-review-spec-20261019`
on `codex/typed-review-spec-20261019`. Sequential execution uses this owned checkout;
no concurrent writers or scheduler/worktree claims are implied. No main merge,
release, SDK transport/auth changes, or other worktree cleanup is authorized.

Intake checked live agent-harness#1443: OPEN, unmerged. This checkout has no
`phase_loop_runtime/panel` package or frozen PANELSPLIT module map. Before RPANEL,
recheck actual owners rather than treating planned extraction as landed.
Consume v11 Phase 16's EC-EXECFIND-0, EC-EXECFIND-2 and EC-EXECFIND-6 by reference;
do not close them or produce IF-0-EXECFIND-1. N8-R3/PRES-S1/S2/S3 remain assigned
to RPANEL. RCONTRACT does not write those panel/governed surfaces.

## External Inputs

- `docs/proposals/typed-review-contract.md`: accepted design input; its observed digest is preserved in the design review record and intake ledger, not a future-history requirement.
- `docs/proposals/typed-review-roadmap.md`: frontmatter digest.
- `docs/proposals/typed-review-roadmap_reviews.md`: preserved full design record.
- Existing locked `baml-bridge==0.20.1`; no upgrade assumed.

## Interface Freeze Gates

- [ ] IF-0-RCONTRACT-1 — `review_reply.baml` declares `EmitReviewReply`, `EmitReviewDecision` and every nested review field/enum; snapshot-aware schema export and worker request/parse APIs use those declarations. The parse result exposes matched IPC operation, request ID, worker fingerprint, runtime version and consumed value. Real-worker recording tests freeze this interface before SL-1 consumes it.
- [ ] IF-0-RCONTRACT-2 — `review_contract.py` freezes coordinator request/transport-registration/content-record and saved-source interfaces, domain-separated canonical digests, strict acceptance, metadata-only rejection mapping, durable idempotence/conflict and lineage reservation. `docs/phase-loop/typed-review-contract.md` documents the exact callable interface and trusted-host policy boundary for downstream adapters.

## Lane Index & Dependencies

SL-0 — BAML types, worker and exporter
  Depends on: (none)
  Blocks: SL-1
  Parallel-safe: no

SL-1 — Acceptance, conformance and docs reduction
  Depends on: SL-0
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — BAML types, worker and exporter

- **Scope**: Extend the isolated local BAML worker and source-derived exporter without changing closeout behavior.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/baml_src/review_reply.baml`, `phase-loop-runtime/src/phase_loop_runtime/baml_src/phase_loop_bridge.baml`, `phase-loop-runtime/src/phase_loop_runtime/_baml_worker.py`, `phase-loop-runtime/src/phase_loop_runtime/baml_modular.py`, `phase-loop-runtime/tests/test_phase_loop_baml_v1_runtime.py`, `phase-loop-runtime/tests/test_phase_loop_baml_schema_export.py`, `phase-loop-runtime/tests/test_phase_loop_baml_schema_source.py`, `phase-loop-runtime/tests/test_phase_loop_baml_v1_callers.py`, `phase-loop-runtime/tests/fixtures/baml_worker_peers.py`, `phase-loop-runtime/tests/data/baml_call_sites.json`, `.github/workflows/test.yml`
- **Interfaces provided**: `IF-0-RCONTRACT-1`
- **Interfaces consumed**: worker framing and fingerprint (pre-existing), finite recovery and shutdown (pre-existing), closeout APIs (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add real-worker review and president parse/request controls, exact original-text and IPC reply recording, class-name/schema-only bypass and echo-input mutation failures; retain closeout, process lifetime and environment coverage.
  - impl: Add native BAML enums and explicit required-null review fields, class-qualified export without Python review enum authority, declared-function `.parse(raw)` and `.build_request()` bridge operations; never execute inference through placeholder clients.
  - impl: Expose saved full rendered-file maps and snapshot-specific worker/schema calls. Preserve the existing canonical fingerprint, isolate parser state per snapshot without global mutable swaps, reject unavailable/unsupported snapshots, and expose metadata only after checking the actual matched reply. Keep existing operation names and closeout APIs compatible. Route each request by its saved fingerprint; never reuse a mismatched generation. Retire and reap the old generation before respawning, preserving the existing single-owner lifetime and bounded recovery guarantees. Snapshot-specific export must not read the global enum cache or current snapshot. A normal snapshot-switch retirement is not a failure, retry or extra request attempt; retain finite existing budgets. Test more consecutive switches than the configured retry limit, all succeeding. Test alternating current and historical maps in one process, with reply fingerprints checked against each request and lifetime/environment/shutdown regressions retained.
  - impl: Change only the two BAML source-count assertions in `.github/workflows/test.yml` to match the actual packaged file count; preserve the required job and its pinned toolchain.
  - verify: Run checksum-verified baml-cli 0.20.1 fmt on owned BAML sources and assert an idempotent second pass; check raw and rendered sources in temporary projects, requiring the actual packaged file count. Record these results and the CI guard checks triggered by the workflow edit. Review declarations must remain OpenAI-dialect-clean through the existing bare-class export path; run `test_phase_loop_v22_principles.py` without changing its contract. Preserve the legacy closeout schema golden; test native review-field/enum mutations in saved maps without changing current-snapshot acceptance.
  - verify: Run the two existing BAML test modules with the new controls, including an actual parse failure. Review the exact API before downstream edits and freeze it in the lane handoff.

### SL-1 — Acceptance, conformance and docs reduction

- **Scope**: Implement coordinator acceptance and durable request/receipt/lineage state, then reduce verified results into the contract and phase ledger.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/review_contract.py`, `phase-loop-runtime/tests/test_review_contract.py`, `phase-loop-runtime/tests/data/typed_review_contract_vectors.json`, `docs/phase-loop/typed-review-contract.md`, `CHANGELOG.md`, `plans/evidence/typed-review/RCONTRACT.json`, `plans/evidence/typed-review/ledger.json`, `plans/manifest.json`
- **Interfaces provided**: `IF-0-RCONTRACT-2`
- **Interfaces consumed**: `IF-0-RCONTRACT-1`, frozen proposal inputs (pre-existing), policy admission and coordinator authority (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Freeze canonical request/receipt vectors, source snapshot replay, strict original-byte/type/equality controls, request/evidence/coverage bindings, semantic verdicts, dissent, lens-free/advisory controls, president ledger membership and contradictions. Exercise byte, nesting, list and code-point limits at their boundaries.
  - impl: Accept one bounded original UTF-8 JSON object, rejecting duplicate keys, suffixes, unknown/missing fields, nonfinite values and coercion. The strict precheck consumes only the IF-0-RCONTRACT-1 schema exported from the request-bound saved map, never a handwritten review field/enum schema. A saved-map declared-field/enum mutation must change strict acceptance for that snapshot alone. Call the real declared-function worker with original text, verify IPC/snapshot metadata and strict tree equality before semantics and record minting. Never accept a class-name-only parse or reviewer-authored authority claims.
  - impl: Implement full frozen request/attempt/lineage/source identity, durable content-addressed BAML source maps, transport registration and metadata-only content records, private original bytes and parsed bodies, atomic idempotent same-delivery intake and different-delivery conflict. Revalidate historical bytes using their saved map. Purpose, usable vote and governed eligibility remain distinct; HOST_ATTESTED never acquires eligibility without existing admission.
  - impl: Reserve at most one correction per original lineage durably before dispatch. Freeze invalid-original → invalid-correction → refused-again, including resume and new attempt IDs. Never retry valid dissent; preserve original failure and replacement identity. This gateway vector is carried to EC-RT3-2 and EC-RPANEL-1 for adapter proof.
  - impl: Apply N9-R3: falsifier identifier/path/node/diff structural validity belongs to the governed gate, not acceptance semantics. NON_BLOCKING-with-falsifier is the only falsifier semantic rejection. Do not execute attachments or fetch evidence references.
  - impl: Last, after both lanes' checks, document API/privacy/host responsibilities and canonical vectors, update CHANGELOG and durable phase ledger with actual EC/IF/review/evidence disposition. Preserve proposal bytes; the new canonical contract supplements their accepted design. No fabricated parse, live-route proof or ratification.
  - verify: Run the complete phase suite through `phase_loop_runtime.verification_evidence.run_verification`, then affected repository checks and closeout audit. Record failures and actual artifact paths; do not convert unit/fake evidence into live qualification.

## Execution Notes

Read/write control artifacts: this plan and its `_reviews.md` sibling,
`.phase-loop/evidence/typed-reviews/RCONTRACT.json`, `.phase-loop/typed-review/**`,
`.dev-skills/handoffs/codex-plan-phase/**`, `.dev-skills/handoffs/codex-execute-phase/**`.
Private task-owned evidence at `.phase-loop/typed-review/private/RCONTRACT/**` is explicitly
allowlisted for reads/writes; never force-stage it or raw model bodies.
Other private/raw/credential inputs remain excluded. Runtime test caches and venv
are toolchain outputs classified by the closeout audit. Resolver-owned skill
reflections use `phase_loop_runtime.skill_paths`. Original staged proposal inputs
may be checkpointed unchanged with task-owned work; do not sweep other staged paths.

The two owned path sets are disjoint and the DAG must pass `parse_phase_plan_ir`.
Serial workers inherit the explicit owned checkout; no parallel fanout is authorized
without scheduler-owned worktrees and machine-verified disjointness. Lockfiles,
generated skills, package metadata and other tests stay untouched because neither
dependency nor skill changes are required. SL-0 may update its caller inventory
after SL-1 introduces the planned acceptance call; that serial integration repair
does not transfer ownership. Amend ownership before any other needed edit.

Use independent review before execution and the applicable implementation review
before closeout/landing. Preserve failures and dissent; three rounds maximum, with
new T3 delegated task per round. Manual fallback reports are private review evidence,
never retroactively BAML-accepted receipts. The selected author is Astra, not Sol;
do not invent Sol-specific ablation completion. Follow actual applicable policy.
Publication follows the supported mode command and runner ownership; scoped feature
commits are authorized, protected merges/releases are not.

## Spec Closeout Plan

The proposal contract remains a preserved design input; the new canonical contract
carries the frozen executable interface. This explicitly locates the roadmap
contract closeout in the canonical successor and is recorded in the phase ledger.

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/phase-loop/typed-review-contract.md`, `phase-loop-runtime/src/phase_loop_runtime/baml_src/review_reply.baml`
- evidence paths: `.phase-loop/evidence/typed-reviews/RCONTRACT.json`, `plans/evidence/typed-review/RCONTRACT.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

Run from the owned repository root with absolute source/test PYTHONPATH. Refresh
locked dependencies using `uv sync --project phase-loop-runtime --group test --extra visual --locked`.
The automation suite is the complete RCONTRACT suite. Run source-scoped repository
checks with `make check`; record their results separately, but closeout preservation
and required CI regressions block lane handoff and phase closeout.
Resolve `suite, findings = resolve_suite_command_doc(repo, roadmap, plan)` and require
a nonempty suite and no findings. Invoke the supported public producer as
`run_verification(repo, run_dir, commands, suite, env_refresh, 1200, phase_alias="RCONTRACT")`,
where `commands, exemptions = verification_commands_from_plan(plan)`,
`env_refresh` contains the locked uv-sync argv above (never a fabricated exit code),
and `run_dir` is a fresh `.phase-loop/typed-review/RCONTRACT/verify-<run_id>` directory.
Require `validate_verification_artifact(run_dir / "verification.json").ok`.
The roadmap evidence file references that exact sealed artifact path and SHA256,
its log path/digest, and actual EC/IF disposition; it cannot restate success without
those bindings. Baseline artifacts remain distinct and cannot close new criteria.

The complete test selection runs once through `automation.suite_command`; the
additional command list below does not repeat it.

- `git diff --check`

## Acceptance Criteria

- [ ] EC-RCONTRACT-1 — proven by `test_phase_loop_baml_v1_runtime.py` and `test_review_contract.py`; falsified by a production parse-review bypass that echoes the input or drops matched IPC metadata while the recording control still passes.
- [ ] EC-RCONTRACT-2 — proven by `test_review_contract.py` and `test_phase_loop_baml_schema_export.py`; falsified by accepting any named strict/semantic/limit negative vector at the production acceptance constructor.
- [ ] EC-RCONTRACT-3 — proven by `test_review_contract.py`; falsified by changed canonical vectors, replay under current rather than saved BAML sources, identity-conflicting delivery accepted, private body leaked into metadata, or a second correction after restart.

Required criteria remain unchecked until their tests and runner evidence pass.
Next dependency-ready phases are RT3 and RPANEL, each requiring its own planned
ownership and review. RENFORCE additionally requires actual route evidence; no
RCONTRACT test closes that operational obligation.
