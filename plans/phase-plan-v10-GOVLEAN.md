---
phase_loop_plan_version: 1
phase: GOVLEAN
roadmap: specs/phase-plans-v10.md
roadmap_sha256: c66949236043e46e956caec1c09d0c19d0e8751e4ce2891de1fe2edf24e9fea1
---

# GOVLEAN: Lean Governance and Evidence Primitives

## Context

GOVLEAN replaces history-shape evidence with content- and behavior-bound runtime primitives, then makes the ratified review and issue-closeout policy executable. The phase has exactly two implementation lanes. Their write sets are complete and disjoint; the cross-lane tests-only landing is a coordinator gate that precedes every production-code task.

The authority switch is atomic: the existing v10 governance remains exclusive until EC-GOVLEAN-5 is verified on main and the ledger records that event. The post-switch policy is full Fable 5, GPT-5.6 Sol, Gemini 3.6 Flash, and Grok 4.5 board plus president for plan or production-code landings, and one grounded reviewer for tests-only or docs-only landings.

PROOFGATE is off-limits: do not edit its plan, its roadmap section, or any PROOFGATE runtime surface, and do not dispatch it. A refreshed PROOFGATE plan is separate downstream work after GOVLEAN completes.

The phase ledger records these pre-registered experiment targets:

| Measure | Target |
|---|---:|
| Merged PRs | `<= 12` |
| Support share (`tests + docs + plans + CI` / all PRs) | `< 40%` |
| Plan size | `<= 3000` words |
| Future-history pins | `0` |
| Plan amendments caused by unrelated landings | `0` |
| Issues | `closed >= opened` during the phase window |
| Elapsed wall time | `<= 4 days` |

## Interface Freeze Gates

- [ ] **IF-0-GOVLEAN-1 — Evidence primitives.** Add these importable module APIs:
  - `ContentTddReceipt` with schema `content_tdd_receipt.v1`, binding sorted test paths and blob digests, RED command and node inventory, exit status, stdout/stderr digests, authoritative base-tree digest, and the resolved tests-only landing reference. `record_content_tdd_receipt(...)` records it; `verify_content_tdd_receipt(...)` proves unchanged bytes and base-tree membership in the declared landing without asserting history shape.
  - `DeclaredCommitIdentity` using trailer `Phase-Loop-Identity: <identity>`; `select_declared_commit(repo, landing_ref, identity)` returns exactly one match and fails closed on zero or duplicate declarations, independent of unrelated commits.
  - `ProducerManifest` with schema `producer_manifest.v1`; every build-backend, setuptools, umask, `SOURCE_DATE_EPOCH` posture, and archive-tool entry is `PINNED` or `NORMALIZED`. `verify_producer_manifest(...)` returns typed `producer_drift` before content comparison when a pinned input changes.
  - `LocalStageCache.get_or_run(stage_id, input_digests, producer_manifest, runner)` keys receipts by stage, sorted content digests, and producer identity; stale input or producer state is a miss/fail-closed. `run_independent_stages(stages, max_workers)` runs local independent stages and returns all outcomes/failures without network, CI, containers, or remote cache.
  - `reseal_roadmap(repo, roadmap, write)` and `python -m phase_loop_runtime.roadmap_reseal --repo . --roadmap specs/phase-plans-v10.md --check|--write`. One authoritative source value feeds `roadmap_assumptions.py`; write mode mechanically refreshes the assumption sidecar and its test-fixture copy, the existing LEGIBLE compatibility test consumes that value, and `plan_manifest.py` removes its duplicate literal in favor of the same canonical constant.
