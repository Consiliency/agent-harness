# BAML typed review contract

Status: proposal for implementation planning. This document does not change the
active roadmap, existing review policy or runtime behavior. Its implementation
roadmap is [typed-review-roadmap.md](typed-review-roadmap.md).

## Purpose and guarantee

Every review counted by the harness must have a BAML-defined, BAML-parsed result
bound to the material and instructions that were reviewed. The same acceptance
rule applies to panel seats, presidents, native fills and T3 delegated reviewers.
A finished task, a final verdict word or a successful process exit cannot by
itself establish a usable review. A typed design-review verdict can support
non-gating discussion without acquiring landing authority.

The guarantee concerns what the harness accepts. It cannot force a model to
produce a response, make a finding true or make an independent application obey
the harness. Direct T3 delegates and other external reviews that bypass this
gateway remain unverified and cannot supply a harness review vote. Strong
isolation from a hostile reviewer sharing the coordinator's operating-system
identity requires an existing enforced isolation boundary; a private directory
alone is not such a boundary. The baseline T3 integration explicitly trusts the
driving host, including its driving agent, to relay authentic tool results.
BAML proves accepted content's type under that assumption; it does not attest
that an agent-relayed string came from T3 independently of that trusted host.

## Existing implementation and boundaries

The inspected runtime uses `baml-bridge==0.20.1`. Executor closeouts already use
`EmitPhaseCloseout` through `baml_modular.py`, `_baml_worker.py` and
`baml_src/phase_loop_bridge.baml`. Class-name calls to `parse_baml_response` can
take a schema-only Python branch: using that branch alone does not satisfy this
proposal's required BAML runtime parse.

`panel_reply.py` supplies a strict JSON/Pydantic verifier, but the inspected panel
path still uses `terminal_verdict` and does not invoke that verifier. The work in
agent-harness#1443 proposes optional integration. Reuse compatible behavior and
tests; reconcile that change at implementation intake rather than assuming its
branch has landed. Existing BAML permissiveness tests show why successful BAML
parsing alone must not silently repair omitted findings or coerce field types.

T3's exposed `delegate_task` accepts a task prompt without a response-schema
parameter. Its `task_status` reports task/run identities and final summary text.
Use these actual capabilities; do not invent a T3 output-schema flag or require
an app change for the baseline gateway. Optional future native schema support
does not replace local BAML acceptance.

agent-harness#1744 concerns the optional solo Claude SDK transport. This proposal
does not reopen that candidate, enable panel SDK execution or change executor
closeout semantics. The selected active roadmap remains
`specs/phase-plans-v11.md` until its owner incorporates this proposal.

## BAML as the contract source

Add `baml_src/review_reply.baml` as the sole definition of review field names,
types and enum literals. Define `EmitReviewReply`, returning `ReviewReplyV1`,
and `EmitReviewDecision`, returning `ReviewDecisionV1` for presidents. Render
instructions and export schemas from those declarations. Do not maintain an
independent handwritten Pydantic schema that can redefine acceptance. Use native
BAML enum declarations for review enum types. Extend the exporter for those
enums with class-qualified field rules and required explicit-null fields for
review objects; do not reuse global comment/Python enum overrides for these
types. Preserve existing closeout export behavior. Version constants, nonblank
strings and cross-field conditions are explicit semantic checks in step 4.

Extend the existing worker bridge with review-request and parse-review
operations, preserving worker isolation, fingerprint binding, environment
scrubbing, finite recovery and shutdown behavior. Building a prompt and parsing
a response are local operations: neither may send an inference request through
BAML's placeholder client or require a provider API key. Provider execution
continues through the admitted transport and subscription policy.

The acceptance sequence is mandatory:

1. Decode bounded UTF-8 bytes as exactly one JSON object, with no surrounding
   prose, fence, duplicate object keys, trailing object, non-finite number or
   incomplete frame. Enforce the BAML-derived schema against this original
   object with no coercion, defaults, unknown fields or omitted nullable fields.
