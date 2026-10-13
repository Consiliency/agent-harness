---
phase_loop_plan_version: 1
phase: HARDEN
roadmap: specs/phase-plans-v11.md
roadmap_sha256: be453ea57c7fe77c0f16f2af0e47158440cb2b0241fa65794292464556a8fa3c
automation:
  suite_command:
    - uv
    - run
    - --quiet
    - --with
    - pytest
    - --with-editable
    - ./phase-loop-runtime
    - python
    - -m
    - pytest
    - -q
    - phase-loop-runtime/scripts
    - phase-loop-runtime/tests
---

# HARDEN: Isolation and Verification Hardening

## Context

Finish the carried SL-6 completion seal and EC-HARDEN-6 under v11 Phase 5.
EC-HARDEN-0 retains its V10 definition. EC-HARDEN-1 through EC-HARDEN-4 and
SL-5 are delivered; EC-HARDEN-5 is retired by v11. The roadmap currently declares
no phase dependencies; completion-admission routing remains unresolved below.
Do not import the old FABPUB/SCHED dispatch holds or author-vendor rotation.

The current verifier's `manifest_plan_row` selects by alias alone;
`verify_authority_paths`, `git_bound_review_input`, suite/ownership readers and
the producer's `_prepare_stage` bind the v10 plan. Its `verify_broker` rejects
tooled records through `harden5_unmet`. Historical checks remain meaningful,
but those assumptions cannot govern v11 completion.

Canonical `.phase-loop/` exists and owns runner state. This planning checkout
contains the active planning run but no local state/events snapshot; absence
does not authorize reconstructing state from `.codex/phase-loop/`.
The tracked v10 HARDEN row is terminal `orphaned`. Preserve it and append
completion only to the v11 row.

## External Inputs

- `plans/phase-plan-v10-HARDEN.md`, SHA-256
  `d3e6860ba91156194769a6a91d547043e64d5f7031036c2e8dcb474d59a4292b`,
  is the frozen predecessor plan. Its historical SL-0/SL-4 inventories, reviewed
  boundaries and repair authorities are inputs, not new implementation tasks.
- V10 goal definitions use the external V10 revision declared by the v11
  roadmap. Resolve historical authority at its recorded Git revision, including
  the pre-supersession roadmap bytes; do not require today's bannered v10
  roadmap to match an old authority digest.
- Existing manifest lifecycle, `sl0_repairs`, retained reviews and receipts
  remain byte-bound provenance. Derive subsequent candidate/main identities,
  inventories and counts from actual evidence; prescribe no future SHA,
  commit count or topology.

## Interface Freeze Gates

- [ ] IF-0-HARDEN-5 — Active authority is selected by phase alias, plan path and
  roadmap identity, bound to Git blobs and the pinned roadmap digest. The
  v11 row is unique and eligible for the current lifecycle stage; historical
  v10 queries explicitly select their predecessor row/revision. Missing,
  duplicate, stale or wrong-roadmap authority fails closed.
  For v4 reviews, use paired `harden_review_instructions.v2` and
  `harden_review_bundle.v2` envelopes: single-line ASCII JSON, sorted keys,
  compact separators, escaped string contents and one terminal LF. Both bind
  `base_head`, `base_tree`, `head`, `tree`. Instructions contain the v11 plan
  path, base-revision blob, SHA-256, byte length, full decoded plan text and
  profile-compatible review directives; the bundle contains the complete Git
  patch, its SHA-256/byte length and the raw-blob-delta SHA-256/byte length.
  These use the runtime's ordinary-text path, without reserved v3 headers or
  inner broker frames. Existing inline/pointer renderers supply outer framing.
  The v4 verifier independently reconstructs both JSON inputs from Git and
  reproduces `provider_input_sha256` through those production renderers.
  Preserve the byte-identical v3 grammar and its v10 pin; never relabel v11
  bytes as v10 or use the retired plan as v11 review authority.
