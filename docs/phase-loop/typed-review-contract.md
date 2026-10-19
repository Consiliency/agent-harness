# Typed review coordinator contract

This is the executable successor to the preserved
[design proposal](../proposals/typed-review-contract.md). The implementation is
`phase_loop_runtime.review_contract`; native result declarations remain in
`baml_src/review_reply.baml`. It supplies the SL-1 portion of
IF-0-RCONTRACT-1 and IF-0-RCONTRACT-2. Whole-phase verification, implementation
review and closeout still determine their production status. Local conformance
does not qualify a live route or deploy mandatory consumer enforcement.

## Acceptance and supported versions

The supported versions are `typed_review.v1`, `review_validator.v1`, and
`baml-bridge==0.20.1`. Reviewer bodies use `review_reply.v1`; president bodies
use `review_decision.v1`. A request fixes all three implementation versions and
the exact full rendered BAML map fingerprint. The coordinator stores that map
in its private database, keyed by the existing worker fingerprint: SHA256 of
sorted-key, compact, ASCII-escaped JSON over the complete filenames/content map.
Historical replay uses that saved map. Missing maps, digest mismatches and
unsupported versions refuse without reading current package sources or enums.

Acceptance, in order:

1. Decode the original bounded UTF-8 bytes as exactly one JSON object. Reject
   duplicate keys, nonfinite numbers, invalid Unicode, incomplete JSON, prose,
   fences and suffixes. JSON whitespace and object-key ordering are immaterial.
2. Check the original tree against the strict schema exported from the bound
   saved map. No handwritten review schema or enum inventory supplies authority.
   Unknown fields, omitted nullable fields and coercion are rejected.
3. Pass the exact original decoded text to `parse_review_response` with
   `EmitReviewReply` or `EmitReviewDecision`. Consume the actual matched worker
   reply and its function, operation, positive integer IPC ID, fingerprint and
   runtime version. Class-name parsing cannot supply this record.
4. Require recursive type, value and field-presence equality with the original
   tree, including boolean/integer and integer/float inequality. Then check
   semantic rules, request binding, evidence, question coverage and president
   ledger membership.
5. Commit a coordinator record. No accepted record is minted on worker failure.
   Rejection records retain closed reason codes and digests; bounded original bytes stay
   private, while over-limit originals are omitted explicitly. Parsing never dispatches a provider, executes a falsifier or fetches
   evidence.