- [ ] **IF-0-GOVLEAN-2 — Plan-pin lint.** `find_plan_pin_violations(text, repo_root, plan_path) -> tuple[PlanPinFinding, ...]` reports the closed categories `future_commit_identity`, `mutable_tracked_blob_pin`, `commit_ordinal`, and `future_topology`. The plan validator fails on every finding, retains a per-class positive control from the unmodified CONFORM plan, exempts only its verified current-roadmap frontmatter seal, and permits a `Pinned inputs` section only for declared external content. This plan has no such section.
- [ ] **IF-0-GOVLEAN-3 — Review policy.** `ReviewLandingTier` is one of `plan`, `production_code`, `tests_only`, or `docs_only`. `review_policy_for_tier(...)` returns four seats plus president for the first two and one grounded reviewer for the latter two. `invoke_president(...)` uses a president-only prompt whose terminal grammar is one `FINDING <id>: BLOCKING|DEFERRED — <reason>` per finding followed by exactly one `FORCING DECISION: <decision>` line. A missing grammar yields typed `president_ruling_format_missing` and one same-session re-ask that does not consume the substantive round cap. President selection descends Fable → Sol → Grok 4.5 → Gemini 3.6 only after a typed availability failure; disagreement never triggers descent, skipped rungs are invalid, and a degraded read-only president fails closed when it defers validation it identified as necessary.
- [ ] **IF-0-GOVLEAN-4 — Issue closeout.** `IssueDisposition` is a closed record with repository-qualified `issue_id`, `phase`, `disposition` (`closed`, `folded_into_successor`, or `carried_with_owner`), and nonempty `owner`; folded records also name `successor_plan`. On `update_lifecycle(..., transition="completed", metadata=...)`, `plan_manifest` parses the externally enrolled `issue_inventory` and `issue_dispositions`, requires phase agreement and exact set equality, and rejects omissions, duplicates, unknown dispositions, or missing owners.
- [ ] **IF-0-GOVLEAN-5 — Fleet prose parity.** All eight planner/roadmap skill sources state content/behavior falsifiers, external-only pins, the 3000-word budget and justification above it, cross-vendor ablation for Sol-authored plans, and proof-cost findings for a single node over roughly five minutes or a run unable to report multiple failures. Regenerated bundle outputs must be byte-parity clean.
- [ ] **TG-GOVLEAN-0 — Tests-only freeze gate.** This coordinator gate has no writer. It consumes successful authorship plus retained RED evidence from both `SL0-T0` and `SL1-T0`, then lands all new GOVLEAN test/support files together. Both implementation tasks depend on the landed gate; neither test task depends on it.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `specs/phase-plans-v10.md`, `skills-src/{claude,codex,gemini,opencode}/*{plan-phase,phase-roadmap-builder}/SKILL.md`, `phase-loop-skills/{plan-phase,phase-roadmap-builder}/**`
- evidence paths: `.phase-loop/evidence/GOVLEAN/spec-delta-closeout.json`, `.phase-loop/evidence/GOVLEAN/issue-dispositions.json`
- redaction posture: `metadata_only`
- downstream handling: `none`; PROOFGATE refresh remains separate and untouched

## Lane Index & Dependencies

SL-0 — Runtime primitives and governance
  Depends on: (none)
  Blocks: SL-1
  Parallel-safe: no

SL-1 — Process, skills, and docs sweep
  Depends on: SL-0
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Runtime primitives and governance