2. Pass the exact JSON submission's original UTF-8-decoded text to the BAML
   runtime's declared review function using the existing worker. Do not
   reserialize the decoded tree before parsing. Bind the matched parse-review
   IPC request/reply ID, operation and worker fingerprint to this invocation
   and to the source snapshot used to generate the request.
3. Compare the BAML result with the original decoded tree by field presence,
   type and value. Any dropped field, inserted default, coercion or changed
   value rejects the review. Object key order and insignificant JSON whitespace
   are immaterial; boolean/integer equivalence is not permitted.
4. Apply the semantic and request-binding checks below and mint a
   coordinator-owned content-validation record. Usability and gating eligibility
   are separate derived fields. No consumer accepts reviewer-authored
   `verified`, `usable` or `accepted` claims.

Raw structural checks and semantic policy supplement BAML; they cannot replace
it. A BAML worker outage, timeout, schema disagreement or fingerprint mismatch
produces no accepted review. An LLM formatter is not an acceptance validator.

Real-worker conformance tests must observe the exact parse operation, original
submission, echoed IPC ID and fingerprint, and consume the result from that
reply. A mutation that simply echoes the decoded input without invoking BAML
must fail the invocation assertion even though tree equality would pass.
Exercise actual BAML parse failures as well as transport failures. A cached
fingerprint, mocked success object or class-name/schema-only branch cannot
stand in for the operation.

The contract snapshot digest is exactly `_baml_worker.fingerprint(files)` over
the full rendered BAML files map passed to worker initialization, using its
existing sorted-key, ASCII-escaped canonical JSON encoding. Persist that exact
map content-addressed, including rendered taxonomy constants and bridge code.
Record bridge/runtime and validator versions separately. Resume uses the saved
map with a supported runtime/contract version, never the current package's
rendered sources. A missing map, mismatched fingerprint or unsupported version
refuses as stale. Unrelated BAML or taxonomy changes therefore cannot silently
change the parser used for an old result.

## Request identity and frozen inputs

Before dispatch the coordinator creates `ReviewRequestV1` containing:

- a unique request ID, attempt ID and original lineage ID; purpose `review` or
  `advisory`;
- coordinator-owned eligibility `NON_GATING | GOVERNED`, derived from the
  authoritative brief and existing policy, plus permitted provenance classes;
- contract version and digest of the exact BAML source snapshot;
- digest of the authoritative brief and ordered subject manifest;
- the expected seat identity and optional lens supplied by the coordinator;
- an ordered list of required questions with stable request-local IDs, selected
  for this seat's assigned scope rather than broadcast as irrelevant obligations;
- explicitly permitted evidence handles and the submission byte limit.

The subject manifest identifies Git content by immutable commit/tree and owned
paths, and standalone documents by byte digest. Dirty inputs use a frozen
snapshot with a manifest, never a mutable path as their sole identity. Artifact
manifests include content digests; referenced files must remain available under
the transport's existing confinement rules. Hash a canonical encoding with
defined array ordering, domain tags and UTF-8 treatment. Publish canonical
examples and negative vectors before adapters consume this contract.

The request binding is the digest of this complete request, excluding transport
IDs assigned after dispatch. After launch the coordinator separately binds
that request to the actual task/run or operation IDs received from the trusted
transport. An echoed binding is necessary to prevent accidental mix-ups; it is
not proof that the reviewer inspected the material.

## Reviewer result

`ReviewReplyV1` contains these required fields. Nullable fields must be present
with explicit JSON null. All objects reject additional properties.

| Field | BAML type or required meaning |
| --- | --- |
| `schema_version` | String fixed by semantic validation to `review_reply.v1` |
| `request_binding` | SHA256 digest of the coordinator's request |
| `review_status` | Enum `COMPLETE` or `INCOMPLETE` |
| `verdict` | Nullable enum `AGREE`, `PARTIALLY_AGREE`, `DISAGREE` |
| `summary` | Nonblank string |
| `scope_reviewed` | List of nonblank descriptions of work actually inspected |
| `findings` | List of `ReviewFindingV1`, explicitly `[]` if empty |
| `coverage` | List of `ReviewCoverageV1`, one entry per required question |
| `limitations` | List of nonblank descriptions of material limitations |

