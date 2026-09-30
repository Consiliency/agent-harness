---
phase_loop_plan_version: 1
phase: RATIFY
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 15960b11e91b369889841691a5b91ace6f39f4f1493697bcd0c0a373a0f7c113
automation:
  suite_command: 'env -u PHASE_LOOP_TDD_EXPECT_HARDEN -u PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_ratify_phase.py phase-loop-runtime/tests/test_ruling_ledger.py phase-loop-runtime/tests/test_president_wiring.py phase-loop-runtime/tests/test_president_heartbeat_1001.py phase-loop-runtime/tests/test_president_ladder_config.py phase-loop-runtime/tests/test_ratification_policy.py phase-loop-runtime/tests/test_governed_review.py phase-loop-runtime/tests/test_phase_loop_plan_manifest.py phase-loop-runtime/tests/test_skills_canon_parity.py phase-loop-runtime/tests/test_skills_bundle_drift.py'
---

# RATIFY: Typed Rulings and an Ancestor-Frozen Ledger

## Context

Planning only. No execution admission, completed phase or reviewed plan is claimed.
Source: agent-harness#935 and the RATIFY section of `specs/phase-plans-v10.md`,
as superseded by its EXECFIND advisory-evidence ruling. Reference EC-RATIFY-0
through EC-RATIFY-5; the roadmap is the normative source.

PRESROUTE's operation and ruling parser are present. EXECFIND's receipt interface
landed through agent-harness#1163 and agent-harness#1164. Receipt verification
binds observations, not the truth of the finding: neither RED nor GREEN settles
the concern. RATIFY consumes that interface; do not require the held EXECFIND
fix-round implementation as an input to the ruling resolver it needs.

The current president prompt is built from seat paragraphs by
`president_findings_from_legs`; `_valid_president_grammar` binds positional ids.
`PresidentFindingRuling` currently has id, disposition and reason. The governed
gate independently holds `finding_receipt` and unresolved prose dissent, and
does not currently discharge either merely because `PanelResult.president`
exists. Integration must resolve that actual gate, not only change prompt prose.

The implementation remains held until exact-plan board/president review,
prerequisite receipt verification and shared-file ownership clearance. Claude
owns agent-harness#1160, agent-harness#1166, agent-harness#1169 and
agent-harness#1171. No lane touches BAML, launch prefixes, sandbox or credential
isolation, registry defaults, board presets or vendor composition. Re-evaluate
shared-file changes after those landings; replay only this plan's manifest delta.

## Interface Freeze Gates

- [ ] IF-0-RATIFY-1 — one typed ruling contract shared by prompt/parser, gate,
  ledger and skill consumers. SL-0 freezes the following behavior and public
  field additions before implementation.

`RULING_CLASSES` is the single closed vocabulary in `ruling_ledger.py`:
`round_local`, `contract_changing`, `roadmap_changing`, `release_rule`.
`PresidentFindingRuling.ruling_class` is an additive trailing field, preserving
the existing positional constructor. The new line is
`FINDING <id>: BLOCKING|DEFERRED <class> — <reason>`; the legacy line resolves
to `round_local` during the roadmap's compatibility window. Bind the window to
release metadata at delivery, not to a guessed future version. Unknown classes,
duplicate/foreign/missing ids and malformed terminal decisions fail the existing
format path. Preserve its one same-session format re-ask and typed cancellation.

The prompt consumes the current per-finding mapping, retaining seat provenance,
finding text, attachment diff, observed outcome and validated record digest.
All `finding_receipt` outcomes are residuals, including RED and GREEN. Invalid
bindings remain unresolved. Preserve foreign-attachment refusal and all unrelated
seat findings. A ruling is applicable only to its exact current candidate,
instruction/board/finding bindings and president authorization; missing or stale
bindings retain the hold. Do not merge findings solely because their text matches
when their attachments, receipt digests or authorization bindings differ.

`ruling_ledger.v1` is JSONL at `plans/rulings.jsonl`. An issued row contains ruling
id, class, repository-qualified PR, reviewed SHA, president model and
authorization identity, per-seat verdicts with actual model/vendor identities,
decision text, guard node id or `pending`, and the declared resolution bound.
A `guard_resolved` row references that issued ruling and a verified guard node.
Use explicit UTC bounds for pending guards, supplied as policy input; do not
invent commit-count or future-SHA deadlines. Already guarded rulings need no
pending bound. Fold rows without editing prior bytes. Guard results require
retained exact-head command/JUnit provenance, not a caller's `passed=true`.