- **Scope**: Land the frozen runtime falsifiers, then implement plan lint, evidence/proof primitives, resealing, producer identity, and bounded panel president/tiering behavior.
- **Owned files**: `skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py`, `phase-loop-runtime/scripts/gate_a_cleanroom.sh`, `phase-loop-runtime/src/phase_loop_runtime/plan_pin_lint.py`, `phase-loop-runtime/src/phase_loop_runtime/tdd_receipts.py`, `phase-loop-runtime/src/phase_loop_runtime/declared_identity.py`, `phase-loop-runtime/src/phase_loop_runtime/producer_manifest.py`, `phase-loop-runtime/src/phase_loop_runtime/proof_stages.py`, `phase-loop-runtime/src/phase_loop_runtime/roadmap_reseal.py`, `phase-loop-runtime/src/phase_loop_runtime/roadmap_assumptions.py`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `specs/roadmap-assumption-probes-v10.json`, `phase-loop-runtime/tests/fixtures/roadmap-assumption-probes-v10.json`, `phase-loop-runtime/tests/govlean_freeze_receipt.py`, `phase-loop-runtime/tests/test_govlean_plan_pin_lint.py`, `phase-loop-runtime/tests/test_govlean_tdd_receipts.py`, `phase-loop-runtime/tests/test_govlean_declared_identity.py`, `phase-loop-runtime/tests/test_govlean_producer_manifest.py`, `phase-loop-runtime/tests/test_govlean_proof_stages.py`, `phase-loop-runtime/tests/test_govlean_roadmap_reseal.py`, `phase-loop-runtime/tests/test_govlean_panel_policy.py`, `phase-loop-runtime/tests/test_legible_review_repairs.py`, `phase-loop-runtime/tests/test_review_policy_govlean_repairs.py`
- **Interfaces provided**: `find_plan_pin_violations`, `ContentTddReceipt`, `DeclaredCommitIdentity`, `ProducerManifest`, `LocalStageCache`, `run_independent_stages`, `reseal_roadmap`, `ReviewLandingPolicy`
- **Interfaces consumed**: `validate_plan_doc.py contract`, `PanelRequest and PanelResult`, `roadmap_assumption_probe.v1` (pre-existing)
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `SL0-T0` | `test` | (none) | new SL-0 test/support files plus the existing LEGIBLE digest-mirror test | seven `test_govlean_*` modules, receipt bootstrap, and canonical roadmap-digest consumption | `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_{plan_pin_lint,tdd_receipts,declared_identity,producer_manifest,proof_stages,roadmap_reseal,panel_policy}.py phase-loop-runtime/tests/test_legible_review_repairs.py` |
| `SL0-I0` | `impl` | `TG-GOVLEAN-0` | SL-0 production/source and seal-representation files | frozen; edits forbidden | same targeted command, now GREEN |
| `SL0-T1` | `test` | `TG-GOVLEAN-0` | `test_review_policy_govlean_repairs.py` | post-review tier-routing, president-re-ask availability, and tracked-digest bypass falsifiers | `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_review_policy_govlean_repairs.py` must fail for the intended assertions before repair |
| `SL0-I1` | `impl` | `SL0-T1` | `panel_invoker.py`, `plan_pin_lint.py`, and `gate_a_cleanroom.sh` | all original GOVLEAN tests remain frozen; `SL0-T1` becomes repair-frozen | original SL-0 command plus `SL0-T1`, now GREEN |
| `SL0-V0` | `verify` | `SL0-I1` | SL-0 owned files | all SL-0 tests plus the repair regression | receipt verification, targeted regression, reseal `--check`, validator controls |

### SL-1 — Process, skills, and docs sweep

