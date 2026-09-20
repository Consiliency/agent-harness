---
type: detailed
status: planned
owner_skill: claude-plan-detailed
input_base_commit: eabfec6c0e4683eba6d5682d7783b92485d198c0
issues: [agent-harness#906]
related_issues: [agent-harness#376, agent-harness#383, agent-harness#388, agent-harness#289]
automation:
  suite_command: "PYTHONPATH=phase-loop-runtime/src .venv/bin/python -m pytest -q phase-loop-runtime/tests/test_train_prebuilt.py phase-loop-runtime/tests/test_train_merge.py phase-loop-runtime/tests/test_train_invariants.py phase-loop-runtime/tests/test_skills_canon_parity.py"
  verification_status: not_run
  human_required: false
---

# Detailed plan: refresh an admitted prebuilt PR on local advance; land single-node prebuilt trains under `--governed`

## Task

Repair the two Run Train continuation blockers in agent-harness#906, verified against
`eabfec6c`: (1) resume skips an already-open prebuilt root node even when the local
candidate advanced past the admitted head, so a reviewed successor can never reach its PR
through the coordinator; (2) `--governed` refuses every prebuilt node at preflight, so a
prebuilt PR can only land by a manual merge the run-train skill forbids. Implement the
smallest supported path for both, preserving exact-head checks, authority and lease checks,
review gates, non-force publication and crash recovery. No fabricated ledger or admission
state, no weakened gate, no relabeling of prebuilt nodes, no manual merge of any PR.

## Research summary

Reconnaissance record: `/mnt/workspace/board-tools/ah906-recon.md` (file:line citations
against `eabfec6c`). Load-bearing facts:

- A `pr_open` ledger record's `head_sha` IS the admitted head (written at publish,
  `train_runner.py:3105-3118`); `completed_nodes[nid]["admitted_head_sha"]` is set from it
  at `:3093-3100` and never from the live PR.
- The resume skip at `train_runner.py:2698-2718` consults only upstream change sets. It never
  reads the workspace HEAD and never consults the node's own live-vs-admitted comparison
  (computed at `:2651-2656` into `out_of_band_upstreams`). That block is the only site holding
  node, workspace, admitted head and both change sets, and it sits directly above the
  existing prebuilt publish arm (`:2798-2853`) inside the same loop iteration.
- The broker's idempotency key is `sha256(repo\0branch\0head_sha)` (`contracts.py:21-23`):
  a new head is a genuinely fresh admission. The push is exact-head, non-force
  (`credsep.py:475`, `build_non_force_branch_ref` `:26-28`): a fast-forward advance of an
  existing branch succeeds, a rewrite fails as `push-unconfirmed`. `gh pr create` on a
  branch with an open PR is reconciled by `_create_reports_existing_pr` (`:278-302`),
  and the readback (`:504+`) requires `ls-remote` head `== request.head_sha` and exactly
  one open PR whose `headRefOid`/`baseRefName`/owner match. Nothing today exercises that
  combination; this plan does, and its tests must prove it rather than assume it.
- `reverify_fn` runs ONLY inside `if _upstream_edges_m:` (`train_runner.py:3302`). A
  prebuilt node with no channel-carrying upstream edge never reaches it. The blanket
  preflight rejection at `:2466-2483` therefore over-refuses the exact one-node shape in
  the issue; every other P4 step it would traverse (ledger `merged_shas`, the live
  cross-check keyed on `admitted_head_sha`, train review, `_live_merge_pr` with
  `--match-head-commit`) is mode-agnostic and already satisfied by a prebuilt node.
- FABPUB transaction resume (`train_runner.py:2500-2535`, replay arm `:2766-2796`;
  `publishing.py::inspect_publish_resume_candidate`) already replays an interrupted publish
  of the SAME head and returns `CONFLICTED` (→ `blocked`) when `rev-parse <exact_ref>` no
  longer equals the transaction's `parent_head_sha`. It is the crash-recovery half of the
  refresh and is reused, not duplicated.
- agent-harness#383 (parked, plan-only) owns post-commit crash resume for EXECUTE nodes and
  states declared prebuilt nodes need no marker; it says nothing about local advance.
  agent-harness#388 concerns dirty-tree preservation; a refresh runs on a clean, ahead-of-base
  tree (preflight `:213`, `:265`) and adds no tree mutation. agent-harness#289 is the
  unwrapped live-head read at `:2651`, which the refresh's drift check reuses.

## Scope and decisions

- **D1. Refresh = fall through into the existing prebuilt publish arm.** In the Step 4
  skip block, for a `pr_open` node whose `mode == "prebuilt"`, read the workspace HEAD
  before the `continue`. If `HEAD == admitted_head_sha` and no upstream changed: unchanged
  resume, `continue` (today's behaviour). If HEAD advanced and the admitted head is an
  ancestor of HEAD (`git merge-base --is-ancestor`): do NOT `continue`; the loop proceeds
  into the prebuilt arm, which re-derives `owned_paths` from `origin/<base>...HEAD`, takes a
  fresh admission at the new head, pushes non-force to the same branch and reconciles the
  existing PR. No second publish path is written. Execute nodes are out of scope: their
  workspace HEAD is coordinator-managed and a divergence there is a different defect class.
- **D2. Refuse unknown remote drift before refreshing.** If the live PR head differs from
  the admitted head (the node is in `out_of_band_upstreams` for ITSELF), append a `blocked`
  record with reason `remote_drift` and return `blocked`. The coordinator never pushes over
  an advance it did not admit.
- **D3. Refuse a diverged candidate.** If HEAD is neither the admitted head nor a descendant
  of it, `blocked` with reason `candidate_diverged`. Non-force push would fail anyway; refuse
  before admission so no idempotency key is minted for a head that cannot land.
- **D4. Ledger head moves only on terminal evidence, append-only.** The existing success
  epilogue appends a new `pr_open` record carrying the new `head_sha` after
  `publish_result["status"] == "published"`. Prior records are preserved. A refused or
  failed admission appends `blocked` and leaves the previously admitted head as the latest
  `pr_open`. No record is rewritten, no admission is fabricated.
- **D5. Narrow the governed rejection to the shape it actually protects.** Replace the
  blanket prebuilt refusal at `:2466-2483` with: refuse a prebuilt node that has at least
  one channel-carrying (non-`order-only`) upstream edge, with the same fail-at-preflight
  property and a message that names the edge; admit prebuilt nodes with none. The merge of
  an admitted prebuilt node then runs the unchanged P4 path, pinned by `--match-head-commit`
  to the LATEST admitted head (the refreshed one when D1 ran).
- **D6. Take agent-harness#289 deliberately.** Wrap the live-head read at `:2651` in the
  same `blocked` pattern the merge loop uses, because D2 depends on that read and a second
  unwrapped read beside it is the failure the issue names. Flip the residual test.
- **D7. Reuse FABPUB transaction resume for an interrupted refresh.** No new marker. A
  refresh interrupted after admission replays through the existing arm; a workspace that
  advanced again in between yields `CONFLICTED` → `blocked`, never a silent replay.
- **D8. Text reconciliation.** The preflight message no longer instructs a manual merge.
  The run-train skill states: prebuilt nodes without channel-carrying upstreams land under
  `--governed`; prebuilt nodes with such upstreams stop at `drafts_open` pending the
  follow-up below; closing a stale PR is done by the operator only when the coordinator's
  `blocked` reason says so.

Out of scope (each gets a follow-up issue on landing, none is a TODO in code): a prebuilt
reverify substitute for upstream-bearing prebuilt nodes (the follow-up the code names at
`:2470-2471`); surfacing `fab_run_id` through prebuilt admission; refresh for execute
nodes; the tagged release and consumer re-pin that make this an INSTALLED fix.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` (modify)
- Step 4 skip block (`~2698-2718`) — modify — add the prebuilt local-advance decision (D1,
  D2, D3) ahead of the existing `continue`; reuse `completed_nodes[nid]["admitted_head_sha"]`
  and the node's own membership in `out_of_band_upstreams`; workspace HEAD via the same
  git helper the prebuilt preflight uses.
- Step 3 live read (`~2651`) — modify — wrap in the `blocked` pattern (D6).
- Governed preflight rejection (`~2466-2483`) — modify — narrow per D5; message names the
  offending edge and no longer says "merge manually".
- No change to the prebuilt publish arm, the success epilogue, `_live_merge_pr`, or the P4
  loop. If implementation finds one is needed, stop and amend this plan.

### `phase-loop-runtime/src/phase_loop_runtime/publishing.py` (verify, expect no change)
- `publish_from_worktree(prebuilt=True)` against an existing branch/PR — verify by test —
  push fast-forwards, `gh pr create` collision reconciles to the same PR, readback pins the
  new head. If any step refuses, the refusal is the finding; do not patch around it.

### Tests (create/modify)
- `phase-loop-runtime/tests/test_train_prebuilt.py` — modify — split
  `test_governed_prebuilt_opens_zero_prs` into "upstream-bearing prebuilt still refused at
  preflight, zero PRs" and "single-node prebuilt admitted under --governed"; add refresh
  cases: unchanged resume (zero publish calls, ledger unchanged), valid refresh (publish
  called once with the new head; new `pr_open` appended; prior record intact), remote drift
  (`blocked`/`remote_drift`, zero publish calls), diverged candidate
  (`blocked`/`candidate_diverged`, zero publish calls), rejected admission (`blocked`, latest
  `pr_open` still the old head).
- `phase-loop-runtime/tests/test_train_merge.py` — modify — governed single-node prebuilt
  merges with `--match-head-commit` pinned to the refreshed admitted head; an out-of-band
  push after the refresh fails closed exactly as `test_oob_push_after_admission_merge_pinned_to_admitted_not_live` does today; interrupted refresh replays via the transaction arm and a
  further-advanced workspace yields `blocked`/`publish_transaction_conflicted`; train review
  not approved → zero merges (unchanged assertion, re-run with a prebuilt node).
- `phase-loop-runtime/tests/test_train_invariants.py` — modify —
  `test_residual_pr_open_resume_live_head_failure` becomes a positive `blocked` assertion.
- Broker-level: one test in the existing credsep suite proving a fast-forward push of a new
  head to a branch with an open PR reconciles to that PR with the new head pinned.

### Skills and docs
- `skills-src/{claude,codex,gemini,opencode}/<harness>-run-train/SKILL.md` — modify — D8
  text; regenerate `phase-loop-skills/run-train/` and `skills_bundle/` with the two existing
  scripts, never by hand.
- `CHANGELOG.md` — modify — Unreleased entry naming both behaviours and the follow-ups.

## Documentation impact
- `CHANGELOG.md` — modify — as above.
- run-train skill sources and generated copies — modify — as above.
- `docs/` — verify — any page that repeats "prebuilt nodes stop at drafts_open" is updated
  or it contradicts the skill (search `drafts_open` and `prebuilt` under `docs/`).

## Dependencies & order
1. Tests first for D1–D3 and D5 against the unmodified tree; they must fail for the stated
   reason (the skip, the blanket refusal), not for a fixture defect.
2. D6, then D1–D3 (one block), then D5. D4 is a property of the existing epilogue; assert
   it, do not implement it.
3. Broker-level proof of the fast-forward-plus-collision path. If it does not hold, the
   refresh cannot be "existing PR reconciliation" and the plan is amended before anything
   else lands.
4. Skill/CHANGELOG text; regenerate; parity test.
5. Plan CR on this document (two rounds maximum, delta re-review of dissenting seats only),
   then implementation in an isolated worktree, then code CR under the standing gate.

## Verification
```sh
PYTHONPATH=phase-loop-runtime/src .venv/bin/python -m pytest -q \
  phase-loop-runtime/tests/test_train_prebuilt.py phase-loop-runtime/tests/test_train_merge.py \
  phase-loop-runtime/tests/test_train_invariants.py phase-loop-runtime/tests/test_skills_canon_parity.py
.venv/bin/python phase-loop-runtime/scripts/regenerate_skills_bundle.py
.venv/bin/python phase-loop-runtime/scripts/sync_skills_bundle.py
PYTHONPATH=phase-loop-runtime/src .venv/bin/python -m pytest -q phase-loop-runtime/tests
git diff --check
```
Non-vacuity: in a scratch copy, restore the unconditional `continue`, restore the blanket
refusal, and drop the drift check; the corresponding new tests must fail. No live provider
call, no production ledger, no remote mutation is part of offline acceptance. The chunker
lane's isolated repro (`codegraph-de/docs/reviews/2026-09-19-chunker-s26/`) is re-run against
the candidate as an external check, mocked boundaries unchanged.

## Acceptance criteria
- [ ] A prebuilt `pr_open` node whose workspace HEAD is a descendant of the admitted head is
  republished once at HEAD through fresh broker admission and non-force push; the ledger
  gains a new `pr_open` record with the new head and keeps the old one.
- [ ] Unchanged resume, remote drift, diverged candidate and rejected admission each make
  zero publish calls; the two refusals append `blocked` with the named reason.
- [ ] A single-node prebuilt train under `--governed` passes preflight, opens its draft,
  runs train review, and merges pinned to its latest admitted head; an upstream-bearing
  prebuilt train is still refused at preflight with zero PRs.
- [ ] An interrupted refresh resumes through the existing transaction arm; a workspace that
  advanced again yields `blocked`, never a replay of a stale head or a duplicate PR.
- [ ] A live-head read failure on resume yields `blocked`, not an uncaught exception.
- [ ] Runtime message, skill sources and generated copies agree; parity test green.

## Execution Policy
- execute: effort=high, reason=coordinator resume/publish/merge control flow with exact-head and admission invariants
