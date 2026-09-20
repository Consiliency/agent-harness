---
type: detailed
status: ratified
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

**r3 (2026-09-20): reconciles board round 2 — gemini AGREE, claude PARTIALLY AGREE, codex
DISAGREE, grok DISAGREE, all CONVERGING, all on ONE item: the Step 2 change in D1 was
under-specified.** Verified against the code and taken: (1) the broker seals a transaction on
EVERY terminal class (`verbs.py:600-606`), so "sealed = published" is false — the evidence
store decides (claude, executed); (2) the post-accept path in `publish_from_worktree`
(`publishing.py:1185-1195`) REQUIRES the sealed transaction to come back attached, and the
publish entry (`:1165`) and Step 2 (`train_runner.py:2509-2515`) each key on
`candidate.transaction`, so the contract has three consumer sites, not one (grok, executed;
codex, gemini); (3) a closed-not-merged original PR is remote lifecycle drift, and "no duplicate
PR" is now defined precisely (codex); (4) text sweep of the refuted "channel-carrying"
predicate in the research summary, D8 and the tests bullet, and "zero publish calls" → "zero
push/PR-creation effects" (all four). Round 2 was the pre-registered cap. **This revision is
the proposed execution contract and awaits maintainer ratification of D1's Step 2 contract
(below) before implementation.**

**r2 (2026-09-20): reconciles board round 1 — four seats, all DISAGREE / CONVERGING.** Round 1
found, and I verified against `eabfec6c`: (1) D5's "channel-carrying" carve-out was wrong — the
P4 guard `if _upstream_edges_m:` (`train_runner.py:3302`) is true for order-only edges too and
`reverify_fn` (`:3333`) sits inside it, so D5 now admits only prebuilt nodes with ZERO upstream
edges (all four seats); (2) D1's fall-through was unreachable on the live path — a successful
publish leaves its FABPUB transaction pointer at `TERMINAL_SEALED`, which
`inspect_publish_resume_candidate` then reports as `CONFLICTED` against the advanced HEAD and
Step 2 turns into a train-level `preflight_failed` (claude seat, executed) — D1 now includes the
Step 2 / `publishing.py` change and D7 is corrected; (3) the skip block ends in a `blocked`
RETURN, not only a `continue`, so the refresh decision is placed in the no-upstream-change arm
and the restructure is named (grok, codex); (4) the `running` record at `:2756` precedes
publication and the ledger is last-wins, so D4's wording was false mid-refresh (grok, codex,
gemini) — D4 now states the real crash-resume behaviour; (5) the pre-admission TOCTOU window is
named, its fail-closed consequence stated, and the one alternative that would close it is
recorded as a maintainer decision, D9 (all four seats).

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

