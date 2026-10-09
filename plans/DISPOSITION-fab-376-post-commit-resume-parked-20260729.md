# Disposition note — FAB `agent-harness#376` post-commit crash-resume seam: PARKED at round 5

*Status: PARKED with two open blockers. This is a RECORD, not a fold — no sixth round was attempted.*
*Branch `plan/376-post-commit-resume-seam` @ `92c8d1b` is the last round-4-folded state of the plan (`plans/detailed-fab-376-post-commit-resume-seam-20260729.md`, 10 ACs).*
*Author: opus-4.8[1m], 2026-07-29. Companions: PR `agent-harness#383` (DRAFT), deferred capability `agent-harness#388`, memory `fab-376-resume-seam-branch.md`, five board transcripts (rounds 1–5).*
*Source anchors verified on `origin/main` @ `1dd3a83` and on branch @ `92c8d1b`, 2026-07-29.*

## Why this note exists

`agent-harness#376` is a **real fix for a live stuck-node bug**, but it is a fix, not roadmap
hardening (the maintainer's standing test: *"roadmap hardening that stops downstream churn"*). It
took five cross-vendor rounds, absorbed a scope cut, and — the decisive fact — **its base moved
underneath it**: `agent-harness#384` merged to `main` (~1h before this note, commit `1dd3a83`) and
changed the very `LedgerRecord` schema this plan prescribes edits to, so one of the two round-5
blockers is not a text defect but **cross-PR staleness created by a merge**. Resolving that blocker
needs a rebase and a re-derivation against the new schema, not a patch. The maintainer parked the
plan in favour of landing `#375` and `#382`, which meet the hardening test. This note preserves the
five rounds of understanding so a successor can resume from a starting point rather than from zero.

| round | board verdict | what it found |
|---|---|---|
| 1 | grok + codex DISAGREE, 5 findings | resumed-execute-node reconstruction class (prebuilt-defaults inheritance) → AC-376-5..9 |
| 2 | grok + codex DISAGREE, 2 blocking | AC-376-2 unreachable through production `run_train` (preflight rejects before the ledger is read) → recovery-aware preflight + AC-376-10 |
| 3 | codex DISAGREE (13 anchors) | equal-HEAD `reset --hard` DESTROYS unrelated work (the "strictly non-regressive" justification was false); confinement is authorization, not identity → post-commit SHA |
| 4 | codex DISAGREE, 1 BLOCKS-MERGE | the round-3 quarantine ref is reusable → a second pre-commit crash orphans the first capture → **(Z) scope-cut** (crash-before-commit auto-resume removed; filed as `#388`) |
| 5 | grok PARTIAL (0 blocks), gemini AGREE, codex DISAGREE, **2 BLOCKS-MERGE** | AC-376-6 asserts an observable `run_train` cannot emit; the ledger-schema edit conflicts with post-`#384` `main` |

Each round found a **different** defect and each fold held — this is convergence, not the
`#368`-style chain where one identity change generated three consecutive defects. It stalled not on
a wall but on a cost/value judgement: a fifth round plus a rebase, for a fix rather than hardening.

## 1. What `#376` is, and that it is a LIVE bug

A train node that crashes **after** its commit but **before** terminal broker evidence cannot
resume its publish. On resume it re-enters the normal publisher; the already-committed tree makes
staging a no-op, so `publish_from_worktree` returns `_blocked("nothing_staged")`
(`publishing.py:225`) **before the broker is ever consulted**. `run_train` writes `pr_open` only
after a successful publish, so the crash window leaves only a `running`/`committing` ledger record —
resume cannot distinguish *committed-not-published* from *not-yet-committed*, and the node is stuck
permanently. This is epoch-independent: the publish idempotency key is
`sha256(repo\0branch\0head_sha)` (`verbs.py:25-26`), so AC-376-1/2/3 fail-then-pass on today's
`lease_epoch=1` code with no dependency on `#368`. Only AC-376-4 (cross-epoch rebuild) is
`#368`-gated. The bug is real and unfixed; parking is a priority decision, not a dismissal.

## 2. The four defects the rounds found (each grounded)

A successor re-deriving the plan needs these so a rewrite does not walk back into them:

1. **Prebuilt-defaults inheritance (round 1, B1/B2/codex-2/codex-3).** The plan first routed a
   *resumed execute node* through the *declared-prebuilt* publish path and let it inherit that
   path's defaults — no `run_loop`, no live snapshot, no FAB provenance, and whole-committed-diff
   scope. That is correct for a prebuilt node and wrong for a resumed execute node, which had all of
   it and lost the live copy to the crash. The only durable carrier across a crash is the ledger, so
   the `committing` marker must persist exactly what resume needs to reconstruct the node
   (`fab_run_id`, `owned_paths`, `completed_nodes` population). Anchor: the prebuilt path branches on
   `getattr(node, "mode", "execute") == "prebuilt"` (`train_runner.py:341`); `_prebuilt_owned_paths`
   measures against `origin/<base>` (`:254-303`).
2. **AC-376-2 unreachable through production `run_train` (round 2, finding 1 — the load-bearing
   one).** The resume mechanism was confined to a ledger marker + a Step-4 branch, but the resume
   *entry point* rejects a marked node before the marker is read: `_default_preflight`
   (`train_runner.py:307`) has no ledger parameter, `_check_repo_clean` (`:172`) fails on any
   `git status --short` output, and `run_train` returns `preflight_failed` (`:2298`) **before**
   `read_ledger` (`:2303`). **This structure still holds on `origin/main` @ `1dd3a83`** — the ledger
   read is still after preflight. Fix (a ratified scope increase): recovery-aware preflight — read
   the ledger before preflight and exempt *only* `_check_repo_clean`, *only* for a marked node. This
   is the same unreachable-path defect class the plan closes (`#368` AC-12/13 sin); see memory
   [[verify-the-proof-not-just-the-fix]].
3. **The false "strictly non-regressive" reset justification (round 3, finding 1).** The equal-HEAD
   recovery arm ran `git reset --hard` + `git clean -fd`, which can DESTROY unrelated uncommitted
   work. The round-2.5 "strictly non-regressive" claim was false: existing preflight BLOCKS while
   PRESERVING bytes (recoverable); reset+clean blocks AND deletes (unrecoverable). Parity with a
   REFUSAL is not parity with the OUTCOME. This is what forced the preserve-before-destroy
   invariant — and, one round later, (Z).
4. **The quarantine ref-collision (round 4, codex BLOCKS-MERGE).** The round-3 fix — quarantine the
   dirty tree to `refs/fab-quarantine/<node>/<run_id>` before any reset — is not crash-safe: the ref
   is reusable, so a second pre-commit crash overwrites it and orphans the first capture *while both
   "ref resolves" checks pass* (a verification green while the thing it verifies is destroyed — the
   exact class this plan exists to eliminate, now inside the preservation invariant). Grounded
   aggravators: `fab_run_id_for_reviewed_tree` is deterministic from the reviewed tree
   (`fab_producer.py:106`) so a repeated crash reuses the same ref; non-FAB nodes have `run_id=None`
   (`train_runner.py:2519`) so the ref name has no discriminator; and
   `git stash push --include-untracked` mutates+cleans the worktree *before* the ref is written.

## 3. The (Z) scope cut and why it was right

The pivot that ended the mechanism argument: **the headline bug (AC-376-1, a POST-commit crash) has
no preserve/destroy problem** — a committed node routes to the publish path and never resets. The
entire (P)/(W)/quarantine contest applied *only* to AC-376-2, the crash-**before**-commit companion
arm. So the real question was never "which preserve mechanism," but "is auto-resuming a pre-commit
crash worth *any* new mechanism," given the bug is fixed either way.

(Z), lead-ratified round 4: scope the pre-commit auto-resume OUT. Narrow the preflight exemption to
Record-B (`committed_head_sha`-present) nodes; a pre-commit crash (Record A only) BLOCKS at
preflight and its bytes survive on disk untouched — the existing behaviour, strictly non-regressive,
**byte survival by inaction** (the maintainer's original "byte-identical afterwards" control,
satisfied by declining to act). Step 4 gains no tree-mutating op. AC-376-10 was KEPT (verified
load-bearing: `publishing.py:163` stages only `owned_paths`, never `git add -A`, and runs no
`git clean`, so untracked `run_loop` residue outside owned scope genuinely survives a legitimate
commit — the Record-B exemption is non-vacuous). AC-376-11 was retired into AC-376-2's positive
control. The class here is the `#368` accumulated-scope shape localized to a companion case: each
preserve mechanism generated the next defect (`reset --hard` destroys → quarantine-ref orphans), and
(Z) stops adding mechanism rather than folding a fourth one.

## 4. The two open round-5 blockers (both verified at source)

**Blocker 1 — `AC-376-6` asserts an observable `run_train` cannot emit (the
assertion-cannot-be-expressed vacuity form).** The AC's positive arm requires `run_train` to return
`{"status":"published"}` (plan `:1277`, and AC-376-1 at plan `:1159`/`:1419`). But **`run_train`
never returns `published`.** Its terminal statuses are `completed` (`train_runner.py:2804`),
`drafts_open` (`:2813`), `merged` (`:3247`), `blocked`, and `preflight_failed`. `published` is
returned only by `publish_from_worktree` (`publishing.py:199`) — an inner call whose result becomes
an entry inside `completed_nodes`, not the train-level return. A test written literally to this AC
fails on a correct implementation; "fixing" it by making `run_train` return `published` would break
the train-return contract and AC-376-8 (which expects `completed`/`drafts_open` with
`completed_nodes` populated). *Resolution direction (UNVETTED — a successor's starting point, not a
fold):* re-express every AC-376 positive/negative observable against `run_train`'s real terminal
(`completed`/`drafts_open`) plus `completed_nodes[nid]` state plus whether `broker.execute` was
called — never against a `published` string the entry point does not produce. This is at least the
fifth instance of the assertion-cannot-be-expressed form the maintainer flagged across three plans
tonight; the class deserves a sweep, not a point patch.

**Blocker 2 — the ledger-schema edit conflicts with post-`#384` `main` (base moved under the
plan).** The plan (design §Changes, plan `:290-293`, `:831-844`) states that `LedgerRecord.to_dict`
"currently hard-codes the omit-when-`None` filter to `fab_run_id` ONLY" and prescribes an exact
replacement omit-set. **That was TRUE when written and `#384` made it FALSE.** On `origin/main` @
`1dd3a83`, `LedgerRecord` (`train_ledger.py:148`) now carries two more optional fields —
`usable_reviewers` and `review_policy_version` (added by `agent-harness#358`/`#384`) — and its
filter is already `_omit_when_none = ("fab_run_id", "usable_reviewers", "review_policy_version")`
(`train_ledger.py:197`). Implemented literally against the plan's stated premise, the prescribed
replacement set would DROP those two fields from the omit filter, so ordinary review records would
serialize null review fields — violating byte-neutrality and the `#358` ledger contract the same
fields exist to honour. **This is not a text patch: the plan must be rebased onto post-`#384` `main`
and its schema edit re-derived against the actual current `LedgerRecord` — adding the `committing`
marker's fields to the *existing* three-field omit set, not replacing it.** A successor who patches
the text without rebasing will chase a phantom (the "`fab_run_id` only" premise no longer exists on
disk).

## 5. The proven deferred design lives in `#388` (not lost)

The capability (Z) removed — auto-resume of a pre-commit crash — is filed as `agent-harness#388`
with a design that was **positive-controlled this round**, so it is reachable rather than lost:

- **Non-mutating capture** via a scratch index OUTSIDE the worktree:
  `GIT_INDEX_FILE=<outside-worktree> git read-tree HEAD && git add -A && git write-tree` — captures
  tracked-mod + tracked-del + untracked with the worktree byte-identical before/after, so the
  "BLOCK if unproven" branch leaves bytes untouched (stash mutates-then-proves; this
  proves-then-mutates). *Caveat carried into `#388`:* the scratch index MUST live outside the
  worktree or it self-pollutes (caught in the first positive-control run).
- **Collision-free naming by TREE sha** — `refs/fab-quarantine/<node>/<tree_sha>`: identical bytes →
  same ref (idempotent, no orphan), distinct bytes → distinct ref; `run_id` leaves the name, so both
  round-4 aggravators evaporate. Create-only `update-ref … 000…0` refuses to overwrite.
- **Wrinkle for the builder:** an identical re-crash finding the ref present must read as
  "preservation already holds, proceed," NOT a block.

grok (round-5 F1) reached the same primitive from the spec alone and graded it FOLLOW-UP; the
corroboration is recorded on `#388`.

## What a successor picking up `#376` must do FIRST

1. **Rebase `plan/376-post-commit-resume-seam` onto post-`#384` `main` and re-derive the
   `LedgerRecord` schema edit** against the real three-field `_omit_when_none` (Blocker 2). Do this
   before any text work — the plan's schema premise is stale on disk.
2. **Re-express every AC observable against `run_train`'s real terminals** (`completed`/
   `drafts_open` + `completed_nodes` + `broker.execute` called), never `published` (Blocker 1).
   Treat this as a class sweep across all AC-376 arms, not a single-line edit.
