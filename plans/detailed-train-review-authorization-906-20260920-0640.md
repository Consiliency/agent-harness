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

- **D1. One authorized board gate, plugged into the existing loop.** Add
  `governed_review.governed_board_gate(*, artifact, author_executor, author_vendors, run_mode,
  canonical_repo_authority, brief_ref=None, reviewed_sha=None, max_concurrency=None,
  compose=compose_review_board, invoke=invoke_board, president_builder=build_president_invoke)
  -> GateResult`, with the SAME `GateResult` contract as `governed_planning_gate`, implemented as
  the production sequence above verbatim: composition authority → compose → clear → drop seats
  whose vendor is an author vendor (same resolution `governed_planning_gate` uses) → refuse below
  `FLOOR_SEATS` with a block result that names the missing/unauthed vendors → bind the
  instruction digest → isolation authorization over the FINAL artifact bytes → `invoke_board`
  with a throwaway scratch `repo_dir`, the artifact staged as `artifact_ref`, the
  authorization and canonical authority, plus `landing_tier=PRODUCTION_CODE` and a president
  seam iff the canonical repo is authority-switched → reset digest in `finally` → map the
  `PanelResult` through `_findings_from_panel`. `_default_train_review(artifact, run_mode,
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
- **D3. Per-leg diagnostics survive the hold.** In BOTH gates, the `no_usable_review` result
  carries the per-leg `panel_leg_degraded`/`panel_nonconforming` findings and attaches `panel`;
  `_block_result` gains optional `findings`/`panel`. `run_train`'s `review_halted` return
  includes `findings` (code, reason, leg status) in `detail`. The chunker's receipt would then
  have read "missing HARDEN review authorization" per leg instead of `no_usable_review`.
- **D4. Review-only stop.** `run_train(..., review_only: bool = False)`. In P4, immediately
  after the approval record is appended (and equally when `already_approved` short-circuits),
  `review_only` returns `{"status": "review_approved", "nodes", "usable_reviewers",
  "review_policy_version"}` before the merge loop; non-approval keeps today's
  `review_halted`. CLI: `run-train --review-only` requires `--governed` (`parser.error`
  otherwise, so a run is never silently upgraded), new status branch in text and `--json`.
  The ledger shape is unchanged, so a later `--governed` resume merges through
  `already_approved` without re-boarding.
- **D5. Stale-head refusal before any board is spent.** In P4, before the review step and only
  for `pr_open` nodes, compare each node's live PR head to its admitted head (the Step 3 read
  already exists); any mismatch returns `review_halted` with reason `stale_head` naming the
  nodes and both heads. Boarding a bundle whose admitted head is no longer live would record an
  approval that `--match-head-commit` can never honour.
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
- `_block_result` — modify — accept `findings`/`panel`; `governed_planning_gate` and the new
  gate pass them on the `no_usable_review` path (D3).

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
  (b) PRODUCTION WIRING: `_default_train_review("...", "governed")` with the real `invoke_board`,
  real authorization and the sanctioned hermetic execution seam the HARDEN suite uses
  (`test_advisor_board_cli_legacy.py::test_harden_real_invoker_revalidates_canonical_repository_authority`
  pattern) — no leg may return "missing HARDEN review authorization"; and the regression
  control: the old `invoke_panel` route still refuses, asserted via a spy that `invoke_panel`
  is never called by the default path;
  (c) unavailable reviewers: compose below `FLOOR_SEATS` → block naming vendors, zero invoke;
  rejected reviewer: a DISAGREE leg → held with body; (d) D3: a held result's findings carry
  each leg's status and detail; (e) D5 stale head → `review_halted`/`stale_head`, zero
  invokes; (f) D4 review-only: approved → `review_approved`, `_merge_pr_fn` never called,
  ledger `approved` record present; second run `--governed` merges with no re-board;
  review-only on an already-approved train → `review_approved` without re-board; rejected →
  `review_halted`, zero merges; publication effects zero in every review-only run (publish stub
  never called after the review step).
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
  `review_approved`, and makes zero merge and zero publication calls; a later `--governed` run
  merges without re-review; `--review-only` without `--governed` is a usage error.
- [ ] A node whose live PR head differs from its admitted head halts the review before any board
  runs, naming the node and both heads.
- [ ] Reviewer floors and author-vendor exclusion behave exactly as today; the CLI advisor-board
  tests and the P4 crash-resume tests pass unchanged.

## Execution Policy
- execute: effort=high, reason=authorization boundary and merge-gate control flow