- Corrected in r2/r3: the predicate that keeps a prebuilt node out of phase-loop
  re-verification is "no upstream edge of ANY kind", because the P4 guard at
  `train_runner.py:3302` tests the full `edges_for_downstream` list, order-only included; the
  earlier "channel-carrying" reading in this section was wrong and is retracted.
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
- `reverify_fn` runs ONLY inside `if _upstream_edges_m:` (`train_runner.py:3302`), and that
  list includes order-only edges. A prebuilt node with NO upstream edge of any kind never
  reaches it. The blanket preflight rejection at `:2466-2483` therefore over-refuses the
  exact one-node shape in the issue; every other P4 step it would traverse (ledger `merged_shas`, the live
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

- **D1. Refresh = fall through into the existing prebuilt publish arm.** The Step 4 skip
  block (`train_runner.py:2698-2750`) has two exits: a `blocked` RETURN when an upstream
  changed, and a bare `continue` otherwise. The refresh decision replaces that bare
  `continue`, for a `pr_open` node whose `mode == "prebuilt"` only: read the workspace HEAD;
  if `HEAD == admitted_head_sha`, `continue` (unchanged resume, today's behaviour); if the
  admitted head is an ancestor of HEAD, fall OUT of the `if nid in completed_nodes` block
  into the existing `running` append and the prebuilt arm (`:2798-2853`), which re-derives
  `owned_paths` from `origin/<base>...HEAD`, takes a fresh admission at the new head, pushes
  non-force to the same branch and reconciles the existing PR. The upstream-changed RETURN
  is untouched. Execute nodes are out of scope.
  **Step 2 contract (r3) — three consumer sites, one predicate.** A completed publish
  leaves the node's transaction pointer at `TERMINAL_SEALED`. Today
  `inspect_publish_resume_candidate` validates that sealed transaction against the current
  HEAD and returns `CONFLICTED`, which Step 2 turns into `preflight_failed` for the whole
  train. The broker seals on EVERY terminal class (`verbs.py:600-606`:
  `_advance_transaction(..., "TERMINAL_SEALED")` runs unconditionally; only the return tests
  `EFFECT_TERMINAL_OBSERVED`), and the sealed payload carries no outcome field, so "sealed"
  alone does not mean "published". The contract:
  1. `inspect_publish_resume_candidate` (`publishing.py:~868-960`): a `TERMINAL_SEALED`
     active transaction is returned as `PublishResumeCandidate(TERMINAL_SEALED, transaction)`
     — ATTACHED, never `CONFLICTED`, and without the HEAD/parent checks that describe an
     in-flight publication. Placed after the sibling-pointer guard (`:880-882`), which is
     unchanged. It must stay attached because the post-accept path
     (`publishing.py:1185-1195`) raises "broker accepted publish without a recoverable
     transaction" when `candidate.transaction is None`.
  2. Step 2 (`train_runner.py:2509-2515`): a `TERMINAL_SEALED` candidate is NEVER a resume
     candidate. Its disposition comes from the broker evidence store replayed for the
     transaction's idempotency key (`sha256(repo\0branch\0committed_head)`,
     `contracts.py:21-23`; lookup `evidence_store.replay().get(key)`, `verbs.py:~611`):
     `effect_terminal_observed` or `no_effect_terminal_proven` → completed prior
     publication, no candidate, the loop proceeds to Step 3/4; `outcome_ambiguous_blocked`
     → `preflight_failed` naming the node, preserving the zero-PRs guarantee at preflight
     (the epoch is already poisoned; blocking late would only lose that guarantee).
  3. `publish_from_worktree` entry (`publishing.py:1165`): a `TERMINAL_SEALED` candidate is
     treated as no active transaction, so `prepare_*_transaction` prepares a NEW one for the
     new head — the same treatment `prepare_*` already applies at `:742`/`:804`. Without this
     the refresh would `resume()` head A's sealed transaction (branch, mode and authority all
     match) instead of publishing head B.
  The Step 4 replay arm (`:2766-2796`) needs no change: it only ever sees what Step 2
  registered. Tests must include a SUCCESSFUL FABPUB prebuilt publish after the inspector
  change (the post-accept regression), not only Step 2 with a sealed prior.
- **D2. Refuse unknown remote drift before refreshing — at observation time.** If the live
  PR head differs from the admitted head (the node is in `out_of_band_upstreams` for ITSELF),
  append `blocked` with reason `remote_drift` and return. The live head is re-read
  immediately before falling through, not only in Step 3. **Named window (r2):** between that
  read and the broker's push there is a TOCTOU window. A divergent remote advance in it fails
  closed at the non-force exact-head push (`credsep.py:475`, `push-unconfirmed` →
  `outcome_ambiguous_blocked`, which `credsep.py:437` documents as permanent and
  epoch-poisoning; recovery is the existing ambiguous-block procedure, not a retry). A remote
  FAST-FORWARD advance in the window is NOT refused: a non-force push of a descendant succeeds
  over it. So D2 is observation-time detection; publication-time enforcement of "remote still
  equals admitted" is not provided. The merge-time `--match-head-commit` pin does not cover
  this window either; it pins the later merge to the new admitted head. See D9.
- **D3. Refuse a diverged candidate.** If HEAD is neither the admitted head nor a descendant
  of it, `blocked` with reason `candidate_diverged`. Non-force push would fail anyway; refuse
  before admission so no idempotency key is minted for a head that cannot land.
