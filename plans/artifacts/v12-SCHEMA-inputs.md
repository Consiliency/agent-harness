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
A separately reviewed harness provenance.json will itself be digest-pinned in
supervised_contracts.py. The implementation receipt must distinguish that
harness metadata from the byte-identical upstream files.

## Coverage findings that prevent premature gate completion

| Finding | Public evidence | Required disposition |
| --- | --- | --- |
| Launch payload coverage | Envelope /properties and closed /additionalProperties contain no instruction bytes/reference, argv, executable/wrapper identity, workspace source or timeout. /workspace has only kind and repo_relative_locators; /units/snapshot_ref is opaque. | Upstream contract owner must resolve how every launch-determining input is bound. No invented fields or caller_context side channel; IF-0-SCHEMA-1 remains blocked under EC-SCHEMA-3. |
| Tier basis | Envelope /x-enforcement-tiers marks local tiers qualified and provider write_scope checked_before_apply; roadmap matrix marks required write_scope unsupported and requires installed-tool qualification. | Reconcile upstream semantics with harness obligations; annotations alone cannot qualify a provider or silently relax the roadmap. |
| Attempt identity | Envelope has no explicit run_id/attempt_id or version property; status /$defs/attempt_identity and journal_line carry their own identity/version shape. | CLOSEOUT must reconcile the trusted codec/local API and bind identity; no public codec is wired in SCHEMA. |
| Lifecycle and bounds | Status /x-journal-rules declares lifecycle, liveness, page/event/attempt limits. Many are semantic annotations; page_size and version are deliberately weak structurally. | Inventory JOURNAL/WORKER production obligations, including all four numeric limits, rather than declaring schema validation sufficient. |
| Provisional distribution | Both schemas and vector files declare provisional status. | Treat this revision as a pinned input, not authoritative runtime readiness. Future changes need reviewed consumer reconciliation and explicit repinning. |
| Maintainer inventory | Published SHA256SUMS pins five files; the owner supplies the public commit and manifest prefix; independent full hashes/blob ids are recorded above. | Confirm whether the owner considers this reviewed publication sufficient for the roadmap's maintainer inventory requirement; do not claim signed provenance. |

The missing launch coverage already prevents a passing byte-pin gate even if
all hash checks pass. Resolve upstream and amend these frozen inputs if necessary;
never manufacture local wire extensions. WORKER is still the declared SCHEMA
prerequisite; this planning artifact does not amend ordering or registry state.

## Structural and semantic evidence separation

The public README says every patched negative is schema-valid by construction.
There are 16 envelope cases (4 controls, 12 negatives) and 35 status cases
(7 controls, 28 negatives). The case table below records original IDs and
expected diagnostics, not observed semantic results. Every row remains
unresolved upstream_phase_unmet for runtime proof, including controls' effects.
SCHEMA tests project structural components and add explicitly local structural
negatives; those local cases do not become upstream vectors.

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
