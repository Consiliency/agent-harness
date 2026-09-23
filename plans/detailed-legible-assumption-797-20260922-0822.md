---
phase_loop_plan_version: 1
roadmap: specs/phase-plans-v10.md
automation:
  suite_command:
    - bash
    - -lc
    - >-
      export PYTHONPATH=phase-loop-runtime/src;
      python -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md &&
      python -m phase_loop_runtime.plan_manifest check --repo . &&
      python -m phase_loop_runtime.roadmap_reseal --repo . --roadmap specs/phase-plans-v10.md --check &&
      python -m pytest -q
      phase-loop-runtime/tests/test_legible_roadmap_contract.py
      phase-loop-runtime/tests/test_legible_review_repairs.py
      phase-loop-runtime/tests/test_govlean_roadmap_reseal.py
      phase-loop-runtime/tests/test_convergence_runtime_imports.py
      phase-loop-runtime/tests/test_phase_loop_plan_manifest.py
      -k 'not LEGIBLE-A3-REVIEWTRUTH-TRANSITION'
---

# Detailed plan: reconcile LEGIBLE assumption 2 (agent-harness#797)

Status: draft; no panel or implementation approval. Planning in Default mode.
Owner: Codex roadmap coordinator. Scope: maintenance of `EC-LEGIBLE-6` after
LEGIBLE completion; no new phase completion or dependency waiver.

## Task and research

Reconcile the two stale A2 probe facts with live upstream, preserving the
fail-loud controls. At inspected main (snapshot recorded in the handoff), the
roadmap/probes require governed-pipeline#128 OPEN and a 0.5.0 pin. Live
GitHub instead reports CLOSED and `phase-loop-runtime==0.7.14`; the supported
range is `>=0.7.14,<0.8.0`. Preserve that observation as an input, not an
instruction to repin governed-pipeline or release agent-harness.

`load_probe_sidecar` binds both roadmap bytes and the canonical probe-array
digest. Updating only the two JSON files is insufficient. The existing
`roadmap_reseal` helper refreshes the roadmap constant and JSON copies, but not
the probe-array constant, four current plan bindings or manifest authority.
The existing A2 live failures supply the tests-first predecessor; capture their
exact causes before changing facts. No new runtime behavior is proposed.

## Changes

| File | Entity / action / reason |
|---|---|
| `specs/phase-plans-v10.md` | Modify assumption 2 and the contradictory current-state cross-reference in assumption 1; correct EC-LEGIBLE-6's stale illustrative control by referring to current assumption 2 rather than duplicating its version/state. Preserve goal IDs and dependencies. |
| `specs/roadmap-assumption-probes-v10.json`, `phase-loop-runtime/tests/fixtures/roadmap-assumption-probes-v10.json` | Modify only A2-I128 and A2-GP-PIN facts/anchors/control labels; keep both copies identical and reseal `roadmap_sha256`. |
| `phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py` | Modify only `CANONICAL_PROBES_SHA256` and `CANONICAL_ROADMAP_SHA256`. No classifier, observer, schema, probe-kind or ID changes. |
| `phase-loop-runtime/tests/test_legible_roadmap_contract.py` | Modify the corresponding `ASSUMPTION_PROBES` observations, mutations and embedded roadmap excerpt. Retain the nodeid inventory and real live-observation arm. |
| `plans/phase-plan-v10-LEGIBLE.md` | Modify the matching A2 probe-table facts and current roadmap bindings; no historical receipt rewrite. |
| `plans/phase-plan-v10-{RUNTIME,PRESROUTE,EXECFIND}.md` | Modify only current roadmap digest bindings. Coordinate these digest-only edits with Claude; preserve its phase content and ownership. |
| `plans/manifest.json` | Append the detailed-plan registration if still absent and current-authority rows for every v10 entry bound to the amended roadmap, including unchanged plan texts. Preserve every existing row and each history prefix. |
| `plans/decision-interim-president-ratification-20260904.md`, `CHANGELOG.md` | Append truthful review/landing bookkeeping and one Unreleased repair note; no invented PR number, approval or release claim. |

