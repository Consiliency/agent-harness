# SCHEMA public input inventory and coverage findings

Planning observation, 2026-11-05 UTC; not an implementation or conformance receipt.
Source: public Consiliency/consiliency-contract, commit
`93db4b4fcc4e3d40c62f6658b6a67b519c750491`, root `core/supervised-run/`.
Only input identities are pinned here. The associated plan is
`plans/phase-plan-v12-SCHEMA.md`, for agent-harness#1818.

## Acquisition and independent verification

Read-only clone of https://github.com/Consiliency/consiliency-contract.git with
`--filter=blob:none --no-checkout --single-branch --branch main`; restored only
core/supervised-run from the requested commit into scratch. No upstream writes.
`gh api repos/Consiliency/consiliency-contract` reported private=false and
default_branch=main. `gh api repos/Consiliency/consiliency-contract/branches/main`
reported protected=true and head equal to the pinned commit.
`git merge-base --is-ancestor <pinned-commit> origin/main` exited 0 after the
fresh fetch. Protection is an observed boolean, not a claim about individual
rules or a signature. Repeat these checks during intake; record changed metadata.

Computed sha256 directly from each fetched file's bytes with sha256sum and
hashlib.sha256, and obtained blob ids with git rev-parse at the requested commit.
All five SHA256SUMS entries independently matched; the full manifest hash agrees
with the owner-supplied b9c2dad7 prefix. Its paths are relative to conformance/.
The immutable commit is the supplied trust anchor; hashes calculated here are
verification observations, not an independently signed maintainer attestation.
Never accept a newly computed digest merely because the new payload claims it.

| Path relative to core/supervised-run | Computed sha256 | Git blob id |
| --- | --- | --- |
| `admitted-launch-envelope.schema.json` | `0273f7a5d80eab95ee84660cd657445e881431bca3b8f91cec61015a5d39d41d` | `1abe40abbb1178295af86b3c6d64f9bffe5a0099` |
| `conformance/README.md` | `2d5045245105af88f1f45f720aa8bc3f366efc95c25e25a9c50e402a175533ca` | `9051f4fcfa7bb91b896f3efe60b6a3b238545a75` |
| `conformance/SHA256SUMS` | `b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285` | `ff78301d393ef361f6c476a7117f0d2d97d2193b` |
| `conformance/envelope.vectors.json` | `876d322c313b444e49d7a95ee8f7ca39eef13c45864c67a0b3877235e1db6d7f` | `4fcb908f0ed89f2206efc2fbf4c5a6c7bdbd7e56` |
| `conformance/run-status.vectors.json` | `5bf9dfbf65805f7340290586d546038fc88659785e60e2f55532df4ac6696730` | `4a156e4fbf56526d483f729c78b2e94eb6f48f93` |
| `provenance.json` | `9444d9285e4fbf9fa78c7e10fb474885c79f77cb65abec2f45527af2ec57ff42` | `cb2d905ba4fc12c9df1244f301c2624a656643ac` |
| `run-status.schema.json` | `5118c1ab8604e85990150d66bf6b8c1af979dcc404fc84ee5a3c4ba4fead9a30` | `8af75b390c1b6dcb5478ac16daec3bd38cb060d1` |

## Approved runtime closure

Vendor admitted-launch-envelope.schema.json, run-status.schema.json,
conformance/README.md, conformance/SHA256SUMS, conformance/envelope.vectors.json
and conformance/run-status.vectors.json verbatim, preserving relative names.
Both schemas declare draft 2020-12. Their IDs are
urn:contract:admitted_launch_envelope.v1 and urn:contract:supervised_run_status.v1;
all schema $refs are fragment-local. No remote resource closure is required.

The inventoried upstream provenance.json is not referenced by either schema
or SHA256SUMS. Keep its digest/blob metadata only: its embedded source-history
content is outside the roadmap's public-input scope. Runtime harness provenance
must cite only the public distribution repository/commit and this six-file
closure, with an explicit exclusion entry for distribution metadata. Do not
copy private-source metadata, fetch its origin or mutate a vendored source file.
A separately reviewed harness-provenance.json, explicitly outside the six upstream
resources, will itself be digest-pinned in
supervised_contracts.py. The implementation receipt must distinguish that
harness metadata from the byte-identical upstream files.