The ledger checker verifies the byte prefix from every reachable ancestor and
every merge parent, uniqueness, resolution references, reviewed-SHA ancestry and
the guard's actual landing-head proof. Missing history or proof fails closed.
Pending within its declared bound is not expired; unresolved past the bound is
`unguarded`. A verified guard stays guarded. An unguarded ruling blocks a new
changing ruling of the same class, including multiple issued rows in one landing.

`RatificationPolicy.human_tier` is additive and defaults to `never`.
Unknown values refuse. Keep existing vendor/lens/consensus defaults. The resolver
returns a typed escalation decision using the existing blocker shape; it never
waits for a human synchronously. Attended release dispatch may require a human;
unattended dispatch retains a non-human hold with the ruling attached. The two
universal triggers remain load-bearing under every tier and shortfall setting.

## Lane Index & Dependencies

SL-0 — Frozen tests and content-TDD receipt
  Depends on: (none)
  Blocks: SL-1, SL-2, SL-3
  Parallel-safe: no

SL-1 — Ledger primitive and ancestor verification (roadmap Lane B)
  Depends on: SL-0
  Blocks: SL-2, SL-3
  Parallel-safe: no

SL-2 — Typed president resolution and human-tier integration (roadmap Lane A)
  Depends on: SL-0, SL-1
  Blocks: SL-3
  Parallel-safe: no

SL-3 — Documentation sweep and acceptance reducer (roadmap Lane B)
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

The two roadmap writer responsibilities are serialized because Lane A consumes
Lane B's checked ledger contract. There is no worker fanout or overlapping writer
ownership. Plan/manifest registration is a control artifact, not a runtime lane.

## Lanes

### SL-0 — Frozen tests and content-TDD receipt

