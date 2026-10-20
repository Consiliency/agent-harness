---
phase_loop_plan_version: 1
phase: RT3
roadmap: docs/proposals/typed-review-roadmap.md
roadmap_sha256: 45b6faac632fcdf47fc5605389826d256126ab6f4c2a2b44859f2a3088f2e3e8
automation:
  suite_command: ["uv", "run", "--quiet", "--project", "phase-loop-runtime", "--group", "test", "--extra", "visual", "--locked", "python", "-m", "pytest", "-q", "phase-loop-runtime/tests/test_review_t3.py", "phase-loop-runtime/tests/test_review_t3_faults.py", "phase-loop-runtime/tests/test_review_t3_cli.py", "phase-loop-runtime/tests/test_review_contract.py", "phase-loop-runtime/tests/test_phase_loop_baml_v1_callers.py", "phase-loop-runtime/tests/test_advisor_board_cli_legacy.py", "phase-loop-runtime/tests/test_advisor_board_advisory_cli_802.py", "phase-loop-runtime/tests/test_presroute_cli.py", "phase-loop-runtime/tests/test_advisor_board_static_import_862.py"]
---

# RT3: Bind delegated review intake to original T3 results

## Context

Explicit roadmap selection; v11 remains globally selected. The whole-roadmap
authorization permits planning, implementation, verification and scoped feature
publication, without main merges, releases or production activation. Preserve
the three proposal inputs and their actual non-unanimous design review history.

Use only `/home/viperjuice/workspace/worktrees/agent-harness-typed-review-spec-20261019`
on `codex/typed-review-spec-20261019`; never parent SDK/VM worktrees or
agent-harness#1744. Serial ownership; no concurrent source writers. Existing
draft agent-harness#1770 remains the publication target. RCONTRACT local EC/IF
evidence and post-publication CI readiness are accepted for serial consumption.
The parent recorded actual corrected-head pytest and suite-gate success in the
phase ledger after preserving the earlier failed run. Both upstream gates are
confirmed; independent plan review is COMPLETE / AGREE in round 2. No production
activation or downstream live-route qualification is implied.

Frozen request → durable dispatch intent → trusted host's actual T3 tool calls
→ original terminal-item recovery → RCONTRACT acceptance → current usable result.
No Python-to-MCP client, T3 application changes, output-schema tool argument,
top-level thread launch, new credential system or generic governed override.
Fake-host integration proves this phase's contract, never RENFORCE live routes.

## External Inputs

- `docs/proposals/typed-review-roadmap.md`: exact EC-RT3-1/2 authority and pinned frontmatter digest.
- `docs/proposals/typed-review-contract.md` and `_reviews.md` sibling of the roadmap: preserved accepted design and actual review history.
- `plans/evidence/typed-review/RCONTRACT.json`, `docs/phase-loop/typed-review-contract.md`: consumed IF-0-RCONTRACT-1/2 and final source hashes; verify current hashes before execution.
- `.phase-loop/typed-review/RT3/recon-20261019-02.md`, `t3-tool-metadata-20261019-02.json`, `t3-capabilities-20261019-02.json`: targeted source map and observed live tool profile; recheck relevant tool capabilities before dispatch, never treat a snapshot as admission.

## Interface Freeze Gates

- [ ] IF-0-RT3-1 — `review_t3.py` and `review_gateway.py` expose versioned host-prepared dispatch, immutable task/thread/original-run registration, bounded complete-item recovery, durable resume/correction and metadata-only results. `cli.py` exposes the corresponding local commands; `docs/phase-loop/typed-reviews.md` specifies actual grammar, host trust policy, refusal and recovery. Only `ReviewCoordinator` accepts content or creates receipts.

## Lane Index & Dependencies

SL-0 — Host adapter, durable service and CLI
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Fault conformance and documentation reduction
  Depends on: SL-0, SL-2
  Blocks: (none)
  Parallel-safe: no

SL-2 — Repository portability and bounded finalizer prerequisite
  Depends on: SL-0
  Blocks: SL-1
  Parallel-safe: no

## Lanes

### SL-0 — Host adapter, durable service and CLI