## Owner decisions and byte-pin authority

Manual SCHEMA intake proceeds now against the frozen v1 publication. The verified
publication satisfies the maintainer inventory requirement; the owner has confirmed
the existing published-inventory record. No additional signature or record is required.
The pin table above distinguishes published expected values from local verification.

IF-0-SCHEMA-1 freezes the v1 loader, six-file input and accurate receipt.
byte_pin_authority is a separate receipt boolean and remains false for this intake.
WORKER remains the roadmap automatic-selection edge; owner-authorized manual intake
does not wait for WORKER or for the test files this phase creates.

The contract owner will publish admitted_launch_envelope.v2 alongside unchanged v1
through a reviewed squash merge of a consiliency-contract PR, without a tag. No
v2 commit or digest is assumed. The five bindings are instruction/reference byte
digests, argv (SHA-256 of UTF-8 RFC 8785 JCS array), executable/wrapper identity,
workspace source and integer timeout seconds in [1, declared_bound], bound <=3600.
Reconciliation also covers effective environment, trusted policy/qualification,
action/route/delivery and conditional execution-view/egress grants. Host-local
identities stay local; public fields carry digest/reference bindings. v2 has no
caller_context or harness-local fields. The harness owns ENVELOPE reconciliation
in the publication-gated CLOSEOUT follow-up, including exact-key codec handling.

| Dimension | Required reconciliation and receipt treatment |
| --- | --- |
| Launch coverage | Verify each of the five bindings against published v2, then the four additional groups against the effective local launch snapshot. Resolve every cited schema pointer and verify every asserted absence. Opaque context, snapshot or obligation references alone do not establish launch coverage. |
| Tier basis | v1 annotates provider_readonly_patch_return_audit and post_write_audit_only qualified=true, and os_enforced qualified=false; provider write_scope is checked_before_apply, the others not_enforced. Annotations describe semantics/limits only; independently qualified tool evidence is still required. Preserve the harness matrix and route_not_qualified outcome when qualification is not established. |
| Named controls | Inventory E-admitted, E-dependency-declared and E-echo separately for required write_scope reconciliation. E-dependency-declared also requires an owner-approved dependency-route mapping. Preserve standalone dependency refusal; schema validity is not permission to queue these controls on that route. |
| Identity | Require the public-codec envelope-to-attempt join, fresh attempt identity, sequential/concurrent/restart replay proof, and invariant unit/snapshot/crosswalk provenance. Resolve the public mapping for EC-JOURNAL-4 correlation without adding fields or reinstating caller_context in v2. |
| Lifecycle and bounds | Require the semantic/journal entries and named coverage obligations below, including all four numeric limits and every lifecycle edge. |
| Distribution | v1 remains provisional and byte-identical. Reconcile and explicitly repin any later publication; no local wire additions. |

These are authority conditions recorded by the v1 receipt, not execution blockers.
Unresolved rows retain upstream_phase_unmet for CLOSEOUT and keep
byte_pin_authority=false even when all structural tests pass. V2 publication is
necessary but does not alone satisfy unresolved identity/lifecycle/evidence proof.

## Structural and semantic evidence separation

The public README says every patched negative is schema-valid by construction.
There are 16 envelope cases (4 controls, 12 negatives) and 35 status cases
(7 controls, 28 negatives). The case table below records original IDs and
expected diagnostics, not observed semantic results. Every row remains
unresolved upstream_phase_unmet for runtime proof, including controls' effects.
SCHEMA consumes verified bundle buffers, projects structural components and adds
explicitly local structural negatives per definition and nested reference; those local cases do not become upstream vectors.

Extraction: envelope cases validate input.envelope; echoed context and injected
validator_context are semantic inputs. Journal cases validate every object line
in every attempt/segment; preserve string lines and final-newline flags for
runtime readers. Projection cases also validate projection against its $defs;
liveness is a semantic input. reader_view uses the complete row/run_record/display
input. Page cases map request to page_request and page to page. Every component
must be accounted for; no skipped raw line can count as semantic conformance.

