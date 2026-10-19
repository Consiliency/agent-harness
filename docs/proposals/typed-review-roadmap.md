# BAML typed reviews implementation roadmap

## Context

Proposal only. The governing design is
[typed-review-contract.md](typed-review-contract.md). The user requires BAML to
provide typed reviews for T3 delegates and panels, including reviewers with no
predefined lens. A single detailed plan would cross the BAML worker, transport
adapters and governed consumers, so this roadmap separates their contract
boundaries. Do not register or select it as the active roadmap in this planning
run; `specs/phase-plans-v11.md` remains active. Do not alter agent-harness#1744.

## Architecture North Star

Frozen request and source manifest → admitted transport → complete original
terminal submission → strict raw check → real BAML runtime parse → equality,
binding and semantic checks → coordinator acceptance record → governed consumer.
All paths share the same BAML result types and acceptance gateway. Free-text
reasoning remains inside typed fields; lenses are optional metadata.

## Assumptions

- Existing `baml-bridge==0.20.1` supplies the worker pattern. Contract freeze
  proves its review parsing capabilities locally; no version upgrade is assumed.
- The baseline T3 driving host, including its driving agent, is trusted to relay
  task identities and complete original output. HOST_ATTESTED and
  TRANSPORT_CAPTURED provenance remain distinct; governed use requires existing
  policy admission. Missing capability refuses without an invented app API.
- The gateway does not isolate hostile same-UID host processes. Existing
  enforced isolation and trusted coordinator state remain prerequisites.
- agent-harness#1443 is integration input if landed, not a prerequisite assumed
  complete. Reconcile its actual state when planning the panel phase.

## Non-Goals

Provider/API authentication changes, panel SDK admission, new model rosters,
changes to executor closeout semantics, automatic fixes or merges, a guarantee
that model claims are true, and a rewrite of the T3 application are outside scope.

## Cross-Cutting Principles

BAML is mandatory on acceptance; strict prechecks cannot replace it. Preserve
failed submissions and dissent. Count tasks, typed content, usable votes and
convergence separately. Never promote advisory content to landing evidence.
Pin inputs, never future commit identities/counts/topology. Downstream plans
reference the EC IDs here instead of paraphrasing them, remain within their
lane budgets, and supply effective `automation.suite_command` metadata.

All implementation phases use ordinary required CI and source-scoped tests.
Do not run suites or generators while authoring this roadmap. Structural
roadmap lint and the user-requested advisor review are planning validation.

## Top Interface-Freeze Gates

- IF-0-RCONTRACT-1 — BAML review/review-decision types, source-derived strict
  schema, worker bridge, semantic rules and conformance vectors.
- IF-0-RCONTRACT-2 — Frozen request, acceptance record, host bridge protocol,
  privacy mapping and source/attempt/contract binding rules.
- IF-0-RT3-1 — T3 request/task/original-result adapter with durable intake.
- IF-0-RPANEL-1 — Panel, native-fill and president adapters before publication.
- IF-0-RENFORCE-1 — Mandatory consumer coverage and route qualification evidence.

## Phases

### Phase 1 — Freeze BAML review contracts and gateway (RCONTRACT)

**Objective**

Implement and freeze the reusable BAML contract and acceptance boundary before
any review transport can claim it.

**Exit criteria**

- [ ] EC-RCONTRACT-1 — Valid review and president objects actually traverse the
  real BAML worker. Recording invocation tests bind the exact parse-review op,
  original bytes, echoed IPC ID/fingerprint and consumed reply. An echo-input
  mutation without that operation and class-name/schema-only bypass both fail;
  worker failures cannot mint a content-validation record.
- [ ] EC-RCONTRACT-2 — Strict original-byte checks, BAML/raw equality and semantic
  vectors reject coercion, omitted fields, duplicate keys, ambiguous/truncated
  JSON, stale bindings, inconsistent verdicts and resource-limit exhaustion;
  valid dissent and lens-free advisory/review controls pass.
- [ ] EC-RCONTRACT-3 — Request/receipt canonical vectors prove domain separation,
  identity binding, idempotence/conflict handling and private-content separation;
  saved rendered-file maps survive unrelated BAML/taxonomy edits without using
  another parser, and missing/unsupported snapshots refuse. The bridge protocol
  explicitly names trusted host and provenance-policy responsibilities. The
  invalid-original → invalid-correction → refused-again lineage vector, including
  resume, applies to every adapter, not just T3.

**Scope notes**

