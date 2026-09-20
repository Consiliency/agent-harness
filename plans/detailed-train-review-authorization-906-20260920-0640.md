---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: e33615a7ba284114f4d8831386754ca6437f92ee
issues: [agent-harness#906]
related_issues: [agent-harness#912, agent-harness#905]
automation:
  suite_command: "PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests .venv/bin/python -m pytest -q phase-loop-runtime/tests/test_governed_planning_gate.py phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py phase-loop-runtime/tests/test_governed_premerge.py phase-loop-runtime/tests/test_train_merge.py phase-loop-runtime/tests/test_train_e2e.py phase-loop-runtime/tests/test_train_invariants.py phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_fab_activation_promotion.py phase-loop-runtime/tests/test_train_review_authorization.py"
  verification_status: not_run
  human_required: false
---

# Detailed plan: broker-authorized train review, per-leg refusal diagnostics, and a review-only stop before merge

**r2 (2026-09-20): reconciles board round 1 — gemini PARTIALLY AGREE, claude DISAGREE, codex
DISAGREE, grok DISAGREE, all CONVERGING.** The architecture was validated by execution (claude:
the CLI sequence with the real authorization and the real `invoke_board` gives four usable legs,
zero providers). Six corrections taken: (1) the gate accepts every keyword
`run_governed_premerge_loop` forwards (`available_legs`, `spawn`, `repo_dir`,
`max_concurrency`) — as declared it raised `TypeError` (all four seats); (2) NO landing tier:
`invoke_board` keys the authority switch on `repo_dir`, which is scratch, so a tierless call is
never refused, and forcing the tier onto a live-composed, possibly backfilled board raises
`PresidentPolicyError` out of `run_train` or turns every leg into `president_ruling_missing`
(claude executed, grok, gemini); (3) the hermetic production-wiring seam is factory replacement
(`factory_replaced and factory_marker is review_authorization`, `panel_invoker.py:7198-7254`)
with the factory resolved DYNAMICALLY at call time and the loop's `spawn` forwarded — not
`_has_injected_review_execution_seam`, which bypasses the very check under test (claude
executed, grok, codex); (4) D3 attaches `findings`, never `panel`, on the zero-usable hold:
attaching `panel` reroutes it into the reviewer-floor guard at `governed_premerge.py:442-452`
with the wrong remedy (claude, grok, codex); (5) D5 sits after the Step 3 live read and BEFORE
the `already_approved` branch; an out-of-band MERGED node is the existing merged-recovery path
(`merge_halted`), not D5 (claude, grok, codex); (6) review-only cannot promise zero
publication if it runs after P3 on a fresh train — it now REQUIRES every node to already hold
an admitted open (or merged) PR and refuses before any publication otherwise (codex). Also
pinned: digest = `_resolve_brief("review", brief_ref)`; the staged `artifact_ref` bytes are the
minted bytes (grok, gemini, codex).

## Task

The release-train coordinator's governed train review cannot run: `train_runner._default_train_review`
→ `governed_premerge.run_governed_premerge_loop` → `governed_review.governed_planning_gate` →
`panel_invoker.invoke_panel` → `_default_spawn`, which refuses every leg with "missing HARDEN
review authorization" because that path never prepares the typed `ReviewIsolationAuthorization`
the review-mode launch boundary requires; the gate then collapses four typed refusals into
`no_usable_review`. Separately, `run-train --governed` couples review with merging and has no
review-only stop. Repair both narrowly, reusing the existing broker authorization and isolation
machinery. Preserve exact-head binding, author/reviewer independence, reviewer floors,
crash-resume safety and per-leg refusal diagnostics. Never fabricate authorization or ledger
approval. Keep agent-harness#912 (prebuilt FAB provenance) separate.

## Research summary

Reproduced on the pinned runtime `b1fae706` (receipt
`/mnt/workspace/board-tools/ah906b/repro-missing-authorization-b1fae706.json`): all four legs
`UNAVAILABLE` / "missing HARDEN review authorization" in 0.0 s, no provider launched, and the
loop's finding says only `no_usable_review`. Recon record: `/mnt/workspace/board-tools/ah906b/recon.md`.
Load-bearing facts (all `origin/main` `e33615a7`):

- The launch boundary (`panel_invoker.py:5898-5905`) refuses `mode == "review"` legs with
  `review_authorization is None` unless a sanctioned hermetic test seam is injected. Only a
  `ReviewIsolationAuthorization` satisfies it; `invoke_board` owns the rest of the lifecycle
  (revalidate `:7317`, activate lease `:7408`, per-leg capability via
  `derive_review_leg_authorization` `:6113`, close on every exit `:7913`). Leases, claims and
  the seal are private; a coordinator must not call `activate_*`/`close_*`/`derive_*`.
- Two production sequences already do it right and agree: the `advisor-board` CLI
  (`cli.py:1855-1921`; ordering pinned by
  `test_advisor_board_cli_legacy.py::test_cli_harden_preflight_authorizes_before_compose_and_invoke`)
  and `runner._run_legible_panel` (`runner.py:8480-8566`). Sequence: composition
  authority → `compose_review_board()` → clear → `set_review_instruction_digest(brief)` →
  `prepare_review_isolation_authorization(board, artifact_bytes, mode="review",
  canonical_repo_authority=repo)` → `invoke_board(board, artifact, repo_dir=<scratch>,
  artifact_ref=..., review_authorization=..., canonical_repo_authority=repo, [+
  landing_tier=PRODUCTION_CODE, president_invoke=build_president_invoke(...) iff
  `_govlean_authority_switched(repo)`])` → reset digest in `finally`.
- `run_governed_premerge_loop` exposes an `invoke: Callable[..., GateResult]` seam
  (`governed_premerge.py:337-351`, called keyword-only at `:417`); `governed_planning_gate`
  calls its `invoke(artifact, pool, **kw)` positionally in `invoke_panel`'s shape
  (`governed_review.py:256-264`), so `invoke_board` cannot be substituted there without an
  adapter. `_findings_from_panel` (`:117-174`) already turns unusable legs into
  `panel_leg_degraded` findings carrying `leg.status` — and `:266-273` throws them away via
  `_block_result`, which builds one fresh finding and leaves `panel=None`.
- P4 (`train_runner.py:3374-3535`): autonomy boundary returns `drafts_open` at `:3380-3387`
  when `run_mode != "governed"`; `already_approved` (`:3485-3490`) honours a persisted
  `_train_review_` record only if its `usable_reviewers` still clears the LIVE
  `_MIN_USABLE_REVIEWERS` (=2, `governed_premerge.py:58`); approval is appended at
  `:3523-3532`; the first merge is inside the loop starting `:3535`. The review-only stop
  belongs between those two lines and must cover the `already_approved` path.
- The `_train_review_fn(artifact, run_mode) -> LoopResult` seam has ~30 injection sites; its
  signature is frozen. `_default_train_review`'s implementation is free to change.
- The chunker supplier repo is NOT authority-switched (`_govlean_authority_switched` False);
  agent-harness is. Both paths must work: tierless pre-switch, tiered-with-president post-switch.
- `FLOOR_SEATS = 3` is the composition floor (`composition.py:114`); `_MIN_USABLE_REVIEWERS = 2`
  is the usable-verdict floor. Both stay.

## Scope and decisions

- **D1. One authorized board gate, plugged into the existing loop (r2).** Add
  `governed_review.governed_board_gate(*, artifact, author_executor=None, author_vendors=None,
  run_mode, available_legs=None, spawn=None, repo_dir=None, max_concurrency=None,
  reviewed_sha=None, canonical_repo_authority=None, brief_ref=None,
  compose=compose_review_board, invoke=None) -> GateResult` — the FULL keyword set
  `run_governed_premerge_loop` forwards (`governed_premerge.py:403-417`) plus the train
  authority, with the SAME `GateResult` contract as `governed_planning_gate`. Sequence, the
  CLI's verbatim (tierless): autonomous short-circuit → author-vendor resolution as
  `governed_planning_gate` → composition authority → `compose_review_board()` with no kwargs →
  clear in `finally` → drop author-vendor seats → refuse below `FLOOR_SEATS` with a block
  result naming the missing/unauthed vendors → `set_review_instruction_digest(_resolve_brief("review",
  brief_ref))` → write the artifact bytes to a scratch file and mint
  `prepare_review_isolation_authorization(board, <those exact bytes>, mode="review",
  canonical_repo_authority=...)` resolving the factory DYNAMICALLY from
  `advisor_board.backing` at call time (so the sanctioned factory-replacement seam is honoured)
  → `invoke_board(board, artifact, repo_dir=<scratch>, artifact_ref=<that file>,
  brief_ref=..., review_authorization=..., canonical_repo_authority=..., spawn=spawn,
  max_concurrency=...)` with NO `mode` and NO `landing_tier` (see below) → reset digest in
  `finally` on every exit → `_findings_from_panel`. `spawn` is forwarded as received: production
  passes `None`; the hermetic seam passes a callback that `invoke_board` accepts only under
  factory replacement, refusing otherwise (`unbound_direct_review_invocation_refused`) — the
  existing fail-closed rule, unchanged. `available_legs` is accepted and ignored: composition
  is the board's, not a leg list. `invoke=None` resolves `panel_invoker.invoke_board` at call
  time (the runner's `invoke_board is _PRODUCTION_INVOKE_BOARD` pattern).
  **Why tierless:** `invoke_board` computes the authority switch over `repo_dir`
  (`panel_invoker.py:7116`), which this gate makes scratch exactly as the CLI does, so a
  tierless call is never refused; passing `PRODUCTION_CODE` onto a live-composed board would
  require the four named seats plus a president, and a backfilled seat then raises
  `PresidentPolicyError` out of `run_train` as a traceback (claude, executed). The train
  review is the CLI-equivalent operation; the runner's tiered board is a phase's
  implementation landing on a frozen four-seat preset, a different operation. `_default_train_review(artifact, run_mode,
  *, canonical_repo_authority=None)` becomes `run_governed_premerge_loop(..., invoke=<partial
  of governed_board_gate bound to the authority>)`; the P4 caller binds the authority with a
  closure so the frozen `(artifact, run_mode)` seam is untouched. `governed_planning_gate` and
  `invoke_panel` are NOT modified for routing; the CLI and `_run_legible_panel` keep their
  code byte-for-byte (a follow-up issue records that three call sites now share a sequence).
- **D2. Canonical repo authority for a train.** The coordinator's current directory's git
  toplevel when it is one (this is how the advisor-board CLI resolves it and how the chunker
  lane runs `run-train`, from the supplier checkout); otherwise the first topo-order node's
  workspace. Recorded on the review evidence. A train whose nodes span repositories is reviewed
  as one bundle text under that authority, exactly as `_build_train_review_bundle` already frames it.
- **D3. Per-leg diagnostics survive the hold (r2: findings only, never `panel`).** In BOTH
  gates, the `no_usable_review` result carries the aggregate blocking finding PLUS the per-leg
  `panel_leg_degraded`/`panel_nonconforming` findings; `_block_result` gains an optional
  `extra_findings`. `panel` stays `None` on the zero-usable hold: `run_governed_premerge_loop`'s
  reviewer-floor guard (`governed_premerge.py:442-452`) keys on `gate.panel`, and attaching it
  would relabel the missing-authorization case `below_reviewer_floor` with the "add a reviewer"
  remedy. Tests assert the terminal `reason` as well as the diagnostics. `run_train`'s `review_halted` return
  includes `findings` (code, reason, leg status) in `detail`. The chunker's receipt would then
  have read "missing HARDEN review authorization" per leg instead of `no_usable_review`.
- **D4. Review-only stop (r2: admitted PRs only).** `run_train(..., review_only: bool = False)`.
  Review-only reviews ADMITTED heads: before Step 4, if any node lacks a `pr_open` or `merged`
  record (after the Step 3 live check), return `{"status": "review_only_requires_admitted_prs",
  "nodes": [...]}` with zero publication effects — it never publishes drafts on the operator's
  behalf. Otherwise P4 runs the review, and immediately after the approval record is appended
  (and equally when `already_approved` short-circuits) returns `{"status": "review_approved",
  "nodes", "usable_reviewers", "review_policy_version"}` before the merge loop; non-approval
  keeps `review_halted`. CLI: `run-train --review-only` requires `--governed` (`parser.error`
  otherwise). The ledger shape is unchanged, so a later `--governed` resume merges through
  `already_approved` without re-boarding; a record with a missing count or a count below a
  later-raised floor re-reviews, exactly as today (fail toward re-review, never toward merge).
- **D5. Stale-head refusal before any board is spent (r2 placement).** In P4, after the Step 3
  live read and BEFORE the `already_approved` branch, for `pr_open` nodes whose live head
  differs from the admitted head (`out_of_band_upstreams`): return `review_halted` with reason
  `stale_head` naming the nodes and both heads. An out-of-band MERGED node is not D5's case: the
  existing merged-recovery cross-check (`train_runner.py:3429-3472`) already halts a
  wrong-head/wrong-base merge as `merge_halted`, before the review step.
- **D6. Floors and independence unchanged.** Composition floor `FLOOR_SEATS` at compose;
  usable floor `_MIN_USABLE_REVIEWERS` in the loop; author-vendor exclusion as today.
  `train-coordinator` resolves as it does today (a non-vendor author).
- **D7. No fabricated authority.** The gate never constructs `ReviewLegAuthorization`, leases,
  claims or the seal; it calls only the two sanctioned public entry points plus
  `prepare_review_composition_authorization` (already used by production `cli.py`).

Out of scope: converging the CLI, `_run_legible_panel` and this gate into one helper (follow-up
issue); agent-harness#912; a heartbeat-only policy for the train board (agent-harness#892's PR
908 adds `monitoring_policy`; when it lands the gate forwards it, nothing here depends on it).

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/governed_review.py` (modify)
- `governed_board_gate` — add — D1; seams `compose`, `invoke`, `president_builder` for tests.
- `_block_result` — modify — accept `extra_findings` (never `panel`); `governed_planning_gate`
  and the new gate pass the per-leg findings on the `no_usable_review` path (D3).

### `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` (modify)
- `_default_train_review` — modify — keyword `canonical_repo_authority`; routes through
  `run_governed_premerge_loop(invoke=partial(governed_board_gate, ...))`.
- `run_train` — modify — `review_only` keyword; default `train_review_fn` bound to the
  resolved authority (D2); stale-head refusal (D5); review-only return (D4);
  `review_halted` detail carries findings (D3).

### `phase-loop-runtime/src/phase_loop_runtime/cli.py` (modify)
- `run-train` subparser — modify — `--review-only`; `_run_train_command` — modify — require
  `--governed`, pass `review_only`, print/JSON the `review_approved` status.

### Tests
- `phase-loop-runtime/tests/test_train_review_authorization.py` — create —
  (a) ordering contract for the gate, mirroring the CLI test: composition authority before
  compose, compose called with no kwargs, isolation authorization after compose, `invoke_board`
  receives the identical authorization object and the canonical authority, `repo_dir` is not
  the canonical repo, digest reset in `finally` on both success and raise; tierless when the
  authority is unswitched, `landing_tier` + president seam when switched;
  (b) PRODUCTION WIRING (r2): enter through `_default_train_review("...", "governed")` with the
  REAL `invoke_board` and the REAL `prepare_review_isolation_authorization`, using the sanctioned
  factory-replacement seam (`factory_replaced and factory_marker is review_authorization`,
  `panel_invoker.py:7198-7254`; the seam `test_advisor_board_cli_legacy.py::test_harden_real_invoker_revalidates_canonical_repository_authority`
  drives) with a hermetic `spawn`; assert at the invoker's validation boundary that the
  authorization object and canonical binding are the ones the gate minted, and that every leg
  passes the boundary (statuses usable, none "missing HARDEN review authorization"). NEVER use
  `_has_injected_review_execution_seam`, which bypasses the check under test. Negative controls,
  without any seam: the old `invoke_panel` route still refuses on every leg; and a spy proves
  `invoke_panel` is never called by the default path;
  (c) unavailable reviewers: compose below `FLOOR_SEATS` → block naming vendors, zero invoke;
  rejected reviewer: a DISAGREE leg → held with body; (d) D3: a held result's findings carry
  each leg's status and detail; (e) D5 stale head → `review_halted`/`stale_head`, zero invokes, and it fires even when an
  `approved` record exists; (f) D4 review-only: approved → `review_approved`, `_merge_pr_fn`
  never called, ledger `approved` record present; second run `--governed` merges with no
  re-board; review-only on an already-approved train → `review_approved` without re-board;
  rejected → `review_halted`, zero merges; a train with a node lacking an admitted PR →
  `review_only_requires_admitted_prs`; the publish stub is never called anywhere in ANY
  review-only invocation; `--review-only` without `--governed` is a parser error.
- `test_train_merge.py` — modify — `test_crash_resume_review_not_re_invoked` and
  `test_crash_resume_stale_approval_without_floor_evidence_is_re_reviewed` must pass
  unchanged (the ledger shape is untouched).
- `test_advisor_board_cli_legacy.py` — unchanged and green (the CLI is not modified).
- Mutants (scratch copy): remove the isolation authorization from the gate → (b) fails; route
  the default back to `invoke_panel` → (b) fails; drop findings on the hold → (d) fails; remove
  the review-only return → (f) fails with a merge call; remove the stale-head check → (e) fails.

### Skills and docs
- `skills-src/{claude,codex,gemini,opencode}/<harness>-run-train/SKILL.md` — modify —
  `--review-only`, the `review_approved` status, and that a held review now names each leg's
  refusal; regenerate with the two scripts. `CHANGELOG.md` — modify.

## Documentation impact
- `CHANGELOG.md`; run-train skill sources and generated copies; `docs/` pages naming
  `run-train --governed` statuses (search `review_halted`).

## Dependencies & order
1. Tests (a)-(f) first against the unmodified tree; (b) must fail with the exact refusal text.
2. D3, then D1 (gate + default wiring), then D5, then D4 + CLI, then docs/skills.
3. Plan CR (one round, delta re-review of dissenting seats only), then implement, then code CR
   under the standing gate, merge, commit-pin instruction on agent-harness#906.

## Verification
```sh
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests .venv/bin/python -m pytest -q \
  phase-loop-runtime/tests/test_train_review_authorization.py \
  phase-loop-runtime/tests/test_governed_planning_gate.py phase-loop-runtime/tests/test_governed_cross_vendor_floor_358.py \
  phase-loop-runtime/tests/test_governed_premerge.py phase-loop-runtime/tests/test_train_merge.py \
  phase-loop-runtime/tests/test_train_e2e.py phase-loop-runtime/tests/test_train_invariants.py \
  phase-loop-runtime/tests/test_advisor_board_cli_legacy.py phase-loop-runtime/tests/test_fab_activation_promotion.py
.venv/bin/python phase-loop-runtime/scripts/regenerate_skills_bundle.py && .venv/bin/python phase-loop-runtime/scripts/sync_skills_bundle.py
PYTHONPATH=phase-loop-runtime/src:phase-loop-runtime/tests .venv/bin/python -m pytest -q phase-loop-runtime/tests
git diff --check
```
External check after the commit pin: the chunker lane re-runs its review-only command against
Consiliency/treesitter-chunker#97's admitted head; the expected terminal is `review_approved` or
`review_halted` with per-leg detail, never `no_usable_review`, and zero merges.

## Acceptance criteria
- [ ] `_default_train_review` in governed mode prepares composition and isolation authorization
  and dispatches through `invoke_board`; no leg returns "missing HARDEN review authorization";
  `invoke_panel` is not called on that path.
- [ ] A held review's result carries every leg's status and detail; `no_usable_review` is never
  the only diagnostic.
- [ ] `run-train --governed --review-only` reviews the admitted heads, records approval, returns
  `review_approved`, and makes zero merge and zero publication calls across the whole
  invocation (a node without an admitted PR is refused before anything publishes); a later
  `--governed` run merges without re-review; `--review-only` without `--governed` is a usage error.
- [ ] A node whose live PR head differs from its admitted head halts the review before any board
  runs, naming the node and both heads.
- [ ] Reviewer floors and author-vendor exclusion behave exactly as today; the CLI advisor-board
  tests and the P4 crash-resume tests pass unchanged.

## Execution Policy
- execute: effort=high, reason=authorization boundary and merge-gate control flow