S-evidence-copied replaces the second attempt's evidence_envelope_digest with
the first attempt's digest and expects exactly attempt_evidence_copied. Its
positive control V-two-attempts deliberately has equal proposal_bytes_digest
values, distinct evidence digests, and distinct envelope/run/attempt identities.
Both are structurally valid; JOURNAL/WORKER must demonstrate rejection and
acceptance respectively through production paths in CLOSEOUT. Equal proposal
bytes must not be mistaken for copied evidence. N20-raw-stdout-ref exercises
inline output in a reference; N18-run-status-as-evidence checks producer authority.
No JSON Schema rejection substitutes for these diagnostics.

| Family | Case | Expected diagnostics | Runtime owner; proof phase |
| --- | --- | --- | --- |
| envelope | `E-admitted` | (none; positive control) | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `E-post-write-honest` | (none; positive control) | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `E-dependency-declared` | (none; positive control) | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `RC16-stale-rehashed` | `authority_baseline_stale` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `RC17-foreign-assignment-rehashed` | `authority_foreign` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `RC17-foreign-project-rehashed` | `authority_foreign` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `S-digest-not-rehashed` | `envelope_digest_mismatch` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `N21-network-required` | `constraint_unsupported` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `N21-command-required` | `constraint_unsupported` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `N21-worktree-under-patch-return` | `workspace_not_separate_copy` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `S-os-enforced-unqualified` | `tier_unqualified` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `S-dependency-without-digest` | `dependency_digest_required` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `S-envelope-absolute-locator` | `locator_not_repo_relative` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `S-envelope-raw-output` | `raw_output_in_record` | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `E-echo` | (none; positive control) | ENVELOPE/WORKER; CLOSEOUT |
| envelope | `S-caller-context-interpreted` | `caller_context_interpreted` | ENVELOPE/WORKER; CLOSEOUT |
| status | `V-two-attempts` | (none; positive control) | JOURNAL/WORKER; CLOSEOUT |
| status | `V-running` | (none; positive control) | JOURNAL; CLOSEOUT |
| status | `V-refused-before-launch` | (none; positive control) | JOURNAL; CLOSEOUT |
| status | `N04a-seq-skip` | `attempt_overwritten` | JOURNAL; CLOSEOUT |
| status | `N04a-seq-regress` | `attempt_overwritten` | JOURNAL; CLOSEOUT |
| status | `N04a-replaced-in-place` | `attempt_overwritten` | JOURNAL; CLOSEOUT |
| status | `N04b-foreign-binding` | `attempt_provenance_mismatch` | JOURNAL/WORKER; CLOSEOUT |
| status | `S-evidence-copied` | `attempt_evidence_copied` | JOURNAL/WORKER; CLOSEOUT |
| status | `N15-torn-line` | `journal_torn_line` | JOURNAL; CLOSEOUT |
| status | `N15-no-final-newline` | `journal_torn_line` | JOURNAL; CLOSEOUT |
| status | `N15-unknown-version` | `journal_unknown_version` | JOURNAL; CLOSEOUT |
| status | `N15-foreign-writer` | `journal_foreign_writer` | JOURNAL; CLOSEOUT |
| status | `N19-refused-after-start` | `refused_after_launch` | JOURNAL; CLOSEOUT |
| status | `N19-refused-after-running` | `refused_after_launch` | JOURNAL; CLOSEOUT |
| status | `S-finished-without-termination` | `lifecycle_invalid` | JOURNAL; CLOSEOUT |
| status | `N20-raw-stdout-ref` | `raw_output_in_record` | JOURNAL; CLOSEOUT |
| status | `N20-raw-message` | `raw_output_in_record` | JOURNAL; CLOSEOUT |
| status | `N20-absolute-locator` | `locator_not_repo_relative` | JOURNAL; CLOSEOUT |
| status | `N20-parent-locator` | `locator_not_repo_relative` | JOURNAL; CLOSEOUT |
| status | `V-projection-at-tail` | (none; positive control) | JOURNAL; CLOSEOUT |
| status | `N16-projection-behind` | `projection_behind_journal` | JOURNAL; CLOSEOUT |
| status | `N16-attempt-missing` | `projection_behind_journal` | JOURNAL; CLOSEOUT |
| status | `S-projection-ahead` | `projection_not_from_journal` | JOURNAL; CLOSEOUT |
| status | `V-owner-live` | (none; positive control) | JOURNAL; CLOSEOUT |
| status | `N17-owner-not-live` | `owner_not_live` | JOURNAL; CLOSEOUT |
| status | `N17-pid-reused` | `owner_not_live` | JOURNAL; CLOSEOUT |
| status | `V-reader-view` | (none; positive control) | JOURNAL; CLOSEOUT |
| status | `N18-completed-as-outcome` | `runtime_not_work_outcome` | JOURNAL; CLOSEOUT |
| status | `N18-run-status-as-evidence` | `runtime_not_work_outcome` | JOURNAL; CLOSEOUT |
| status | `RC24-foreign-assignment` | `run_record_foreign` | JOURNAL; CLOSEOUT |
| status | `RC24-foreign-snapshot` | `run_record_foreign` | JOURNAL; CLOSEOUT |
| status | `V-page` | (none; positive control) | JOURNAL; CLOSEOUT |
| status | `RC25-no-page-size` | `read_unbounded` | JOURNAL; CLOSEOUT |
| status | `RC25-no-omitted` | `read_unbounded` | JOURNAL; CLOSEOUT |
| status | `RC25-over-bound` | `read_unbounded` | JOURNAL; CLOSEOUT |