Decompose into 2 lanes. Lane A owns BAML declarations, worker operations and
schema export; lane B owns `review_contract.py`, conformance vectors and gateway
validation. Freeze their common interface before merging lane outputs. The
current fixed worker op table is deliberately extended for the new review
protocol; preserve all existing operation names and worker lifetime guarantees.
Implement native BAML enum export, class-qualified review field rules and
required explicit-null review fields without Python-sourced review enums.
Version/nonblank and cross-field rules are semantic checks. Include president
status/decision contradictions, duplicate cross-seat F1 keys, non-gating review
verdicts, exact units and JSON-with-terminal-suffix rejection. Tree equality
cannot substitute for the actual parse-invocation proof.

**Non-goals**

No transport dispatch or change to existing closeout acceptance.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/baml_src/review_reply.baml` (new).
- `phase-loop-runtime/src/phase_loop_runtime/baml_src/phase_loop_bridge.baml`.
- `phase-loop-runtime/src/phase_loop_runtime/_baml_worker.py`.
- `phase-loop-runtime/src/phase_loop_runtime/baml_modular.py`.
- `phase-loop-runtime/src/phase_loop_runtime/review_contract.py` (new).
- `phase-loop-runtime/tests/test_review_contract.py` (new).
- Existing `tests/test_phase_loop_baml_v1_runtime.py` and schema-export tests.

**Depends on**

- (none)

**Produces**

- IF-0-RCONTRACT-1 — Frozen BAML types and validator conformance vectors.
- IF-0-RCONTRACT-2 — Frozen request/receipt and trusted host bridge protocol.

**Spec closeout policy**

`schema: spec_delta_closeout.v1`; decision `canonical_spec_update`; target this
proposal's contract and packaged BAML source; evidence
`.phase-loop/evidence/typed-reviews/RCONTRACT.json`;
`redaction_posture: metadata_only`. Missing/malformed evidence routes
non-human `blocker_class=contract_bug`.

### Phase 2 — Integrate T3 delegated review intake (RT3)

**Objective**

Route T3 reviews through the frozen gateway while preserving app-owned task and
original-run identity.

**Exit criteria**

- [ ] EC-RT3-1 — Host registration binds taskId, childThreadId and childRunId,
  original completed/result_available status and complete terminal-item recovery
  with UTF-16 pagination. Later turns cannot replace/reopen it. Provenance and
  trust assumptions are explicit; unsupported modes, unknown classes and
  reviewer self-attestation cannot upgrade eligibility.
- [ ] EC-RT3-2 — Restart, duplicate delivery, lost dispatch response and correction
  attempts preserve one standing vote per seat and do not trigger duplicate
  work or retry valid dissent. An invalid original followed by an invalid
  correction cannot receive another correction, including after restart.
  Unsupported bridge capability is not usable.

**Scope notes**

Decompose into 2 lanes. Lane A owns the adapter and request/registration/intake
interfaces; lane B owns fake-transport fault tests and the host integration
guide. Use `delegate_task` anew per review/correction round, preserve the task ID,
and use stable `clientRequestId` for retries of the same dispatch. No direct
Python-to-MCP capability is presumed. The trusted driving host is the tool bridge;
its relayed data is HOST_ATTESTED, not independently authenticated capture.
Every correction is a substantive replacement, never certified format-only.

**Non-goals**

No top-level T3 thread launch, application modification or universal restriction
on independent users calling T3 directly.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/review_t3.py` (new).
- `phase-loop-runtime/src/phase_loop_runtime/review_gateway.py` (new).
- `phase-loop-runtime/src/phase_loop_runtime/cli.py` (request/register/intake).
- `phase-loop-runtime/tests/test_review_t3.py` (new).
- `docs/phase-loop/typed-reviews.md` (new).

**Depends on**

- RCONTRACT

**Produces**

- IF-0-RT3-1 — Bound T3 adapter and restart-safe intake interfaces.

**Spec closeout policy**

`schema: spec_delta_closeout.v1`; decision `canonical_spec_update`; target host
bridge documentation; evidence `.phase-loop/evidence/typed-reviews/RT3.json`;
`redaction_posture: metadata_only`; missing/malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 3 — Integrate panels native fills and presidents (RPANEL)

**Objective**

Require typed validation before any panel result can reach a stream, aggregate
or president and preserve review/advisory distinctions.

**Exit criteria**

- [ ] EC-RPANEL-1 — Ordinary seats, both native-fill branches and president
  decisions, including native-president initial deferral and resume, pass the
  BAML gateway before callbacks, verdict files or aggregation;
  one bypass mutation per ingress is detected by its matching negative test.
  Panel/native/president paths each cover the shared one-correction lineage
  budget, including invalid correction and resume without a reset.
