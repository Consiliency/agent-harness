---
phase_loop_plan_version: 1
phase: EXECFIND
roadmap: specs/phase-plans-v10.md
roadmap_sha256: 19b9c36311c93d0534c4cab1187cfda59ee589ee2c904aa0b71b581d09daf87e
automation:
  suite_command:
    - bash
    - -lc
    - >-
      set -euo pipefail;
      uv run --project phase-loop-runtime python phase-loop-runtime/tests/execfind_content_tdd_adapter.py verify --repo . --landing-ref origin/main --receipt .phase-loop/evidence/EXECFIND/content-tdd-receipt.json;
      PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q
      phase-loop-runtime/tests/test_execfind_falsifier.py
      phase-loop-runtime/tests/test_governed_review.py;
      PYTHONPATH=phase-loop-runtime/src python3 -m phase_loop_runtime.cli validate-roadmap specs/phase-plans-v10.md;
      PYTHONPATH=phase-loop-runtime/src python3 -c 'from pathlib import Path; from phase_loop_runtime.goal_coverage import check_goal_coverage; r=check_goal_coverage(repo=Path("."), plan=Path("plans/phase-plan-v10-EXECFIND.md"), roadmap=Path("specs/phase-plans-v10.md")); assert not r.unreferenced_ids and not r.dangling_refs, r';
      uv run --project phase-loop-runtime ruff check phase-loop-runtime/src/phase_loop_runtime
---

# EXECFIND: Executable Findings

## Context