- [ ] IF-0-HARDEN-6 — Add `harden_evidence_inputs.v2` and HARDEN's
  `verification_evidence.v4` for EC-HARDEN-6. Freeze their closed field sets
  in `plans/evidence/v11-HARDEN-contract.md` before implementation.
  Bind declared seat capabilities, actual profile/filter/owner-argv digests,
  operation authorization and verdict disclosure to retained runtime evidence.
  Keep `harden_evidence_inputs.v1`, `verification_evidence.v3` and direct
  legacy `verify_broker` behavior unchanged. Unknown versions and mixed
  contracts fail closed; this is not a change to runner `verification.json`.
- [ ] IF-0-HARDEN-7 — Existing `prepare`, `seal` and verifier CLI arguments
  will select the new version explicitly through input schema selection. Preparation
  produces an independently verifiable pre-completion aggregate and request;
  sealing binds exactly one matching canonical event without changing the
  normalized pre-completion digest. Do not freeze this gate until the admission
  decision in Execution Notes is resolved. Then freeze `harden_completion_request.v2`
  and `harden_completion.v2` payloads, preserving v1. The request/event binds v11 authority as
  well as candidate/main evidence; v10 completion cannot satisfy it.

## Lane Index & Dependencies

SL-6 — Evidence migration, docs sweep and completion reducer
  Depends on: (none)
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-6 — Evidence migration, docs sweep and completion reducer

