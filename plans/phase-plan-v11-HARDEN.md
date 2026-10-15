---
phase_loop_plan_version: 1
phase: HARDEN
roadmap: specs/phase-plans-v11.md
roadmap_sha256: d294c3bab92c995bda8266a12340c78a9d73c12a18919a47b2154ceb4555aba4
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

Finish SL-6's completion seal and EC-HARDEN-6.
Retain EC-HARDEN-0's V10 definition; EC-HARDEN-1 through -4 and SL-5 are delivered;
EC-HARDEN-5 is retired. No phase dependencies; agent-harness#1584 owns admission.
Old FABPUB/SCHED dispatch holds and author-vendor rotation do not apply.

Current `manifest_plan_row` selects only by alias; `verify_authority_paths`,
`git_bound_review_input`, suite/ownership readers and `_prepare_stage` bind v10.
`verify_broker` rejects tooled records via `harden5_unmet`.
Retain these historical checks; they cannot govern v11 completion.

Canonical `.phase-loop/` owns HARDEN-selected planning state; its ledger has
no `phase_execute` completion. `.codex/phase-loop/` is not authority.
Preserve terminal `orphaned` v10; append completion only to v11.

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
  The v4 verifier independently reconstructs the JSON pair from Git; retained
  broker evidence supplies outer-framing arguments for `provider_input_sha256` reproduction.
  Select by retained `provider_input_mode`/`sandbox_staged_at` and the leg
  capability table (`sandbox_usable_by`, `JAILED_LEGS`):
  sealed → `_render_broker_inline_prompt(..., staged_tree=None)`;
  sandbox-inline (codex/grok) → `_broker_review_sandbox_preamble(Path(sandbox_staged_at))`
  plus `_assemble_broker_inline_prompt`;
  jailed pointer → `_render_broker_pointer_prompt(source_commit=<reviewed head>, staged_tree_sha256=<sandbox_snapshot_sha256>, model_only_network=<bound provider/profile flag>)`.
  Derive the flag from the Git-bound provider/profile: true for jailed Gemini,
  false for Claude. Reject profile substitution.
  `sandbox_snapshot_sha256` is authorization's `staged_tree_sha256`
  (`review_tree_manifest_sha256`), not a Git tree ID. Stage cleanup prevents
  post-hoc sandbox-inline renderer calls. A retained path/preamble mismatch or unreproducible
  digest is filed as an unmet runtime defect with a qualified issue, never an accepted residual.
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
  normalized pre-completion digest. Keep this gate explicitly unfrozen until
  agent-harness#1584 lands, as resolved in Execution Notes. Then freeze `harden_completion_request.v2`
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
- **Owned files**: `phase-loop-runtime/scripts/verify_harden_evidence.py`, `phase-loop-runtime/scripts/build_harden_evidence.py`, `phase-loop-runtime/scripts/test_v11_harden_evidence.py`, `phase-loop-runtime/scripts/test_v11_harden_seal.py`, `plans/phase-plan-v11-HARDEN.md`, `plans/manifest.json`, `plans/evidence/v11-HARDEN-contract.md`, `plans/evidence/v11-HARDEN-closeout.md`, `plans/evidence/v11-HARDEN/*.json`, `plans/evidence/v11-HARDEN/*.jsonl`
- **Interfaces provided**: IF-0-HARDEN-5, IF-0-HARDEN-6, IF-0-HARDEN-7.
- **Interfaces consumed**: predecessor plan (pre-existing), historical SL-0/SL-4 receipts (pre-existing), seat profile and authorization records (pre-existing), canonical runner ledger (pre-existing), external reuse registry (pre-existing), runtime completion-admission contract (agent-harness#1584; see Execution Notes).
- **Parallel-safe**: no.
- **Tasks**:
  - test: Stage separate tests-only landings on canonical main per freeze gate.
    Landing 1 now: freeze the IF-0-HARDEN-5/-6, EC-HARDEN-6 and prepare-side
    corpus in `scripts/test_v11_harden_evidence.py`.
    Landing 2 after agent-harness#1584 lands and IF-0-HARDEN-7 freezes:
    seal/completion corpus in `scripts/test_v11_harden_seal.py`, before any
    seal/completion-admission production edit; landing 1's bytes stay immutable.
    Each landing requires exact-head board approval and genuine source-entered
    RED before covered production edits; import/collection errors are not RED.
    Record each approved head; covered production descends from it.
    Freeze both corpora; implementation PRs contain no test diff.
  - test: Exercise production `manifest_plan_row`, authority/input-envelope
    readers and `derive_live_facts` with orphaned v10 plus live v11 rows.
    Reject two live matches, wrong plan/roadmap, stale digest, forged predecessor,
    missing historical repair, unrelated alias and fallback to v10.
    Accept historical v10 evidence through explicit historical selection and
    v11 evidence through explicit current selection.
    Reproduce retained provider-input digests across IF-0-HARDEN-5's sealed,
    sandbox-inline and jailed pointer routes using Git-rebuilt v2 JSON plus
    retained `provider_input_mode`, `sandbox_staged_at`, `sandbox_snapshot_sha256`
    and reviewed head. Freeze Claude/Gemini pointer positives and cross-profile
    rejection using the bound network flag. Exercise post-cleanup assembly; reject changed framing,
    Git identities, plan path/blob or payload bytes.
  - test: Through production profile construction, authorization revalidation,
    verdict serialization and aggregate verification, prove EC-HARDEN-6 with
    historical sealed-profile controls and current tooled/credentialed positives.
    Current sealed review admission must fail; renderer compatibility is not a vote.
    Inject an extra mount/environment variable/descriptor, change installed
    filter or owner argv, omit the credential/tool disclosure, and supply
    absent/forged/expired/wrong-operation authorization. Assert each injection
    site was entered and its restored control passes. Pure configuration
    controls perform zero capability effects without authorization.
  - test: Landing 1 covers chronology, capabilities, authorization, disclosure,
    v2 renderer reproduction and real producer/verifier prepare-path rejections:
    copied fixtures, stale heads, changed retained bytes, nonce reuse, incomplete
    review/CI, secret-bearing payloads and path escapes. Preserve v3 acceptance/refusal
    and adversarial controls, including J8 tooled-seat rejection.
    Landing 2 covers v2 request/event binding, duplicate/v10/stale/wrong-plan
    event selection, missing v11 binding and admission rejection/replay through
    real seal/completion entrypoints.
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
    For each tests-only landing, audit gated production: retain
    `git diff --name-only` from each implementation PR's actual base to landed
    head, rejecting all test paths (including additions/deletions/renames).
    Check descent from that approved tests-only head with
    `git merge-base --is-ancestor`; derive identities from retained Git/PR evidence.
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

Docs/evidence writing follows both tests-only landings and implementation stages.
No additional producer lane or shared writable worktree is implied. Obtain required plan
review before production work. Treat unavailable proof as unresolved work,
with human input required only for an actual access or policy decision.

**Plan-board status: RESOLVED (maintainer decision; codex red-team F002).**
The maintainer chose to file [agent-harness#1584](https://github.com/Consiliency/agent-harness/issues/1584)
and land the plan. Runtime completion admission is owned outside HARDEN.
IF-0-HARDEN-7 stays explicitly unfrozen until agent-harness#1584 lands;
every other lane task proceeds under landing 1's review and tests-first gates.
HARDEN's completion/closeout waits on agent-harness#1584 and the resulting
verified seal; the open dependency is not an accepted residual.
Per the maintainer decision in agent-harness#1584, read the carried V10
EC-HARDEN-0 chronology falsifier against the production change each test corpus covers.

HARDEN consumes the **runtime completion-admission contract** defined by
agent-harness#1584: an authorized runtime operation validates
`harden_completion_request.v2` against v11 authority and evidence, then emits
the bound `phase_execute` complete event with `metadata.harden_completion`
(`harden_completion.v2`) through a lifecycle transition the seal accepts.
Consume its landed operation, validation, rejection/replay behavior and
live-v11-row transition by reference when freezing IF-0-HARDEN-7; preserve
the historical v10 row. HARDEN never hand-edits events or uses generic event
append, `phase-loop reconcile` / `manual_repair`, or other manual repair as a
substitute for admission. The roadmap and `src/` remain untouched by HARDEN.

## Verification

Run commands from the repository root. Before execution, validate the effective
`automation.suite_command` and expanded verification argv through
`validate_verification_commands` (IF-0-VC-2). Revalidate paths created by
SL-6 after each tests-only artifact exists. Keep runner verification output
separate from the versioned HARDEN aggregate.

Narrow new regression, then existing contracts (omit the seal test path from
ruff before landing 2):

```bash
uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest -q phase-loop-runtime/scripts -k v11_harden
env PHASE_LOOP_TDD_EXPECT_HARDEN=1 PHASE_LOOP_TDD_EXPECT_HARDEN_PRODUCER=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests uv run --quiet --with pytest --with-editable ./phase-loop-runtime python -m pytest -q phase-loop-runtime/tests/test_harden_evidence_producer.py phase-loop-runtime/tests/test_harden_evidence_verifier.py phase-loop-runtime/tests/test_advisor_board_composition.py phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_review_leg_sandbox.py phase-loop-runtime/tests/test_review_stage_binding.py phase-loop-runtime/tests/test_seat_jail.py phase-loop-runtime/tests/test_seat_sandbox_permissions.py phase-loop-runtime/tests/test_seat_notices.py
uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/scripts/verify_harden_evidence.py --self-test
uv run --quiet --with ruff ruff check phase-loop-runtime/scripts/verify_harden_evidence.py phase-loop-runtime/scripts/build_harden_evidence.py phase-loop-runtime/scripts/test_v11_harden_evidence.py phase-loop-runtime/scripts/test_v11_harden_seal.py
```

Run the frontmatter suite for whole-phase regression, retaining exit data and
JUnit through the runner. Run the pure controls separately with
`PHASE_LOOP_HARDEN_PROOF_MODE=pure_control`. Landing 1 must expose selections
`v11_harden_chronology`, `v11_harden_capabilities`,
`v11_harden_authorization` and `v11_harden_disclosure`; landing 2 adds
`v11_harden_seal`. Zero collection fails for each of the four non-seal selections
until landing 2, then for all five.

The runner supplies absolute non-secret paths and session hashes below.
`HARDEN_LEDGER` must resolve to this run's canonical `.phase-loop/` ledger;
the reuse registry remains externally owned.

```bash
uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/scripts/build_harden_evidence.py prepare --inputs "$HARDEN_INPUTS" --source-root "$HARDEN_SOURCE_ROOT" --evidence-root "$HARDEN_EVIDENCE_ROOT" --repo "$PWD" --output "$HARDEN_PRE" --completion-request "$HARDEN_REQUEST" --reuse-registry "$HARDEN_REUSE_REGISTRY" --expected-coordinator-session-sha256 "$HARDEN_COORDINATOR_SHA256" --expected-author-session-sha256 "$HARDEN_AUTHOR_SHA256"
uv run --quiet --with-editable ./phase-loop-runtime python phase-loop-runtime/scripts/verify_harden_evidence.py --evidence "$HARDEN_PRE" --evidence-root "$HARDEN_EVIDENCE_ROOT" --repo "$PWD" --reuse-registry "$HARDEN_REUSE_REGISTRY" --expected-coordinator-session-sha256 "$HARDEN_COORDINATOR_SHA256" --expected-author-session-sha256 "$HARDEN_AUTHOR_SHA256"
```

**BLOCKED until agent-harness#1584 lands, landing 2 and gated implementation pass,
and the request is admitted under the consumed contract.** Operator-run seal:

```bash
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

- [ ] EC-HARDEN-0 — definition at `9eb77a3d:specs/phase-plans-v10.md`.
  Proven by both approved tests-only landings' scoped ancestry/test-path audits,
  the narrow `-k v11_harden_chronology` command and final sealed-evidence verifier;
  falsified by a path-entered authority/chronology mutation accepting
  production-before-review for covered production or unapproved frozen-test
  drift, with restored historical/current controls passing.
- [ ] EC-HARDEN-6 — proven by the narrow command with
  `-k 'v11_harden_capabilities or v11_harden_authorization or v11_harden_disclosure'`
  plus the final sealed-evidence verifier command; falsified by path-entered
  profile, authorization or verdict mutations being accepted, with restored
  historical sealed and current tooled positives passing; refuse sealed current-review admission.
- [ ] IF-0-HARDEN-5 and IF-0-HARDEN-6 — proven by the narrow
  `python -m pytest -q` command on `phase-loop-runtime/scripts/test_v11_harden_evidence.py`
  with all four landing-1 `-k` selections, plus prepare-side verification.
  Assert each selection collects tests and exits 0; falsified by path-entered
  authority/schema/provider-input mutations being accepted with restored v11/v3
  controls passing.
  Provable before agent-harness#1584 lands.
- [ ] IF-0-HARDEN-7 — conditional on landing 2; proven by the narrow command
  with `-k v11_harden_seal` plus sealed operational verification; falsified by
  a path-entered completion selector accepting a stale, duplicate or wrong-plan
  event. Only after the effective suite and
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
