---
phase_loop_plan_version: 1
phase: SCHEMA
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 8aea5fbcb0a8caa2b75d51ecb0147bd6f0e9e7db9bdeb9e58988d09bf12fdf2d
automation:
  suite_command: ["timeout", "300", "python3", "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "phase-loop-runtime/tests/test_supervised_contracts.py", "phase-loop-runtime/tests/test_supervised_contracts_vectors.py", "phase-loop-runtime/tests/test_supervised_contracts_mutations.py", "phase-loop-runtime/tests/test_supervised_contracts_receipt.py"]
---

# SCHEMA: Published schema intake

## Context

Detailed phase-four plan for agent-harness#1818. The roadmap EC-SCHEMA IDs remain
acceptance authority. ENVELOPE landed through agent-harness#1828. The owner
authorizes manual SCHEMA execution now against frozen v1; the roadmap WORKER
edge still governs automatic selection, not these independent intake lanes.
Advisory registry status and the roadmap DAG remain unchanged.

IF-0-SCHEMA-1 records completion of the v1 loader, verified six-file closure and
receipt. Its distinct byte_pin_authority field remains false pending published
v2 and coverage reconciliation. Coverage/identity obligations and absent future
test files are not work-start blockers. Schema validity is not semantic proof.
No provider execution, controller implementation, upstream edit, release or
local wire extension is authorized by this phase.

Inspected seams: supervised_launch.py, supervised_launch_binding.py,
conformance/outside_agent_imports.py, pyproject.toml and the ENVELOPE receipt.
The current schemas/*.json package-data pattern needs the nested closure.

## External Inputs

Public repository: Consiliency/consiliency-contract; full immutable v1 commit and
all seven raw-byte hashes/blob IDs are in `plans/artifacts/v12-SCHEMA-inputs.md`.
Root: `core/supervised-run/`. Independently verified SHA256SUMS hash:
`b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285`.
The owner accepts the verified publication as the maintainer inventory.

The SCHEMA manifest entry's frozen_inputs extension seals this artifact's
SHA-256. V0 verifies the seal, production pin/blob table and an independent
literal SHA256SUMS anchor against the frozen table. Expected values come from
reviewed inputs, never from regenerating the payload under verification.

Vendor the six schema/vector/README/manifest resources byte-identically,
preserving relative names. Upstream provenance.json is inventoried by digest
only, outside the reference closure; its source-history content is excluded.
Name the separate harness-authored metadata harness-provenance.json, explicitly
outside the upstream six-file set. No private inputs are fetched or published.
Keep consiliency-contract>=0.6.5,<0.7 and its conftest floor unchanged.
Importing these schemas from the installed consiliency-contract distribution
requires an amendment; importlib.resources inside phase_loop_runtime is the
required vendored loader. Changed upstream bytes require reviewed repinning.

## Interface Freeze Gates

- [ ] IF-0-SCHEMA-1 — supervised_contracts.py exports load_contract_bundle,
  validate_record, ContractBundle.resource_bytes and ContractError; verified
  resources live under schemas/supervised-worker-v1/; public harness provenance
  and plans/evidence/supervised-worker/SCHEMA.md complete the intake freeze.
  The receipt separately records byte_pin_authority=false for this v1 intake.

load_contract_bundle() returns an immutable ContractBundle or raises
ContractError(code, resource). bundle.resource_bytes(name) returns captured
immutable bytes for an exact allowlisted name. validate_record(bundle, family,
record: bytes, *, definition=None) strictly parses JSON, returning None only for
schema validity. It implements no launch admission or x-semantic-rules.
Families: admitted_launch_envelope.v1 and supervised_run_status.v1. Envelope
permits only definition=None; status defaults to journal_line and also permits
projection, page_request, page and reader_view. Other selectors refuse.

Closed error codes: resource_missing, digest_mismatch, manifest_invalid,
resource_unlisted, reference_unlisted, resource_json_invalid, schema_invalid,
runtime_unsupported, selector_invalid, record_json_invalid, record_schema_invalid.
resource is an allowlisted name or None. Messages contain only code/resource;
translate underlying exceptions with raise ... from None. Instance values and
nested exception text must not enter errors, logs or receipt metadata.

Read each resource once; hash and parse identical captured bytes. Compare the
complete allowlist with code-owned expected digests and sealed input identities,
including SHA256SUMS and separately named harness-provenance.json. Metadata
cannot provide its own expected pin. Strict JSON parsing applies to resources
and record bytes: reject duplicate keys, nonfinite numbers and integers outside
[-9007199254740991, 9007199254740991]. Preserve finite numbers without coercing
schema types. Parsed Python objects are not accepted by the public record API;
these intake conditions are distinct from JSON Schema semantics.

Use Draft202012Validator with ECMA-262 pattern end-anchor semantics without
changing vendor bytes. Every schema-declared sha256 position accepts exactly
64 lowercase hex characters. The production pattern compatibility and every
relevant position must have conformance tests. Resolve only verified IDs/local
fragments in an offline registry. Before construction, check registry API
support: jsonschema before 4.18 or unavailable compatible referencing yields
runtime_unsupported, with no legacy resolver. The dependency floor/lock remains
unchanged; increasing the floor requires a separate amendment. No public
injection argument, mutable validator escape or environment/cwd override exists.

intake_results, schema_results and mutation_results are runner evidence groups,
not extra APIs. Rows carry group, test_node_id, case_or_control_id,
resource_sha256, outcome and runner_artifact_ref. semantic_inventory rows carry
id, source_pointer, vector_ids, owner, status and required_proof. SL-2 serializes
these metadata-only groups in plans/evidence/supervised-worker/SCHEMA.md, with
input_artifact_sha256, suite_artifact_sha256, hosted_run_id and byte_pin_authority.
Outcomes must match runner-produced JUnit node/results and artifact digest,
plus hosted run/job/head identity where applicable. Collection is not outcome
proof. Intermediate JUnit remains runner-owned scratch, not a tracked artifact.
A separate post-suite stamp step compares that JUnit with the rows, then writes
its digest. V3 always checks row shape and completeness; it compares the artifact
only in the stamp step, where a missing artifact fails. The digest describes the
suite run before the stamp, never a later head.

## Lane Index & Dependencies

SL-0 — Pinned resource intake and loader
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Schema corpus and mutation proof
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no

SL-2 — Contract documentation and receipt reducer
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Pinned resource intake and loader

- **Scope**: Vendor the approved closure and build the fail-closed offline schema API.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/**`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/tests/test_supervised_contracts.py`, `phase-loop-runtime/scripts/verify_supervised_contract_publication.py`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/tests/test_agy_self_qualification.py`, `.github/workflows/supervised-contract-intake.yml`, `.gitleaks.toml`
- **Interfaces provided**: `load_contract_bundle`, `validate_record`, `ContractBundle`, `ContractError`, `resource_bytes`, `intake_results`
- **Interfaces consumed**: `jsonschema` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Exercise missing/altered resources, manifest/provenance integrity,
    every selector, offline resolution, duplicate/nonfinite JSON, strict record
    intake and immutable same-buffer parsing through the production API. Assert
    closed codes and sanitized exception chains using sentinel-bearing records.
    Verify artifact seal, production hashes/blob IDs and independent manifest
    anchor. Include source-copy reference-integrity controls and installed
    package resources. Reference-integrity controls cover the entire closure, its
    metadata and the code-owned expected pins together. With all of them regenerated
    consistently, the anchor assertion against the unmodified sealed artifact must
    still fail. Test hosted comparison logic offline in V0.
  - impl: Fresh-fetch the canonical pinned commit; verify protected-default-branch
    ancestry and every expected raw digest/blob. Vendor the six approved files.
    Add harness-provenance.json naming public source, full commit, hashes/blob IDs
    and excluded metadata; freeze its expected digest in the loader. Implement
    the APIs, pattern compatibility and runtime support check. Add the nested
    package-data glob. Keep dependencies, lockfile, init and generated bundles
    unchanged. If gitleaks requires it, add only narrow path/digest allowlists,
    preserving vendor bytes. Add a network-enabled hosted publication workflow
    and script with the required `supervised contract publication` check, run on
    every pull_request and every push to main with no path filter. The check is a
    successful no-op on non-contract changes, using the exact contract path set
    pinned in the workflow, including vendored resources, the loader, packaging
    declarations, and seal/anchor owners. For contract changes, independently
    fetch the pinned commit, re-verify protected-default-branch ancestry, and
    compare vendor bytes/blobs and sealed inventory, failing closed on any error
    or difference. A red contract run blocks the receipt and landing; ordinary
    tests remain offline. The owner adds the check to branch protection after
    merge; implementation does not change repository settings.
  - verify: Run V0. The hosted job runs the publication script, records branch
    provenance and observed run/job/head, and fails on any comparison difference.
    Hosted packaging verification builds/extracts the wheel to scratch and runs
    V0 with the extracted package ahead of the source checkout. Assert actual
    module/resource origins and identical bytes. No version bump or release.

### SL-1 — Schema corpus and mutation proof

- **Scope**: Exercise pinned structural cases and inventory every semantic obligation.
- **Owned files**: `phase-loop-runtime/tests/test_supervised_contracts_vectors.py`, `phase-loop-runtime/tests/test_supervised_contracts_mutations.py`
- **Interfaces provided**: `schema_results`, `semantic_inventory`, `mutation_results`
- **Interfaces consumed**: `load_contract_bundle`, `validate_record`, `ContractBundle`, `ContractError`, `resource_bytes`, `intake_results`
- **Parallel-safe**: no
- **Tasks**:
  - test: Consume vectors only through resource_bytes; compare case IDs with the
    frozen artifact (16 envelope, 35 status). Expand RFC 6901/6902 patches from
    named controls, asserting every declared pointer effect and a changed value.
    Assert specified rehash results and S-digest-not-rehashed's expected digest
    relation using the corpus's ASCII/integer JCS domain. Preserve raw lines and
    final-newline flags. Map all components to the proper definitions; malformed
    raw lines remain semantic obligations. Add labelled structural negatives for
    each definition and nested reference, including every sha256-typed position.
  - impl: Keep extraction/patch helpers test-local. All parseable published
    semantic negatives remain structurally valid; that proves no diagnostic.
    Inventory the union of all x-semantic-rules codes, all x-journal-rules entries
    and named coverage obligations in the artifact, each mapped to zero or more
    vectors. Zero-vector rows remain unresolved upstream_phase_unmet and withhold
    byte-pin authority, not SCHEMA execution. Include controls' runtime effects.
    Preserve S-evidence-copied and V-two-attempts as the evidence/identity pair,
    plus N20-raw-stdout-ref and N18-run-status-as-evidence. Producer evidence,
    baseline identity and acceptance remain independently bound per attempt.
  - verify: Run V1 then V2. Require path-entered production controls for digest,
    validation, selector, pattern compatibility, offline resolution, allowlist
    and captured-buffer parsing. Include reference-integrity and patch-expansion
    controls. Use isolated source copies; no public API permits test injection.
    Each control must change a passing assertion to failure. Restore each copy
    independently. Semantic controls belong to actual runtime paths at CLOSEOUT.

### SL-2 — Contract documentation and receipt reducer

- **Scope**: Reconcile both producers into documentation and an accurate authority receipt.
- **Owned files**: `docs/supervised-worker-contracts.md`, `plans/evidence/supervised-worker/SCHEMA.md`, `phase-loop-runtime/tests/test_supervised_contracts_receipt.py`, `CHANGELOG.md`
- **Interfaces provided**: `plans/evidence/supervised-worker/SCHEMA.md`
- **Interfaces consumed**: `intake_results`, `schema_results`, `semantic_inventory`, `mutation_results`, `load_contract_bundle`, `validate_record`
- **Parallel-safe**: no
- **Tasks**:
  - test: Compare receipt bindings with production loader observations, actual
    JUnit/run evidence and the complete schema-derived rule/entry inventory.
    Require every named obligation and case, correct schema-only classifications
    and false byte-pin authority. Resolve coverage pointers and verify asserted
    absences in captured schemas; opaque context/snapshot/obligation fields do not
    establish launch coverage. Enter production before temporary receipt controls.
    Check no production launch/journal module imports supervised_contracts while
    byte_pin_authority is false. Missing or skipped required results fail.
  - impl: Document APIs, pins, all coverage dimensions and owner decisions from
    the artifact. Produce IF-0-SCHEMA-1 for completed intake, recording
    byte_pin_authority=false until published v2 and identity/lifecycle/evidence
    obligations are reconciled. Bind actual node/control outcomes and module
    provenance to runner evidence; never prefill outcomes or predicted heads.
    Add one CHANGELOG.md Unreleased entry for the new hosted contract-intake
    workflow (docs-audit treats workflows as release surfaces); README and release
    notes stay unchanged because this internal seam adds no public CLI or release.
    WORKER owns integrated feature documentation. No UI is introduced.
  - verify: Run V3 and the effective phase suite; verify both producer groups,
    coverage inventory and evidence bindings. Require accurate withheld authority
    independently of successful schema tests. No local wire additions are made.

## Verification

V0–V3 and the frontmatter suite are future implementation commands. Use locked
Python 3.12+ and absolute checkout source/test PYTHONPATH per CONTRIBUTING.md.
Check uptime, free -g and /proc/pressure/io before each command; stop if degraded.
Run serially under timeout, -n 0 and no cacheprovider. No full local suites,
make check or unbounded parallelism.

- V0: `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts.py`
- V1: `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_vectors.py`
- V2: `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_mutations.py`
- V3: `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_receipt.py`

The effective whole-phase suite runs exactly these four owned files serially.
Collect each individually after creation; require every case/control, with no
missing/skipped-only required nodes or exit 5. Report multiple failures; flag
proof cost exceeding roughly five minutes on one node.

Validate all argv and automation.suite_command through
verification_evidence.validate_verification_commands (IF-0-VC-2). Missing paths
owned by these lanes are expected pre-implementation state, not a work-start
blocker. Repeat after creation and require zero findings before verification and
closeout. Do not create empty tests or use whole-repository collection.
Hosted CI owns publication comparison, wheel proof, full regression and the
required checks, including `supervised contract publication`, which is a
successful no-op on non-contract changes.
CLOSEOUT owns observed-head Gate A and independent review.
Runner-stamped receipt amendments bind JUnit artifacts and hosted run/job/head
identities. Proxy evidence requires a roadmap amendment. No future SHA/count
is an acceptance condition.

## Acceptance Criteria

- [ ] EC-SCHEMA-1 — proven by `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts.py`; falsified by a path-entered production load_contract_bundle reference-integrity control failing its refusal assertion.
- [ ] EC-SCHEMA-2 — proven by `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_vectors.py phase-loop-runtime/tests/test_supervised_contracts_mutations.py`; falsified by path-entered production validate_record pattern/selector controls or incorrect schema-only evidence classification.
- [ ] EC-SCHEMA-3 — proven by `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_receipt.py`; falsified by incorrect receipt bindings or byte_pin_authority after entering production load_contract_bundle and validate_record.

## Execution Notes

File sets are disjoint: SL-0 owns shared package/workflow configuration; SL-2
consumes both producers. All lanes are sequential, with no subagents or worktree
fanout. ENVELOPE, journal/worker, conftest, dependencies and generated bundles
stay untouched. phase-loop-runtime/uv.lock stays unchanged because only package
data changes; check (R) is advisory. The input artifact and its manifest seal
are read-only execution inputs. No release dispatch or post-dispatch reducer
is needed; package-data ownership accounts for check (N).

Next phase: SCHEMA - execution ready for owner-authorized manual v1 intake.
Next command: codex-execute-phase plans/phase-plan-v12-SCHEMA.md.

## V2 follow-up in CLOSEOUT

Plan a separate sequential reconciliation lane after reviewed v2 publication and
inventory from a squash-merged consiliency-contract PR; no tag is required. Pin
no v2 revision/digest yet. The follow-up covers supervised_launch.py,
supervised_launch_binding.py, their launch/binding/route/mutation/receipt tests,
public fixtures, supervised-worker documentation and CLOSEOUT evidence. Its
execution plan must enumerate journal/worker integration companions before
writing them. This future lane does not delay current SCHEMA work.

The owner-defined v2 binds instruction/reference digests, argv as SHA-256 of the
UTF-8 RFC 8785 JCS array, executable/wrapper identity, workspace source and integer
seconds in [1, declared_bound], with declared_bound <= 3600. Reconcile effective
environment, trusted policy/qualification, action/route/delivery and conditional
execution-view/egress grants through digest/references, keeping host details local.
Tier annotations confer no provider qualification. v2 has no caller_context or
harness-local fields. Explicitly reconcile the exact-key ENVELOPE seam, preserving
v1 bytes and conservative tier/dependency guards. Use the artifact's public-codec
identity/replay, lifecycle and evidence obligations before granting authority.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/`, `docs/supervised-worker-contracts.md`
- evidence paths: `plans/evidence/supervised-worker/SCHEMA.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

Malformed evidence is a repairable contract_bug. Unresolved coverage/semantic rows
retain upstream_phase_unmet for subsequent authority decisions; they do not
block v1 execution or an accurate false-authority receipt.