Expected effects, when supplied, remain exact subset assertions under the public
README. At CLOSEOUT, bind every production result and per-guard mutation witness
to this inventory. Unknown versions, broken chains, torn tails, stale projections,
foreign records, unbounded pages and copied evidence must not be marked proven
by a structurally green record. Do not implement a second semantic evaluator in
supervised_contracts.py or in this planning task.

## Schema-derived obligation inventory

The 51 case rows are one index, not the full semantic inventory. The required union
is every x-semantic-rules code, every recursive x-journal-rules member and every
named obligation below. Tests derive those sets from verified resource_bytes and
require exact coverage. Each receipt row carries id, source_pointer, vector_ids
(possibly empty), owner, status and required_proof. All semantic results remain
unresolved upstream_phase_unmet until production proof; zero-vector rows remain
explicit authority conditions. Expected effects are recorded independently of
expected diagnostic sets. SCHEMA does not implement new semantic rules.

| Rule ID | Source pointer | Published diagnostic vectors | Owner |
| --- | --- | --- | --- |
| `envelope:envelope_digest_mismatch` | `admitted-launch-envelope.schema.json#/x-semantic-rules/envelope_digest_mismatch` | `S-digest-not-rehashed` | ENVELOPE/WORKER |
| `envelope:authority_foreign` | `admitted-launch-envelope.schema.json#/x-semantic-rules/authority_foreign` | `RC17-foreign-assignment-rehashed`, `RC17-foreign-project-rehashed` | ENVELOPE/WORKER |
| `envelope:authority_baseline_stale` | `admitted-launch-envelope.schema.json#/x-semantic-rules/authority_baseline_stale` | `RC16-stale-rehashed` | ENVELOPE/WORKER |
| `envelope:tier_unqualified` | `admitted-launch-envelope.schema.json#/x-semantic-rules/tier_unqualified` | `S-os-enforced-unqualified` | ENVELOPE/WORKER |
| `envelope:constraint_unsupported` | `admitted-launch-envelope.schema.json#/x-semantic-rules/constraint_unsupported` | `N21-network-required`, `N21-command-required` | ENVELOPE/WORKER |
| `envelope:workspace_not_separate_copy` | `admitted-launch-envelope.schema.json#/x-semantic-rules/workspace_not_separate_copy` | `N21-worktree-under-patch-return` | ENVELOPE/WORKER |
| `envelope:locator_not_repo_relative` | `admitted-launch-envelope.schema.json#/x-semantic-rules/locator_not_repo_relative` | `S-envelope-absolute-locator` | ENVELOPE/WORKER |
| `envelope:dependency_digest_required` | `admitted-launch-envelope.schema.json#/x-semantic-rules/dependency_digest_required` | `S-dependency-without-digest` | ENVELOPE/WORKER |
| `envelope:raw_output_in_record` | `admitted-launch-envelope.schema.json#/x-semantic-rules/raw_output_in_record` | `S-envelope-raw-output` | ENVELOPE/WORKER |
| `envelope:caller_context_interpreted` | `admitted-launch-envelope.schema.json#/x-semantic-rules/caller_context_interpreted` | `S-caller-context-interpreted` | ENVELOPE/WORKER |
| `envelope:refusal_zero_invocations` | `admitted-launch-envelope.schema.json#/x-semantic-rules/refusal_zero_invocations` | (none; explicit unresolved obligation) | ENVELOPE/WORKER |
| `status:journal_torn_line` | `run-status.schema.json#/x-semantic-rules/journal_torn_line` | `N15-torn-line`, `N15-no-final-newline` | JOURNAL/WORKER |
| `status:journal_malformed_line` | `run-status.schema.json#/x-semantic-rules/journal_malformed_line` | (none; explicit unresolved obligation) | JOURNAL/WORKER |
| `status:journal_unknown_version` | `run-status.schema.json#/x-semantic-rules/journal_unknown_version` | `N15-unknown-version` | JOURNAL/WORKER |
| `status:journal_foreign_writer` | `run-status.schema.json#/x-semantic-rules/journal_foreign_writer` | `N15-foreign-writer` | JOURNAL/WORKER |
| `status:attempt_overwritten` | `run-status.schema.json#/x-semantic-rules/attempt_overwritten` | `N04a-seq-skip`, `N04a-seq-regress`, `N04a-replaced-in-place` | JOURNAL/WORKER |
| `status:attempt_provenance_mismatch` | `run-status.schema.json#/x-semantic-rules/attempt_provenance_mismatch` | `N04b-foreign-binding` | JOURNAL/WORKER |
| `status:attempt_evidence_copied` | `run-status.schema.json#/x-semantic-rules/attempt_evidence_copied` | `S-evidence-copied` | JOURNAL/WORKER |
| `status:refused_after_launch` | `run-status.schema.json#/x-semantic-rules/refused_after_launch` | `N19-refused-after-start`, `N19-refused-after-running` | JOURNAL/WORKER |
| `status:lifecycle_invalid` | `run-status.schema.json#/x-semantic-rules/lifecycle_invalid` | `S-finished-without-termination` | JOURNAL/WORKER |
| `status:raw_output_in_record` | `run-status.schema.json#/x-semantic-rules/raw_output_in_record` | `N20-raw-stdout-ref`, `N20-raw-message` | JOURNAL/WORKER |
| `status:locator_not_repo_relative` | `run-status.schema.json#/x-semantic-rules/locator_not_repo_relative` | `N20-absolute-locator`, `N20-parent-locator` | JOURNAL/WORKER |
| `status:projection_behind_journal` | `run-status.schema.json#/x-semantic-rules/projection_behind_journal` | `N16-projection-behind`, `N16-attempt-missing` | JOURNAL/WORKER |
| `status:projection_not_from_journal` | `run-status.schema.json#/x-semantic-rules/projection_not_from_journal` | `S-projection-ahead` | JOURNAL/WORKER |
| `status:owner_not_live` | `run-status.schema.json#/x-semantic-rules/owner_not_live` | `N17-owner-not-live`, `N17-pid-reused` | JOURNAL/WORKER |
| `status:run_record_foreign` | `run-status.schema.json#/x-semantic-rules/run_record_foreign` | `RC24-foreign-assignment`, `RC24-foreign-snapshot` | JOURNAL/WORKER |
| `status:runtime_not_work_outcome` | `run-status.schema.json#/x-semantic-rules/runtime_not_work_outcome` | `N18-completed-as-outcome`, `N18-run-status-as-evidence` | JOURNAL/WORKER |
| `status:read_unbounded` | `run-status.schema.json#/x-semantic-rules/read_unbounded` | `RC25-no-page-size`, `RC25-no-omitted`, `RC25-over-bound` | JOURNAL/WORKER |

