---
phase_loop_plan_version: 1
phase: PRESROUTE
roadmap: specs/phase-plans-v11.md
roadmap_sha256: be453ea57c7fe77c0f16f2af0e47158440cb2b0241fa65794292464556a8fa3c
automation:
  suite_command:
    - bash
    - -c
    - >-
      set -eu;
      PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q
      phase-loop-runtime/tests/test_presroute_hardening.py
      phase-loop-runtime/tests/test_govlean_panel_policy.py
      phase-loop-runtime/tests/test_president_wiring.py;
      python3 phase-loop-runtime/scripts/verify_presroute_historical_receipt.py
      --repo . --verify-repairs --record-closeout;
      git diff --check
---

# PRESROUTE: President Execution Route — receipt closeout

## Context

This is v11 Phase 7's single-lane closeout of EC-PRESROUTE-0, tracked by
agent-harness#1143. The carried implementation is delivered. The v10 plan is a
frozen input; only its remaining receipt work carries forward. The roadmap has
no upstream dependency for this phase. PANEL, ROUTE and RATIFY consume its result.

The historical verifier checks the original receipt at its original landing,
including physical, index and HEAD evidence bytes. It does not reconcile later
frozen-test changes with the ledger. The v10 PRESROUTE row is orphaned by v11
supersession and contains an unconsumed PANEL authorization and supplement.
Preserve that history and append a separate v11 completion through the normal
lifecycle after successful verification.

## External Inputs

These are historical inputs, never requirements on this phase's future commits.

- `specs/phase-plans-v11.md`, with the frontmatter digest.
- `plans/phase-plan-v10-PRESROUTE.md` and the carried V10 definitions identified
  by the roadmap's External Inputs.