- [ ] EC-RPANEL-2 — Lens-free and arbitrary-lens panels use identical schemas;
  advisory analysis and non-gating design-review verdicts cannot satisfy landing
  policy. Typed JSON candidates need no in-band marker; JSON plus a suffix fails.
  President status/decision and exact globally unique ledger membership validate.
- [ ] EC-RPANEL-3 — The actual `governed_board_gate` typed intake preserves
  IF-0-EXECFIND-1 and met EC-EXECFIND-1, EC-EXECFIND-3, EC-EXECFIND-4 and
  EC-EXECFIND-5, plus the currently landed controls associated with carried
  EC-EXECFIND-2 without claiming it complete, using the contract's
  in-gate attachment construction, validation, limits, execution and per-finding
  classification rules. Pure JSON yields a receipt and one authorized runner
  call; null blocking findings preserve optional/required policy, including
  PARTIALLY_AGREE. Vectors cover non-blocking falsifiers, invalid-attachment holds,
  foreign attachments, four/seat and twelve/board limits, missing authorization,
  attachment loss and prose scraping. A direct-runner-only test cannot satisfy
  this criterion; bypassing the gate must fail its matching control.

**Scope notes**

Decompose into 2 lanes. Lane A owns panel/native-fill intake and completion
compatibility; lane B owns president input/output and callback/serialization
tests. Lane A also owns `governed_review.py` typed gate intake/classification for
EC-RPANEL-3; RENFORCE later hardens its consumer coverage. Serialize edits to
shared `panel_invoker.py` through the lane owner.
Reuse strict-verifier tests but move schema authority to BAML. Inspect
agent-harness#1443 before editing overlapping paths. Preserve admitted transport,
subscription, source-grounding and vendor-independence rules.

Frozen legacy `PanelLegResult.detail` contract currently says:
“`PanelLegResult.detail` is built ONLY from our own closed vocabulary. Raw CLI
text never enters it.” Keep that promise. New review rejection codes belong to
the new contract; any additional legacy enum literal requires an explicit
contract amendment and tests, not an incidental string addition.

**Non-goals**

No roster/effort changes, new fallback or panel SDK transport.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/panel_reply.py`.
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`.
- `phase-loop-runtime/src/phase_loop_runtime/president_operation.py`.
- `phase-loop-runtime/src/phase_loop_runtime/president_adapter.py`.
- `phase-loop-runtime/src/phase_loop_runtime/advisor_board/advisory_contract.py`.
- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py` (typed gate).
- `phase-loop-runtime/src/phase_loop_runtime/falsifier.py` (preserve validator).
- `phase-loop-runtime/tests/test_panel_reply.py`.
- `phase-loop-runtime/tests/test_panel_native_fill_183.py`.
- `phase-loop-runtime/tests/test_typed_review_panel.py` (new).

**Depends on**

- RCONTRACT

**Produces**

- IF-0-RPANEL-1 — Typed panel/native/president intake before publication.

**Spec closeout policy**

`schema: spec_delta_closeout.v1`; decision `canonical_spec_update`; target typed
review integration contract; evidence
`.phase-loop/evidence/typed-reviews/RPANEL.json`;
`redaction_posture: metadata_only`; missing/malformed evidence routes non-human
`blocker_class=contract_bug`.

### Phase 4 — Enforce consumer coverage and qualify routes (RENFORCE)

**Objective**

Make accepted BAML results mandatory across governed consumers and prove actual
route coverage before advertising the guarantee.

**Exit criteria**

- [ ] EC-RENFORCE-1 — An exact consumer inventory covers direct/legacy panel,
  governed review, executor/train/FAB/premerge paths, CLI, president, stream,
  resume and T3 intake. Every usable
  governed vote requires a current valid acceptance record; removing each
  inventoried gate causes its named test to fail. Legacy prose is advice only.
- [ ] EC-RENFORCE-2 — Private operational qualification records real BAML parses
  for T3, panel, native fill and president routes with failed-content controls,
  matching source/contract/validator bindings and metadata-only public reports.
  Missing route evidence remains unmet; fake transports are not live proof.
  T3 records actual provenance; HOST_ATTESTED stays non-gating until existing
  policy admits it. Live typing proof cannot itself confer governed eligibility.
- [ ] EC-RENFORCE-3 — Documentation, canonical harness skills and serializers
  consistently describe mandatory acceptance; existing executor BAML closeouts,
  advisory identity, quorum, privacy and independence controls retain coverage.

**Scope notes**

Decompose into 2 lanes. Lane A owns the consumer inventory and enforcement;
lane B owns route qualification, canonical skill/docs updates and regressions.
Coordinate skill-source regeneration in the implementation run. No source
generation, live qualification or provider execution is performed by this
planning artifact. Publish exact test commands in each downstream detailed plan.

**Non-goals**

No release dispatch, merge authority or promotion of the active roadmap here.

**Key files**

- `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`.
- `phase-loop-runtime/src/phase_loop_runtime/cli.py`.
- `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`.
- `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`.
- `phase-loop-runtime/src/phase_loop_runtime/runner.py`.
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py`.
- `phase-loop-runtime/src/phase_loop_runtime/train_review_packet.py`.
- `phase-loop-runtime/src/phase_loop_runtime/governed_premerge.py`.
- `phase-loop-runtime/src/phase_loop_runtime/fab_gate.py`.
- `phase-loop-runtime/src/phase_loop_runtime/fab_producer.py`.
- `phase-loop-runtime/src/phase_loop_runtime/fab_provenance.py`.
- `phase-loop-runtime/src/phase_loop_runtime/review_summary.py`.
- `phase-loop-runtime/tests/data/typed_review_consumers.json` (new).
- `phase-loop-runtime/tests/test_typed_review_enforcement.py` (new).
- Canonical `skills-src/*/*-advisor-board/SKILL.md` and generated bundles.
- `phase-loop-runtime/README.md`, `docs/phase-loop/typed-reviews.md`.

