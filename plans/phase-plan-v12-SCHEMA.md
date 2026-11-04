---
phase_loop_plan_version: 1
phase: SCHEMA
roadmap: specs/phase-plans-v12.md
roadmap_sha256: 192db96f3d99fdddff725519e818fe67520383610dac919f4b51542c2d7f9428
automation:
  suite_command: ["python3", "-m", "pytest", "-q", "phase-loop-runtime/tests", "-k", "supervised_contracts"]
---

# SCHEMA: Published schema intake

## Context

Implements only SCHEMA of agent-harness#1818. The roadmap EC IDs are the
acceptance authority. This plan is structurally validated but **execution is
blocked pending the public contract commit and digest inventory**. No source/schema bytes, tests
or builds are produced by this planning task.

The existing adapter, convergence log/projection, output retention and
executable-dependency startup were inspected for downstream compatibility.
SCHEMA adds only an offline package-resource loader and its conformance gate.
It never imports a private validator implementation or runs a provider.
Existing `jsonschema>=4,<5` supplies validation. The existing
`consiliency-contract>=0.6.5,<0.7` dependency and the conftest
`check_installed_contract_floor()` guard remain in place. Reuse its package
resources if they expose the pinned bytes and complete vector/resource closure;
the floor alone does not establish commit provenance. Otherwise vendor the
published files. The package currently includes `schemas/*.json`, so nested
vendored resources need an explicit package-data entry. Do not alter generated skill bundles.

## External Inputs

The owner selected public `Consiliency/consiliency-contract` as publisher of
the `admitted_launch_envelope.v1` and `supervised_run_status.v1` schemas and
conformance vectors only. Require a maintainer-selected published full commit
plus per-file sha256 covering both schemas, their referenced-resource closure,
vectors and expected outcomes. Neither commit nor digest inventory exists yet.

That absence is an explicit input gate. Do not invent an upstream revision or
write schemas, vectors or changes inside consiliency-contract. Pin by commit,
not tag; release/tag creation needs separate owner approval and is out of scope.
The intake records public provenance and validates bytes against the selected
commit and digest inventory before admitting them. No private source metadata
enters the repo. A dependency package lacking these resources is not permission
to relax validation or wait implicitly for an unapproved release: use the
byte-identical vendoring route at the published commit.

The roadmap hash in frontmatter binds this plan's existing input; it is not a
pin of future work. Publication of compatible inputs completes intake without
rewriting goals. A changed wire contract requires consumer reconciliation and
a roadmap/plan amendment before implementation.

## Interface Freeze Gates

- [ ] IF-0-SCHEMA-1 — Commit/sha256-pinned resources resolved through the existing contract
  dependency when suitable, otherwise vendored under
  `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/`,
  public `PROVENANCE.md` (repository and full commit) and `SHA256SUMS`
  retained at that harness path for either route, plus
  `supervised_contracts.py:load_contract_bundle` and
  `supervised_contracts.py:validate_record`; receipt at
  `plans/evidence/supervised-worker/SCHEMA.md`.

These are harness-local loader API names, not new wire types.
`load_contract_bundle()` returns an immutable verified bundle or raises a
typed local contract error. `validate_record(bundle, schema_id, record)`
returns only on conformance and otherwise raises a typed local validation
error. Schema IDs and resolver resources come solely from the pinned inventory.
No alternate acceptance model is defined in Python. Deny network resolution,
unlisted resources and path escapes; allow only pinned bundle-local references.

The receipt records input digests, vector identifiers/results, path-entered
mutation evidence and unresolved items. It is metadata, never route
qualification. Input gate closure requires a complete inventory and agreement
on lifecycle, tier names, bounds, projection and identity coverage; omissions
return to the external controller, without a substitute local schema.

## Lane Index & Dependencies

SL-0 — Public input intake and production loader
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no

SL-1 — Conformance and mutation corpus
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no

SL-2 — Freeze evidence and documentation reducer
  Depends on: SL-0, SL-1
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Public input intake and production loader