The envelope refusal_zero_invocations obligation additionally consumes refusal
expected_effect assertions; diagnostic-vector absence never removes that obligation.

| Journal entry | Owner | Required evidence |
| --- | --- | --- |
| `run-status.schema.json#/x-journal-rules/location` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/writers` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/segments` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/queued` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/queued/0` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/queued/1` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/running` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/running/0` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/running/1` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/cancelling` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/cancelling/0` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/finished` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/lifecycle/refused` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/bounds` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/bounds/page_size_max` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/bounds/event_message_max_chars` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/bounds/per_attempt_event_cap` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/bounds/attempts_per_page_max` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |
| `run-status.schema.json#/x-journal-rules/liveness` | JOURNAL/WORKER | Production proof, mapped to zero or more case IDs; unresolved until observed. |

## Named coverage obligations

These are required outcomes for publication reconciliation and runtime proof, not
new harness wire rules. The public contract owner supplies any necessary normative
rule/vector coverage; the harness implements only the reconciled contract.

| ID | Required behavior / publication decision | Proof owner |
| --- | --- | --- |
| status-digest-text | All digest-typed positions have exact lexical identity; settle the status-wide control-character policy with the owner. | Contract owner; JOURNAL |
| lifecycle-shape | line_kind and body_kind agree; each terminal state has its owner-defined termination/refusal/result-binding combination, with no contradictory state data. | Contract owner; JOURNAL |
| lifecycle-transitions | Enforce every allowed transition and terminal-state requirement, including required refusal data and malformed nonterminal-line handling; publish corresponding cases where needed. | Contract owner; JOURNAL |
| lifecycle-process-result | Completed runtime results bind actual invocation and owner-defined result evidence; publish the required invocation/result relationship. | Contract owner; WORKER/JOURNAL |
| identity-units | Unit IDs, snapshot and crosswalk provenance remain consistent across an attempt and its admitted envelope. | Contract owner; ENVELOPE/JOURNAL |
| identity-public-replay | Public-codec path joins attempt.envelope_digest to the admitted envelope and repeats sequential, concurrent and restart replay tests with fresh identities. | Contract owner; ENVELOPE/JOURNAL/WORKER |
| identity-journal-correlation | Resolve public status crosswalk and EC-JOURNAL-4 correlation mapping, respecting v2's lack of caller_context and prohibiting local fields. | Contract owner; JOURNAL |
| route-public-controls | Reconcile E-admitted, E-echo and E-dependency-declared effects with required write_scope, qualification and supported dependency routes; preserve standalone refusal. | Contract owner; ENVELOPE/WORKER |
| evidence-producer-binding | Resolve producer-owned evidence and verify its contents bind envelope, run and attempt; define coverage for both terminal result_binding and event evidence_envelope references. | Contract owner; JOURNAL/WORKER |
| proposal-attempt-independence | Equal proposal digests never transfer acceptance, deduplicate attempt evidence or establish freshness. Preserve separately proven baseline identity and per-attempt evidence; publish the baseline/result mapping. | Contract owner; WORKER/JOURNAL |