- **D4. Ledger head moves only on terminal evidence, append-only — with the `running`
  record stated honestly (r2).** The success epilogue appends a new `pr_open` carrying the new
  `head_sha` only after `publish_result["status"] == "published"`; prior lines are preserved.
  But the existing `running` append (`train_runner.py:2756`) precedes publication and
  `read_ledger` is last-wins, so mid-refresh the folded view shows `running`, not the prior
  `pr_open`. A crash there resumes as "not pr_open": the node republishes at HEAD through the
  transaction store (replay if a transaction was prepared, fresh otherwise), pushes to the same
  branch and reconciles the same open PR. That is correct and duplicate-free, and the test for
  it asserts exactly that: one open PR, no fabricated admission, the prior `pr_open` line still
  present in the file. **"No duplicate PR" defined (r3):** never a `gh pr create` while an open
  PR exists on the branch, and never a second OPEN PR on the branch. If the original PR was
  CLOSED (not merged) out of band before resume, that is remote lifecycle drift: the existing
  Step 3 rule drops the node and it republishes as a NEW PR (`test_not_open_and_not_merged_still_drops`
  pins this today). The refresh does not enforce same-PR identity across an operator's closure;
  the ledger keeps both PR URLs, so the history is not lost. A refused or failed admission appends `blocked`; the previously
  admitted head remains recoverable from the file and from the live PR. No record is
  rewritten.
- **D5. Narrow the governed rejection to the shape it actually protects (r2: ZERO upstream
  edges).** Replace the blanket prebuilt refusal at `:2466-2483` with: refuse a prebuilt node
  for which `roadmap.edges_for_downstream(node)` is non-empty — ANY upstream edge, order-only
  included, because the P4 guard at `:3302` tests the full edge list and `reverify_fn` at
  `:3333` runs for every node inside it — with the same fail-at-preflight property and a
  message naming the edge; admit prebuilt nodes with no upstream edges. The predicate is
  the same test P4 uses, so it cannot drift from it. The merge of an admitted prebuilt node
  then runs the unchanged P4 path, pinned by `--match-head-commit` to the LATEST admitted
  head. Extending this to prebuilt nodes WITH upstreams is the follow-up, not this plan.
- **D6. Take agent-harness#289 deliberately.** Wrap the live-head read at `:2651` in the
  same `blocked` pattern the merge loop uses, because D2 depends on that read and a second
  unwrapped read beside it is the failure the issue names. Flip the residual test.
- **D7. Reuse FABPUB transaction resume for an interrupted refresh (r2: corrected).** No new
  marker. A refresh interrupted after its transaction was prepared replays through the
  existing Step 4 arm on the next run. A workspace that advanced AGAIN in between yields
  `CONFLICTED` at Step 2 → train-level `preflight_failed` naming the node (the existing
  behaviour at `:2508-2520`), never a silent replay of a stale head. The earlier wording
  (`blocked`/`publish_transaction_conflicted`) described the wrong status at the wrong stage.
- **D8. Text reconciliation (r3 wording).** The preflight message no longer instructs a
  manual merge. The run-train skill states: prebuilt nodes with ZERO upstream edges land under
  `--governed`; prebuilt nodes with any upstream edge, order-only included, stop at
  `drafts_open` pending the follow-up below; closing a stale PR is done by the operator only when the coordinator's
  `blocked` reason says so.

- **D9. Maintainer decision (r2): accept the D2 window, or close it with compare-and-swap.**
  `git push --force-with-lease=<branch>:<admitted_head>` would refuse ANY remote change in
  the window, including a fast-forward, and is the only mechanism that enforces "remote still
  equals admitted" at publication time. It is a `--force*` option, and the operator
  requirement is non-force publication. Default for this plan: keep the non-force exact-head
  push, accept the fast-forward window, and test the divergent case fails closed. If the
  maintainer wants the window closed, that is a broker change with its own review, not a
  silent flag flip.

