---
phase_loop_plan_version: 1
phase: EXECFIND
roadmap: specs/phase-plans-v10.md
roadmap_sha256: c446c22154e83cf629cbaa5d2f2c46abd56b7b16e535f2faba41262351187526
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

Current shape: `PanelLegResult` (`panel_invoker.py`) carries
non-field affordances attached with `object.__setattr__` and read through a property
defaulting to `None`, so a field-walking serializer (`dataclasses.asdict`, the golden)
never sees them — `attach_native_agent_request` (`panel_invoker.py`,
agent-harness#921) is the landed precedent the attachment copies.
`terminal_verdict` (`panel_invoker.py`) is the seat-text parser the falsifier
parser sits beside, never edited. Review isolation is minted in `backing.py:964`
(`prepare_review_isolation_authorization`, `public_board_review.v1`, three isolation
flags fail-closed, agent-harness#737); the falsifier authorization mints the same way.
`stage_review_tree` (`review_stage.py:268`) materializes the writable clone the falsifier
runs in. `collect_test_execution_evidence`
(`legible_evidence.py:2280`) is the JUnit/node/status-binding semantics the outcome
binding reuses (LEGIBLE-owned, not edited); EXECFIND's `FALSIFIER_OUTCOMES` deliberately
differs from that function's LEGIBLE literals — mechanics reused, vocabulary not.
`_findings_from_panel` (`governed_review.py:120`) emits whole-leg codes this phase keeps
beside a new per-finding decomposition. The sealed brief is
`_REVIEW_INSTRUCTIONS`/`_mode_instructions` (`panel_invoker.py`), staged as
`review-instructions.md` (`composition.py` is board-seating only, no brief text); brief
inlining uses the `artifact_ref` seam (`panel_invoker.py`) under the 512 KiB transport cap
(`review_stage.py:6`) and the 16 KiB `_BROKER_MAX_BYTES` soft warning (`backing.py:177`).
`governed_board_gate` owns the canonical repository authority and receives the exact
`reviewed_sha`; after `invoke_board` returns it is the only place that can run an
attached falsifier and hand its outcome to `_findings_from_panel`. The current
`_gate_result_from_panel` call supplies neither the repository nor run results.

This plan touches only EXECFIND's roadmap Key files, edits no frozen surface, adds no
`Depends on` edge, and does not implement RATIFY/GOVSETUP, change seat isolation or the
completion grammar, or make falsifiers required by default. The `REVIEWTRUTH → EXECFIND`
edge is relaxed at criterion granularity (Execution Notes): EC-EXECFIND-1..-5 execute
now; EC-EXECFIND-6 is **dispatch-held** (SL-3) until EC-REVIEWTRUTH-8 is verified
complete on `main`.

## Interface Freeze Gates

- [ ] IF-0-EXECFIND-1 — the falsifier attachment shape plus the run outcome vocabulary
  (what RATIFY consumes). The day-one freeze spans both lanes: the golden fixture
  `phase-loop-runtime/tests/data/execfind_falsifier_attachment_v1.golden.json` is landed
  by SL-0 (Lane B tests-first) — Lane B builds against the outcome vocabulary, Lane A
  against the attachment shape, before either lands — and the new
  `advisor_board/CONTRACTS.md` section (SL-1) is the frozen prose artifact. Concrete
  freeze:
  - **Attachment dataclasses** (`panel_invoker.py`): `FindingFalsifier` = `finding_id: str`, `new_test_path: str` (= `phase-loop-runtime/tests/test_finding_<finding_id>.py`), `expected_nodeid: str` (must start with `new_test_path + "::"` and have a non-empty node suffix), `diff: str` (a unified diff creating that one new file); `FindingFalsifierAttachment` = `falsifiers: tuple[FindingFalsifier, ...]`, `finding_id` unique. Attached non-field via `attach_finding_falsifiers(leg, attachment) -> PanelLegResult` (`object.__setattr__` into `_finding_falsifiers`), read via the `finding_falsifiers` property (default `None`), invisible to `dataclasses.asdict` and the golden.
  - **Outcome vocabulary** (`falsifier.py`): `FALSIFIER_OUTCOMES: tuple[str, ...] = ("red_on_head", "green_on_head", "apply_failed", "node_missing", "error")` — the frozen set EC-EXECFIND-2 binds, EC-EXECFIND-3 decomposes on.
  - **Runner callable** (`falsifier.py`): `run_finding_falsifier(*, falsifier: FindingFalsifier, seat_key: str, authorization: FalsifierIsolationAuthorization, repo: Path, wall_clock_s: float, output_cap_bytes: int) -> FalsifierRunResult`. `FalsifierIsolationAuthorization` is the additive `backing.py` identity (`public_board_falsifier.v1`, three isolation flags fail-closed) and binds the exact `reviewed_sha`. `FalsifierRunResult` = `outcome: str` (in `FALSIFIER_OUTCOMES`), `nodeid: str`, `red_output_digest: str | None`, `diff_digest: str`, `junit_path: str | None`, `detail: str | None`, `record: dict[str, object]` (the metadata-only `finding_falsifier.v1` record; it takes `seat_key` from the board leg and `reviewed_sha` from the authorization, and the caller computes its canonical JSON digest). This return value makes the receipt available without writing to the live source tree.
  - **Run-result binding** (`governed_review.py`): `governed_board_gate` parses each usable leg's attachment after the board returns, refuses more than four falsifiers per leg or twelve per board before starting any run, mints `FalsifierIsolationAuthorization` over the canonical repository and `reviewed_sha`, runs each admitted falsifier under that identity, and passes `falsifier_runs: Mapping[tuple[str, str], FalsifierRunBinding] | None = None` as a keyword-only argument through `_gate_result_from_panel` to `_findings_from_panel`. The tuple key is `(seat_key, finding_id)`; `FalsifierRunBinding` is an additive dataclass in `governed_review.py` with `seat_key: str`, `finding_id: str`, `reviewed_sha: str`, `result: FalsifierRunResult`, and `record_digest: str` (the canonical digest of `result.record`). Neither binding nor mapping is a field on `PanelLegResult` or `PanelResult`. `_findings_from_panel` already receives the gate's expected `reviewed_sha`; at its direct-injection seam, before classifying *any* outcome, it verifies the mapping key equals the binding's seat/finding fields, the binding and record SHA equal that expected SHA, the record's `seat_key` and `finding_id` equal that key, the record's `nodeid` and `diff_digest` equal that seat/finding attachment's `expected_nodeid` and SHA-256 of `diff`, `record_digest` recomputes from `result.record`, and the result's `outcome`, `nodeid`, `diff_digest`, and `red_output_digest` equal the corresponding record fields. The record schema and authorization identity must equal their frozen literals; a missing, duplicate, or mismatched attachment holds. These comparisons bind a result to the board seat, finding, reviewed tree and exact offered test, rather than only checking a wrapper against its own contents. It classifies only from the verified record. An absent or mismatched binding holds as `error`, never as `red_on_head` or `green_on_head`. Before staging, verify that the canonical source is clean at that SHA; after staging and before applying the diff, verify the staged materialized path set, bytes, symlink targets, and executable bits match the reviewed Git tree exactly, including refusal of extra files even if ignored. `stage_review_tree` overlays the source working tree, so a matching staged HEAD alone is insufficient; drift yields an `error` receipt and a hold.
  - **`finding_falsifier.v1` record shape**: `schema` (str = `"finding_falsifier.v1"`), `authorization_identity` (str = `"public_board_falsifier.v1"`), `seat_key` (str), `reviewed_sha` (40-character Git SHA str), `finding_id` (str), `nodeid` (str), `outcome` (str in `FALSIFIER_OUTCOMES`), `red_output_digest` (lowercase sha256 hex, or `null` unless `red_on_head`), `diff_digest` (lowercase sha256 hex), `wall_clock_bound_s` (float), `output_cap_bytes` (int).
  - **Digest canonicalization** (SHA-256, lowercase hex): `diff_digest = hashlib.sha256(falsifier.diff.encode("utf-8")).hexdigest()` over the attached diff bytes; `red_output_digest = hashlib.sha256(red_output_bytes).hexdigest()` where `red_output_bytes` is the failing node's captured stdout bytes followed by its captured stderr bytes, concatenated in that exact order from two separate captures (never a merged or interleaved stream), present only when `outcome == "red_on_head"`; `record_digest = hashlib.sha256(json.dumps(result.record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()`. The golden fixture carries `record.diff_digest`, `record.red_output_digest`, top-level `record_digest`, and fixed RED-output stdout/stderr bytes.
  - **Freeze verification**: `pytest -k attachment_matches_frozen_contract` in `test_execfind_falsifier.py` builds the attachment, `FalsifierRunResult`, `FalsifierRunBinding`, and a `finding_falsifier.v1` record, asserts their field sets and types equal the frozen shapes, including the record's board `seat_key` and authorization `reviewed_sha`, `diff_digest` recomputes, `red_output_digest` recomputes from the golden's fixed RED-output byte fixture, and the fixed golden record recomputes to the golden `record_digest`; `FALSIFIER_OUTCOMES` equals the frozen 5-tuple, and the attachment is absent from `dataclasses.asdict(leg)`. Consumed by SL-2 and RATIFY.

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

- **Scope**: Lane B's first stage. Freeze the falsifiers and the IF-0-EXECFIND-1 golden fixture before any production edit, recording the content-bound receipt via `content_tdd_receipt.v1` (`phase_loop_runtime.tdd_receipts`), re-verified byte-equal at merge; no commit-topology. SL-2 cannot edit these bytes; SL-1 consumes them.
- **Owned files**: `phase-loop-runtime/tests/test_execfind_falsifier.py`, `phase-loop-runtime/tests/test_governed_review.py`, `phase-loop-runtime/tests/test_advisor_board_golden.py`, `phase-loop-runtime/tests/execfind_content_tdd_adapter.py`, `phase-loop-runtime/tests/data/execfind_falsifier_attachment_v1.golden.json`, `.phase-loop/evidence/EXECFIND/content-tdd-receipt.json`, `.phase-loop/evidence/EXECFIND/content-tdd-receipt.red.stdout.log`, `.phase-loop/evidence/EXECFIND/content-tdd-receipt.red.stderr.log`
- **Interfaces provided**: frozen EXECFIND falsifiers, the IF-0-EXECFIND-1 golden fixture, a `content_tdd_receipt.v1` receipt.
- **Interfaces consumed**: the pre-implementation attachment/parser/decomposition/brief behavior, `phase_loop_runtime.tdd_receipts`, the `attach_native_agent_request` precedent (all pre-existing).
- **Parallel-safe**: no (tests-first boundary; SL-1 and SL-2 consume its frozen bytes and never edit them).
- **Tasks**:
  - test: In `test_execfind_falsifier.py`, land the RED cases the EC-EXECFIND-1/-2/-4 acceptance items name (no falsifier restated in prose); pin these `-k` node identifiers later ECs select: `grammar`, `parser_reject_outside_tests`, `parser_reject_modify_existing`, `parser_reject_no_nodeid`, `parser_reject_foreign_nodeid`, `parser_reject_double_claim`, `attachment_byte_neutral`, `attachment_matches_frozen_contract`, `outcome_vocabulary`, `apply_failed`, `red_on_head`, `green_on_head`, `node_missing`, `bound_expiry_error`, `no_network_no_credentials`, `staged_tree_only`, `staged_overlay_drift_error`, `staged_untracked_extra_error`, `staged_ignored_extra_error`, `staged_symlink_retarget_error`, `staged_exec_bit_drift_error`, `only_named_node_runs`, `seat_tool_attempt_refused`, `authorization_identity`, `brief_teaches_form`, `inline_fixture_artifact_ref`, `brokered_text_only`, `prompt_over_cap_refused`. `staged_overlay_drift_error` mutates a tracked source file after the clean-source preflight but before `stage_review_tree` overlays it; staged HEAD still matches `reviewed_sha`, while staged content differs. The four adjacent staged-drift nodes inject an untracked extra, a Git-ignored extra, a symlink retarget, and an executable-bit flip into the materialized staged tree after staging and before applying the diff. Each must produce `error` and invoke no test node; Git status/HEAD checks alone cannot satisfy them.
  - test: In `test_governed_review.py`, land the EC-EXECFIND-3/-5 RED cases; pin `-k` nodes `finding_bound`, `finding_unbound`, `finding_receipt`, `finding_receipt_digest_unresolved`, `falsifier_count_bound`, `finding_prose`, `degraded_leg_whole_code`, `falsifier_policy_optional`, `falsifier_policy_required_refuses_prose`. The `finding_bound` and `finding_unbound` nodes must exercise `governed_board_gate` from an attached text diff through the harness-run falsifier to the reduced finding at the exact reviewed SHA; the receipt nodes reject a missing or mismatched record digest and a missing/drifted reviewed SHA. `finding_receipt_digest_unresolved` also injects missing, wrong-key, bad-digest, foreign binding SHA, cross-finding, cross-seat, wrong record SHA, wrong nodeid, wrong diff, wrong schema, wrong authorization, and a separate result/record mismatch for each of `outcome`, `nodeid`, `diff_digest`, and `red_output_digest` directly into `_findings_from_panel(..., reviewed_sha=..., falsifier_runs=...)` for both `red_on_head` and `green_on_head`. A valid binding must first classify as bound/unbound; every invalid case must emit `finding_receipt` with block severity and `record_digest=unresolved` in its reason, never bound/unbound. `finding_receipt` separately pins a verified apply/node/error digest in the reason. This does not use an invalid digest as evidence. `falsifier_count_bound` supplies five attachments on one leg and thirteen across a four-seat board distributed 4+4+4+1, asserting each case holds before any staged run; it also supplies exactly four on one leg and twelve across a board distributed 4+4+4, asserting every admitted node runs. This isolates the per-leg and aggregate caps and both boundary inclusions. In `test_advisor_board_golden.py`, assert the golden bytes are unchanged by an attached falsifier; do not edit golden data.
  - test: Add `execfind_content_tdd_adapter.py`, a bounded wrapper over `phase_loop_runtime.tdd_receipts` (mirroring `proofgate_content_tdd_adapter.py`): a `record-red` subcommand running the frozen tests under `PHASE_LOOP_TDD_EXPECT_EXECFIND=1`, emitting `RED_ANCHOR_MARKER` plus a distinct `EXECFIND_RED::<case-id>` marker, exiting 1, and calling `record_content_tdd_receipt`; a `verify` subcommand calling `verify_content_tdd_receipt`. Do not edit `tdd_receipts.py`. Recording integrity (named as requirements, not by-copy): an unexpected PASS (pytest XPASS/unexpected-pass, or a node that neither failed nor errored) MUST fail recording, never be accepted as RED; each `EXECFIND_RED::<case-id>` marker MUST match by exact per-case count, never loose substring; an `ImportError` or other unrelated exception from a PRESENT module MUST propagate, never be laundered into a red marker or read as capability absence; a rejected recording MUST write no receipt (soundness gates precede the write); every expected case MUST have executed — a missing, skipped, or deselected case, or a collection-only failure where no case ran, MUST fail recording, never pass as RED (exact marker counts and no-unexpected-pass do not by themselves prove a case ran); the receipt's `test_files` inventory MUST equal the full frozen corpus exactly (no file dropped or added) and every frozen node id MUST be present in the receipt's recorded RED nodeids (a dropped file makes EC-EXECFIND-0's byte-equality pass vacuously over the survivors — proofgate's `receipt_paths != EXPECTED_FREEZE_FILES` and "missing canonical node" guards); AND `verify` MUST re-validate the frozen RED log's soundness (exact markers, no unexpected pass, all expected cases present, inventory exact), not trust that record-time refused. These nine adapter self-tests live in the collected file `test_execfind_falsifier.py` (so the `suite_command` runs them and EC-EXECFIND-0 selects them, below), pinned `-k` nodes `unexpected_pass_refused`, `marker_exact_match_only`, `unrelated_exception_propagates`, `importerror_not_capability_absence`, `rejected_recording_no_receipt`, `verify_rescans_red_log`, `every_expected_case_ran`, `red_output_digest_golden`, `frozen_inventory_exact`.
  - impl: Run `execfind_content_tdd_adapter.py record-red` to capture RED stdout/stderr and each frozen test's sha256 into `.phase-loop/evidence/EXECFIND/content-tdd-receipt.json` against the pre-implementation base; bind no SHA, count, or tree shape. Land the tests, adapter, golden fixture, and receipt before any SL-1/SL-2 production edit. A later test correction restarts SL-0.

### SL-1 — Falsifier runner, authorization identity, staging seam (Lane A)

- **Scope**: Add `falsifier.py` (apply + run a falsifier in a staged tree under a minted `public_board_falsifier.v1` identity, bind the outcome), the additive identity in `backing.py`, the `review_stage.py` seam, and the IF-0-EXECFIND-1 freeze in `CONTRACTS.md`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/falsifier.py`, `phase-loop-runtime/src/phase_loop_runtime/review_stage.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`
- **Interfaces provided**: IF-0-EXECFIND-1 outcome half (`FALSIFIER_OUTCOMES`, `run_finding_falsifier`, `FalsifierRunResult`, `finding_falsifier.v1` record), `FalsifierIsolationAuthorization`, and the EC-EXECFIND-6 **pure** helpers `bound_findings_repair_context`/`president_blocked_by_red_findings` — pure functions over findings with no dependency on REVIEWTRUTH's `apply_fix`/repair-context wiring, so the executable wave (SL-0..SL-2) never acquires the held -6 dependency.
- **Interfaces consumed**: frozen EXECFIND falsifiers (SL-0); `stage_review_tree`, the `ReviewIsolationAuthorization` mint pattern (agent-harness#737), and `collect_test_execution_evidence` semantics (pre-existing, not edited).
- **Parallel-safe**: no (SL-2 consumes its frozen interface).
- **Tasks**:
  - impl: In `falsifier.py`, define `run_finding_falsifier`: verify the authorization's reviewed SHA equals the clean canonical source HEAD before staging; after `stage_review_tree` overlays the source, verify the staged HEAD and materialized content both match that Git tree before applying the diff, with no extra staged files. `git apply` the diff inside the checked clone under the minted authorization, run the named node with `--junitxml` under `wall_clock_s`/`output_cap_bytes`, and bind the outcome to `FALSIFIER_OUTCOMES` reusing `collect_test_execution_evidence` semantics (`red_on_head` only when the node ran and failed; a bound/cap expiry or source/staged-content drift is `error`; a diff that is not exactly one NEW `test_finding_<finding_id>.py` is `apply_failed`), and return the `finding_falsifier.v1` record with both digests. Add the two EC-EXECFIND-6 **pure** helpers (functions over findings only; they import no REVIEWTRUTH repair wiring, keeping the executable wave independent of the held -6 gate).
  - impl: In `backing.py`, add `prepare_falsifier_isolation_authorization` beside `prepare_review_isolation_authorization` (minting `public_board_falsifier.v1` bound to the exact `reviewed_sha`, three isolation flags fail-closed, same lease discipline; review authorization unedited). In `review_stage.py`, add the additive keyword-only bounded staged-run seam (no live tree or credentials exposed; `stage_review_tree` unchanged). Add the `CONTRACTS.md` ABDFALSIFY section by the ABDPRES amendment path, freezing the attachment shape, outcome vocabulary, and `finding_falsifier.v1` record.

### SL-2 — Lane B implementation stage: grammar, parser, attachment, per-finding decomposition, brief, policy

- **Scope**: Parse the `falsifier` block beside `terminal_verdict`, attach it non-field to `PanelLegResult`, decompose per finding, teach the brief the falsifier form + inline fixtures, add the `falsifier_policy`.
- **Owned files**: `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`
- **Interfaces provided**: the falsifier-block parser, `FindingFalsifier`/`FindingFalsifierAttachment`, `attach_finding_falsifiers`; per-finding decomposition (`finding_bound`/`finding_unbound`/`finding_receipt`/`finding_prose`) beside whole-leg codes; the `falsifier_policy`; the appended falsifier-form brief instruction + inline-fixture support.
- **Interfaces consumed**: IF-0-EXECFIND-1 (SL-1); the `attach_native_agent_request` pattern (`panel_invoker.py`), `terminal_verdict`, `_REVIEW_INSTRUCTIONS`/`_mode_instructions`, and the `artifact_ref` seam (`panel_invoker.py`) — all pre-existing.
- **Parallel-safe**: no (consumes SL-1's frozen interface; serializes after any REVIEWTRUTH landing rewriting the same `governed_review.py` lines).
- **Tasks**:
  - impl: In `panel_invoker.py`, add the falsifier-block parser as a new function beside `terminal_verdict` (unedited), the `FindingFalsifier`/`FindingFalsifierAttachment` dataclasses, and `attach_finding_falsifiers` mirroring `attach_native_agent_request` (`object.__setattr__` into `_finding_falsifiers`; a `finding_falsifiers` property defaulting to `None`). The parser rejects a diff outside `phase-loop-runtime/tests/`, a modification of an existing file, a no-node-id block, and a double-claimed block before the runner sees it.
  - impl: In `governed_review.py`, add a post-`invoke_board`, pre-reduction seam in `governed_board_gate`: parse and attach falsifiers from usable leg text, authorize and run them against the clean exact `reviewed_sha`, canonicalize each returned metadata record to its SHA-256 digest, and pass the `(seat_key, finding_id)` result mapping into `_gate_result_from_panel` and `_findings_from_panel`. Never run a seat's text as a provider command or treat a seat-authored outcome as evidence. At `_findings_from_panel`, apply the complete IF-0 run-result binding rule *before* reading an outcome; classify only the verified record. Extend the additive per-finding branch to emit `finding_bound` (`red_on_head`, block), `finding_unbound` (`green_on_head`, warn, to the president), `finding_receipt` (block pending the president's ruling; its `reason` includes `record_digest=<validated hex>` for a verified `apply_failed`, `node_missing`, or `error` record, and `record_digest=unresolved` for a missing or invalid binding; its `body` remains the seat's finding text), and `finding_prose` (no falsifier, warn), keeping whole-leg codes for degraded/non-conforming legs. Thread `falsifier_policy` (`optional | required`, default `optional`) through the same keyword-only reducer seam to gate a prose blocking finding. Do not rewrite an existing whole-leg branch.
  - impl: In `panel_invoker.py`, teach the falsifier form by appending one new adjacent string-literal line to `_REVIEW_INSTRUCTIONS` — additive, the existing AGREE/DISAGREE completion-grammar lines unrewritten (non-goal preserved); support the inline-fixture path via the existing `artifact_ref` seam (`panel_invoker.py`; named fixtures as extra `artifact_ref` paths under the 512 KiB cap, 16 KiB soft warning kept); brokered seats stay text-only, `context_refs` metadata-only. `composition.py` is not touched (see its note below).

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

- **Binding ruling — concurrency on PRESROUTE and EXECFIND** (agent-harness#935, maintainer 2026-09-21; the roadmap Execution Notes are authority): no `Depends on` edge is added, no phase edited. `HARDEN → EXECFIND` is satisfied by the landed isolation-authorization mechanism (`backing.py`, `public_board_review.v1`, agent-harness#737), not HARDEN's completion or EC-HARDEN-5. `REVIEWTRUTH → EXECFIND` is relaxed at criterion granularity: EC-EXECFIND-1's precedent (agent-harness#921) is landed, EC-EXECFIND-2 mints its own `public_board_falsifier.v1`, EC-EXECFIND-3 lands only through the named `governed_review.py` seam serialized after any REVIEWTRUTH landing rewriting the same lines, and EC-EXECFIND-6 (SL-3) is dispatched only after EC-REVIEWTRUTH-8 is verified complete on `main`.
- **Dispatch holds**: SL-3 is held pending EC-REVIEWTRUTH-8 on `main`. The executable wave is SL-0 → SL-1 → SL-2 → SL-4 (EC-EXECFIND-0..-5); SL-3 lands later through REVIEWTRUTH's `runner.py` seam. SL-4 reduces only the executable wave (not SL-3, which carries its own docs later).
- **Touch-shape falsifier (named seams)**: `panel_invoker.py`, `governed_review.py`, `backing.py`, `runner.py` are shared with open HARDEN/REVIEWTRUTH/LEGLIFE/RESIDUAL phases. A landing PR whose diff deletes or rewrites an existing line of a shared owned file OUTSIDE its named seams fails the phase. Named seams (additive, no existing line rewritten except the exact existing signatures/call lines named next): in `panel_invoker.py`, the new parser function beside `terminal_verdict`, the attachment dataclasses, `attach_finding_falsifiers`, and one appended adjacent string-literal line in `_REVIEW_INSTRUCTIONS` (the AGREE/DISAGREE lines are not rewritten); in `governed_review.py`, additive imports and `FalsifierRunBinding`, the post-board falsifier run and result-mapping handoff in `governed_board_gate`, only the `_gate_result_from_panel` and `_findings_from_panel` signature and direct call lines needed to add `falsifier_runs`/`falsifier_policy` keyword arguments, and the per-finding branch in `_findings_from_panel` (existing whole-leg branches are unedited); in `backing.py`, the additive identity; in `runner.py`, the repair-context seam (SL-3, held). Every other touch is a new file or the additive `review_stage.py` seam.
- **`composition.py` note (roadmap Key-files reconciliation)**: the roadmap annotates `composition.py` with "(brief instruction)", but the sealed brief text is `_REVIEW_INSTRUCTIONS`/`_mode_instructions` in `panel_invoker.py`; `composition.py` is board-seating / `composition_digest` only (`panel_invoker` imports only `composition_digest` from it), with no brief path. EC-EXECFIND-4 therefore lands its instruction as the additive `_REVIEW_INSTRUCTIONS` append and EXECFIND does not touch `composition.py` — reconciling the annotation to the code without editing the roadmap (not EXECFIND's to amend).
- **Lane B two stages (tests-first ownership)**: SL-0 is Lane B's tests-first stage (owning the tests, adapter, golden fixture, receipt); SL-2 is its implementation stage. EC-EXECFIND-0's freeze forbids SL-2 from editing the SL-0 test bytes (re-verified byte-equal at merge); SL-1 consumes them. The split keeps Lane B's test ownership while avoiding a Lane A↔Lane B cycle.
- **Single-writer files**: each lane's Owned-files set (above) is its sole-writer set; no file is owned by two lanes.
- **Proofgate refusal sweep — conditions NOT adopted, with reasons** (from an end-to-end read of `proofgate_content_tdd_adapter.py`; adopted refusals are the nine pinned SL-0 nodes): mutation-manifest schema validation (`fixtures/proofgate/*.json`) — N/A, EXECFIND has no mutation manifest; plan-scope / owned-file-union verify (`_scope_verify`) — covered at phase level by the touch-shape falsifier, not the adapter; landing-commit binding (declared-identity / `landing_commit` match) — EC-EXECFIND-0 is content-bound (byte-equal via `verify_content_tdd_receipt`), no commit-topology, and the per-file sha re-check IS that byte-equality; green-run JUnit accounting (run-and-assert) — its RED analogues are the pinned nodes and the GREEN state is the post-impl `suite_command` pytest exit. These nine recording-integrity properties are expected to hoist into the shared `content_tdd_receipt.v1` mechanism (agent-harness#962) so they cannot be dropped per-consumer; until that lands each phase restates them and this plan's SL-0 requirements stand — a future phase author should check whether the hoist has landed rather than copying this list.
- **Known destructive changes**: none — every lane is additive; no lane deletes a file another produces. `tdd_receipts.py`, `terminal_verdict`, `stage_review_tree`, the review authorization, and the golden data file are not edited.
- **Expected add/add conflicts**: none (SL-0 stubs no source file a later lane replaces). **SL-0 re-exports**: none (SL-0 owns only tests, the adapter, the golden fixture, and receipt evidence; no package `__init__` symbol).
- **Stale-base guidance** (verbatim): Lane teammates working in isolated worktrees do not see sibling-lane merges automatically. If a lane finds its worktree base is pre-<first upstream dependency's merge>, it MUST stop and report rather than committing — the orchestrator will re-spawn or rebase. Silent `git reset --hard` or `git checkout HEAD~N -- …` in a stale worktree produces commits that destroy peer-lane work on `--no-ff` merge.

## Spec Closeout Plan

- schema: `spec_delta_closeout.v1`
- decision: `no_spec_delta`
- target surfaces: `phase-loop-runtime/src/phase_loop_runtime/falsifier.py`, `phase-loop-runtime/src/phase_loop_runtime/review_stage.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/backing.py`, `phase-loop-runtime/src/phase_loop_runtime/advisor_board/CONTRACTS.md`, `phase-loop-runtime/src/phase_loop_runtime/panel_invoker.py`, `phase-loop-runtime/src/phase_loop_runtime/governed_review.py`, `phase-loop-runtime/src/phase_loop_runtime/runner.py`
- evidence paths: `plans/phase-plan-v10-EXECFIND.md`, `plans/manifest.json`, `phase-loop-runtime/tests/data/execfind_falsifier_attachment_v1.golden.json`, `.phase-loop/evidence/EXECFIND/content-tdd-receipt.json`
- redaction posture: `metadata_only`
- downstream handling: none; roadmap bytes remain unchanged and RATIFY consumes IF-0-EXECFIND-1

## Verification

Run after the executable lanes merge; `automation.suite_command` is the effective suite (pytest targets are RED-first on base until the impl lands):

```bash
uv run --project phase-loop-runtime python phase-loop-runtime/tests/execfind_content_tdd_adapter.py verify --repo . --landing-ref origin/main --receipt .phase-loop/evidence/EXECFIND/content-tdd-receipt.json
PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py phase-loop-runtime/tests/test_governed_review.py
```

Plan-artifact checks (green now): `validate_plan_doc.py`, `validate-roadmap`, `plan_manifest.validate_manifest`, `validate_plan_dispatch_hints` (empty), `goal_coverage.check_goal_coverage` (clean), `git diff --exit-code -- specs/phase-plans-v10.md`, `git diff --check`.

**Plan budget** (GOVLEAN policy — explicit justification for exceeding 3000 words; AGENTS.md sets no fixed cap, "length is a signal"): the overage is SL-0's nine-node recording-integrity set, the proofgate refusal sweep, and the grok-round brief-seam reconciliation — all added over review rounds after seats found real gaps (a passing contract accepted as RED, a case or file vanishing, and EC-EXECFIND-4's brief seam mis-located). Compressing further re-introduces the "mirror dropped a check" risk these name-each-invariant requirements exist to prevent; the nine integrity invariants belong in the shared mechanism (agent-harness#962) and the length will fall when they hoist there.

## Acceptance Criteria

- [ ] EC-EXECFIND-0 — proven by `uv run --project phase-loop-runtime python phase-loop-runtime/tests/execfind_content_tdd_adapter.py verify --repo . --landing-ref origin/main --receipt .phase-loop/evidence/EXECFIND/content-tdd-receipt.json` (recomputes each frozen test's sha256 against the `content_tdd_receipt.v1` receipt via `phase_loop_runtime.tdd_receipts.verify_content_tdd_receipt`) AND the nine adapter-integrity self-tests `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py -k "unexpected_pass_refused or marker_exact_match_only or unrelated_exception_propagates or importerror_not_capability_absence or rejected_recording_no_receipt or verify_rescans_red_log or every_expected_case_ran or red_output_digest_golden or frozen_inventory_exact"`; falsified by a one-byte mutation to any frozen test, a stripped receipt/RED log, or a mutation defeating any adapter-integrity node.
- [ ] EC-EXECFIND-1 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py -k "grammar or parser_reject or attachment_byte_neutral or attachment_matches_frozen_contract"`; falsified by a path-entered mutation defeating any node in that selector.
- [ ] EC-EXECFIND-2 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py -k "apply_failed or red_on_head or green_on_head or node_missing or bound_expiry_error or no_network_no_credentials or staged_tree_only or staged_overlay_drift_error or staged_untracked_extra_error or staged_ignored_extra_error or staged_symlink_retarget_error or staged_exec_bit_drift_error or only_named_node_runs or seat_tool_attempt_refused or authorization_identity or outcome_vocabulary"`; falsified by a path-entered mutation defeating any node in that selector.
- [ ] EC-EXECFIND-3 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_governed_review.py -k "finding_bound or finding_unbound or finding_receipt or finding_receipt_digest_unresolved or falsifier_count_bound or finding_prose or degraded_leg_whole_code"`; falsified by a path-entered mutation defeating any node in that selector.
- [ ] EC-EXECFIND-4 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_falsifier.py -k "brief_teaches_form or inline_fixture_artifact_ref or brokered_text_only or prompt_over_cap_refused"`; falsified by a path-entered mutation defeating any node in that selector.
- [ ] EC-EXECFIND-5 — proven by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_governed_review.py -k "falsifier_policy_optional or falsifier_policy_required_refuses_prose"`; falsified by a path-entered mutation defeating either node in that selector.
- [ ] EC-EXECFIND-6 — **DISPATCH-HELD (SL-3) until EC-REVIEWTRUTH-8 is verified complete on `main`**; proven, when dispatched, by `PYTHONPATH=phase-loop-runtime/src python3 -m pytest -q phase-loop-runtime/tests/test_execfind_fix_round.py -k "repair_context_node_ids or president_refused_while_red"`; falsified by a path-entered mutation defeating either node in that selector.