## Verification requirements

- The production validator supplies ECMA-262 pattern end-anchor behavior, without
  editing upstream bytes. Label local conformance negatives at all schema-declared
  sha256 positions. Source-copy controls cover pattern-keyword compatibility and
  every definition selector, with production path-entry witnesses.
- Vector expansion asserts every patch operation's effect, changed addressed value,
  specified rehash and the S-digest-not-rehashed relation. Source-copy helper controls
  must affect these assertions. Record all raw-line components without claiming
  that parsing them is semantic proof.
- Verify the artifact seal in the SCHEMA manifest frozen_inputs extension, production pin/blob
  table and the independent published SHA256SUMS anchor. Reference-integrity controls
  cover the entire closure and its metadata together. A separate hosted job fetches
  the frozen public commit and checks actual vendor bytes and blob IDs; its run/job/head
  and result artifact digest are required receipt evidence. Offline tests use no network.
- Record inputs are strict JSON bytes, with duplicate-key/nonfinite/exact-integer
  domain checks. Test finite numeric forms without coercing schema types; never
  infer canonical JCS byte identity from Python serialization. jsonschema/referencing
  API support is checked explicitly and unsupported runtimes refuse with code-only
  errors; dependencies remain unchanged in this phase.
- Coverage-pointer tests resolve the verified schemas and check each claimed absence.
  Receipt tests compare complete rule/entry/obligation sets and actual runner JUnit
  outcomes; node collection alone is insufficient. Runtime modules do not import
  the schema-only seam while byte-pin authority is false. Public API surfaces expose
  no test injection path. Errors and chains contain only approved code/resource data.