Out of scope (each gets a follow-up issue on landing, none is a TODO in code): a prebuilt
reverify substitute for upstream-bearing prebuilt nodes (the follow-up the code names at
`:2470-2471`); surfacing `fab_run_id` through prebuilt admission; refresh for execute
nodes; the tagged release and consumer re-pin that make this an INSTALLED fix.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` (modify)
- Step 4 skip block (`~2698-2750`) — modify — replace the no-upstream-change `continue` with
  the prebuilt local-advance decision (D1, D2, D3); reuse `completed_nodes[nid]["admitted_head_sha"]`,
  re-read the live head, and read the workspace HEAD via the same git helper the prebuilt
  preflight uses. The upstream-changed `blocked` return is unchanged.
- Step 3 live read (`~2651`) — modify — wrap in the `blocked` pattern (D6).
- Governed preflight rejection (`~2466-2483`) — modify — narrow per D5; message names the
  offending edge and no longer says "merge manually".
- No change to the prebuilt publish arm, the success epilogue, `_live_merge_pr`, or the P4
  loop. If implementation finds one is needed, stop and amend this plan.

### `phase-loop-runtime/src/phase_loop_runtime/publishing.py` (modify)
- `inspect_publish_resume_candidate` — modify — a `TERMINAL_SEALED` active transaction is a
  completed prior publication: return no resume candidate (a dedicated state, not `None` and
  not `CONFLICTED`), matching what `prepare_prebuilt_transaction` and its sibling already
  assume at `:742`/`:804`. Nothing else in the store is touched; no tombstone is fabricated.
- `publish_from_worktree(prebuilt=True)` against an existing branch/PR — verify by test —
  push fast-forwards, `gh pr create` collision reconciles to the same PR, readback pins the
  new head (`credsep.py:551`). If any step refuses, the refusal is the finding; do not patch
  around it.

### Tests (create/modify)
- `phase-loop-runtime/tests/test_train_prebuilt.py` — modify — split
  `test_governed_prebuilt_opens_zero_prs` into "prebuilt with ANY upstream edge (one case
  channel-carrying, one case ORDER-ONLY) still refused at preflight, zero PRs" and
  "single-node prebuilt admitted under --governed"; add an end-to-end refresh case that runs
  the REAL Step 2 inspection with a sealed prior transaction in the checkpoint root and
  FABPUB active (the round-1 blocker); add refresh cases: unchanged resume (zero publish calls, ledger unchanged), valid refresh (publish
  called once with the new head; new `pr_open` appended; prior record intact), remote drift
  (`blocked`/`remote_drift`), diverged candidate (`blocked`/`candidate_diverged`), rejected
  admission (`blocked`). "Zero effects" is asserted as zero push and zero PR-creation calls
  at the broker seam, not as zero `publish_fn` calls: under FABPUB, admission happens INSIDE
  `publish_from_worktree`, so a rejected admission necessarily enters it (r3, codex). The
  drift and divergence refusals additionally assert `publish_fn` was never entered, since
  they are decided before it. A rejected admission leaves the latest `pr_open` at the old
  head.
- `phase-loop-runtime/tests/test_train_merge.py` — modify — governed single-node prebuilt
  merges with `--match-head-commit` pinned to the refreshed admitted head; crash after the
  `running` append and before terminal evidence resumes to ONE open PR at HEAD with the prior
  `pr_open` line still in the file (D4); an out-of-band
  push after the refresh fails closed exactly as `test_oob_push_after_admission_merge_pinned_to_admitted_not_live` does today; interrupted refresh replays via the transaction arm and a
  further-advanced workspace yields train-level `preflight_failed` naming the node (D7, r3
  wording); train review
  not approved → zero merges (unchanged assertion, re-run with a prebuilt node).
- publishing transaction tests — modify — a SUCCESSFUL FABPUB prebuilt publish after the
  inspector change (post-accept path at `publishing.py:1185-1195` still seals); a sealed
  prior with `effect_terminal_observed` evidence → no resume candidate; a sealed prior with
  `outcome_ambiguous_blocked` evidence → `preflight_failed` at Step 2; a sealed prior at the
  publish entry → a NEW transaction is prepared for the new head.
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
- [ ] Unchanged resume, remote drift, diverged candidate and rejected admission each cause
  zero push and zero PR-creation effects; the two refusals append `blocked` with the named
  reason and never enter `publish_fn`.
- [ ] A single-node prebuilt train under `--governed` passes preflight, opens its draft,
  runs train review, and merges pinned to its latest admitted head; an upstream-bearing
  prebuilt train is still refused at preflight with zero PRs.
- [ ] A sealed prior transaction does not block a refresh at preflight; an interrupted
  refresh resumes through the existing transaction arm; a workspace that advanced again
  yields train-level `preflight_failed` naming the node, never a replay of a stale head or a
  duplicate PR.
- [ ] A live-head read failure on resume yields `blocked`, not an uncaught exception.
- [ ] Runtime message, skill sources and generated copies agree; parity test green.

## Execution Policy
- execute: effort=high, reason=coordinator resume/publish/merge control flow with exact-head and admission invariants