- **Scope**: Freeze path-entered falsifiers and compatibility controls before production.
- **Owned files**: `phase-loop-runtime/tests/test_ratify_phase.py`, `phase-loop-runtime/tests/test_ruling_ledger.py`, `phase-loop-runtime/tests/ratify_content_tdd_adapter.py`, `.phase-loop/evidence/RATIFY/**`
- **Interfaces provided**: `RATIFY_RED_SUITE`, `content_tdd_receipt.v1`, IF-0-RATIFY-1 test shape.
- **Interfaces consumed**: PRESROUTE functions (pre-existing), IF-0-EXECFIND-1 (pre-existing), content-TDD primitives (pre-existing), retained Git history (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: Default-GREEN/activated-RED with `PHASE_LOOP_TDD_EXPECT_RATIFY=1`, distinct `RATIFY_CAPABILITY_VERSION`; no upstream marker may skip the new falsifiers. Assert the named production seam entered, then kill its mutation and restore the control.
  - test: Cover receipt partitioning with two identical prose findings carrying different receipts; RED/GREEN both reach the president; a foreign attachment remains refused. Exercise the real governed gate with a valid bound ruling and an otherwise agreeing board, not only pure helpers.
  - test: Cover every ruling class and legacy grammar, unknown class, stale candidate, omitted/duplicate ids, declined ruling, every human tier across attended/unattended and unanimous/non-unanimous/exhausted boards. An absent seat is not unanimity.
  - test: Real Git histories cover in-place edit, second-parent divergence, pending and resolved folds, same-class multirow landings, unverified guard results, stale reviewed SHA and unavailable ancestry. Positive controls admit ordinary sibling landings and unrelated classes without weakening existing floors.
  - impl: Record RED and restored controls, panel the tests-only bytes, and land them before production. Record a content-bound receipt; never pin predicted commits or test counts. Later test correction restarts this boundary.
  - verify: `PHASE_LOOP_TDD_EXPECT_RATIFY=1 PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_ratify_phase.py phase-loop-runtime/tests/test_ruling_ledger.py`.

### SL-1 — Ledger primitive and ancestor verification

- **Scope**: Implement the ledger's closed rows, folding, append operation and ancestry guard.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/ruling_ledger.py`, `phase-loop-runtime/src/phase_loop_runtime/plan_manifest.py`, `plans/rulings.jsonl`
- **Interfaces provided**: `RULING_CLASSES`, `RULING_LEDGER_ADMISSION`.
- **Interfaces consumed**: RATIFY_RED_SUITE, Git objects (pre-existing), retained guard-result proofs (pre-existing), manifest validation machinery (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: Run SL-0's ledger selectors; no frozen test edits.
  - impl: Add only the ruling-ledger check at the existing manifest validation boundary; preserve all lifecycle and authority-history prefixes. Loading, folding and validating do not execute recorded commands or issue approvals.
  - impl: A proposed candidate row may be checked against the actual landing head before publication; record landing facts only after they exist. Never require the row's containing commit to pre-exist itself. An empty ledger is valid, not a fabricated first ruling.
  - verify: `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_ruling_ledger.py phase-loop-runtime/tests/test_phase_loop_plan_manifest.py`.

### SL-2 — Typed president resolution and human-tier integration

- **Scope**: Resolve advisory residuals through a bound typed ruling, checked ledger and additive human tier.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/ratification_policy.py`, `phase-loop-runtime/src/phase_loop_runtime/gate_posture.py`
- **Interfaces provided**: `RATIFY_RESOLUTION` (typed ruling, receipt resolution and human-tier decision).
- **Interfaces consumed**: IF-0-EXECFIND-1 (pre-existing), RULING_LEDGER_ADMISSION, `release_guard.py` attended/unattended contracts (pre-existing; read-only).
- **Parallel-safe**: no.
- **Tasks**:
  - test: Run SL-0's prompt, parser, gate and escalation selectors; no frozen test edits.
  - impl: Restrict panel changes to president prompt/parser/result bindings and call sites in `invoke_board`; restrict governed changes to the president resolution/admission after receipt validation. Never change provider launch, transports, auth, monitoring, sandbox facts, retention, roster selection or foreign-attachment semantics.
  - impl: Retain the raw seat reports and all refusals. Only an applicable ruling can discharge a receipt hold; a BLOCKING disposition or an invalid/missing ruling retains it. A DEFERRED finding still participates in the ledger/class/human checks and must not erase unrelated dissent.
  - impl: Reuse `resolve_ratification_policy` for the additive field and preserve old constructors/JSON consumers. Verify that existing attended/unattended consumers carry the resolver's blocker shape without edits outside ownership. If integration requires changing `release_guard.py`, runner closeout or another owned lane, hold SL-2 and reconcile ownership before writing; do not add a parallel escalation system.
  - verify: `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests/test_ratify_phase.py phase-loop-runtime/tests/test_president_wiring.py phase-loop-runtime/tests/test_president_heartbeat_1001.py phase-loop-runtime/tests/test_president_ladder_config.py phase-loop-runtime/tests/test_ratification_policy.py phase-loop-runtime/tests/test_governed_review.py`.

### SL-3 — Documentation sweep and acceptance reducer

- **Scope**: Publish the reconciliation order and reduce the exact landed lane evidence.
- **Owned files**: `skills-src/codex/codex-plan-phase/SKILL.md`, `skills-src/codex/codex-execute-phase/SKILL.md`, `skills-src/claude/claude-plan-phase/SKILL.md`, `skills-src/claude/claude-execute-phase/SKILL.md`, `skills-src/gemini/gemini-plan-phase/SKILL.md`, `skills-src/gemini/gemini-execute-phase/SKILL.md`, `skills-src/opencode/opencode-plan-phase/SKILL.md`, `skills-src/opencode/opencode-execute-phase/SKILL.md`, `phase-loop-skills/*-plan-phase/**`, `phase-loop-skills/*-execute-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-plan-phase/**`, `phase-loop-runtime/src/phase_loop_runtime/skills_bundle/*-execute-phase/**`
- **Interfaces provided**: IF-0-RATIFY-1 acceptance evidence and four-harness reconciliation instructions.
- **Interfaces consumed**: RATIFY_RED_SUITE, RULING_LEDGER_ADMISSION, RATIFY_RESOLUTION, advisory-evidence ruling (pre-existing).
- **Parallel-safe**: no.
- **Tasks**:
  - test: Verify every shipped plan/execute skill carries the advisory receipt, president, ledger and author-owned guard order. The docs falsifier removes each step independently.
  - impl: Edit only canonical skill sources, then regenerate both existing bundle layers. Refuse an unexplained generated diff outside the declared skill subtrees.
  - impl: No README, CHANGELOG or release-notes change in this lane: this phase's documentation contract is the plan/execute reconciliation instruction, and release publication is separate. Reassess this no-doc-change decision after the runtime lanes without editing a concurrently owned release artifact.
  - verify: `python3 phase-loop-runtime/scripts/regenerate_skills_bundle.py`; `python3 phase-loop-runtime/scripts/sync_skills_bundle.py`; run the effective suite, content-TDD verifier, full non-dotfiles suite and whitespace check. Record omitted or degraded checks honestly; no installed qualification follows from source tests.
  - verify: Exact final bytes require the governed board, president and green required CI. Model substitutions are explicit and actual vendor counts are retained. Never claim four vendors with two OpenAI seats. Use the supported tool-enabled review route after agent-harness#1166 qualification; do not bypass it or replace it with an oversized packet.

## Execution Policy

- work-unit defaults: executor=`codex`, effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`
- SL-3: executor=`codex`, effort=`high`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`

## Execution Notes

No runtime lane starts on publication of this draft. Verify prerequisites,
the reviewed plan digest, its registration and ownership before dispatch.
SL-0 lands tests-only first; production preserves those files. SL-1 and SL-2
serialize their writer responsibilities, and SL-3 consumes both. Each material
revision receives fresh exact-byte review and required CI; earlier votes never
transfer. Append-only records are replayed onto current main without restoring
an old manifest. The normal board, president and merge guard remain required.

## Verification

The frontmatter suite is the implementation regression command. The SL-0 RED run
precedes production; the ordinary suite must be green after the lawful writers.
Record `ratify_content_tdd_adapter.py verify --repo . --landing-ref HEAD` against
the retained receipt, using the adapter's frozen interface. Run the full suite
with `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests` and
`-m "not dotfiles_integration"`, then `git diff --check`.

- `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 phase-loop-runtime/tests/ratify_content_tdd_adapter.py verify --repo . --landing-ref HEAD`
- `env -u PHASE_LOOP_TDD_EXPECT_HARDEN -u PHASE_LOOP_TDD_EXPECT_REVIEWTRUTH PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 -m pytest -q phase-loop-runtime/tests -m "not dotfiles_integration"`
- `git diff --check`

Before dispatch, validate the plan and command intake, verify the actual upstream
receipt interface and check current Claude ownership. No native fill under
heartbeat-only, model deadline, silence kill, broker bypass or policy-floor
lowering is authorized by this plan. No self-issued ledger row satisfies review.

## Acceptance Criteria

- [ ] EC-RATIFY-0 — proven by `PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests python3 phase-loop-runtime/tests/ratify_content_tdd_adapter.py verify --repo . --landing-ref HEAD` and runner-sealed `verification_evidence.v3`; falsified by a path-entered mutation admitting an unmatched anchor, missing retained RED/restored control, or changed frozen SL-0 blob.
- [ ] EC-RATIFY-1 — proven by `test_ratify_phase.py -k receipt_partition`; falsified by a path-entered gate mutation accepting an absent/stale ruling or interpreting advisory GREEN as a decision.
- [ ] EC-RATIFY-2 — proven by `test_ratify_phase.py -k ruling_classes`; falsified by a path-entered parser/admission mutation accepting an unknown class or a changing ruling without a checked row.
- [ ] EC-RATIFY-3 — proven by `test_ruling_ledger.py`; falsified by a path-entered admission mutation accepting a changed ancestor prefix, caller-invented guard pass, foreign reviewed SHA or expired same-class guard.
- [ ] EC-RATIFY-4 — proven by `test_ratify_phase.py -k human_tiers`; falsified by a path-entered escalation-consumer mutation permitting a universal-trigger bypass, synchronous wait or unattended human blocker.
- [ ] EC-RATIFY-5 — proven by `test_ratify_phase.py -k skill_reconciliation` plus both skill parity suites; falsified by path-entered delivery checks accepting removal of an ordered step from any shipped body.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: RATIFY runtime seams, `plans/rulings.jsonl`, plan/execute skill bundles
- evidence paths: `.phase-loop/evidence/RATIFY/**`, `plans/phase-plan-v10-RATIFY.md`
- redaction posture: `metadata_only`
- downstream handling: GOVSETUP consumes IF-0-RATIFY-1 only after acceptance; no downstream dispatch is implied by publishing this plan.