`ReviewFindingV1` requires a request-local unique `id`, `severity` enum
`BLOCKING | NON_BLOCKING`, nonblank `title`, `explanation`, `requested_change`,
an `obligation_refs` string list and an `evidence` list. A blocking finding must
identify an applicable requirement, contract, invariant or regression in
`obligation_refs`; absence of a roadmap goal ID alone does not dismiss a defect.

Each finding also requires nullable `falsifier: ReviewFalsifierV1`. Preserve the
landed IF-0-EXECFIND-1 interface and the met EC-EXECFIND-1, EC-EXECFIND-3,
EC-EXECFIND-4 and EC-EXECFIND-5 behavior, plus the currently landed foreign-
attachment hold, validator and authorized bounded runner associated with carried
EC-EXECFIND-2. This does not claim EC-EXECFIND-2 complete. Reconcile the active
EXECFIND phase and its governing amendment at implementation-planning intake.
Only a `BLOCKING`
finding may carry a non-null falsifier; a `NON_BLOCKING` finding carrying one
fails semantic validation. A non-null object has `nodeid` and `diff` strings.
Code-bearing fields remain private untrusted content; BAML acceptance does not
authorize execution. A null object remains non-executable prose evidence.
No source-code-only requirement is introduced for general or advisory findings.

`governed_board_gate` alone constructs and runs the existing attachment. Its
unchanged foreign-attachment check runs first: any leg arriving with
`finding_falsifiers` already set still holds with
`governed_foreign_falsifier_attachment`. For a typed leg, the gate then reads its
bound content-validated findings, never `parse_finding_falsifiers(leg.text)`.
Inside the gate, construct `FindingFalsifier` with `finding_id` equal to the
local finding ID, `new_test_path` derived using the existing
`phase-loop-runtime/tests/test_finding_<id>.py` identifier grammar,
`expected_nodeid=falsifier.nodeid` and `diff=falsifier.diff` (no prepended nodeid
line). Apply `_one_new_test_diff` unchanged: one named new test, matching node
identity and diff, no other file changes. This in-gate construction is not a
foreign attachment. Preserve the four-falsifiers-per-seat and twelve-per-board
limits across admitted attachments; excess holds with
`governed_falsifier_count_exceeded` before any runner call. A structurally invalid
blocking attachment, including invalid identifier/path/node/diff, produces the
existing board-wide non-human `governed_invalid_falsifier` hold. Retain that hold
for the bound board attempt: marking the seat unusable or consuming a content
correction cannot erase it. This differs from content-semantic rejection of a
forbidden non-blocking falsifier. Never scrape code from explanation, silently
drop an invalid object, or count a pre-attached object as a receipt.

After those checks, retain existing isolation authorization, exact-source
binding, bounded `run_finding_falsifier`, seat/local-ID result binding and outcome
classification. Missing authorization or a failed/unrecorded operation cannot
produce an executed receipt or clear dissent. Classify each accepted typed
finding using its local ID, severity and optional attachment, independently of
whether the overall verdict is `DISAGREE` or `PARTIALLY_AGREE`; do not read
`^FINDING` lines, terminal markers or prose to choose the branch. A `BLOCKING`
finding with an attachment enters the existing `finding_receipt` and runner
outcome rules. A `BLOCKING` finding with null attachment is `finding_prose`:
warn under `optional` falsifier policy and block under `required`, preserving
`unresolved_prose_dissent` and the existing required-policy hold. `NON_BLOCKING`
findings remain non-blocking codes. Derived legacy markers cannot replace
this per-finding classification or turn a warn-level finding into `panel_block`.
The typed path preserves source/authorization checks; a non-gating typed verdict
does not authorize execution. The governed gate, rather than a direct runner
call, is the required integration and regression-test boundary.

`ReviewEvidenceV1` requires a `basis` enum
`OBSERVED | INSPECTED | SUPPLIED | REASONED`, a nonblank `description` and
nullable `reference`. An observed test execution differs from inspecting a
saved result or repeating a supplied claim. References use coordinator-provided
handles where available. Validate handle membership and referenced digests;
unsupported or missing evidence is recorded as unverified, never automatically
retrieved from an arbitrary model-generated URL or filesystem path. A reasoned
design finding may have no file location and may use null reference.