- **Scope**: Implement the host-neutral adapter and durable orchestration around the frozen coordinator, then its local CLI.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/review_t3.py`, `phase-loop-runtime/src/phase_loop_runtime/review_gateway.py`, `phase-loop-runtime/src/phase_loop_runtime/cli.py`, `phase-loop-runtime/tests/test_review_t3.py`
- **Interfaces provided**: `IF-0-RT3-1` implementation handoff for SL-1
- **Interfaces consumed**: `IF-0-RCONTRACT-1`, `IF-0-RCONTRACT-2`, live T3 tool metadata (pre-existing), same-UID driving-host trust (pre-existing), CoordinatorPolicy interface (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add real-local-BAML positive controls at the adapter acceptance construction site and negative controls for skipped original-run binding, incomplete recovery and gateway invocation. Test initial request, known task resume and invalid-original/invalid-correction/refused-again before interface handoff.
  - impl: In `review_t3.py`, define a versioned HOST_ATTESTED observation profile using only exposed tool fields. Persist the requested provider/model/options, tool/capability profile, parent host scope, request/attempt/lineage bindings, exact prompt and stable `clientRequestId` before emitting a dispatch action. Emit actual `delegate_task` arguments with the saved BAML prompt as `task`; never its placeholder HTTP URL/headers. Unsupported required capabilities, modes, classes or target substitutions refuse without dispatch.
  - impl: In `review_gateway.py`, keep one private durable orchestration journal beside the coordinator. Use transactional crash-safe intent states and immutable registration. Return host actions; Python never launches a provider or T3 tool. A retry re-emits the same intent only with established same-key reconciliation/deduplication capability; the mere presence of `clientRequestId` is insufficient. Default unknown launch outcome stays unresolved, retaining the key and payload; no new task, key, lineage or correction budget. Known task recovery uses its saved taskId. Reject changed-payload same-key reuse and cross-parent recovery without established authority.
  - impl: Bind actual taskId, childThreadId and non-null original childRunId, plus requested/actual provider/model, before intake. Accept original `status=completed` and `workState=result_available` only. Original failure or nested unfinished original work supplies no candidate. Later `latestTerminal*`, pending later turns and thread-level status never replace/reopen the original result. Freeze the registration once; store terminal-item identity separately to avoid mutating it.
  - impl: Recover the complete original assistant result through the trusted host's `t3_thread_read` observations, not an assumed complete summary. The supported profile requires an explicit trusted-host original-terminal-item attestation plus original-run completion, sourceThreadId/runId/itemId/position binding, local provider `assistant_message` identity and stable observations. A generic completed assistant message is insufficient: commentary has the same exposed type. Document this host assertion as HOST_ATTESTED, not a nonexistent T3 terminal flag. Check uniqueness and full original-run timeline coverage; reject ambiguity, inherited/synthetic content, moving items and later-run substitutions. If a complete original summary is supplied, equality may corroborate but cannot replace recovered original bytes.
  - impl: Traverse returned timeline cursors until complete; then recover only the selected item using returned nextTextOffset UTF-16 units. Preserve exact whitespace and escaping. Validate forward progress, identity/version stability, contiguous offsets, actual UTF-16 lengths, astral/split-surrogate boundaries, final null offset and truncation flags; never join distinct items. Independently enforce UTF-8 limits. Bound pages, observations, retained metadata and aggregate recovery bytes. A finite adapter recovery ceiling may exceed the content bound to permit authentic oversize rejection; beyond it return result_unavailable without truncation, fabricated padding or digest-only evidence of unseen bytes. Publish the ceiling as a host capability, not a renewed reviewer attempt.
  - impl: Form one deterministic bounded host envelope containing the complete original body once and original identity/completion evidence. Preserve original raw observations privately within documented bounds. Do not embed repeated full pages or volatile later-turn metadata into the intake envelope. Fit `6 * MAX_BYTES + 65536` framing for every body admitted by the profile. Freeze the first complete delivery so later status changes do not break idempotence. Pass exact bytes to `ReviewCoordinator.ingest`; replay uses saved sources and current `revalidate`, never cached usable records alone.
  - impl: Use the concrete policy seam below: injected CoordinatorPolicy for in-process hosts and a shipped restrictive policy for CLI. This CLI relies on same-UID driving-host trust, not caller authentication or new admission. Refuse incompatible policy results, unbound state and authority overrides; no policy JSON, token or environment variable grants authority.
  - impl: Recover an existing correction reservation first, otherwise reserve exactly once through the coordinator before dispatch. New substantive review/correction uses a new delegate_task and stable distinct key; never t3_thread_send. Preserve brief, original content or its honest digest-only absence, failures, findings, prior responses and unresolved objections. Valid dissent/incomplete content, BAML outage, lock timeout or bridge failure authorize no provider retry. Use coordinator standing/ledger APIs, not private SQL edits or a second receipt authority.
  - impl: Add a `typed-review` local CLI group whose concrete request/prepare/register/intake/resume/correction grammar is frozen in the lane handoff. Private file inputs and host actions must avoid raw prompt/body/errors in metadata stdout; dispatch payload files are explicit private artifacts. Lazy imports preserve existing CLI and advisory/landing behavior. Commands never dispatch by themselves.
  - verify: Run the new adapter controls plus existing caller/advisory/president CLI regressions. Inspect actual handoff API, complete ownership and supported command help before SL-1 consumption. No direct BAML calls should be added outside the coordinator, so caller inventory remains unchanged.

### SL-1 — Fault conformance and documentation reduction

- **Scope**: Exercise the completed production adapter under transport/restart faults and document its exact host contract, then reduce phase evidence.
- **Owned files**: `phase-loop-runtime/tests/test_review_t3_faults.py`, `phase-loop-runtime/tests/test_review_t3_cli.py`, `docs/phase-loop/typed-reviews.md`, `phase-loop-runtime/README.md`, `CHANGELOG.md`, `plans/evidence/typed-review/RT3.json`
- **Interfaces provided**: `IF-0-RT3-1` verified conformance and final documentation
- **Interfaces consumed**: `IF-0-RT3-1` SL-0 handoff, `IF-0-RCONTRACT-1`, `IF-0-RCONTRACT-2`, frozen lineage replay fixture (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Add standalone CLI tests, not exclusively fleet-overlay modules. Cover shipped CLI policy and injected service policy, unbound/malformed charter refusal, no caller authority upgrade, metadata privacy, exact dispatch payload, and reopen across processes without provider effects.
  - test: Exercise wrong/missing task/thread/run/item/provider, unsupported profiles, misleading summaries, original failed/later completed and original completed/later failed/running/question; pagination through later turns, ambiguity, UTF-16 astral/split/gap/overlap, mutable observations, cursor loops, bounded oversize recovery and authentic digest-only gateway rejection.
  - test: Cover every durable dispatch/registration/intake crash window, concurrent same/conflicting delivery, lost response with unestablished and established recovery capability, same-key changed payload, current revalidation failure and no redispatch on valid dissent. Execute all frozen `typed_review_lineage_replay.v1` scenarios through production adapter APIs, including oversized correction and restart. Add one matching bypass mutation control per original-identity, complete-recovery, BAML-gateway and correction-reservation gate.
  - impl: Add only required test fixtures/helpers inside owned test modules. Route any production repair back to the serial SL-0 owner and reverify affected controls; do not silently acquire shared sources.
  - impl: Document actual CLI grammar and supported profile, same-UID host deployment/private-state prerequisites, provenance/eligibility separation, limits and failure/recovery matrix. Explain unavailable governed admission, unresolved launch outcomes and unknown terminal completeness honestly. Mark fake-host tests versus actual route evidence. Preserve N9-R3 governed attachment ownership in RPANEL and carried EC-EXECFIND-2.
  - verify: Last, run the complete phase suite via supported sealed producer, required repository/docs checks and closeout audit. Reduce exact EC/IF dispositions, source/log hashes and manual review status into metadata-only phase evidence; no operational qualification claim.

### SL-2 — Repository portability and bounded finalizer prerequisite

- **Scope**: Repair confirmed test portability assumptions and the separately designated finalizer prerequisite; preserve existing assertions and unresolved host prerequisites.
- **Owned files**: `phase-loop-runtime/tests/test_agy_canary_evidence.py`, `phase-loop-runtime/tests/test_seat_host_git.py`, `phase-loop-runtime/tests/test_gemini_heartbeat_bootstrap.py`, `phase-loop-runtime/src/phase_loop_runtime/agy_canary_evidence.py`
- **Interfaces provided**: none; repository verification repairs only
- **Interfaces consumed**: `.phase-loop/typed-review/RT3/check-failure-diagnosis/report.md` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Preserve historical failure records and logs unmodified. The hermetic default intentionally exercises workspace policy; retain at least one end-to-end default-path home-policy control. Capture the real workspace constant and authority function at module import; assert the committed default and its bound signature, explicit-root forwarding and negative authority checks. Keep real kernel lease and signal assertions.
  - impl: Confine synthetic account-home and workspace authority to test-owned temporary roots. Forward omitted workspace arguments to the fixture root through the real validator, preserving explicit arguments and adversarial tests. Remove real workspace ownership/chown dependence and the hard-coded evidence-root parent. Canonicalize expected true/sleep executables while retaining hostile-search, descendant, namespace and identity assertions.
  - verify: Run the entire test_agy_canary_evidence.py module and frozen-search node on Python3.12; compare counts with the 278-setup-error baseline and report every body failure. Repairs outside the exact finalizer symbols and test additions require a new ownership amendment. Label the sleep-path repair unexecuted pending prerequisite; run its nested-helper control only when qualified. Obtain independent review of the narrow repair. Rerun the original failing make check only after justified repairs and qualified execution prerequisites; never substitute targeted passes, skip nodes or waive failures.

  - test: For the bounded finalizer prerequisite, preserve all existing test bodies and fixtures; add only the names/boundaries and controls frozen in `.phase-loop/typed-review/RT3/finalizer-amendment/controls-accepted.md`. Exercise inherited state, child-local 0077/0022 crossed with 0640/0600, unchanged default behavior, and fchmod failure for EACH staged target before exchange. Retain original bytes, mode, identity, rollback, collision and race checks.
  - impl: Only `_exclusive_write_at` gains keyword-only `exact_mode=False`; only `_finalize_targets_transactionally` opts in using captured original mode. When opted in, fchmod the already-open exclusive descriptor after writes and before existing fsync. Preserve flags, default callers, error propagation and cleanup; no global umask or ownership change.
  - verify: Follow the frozen finite sequence and input binding in `controls-accepted.md`; no broad make check, namespace/provider/rearm tests or host changes. Root-designated ownership is conditional on exact Jev hunk reconciliation and independent scope review. The original three plan-review rounds remain intact; cap-exception disposition must be recorded before additional scope review. Require independent production/security implementation review and closeout.

SL-1 conformance and documentation already exist; its pending final reduction now waits for SL-2. The new dependency does not require reimplementing completed SL-1 work. The parent reduces final evidence after SL-2. This amendment does not reopen the accepted adapter design or change EC/IF IDs. Root designated the finalizer prerequisite only; module-wide ownership is not transferred. Nested namespace AppArmor denials and the observed exec-transition PDEATHSIG reset remain unresolved; host policy and runtime helper changes require separate owner reconciliation and reviewed scope before edits. No host policy change, helper ownership, test skip or verification waiver is granted here. The phase remains incomplete until required checks and corrected-head CI pass. Diagnosis and original sealed suite remain historical evidence.

## Bound host profile and recovery decisions

These decisions refine IF-0-RT3-1 before implementation; they are not new T3 API fields.

- **Policy seam**: Python hosts inject a CoordinatorPolicy object. A service wrapper keeps the injected identity unchanged and rejects GOVERNED eligibility or nonempty governed_provenance in authorize before create_request can persist anything; future admission requires separate reviewed integration. CLI uses only shipped T3NonGatingPolicy, with identity derived from its version and fixed rules: NON_GATING, HOST_ATTESTED only, empty governed_provenance, unusable-seat blocking, no deferred waiver. Its admit_transport checks the frozen host scope and exact taskId/childThreadId/childRunId identity key set; this is structural matching, not authentication. No dynamic policy loader or authority override.
- **Charter carrier**: preparation accepts one t3_host_charter.v1 object with review_brief, immutable host_scope (parent thread identity and dispatched checkout binding), and boolean allow_correction (default false). Canonical charter bytes are the coordinator brief; persist them privately by digest before request construction, and verify digest/shape when policy resolves context.brief_digest. The policy resolves this same digest-bound charter to compare registration host_identity with its frozen parent-thread host_scope, never a current argument or the registration itself. Policy identity is constant across charters/processes; charter-specific correction permission is bound by frozen brief and request admission. Later operations cannot override it. Orphan pre-request charter data authorizes no dispatch. Cross-round findings/responses/objections enter initial brief and ledger only. For original and correction, emitted task is UTF-8-byte-identical to build_request(binding).prompt; never append later text.
- **Observed type and files**: live-item-profile-observation.json records an existing child read establishing assistant_message for commentary and terminal results; this is a versioned observed literal, not a schema enum. Each private observation file is one versioned wrapper containing exact tool name, request arguments and verbatim tool-result JSON object, preserving surrogate escapes. Host terminal attestation is a separate bound profile record, not an invented result field. Retain original objects; do not coerce a summary into them.
- **Timeline coverage**: use view=messages, start afterPosition=null, require strictly increasing positions and no duplicate itemId; filtered position gaps are valid. Follow nextPosition only while hasMore=true and require forward progress. End on hasMore=false; the final cursor must be null or exactly the maximum position observed across the whole traversal. Refuse any other cursor or an empty final page with result_unavailable; test both. The non-null form rests on one observed sample (44), not a universal schema guarantee. Do not demand null at timeline completion. The attested original item must be the maximum-position local provider assistant item in the original run after full traversal; later original-run assistant items make an earlier attestation ambiguous. Terminal reads acknowledge delivery; acknowledgement never changes intake identity.
- **UTF-16 fidelity**: preserve lone surrogate units as JSON escapes until reassembly, then require valid UTF-8 conversion. U+FFFD immediately on either side of a chunk boundary, unmatched high/low surrogates or uncertain serialization returns result_unavailable. Never substitute characters and claim exact bytes. Test paired U+FFFD boundaries and genuine astral splits; final item-text offset must be null, separately from timeline cursor behavior.
- **Launch capability**: production profile fixes durable same-key redispatch capability to false; caller JSON/CLI cannot enable it. A fake-only injected profile may test true, never count as live capability. A late host-attested original task registration may reconcile an unresolved intent only with exact persisted intent/payload/target association and observed tool identities; it never re-arms dispatch. Uncertain association stays unresolved. Requested model with null/different actual model refuses; recentRuns only corroborates.
- **Store order**: coordinator create_request/reserve_correction commit precedes journal intent creation. Intent is uniquely keyed by request binding; a recovered binding without an intent creates it because no action can be emitted before intent persistence. A persisted emitted/offered intent without registration is unresolved. Always call correction_request before reserve_correction. Test crashes after coordinator commit/before intent and after intent/before registration; neither creates another request or correction.
- **State placement**: production journal/coordinator state must resolve outside every dispatched checkout, including shared isolation; reject symlink-resolved inside-worktree state. Test temporary state is separate from fixture checkout. Private evidence allowance is not live reviewer-database placement authority. Outside-checkout placement alone does not isolate hostile same-UID processes; document host trust and reviewer-exclusion prerequisites, never claim bare T3 worktrees supply exclusion.
- **Control writers**: ledger and manifest are parent controls before/between lanes. During SL-1 delegation the parent retains these two paths and performs reduction after child completion; child briefs exclude them. No simultaneous parent/child writes. Production repairs return to the serial SL-0 owner.

## Execution Notes

Parent-serialized control reads/writes: this plan and `plans/reviews/typed-review-RT3_reviews.md`,
`plans/evidence/typed-review/ledger.json`, `plans/manifest.json`,
`phase-loop-runtime/tests/data/seat_launch_references.json`,
`.phase-loop/typed-review/RT3/**`, `.phase-loop/evidence/typed-reviews/RT3.json`,
`.dev-skills/handoffs/codex-plan-phase/**`, `.dev-skills/handoffs/codex-execute-phase/**`.
Explicit private read/write allowance: `.phase-loop/typed-review/private/RT3/**`.
RCONTRACT frozen API/evidence at `.phase-loop/typed-review/RCONTRACT/**` are read-only
inputs; raw unrelated/private/auth inputs are excluded. Never force-stage private
observations, bodies or reports. Reflection paths use skill_paths resolvers.

The parent alone updates the launch-reference inventory after each source lane,
classifying actual new host I/O without changing scanner/assertions. This is a
serialized reduction control, not permission for child inventory writes; the
frozen BAML caller inventory remains read-only. Retain both global inventory and
canonical manifest checks in final verification to catch cross-repository guards.

All lanes are serial in the owned checkout; validate lane IR disjointness/DAG.
SL-0 exclusively owns cli.py. Existing tests except the three explicit SL-2 paths, `review_contract.py`, `baml_modular.py`, `_baml_worker.py`,
`baml_src/**`, `tests/data/baml_call_sites.json`, lockfiles and generated skills, SDK transport/roster/auth and panel/governed/falsifier consumers
remain untouched: new tests use the existing coordinator boundary. Amend ownership
before any necessary additional edit. Do not transfer shared files by implication.

Independent plan and implementation reviews precede execution and closeout
respectively; three-round cap per loop, fresh T3 task with full prior findings and
responses each round. Author Astra/high; Claude Opus 5.5/medium independent reviewer
through live catalog. No silent provider switch, invented ablation, or retroactive
BAML acceptance of manual reviews. Flagged content only Daybreak. Respect current
publication mode, existing draft PR and no merge authority.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `docs/phase-loop/typed-reviews.md`, `phase-loop-runtime/README.md`
- evidence paths: `.phase-loop/evidence/typed-reviews/RT3.json`, `plans/evidence/typed-review/RT3.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

## Verification

Use absolute source/test PYTHONPATH from the owned root. Real refresh:
`uv sync --project phase-loop-runtime --group test --extra visual --locked`.
Resolve the plan suite with `resolve_suite_command_doc(repo, roadmap, plan)` and
require no findings; obtain commands/exemptions with `verification_commands_from_plan`.
Invoke `run_verification(repo, fresh_run_dir, commands, suite, env_refresh, 1200,
operational_exemptions=exemptions, phase_alias="RT3")`; require sealed
`validate_verification_artifact(...).ok`. Bind its exact artifact/log hashes to
phase evidence. Run the suite once; fake host transports never count as live routes.

Run `make check`, entry_doc_check and docs-audit exactly as CONTRIBUTING specifies;
record complete results, skips and warnings. Docs audit compares committed HEAD:
checkpoint tested owned changes before its final comparison. Required CI must pass
before final readiness; Gate A is required before any later authorized merge when
applicable, not a release or merge authorization here. Audit ignored outputs with
`python -m phase_loop_runtime.closeout_classifier --repo . --record-outputs --phase RT3`.
Preserve actual failures and resolve task-created toolchain outputs without
deleting other worktrees. No repeated full suites without source change or risk.

- `git diff --check`

## Acceptance Criteria

- [ ] EC-RT3-1 — proven by `test_review_t3.py`, `test_review_t3_faults.py` and `test_review_t3_cli.py`; falsified by original-run, complete-item, gateway or eligibility-upgrade bypass, or unsupported mode/class acceptance, passing its matching production-entry negative control.
- [ ] EC-RT3-2 — proven by `test_review_t3_faults.py` and `test_review_t3_cli.py`; falsified by duplicate dispatch after unknown outcome, changed standing identity, retry of valid dissent, second correction after restart, or unsupported-capability dispatch passing its matching control.

RPANEL remains independently dependent on RCONTRACT. RENFORCE waits for RT3 and
RPANEL plus actual route evidence; no tests in this phase close EC-RENFORCE-2.