- **Scope**: Repair v11 evidence selection, prove EC-HARDEN-6, then reduce verified retained evidence into canonical completion.
- **Owned files**: `phase-loop-runtime/scripts/verify_harden_evidence.py`, `phase-loop-runtime/scripts/build_harden_evidence.py`, `phase-loop-runtime/scripts/test_v11_harden_evidence.py`, `plans/phase-plan-v11-HARDEN.md`, `plans/manifest.json`, `plans/evidence/v11-HARDEN-contract.md`, `plans/evidence/v11-HARDEN-closeout.md`, `plans/evidence/v11-HARDEN/*.json`, `plans/evidence/v11-HARDEN/*.jsonl`
- **Interfaces provided**: IF-0-HARDEN-5, IF-0-HARDEN-6, IF-0-HARDEN-7.
- **Interfaces consumed**: predecessor plan (pre-existing), historical SL-0/SL-4 receipts (pre-existing), seat profile and authorization records (pre-existing), canonical runner ledger (pre-existing), external reuse registry (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: First freeze the contract and new regression corpus in
    `scripts/test_v11_harden_evidence.py`; this scripts-local location respects
    the roadmap's scripts/plans boundary and leaves landed tests immutable.
    Require a separate tests-only landing on canonical main with exact-head
    board approval and genuine RED results before production edits. Record
    the approved tests-only landing head; production must descend from it.
    Freeze the test bytes; the implementation PR must contain no test diff.
    Use source-entered controls, not missing-import or collection errors, as RED.
  - test: Exercise production `manifest_plan_row`, authority/input-envelope
    readers and `derive_live_facts` with orphaned v10 plus live v11 rows.
    Reject two live matches, wrong plan/roadmap, stale digest, forged predecessor,
    missing historical repair, unrelated alias and fallback to v10.
    Accept historical v10 evidence through explicit historical selection and
    v11 evidence through explicit current selection.
    Exercise both current runtime renderers with the v2 JSON pair and reproduce
    retained provider-input digests; reject changed Git identities, plan
    path/blob or payload bytes, while preserving v3 acceptance/refusal controls.
  - test: Through production profile construction, authorization revalidation,
    verdict serialization and aggregate verification, prove EC-HARDEN-6 with
    positive sealed and deliberately tooled/credentialed profiles.
    Inject an extra mount/environment variable/descriptor, change installed
    filter or owner argv, omit the credential/tool disclosure, and supply
    absent/forged/expired/wrong-operation authorization. Assert each injection
    site was entered and its restored control passes. Pure configuration
    controls perform zero capability effects without authorization.
  - test: Drive real producer/verifier entrypoints through prepare and seal.
    Reject copied fixture evidence, duplicate or v10 events, missing v11
    binding, stale heads, changed retained bytes, nonce reuse, incomplete
    review/CI, secret-bearing payloads and path escapes. Preserve all existing
    v3 refusal and adversarial cases, including the J8 tooled-seat rejection.
  - impl: Introduce explicit current-versus-historical authority resolution
    throughout both scripts, including ownership history, suite contracts,
    review envelopes, source-boundary checks and completion-event selection.
    Retain historical SL-0/SL-4 chronology and repair chains using their
    recorded authority; do not search merely for the last alias or silently
    treat missing history as an empty baseline. New writes affect only the
    `v11-HARDEN` manifest row; unrelated and v10 rows remain unchanged.
  - impl: Implement separate schema dispatch for v2/v4. Derive declarations
    from Git-bound profile code and retained qualification records, and actual
    capabilities from runtime observations: `seat_jail.jail_profile_digest`,
    `actual_profile_digest`, installed filter, owner argv, staged tree,
    environment, descriptors and confinement probes. Bind authorization to
    the operation and retained verdict, including deliberate credential/tool
    use. Self-reported digests or a profile label alone cannot pass.
    Bind disclosure to `harden_isolation_evidence`, the retained broker record
    beside each leg verdict: profile ID/digest, filter SHA-256 and owner argv.
    A successful jailed route need not emit a notice code. This lane does not change
    `src/phase_loop_runtime/` or reopen seat confinement implementation.
    An uncovered runtime defect remains an unmet criterion with concrete
    evidence and a qualified issue, never an accepted green residual.
  - impl: Preserve reviewed tests-first evidence from V10 and append the new
    content-bound RED/positive-control receipts. Freeze exact v4 suite argv,
    node inventories and outcome policy in the contract artifact; derive
    counts from raw/JUnit output. Keep v3's historical suite parser intact.
    Machine-check the new contract rather than relying on prose attestations.
    For each implementation landing, retain `git diff --name-only` between
    its actual PR base and landed head and reject any test path, including
    additions, deletions or renames. Check descent from the approved tests-only
    landing with `git merge-base --is-ancestor`; derive identities from retained
    Git/PR evidence, never prescribed future commits.
  - verify: Run the narrow regression command below, unchanged producer/verifier
    tests, the existing self-test, then the effective suite. Repeat the fresh
    focused, pure-control, broad, lint and CI collection on clean candidate
    and canonical-main worktrees. Record every skip and its host requirement;
    skipped required confinement witnesses do not prove acceptance.
  - impl: After all producer work passes, perform the docs sweep and write
    `v11-HARDEN-closeout.md` with contract/command references, observed
    results, review dispositions and metadata artifact digests. No doc change is required for public
    README, CHANGELOG or release notes: the changed interface is the
    internal HARDEN collector and its usage is documented in the owned
    contract. All other docs, dependency files, generated bundles, snapshots
    and the companion files under `phase-loop-runtime/tests/` stay untouched.
  - impl: As terminal reducer, gather independently attested roles and fresh
    candidate/main review rounds under current governance, preserving the
    carried four-seat/eight-unique-session evidence obligation. Resolve
    models through current routing; no historical vendor pin or silent
    fallback. Retain real provider, CI and broker results, never self-test
    artifacts. Prepare, independently verify, submit the exact request to
    runner authority, then seal and independently verify once before claiming
    identities/nonces in the external reuse registry.
    Recollect after head, input, review, CI or ledger drift.
  - verify: Validate the sealed evidence and v11 lifecycle transition together.
    Finalize committed contract/closeout metadata before the final candidate
    freeze. Store the resulting seal receipt and final ledger reference in
    runner-owned output, avoiding a self-referential committed seal. Any
    later tracked correction requires fresh candidate/main evidence. Do not hand-edit runner
    events, fabricate operational results or report completion while the
    final seal remains unresolved.

## Execution Policy

- SL-6: work-unit=`phase_reducer`, unsupported=`inherit_default`, inherit-default=`true`, policy-source=`phase plan`

Model and effort inherit the effective policy. Precedence is CLI/operator
override, phase-plan policy, roadmap policy, Dispatch Hints, then registry
defaults. Any fallback must be explicit; no downgrade is implied.

## Execution Notes

One serial lane intentionally combines repair and reduction; its docs/evidence
writer runs only after its separate tests-only landing and implementation stages. No additional
producer lane or shared writable worktree is implied. Obtain required plan
review before production work. Treat unavailable proof as unresolved work,
with human input required only for an actual access or policy decision.

**Plan-board status: NEEDS-DECISION (codex red-team F002).** The plan cannot
land or freeze IF-0-HARDEN-7 yet. `_prepare_stage` only writes the completion
request; no runtime consumer admits it. The seal requires a `phase_execute`
complete event with `metadata.harden_completion`; normal execution omits that
proof, and `phase-loop reconcile` emits `manual_repair`, which the seal rejects.
Neither generic event append nor manual repair is request admission.
The owner must authorize an owning phase or qualified issue for admission and
route HARDEN's `Depends on` and the roadmap lane boundary through the runner.
That decision must specify the authorized operation, request validation and
lifecycle transition that emits the bound event and updates only the live v11
row, including rejection/replay behavior. No such ownership, dependency or
runtime edit is authorized by this amendment; admission and sealing remain
unresolved, not accepted residuals. The roadmap and `src/` remain untouched.

## Verification

Run commands from the repository root. Before execution, validate the effective
`automation.suite_command` and expanded verification argv through
`validate_verification_commands` (IF-0-VC-2). Revalidate paths created by
SL-6 after the tests-only artifact exists. Keep runner verification output
separate from the versioned HARDEN aggregate.

Narrow new regression, then existing contracts:

```bash
uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest -q phase-loop-runtime/scripts -k v11_harden
env PHASE_LOOP_TDD_EXPECT_HARDEN=1 PHASE_LOOP_TDD_EXPECT_HARDEN_PRODUCER=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest -q phase-loop-runtime/tests/test_harden_evidence_producer.py phase-loop-runtime/tests/test_harden_evidence_verifier.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_review_stage_binding.py phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_sandbox_permissions.py phase-loop-runtime/tests/test_seat_notices.py
uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/scripts/verify_harden_evidence.py --self-test
uv run --quiet --with ruff ruff check phase-loop-runtime/scripts/verify_harden_evidence.py phase-loop-runtime/scripts/build_harden_evidence.py phase-loop-runtime/scripts/test_v11_harden_evidence.py
```

Run the frontmatter suite for whole-phase regression, retaining exit data and
JUnit through the runner. Run the pure controls separately with
`PHASE_LOOP_HARDEN_PROOF_MODE=pure_control`. New tests must expose selections
`v11_harden_chronology`, `v11_harden_capabilities`,
`v11_harden_authorization`, `v11_harden_disclosure` and
`v11_harden_seal`; zero collection is failure.

The runner supplies absolute non-secret paths and session hashes below.
`HARDEN_LEDGER` must resolve to this run's canonical `.phase-loop/` ledger;
the reuse registry remains externally owned.

```bash
uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/scripts/build_harden_evidence.py prepare --inputs "$HARDEN_INPUTS" --source-root "$HARDEN_SOURCE_ROOT" --evidence-root "$HARDEN_EVIDENCE_ROOT" --repo "$PWD" --output "$HARDEN_PRE" --completion-request "$HARDEN_REQUEST" --reuse-registry "$HARDEN_REUSE_REGISTRY" --expected-coordinator-session-sha256 "$HARDEN_COORDINATOR_SHA256" --expected-author-session-sha256 "$HARDEN_AUTHOR_SHA256"
uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/scripts/verify_harden_evidence.py --evidence "$HARDEN_PRE" --evidence-root "$HARDEN_EVIDENCE_ROOT" --repo "$PWD" --reuse-registry "$HARDEN_REUSE_REGISTRY" --expected-coordinator-session-sha256 "$HARDEN_COORDINATOR_SHA256" --expected-author-session-sha256 "$HARDEN_AUTHOR_SHA256"
# BLOCKED: the admission operation and lifecycle transition above must be resolved before seal.
uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/scripts/build_harden_evidence.py seal --pre-completion "$HARDEN_PRE" --evidence-root "$HARDEN_EVIDENCE_ROOT" --repo "$PWD" --ledger "$HARDEN_LEDGER" --output "$HARDEN_SEALED" --reuse-registry "$HARDEN_REUSE_REGISTRY" --expected-coordinator-session-sha256 "$HARDEN_COORDINATOR_SHA256" --expected-author-session-sha256 "$HARDEN_AUTHOR_SHA256"
uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/scripts/verify_harden_evidence.py --evidence "$HARDEN_SEALED" --evidence-root "$HARDEN_EVIDENCE_ROOT" --repo "$PWD" --reuse-registry "$HARDEN_REUSE_REGISTRY" --expected-coordinator-session-sha256 "$HARDEN_COORDINATOR_SHA256" --expected-author-session-sha256 "$HARDEN_AUTHOR_SHA256"
git diff --check
```

Ignored raw/JUnit artifacts and runner receipts belong under the runner-assigned
`.phase-loop/runs/` directory, not committed evidence. Commit only sanitized
metadata references under the owned evidence paths. Operational collection
requires real CI/review access: inspect local configuration and metadata-only
CLI state before escalating an access blocker. An unavailable host or provider
is not proxy proof; changed evidence standards require a runner-stamped
roadmap amendment before acceptance.

## Acceptance Criteria

- [ ] EC-HARDEN-0 — definition and falsifier are those at
  `9eb77a3d:specs/phase-plans-v10.md` (the v11 roadmap's V10 input).
  Prove with the approved tests-only landing, ancestry and implementation
  test-path diff audit above, the narrow command with `-k v11_harden_chronology`,
  and the final sealed-evidence verifier command.
- [ ] EC-HARDEN-6 — proven by the narrow command with
  `-k 'v11_harden_capabilities or v11_harden_authorization or v11_harden_disclosure'`
  plus the final sealed-evidence verifier command; falsified by path-entered
  profile, authorization or verdict mutations being accepted, with restored
  sealed and intentionally tooled positive controls passing.
- [ ] IF-0-HARDEN-5, IF-0-HARDEN-6 and IF-0-HARDEN-7 — proven by
  the narrow command with `-k v11_harden_seal` and sealed operational
  verification; falsified by a path-entered completion selector accepting a
  stale, duplicate or wrong-plan event. Only after the effective suite and
  operational verification pass may the runner report complete with all gates.
- [ ] Ownership — proven by `git diff --name-only` and the runner's dirty-path
  audit against SL-6 ownership, plus predecessor/roadmap/frozen-test blob
  comparison; falsified by an unowned changed path or historical blob drift.
  Single-lane ownership is disjoint and has no DAG edges. Pending closeout
  work remains unresolved until its evidence passes.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/scripts/verify_harden_evidence.py`, `phase-loop-runtime/scripts/build_harden_evidence.py`, `plans/evidence/v11-HARDEN-contract.md`, `plans/evidence/v11-HARDEN-closeout.md`
- evidence paths: `plans/evidence/v11-HARDEN/*.json`, `plans/evidence/v11-HARDEN/*.jsonl`, `plans/manifest.json`, `.phase-loop/runs/**/verification.json`
- redaction posture: `metadata_only`
- downstream handling: `none`

No external specification or shared runner format changes. No visible-render
deliverable is declared. Review and execution evidence are produced during
execution; this plan alone does not claim ratification or acceptance.