`ReviewCoverageV1` requires `question_id`, `status` enum
`ANSWERED | NOT_ASSESSED`, nonblank `answer`, and a list of relevant finding IDs.
Reject duplicate, unknown or missing required question IDs and references to
nonexistent findings. With no required questions, coverage is explicitly `[]`.
The schema does not pretend that checking a question ID proves substantive
coverage; the full answer and evidence remain available for review.

The frozen contract must bound bytes, nesting, string lengths and list sizes.
Initial limits: 1,048,576 total UTF-8 bytes, nesting depth 32, 200 findings,
200 required questions, 100 evidence entries per finding, and 20,000 Unicode
code points per free-text field. The code-bearing `falsifier.diff` is exempt
from the free-text field cap but remains inside the total submission cap. The total
intentionally differs from the old verifier's 1,000,000-byte cap. Reject on
exhaustion; never truncate before validation.
Changes to limits are versioned policy inputs, not promises about future
commit counts, execution duration or history.

## Open-ended panels and decision semantics

A lens is optional request metadata, not a prerequisite for a typed reply.
Finding explanations and topics remain unrestricted natural language inside
typed fields. Code review, architecture, research and design panels all use
this envelope without inventing a closed taxonomy of every possible concern.
Adding a lens or question never changes the base result schema.

For purpose `review`, `COMPLETE` requires a non-null verdict, nonempty
`scope_reviewed` and every required question `ANSWERED`. `INCOMPLETE` requires
null verdict and at least one limitation; partial findings are retained but do
not supply a usable vote. `AGREE` permits no blocking findings; `DISAGREE`
requires at least one; `PARTIALLY_AGREE` requires at least one finding. A valid
dissent is a usable review, never a provider failure or a reason to swap models.

For purpose `advisory`, verdict is always null. `COMPLETE` still requires
nonempty `scope_reviewed` and every required question `ANSWERED`; `INCOMPLETE`
requires a limitation and provides no usable completed analysis. Select
seat-applicable required questions before dispatch; a reviewer cannot make an
obligation optional by declaring it inapplicable. Advisory suggestions use
summary and `NON_BLOCKING` findings without pretending to be defects.

Purpose and authority are independent. A `review` request with coordinator-owned
eligibility `NON_GATING` can express typed agreement for design convergence but
cannot satisfy a landing quorum. An advisory brief always implies `NON_GATING`.
`GOVERNED` additionally requires existing policy and admitted provenance. Neither
is a reviewer-authored field. Register identities for every typed non-gating brief
variant, including both review-purpose design verdicts and advisory analysis,
alongside the existing non-gating digests; preserve historical advisory identities.

`ReviewDecisionV1` requires schema version `review_decision.v1`, request binding,
review status, nullable decision `ACCEPT | REVISE`, summary, dispositions and
limitations. `COMPLETE` requires a non-null decision. `INCOMPLETE` requires null
decision and a limitation and never supplies a usable ruling. Reject every
other status/decision combination; there is no redundant INCOMPLETE decision.