EXECFIND makes a blocking review finding a failing test the harness runs: a seat
attaches a `falsifier` block as text, the harness applies and runs it in a staged tree
under its own authorization identity; only a finding red on the reviewed head binds.
Seats never execute (agent-harness#935).

Current shape: `PanelLegResult` (`panel_invoker.py:904`) carries
non-field affordances attached with `object.__setattr__` and read through a property
defaulting to `None`, so a field-walking serializer (`dataclasses.asdict`, the golden)
never sees them — `attach_native_agent_request` (`panel_invoker.py:978`,
agent-harness#921) is the landed precedent the attachment copies.
`terminal_verdict` (`panel_invoker.py:1275`) is the seat-text parser the falsifier
parser sits beside and never edits. Review isolation is minted in `backing.py:964`
(`prepare_review_isolation_authorization`, `public_board_review.v1`, three isolation
flags fail-closed, agent-harness#737); the falsifier authorization mints the same way.
`stage_review_tree` (`review_stage.py:268`) materializes the writable independent clone
the falsifier runs inside. `collect_test_execution_evidence`
(`legible_evidence.py:2280`) is the JUnit/node/status-binding semantics the outcome
binding reuses (LEGIBLE-owned, not edited); EXECFIND's `FALSIFIER_OUTCOMES` deliberately
differs from that function's LEGIBLE outcome literals, so the falsifier reuses its
parse/binding mechanics without adopting its vocabulary. `_findings_from_panel`
(`governed_review.py:120`) emits whole-leg codes this phase keeps beside a new
per-finding decomposition. Brief inlining uses the `artifact_ref` seam
(`panel_invoker.py:1520`) under the 512 KiB transport cap (`review_stage.py:6`) and the
16 KiB `_BROKER_MAX_BYTES` soft warning (`backing.py:177`).

This plan touches only EXECFIND's roadmap Key files, edits no frozen surface, adds no
`Depends on` edge, and does not implement RATIFY/GOVSETUP, change seat isolation or the
completion grammar, or make falsifiers required by default. The `REVIEWTRUTH → EXECFIND`
edge is relaxed at criterion granularity (Execution Notes): EC-EXECFIND-1..-5 execute
now; EC-EXECFIND-6 consumes EC-REVIEWTRUTH-8's repair context (`runner.py` still passes
`apply_fix=None`) and is **dispatch-held** (SL-3) until EC-REVIEWTRUTH-8 is verified
complete on `main`.

## Interface Freeze Gates

- [ ] IF-0-EXECFIND-1 — the falsifier attachment shape plus the run outcome vocabulary,
  what RATIFY consumes. The day-one freeze spans both lanes: the golden fixture
  `phase-loop-runtime/tests/data/execfind_falsifier_attachment_v1.golden.json` is landed
  by SL-0 (Lane B tests-first) — Lane B builds against the outcome vocabulary, Lane A
  against the attachment shape, before either lands — and the new
  `advisor_board/CONTRACTS.md` section (SL-1) is the frozen prose artifact. Concrete
  freeze:
  - **Attachment dataclasses** (`panel_invoker.py`): `FindingFalsifier` = `finding_id: str`, `new_test_path: str` (= `phase-loop-runtime/tests/test_finding_<finding_id>.py`), `expected_nodeid: str`, `diff: str` (a unified diff creating that one new file); `FindingFalsifierAttachment` = `falsifiers: tuple[FindingFalsifier, ...]`, `finding_id` unique. Attached non-field via `attach_finding_falsifiers(leg, attachment) -> PanelLegResult` (`object.__setattr__` into `_finding_falsifiers`), read via the `finding_falsifiers` property (default `None`), invisible to `dataclasses.asdict` and the golden.
  - **Outcome vocabulary** (`falsifier.py`): `FALSIFIER_OUTCOMES: tuple[str, ...] = ("red_on_head", "green_on_head", "apply_failed", "node_missing", "error")` — the frozen set EC-EXECFIND-2 binds, EC-EXECFIND-3 decomposes on.
  - **Runner callable** (`falsifier.py`): `run_finding_falsifier(*, falsifier: FindingFalsifier, authorization: FalsifierIsolationAuthorization, repo: Path, wall_clock_s: float, output_cap_bytes: int) -> FalsifierRunResult`. `FalsifierIsolationAuthorization` is the additive `backing.py` identity (`public_board_falsifier.v1`, three isolation flags fail-closed). `FalsifierRunResult` = `outcome: str` (in `FALSIFIER_OUTCOMES`), `nodeid: str`, `red_output_digest: str | None`, `diff_digest: str`, `junit_path: str | None`, `detail: str | None`.
  - **`finding_falsifier.v1` record shape**: `schema` (str), `authorization_identity` (str = `"public_board_falsifier.v1"`), `finding_id` (str), `nodeid` (str), `outcome` (str in `FALSIFIER_OUTCOMES`), `red_output_digest` (lowercase sha256 hex, or `null` unless `red_on_head`), `diff_digest` (lowercase sha256 hex), `wall_clock_bound_s` (number), `output_cap_bytes` (int).
  - **Digest canonicalization** (both SHA-256, lowercase hex): `diff_digest = hashlib.sha256(falsifier.diff.encode("utf-8")).hexdigest()` over the attached diff bytes; `red_output_digest = hashlib.sha256(red_output_bytes).hexdigest()` where `red_output_bytes` is the failing node's captured stdout bytes followed by its captured stderr bytes, concatenated in that exact order from two separate captures (never a merged or interleaved stream), present only when `outcome == "red_on_head"`. The golden fixture carries a fixed RED-output byte fixture and its golden `red_output_digest`.
  - **Freeze verification**: `pytest -k attachment_matches_frozen_contract` in `test_execfind_falsifier.py` builds the attachment and a `finding_falsifier.v1` record, asserts keys/types equal the golden, `diff_digest` recomputes, `red_output_digest` recomputes from the golden's fixed RED-output byte fixture and equals its golden digest (so two implementations cannot disagree on the byte construction silently), `FALSIFIER_OUTCOMES` equals the frozen 5-tuple, and the attachment is absent from `dataclasses.asdict(leg)`. Consumed by SL-2 and RATIFY.

## Lane Index & Dependencies

SL-0 — Lane B tests-first stage (content-bound frozen corpus)
  Depends on: (none)
  Blocks: SL-1, SL-2
  Parallel-safe: no
SL-1 — Falsifier runner, authorization identity, staging seam (Lane A)
  Depends on: SL-0
  Blocks: SL-2
  Parallel-safe: no
SL-2 — Lane B implementation stage: grammar, parser, attachment, per-finding decomposition, brief, policy
  Depends on: SL-0, SL-1
  Blocks: SL-4
  Parallel-safe: no
SL-3 — EC-EXECFIND-6 fix-round wiring (DISPATCH-HELD until EC-REVIEWTRUTH-8 on main)
  Depends on: SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no
SL-4 — Documentation and phase reducer
  Depends on: SL-0, SL-1, SL-2
  Blocks: (none)
  Parallel-safe: no

## Lanes

### SL-0 — Lane B tests-first stage (content-bound frozen corpus)

- **Scope**: Lane B's first stage. Freeze the falsifiers and the IF-0-EXECFIND-1 golden fixture before any production edit, recording the content-bound receipt via `content_tdd_receipt.v1` (`phase_loop_runtime.tdd_receipts`), re-verified byte-equal at merge; no commit-topology. SL-2 may not edit these bytes; SL-1 consumes them.
- **Owned files**: `phase-loop-runtime/tests/test_execfind_falsifier.py`, `phase-loop-runtime/tests/test_governed_review.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/execfind_content_tdd_adapter.py`, `phase-loop-runtime/tests/data/execfind_falsifier_attachment_v1.golden.json`, `.phase-loop/evidence/EXECFIND/content-tdd-receipt.json`, `.phase-loop/evidence/EXECFIND/content-tdd-receipt.red.stdout.log`, `.phase-loop/evidence/EXECFIND/content-tdd-receipt.red.stderr.log`
- **Interfaces provided**: frozen EXECFIND falsifiers, the IF-0-EXECFIND-1 golden fixture, a `content_tdd_receipt.v1` receipt.
- **Interfaces consumed**: the pre-implementation attachment/parser/decomposition/brief behavior, `phase_loop_runtime.tdd_receipts`, and the `attach_native_agent_request` precedent (all pre-existing).
- **Parallel-safe**: no (tests-first boundary; SL-1 and SL-2 consume its frozen bytes and never edit them).
- **Tasks**:
  - test: In `test_execfind_falsifier.py`, land the RED cases the EC-EXECFIND-1/-2/-4 acceptance items name (no falsifier restated in prose); pin these `-k` node identifiers later ECs select: `grammar`, `parser_reject_outside_tests`, `parser_reject_modify_existing`, `parser_reject_no_nodeid`, `parser_reject_double_claim`, `attachment_byte_neutral`, `attachment_matches_frozen_contract`, `outcome_vocabulary`, `apply_failed`, `red_on_head`, `green_on_head`, `node_missing`, `bound_expiry_error`, `no_network_no_credentials`, `staged_tree_only`, `only_named_node_runs`, `seat_tool_attempt_refused`, `authorization_identity`, `brief_teaches_form`, `inline_fixture_artifact_ref`, `brokered_text_only`, `prompt_over_cap_refused`.
  - test: In `test_governed_review.py`, land the EC-EXECFIND-3/-5 RED cases; pin `-k` nodes `finding_bound`, `finding_unbound`, `finding_receipt`, `finding_receipt_digest_unresolved`, `finding_prose`, `degraded_leg_whole_code`, `falsifier_policy_optional`, `falsifier_policy_required_refuses_prose`. In `test_advisor_board_golden.py`, assert the golden bytes are unchanged by an attached falsifier; do not edit golden data.
  - test: Add `execfind_content_tdd_adapter.py`, a bounded wrapper over `phase_loop_runtime.tdd_receipts` (mirroring `proofgate_content_tdd_adapter.py`): a `record-red` subcommand running the frozen tests under `PHASE_LOOP_TDD_EXPECT_EXECFIND=1`, emitting `RED_ANCHOR_MARKER` plus a distinct `EXECFIND_RED::<case-id>` marker, exiting 1, and calling `record_content_tdd_receipt`; a `verify` subcommand calling `verify_content_tdd_receipt`. Do not edit `tdd_receipts.py`. Recording integrity (named as requirements, not by-copy): an unexpected PASS (pytest XPASS/unexpected-pass, or a node that neither failed nor errored) MUST fail recording, never be accepted as RED; each `EXECFIND_RED::<case-id>` marker MUST match by exact per-case count, never loose substring; an `ImportError` or other unrelated exception from a PRESENT module MUST propagate, never be laundered into a red marker or read as capability absence; a rejected recording MUST write no receipt (soundness gates precede the write); every expected case MUST have executed — a missing, skipped, or deselected case, or a collection-only failure where no case ran, MUST fail recording, never pass as RED (exact marker counts and no-unexpected-pass do not by themselves prove a case ran); AND `verify` MUST re-validate the frozen RED log's soundness (exact markers, no unexpected pass, all expected cases present), not trust that record-time refused. Pin adapter self-test `-k` nodes `unexpected_pass_refused`, `marker_exact_match_only`, `unrelated_exception_propagates`, `importerror_not_capability_absence`, `rejected_recording_no_receipt`, `verify_rescans_red_log`, `every_expected_case_ran`, `red_output_digest_golden`.
  - impl: Run `execfind_content_tdd_adapter.py record-red` to capture RED stdout/stderr and each frozen test's sha256 into `.phase-loop/evidence/EXECFIND/content-tdd-receipt.json` against the pre-implementation base; bind no SHA, count, or tree shape. Land the tests, adapter, golden fixture, and receipt before any SL-1/SL-2 production edit. A later test correction restarts SL-0.

### SL-1 — Falsifier runner, authorization identity, staging seam (Lane A)

- **Scope**: Add `falsifier.py` (apply + run a falsifier in a staged tree under a minted `public_board_falsifier.v1` identity, bind the outcome), the additive identity in `backing.py`, the `review_stage.py` seam, and the IF-0-EXECFIND-1 freeze in `CONTRACTS.md`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/falsifier.py`, `phase-loop-runtime/src/phase_loop_runtime/review_stage.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- **Interfaces provided**: IF-0-EXECFIND-1 outcome half (`FALSIFIER_OUTCOMES`, `run_finding_falsifier`, `FalsifierRunResult`, `finding_falsifier.v1` record), `FalsifierIsolationAuthorization`, and the EC-EXECFIND-6 **pure** helpers `bound_findings_repair_context`/`president_blocked_by_red_findings` — pure functions over findings with no dependency on REVIEWTRUTH's `apply_fix`/repair-context wiring, so the executable wave (SL-0..SL-2) never acquires the held -6 dependency.
- **Interfaces consumed**: frozen EXECFIND falsifiers (SL-0); `stage_review_tree`, the `ReviewIsolationAuthorization` mint pattern (agent-harness#737), `collect_test_execution_evidence` semantics (all pre-existing, not edited).
- **Parallel-safe**: no (SL-2 consumes its frozen interface).
- **Tasks**:
  - impl: In `falsifier.py`, define `run_finding_falsifier`: `git apply` the diff inside a `stage_review_tree` clone under the minted authorization, run the named node with `--junitxml` under `wall_clock_s`/`output_cap_bytes`, and bind the outcome to `FALSIFIER_OUTCOMES` reusing `collect_test_execution_evidence` semantics (`red_on_head` only when the node ran and failed; a bound/cap expiry is `error`; a diff that is not exactly one NEW `test_finding_<finding_id>.py` is `apply_failed`), and emit the `finding_falsifier.v1` record with both digests. Add the two EC-EXECFIND-6 **pure** helpers (functions over findings only; they import no REVIEWTRUTH repair wiring, keeping the executable wave independent of the held -6 gate).
  - impl: In `backing.py`, add `prepare_falsifier_isolation_authorization` beside `prepare_review_isolation_authorization` (minting `public_board_falsifier.v1`, three isolation flags fail-closed, same lease discipline; review authorization unedited). In `review_stage.py`, add the additive keyword-only bounded staged-run seam (no live tree or credentials exposed; `stage_review_tree` unchanged). Add the `CONTRACTS.md` ABDFALSIFY section by the ABDPRES amendment path, freezing the attachment shape, outcome vocabulary, and `finding_falsifier.v1` record.

### SL-2 — Lane B implementation stage: grammar, parser, attachment, per-finding decomposition, brief, policy

- **Scope**: Parse the `falsifier` block beside `terminal_verdict`, attach it non-field to `PanelLegResult`, decompose per finding, teach the brief the falsifier form + inline fixtures, and add the `falsifier_policy`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`
- **Interfaces provided**: the falsifier-block parser, `FindingFalsifier`/`FindingFalsifierAttachment`, `attach_finding_falsifiers`; per-finding decomposition (`finding_bound`/`finding_unbound`/`finding_receipt`/`finding_prose`) beside the whole-leg codes; the `falsifier_policy`; the brief instruction and inline-fixture support.
- **Interfaces consumed**: IF-0-EXECFIND-1 (SL-1); the `attach_native_agent_request` pattern (`panel_invoker.py:978`), `terminal_verdict` (`:1275`), and `artifact_ref` seam (`:1520`) — all pre-existing, not edited.
- **Parallel-safe**: no (consumes SL-1's frozen interface; serializes after any REVIEWTRUTH landing rewriting the same `governed_review.py` lines).
- **Tasks**:
  - impl: In `panel_invoker.py`, add the falsifier-block parser as a new function beside `terminal_verdict` (unedited), the `FindingFalsifier`/`FindingFalsifierAttachment` dataclasses, and `attach_finding_falsifiers` mirroring `attach_native_agent_request` (`object.__setattr__` into `_finding_falsifiers`; a `finding_falsifiers` property defaulting to `None`). The parser rejects a diff outside `phase-loop-runtime/tests/`, a modification of an existing file, a no-node-id block, and a double-claimed block before the runner sees it.
  - impl: In `governed_review.py`, extend `_findings_from_panel` at an additive named seam to emit one `ReviewFinding` per finding — `finding_bound` (`red_on_head`, block), `finding_unbound` (`green_on_head`, warn, to the president), `finding_receipt` (receipt artifact by digest, block pending the president's ruling, rejected on an unresolved digest), `finding_prose` (no falsifier, warn) — keeping whole-leg codes for degraded/non-conforming legs. Add the `falsifier_policy` (`optional | required`, default `optional`) gating a prose blocking finding. Do not rewrite an existing whole-leg branch.
  - impl: In `advisor_board/composition.py`, add the brief instruction teaching the falsifier form and inline-fixture path (named fixtures as extra `artifact_ref` paths under the 512 KiB cap, 16 KiB soft warning kept); brokered seats stay text-only, `context_refs` metadata-only.

### SL-3 — EC-EXECFIND-6 fix-round wiring (DISPATCH-HELD until EC-REVIEWTRUTH-8 on main)

- **Scope**: Wire EC-EXECFIND-6 into `runner.py` via REVIEWTRUTH's repair-context seam — carry each bound finding as node id + RED digest, re-run the node after repair, refuse a president invocation while any bound finding is red. **Dispatch-held**: `runner.py` still passes `apply_fix=None`, so EC-REVIEWTRUTH-8 must be verified complete on `main` first; not in the -1..-5 wave.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/runner.py`, `phase-loop-runtime/tests/test_execfind_fix_round.py`
- **Interfaces provided**: the fix-round repair context (bound-finding node ids + RED digests); the president-refusal-while-red guard at the president-invocation site.
- **Interfaces consumed**: SL-1's `bound_findings_repair_context`/`president_blocked_by_red_findings`; SL-2's per-finding decomposition; EC-REVIEWTRUTH-8's `runner.py` repair-context / `apply_fix` seam (external, landed on `main` first).
- **Parallel-safe**: no (held; lands only through REVIEWTRUTH's `runner.py` seam after EC-REVIEWTRUTH-8; own tests-first sub-stage).
- **Tasks**:
  - test: In `test_execfind_fix_round.py`, freeze the EC-EXECFIND-6 RED cases; pin `-k` nodes `repair_context_node_ids`, `president_refused_while_red`.
  - impl: At the additive `runner.py` repair-context seam, pass each bound finding's node id and RED digest into the repair context, re-run the node after repair, and refuse a president prompt while any bound finding is red via `president_blocked_by_red_findings`. Do not rewrite an existing line outside that seam.

### SL-4 — Documentation and phase reducer

- **Scope**: Refresh the docs catalog, update cross-cutting docs this phase touches, and reduce the phase. This phase amends no spec (`no_spec_delta`; the roadmap is not EXECFIND's to amend).
- **Owned files**: `CHANGELOG.md`, `.claude/docs-catalog.json`
- **Interfaces provided**: (none)
- **Interfaces consumed**: (none)
- **Parallel-safe**: no (terminal reducer; reduces SL-0/SL-1/SL-2).
- **Depends on**: SL-0, SL-1, SL-2
- **Tasks**:
  - docs: Rescan the docs catalog (`python3 "$(git rev-parse --show-toplevel)/.claude/skills/_shared/scaffold_docs_catalog.py" --rescan`; if absent, record "docs-catalog rescan helper unavailable; manual catalog audit" and proceed).
  - docs: Add the CHANGELOG note for the falsifier runner, attachment channel, per-finding decomposition, brief instruction, and `falsifier_policy`; record any catalog file skipped.
  - verify: Assert no spec touched (`git diff --exit-code -- specs/phase-plans-v10.md`), then run repo doc linters if configured; else no-op.

## Execution Policy

- work-unit defaults: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- execute: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-1: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-2: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-3: effort=`high`, work-unit=`lane_execute`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`
- SL-4: effort=`medium`, work-unit=`phase_reducer`, unsupported=`block`, inherit-default=`false`, policy-source=`phase plan`

## Execution Notes

- **Binding ruling — concurrency on PRESROUTE and EXECFIND** (agent-harness#935, maintainer 2026-09-21; the roadmap Execution Notes are authority): no `Depends on` edge is added and no phase edited — declared overlap plus the touch-shape falsifier suffices. `HARDEN → EXECFIND` is satisfied by the landed isolation-authorization mechanism (`backing.py`, `public_board_review.v1`, agent-harness#737), not HARDEN's completion or EC-HARDEN-5. `REVIEWTRUTH → EXECFIND` is relaxed at criterion granularity: EC-EXECFIND-1's precedent (agent-harness#921) is landed, EC-EXECFIND-2 mints its own `public_board_falsifier.v1`, EC-EXECFIND-3 lands only through the named `governed_review.py` seam serialized after any REVIEWTRUTH landing rewriting the same lines, and EC-EXECFIND-6 (SL-3) is dispatched only after EC-REVIEWTRUTH-8 is verified complete on `main`.
- **Dispatch holds**: SL-3 is held pending EC-REVIEWTRUTH-8 on `main`. The executable wave is SL-0 → SL-1 → SL-2 → SL-4 (EC-EXECFIND-0..-5); SL-3 lands later through REVIEWTRUTH's `runner.py` seam. SL-4 reduces only the executable wave (not SL-3, which carries its own docs later).
- **Touch-shape falsifier (named seams)**: `panel_invoker.py`, `governed_review.py`, `backing.py`, `composition.py`, `runner.py` are shared with open HARDEN/REVIEWTRUTH/LEGLIFE/RESIDUAL phases. A landing PR whose diff deletes or rewrites an existing line of a shared owned file OUTSIDE its named seams fails the phase. Named seams (all additive, no existing line rewritten): in `panel_invoker.py`, the new parser function beside `terminal_verdict`, the attachment dataclasses, and `attach_finding_falsifiers`; in `governed_review.py`, the per-finding branch in `_findings_from_panel` and the `falsifier_policy`; in `backing.py`, the additive identity; in `composition.py`, the brief instruction; in `runner.py`, the repair-context seam (SL-3, held). Every other touch is a new file or the additive `review_stage.py` seam.
- **Lane B two stages (tests-first ownership)**: SL-0 is Lane B's tests-first stage (owning the tests, adapter, golden fixture, receipt); SL-2 is its implementation stage. EC-EXECFIND-0's freeze forbids SL-2 from editing the SL-0 test bytes (re-verified byte-equal at merge); SL-1 consumes them. The split keeps Lane B's test ownership while avoiding a Lane A↔Lane B cycle.
- **Single-writer files**: each lane's Owned-files set is its sole-writer set; no file is owned by two lanes (SL-2: `panel_invoker.py`/`governed_review.py`/`composition.py`; SL-1: `falsifier.py`/`review_stage.py`/`backing.py`/`CONTRACTS.md`; SL-0: the three test files/adapter/golden/receipt; SL-3 held: `runner.py`/`test_execfind_fix_round.py`; SL-4: `CHANGELOG.md`/`.claude/docs-catalog.json`).
- **Known destructive changes**: none — every lane is additive; no lane deletes a file another produces. `tdd_receipts.py`, `terminal_verdict`, `stage_review_tree`, the review authorization, and the golden data file are not edited.
- **Expected add/add conflicts**: none (SL-0 stubs no source file a later lane replaces). **SL-0 re-exports**: none (SL-0 owns only tests, the adapter, the golden fixture, and receipt evidence; no package `__init__` symbol).
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/falsifier.py`, `phase-loop-runtime/src/phase_loop_runtime/review_stage.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/composition.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- evidence paths: `plans/phase-plan-v10-EXECFIND.md`, `plans/manifest.json`, `phase-loop-runtime/tests/data/execfind_falsifier_attachment_v1.golden.json`, `.phase-loop/evidence/EXECFIND/content-tdd-receipt.json`
- redaction posture: `metadata_only`
- downstream handling: none; roadmap bytes remain unchanged and RATIFY consumes IF-0-EXECFIND-1

## Verification

Run after the executable lanes merge; `automation.suite_command` is the effective suite (pytest targets are RED-first on base until the impl lands):

```bash
uv run --project phase-loop-runtime python phase-loop-runtime/tests/execfind_content_tdd_adapter.py verify --repo . --landing-ref origin/main --receipt .phase-loop/evidence/EXECFIND/content-tdd-receipt.json
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py phase-loop-runtime/tests/test_governed_review.py
```

Plan-artifact checks (green now): `validate_plan_doc.py`, `validate-roadmap`, `plan_manifest.validate_manifest`, `validate_plan_dispatch_hints` (empty), `goal_coverage.check_goal_coverage` (clean), word count ≤ 3000, `git diff --exit-code -- specs/phase-plans-v10.md`, `git diff --check`.

## Acceptance Criteria

- [ ] EC-EXECFIND-0 — proven by `uv run --project phase-loop-runtime python phase-loop-runtime/tests/execfind_content_tdd_adapter.py verify --repo . --landing-ref origin/main --receipt .phase-loop/evidence/EXECFIND/content-tdd-receipt.json` (recomputes each frozen test's sha256 against the `content_tdd_receipt.v1` receipt via `phase_loop_runtime.tdd_receipts.verify_content_tdd_receipt`); falsified by a one-byte mutation to any frozen test or a stripped receipt/RED log.
- [ ] EC-EXECFIND-1 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py -k "grammar or parser_reject or attachment_byte_neutral or attachment_matches_frozen_contract"`; falsified by a path-entered mutation defeating any node in that selector.
- [ ] EC-EXECFIND-2 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py -k "apply_failed or red_on_head or green_on_head or node_missing or bound_expiry_error or no_network_no_credentials or staged_tree_only or only_named_node_runs or seat_tool_attempt_refused or authorization_identity or outcome_vocabulary"`; falsified by a path-entered mutation defeating any node in that selector.
- [ ] EC-EXECFIND-3 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_governed_review.py -k "finding_bound or finding_unbound or finding_receipt or finding_receipt_digest_unresolved or finding_prose or degraded_leg_whole_code"`; falsified by a path-entered mutation defeating any node in that selector.
- [ ] EC-EXECFIND-4 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py -k "brief_teaches_form or inline_fixture_artifact_ref or brokered_text_only or prompt_over_cap_refused"`; falsified by a path-entered mutation defeating any node in that selector.
- [ ] EC-EXECFIND-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_governed_review.py -k "falsifier_policy_optional or falsifier_policy_required_refuses_prose"`; falsified by a path-entered mutation defeating either node in that selector.
- [ ] EC-EXECFIND-6 — **DISPATCH-HELD (SL-3) until EC-REVIEWTRUTH-8 is verified complete on `main`**; proven, when dispatched, by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_fix_round.py -k "repair_context_node_ids or president_refused_while_red"`; falsified by a path-entered mutation defeating either node in that selector.