- **Scope**: Verify the public commit/content pin, resolve dependency or vendored resources and expose an offline loader.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/**`, `phase-loop-runtime/src/phase_loop_runtime/supervised_contracts.py`, `phase-loop-runtime/tests/test_supervised_contracts.py`, `phase-loop-runtime/pyproject.toml`, `phase-loop-runtime/uv.lock`
- **Interfaces provided**: `pinned_contract_bundle`, `load_contract_bundle`, `validate_record`
- **Interfaces consumed**: `published_contract_commit_and_sha256`, `jsonschema` (pre-existing)
- **Parallel-safe**: no
- **Tasks**:
  - test: Before production implementation, exercise the production loader API
    with missing inventory/resources, altered bytes, unknown schema ID, remote
    and escaping references. Include valid packaged-resource loading and
    public-safe provenance/inventory checks. Missing public publication stops
    before tests or vendor files are authored.
  - impl: Verify the selected public commit and expected per-file hashes.
    Inspect the existing dependency's package resources first. If all pinned
    bytes are present, reuse them; otherwise vendor byte-identical files from
    that commit, including vectors, and document the reason. Retain upstream
    resource IDs. Record the public repository, full commit and hashes in
    provenance for either route. Add the loader and immutable resolver; never
    fetch references at runtime or silently switch origins on a hash mismatch.
    Own the package-data edit here so consumers see the exact same resources
    from an installed package. Preserve the existing contract-floor check and
    version requirement; it does not need an upstream release for vendoring.
    Reuse installed jsonschema, with no new dependency. Reserve the lockfile for packaging metadata refresh only if required;
    otherwise leave it byte-identical. Do not add package-root exports.
  - verify: Run V0; then show that changing one vendored byte without updating
    its pinned sha256 fails the production loader. The tests must assert
    the actual loader path was entered; a test-local imitation is insufficient.

### SL-1 — Conformance and mutation corpus

- **Scope**: Exercise published positive and negative vectors through the production loader and validator.
- **Owned files**: `phase-loop-runtime/tests/test_supervised_contracts_mutations.py`
- **Interfaces provided**: `contract_conformance_receipt_inputs`
- **Interfaces consumed**: `pinned_contract_bundle`, `load_contract_bundle`, `validate_record`
- **Parallel-safe**: no
- **Tasks**:
  - test: Parameterize all pinned vectors and compare to pinned expectations,
    preserving negative/unknown results. Cover both wire families and their
    version/digest/identity/writer/seq/lifecycle/redaction fields as supplied.
    Wire validation cannot by itself prove journal ordering or launch behavior.
  - impl: Add reversible offline mutation controls at the production digest
    comparison and validator construction/call sites: suppressing the guard
    must make the negative corpus fail. Record a path-entered witness and
    assert nonempty positive and negative coverage for each schema family.
    Missing vectors block intake; do not write replacement golden vectors.
    Test-local malformed copies are allowed only as explicitly labelled
    mutation controls, never additions to the authoritative handoff.
  - verify: Run V1. Fail on surviving mutants, zero collection, skipped-only
    cases, blanket mocked validation or a control that never reached production.
    Mutants run in temporary copies or scoped monkeypatches and restore clean
    production code; SL-1 does not own SL-0's source.

### SL-2 — Freeze evidence and documentation reducer

- **Scope**: Reduce both producer lanes into a reproducible public-safe freeze record.
- **Owned files**: `docs/supervised-worker-contracts.md`, `plans/evidence/supervised-worker/SCHEMA.md`, `phase-loop-runtime/tests/test_supervised_contracts_freeze.py`, `CHANGELOG.md`
- **Interfaces provided**: `schema_freeze_receipt`
- **Interfaces consumed**: `pinned_contract_bundle`, `load_contract_bundle`, `validate_record`, `contract_conformance_receipt_inputs`
- **Parallel-safe**: no
- **Tasks**:
  - test: Add offline receipt consistency tests that call the production loader
    before checking documented schema IDs/digests and evidence references;
    stale or missing receipt input bindings must fail. A digest-bypass mutant
    must be caught even when the documentation looks internally consistent.
  - impl: Write provenance/use documentation and a metadata-only freeze receipt,
    consuming both producer outputs. Record commands, actual results, input
    digests and remaining blocked edges, without raw records or private context. Record whether dependency reuse
    was suitable and bind either choice to the same public commit/file pins.
    Record SCHEMA's spec delta and the user-visible package-resource capability.
    Do not mark future phases complete or claim this receipt qualifies a route.
  - verify: Run V2 and the full suite. Remove/alter a receipt input digest in a
    temporary copy and verify the consistency check fails after entering the
    loader. Finalize receipt evidence through the runner, not a fabricated pass.

## Execution Notes

All lanes are sequential; ownership has no overlap, including future files.
SL-0 owns shared packaging configuration. SL-2 depends explicitly on both
producers. No scheduler fanout, subagent or ambient worktree is authorized.
The complete touch set is above; existing `__init__.py`, generated
bundles and existing test companions stay unchanged. If published resources need
a new dependency or different ownership, amend the plan first.

Refusal metadata must not leak arbitrary input paths. Inspect incoming
provenance for public suitability before copying it. Runtime invariants beyond
schema conformance remain ENVELOPE/JOURNAL/WORKER duties. In particular, this
phase does not count JSON-schema success as proof of zero spawn, durability,
cancellation, liveness or provider enforcement.

Required future landing evidence is all six checks from CONTRIBUTING.md
(`suite gate`, `lint (pyflakes)`, `chronology retention guard`,
`docs-freshness audit`, `gitleaks`, `check`), dispatched Gate A on the exact
reviewed head, and a T3 cross-vendor board with correctness, red-team and
adversarial seats plus a separate president. The maintainer owns dispatch,
review and landing authorization. No push, PR, review delegation, CI dispatch,
live run or qualification happens in this planning task.

Operational evidence is recorded under
`plans/evidence/supervised-worker/SCHEMA.md` using runner-stamped amendments
after the actual head/check/review results exist. Do not pin future heads.
A proxy verdict needs a roadmap amendment. External delivery and review
readiness remain distinct from an implemented, offline-tested contract bundle.

## Verification

Use the locked Python 3.12+ test environment and absolute source/test
PYTHONPATH prescribed by CONTRIBUTING.md. The following commands are **future
execution verification**, not permission to run tests during planning.
Directory selectors intentionally resolve before new tests exist; pytest exit
5 (no tests) is failure, never proof. Each named lane must collect its intended
new tests; record collected node IDs, failures and mutation results.

V0:

```bash
python3 -m pytest -q phase-loop-runtime/tests -k "supervised_contracts and not mutations and not freeze"
```

V1:

```bash
python3 -m pytest -q phase-loop-runtime/tests -k supervised_contracts_mutations
```

V2:

```bash
python3 -m pytest -q phase-loop-runtime/tests -k supervised_contracts_freeze
```

Whole-phase regression (effective frontmatter suite):

```bash
python3 -m pytest -q phase-loop-runtime/tests -k supervised_contracts
```

Validate these argv and the effective suite with
`validate_verification_commands` (IF-0-VC-2), without executing them during
planning. Repeat path/selector validation at intake after tests exist. The
standard Gate A clean installed-wheel checks must also exercise this contract
corpus and resource inclusion before landing; they are not run here.
Tests/mutants use temporary resources, no network or provider, and report
multiple failures rather than stopping at the first.

## Acceptance Criteria

- [ ] EC-SCHEMA-1 — proven by `python3 -m pytest -q phase-loop-runtime/tests -k "supervised_contracts and not mutations and not freeze"`; falsified by digest-check bypass at `supervised_contracts.py:load_contract_bundle`, with a path-entered witness and tampered resource control.
- [ ] EC-SCHEMA-2 — proven by `python3 -m pytest -q phase-loop-runtime/tests -k supervised_contracts_mutations` and the whole-phase suite; falsified by validation bypass at `supervised_contracts.py:validate_record`, with a path-entered witness and the pinned negative corpus.
- [ ] EC-SCHEMA-3 — proven by `python3 -m pytest -q phase-loop-runtime/tests -k supervised_contracts_freeze` and the whole-phase suite; falsified by a stale receipt binding and production loader digest-bypass control after the loader has been entered.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `canonical_spec_update`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/schemas/supervised-worker-v1/**`, `docs/supervised-worker-contracts.md`
- evidence paths: `plans/evidence/supervised-worker/SCHEMA.md`
- redaction posture: `metadata_only`
- downstream handling: `none`

Missing/malformed evidence is a non-human `contract_bug`; absent published input
is `upstream_phase_unmet`. Neither permits a partial freeze. Once the gate
passes, the next plannable phases are ENVELOPE and JOURNAL; no downstream
implementation is authorized by this plan's mere existence.