The coordinator builds a complete ledger from content-validated seat records,
including findings from incomplete submissions and unresolved carried dissent.
Its unique finding key binds the originating content-validation record and
local finding ID; preserve original seat, severity, body and falsifier. Two
seats both using F1 remain distinct. The president request binds this complete
ledger's digest. Each key gets exactly one disposition `RESOLVED | OPEN |
DEFERRED`, nonblank rationale and evidence; reject missing, duplicate or foreign
keys. Never scrape/deduplicate prose to define membership. Invalid content is
preserved as diagnostic text, not invented typed findings. When existing policy
requires a president to address unusable seats, add separate coordinator-minted
status entries, with unique keys and the existing policy meaning.

`ACCEPT` cannot coexist with an OPEN blocking finding or a blocking finding
DEFERRED without already applicable policy authorizing that disposition.
Non-gating president decisions remain non-gating. No new waiver or merge
authority is created.

Transport completion, valid typed content, usable review vote and board
convergence are separate facts. Existing quorum, vendor independence,
source-grounding, author exclusion and presidential requirements still apply
after content validation.

## Transport adapters and durable intake

Implement a transport-neutral gateway with adapters for the existing panel
runtime, native-fill path and T3 host bridge. Provider structured-output support
may improve delivery; acceptance always follows the same BAML path.

For T3, the trusted driving host dispatches the frozen request through
`delegate_task` and registers its actual `taskId`, `childThreadId`, `childRunId`.
Read `task_status` for that original task; require original `status=completed`
and `workState=result_available`, using the fields exposed by the actual
`task_status` schema. An absent status or work-state field refuses
`result_unavailable`; do not infer success from a terminal-looking summary.
Pending original work/questions provide no candidate. Later `latestTerminal*` and `hasPendingChildRuns` are audit-only and
cannot replace or reopen an already completed original task. Delivery
acknowledgement does not change re-intake identity.

Use the complete original terminal summary. If it is not available untruncated,
recover the bound original-run terminal assistant item via `t3_thread_read`.
Check run/item identity and stable item content, then reassemble `textOffset` /
`nextTextOffset` chunks in UTF-16 code units without gaps/overlaps while enforcing
the UTF-8 byte cap. Never concatenate separate assistant items or later runs.
If completeness/identity cannot be established, refuse `result_unavailable`.
No shared reviewer-written file is authoritative.

Baseline provenance is `HOST_ATTESTED`: the trusted driving host, including its
driving agent, relays tool IDs and bytes and attests their source. An available
programmatic host channel may provide `TRANSPORT_CAPTURED`, where the gateway
captures the response directly. Record the actual class, host identity and trust
assumption; never label relayed data independently authenticated. Existing policy
must explicitly admit a class for governed use; otherwise host-attested typed
content stays non-gating. Unknown classes and reviewer self-attestation cannot
upgrade eligibility. Direct-capture tests reject content differing from the
transport response; host-attested mode cannot detect a dishonest trusted host.

The bridge assumes no ambient Python MCP access. Supply request, registration
and ingestion interfaces for the admitted trusted control channel, with fake
transports for tests. Preflight declares its actual provenance mode and refuses
unsupported modes. Reuse existing coordinator authority; do not fabricate a
receipt to turn a generic CLI caller into a trusted host. Direct T3 reviews
outside this gateway remain unverified advice.

Panel/native adapters validate before callbacks, verdict files, aggregation and
president inputs. Cover the early all-deferred and per-seat native-fill branches,
native-president initial deferral, `_resolve_native_president`,
`_resume_native_president` and bound `president.pending.json`. President prompts
and resumes bind the same complete ledger, brief and contract; changing one
invalidates the pending ruling.

Typed response bodies are JSON only. Change typed-mode `_completion_ok`, TUI,
broker and native completion checks to recognize complete JSON candidates
without requiring in-band terminal lines. Candidate detection is not acceptance
or proof of provider completion. Decode only defined transport envelopes to
recover the exact final content; retain separate transport and body digests.
Reject JSON followed by AGREE, RECOMMENDATION or FORCING DECISION even if
consistent; never strip such suffixes. After BAML acceptance, compatibility
renderers may derive legacy markers. Freeze `PARTIALLY_AGREE` to `PARTIALLY AGREE`
and uppercase severity to legacy lowercase mappings. Advisory markers derive
from validated advisory completion, not an invented verdict. Legacy markers
cannot create a usable vote.

The coordinator stores raw submissions privately and appends acceptance records
atomically outside reviewer-writable artifacts. A record binds request, attempt,
source manifest, saved BAML fingerprint, parse IPC ID/operation, runtime and
validator versions, transport identity/provenance, raw transport/body digests,
parsed result digest and outcome. Duplicate delivery of the
same terminal result is idempotent. A different result for a consumed attempt
is a conflict. Unknown launch outcome is reconciled before re-dispatch; a lost
connection is not permission to launch a duplicate review.

Resume revalidates bytes, identity, schema and outcome before counting a stored
vote. A digest-stable historical raw record can be re-parsed locally after a
worker outage without another provider call. Stale input/contract bindings
cannot silently carry forward. Legitimate delta-review carry uses an explicit
coordinator record naming its old input, reviewed delta and current applicability.

## Failure handling and privacy

Gateway outcomes distinguish transport failure, invalid content, incomplete
review, valid advisory result and usable review vote. Initial rejection codes
are closed constants: `invalid_json`, `schema_mismatch`, `binding_mismatch`,
`semantic_mismatch`, `baml_unavailable`, `baml_parse_failed`, `baml_changed_value`,
`result_incomplete`, `result_unavailable`, `delivery_conflict`, `limit_exceeded`.
They live in the new result contract, not implicitly in frozen legacy detail
or blocker enums. Map rejection to existing unusable/DEGRADED and
`panel_nonconforming` behavior until an explicit compatible vocabulary amendment
is tested. Quote the affected legacy contracts in downstream plans.

Allow at most one correction task in total per original seat-request lineage,
when the original policy permits it. Reserve this budget durably before dispatch;
restart, unknown launch outcome and fresh task/attempt IDs cannot reset it. An
invalid correction exhausts the allowance and cannot receive another correction.
Include the original brief, original
response, validation codes and all unresolved objections. Assign a new attempt
ID and preserve the original failure. Never retry valid dissent, silently change
provider/model, or reuse a correction as an additional independent vote.
Every valid correction is a fresh substantive standing review linked to the
original failed submission, never a certified format-only conversion: equivalence
to unparseable content cannot be established. Separately authorized substantive
review rounds retain their existing cap. Exhaustion leaves the seat unusable.

Raw text and model-authored strings are untrusted, including valid JSON.
Do not place them in metadata-only events, CLI diagnostics, exceptions or
telemetry. Preserve existing redaction before public text rendering; keep
validated review bodies in explicitly content-bearing private outputs. Public
events contain coordinator-derived IDs, digests, enum codes and counts only.
Acceptance does not execute requested changes, follow links or grant tools.

## Adoption and completion evidence

Freeze BAML types, semantic rules, request/receipt bindings, failure mapping and
test vectors before adapters. Build T3 and panel adapters in parallel, then
inventory and connect every governed consumer, serializer, stream and resume
path. No compatibility setting may let an untyped result satisfy a governed
review. Legacy prose can remain available as explicitly unverified advice.

Seed the exact consumer inventory with `runner.py`, `train_runner.py`,
`train_review_packet.py`, `governed_premerge.py`, `fab_gate.py`, `fab_producer.py`,
`fab_provenance.py`, `review_summary.py`, `governed_review.py`, the CLI,
ratification policy, all panel/native/president serializers and resumes and T3
intake. Discover direct and indirect callers rather than assuming this list
complete. Reconcile IF-0-PANELSPLIT-1 ownership: once it lands, use the actual
`phase_loop_runtime/panel/*` modules and facade consumers. Preserve
IF-0-EXECFIND-1 typed attachments and existing authorized falsifier execution
through these consumers without re-extracting code from prose.

Do not advertise universal enforcement until the complete consumer inventory
and mutation tests prove it. A feature flag or optional CLI mode is useful for
pilots but does not complete this requirement. Preserve existing executor BAML
closeouts and the legacy advisory contract during deployment.

Operational qualification must include one admitted T3 delegate result, one
panel execution, one native-fill execution and a president decision, each with
real BAML parsing and a failed-content negative control. T3 qualification records
its actual provenance class and proves typed intake under that trust assumption;
HOST_ATTESTED results remain non-gating unless existing policy explicitly admits
them. A successful live route does not itself grant governed eligibility.
When a required route is unavailable, report its coverage as unmet. Deterministic fake transports
prove boundary logic; they do not substitute for the named live route proof.
Bind the private qualification artifact to source, contract, route, request and
validator versions. Any proxy substitution requires the existing runner-stamped
plan/roadmap amendment mechanism before it can satisfy a gate.

This proposal can receive advisory review now. Its own current panel run does
not claim that the proposed BAML enforcement is already deployed or ratified.