**Depends on**

- RT3
- RPANEL

**Produces**

- IF-0-RENFORCE-1 — Consumer coverage and actual admitted-route qualification.

**Spec closeout policy**

`schema: spec_delta_closeout.v1`; decision `canonical_spec_update`; target
consumer inventory and user/skill contracts; evidence
`.phase-loop/evidence/typed-reviews/RENFORCE.json` and private
`.dev-skills/typed-reviews/qualification.json`;
`redaction_posture: metadata_only`; missing/malformed evidence routes non-human
`blocker_class=contract_bug`. Proxy qualification requires a runner-stamped
plan/roadmap amendment before any downstream gate relies on it.

## Phase Dependency DAG

RCONTRACT → RT3 → RENFORCE; RCONTRACT → RPANEL → RENFORCE.

## Execution Notes

RCONTRACT is the first phase to plan. After its two interface gates freeze, RT3
and RPANEL can be planned/executed concurrently in disjoint owned subtrees.
RENFORCE waits for both; an optional output flag does not satisfy its gates.
Reconcile overlaps with v11 REVIEWTRUTH/PRESROUTE/EXECFIND and
agent-harness#1443 at planning intake without claiming their existing EC IDs
complete. EXECFIND Phase 16 carries EC-EXECFIND-0, EC-EXECFIND-2 and
EC-EXECFIND-6 under the governing 2026-09-25 amendment; reconcile its ownership
and current receipt semantics for `governed_review.py` and `falsifier.py` before
typed gate work. Existing-validator/runner preservation here does not freeze an
older snapshot against that carried work or supersede its amended semantics.
Reconcile
IF-0-PANELSPLIT-1: if its module map has landed, transfer the listed monolithic
panel ownership to actual `phase_loop_runtime/panel/*` owners and facade call
sites. Inventory direct and indirect consumers, including IF-0-EXECFIND-1
attachment handling; no seed list is assumed exhaustive. Promotion into
the governing roadmap is a separate ownership/coherence action, not performed
by writing this proposal. No execution is authorized by this planning run.

The advisor review loop has a three-round cap. Collect all seats before one
combined correction; re-review dissenting seats on the delta, carry only their
usable AGREE judgments, and record unavailable/error seats without counting
them as agreement. Advisory agreement is design feedback, not ratification;
ratified Sol-authored plans require the applicable cross-vendor ablation
evidence. Never change reviewers merely to replace a dissent.

## Verification

Planning validation: `python -m phase_loop_runtime.roadmap_lint docs/proposals/typed-review-roadmap.md`.

Downstream plans run their actual named tests via the supported verification
runner, with locked test dependencies and `automation.suite_command`. Expected
commands, after the named tests exist:

- RCONTRACT: `python -m pytest -q tests/test_review_contract.py tests/test_phase_loop_baml_v1_runtime.py tests/test_phase_loop_baml_schema_export.py`.
- RT3: `python -m pytest -q tests/test_review_t3.py`.
- RPANEL: `python -m pytest -q tests/test_typed_review_panel.py tests/test_panel_reply.py tests/test_panel_native_fill_183.py`.
- RENFORCE: `python -m pytest -q tests/test_typed_review_enforcement.py tests/test_governed_review.py tests/test_advisor_board_advisory_cli_802.py`.

Test commands run from `phase-loop-runtime` with its supported interpreter and
absolute source/test `PYTHONPATH`. Add the applicable affected existing suites
and real route qualification commands during phase planning. No future suite
pass, exact commit identity or prescribed commit count is assumed here.