- Original landing (agent-harness#998), resolved by the existing verifier's
  `LANDING` constant, the original `content_tdd_receipt.v1`, and its two RED logs.
- Every historical frozen-test edit named in v11's PRESROUTE criterion:
  agent-harness#1025 / agent-harness#1026 (`test_govlean_panel_policy.py`),
  agent-harness#1282 and agent-harness#1446 (`test_president_wiring.py`).
  Resolve their exact historical objects from the roadmap and local Git history.
- Post-closeout repair precedent: agent-harness#614, recorded in
  `plans/manifest.json`. Pending PANEL authority:
  `agent-harness#1078:PANEL-SL1:PRESROUTE`; it remains pending until its own landing.

## Interface Freeze Gates

- [ ] IF-0-PRESROUTE-1 — Carry forward the existing
  `public_board_president.v1` identity, completion grammar
  (`FINDING <id>: BLOCKING|DEFERRED — <reason>`, terminal
  `FORCING DECISION:`), and `president.ruling.json` shape, as frozen in
  `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md` and
  `phase-loop-runtime/tests/data/president_ruling_v1.golden.json`.
  Publish its receipt reconciliation without changing this interface.

## Lane Index & Dependencies

SL-0 — Receipt repairs, documentation audit and closeout
  Depends on: (none)
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Receipt repairs, documentation audit and closeout

- **Scope**: Reconcile the existing frozen receipt with all landed test repairs, prove that reconciliation, and record the v11 closeout.
- **Depends on**: (none).
- **Owned files**: `plans/manifest.json`, `phase-loop-runtime/scripts/verify_presroute_historical_receipt.py`, `phase-loop-runtime/tests/test_presroute_hardening.py`, `.phase-loop/evidence/PRESROUTE/v11-closeout.json`
- **Interfaces provided**: IF-0-PRESROUTE-1 closeout evidence; append-only PRESROUTE repair records; machine-checked current frozen-file bindings.
- **Interfaces consumed**: `content_tdd_receipt.v1` (pre-existing), `plans/manifest.json` repair precedent and lifecycle (pre-existing), `verify_presroute_historical_receipt.py` historical verification (pre-existing), IF-0-PRESROUTE-1 (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: In the existing non-frozen hardening test file, add tests selected by
    `historical_receipt` that enter the real verifier's CLI/validation path on
    temporary Git fixtures. A valid history and ledger pass. Removing any repair,
    duplicating one, changing an old/new blob or patch digest, introducing an
    unrecorded frozen-file edit, substituting unchanged HEAD bytes for dirty index
    or physical bytes, or modifying original evidence must fail. Shuffling repair
    records must preserve the result. An unrelated pending PANEL authorization
    must neither excuse drift nor become falsely marked landed. Capture the new
    tests' failure before extending the verifier; do not regenerate the original
    RED receipt.
  - impl: Extend the existing verifier with `--verify-repairs`, preserving its
    current no-flag historical behavior and all evidence-integrity checks.
    Inventory the full receipt's frozen path set, including the adapter and
    golden fixture. Discover every content-changing integration since the
    historical landing; the known inputs are a minimum, not an allowlist.
    Derive old/new Git blobs, SHA-256 file digests, changed node/helper scope and
    exact patch digests from Git objects. Reconcile per-path chains from original
    bytes to current HEAD, index and physical files. Require complete, unique,
    continuous coverage independent of record order; unchanged frozen paths
    must still match the receipt. Do not import HARDEN's authorization-before-
    merge checker as a substitute: these are explicitly post-hoc repairs.
  - impl: Append one metadata-only post-closeout `sl0_repairs` record per
    historical change to the original `v10-PRESROUTE` row. Each record names
    its unique record ID, qualified issue/PR, reason, actual recording time,
    original receipt reference, historical edit and integration, first parent,
    affected paths/nodes, old/new blobs and SHA-256 digests, and recomputable
    patch digest. Distinguish historical edit identity from integration identity.
    Label the record post-hoc; never invent prior authorization or a new
    tests-first claim. Follow agent-harness#614's append-only precedent, leaving
    existing row fields, lifecycle, timestamps, pending authorizations and every
    other phase's rows unchanged.
  - impl: Add `--record-closeout`, valid only with successful
    `--verify-repairs`, to write `.phase-loop/evidence/PRESROUTE/v11-closeout.json`.
    Derive its metadata from checked inputs: phase and goal ID, original receipt
    and RED-log digests, frozen-file inventory and current digests, repair-record
    identities, verification command/result and IF-0-PRESROUTE-1. This records
    receipt verification; only the runner's successful whole-suite evidence
    authorizes phase completion. No record can substitute for rerunning checks.
  - docs: After the repairs and verification, record in the closeout artifact
    the `no_doc_delta` decision: public behavior and contract documentation are
    unchanged, so README, changelog and catalog need no edit. This lane is the terminal
    reducer and consumes all of its own outputs.
  - verify: Run the narrow hardening selector, then the complete Verification
    suite. Persist the runner's verification result. Advance only
    `v11-PRESROUTE` through the supported manifest lifecycle once acceptance and
    required review pass; preserve the orphaned v10 row. Include IF-0-PRESROUTE-1
    in the eventual completed runner closeout.

## Execution Notes

- The verifier and its existing test companion are the only support-code changes;
  they make the receipt-only closeout machine-checkable. President runtime,
  frozen tests, adapter, golden fixture, original receipt and RED logs remain
  read-only. No generated bundle, dependency, lockfile, migration or environment
  change is needed. agent-harness#1006 and agent-harness#1206 remain out of scope.
- One lane owns every writable path, so ownership is disjoint and the DAG is
  acyclic. Serialize updates to the shared manifest, reread it immediately before
  editing, and preserve unrelated rows. No write-capable agent fanout is implied.
- Use canonical `.phase-loop/` runner state; compatibility files under
  `.codex/phase-loop/` cannot supersede it. Runtime-generated event and
  verification logs remain runner-owned. Track the new ignored evidence file
  explicitly when staging phase outputs.
- Planning registers the v11 plan as committed in the manifest vocabulary;
  that is not a Git commit or a phase-completion claim. The runner owns lifecycle
  and final closeout. Do not rewrite v10's orphaned status to completed.
- Resolve execution policy by CLI/operator override, phase plan, roadmap,
  executor-only Dispatch Hints, then registry defaults. This plan adds no
  executor/model override; no silent downgrade is permitted without explicit
  fallback or default inheritance.
- Standard plan review and landing gates still apply. A staged plan is not
  ratified review evidence. This plan does not authorize publishing or merging.
- Use the existing verifier's team-host-aware worktree-root resolver. Historical
  evidence verification may use an isolated checkout; never alter this worktree's
  source bytes to emulate the original landing.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `plans/manifest.json`, `.phase-loop/evidence/PRESROUTE/v11-closeout.json`
- evidence paths: `.phase-loop/evidence/PRESROUTE/v11-closeout.json`, `.phase-loop/evidence/PRESROUTE/content-tdd-receipt.json`, `plans/manifest.json`
- redaction posture: `metadata_only`
- downstream handling: none; PANEL, ROUTE and RATIFY consume the preserved gate and reconciled receipt.

## Verification

Run from the repository root with the runtime and pytest available; `uv` is
required by the existing historical verifier. The new verifier switches are
implemented by SL-0. First run the targeted receipt tests; then the effective
`automation.suite_command` runs the complete phase regression and records
closeout evidence only after those tests pass.

- `env PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_presroute_hardening.py -k historical_receipt`
- `env PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_presroute_hardening.py phase-loop-runtime/tests/test_govlean_panel_policy.py phase-loop-runtime/tests/test_president_wiring.py`
- `python3 phase-loop-runtime/scripts/verify_presroute_historical_receipt.py --repo . --verify-repairs --record-closeout`
- `git diff --check`

IF-0-VC-2 intake must accept these command paths and the effective suite before
handoff. Validate the plan structure with
`python3 phase-loop-skills/plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v11-PRESROUTE.md`.
Check goal coverage and the supplied roadmap digest without changing roadmap
bytes. The full repository suite remains governed by TESTLOOP; this phase's
regression boundary is the receipt verifier and existing president contract tests.

## Acceptance Criteria

- [ ] EC-PRESROUTE-0 — proven by `python3 phase-loop-runtime/scripts/verify_presroute_historical_receipt.py --repo . --verify-repairs` and `env PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_presroute_hardening.py -k historical_receipt`; falsified by a path-entered negative control at `phase-loop-runtime/scripts/verify_presroute_historical_receipt.py:main` that removes a required repair, tampers with its content binding, or changes original evidence and still exits zero, paired with an intact-history positive control entering the same production verification path.
