---
phase_loop_plan_version: 1
phase: PRESROUTE
roadmap: specs/phase-plans-v11.md
roadmap_sha256: d294c3bab92c995bda8266a12340c78a9d73c12a18919a47b2154ceb4555aba4
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
no upstream dependency for this phase. PANEL, ROUTE and RATIFY consume the
preserved gate and reconciled receipt subject to the carried gaps in Spec Closeout
Plan: the post-hoc records are not V10 chain links, the pending PANEL authorization
cannot land as written, and HARDEN's duplicate-alias lookup remains unresolved.

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
  `agent-harness#1078:PANEL-SL1:PRESROUTE`; preserve it unchanged, with its
  unlandable disposition carried as specified in Spec Closeout Plan.

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
    must neither excuse drift nor become falsely marked landed. Assert that
    `--record-closeout` emits the informational `carried_gap` when a pending pin
    differs from reconciled HEAD, recording the wiring-file mismatch and the
    policy-file match without failing verification; assert that `carried_gap` is
    absent when all pending pins match. Capture the new tests' failure before
    extending the verifier; do not regenerate the original RED receipt.
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
    its unique `record_id`, qualified issue/PR, reason, actual recording time,
    original receipt reference, historical edit and integration, first parent,
    affected paths/nodes, old/new blobs and SHA-256 digests, and recomputable
    patch digest. Each record carries neither an `entry` key nor an
    `authorization_id` key; `record_id` is its own identity. Distinguish historical
    edit identity from integration identity, using fields other than
    `authorization_id` for both. Label the record post-hoc; never invent prior
    authorization or a new tests-first claim. Follow agent-harness#614's append-only precedent, leaving
    existing row fields, lifecycle, timestamps, pending authorizations and every
    other phase's rows unchanged.
  - impl: Add `--record-closeout`, valid only with successful
    `--verify-repairs`, to write `.phase-loop/evidence/PRESROUTE/v11-closeout.json`.
    Derive its metadata from checked inputs: phase and goal ID, original receipt
    and RED-log digests, frozen-file inventory and current digests, repair-record
    identities, verification command/result and IF-0-PRESROUTE-1. If any pending
    authorization pin differs from the reconciled HEAD blob, add a `carried_gap`
    object on the agent-harness#614 shape: `finding`, `handling`, `owner`,
    `status: "carried"`. Derive `finding` at run time by comparing the pending
    authorization's `base_blob` with the reconciled HEAD blob for each pinned
    path, recording both the mismatch for `test_president_wiring.py` and the match
    for `test_govlean_panel_policy.py` on the reviewed inputs. Set `owner` to
    `PANEL / roadmap coordinator`; `handling` carries disposition to PANEL (a
    new authorization pinned to the current blob) or a maintainer ruling and
    cross-references the duplicate-alias hazard assigned to v11 HARDEN in Spec
    Closeout Plan. This
    record is informational: the verifier does not fail on the stale pin; omit
    `carried_gap` when all pins match. This records receipt verification; only
    the runner's successful whole-suite evidence authorizes phase completion.
    No record can substitute for rerunning checks.
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
- downstream handling: These `sl0_repairs` records are post-hoc and are not V10
  chain links. `agent-harness#1078:PANEL-SL1:PRESROUTE` pins
  `phase-loop-runtime/tests/test_president_wiring.py` at
  the pre-agent-harness#1282 blob, while the reconciled HEAD blob at
  review is the agent-harness#1446 blob. Under
  `phase-loop-runtime/scripts/verify_harden_evidence.py` lines 3144/3215/3077-3078,
  that immutable authorization cannot pair with any future landed entry: the
  old blob must equal both its `base_blob` and the merge's first-parent blob,
  and a supplement cannot move `base_blob`. Its disposition belongs to PANEL
  (a new authorization pinned to the current blob) or a maintainer ruling,
  not to this phase. The HARDEN checker's unique-alias row lookup (lines
  2278-2285) will also refuse the first `landed` entry on a PRESROUTE row until
  the v11 HARDEN plan makes it resolve the live row
  (`specs/phase-plans-v11.md:362`). PANEL, ROUTE and RATIFY consume the preserved
  gate and reconciled receipt subject to these carried gaps.

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