3. **Re-confirm the parking rationale still holds.** `#376` is a real live bug; if `#375`/`#382`
   have landed and priorities shift, the plan is one rebase + one observable-layer correction from
   round-6-ready. Nothing in the design was overturned in round 5 — both blockers are
   expression/staleness defects, not mechanism defects.

*Speculation label:* items 1–2 name directions the round-5 board did NOT vet end-to-end; they are
starting points derived from the two grounded blockers, not ratified solutions. The (Z) design and
the four historical folds (sections 2–3) ARE grounded and held.

## Anchors (verified 2026-07-29)

- `phase-loop-runtime/src/phase_loop_runtime/publishing.py` — `nothing_staged` (`:225`, the live
  bug); `published` returned only here (`:199`); `on_committed` insertion point after `head_sha`
  capture (`:188-190`, before broker execute `:196`).
- `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` (@ `1dd3a83`) — `_check_repo_clean`
  (`:172`); `_default_preflight` (`:307`, no ledger param); prebuilt branch `:341`; `run_train`
  (`:2126`); `preflight_failed` returns (`:2265`/`:2284`/`:2298`) BEFORE `read_ledger` (`:2303`);
  `_node_fab_run_id: Optional[str] = None` (`:2519`, non-FAB nodes); terminals `completed` (`:2804`),
  `drafts_open` (`:2813`), `merged` (`:3247`) — none `published`.
