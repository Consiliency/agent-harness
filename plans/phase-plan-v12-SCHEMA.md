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

Detailed phase-four plan for agent-harness#1818 (Spec–Greenfield supervised
worker). The roadmap's EC-SCHEMA IDs remain the sole acceptance authority.
ENVELOPE landed through agent-harness#1828; its synthetic codec is not public
conformance. WORKER remains this phase's prerequisite. Planning neither changes
that edge nor activates the advisory v12 roadmap.

The published provisional contract is now available, but availability is not
adequacy. The input artifact below records missing launch coverage and divergent
tier annotations. IF-0-SCHEMA-1 stays unproduced until those questions are
resolved against EC-SCHEMA-3. A schema-valid negative is not a successful
semantic conformance result. This plan authorizes no provider execution,
controller implementation, upstream edit, release or local wire extension.

Inspected seams: supervised_launch.py, supervised_launch_binding.py,
conformance/outside_agent_imports.py, pyproject.toml package-data and the existing
ENVELOPE receipt. jsonschema is already a runtime dependency. The current
schemas/*.json package-data pattern does not include the new nested closure.

## External Inputs

- Public repository: Consiliency/consiliency-contract; full immutable commit in
  the frozen inventory below; root `core/supervised-run/`.
- Independently computed SHA256SUMS hash:
  `b9c2dad7ca32d32b9860e56c2e14141827955a50b52a54c8088760d9756e1285`.
- Frozen inventory and research findings:
  `plans/artifacts/v12-SCHEMA-inputs.md`. It records every fetched file's raw-byte
  sha256 and git blob id, branch-protection/ancestry observations, resource
  closure, vector routing and unresolved coverage. Expected values come from
  that reviewed inventory, checked against the published manifest; never bless
  newly fetched bytes by regenerating expected pins.

Vendor the six schema/vector/README/manifest files byte-identically. The seventh
file, upstream provenance.json, is inventoried by digest only: it is distribution
metadata, outside the schema reference closure, and embeds source-history
metadata excluded by the roadmap. Do not copy that content or sanitize it into
a purported byte-identical file. Supply public harness provenance separately.
No private inputs are fetched. Keep consiliency-contract>=0.6.5,<0.7 and its
conftest floor unchanged; dependency version alone is not provenance. Switching
to package resources or changing upstream bytes requires a reviewed amendment.

## Interface Freeze Gates

- [ ] IF-0-SCHEMA-1 — `supervised_contracts.py:load_contract_bundle`,
  `validate_record`, `ContractBundle`, `ContractError`; byte-identical resource
  closure under `schemas/supervised-worker-v1/`; public provenance and
  `plans/evidence/supervised-worker/SCHEMA.md` bound to the frozen inventory.

Harness-local API: load_contract_bundle() returns an immutable ContractBundle
or raises ContractError(code, resource), without network, subprocess or fallback.
validate_record(bundle, family, record, *, definition=None) returns normally
only for JSON Schema validity; otherwise raises ContractError with a stable
schema-validation code. It does not admit a launch or evaluate x-semantic-rules.
The closed families are admitted_launch_envelope.v1 and supervised_run_status.v1.
The latter defaults to journal_line and permits only projection, page_request,
page and reader_view as alternate definitions. Unknown selectors refuse.

Read each allowed resource once through importlib.resources, hash captured
bytes before parsing, and retain immutable bytes/private parsed validators.
Verify the complete allowlist against code-owned expected digests, including
SHA256SUMS and a digest-pinned harness provenance.json; the provenance file
cannot supply its own expected pins. Cross-check its public commit/blob inventory.
Missing files, mismatches, malformed manifests, unexpected resource names and
unlisted references refuse the entire bundle before returning a validator.
Reject duplicate JSON keys and nonfinite values. Do not reread a path for parsing
or expose mutable schema/registry objects that bypass verified snapshots.

Use Draft202012Validator and an offline registry with only verified schema IDs.
The published $refs are fragment-local; permit these plus listed IDs, deny all
other retrieval, including file/http/https URIs. The $schema annotation selects
the installed draft implementation, never a download. No environment override,
cwd discovery, editable expected-pin argument or latest-version fallback exists
in the production API. Tests inject resource readers privately.

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

- **Scope**: Vendor the approved public closure and build the fail-closed offline schema API.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`, `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/**`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/tests/test_supervised_contracts.py`
- **Interfaces provided**: `load_contract_bundle`, `validate_record`, `ContractBundle`, `ContractError`, `intake_results`
- **Interfaces consumed**: `jsonschema` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: First add tests for absent/altered bytes, manifest/provenance drift,
    unavailable resources, unknown family/definition, remote/unlisted refs,
    duplicate keys, mutable-return substitution and replacement between read
    and parse. Enter the production loader and assert refusal, not a test-only
    checksum helper. Cover installed package resources as well as source files.
  - impl: Fresh-fetch the pinned commit from the canonical public repository;
    verify protected-default-branch ancestry and every expected raw digest/blob.
    Vendor only the approved six files with their relative layout preserved.
    Add harness provenance.json naming the public source, full commit, file
    hashes/blob ids and explicitly excluded distribution metadata. Freeze its
    expected hash in the loader after review. Implement the frozen API and add
    schemas/supervised-worker-v1/** to package-data. Keep unrelated dependencies,
    lockfile, init modules and generated skill bundles unchanged.
  - verify: Run V0; record individual failure cases and same-buffer witnesses.
    Hosted packaging verification must build/extract the wheel into scratch
    and run V0 with the extracted package ahead of the source checkout; assert
    module/resource provenance and identical vendored bytes. No package-version
    change or release dispatch is part of this phase.

### SL-1 — Schema corpus and mutation proof

- **Scope**: Exercise pinned structural cases and inventory every deferred semantic obligation.
- **Owned files**: `phase-loop-runtime/tests/test_supervised_contracts_vectors.py`, `phase-loop-runtime/tests/test_supervised_contracts_mutations.py`
- **Interfaces provided**: `schema_results`, `semantic_inventory`, `mutation_results`
- **Interfaces consumed**: `load_contract_bundle`, `validate_record`, `ContractBundle`, `ContractError`, `intake_results`
- **Parallel-safe**: no
- **Tasks**:
  - test: Parameterize every published case ID: 16 envelope and 35 status cases.
    Expand negative patches from their named controls using RFC 6901/6902;
    preserve raw torn-line strings and final-newline flags. Apply rehash only as
    specified, using the vectors' restricted ASCII/integer JCS domain. Project
    envelopes, parseable journal lines, projection, request/page and reader_view
    objects into the appropriate schema definition; never validate the wrapper
    as a record or silently drop a component. Malformed raw lines stay semantic
    obligations, not invented schema failures. Add labelled local structural
    negatives for required fields, wrong types and closed enums/properties in
    both families. Do not alter the published vectors.
  - impl: Keep patch/extraction helpers test-local; validate_record remains JSON
    Schema only. Inventory each expected diagnostic/effect with its exact case
    ID, component mapping, producer owner and unresolved upstream_phase_unmet
    status for CLOSEOUT. All published semantic negatives must remain structurally
    valid where a JSON object exists. Do not count that result as proof of their
    expected diagnostic. Include the positive controls' deferred runtime effects.
    Explicitly pair S-evidence-copied with V-two-attempts: copied evidence-envelope
    digest requires attempt_evidence_copied; identical proposal bytes with
    distinct evidence, envelope, run and attempt provenance remain legitimate.
    Also retain N20-raw-stdout-ref and N18-run-status-as-evidence to distinguish
    inline evidence/output from producer-owned references and work authority.
  - verify: Run V1 then V2. Mutate the production digest comparison and
    Draft202012 validation invocation separately; each previously passing test
    must fail with a path-entered witness. Also bypass the offline resolver,
    allowlist and captured-buffer parsing separately. For resolver mutation,
    inject a synthetic resource behind a controlled verified-read seam so the
    digest guard cannot mask whether reference denial was entered. Restore each
    mutant before the next run. Semantic bypass mutants belong to the actual
    ENVELOPE/JOURNAL/WORKER paths in CLOSEOUT, never a parallel semantic model.

### SL-2 — Contract documentation and receipt reducer

- **Scope**: Reconcile both producers into public documentation and an honest metadata-only gate receipt.
- **Owned files**: `docs/supervised-worker-contracts.md`, `plans/evidence/supervised-worker/SCHEMA.md`, `phase-loop-runtime/tests/test_supervised_contracts_receipt.py`
- **Interfaces provided**: `plans/evidence/supervised-worker/SCHEMA.md`
- **Interfaces consumed**: `intake_results`, `schema_results`, `semantic_inventory`, `mutation_results`, `load_contract_bundle`, `validate_record`
- **Parallel-safe**: no
- **Tasks**:
  - test: Test receipt bindings against the production loader, actual per-node
    results and the complete case inventory. Omitted S-evidence-copied or
    V-two-attempts, a semantic case relabelled satisfied by schema validity,
    missing mutation evidence or an unresolved coverage blocker labelled passed
    must fail. Enter production before falsifying a temporary receipt binding.
  - impl: Document the APIs, package resource closure and exact input pins.
    Record coverage of instruction/reference, argv, executable/dependency
    identity, workspace source/baseline, timeout, tiers, lifecycle, identity,
    projection and bounds using public JSON pointers or explicit absence.
    Track input-artifact questions individually, preserve unresolved semantic
    ownership and withhold IF-0-SCHEMA-1 while coverage is inadequate. Actual
    outcomes, module provenance, nodes and mutants are runner-stamped here;
    never prefill passes or predicted repository heads. No-doc-change decision:
    CHANGELOG/README/release notes remain current because this internal schema seam adds no user CLI or
    release; WORKER owns integrated-feature documentation. No UI is introduced.
  - verify: Run V3 and the effective phase suite. Check the receipt rejects
    stale input/results and false readiness. Confirm both producer lanes are
    consumed and no unresolved question was replaced with an invented wire key.

## Verification

V0–V3 and the effective suite are future implementation commands, not run by
this planning task. Use locked Python 3.12+ with absolute checkout source/test
PYTHONPATH per CONTRIBUTING.md. Check uptime, free -g and /proc/pressure/io
before each command; stop if degraded. Run serially under timeout, with -n 0
and no cacheprovider; no full local suites, make check or unbounded parallelism.

- V0: `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts.py`
- V1: `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_vectors.py`
- V2: `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_mutations.py`
- V3: `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_receipt.py`

The frontmatter suite runs exactly these four owned files, serially, and is the
whole-phase regression command. Collect each file individually after creation;
require every required case and mutant, no missing/skipped-only nodes or exit 5.
Report multiple failures; flag proof cost above roughly five minutes on one node.

Validate all four argv lists and automation.suite_command through
verification_evidence.validate_verification_commands (IF-0-VC-2). Planning must
record missing future test paths honestly; repeat after implementation and
require zero findings before execution handoff. Do not create empty test files
or use whole-repository collection to manufacture a pass.
Hosted CI owns full regression, wheel packaging proof and the repository's six
required checks. CLOSEOUT owns observed-head Gate A and independent review.
Operational evidence is recorded through runner-stamped amendments to the SCHEMA
receipt; proxy evidence requires a roadmap amendment. No future SHA/count is
an acceptance condition.

## Acceptance Criteria

- [ ] EC-SCHEMA-1 — proven by `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts.py`; falsified by digest-comparison bypass at production load_contract_bundle with path-entered tampered-resource refusal assertions.
- [ ] EC-SCHEMA-2 — proven by `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_vectors.py phase-loop-runtime/tests/test_supervised_contracts_mutations.py`; falsified by production validate_record validation bypass with path-entered structural-negative assertions and a semantic case falsely marked satisfied.
- [ ] EC-SCHEMA-3 — proven by `timeout 300 python3 -m pytest -q -n 0 -p no:cacheprovider phase-loop-runtime/tests/test_supervised_contracts_receipt.py`; falsified by stale input/result bindings or uncovered launch inputs marked accepted after entering production load_contract_bundle and validate_record.

## Execution Notes

Owned-file sets are disjoint; SL-0 owns shared package metadata, SL-2 consumes
both producer lanes. All lanes are sequential; no subagents or worktree fanout.
Do not edit the roadmap, ENVELOPE implementation, journal/worker code, installed
contract package, conftest, dependency locks or generated bundles. In particular,
phase-loop-runtime/uv.lock stays untouched because only package-data discovery
changes, with no dependency/version/resolution change; check (R) is advisory.
The input
artifact is read-only; upstream repair requires an explicit plan/input amendment.
No post-dispatch reducer is needed; package-data ownership is not a release.

Next phase: SCHEMA - blocked: WORKER prerequisite, unresolved public coverage,
and future verification paths; advisory activation is a separate owner decision.
Next command: none - preserve prerequisites and resolve public coverage first.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/`, `docs/supervised-worker-contracts.md`
- evidence paths: `plans/evidence/supervised-worker/SCHEMA.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

Malformed evidence is a repairable contract_bug; unresolved upstream coverage
is upstream_phase_unmet. Neither can be waived by a schema-only green run.