- **Scope**: Add the typed plan-manifest issue-disposition gate, update its execute-phase callers, sweep all planner/roadmap skill variants, regenerate and package committed skill outputs, and reduce metadata-only issue/spec closeout evidence.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py`, `phase-loop-runtime/tests/test_govlean_plan_manifest_issue_dispositions.py`, `phase-loop-runtime/tests/test_govlean_skill_policy_parity.py`, `phase-loop-runtime/tests/test_skill_plan_manifest_write.py`, `phase-loop-runtime/tests/data/launchspec_golden/launchspec_golden.json`, `skills-src/claude/claude-plan-phase/SKILL.md`, `skills-src/codex/codex-plan-phase/SKILL.md`, `skills-src/gemini/gemini-plan-phase/SKILL.md`, `skills-src/opencode/opencode-plan-phase/SKILL.md`, `skills-src/claude/claude-phase-roadmap-builder/SKILL.md`, `skills-src/codex/codex-phase-roadmap-builder/SKILL.md`, `skills-src/gemini/gemini-phase-roadmap-builder/SKILL.md`, `skills-src/opencode/opencode-phase-roadmap-builder/SKILL.md`, `skills-src/claude/claude-execute-phase/SKILL.md`, `skills-src/codex/codex-execute-phase/SKILL.md`, `skills-src/gemini/gemini-execute-phase/SKILL.md`, `skills-src/opencode/opencode-execute-phase/SKILL.md`, `phase-loop-skills/plan-phase/**`, `phase-loop-skills/phase-roadmap-builder/**`, `phase-loop-skills/execute-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-plan-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-phase-roadmap-builder/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-execute-phase/**`
- **Interfaces provided**: `IssueDisposition`, `completed issue-disposition gate`, `GOVLEAN skill policy parity`
- **Interfaces consumed**: `find_plan_pin_violations`, `ProducerManifest`, `LocalStageCache`
- **Parallel-safe**: no

| Task ID | Type | Depends on | Files in scope | Tests owned | Test command |
|---|---|---|---|---|---|
| `SL1-T0` | `test` | (none) | two new SL-1 tests plus the existing phase-completion compatibility test | issue omission/schema negatives, agent-harness#548 lossless extension-field roundtrip, fleet-source parity, and frozen existing-caller compatibility | `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_{plan_manifest_issue_dispositions,skill_policy_parity}.py phase-loop-runtime/tests/test_skill_plan_manifest_write.py` |
| `SL1-I0` | `impl` | `TG-GOVLEAN-0`, `SL0-I0` | `plan_manifest.py` and twelve exact skill sources | all SL-1 tests frozen; edits forbidden | same targeted command, now GREEN |
| `SL1-I1` | `impl` | `SL1-I0` | generated neutral and packaged skill directories plus the launch-spec golden affected by execute-phase prose | frozen; edits forbidden | run `regenerate_skills_bundle.py`, `sync_skills_bundle.py`, then intentionally regenerate the launch-spec golden |
| `SL1-V0` | `verify` | `SL1-I1` | all SL-1 owned files and closeout evidence | both SL-1 tests plus existing parity tests | focused and whole-phase commands below |

## Execution Notes

1. Review and land this exact plan under the pre-switch v10 four-seat board and Fable chair. Record the reviewed digest and cross-vendor ablation because Sol authored it. Do not begin tests until that landing is ratified.
2. Before any production edit, author every new test/support file from both lanes in parallel, with no dependency on `TG-GOVLEAN-0`. Run the new tests against the implementation-free base, require a nonzero result with the intended assertions firing, and retain raw stdout, stderr, command, nodes, and exit status. `TG-GOVLEAN-0` then consumes both test tasks and lands them in one tests-only PR; both implementation tasks remain blocked until that landing is synced on main. Then run:

   `uv run --project phase-loop-runtime python phase-loop-runtime/tests/govlean_freeze_receipt.py record --repo . --test-glob 'phase-loop-runtime/tests/test_govlean_*.py' --red-command 'uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_*.py' --landing-ref origin/main --out .phase-loop/evidence/GOVLEAN/content-tdd-receipt.json`

   The bootstrap writer emits the frozen `content_tdd_receipt.v1` schema. Preserve its RED logs. Implementation worktrees receive the receipt read-only and may not edit any frozen test byte. The tests-only landing occurs before the authority switch, so it clears the still-operative pre-switch review gate; after the switch, tests-only/docs-only use one grounded reviewer as required by the implemented tiering.
3. Implement SL-0 without touching frozen tests. Verify with `uv run --project phase-loop-runtime python -m phase_loop_runtime.tdd_receipts verify --receipt .phase-loop/evidence/GOVLEAN/content-tdd-receipt.json --repo .`. Review the production landing with the full four-seat board under current authority. The first combined-head review found three blocking runtime falsifiers and one unowned clean-room support edit. This amendment owns the support edit and adds `SL0-T1`; author and retain its RED result before `SL0-I1`, and do not alter any receipt-frozen `test_govlean_*` byte. Record EC-GOVLEAN-5 verification on main as the single authority-switch event; never infer it from partial code or a green subset.
4. Execute SL-1 only after SL-0. `plan_manifest` code remains tests-first. Scope the completion gate to `type=phase`; a phase closeout must pass explicit enrolled inventory and dispositions, including explicit empty arrays when the authoritative inventory is empty. Update all four execute-phase skill sources and the existing phase-completion test to supply that contract. Skill prose records the accepted non-code exception; its content/parity tests do not convert prose into a production-code chronology claim. Regenerate through `regenerate_skills_bundle.py`, package through `sync_skills_bundle.py`, and intentionally regenerate the launch-spec golden affected by the Claude execute-phase prose, then require parity and launch-spec golden guards. As a post-switch production-code landing, SL-1 requires the full four-seat board plus the first available president from the frozen ladder.
5. Materialize issue enrollment outside the manifest with `gh issue list --repo Consiliency/agent-harness --state open --limit 1000 --json number,labels,createdAt`; include open issues created during the ledger phase window or carrying the GOVLEAN phase label. Store repository-qualified IDs, triage each to one typed disposition, and require ledger/inventory equality before `completed`. Record opened/closed counts, PR classification, plan words, elapsed timestamps, unrelated-landing amendment count, and target verdicts in metadata-only phase evidence. If three non-mandated support PRs land before an implementation PR, stop for diagnosis; the plan PR and required tests-first landing are excluded from that tripwire.
6. The SL-1 docs/spec reducer inspects the roadmap and generated skill diff, records `no_spec_delta` plus an explicit `no_doc_delta`, and confirms that no unowned docs/spec change is needed. It must not amend the roadmap or PROOFGATE. If a real canonical delta emerges, stop and replan instead of widening ownership.

## Acceptance Criteria

- [ ] EC-GOVLEAN-0 — proven by `uv run --project phase-loop-runtime python -m phase_loop_runtime.tdd_receipts verify --receipt .phase-loop/evidence/GOVLEAN/content-tdd-receipt.json --repo .`
- [ ] EC-GOVLEAN-1 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_plan_pin_lint.py`
- [ ] EC-GOVLEAN-2 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_tdd_receipts.py`
- [ ] EC-GOVLEAN-3 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_declared_identity.py`
- [ ] EC-GOVLEAN-4 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_proof_stages.py phase-loop-runtime/tests/test_govlean_producer_manifest.py`
- [ ] EC-GOVLEAN-5 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_panel_policy.py`
- [ ] EC-GOVLEAN-6 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_plan_manifest_issue_dispositions.py`
- [ ] EC-GOVLEAN-7 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_skill_policy_parity.py phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_skills_bundle_drift.py`
- [ ] EC-GOVLEAN-8 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_roadmap_reseal.py`
- [ ] EC-GOVLEAN-9 — proven by `uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_producer_manifest.py`

## Verification

```bash
uv run --project phase-loop-runtime python -m phase_loop_runtime.tdd_receipts verify --receipt .phase-loop/evidence/GOVLEAN/content-tdd-receipt.json --repo .
uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_govlean_*.py
uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests/test_phase_loop_plan_manifest.py phase-loop-runtime/tests/test_skill_plan_manifest_write.py phase-loop-runtime/tests/test_panel_invoker.py phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_skills_bundle_drift.py phase-loop-runtime/tests/test_phase_loop_planner_validation.py phase-loop-runtime/tests/test_phase_loop_roadmap_validate.py phase-loop-runtime/tests/test_roadmap_authority.py
uv run --project phase-loop-runtime python -m phase_loop_runtime.roadmap_reseal --repo . --roadmap specs/phase-plans-v10.md --check
uv run --project phase-loop-runtime python skills-src/claude/claude-plan-phase/scripts/validate_plan_doc.py plans/phase-plan-v10-GOVLEAN.md
uv run --project phase-loop-runtime python -c "from pathlib import Path; from phase_loop_runtime.planner_validation import validate_plan_dispatch_hints; p=Path('plans/phase-plan-v10-GOVLEAN.md'); print(validate_plan_dispatch_hints(p.read_text()))"
uv run --project phase-loop-runtime python -c "from pathlib import Path; n=len(Path('plans/phase-plan-v10-GOVLEAN.md').read_text().split()); print(n); assert n <= 3000"
uv run --project phase-loop-runtime ruff check phase-loop-runtime/src/phase_loop_runtime/
uv run --project phase-loop-runtime pytest -q phase-loop-runtime/tests -m "not dotfiles_integration"
git diff --check
```

At phase start, store a metadata-only content digest for `plans/phase-plan-v10-PROOFGATE.md`; at closeout require byte equality and an empty path-specific working/index diff. This is a no-touch assertion, not a future-history pin.