- `phase-loop-runtime/src/phase_loop_runtime/train_ledger.py` (@ `1dd3a83`) — `LedgerRecord`
  (`:148`); the two `#358`/`#384` fields `usable_reviewers`/`review_policy_version`; the current
  three-field `_omit_when_none` (`:197`).
- `phase-loop-runtime/src/phase_loop_runtime/fab_producer.py:106` — `fab_run_id_for_reviewed_tree`
  deterministic from the reviewed tree (the round-4 ref-collision root).
- Plan (last folded): `plans/detailed-fab-376-post-commit-resume-seam-20260729.md` @ `92c8d1b`
  (10 ACs; AC-376-6 positive arm `:1277`; §Changes ledger-schema `:831-844`).

## Cross-refs

- `agent-harness#383` — PR (DRAFT) carrying this plan; leave DRAFT, do not close (the bug is real).
- `agent-harness#388` — the deferred pre-commit auto-resume capability with the proven-safe design.
- `agent-harness#384` (`1dd3a83`) — the merge that moved the base under Blocker 2.
- `agent-harness#358` / `#375` — the review-evidence work that owns `usable_reviewers`/
  `review_policy_version`; a `#376` rebase must not regress their ledger contract.
- Memory: `fab-376-resume-seam-branch.md` (full round log), `verify-the-proof-not-just-the-fix.md`
  (the unreachable-path class of Blocker 1 and defect 2), `relay-findings-not-summaries.md`.