Limits are 1,048,576 total UTF-8 bytes (or the request's smaller bound), container
depth 32 with the root object at depth one, 200 findings, 200 required questions,
100 evidence entries per finding/disposition, and 20,000 Unicode code points per
string value. Only `falsifier.diff` is exempt from the field cap; total bytes
still apply. Paired escaped surrogates decode normally; lone surrogates refuse.
The transport envelope has a separate `MAX_TRANSPORT_BYTES = 6_356_992` byte
limit (`6 * MAX_BYTES + 65_536`), independent of the original body limit
`MAX_BYTES = 1_048_576`. This covers the worst-case sixfold expansion of one
JSON string encoding of any bounded UTF-8 body, plus 65,536 bytes of host
metadata and framing. Adapters must preflight that their envelope format fits
this bound for every admitted body; nested encodings or larger host metadata
require a separately versioned contract, not a new review attempt. Both are
checked before inserting bytes. After host evidence/admission/capture checks,
delivery identity is compared first: differing content on a consumed attempt
raises `delivery_conflict`, even when the second candidate is oversized.

A reviewer body exceeding its bound consumes the attempt. The coordinator
atomically commits a digest-only delivery, `invalid_content/limit_exceeded`
record, validation observation and unusable-seat standing status. Neither body
nor envelope bytes are retained, even if the envelope fits. Their original SHA256
digests and byte lengths are retained. An original is eligible for its one
policy-permitted correction; an oversized correction exhausts that allowance.
When both body and envelope exceed their limits, this body-content rejection
takes precedence. Same-delivery retries and restart preserve the same rejection.

Envelope-only overflow exceeds this admitted framing bound:
`ReviewRefused("limit_exceeded")` commits
only request binding, closed code, original body/envelope digests and lengths to
private `intake_refusals`, without claiming a delivery or reviewer failure.
The first such observation binds the authentic body digest and length; across
restart, only envelope repair with that same body can retry. A different body
raises `delivery_conflict`, including a new oversized candidate. This is local
host repair, never provider redispatch authority or renewed correction budget.
Storage metadata is bounded per observation; there is no total database quota.
No input is truncated. Limits are versioned policy, not future-history pins.

`COMPLETE` reviews require scope and answered coverage; review-purpose replies
also require a verdict. `AGREE` excludes blockers, `DISAGREE` requires a blocker,
and `PARTIALLY_AGREE` requires a finding. Valid dissent is usable. `INCOMPLETE`
requires null verdict/decision and a limitation, preserves partial findings,
and supplies no vote/ruling. Advisory replies always have null verdict and no
blocking findings. Lenses are optional and never change the result schema.

Finding IDs are nonblank and request-local unique. Blocking findings require
obligation references. Coverage has exactly one entry per required question and
references only existing findings. Evidence references are handles in the
request's ordered `{handle, sha256}` list. An admitted host supplies independently
computed `evidence_digests` at ingestion: `None` means an empty dictionary;
otherwise the value must be a dictionary with nonblank string handles (at most
20,000 code points) and lowercase 64-hex SHA256 digests. Every handle must belong
to the request and its digest must match. Type, shape and membership/digest
errors raise the closed `ReviewRefused("binding_mismatch")` before committing
delivery or invoking the worker. They mint no reviewer failure record, authorize
no correction, and a corrected host submission may use the same unconsumed
attempt. A model reference absent from that verified set remains
unverified and is counted, including null/reasoned references; no retrieval or
claim of evidentiary truth follows from typing.

N9-R3: the only falsifier-specific semantic rejection is a `NON_BLOCKING`
finding with a non-null falsifier. Identifier/path/node/diff structural validity,
attachment counts, source/isolation authorization and execution belong to the
governed gate. Accepted code-bearing content remains private and untrusted.
This lane does not close EC-EXECFIND-2 or produce IF-0-EXECFIND-1.

## Trusted coordinator boundary

Construct `ReviewCoordinator(private_directory, policy=existing_policy)` only
inside an admitted coordinator. There is deliberately no default policy,
credential factory or generic CLI admission path. Its `CoordinatorPolicy`
protocol requires:

- `identity`: SHA256 identity of the existing versioned policy interpretation.
- `authorize(context) -> Admission`: derives eligibility, permitted provenance,
  correction permission and unusable-seat blocking policy from authoritative
  inputs. Context is a detached private input copy. `Admission` is a decision,
  not an authentication token or new waiver.
- `admit_transport(request, registration) -> bool`: recognizes the actual
  trusted host/control channel and permitted transport identity.
- `allow_deferred(request, finding_key) -> bool`: consults already applicable
  policy for blocking DEFERRED dispositions. The authorized keys are frozen
  into the president request.

`Admission` fields, in constructor order, are `eligibility` (`NON_GATING` by
default, or `GOVERNED`), `permitted_provenance` (default `("HOST_ATTESTED",)`),
`correction_allowed` (default false), `unusable_seat_blocks` (default true), and
`governed_provenance` (default empty tuple). Provenance sets must be tuples of
unique known strings; dispatch-permitted provenance must be nonempty and governed
provenance must be its subset. Both sets are copied as lists into the frozen
request. Invalid policy sets refuse with `binding_mismatch` before request creation.
Governed eligibility requires usable review-purpose content, GOVERNED authority,
and the current registered class explicitly present in `governed_provenance`.
Thus `Admission("GOVERNED")` still leaves HOST_ATTESTED content non-gating.
An existing policy can permit dispatch of both classes while admitting only
TRANSPORT_CAPTURED for governance, for example:

```python
Admission(eligibility="GOVERNED",
          permitted_provenance=("HOST_ATTESTED", "TRANSPORT_CAPTURED"),
          governed_provenance=("TRANSPORT_CAPTURED",))
```

This expresses a decision by existing authority; it is not an issuer or bootstrap.
Advisory requests cannot be governed. Purpose,
usable content and governed eligibility are separate. The host must change
`policy.identity` when its interpretation changes; mismatched saved identities
refuse. Reviewers must not implement policy or write the coordinator database.

`HOST_ATTESTED` explicitly trusts the driving host, including its agent, to relay
authentic task identities and terminal bytes. `TRANSPORT_CAPTURED` means the
admitted programmatic channel supplies the captured bytes directly; ingestion
requires them to equal the candidate body. Neither class implies governed
admission. The host-attested path cannot detect a dishonest trusted host. These
Python interfaces do not isolate hostile same-UID code or authenticate an
arbitrary caller; existing enforced isolation and an admitted control channel
remain prerequisites.

Adapters establish provider completion, original task/run/item identity,
untruncated terminal content, confinement and envelope decoding before intake.
For T3 this includes the original completed/result_available status and exact
original-run terminal item, with UTF-16 pagination where needed. Those are RT3
obligations, not claims made by the transport-neutral gateway.

## Frozen request and dispatch API

`create_request` has these keyword-only arguments:

```python
create_request(
    coordinator_key: str, brief: bytes, subjects: list[dict], seat: str,
    source_snapshot: BamlSourceSnapshot,
    purpose="review", lens=None, questions=None, evidence=None,
    function="EmitReviewReply", byte_limit=1_048_576, ledger=None,
) -> FrozenRequest
```

The coordinator key is the stable authorized board/round/seat dispatch identity.
Repeated creation with identical inputs recovers the same original request,
attempt and lineage; changed inputs conflict. A new key is a separately
authorized substantive round, never recovery from an unknown launch outcome.
The host owns round caps and key allocation. The gateway generates request,
attempt and lineage IDs; callers cannot assign a replacement lineage to a
correction.

Subjects are ordered `{kind, sha256, paths, revision}` objects. `kind` is
`document`, `git` or `snapshot`; `sha256` binds document bytes or an immutable
content manifest. Git requires a full 40/64-character commit/tree hash in
`revision`; other kinds require null. `paths` is an ordered nonempty string
list. Dirty inputs require a frozen snapshot manifest, never a mutable path as
identity. The transport retains actual subject availability and confinement.
Questions are ordered `{id, text}` objects, selected for the seat's applicable
scope; evidence is the ordered handle/digest list above. The brief's exact UTF-8
bytes are stored privately and bound by SHA256. Inputs are copied deeply;
`FrozenRequest.value` returns a detached copy and its repr omits content.

`FrozenRequest.binding` hashes the complete canonical request, including policy,
source, purpose, seat/lens, ordered inputs, limits and president ledger digest.
Transport IDs assigned after dispatch are excluded. `load_request(binding)`
loads the persisted identity and verifies source/version availability.
`build_request(binding)` returns the existing `BamlRequest`, built locally from
that saved map. Its prompt includes the frozen request, binding and exact brief.
Correction prompts include failure metadata and the `substantive_replacement`
label. Retained original invalid bytes are included losslessly as base64.
For an oversized original, `original_body_base64` is null, not empty or truncated
text. The prompt explicitly says the over-limit original bytes were not retained,
and supplies their digest, byte length, closed failure and exact original brief.
The absence fields below distinguish this from an authentic empty submission.

After dispatch call:

```python
register_transport(binding, *, host_identity, provenance, identity) -> str
ingest(binding, *, body: bytes, transport: bytes,
       evidence_digests=None, captured_body=None) -> ContentRecord
revalidate(binding) -> ContentRecord
validation_history(binding) -> list[dict]
```

`identity` is the admitted adapter's actual task/thread/run or operation ID map.
Registration is immutable and returns its domain-separated digest. Re-registration
is idempotent only for identical values. `transport` retains the exact original
transport envelope separately from decoded `body`. `captured_body` is required
only for direct capture and must come from the trusted capture channel.
`revalidate` repeats acceptance on retained bytes with saved sources locally.
For a digest-only delivery it checks the bound metadata, source and policy and
returns the same deterministic limit rejection without a BAML parse. Strict
precheck rejection does not require parsing; it can never create an accepted
receipt. Missing or altered stored bindings/sources still refuse. It never
dispatches or replenishes correction allowance.

## Durable delivery, records and correction

On POSIX the private directory is mode 0700 and `reviews.sqlite3` mode 0600.
Use a local filesystem supporting SQLite transactions and locking; the host must
enforce reviewer exclusion with its platform's access controls. Requests, full
BAML maps, briefs, registrations, raw body/envelope bytes,
parsed bodies, validation history, carry records and lineage reservations all
live there. Do not stage, publish or treat this database as telemetry.

SQLite `BEGIN IMMEDIATE` transactions with `synchronous=FULL` serialize delivery
claims and correction reservations across processes. Bounded original bytes and delivery
identity commit before parsing, after the host-input and storage bounds checks.
A process dying afterward leaves a resumable local validation, not permission
for a second dispatch. Matching terminal body, envelope, registration and evidence
verification are idempotent; any conflicting delivery for a consumed
attempt refuses. Retained delivery hashes are checked before replay.

`deliveries.raw` and `.transport` are SQL NULL for digest-only intake;
`.omitted` contains exactly `body_digest`, `transport_digest`, `body_bytes`, and
`transport_bytes`. Its digests, lengths and explicit absence participate in the
delivery identity. Retained deliveries have `.omitted = NULL` and exact blobs;
their existing delivery identities are unchanged. Every byte consumer checks
this distinction before decoding. Omitted bytes are never replaced by `b''`, a
prefix, synthesized JSON or worker input. Digest-only delivery and rejection
commit in one transaction; a crash rolls both back so retry of the same authentic
delivery can finish locally. Schema initialization and migration are also atomic:
older six-column delivery tables gain nullable blobs and `.omitted`, preserving
all existing bytes/identities without inventing history or reclassifying past
size-refusal observations. The first old envelope-refusal observation also binds
body identity on a new intake; historical refusals are not retroactive deliveries.

F4 accepted operational alternative: worker parsing deliberately holds the SQLite
write lock. Other coordinator operations have a **60-second busy timeout** and
may raise `result_unavailable` during a slow parse; the worker's own finite budget
can exceed that timeout. Callers may retry local coordination against the same
request/delivery or recover an existing correction reservation. Neither timeout
nor retry permits provider redispatch or resets the correction budget. This
implementation adds no pending claim, lease or compare-and-set parsing protocol.

Local revalidation retains the first matching valid or invalid-content `ContentRecord` when
all metadata other than per-invocation IPC ID agree: request/attempt/delivery,
source/version, parsed digest, outcome, policy/usability and replacement linkage.
Its original IPC identity and receipt hash remain unchanged, as do finding keys
and an unchanged president ledger, including invalid-seat status keys. Every completed validation attempt appends a
private `validations` row atomically with its result. `validation_history(binding)`
returns ordered dictionaries with `sequence`, `result_record_id`, and `invocation`.
`invocation` contains the complete metadata for that actual validation, including
matched operation/IPC ID/fingerprint/runtime and its result code/digest; unavailable
parse metadata is null. A successful reparse's `result_record_id` can therefore
refer to the original receipt while `invocation.ipc_id` names the new parse.
An idempotent delivery lookup appends no fictitious invocation. A digest-only
revalidation appends a validation observation with null operation, IPC ID,
runtime and parsed digest: it does not claim a parse occurred. A deterministic
semantic or changed-worker-value rejection keeps its original record identity
while history records the actual new IPC metadata.

A failed revalidation becomes the delivery's explicit current failure and is
returned as unusable, while the historical accepted standing record stays intact.
`build_ledger` refuses `result_unavailable` when current validation differs from
standing. Recovery must revalidate successfully; matching success recovers the
original record and keys without dispatch. History/private-body access alone
never proves current usability. Initial failures with no accepted history remain
standing diagnostic/status records. No historical failure or invocation is erased.

`ContentRecord` binds generated attempt/lineage IDs, request/subject/source
digests, versions, actual parse operation/IPC ID, registration/host/body/envelope
digests, parsed digest, outcome, rejection code, provenance, counts, usability,
eligibility and replacement identity. `record_id` hashes the remaining metadata
under the receipt domain. No arbitrary model strings, raw transport IDs, seat
names or host names enter it. `usable_vote` and `usable_ruling` distinguish
review and president results; `usable` also includes completed advisory analysis.
Neither property substitutes for quorum, independence or governed policy.
`private_body(record_id)` explicitly returns content-bearing validated data;
invalid content, including digest-only rejection, refuses `binding_mismatch`.
Consumers must revalidate retained bytes before counting a resumed result and
check that call's successful usable result. An exception, unusable result or
previously cached receipt is insufficient; retry local revalidation after recovery.
`private_body` intentionally allows historical inspection and is not an acceptance
or current-validation gate. Existing pre-freeze databases gain history tables on
open, but no past invocation history is invented. Pre-correction requests lack the
new admission field and are not migration-qualified; downstream rollout must use
the frozen corrected request contract rather than infer governed admission.

Closed rejection codes are `invalid_json`, `schema_mismatch`,
`binding_mismatch`, `semantic_mismatch`, `baml_unavailable`, `baml_parse_failed`,
`baml_changed_value`, `result_incomplete`, `result_unavailable`,
`delivery_conflict`, and `limit_exceeded`. `ReviewRefused` exposes only a closed
code. Outcomes distinguish `transport_failure`, `invalid_content`,
`incomplete_review`, `valid_advisory`, `usable_review` and `usable_decision`.
Adapters map unusable outcomes to existing unusable/DEGRADED and
`panel_nonconforming` behavior without appending these codes to frozen legacy
enums or copying model text into legacy detail fields. Valid dissent is not a
transport failure.

`reserve_correction(original_binding)` atomically reserves at most one new
attempt for the original lineage before dispatch. It requires policy permission
and a content-invalid original; valid/incomplete typed content and worker
outages do not justify correction dispatch. `correction_request(original_binding)`
recovers an existing reservation, including an unknown launch outcome, without
replenishing it. `correction_context(correction_binding)` is a private accessor
for original bytes, exact original brief, brief digest and failure metadata.
Its `original_body` is now `bytes | None`: None means the oversized original was
not retained. Additive fields are `original_body_retained` (bool),
`original_body_absence_reason` (null or `limit_exceeded`),
`original_body_digest` (original SHA256) and `original_body_bytes` (original byte
length). An authentic empty body remains `b''`, retained true, absence reason
null, length zero. Consumers must branch on the explicit absence fields; no
format-only equivalence or reconstruction of absent content is possible.
The adapter carries all unresolved objections and unchanged provider/model.
An invalid correction exhausts the allowance. A valid correction is a substantive
replacement linked to the original failure, not certified format-only equivalence.
The `lineage` object in `typed_review_contract_vectors.json` is an executable
`typed_review_lineage_replay.v1` fixture. It supplies complete request/body inputs,
`$name.field` symbolic bindings, expected codes, replacement links, standing
transitions, distinct correction attempt IDs, restart and reservation recovery.
Its four scenarios cover invalid-original → invalid-correction → refused-again,
valid substantive replacement, no correction of valid dissent, and oversized
original → oversized correction with idempotent retry and conflicting later
content. `body_suffix_spaces` specifies exact ASCII whitespace padding for
bounded fixture generation, not truncation or intake repair. Revalidation in
scenario 1 retains the original invalid correction record ID. The gateway
test executes every step; RT3/RPANEL adapters must replay it through their own
interfaces for EC-RT3-2 and EC-RPANEL-1. Fixture execution is not live-route proof.

## President ledger and carried dissent

`build_ledger(lineage_ids, *, carry_ids=None)` builds a private ledger from the
single standing record for every supplied seat lineage, including incomplete
findings and coordinator status entries for unusable seats. The trusted host
must supply its complete authoritative roster. Invalid bodies create no invented
typed findings. A finding key hashes its originating content-record ID and local
finding ID, so two seats' `F1` values remain distinct. Original seat, body,
severity and falsifier are retained. Status keys use a null local ID and follow
the request's already authorized unusable-seat policy.

Legitimate delta carry uses
`register_carry(record_id, reviewed_delta_digest=..., current_applicability_digest=...)`.
It persists an explicit coordinator record binding the old request/input and
current applicability decision; its returned ID goes in `carry_ids`. Passing a
raw content-record ID as a carry refuses. Carry does not change provenance or
grant eligibility; its policy and source bindings remain checked.

A president request uses `function="EmitReviewDecision"` and the exact ledger,
review purpose and no required-question list. Ledger bodies are verified against
coordinator storage; the request includes its domain-separated digest. Changing
the standing ledger invalidates a pending ruling. Revalidation or first intake
against a genuinely changed or unavailable ledger records coordinator-side
`transport_failure` / `result_unavailable`, never invalid reviewer content and
never correction eligibility. A historically accepted ruling remains retained
but cannot be counted on that failed current validation. Every key requires exactly one
disposition with rationale and evidence. `ACCEPT` cannot leave an OPEN blocker
or DEFER a blocker without existing frozen authorization. COMPLETE requires a
decision; INCOMPLETE requires null and a limitation. No new merge or waiver
authority follows.

## Canonical encoding and adapter example

`canonical_json` supports null/bool/int/string/list/object: sorted object keys,
compact separators, literal UTF-8, original array order, no Unicode normalization
and no floats. `canonical_digest(domain, value)` hashes
`b"phase-loop/typed-review/v1/" + domain.encode("ascii") + b"\0" + canonical_json(value)`.
Domains are `request`, `receipt`, `ledger`, `finding`, `delivery`, `registration`,
`subjects`, `policy` and `carry`. The BAML source fingerprint retains its separate
upstream ASCII encoding. Published full request/receipt examples and their exact
canonical bytes/digests are in
`phase-loop-runtime/tests/data/typed_review_contract_vectors.json`; they are
synthetic encoding examples, not acceptance receipts.

Inside an already admitted downstream adapter:

```python
from phase_loop_runtime.baml_modular import snapshot_baml_sources
from phase_loop_runtime.review_contract import ReviewCoordinator

gateway = ReviewCoordinator(private_directory, policy=existing_coordinator_policy)
request = gateway.create_request(
    coordinator_key=authorized_board_round_seat_key,
    brief=authoritative_brief_bytes,
    subjects=frozen_subject_manifest,
    seat=expected_seat,
    questions=seat_applicable_questions,
    evidence=permitted_evidence_handles,
    source_snapshot=snapshot_baml_sources(),
)
provider_request = gateway.build_request(request.binding)
# Existing admitted adapter dispatches once, reconciles unknown outcomes, and
# checks original task completion/item identity and complete untruncated bytes.
gateway.register_transport(
    request.binding, host_identity=admitted_host_identity,
    provenance="HOST_ATTESTED", identity=actual_task_thread_run_ids,
)
record = gateway.ingest(
    request.binding, body=complete_original_body, transport=original_envelope,
    evidence_digests=independently_verified_evidence_digests,
)
if record.usable_vote:
    private_reply = gateway.private_body(record.record_id)
    # Apply existing consumer policy; governed eligibility is a separate field.
# Resume: gateway.revalidate(request.binding), never another provider dispatch.
```

The gateway tests exercise actual local worker replies for valid review and
president bodies, invocation-bypass and changed-reply controls, saved-map replay,
limits, privacy, conflicting concurrent delivery, process restart and correction
exhaustion. EC-RCONTRACT-1/2/3 evidence is reduced by the parent through sealed
phase verification. These tests do not qualify T3, panel, native-fill or president
live routes and do not claim universal enforcement or phase/roadmap completion.