The closed contract is unchanged. `roadmap_assumptions.py:43-46` defines
`{"schema", "roadmap", "roadmap_sha256", "probes"}` and
`{"id", "assumption", "kind", "subject", "expected", "source_anchor", "mutation_id", "positive_control_id"}`.
Use those existing fields; introduce no vocabulary or schema. The I128 row
expects CLOSED, with an OPEN mutation. The pin row expects package
`phase-loop-runtime`, version `0.7.14`, spec `phase-loop-runtime==0.7.14`;
its mutation changes only `expected_version` to `0.5.0`, leaving other fields
unchanged. Keep all unrelated probes and the local agent-harness version intact.

## Dependencies and order

1. Review this bounded plan under the current four-vendor gate before execution.
   Acquire the coordinator's single-writer slot for roadmap/probe/manifest seals;
   do not compete with agent-harness#978 or Claude PRESROUTE/EXECFIND edits.
2. At execution, capture current main, upstream issue/pin metadata, original
   manifest JSON, current probe rows, both frozen test blobs and current authority
   into `.phase-loop/legible-797/inputs/`. If upstream facts changed again,
   reconcile the input/expected values before code review; never suppress drift.
3. Retain the two existing live A2 RED traces with their typed state/field
   mismatches, then update facts, controls and all current seals together. This
   authorizes the narrowly enumerated test-data repair, not modification or
   re-certification of LEGIBLE's historical tests-first receipts. Do not alter
   `legible_evidence.py` or label old evidence as reviewing the repair.
4. Compute the probe digest using the existing sorted-key, compact JSON encoding
   of `probes`; compute the roadmap digest from final bytes. Inventory all current
   seal consumers before updating them. The currently observed phase-plan seal
   consumers are LEGIBLE, RUNTIME, PRESROUTE and EXECFIND; broader unexpected
   semantic ownership changes require a revised scope.
5. Preserve RUNTIME's original `lifecycle[0].metadata.roadmap_sha256` and all old
   authority rows byte-for-byte in value. Append `plan_current_authority.v1`
   records using the existing format. On refresh, apply the owned delta onto
   current main's file; never restore an older whole manifest. Preserve the
   existing plan order and every old authority/lifecycle prefix. Existing v10
   rows change only by appending current-authority records; current authority
   rebinding requires no other metadata mutation. For this new detailed plan
   alone (`detailed-legible-assumption-797-20260922`), allow ordinary
   `update_lifecycle` transitions permitted by `TRANSITIONS`: its `status` and
   `updated_at` may change and its `lifecycle` may gain new events, retaining
   all prior events and other fields. Apply this exception even when registration
   precedes the captured execution inputs. Compare all other old fields for
   equality. The generic append helper sorts rows, so do not let it reorder
   main's preserved prefix.
6. Run the verification below, then obtain exact-candidate review/CI and normal
   governed landing. Refresh authority after integration without rewriting old
   receipts. Close only agent-harness#797's A2 reconciliation scope; report any
   unrelated A3/provider observation separately.

## Verification and acceptance

- [ ] EC-LEGIBLE-6 — this bounded A2 maintenance is proven by the two exact
  `test_assumption_probe_mutation_and_positive_control` nodes selected with
  `-k 'LEGIBLE-A2-I128 or LEGIBLE-A2-GP-PIN'`, including real current upstream,
  opposite-state/single-field mutations and their independent positive controls.
  Retain an evidence-only constant-pass mutation's failing assertion to prove
  those controls still discriminate. This is not whole-phase reacceptance.
- [ ] The declared `automation.suite_command` passes on the repaired candidate.
  Its exclusion names the separate A3 model observation explicitly; it changes
  no test policy, and A3 must never be silently counted as passed.
- [ ] Preserve historical metadata and old manifest/history prefixes; record the
  mechanical before/after comparison in `.phase-loop/legible-797/preservation.json`.
  `test_convergence_runtime_imports.py` and the manifest check additionally prove
  the historical RUNTIME record plus current authority agree with their contracts.
- [ ] Run `PYTHONPATH=phase-loop-runtime/src python -m pytest -q phase-loop-runtime/tests`
  after the focused suite, then `git diff --check`. Report retained full-suite
  failures against exact baseline causes, never as green. Record the changed
  source/fixture identities before and after verification in the native runner
  evidence; model work keeps the operator's heartbeat-only/no-thinking-deadline
  policy. No provider launch is needed for the A2-only verification.

Documentation impact is the roadmap/LEGIBLE table, digest-only current plan
bindings, ledger and changelog listed above. No setup skill, runtime API,
provider route, deployment, downstream install, HARDEN retry or historical
INTEG evidence search is included.
