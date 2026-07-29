# Detailed plan: post-commit crash-resume seam for train publish (`Consiliency/agent-harness#376`)

> **PLAN ONLY.** No implementation, no merge. Written 2026-07-29 to be paneled;
> revised for the round-1 board (grok+codex, five findings — see `## CR fold`),
> the round-2 board (two blocking — `## CR fold — round 2`), and the round-3 board
> (codex DISAGREE 13 anchors, two blocking — `## CR fold — round 3`).
> **Core (AC-376-1/2/3, and the CR fold AC-376-5..11) is INDEPENDENT of `#368` and
> fixes the reachability + safety defects on today's code** (the publish
> idempotency key is epoch-independent — see `## The #368 interlock`). Identity is
> now an EXACT match against a POST-commit `committed_head_sha` (round-3 finding 2 —
> confinement proved AUTHORIZATION, not identity; `## Commit identity via post-commit
> SHA`), recorded by a best-effort `on_committed` callback (a named `publishing.py`
> scope increase). The crash-before-commit arm PRESERVES the dirty tree before
> regenerating (round-3 finding 1 — the round-2.5 `reset --hard` destroyed unrelated
> work; "non-regressive" was FALSE). The reachability fix includes this plan's OWN
> recovery-aware preflight change (round-2 finding 1, lead-ratified in-scope). Two
> scope increases are named to the lead in `## CR fold — round 3`. **Only `AC-376-4`**
> — the cross-epoch identity proof — is `#368`-gated. See `## Dependencies & order`.
> Scope: the CRASH case only (last ledger record survives as `committing`). The
> graceful post-commit-block variant is filed as `Consiliency/agent-harness#380`;
> the broker `PROVIDER_CALL_IN_FLIGHT` recovery gap (codex 1) is a separate
> broker follow-up — neither is built here (see
> `## Scope & explicitly-deferred variants`).

## Task

Close `Consiliency/agent-harness#376`: a train node that crashes **after** its
commit but **before** terminal broker evidence cannot resume its publish. On
resume it re-enters the normal publisher; the already-committed tree makes
staging a no-op; `publishing.py:223` returns `_blocked("nothing_staged")` before
the broker is ever consulted. `train_runner.py:2780` writes `pr_open` only after
successful publication, so the crash window leaves only the earlier `running`
ledger record — resume has **no marker distinguishing committed-not-published
from not-yet-committed**, and no commit-detection / prebuilt-recovery switch
exists anywhere in `train_runner.py:2562-2702`.

The obligation: make a node that crashed after commit resume and publish the
**same committed tree** through the broker; make a node that crashed **before**
commit re-run normally; fail closed on any state that is neither.

## Research summary

All source below was read directly in this session against the plan branch
`plan/288-shared-epoch-allocator` (HEAD `a2025c1`), which is what #376 builds on.

- **The broker layer is crash-safe EXCEPT one narrow sub-window (corrected in CR —
  codex 1).** `execute`'s replay-before-admit sequence (#288/#337) dedups an
  already-published head via the evidence store; the idempotency key is
  `publish_committed_branch_idempotency_key(repo, branch, head_sha)` — stable
  across resume because `head_sha` is the frozen committed SHA. The primary defect
  is that the normal publisher never REACHES the broker on resume:
  `publish_from_worktree`'s staged-diff audit fires `nothing_staged`
  (the `_audit_staged_diff` "nothing staged" branch, `publishing.py:223`) before
  `broker_client.execute(...)` (`publishing.py:196`). **But the broker's recovery
  is NOT total.** The replay guard (the "state is not `PROVIDER_CALL_IN_FLIGHT`"
  test, `verbs.py:58`) explicitly EXCLUDES an in-flight record from replay, and
  `record_intent` writes `PROVIDER_CALL_IN_FLIGHT` (`verbs.py:65`) BEFORE the
  adapter call (`verbs.py:67`). So a crash after `gh pr create` SUCCEEDS but
  before `record_terminal` (`verbs.py:72`) leaves the evidence in-flight; on
  resume the adapter is RE-INVOKED, credsep's `git push` is idempotent but
  `gh pr create` hits GitHub's "a PR already exists" and returns non-zero, so the
  `gh pr create` non-zero branch returns `_ambiguous("pr-unconfirmed")`
  (`credsep.py:284`) — **before** the existing-PR recovery read (the `gh pr list`
  at `credsep.py:293`) is ever reached. Net: that sub-window resolves to
  `OUTCOME_AMBIGUOUS_BLOCKED`. This FAILS CLOSED (a determinate block, no silent
  loss — the commit is pushed and the PR exists), it is NOT a fail-open; but it is
  NOT "publishes," so #376's scope claim and AC-376-1 are corrected accordingly
  (see `## Broker in-flight sub-window` and AC-376-1) and the broker-side recovery
  (credsep should `gh pr list --head` to adopt an already-created PR before
  returning ambiguous) is filed as its own follow-up — it is a pre-existing broker
  gap #376 merely makes reachable on the resume path, not new machinery to build here.
- **The recovery machinery already exists and is production-wired.** The
  `prebuilt=True` path in `publish_from_worktree` skips staging (`:164`), the
  staged-diff audit (`:173`), and the commit (`:179`), resolving `head_sha` from
  `git rev-parse HEAD` (`:157`) and going straight to `broker_client.execute` at
  `:196`. And `train_runner.py:2518-2561` already routes a **declared** prebuilt
  node through that path: it reconstructs `owned_paths` from the committed diff
  (`prebuilt_owned_paths_fn(workspace, _DEFAULT_BASE)`, `:2536`) and builds the
  admission via `admission_fn(...)` (`:2554`). **#376 is not new publish/broker
  machinery** — it is a durable pre-commit marker + resume-detection that routes
  a committed-unpublished EXECUTE node through this existing prebuilt path.
  **CORRECTION (CR — B1/B2/codex 2/codex 3): a resumed EXECUTE node is NOT a
  declared prebuilt node,** and routing it through the declared-prebuilt path
  verbatim silently inherits that path's defaults — no `fab_run_id` (fail-open,
  B1), no `completed_nodes` population (multi-node break, B2), whole-branch-diff
  `owned_paths` (broadened authorization, codex 3), and a parentage-only landed
  check with no committed-tree identity (codex 2). Those defaults are correct for
  a node whose work was built and verified ELSEWHERE; they are wrong for a node
  that ran `run_loop` in THIS train and lost its live snapshot to the crash. The
  fix is one class, stated in `## The resumed-execute-node reconstruction class`:
  the marker must PERSIST the execute node's pre-crash state (committed-tree
  identity, `fab_run_id`, owned scope) so resume RECONSTRUCTS it faithfully
  instead of borrowing the prebuilt path's assumptions.
- **The admission builder, verified TODAY** (`_default_build_admission`,
  `train_runner.py:103-144`): binds `base_sha = git rev-parse HEAD` (`:119-120`)
  and `lease_epoch=1` (`:138`, the constant #288 removes). This precisely bounds
  the #368 interlock — see `## The #368 interlock`.
- **Ledger contract** (`train_ledger.py`): `VALID_STATUSES = {pending, running,
  pr_open, approved, merged, blocked}` (`:56-58`); `LedgerRecord` is append-only,
  last-record-wins fold (`read_ledger`, `:302-345`); `append_record(...,
  durable=True)` fsyncs (`:254-296`) — used today only by `_fab_delta_readmit`
  as the re-admission commit point; the `to_dict` omit-when-`None` pattern
  (`:175-183`, for `fab_run_id`) keeps records byte-neutral when a new optional
  field is unset.
- **The exception handler at `train_runner.py:2704` is `except Exception`** — it
  does NOT catch `SystemExit`/`KeyboardInterrupt` (`BaseException`). A hard
  crash (signal / `os._exit` / injected `BaseException`) therefore writes NO
  terminal record, leaving the `committing` marker as the last record. A
  GRACEFUL post-commit failure (broker returns not-accepted, `:2721`; or a
  normal `Exception`, `:2707`) writes `blocked` — a different, deferred case.

## The defect and the crash window (precise)

The crash window spans from the commit (`publishing.py:179`) to the `pr_open`
append (`train_runner.py:2780`), covering the commit, `broker.execute` (push +
PR open + terminal evidence), and the FAB run-id bind. A hard kill anywhere in
that window leaves: a committed local tree, and a ledger whose last record for
the node is `running` (from `:2509`) — indistinguishable from "crashed during
`run_loop`, never committed." Resume re-runs; staging is a no-op; `nothing_staged`.

## CR fold (round-1 board: grok + codex DISAGREE, five findings)

The lead's header said "four blockers" and listed five; the fifth (grok B2) is
carried, not dropped. Disposition of all five, each grounded against source this
session:

| # | Finding | Root | Fix in this fold | AC |
|---|---|---|---|---|
| codex 2 | `HEAD^ == pre_commit_head` proves PARENTAGE, not committed-tree identity | marker records only the pre-commit parent | ~~marker records `expected_tree_sha`; resume requires `HEAD^{tree} == expected_tree_sha`~~ **SUPERSEDED in round-2 finding 2** (exact-tree false-rejects a hook-mutated legitimate commit), then **again in round-3 finding 2** (confinement proved authorization, not identity) → identity is now the POST-commit `committed_head_sha`, see `## Commit identity via post-commit SHA` | AC-376-6 |
| grok B1 | routing a resumed FAB node through the prebuilt path drops `fab_run_id` → merge-gate inert → **fail-open** | prebuilt path leaves `_node_fab_run_id=None` (`:2526-2532`) | marker carries `fab_run_id`; resume epilogue runs `_resolve_admission_fab_run_id` → bind or BLOCK | AC-376-7 |
| codex 3 | recovery broadens authorization to whole-branch-diff | prebuilt `owned_paths` = committed diff vs base (`:2536`) | marker persists the node's `owned_paths`; resume publishes at that scope | AC-376-9 |
| grok B2 | resume epilogue omits `completed_nodes` | epilogue collapsed to "write `pr_open`" | resume runs the FULL normal epilogue `:2739-2792` | AC-376-8 |
| codex 1 | crash window not fully covered — `PROVIDER_CALL_IN_FLIGHT` sub-window re-invokes `gh pr create` → ambiguity | broker replay excludes in-flight (`verbs.py:58`); credsep returns ambiguous before adopting an existing PR (`credsep.py:284` vs `:293`) | premise + scope corrected (fails CLOSED, not open); broker recovery filed as a follow-up | AC-376-5 |

codex 2, B1, B2, codex 3 are ONE class (the resumed-execute-node needs persisted
state — next section). codex 1 is a distinct pre-existing broker gap #376 makes
reachable. Priority the lead set — codex 2 and grok B1 first (the two that make
the fix worse than the bug) — is reflected in the marker-identity and FAB-scope
work being the load-bearing changes.

## CR fold — round 2 (grok + codex DISAGREE, two blocking; gemini AGREE, 0 anchors — non-corroborating)

Both blockers were verified against source THIS session before folding (the
line/symbol evidence is in each row's "Grounded" cell). Gemini's AGREE cited
nothing and is treated as non-corroborating.

| # | Finding (round-2) | Grounded against source | Root | Fix in this fold | AC |
|---|---|---|---|---|---|
| **round-2 finding 1** (severe) | AC-376-2 (and the whole resume mechanism) is UNREACHABLE through production `run_train`: the marker is written while the tree is still dirty; on resume `_default_preflight` rejects the dirty workspace and `run_train` returns `preflight_failed` BEFORE it ever reads the ledger — so no Step-4 arm runs. | `_default_preflight(nodes, resolve_workspace)` (`train_runner.py:303`) has NO ledger param; `_check_repo_clean` fails on any `git status --short` output (`:181-182`); `run_train` returns at `:2294` before `read_ledger` at `:2299`; and preflight failure is a STRUCTURAL whole-train abort (`:17-19`), so one dirty marked node blocks the entire resume. | The fix was confined to a ledger marker + a Step-4 branch, but the resume ENTRY point (preflight) rejects a marked node before the marker is read. It is the exact `#368` AC-12/13 sin: a fix proven against a path production cannot enter. | **Recovery-aware preflight** — read the ledger at Step 1.5 (before preflight), thread `ledger_state` into `_default_preflight`, and exempt ONLY `_check_repo_clean`, ONLY for a node carrying a durable `committing` marker; every other failure (and every unmarked dirty node) still aborts, zero PRs. The crash-before-commit arm then `git reset --hard`+cleans the untrusted dirty tree and re-runs. See design §1b (`### 1b. Recovery-aware preflight`). **This IS a scope increase (run_train entry reorder + preflight signature/behaviour); the lead RATIFIED keeping it in this ONE plan — in-scope, not adjacent (it is the same unreachable-path defect class this plan closes; the marker + gate interlock at one entry point and neither half is independently useful). See §1b "Why this is in scope."** | AC-376-2 (rewritten), **AC-376-10** (new) |
| **round-2 finding 2** | `expected_tree_sha` (round-1 codex 2) is NOT guaranteed to equal the tree the publisher produces: the marker computes the tree in a temp index with one `git add`; the publisher does a SECOND `git add` + an unrestricted `git commit -m`, so a clean filter or a mutating pre-commit hook can make a LEGITIMATE completed commit's tree differ from the marker → the resume misroutes it to `committed_head_ambiguous_on_resume` even with terminal broker evidence — a correct crash-resume REFUSED (a new stuck-node). | publisher `git add -- owned_paths` (`publishing.py:164`, clean filters apply) then `git commit -m` (`:179`, runs pre-commit hooks — the `:184` error string names "a pre-commit hook rejected the commit"); the marker's temp-index `write-tree` sees neither. | Any tree identity computed BEFORE `git commit` cannot predict a mutating hook; exact-tree's only strength over parentage IS that false-positive. | **Drop `expected_tree_sha`; identity = parent + owned-scope confinement** — `HEAD^ == pre_commit_head` AND `_paths_covered_by_owned(enumerate_changed_paths(…, pre_commit_head, HEAD), rec.owned_paths)`, REUSING the runtime's existing helpers (`train_runner.py:738-754` → broker's `_covered_by_owned`; `fab_canonical.py:641-664` `-z --no-renames`) — the `#371`-safe single implementation, not a new mirror. Hook-robust: a hook reformatting owned files changes blobs, not the changed-path SET. **(Round-3 finding 2 SUPERSEDED this: confinement is authorization, not identity — identity is now the POST-commit `committed_head_sha`; see `## CR fold — round 3` and `## Commit identity via post-commit SHA`.)** | AC-376-6 (rewritten) |

**Grok non-blocking (folded anyway per the lead).** The `## The #368 interlock`
point 1 prose was imprecise: `_default_build_admission` runs `git rev-parse HEAD`
(`:119-120`) at `admission_fn(...)` (`train_runner.py:2695`) — which is BEFORE
`publish_fn`'s commit (`:2698` → `publishing.py:179`) — so the FIRST execute
admission's `base_sha` is the PARENT (pre-commit), while the resume prebuilt
rebuilds at the committed HEAD: the two `base_sha` values DIFFER on today's code.
Core resume independence never rested on `base_sha` stability — it rests on the
head_sha-keyed publish idempotency key — so the substance holds and the wording
is corrected in-place (it actually STRENGTHENS the #368-independence claim). Grok
also confirmed AC-376-1/2/3/5–9 observables map to real symbols and AC-4 correctly
avoids `granted_epoch`.

## CR fold — round 3 (codex DISAGREE, 13 anchors; grok AGREE 13; gemini AGREE 4)

Two blocking findings. The first OVERTURNS a justification the round-2.5 fold
added and the lead approved; the second is the deepest correctness point in the
review to date. Both were verified against source before folding. The rest of the
plan (preflight-exemption scope, the reuse of `_paths_covered_by_owned` /
`enumerate_changed_paths` as CRAFT, the faithfulness constraint) survived review.

| # | Finding (round-3) | Grounded against source | Root | Fix in this fold | AC |
|---|---|---|---|---|---|
| **round-3 finding 1** (overturns an approved justification) | The equal-HEAD recovery arm can DESTROY unrelated user work. The `committing` marker proves only that a crash occurred — NOT that every tracked/untracked change in the tree came from this run. The round-2.5 arm skips the clean gate and runs a repository-wide `git reset --hard` + `git clean -fd`, deleting any unrelated uncommitted edits. The round-2.5 "strictly non-regressive" justification is FALSE: the existing behaviour BLOCKS while PRESERVING those bytes; the plan blocks-then-DELETES. A stranded node is recoverable; deleted uncommitted work is not — a regression on the one axis that matters. | Existing preflight `_check_repo_clean` (`:181-182`) BLOCKS on a dirty tree and touches nothing — bytes survive on disk. The round-2.5 arm (§1b, §2) issues `git reset --hard rec.pre_commit_head` + `git clean -fd` unconditionally. | "It was going to be rejected by preflight anyway" is parity with the existing REFUSAL, not with the existing OUTCOME (bytes-preserved). Parity of refusal ≠ parity of outcome. | **Never destroy: preserve/quarantine first.** The equal-HEAD arm must durably PRESERVE the full dirty tree (tracked + untracked) to a recoverable, named location BEFORE any `reset`/`clean`, and must BLOCK if that preservation cannot be PROVEN (never `reset --hard` on an unverified quarantine). New **AC-376-11** asserts unrelated pre-existing changes survive a resume. **(Mechanism choice — quarantine-in-place vs fresh-worktree — is a lead decision; it changes the literal positive control, see §1b.)** | AC-376-2 (rewritten), **AC-376-11** (new) |
| **round-3 finding 2** (identity vs authorization) | Owned-scope confinement (round-2.5) is AUTHORIZATION ("was this change permitted"), not commit IDENTITY ("is this the commit we made"). The stated obligation is *publish the SAME committed tree*, fail-closed on foreign state — but confinement ACCEPTS any same-parent foreign commit confined to owned paths. Dropping `expected_tree_sha` (round-2) fixed the hook false-reject but silently substituted a WEAKER adjacent question for the obligation. | §2 else-arm accepts `HEAD^ == pre_commit_head` + `_paths_covered_by_owned(...)` and records `branch` without any check that the committed OBJECT is the one this run produced. The plan's own Execution Policy says "never publish a stale/foreign/unidentified HEAD" — confinement does not establish "not foreign." | A PRE-commit marker cannot name the POST-commit SHA, so it cannot prove identity; confinement was the closest pre-commit signal and got promoted into the identity role it cannot fill. | **Record the post-commit SHA durably (option a), giving EXACT identity.** Add a best-effort `on_committed(head_sha)` callback fired inside `publish_from_worktree` right after the commit (`publishing.py:188-190`, reusing the already-captured `head_sha`); the coordinator's closure durably appends `committed_head_sha`. Resume identity = exact `HEAD == rec.committed_head_sha` (hook-robust: recorded POST-mutation). Confinement is REMOVED from the identity role (the broker still does authoritative owned-scope authorization on publish). The residual commit→append gap (committed, SHA not yet recorded) FAILS CLOSED (`committed_head_unrecorded_on_resume`), a bounded stated limitation — authorization NEVER substitutes for identity. **(New `publishing.py` seam — a scope increase, named to the lead.)** | AC-376-6 (rewritten) |

**This reverses round-2's "rejected alternative (b)" (a second post-commit SHA
marker) — honestly.** Round-2 rejected it as "reduces nothing" because it "still
leaves a commit→marker window." That was WRONG: the SHA record moves the
identity boundary to JUST AFTER the commit, so the entire LONG part of the crash
window — `broker.execute` (push + `gh pr create` + terminal evidence, the
network-round-trip span) — now has EXACT identity; only the tiny synchronous
commit→append gap lacks it, and that gap fails closed. Round-2's rejection
under-counted the window it eliminates. Round-3 finding 2 is exactly the reason to
adopt it.

**Two scope increases named to the lead (a scope increase is a decision, not a
fold).** (1) The `publishing.py` `on_committed` callback — the plan previously had
"no `publishing.py` footprint"; identity requires a durable write from INSIDE the
commit's process (a crash mid-`publish_fn` never returns to `train_runner`), so the
seam is unavoidable for option (a). It is minimal (default-`None`, best-effort — a
failed append never fails the publish) and behaviour/byte-neutral when absent.
(2) Finding 1's preserve-not-destroy mechanism (quarantine vs fresh-worktree)
changes the AC-376-11 positive control the lead specified ("byte-identical
afterwards") — see §1b for why only fresh-worktree satisfies that literally.

## The resumed-execute-node reconstruction class (CR — B1, B2, codex 2, codex 3)

Four of the five CR findings are ONE defect: the plan routed a resumed execute
node through the declared-prebuilt path and let it inherit that path's defaults.
A declared prebuilt node has no `run_loop`, no live snapshot, no FAB provenance,
and its scope IS the whole committed diff — so the prebuilt path is right to skip
all of that. A resumed execute node had ALL of it and lost the live copy to the
crash. The only durable carrier that survives the crash is the ledger, so the
`committing` marker must persist exactly what resume needs to reconstruct the
node faithfully:

| Finding | Inherited prebuilt default (wrong for resume) | Persist on marker | Resume uses it to |
|---|---|---|---|
| **codex 2** (r1) → **r2 finding 2** → **r3 finding 2** | landed-check is parentage only (`HEAD^ == parent`) — any child passes; r1 `expected_tree_sha` false-rejects hook-mutated commits; r2 owned-scope confinement proves AUTHORIZATION not IDENTITY | `committed_head_sha` (post-commit, via best-effort `on_committed` callback — the exact SHA the publisher produced) | require EXACT `HEAD == rec.committed_head_sha` (hook-robust: recorded POST-mutation) → true commit identity, not a pre-commit proxy. Confinement DROPPED from identity; the broker still authorizes owned-scope on publish. Residual commit→append gap fails closed. See `## Commit identity via post-commit SHA` |
| **B1** | `_node_fab_run_id` stays `None` (comment `train_runner.py:2526-2532`) → merge-time re-gate inert → FAB content merges ungated | `fab_run_id` (the run_loop-plumbed value) | re-resolve provenance against the committed head; bind or BLOCK — never silent `None` |
| **codex 3** | `owned_paths = prebuilt_owned_paths_fn(...)` = whole committed diff vs base | `owned_paths` (the node's actual owned scope: run_loop snapshot dirty ∪ injected-upstream union) | publish scoped to what the node OWNED, not everything the branch touched |
| **B2** | success epilogue collapsed to "write `pr_open`" | (nothing new — code, not marker) | run the FULL normal epilogue `train_runner.py:2739-2792`: `completed_nodes[nid]` population incl. `admitted_head_sha` |

Three new marker fields (`pre_commit_head`, `owned_paths`, `committed_head_sha`)
are `committing`-only and omit-when-absent (mirror the `fab_run_id` omit-when-`None`
pattern, `train_ledger.py:175-183`); `committing` is a brand-new status, so no
EXISTING record ever sets them. Byte-neutrality of every non-`committing` record is
preserved as long as `to_dict`'s omit filter is GENERALIZED from the current
`fab_run_id`-only hard-code to include all three new fields — a required, verified
code change, not automatic (see the BYTE-NEUTRALITY TRAP in `## Changes`). (Round-1
`expected_tree_sha` was dropped in round-2; round-3 identity is `committed_head_sha`,
recorded POST-commit by the best-effort callback — see `## Commit identity via
post-commit SHA`. `owned_paths` now carries ONLY recovery scope (codex 3), not
identity.)

## Commit identity via post-commit SHA (CR round-3 finding 2 — supersedes owned-scope confinement)

**The obligation, and three rounds converging on it.** The obligation is exact:
resume must publish *the same committed tree this run produced*, fail-closed on
foreign state (the plan's Execution Policy: "never publish a stale/foreign/
unidentified HEAD"). Identity — "is THIS the commit we made" — is the load-bearing
question, and it took three rounds to answer honestly:

- **Round-1 (codex 2):** parentage (`HEAD^ == pre_commit_head`) proves too little —
  any child of the parent passes. Tightened to an exact committed-tree match against
  an `expected_tree_sha` computed in a temp index.
- **Round-2 (finding 2):** `expected_tree_sha` is computed BEFORE the commit, so it
  cannot predict the publisher's clean-filter (`publishing.py:164`) or pre-commit
  hook (`:179`) mutation → it FALSE-REJECTS a legitimate hook-mutated commit (a new
  stuck-node). Dropped it for owned-scope confinement (`_paths_covered_by_owned`
  over `enumerate_changed_paths`), which is hook-robust.
- **Round-3 (finding 2):** owned-scope confinement answers a DIFFERENT question —
  AUTHORIZATION ("was this change permitted") — and was silently substituted for
  IDENTITY ("is this the commit we made"). It ACCEPTS any same-parent foreign commit
  confined to owned paths. That is a weaker adjacent obligation, and for a
  security-adjacent seam that forbids publishing a foreign HEAD, unacceptable.

**Why no PRE-commit signal can prove identity — and the honest fix.** A pre-commit
marker cannot name the post-commit SHA (the commit does not exist yet), so NOTHING
recorded before the commit can prove "this is the object we made." Confinement was
the closest pre-commit proxy and got over-promoted. The fix is to stop proxying and
record the actual result: **a durable post-commit SHA.**

**The identity (exact, hook-robust).** Resume identifies the node's own committed
head by an EXACT match against a SHA recorded AFTER the commit landed:

```
rec.committed_head_sha is not None  AND  HEAD == rec.committed_head_sha
                                     AND  <current branch> == rec.branch
```

The branch clause closes finding 2's second half ("accepts any same-parent foreign
commit confined to owned paths, AND records `branch` without checking it"): the SHA
answers commit-content identity, the branch clause answers ref identity. It is not
redundant with the broker's own branch check — `credsep.py:210` compares the current
branch to `request.branch`, but `request.branch` is itself derived from the current
branch (tautological), so it cannot catch a wrong-branch resume; comparing against
the RECORDED `rec.branch` can. (In a single persistent worktree the branch is
normally invariant across the crash, so this is defense-in-depth; it fails closed if
that assumption is ever violated — e.g. an operator checked out a different branch
before re-running.)

`committed_head_sha` is written by a best-effort `on_committed(head_sha)` callback
fired INSIDE `publish_from_worktree` immediately after the commit, reusing the
`head_sha` the publisher already captures at `publishing.py:188` (its comment:
"Capture head_sha immediately after commit"). A crash mid-`publish_fn` never returns
control to `train_runner`, so this durable write MUST originate inside the publish
process — hence the callback (a named `publishing.py` scope increase, §"CR fold —
round 3"). It is EXACT identity, and hook-robust for the RIGHT reason: it records
the tree the hook actually produced, rather than predicting a tree the hook then
mutates.

**Confinement is REMOVED from the identity role; authorization stays with the
broker.** Once identity is `committed_head_sha`, `_paths_covered_by_owned` has NO
identity role left — and owned-scope AUTHORIZATION is already enforced
authoritatively by the broker on every publish (credsep re-derives
`origin/<base>...head_sha` and rejects any path not `_covered_by_owned`,
`credsep.py:248-253`, including the `--no-renames` rename-escape). So the resume
path DROPS the local confinement check entirely: identity = exact SHA; authorization
= the broker's own re-diff; scope passed to the publish = `rec.owned_paths` (codex
3, unchanged). The round-2.5 reuse of `_paths_covered_by_owned` /
`enumerate_changed_paths` was correct CRAFT for the role it then had; round-3
removed that role, so the check goes with it — keeping praised code for a dead role
would be the defect, not the fix. (`enumerate_changed_paths` is retained ONLY where
it still has a live role: `_fab_delta_readmit`'s own re-admission, untouched.)

**The residual commit→append gap fails closed (a bounded, stated limitation).** The
commit (`publishing.py:179`) and the durable `committed_head_sha` append are two
non-atomic durable ops; a crash in the synchronous gap between them leaves HEAD at
the committed object with NO `committed_head_sha` record. In that gap identity is
UNPROVABLE — and the plan does NOT fall back to authorization (that is the exact
substitution finding 2 forbids). It FAILS CLOSED: `HEAD^ == pre_commit_head` with no
`committed_head_sha` → block `committed_head_unrecorded_on_resume`, a determinate
diagnosed block an operator resolves. This is strictly narrower than round-2's
window: the SHA record moves the identity boundary to JUST AFTER the commit, so the
entire `broker.execute` span (push + `gh pr create` + terminal evidence — the long,
network-bound part of the crash window) has EXACT identity; only the tiny in-process
commit→append gap lacks it, and it blocks rather than guesses. The lead explicitly
invited this ("carry it as a stated limitation"); we carry it as fail-closed, which
is more conservative than option (b)'s authorization-only.

*Rejected alternatives.* (a) **Keep owned-scope confinement AS identity + state
plainly that identity is unproven** (the lead's option b) — honest, but it
PERMANENTLY substitutes authorization for identity and knowingly ships a resume that
publishes a foreign same-parent in-scope commit, contradicting the plan's own
"never publish a foreign HEAD." Rejected because identity IS attainable (option a);
retreating to the weaker obligation when the code can satisfy the stronger one is
the `#375` sin. (b) **Exact `expected_tree_sha` + a "no mutating hooks" precondition**
— couples correctness to unverifiable downstream repo config (round-2's refutation).
(c) **`publish_fn` RETURNS the SHA and `train_runner` records it** — the return only
arrives AFTER the whole publish, so a crash mid-publish never records it; the write
must be inside the commit's process (the callback).

## Design

### 1. Durable markers — a PRE-commit `committing` record + a POST-commit `committed_head_sha` append

The `committing` status carries TWO durable appends around the commit (append-only,
last-record-wins fold — `read_ledger` gives resume the later one):

**Record A — PRE-commit (`durable=True`), written by `train_runner` immediately
before `publish_fn(...)` on the EXECUTE path** (around `train_runner.py:2698`). At
that point `owned_paths` and `_node_fab_run_id` are already computed (both are
inputs to the very `publish_fn` call that follows):

- `pre_commit_head` = `git rev-parse HEAD` — the PARENT the commit will be built on.
  Answers LANDED-DETECTION only (§2): `HEAD == pre_commit_head` ⟹ the commit did not
  land. It is NOT an identity signal (round-3 finding 2 — parentage/confinement
  proved authorization, not identity).
- `owned_paths` = the node's actual owned scope passed to `publish_fn` (run_loop
  snapshot dirty ∪ injected-upstream union). Carries RECOVERY SCOPE only (codex 3 —
  the resume publish is scoped to it); no longer an identity signal.
- `fab_run_id` = `_node_fab_run_id` (`None` on non-FAB / flag-off) — FAB scope
  carrier (B1). Omit-when-`None`, byte-neutral.

**Record B — POST-commit (`durable=True`), written by a best-effort `on_committed`
callback fired INSIDE `publish_from_worktree` right after the commit** (reusing the
`head_sha` captured at `publishing.py:188`). The coordinator injects a closure that
appends a second `committing` record carrying ALL of Record A's fields PLUS
`committed_head_sha = head_sha` (the fold is last-record-wins per node, so Record B
must re-carry the resume fields, not rely on field-merge). This is the EXACT
identity signal (§"Commit identity via post-commit SHA"). The callback is
**best-effort**: a raised or failed durable append MUST NOT fail the publish
(swallow + log + proceed) — a missing Record B only widens the fail-closed
commit→append gap on resume, which is safe. Default `on_committed=None` → no-op, and
every non-resume publish (and the declared-prebuilt path) is behaviour/byte-neutral.

A failure to capture `pre_commit_head` (git error) fails closed BEFORE `publish_fn`
— the node is not left with Record A half-written.

**Why this records identity POST-commit, and how non-atomicity is handled.** The
lead's caution — "a marker non-atomic with respect to the commit just relocates the
window" — is met by making git the source of truth for "did the commit land"
(`pre_commit_head`) and recording the ACTUAL committed object for "is this our
commit" (`committed_head_sha`, written after the fact — the only thing that can name
a SHA the commit only just created). Resume reconciles the folded `committing`
record against `git rev-parse HEAD`:

- Record B present (`committed_head_sha` set) AND `HEAD == committed_head_sha` →
  EXACT identity → route to the prebuilt publish path.
- Record B present AND `HEAD != committed_head_sha` → the head moved off the recorded
  commit (foreign/advanced) → **fail closed**.
- Record B absent, `HEAD == pre_commit_head` → the commit never landed → equal-HEAD
  arm: PRESERVE-then-regenerate (§1b, round-3 finding 1).
- Record B absent, `HEAD^ == pre_commit_head` → committed in the tiny commit→append
  gap, identity UNRECORDED → **fail closed** `committed_head_unrecorded_on_resume`
  (never substitute authorization for identity — round-3 finding 2).
- anything else (`HEAD^ != pre_commit_head`, foreign parent) → **fail closed**.

The durable facts need not be simultaneous because resume COMPARES them; atomicity
is never assumed. A torn/absent Record A ⟹ the commit definitely had not started
(the tolerant reader `train_ledger.py:311-345` drops a torn trailing line and resume
sees the prior `running`, re-running safely). `git`'s own ref update is atomic
(rename), so HEAD is never observed half-moved.

**Why `durable=True` (fsync) on both.** Without fsync, a crash could lose a record
while keeping the commit — reproducing the undetectable state #376 exists to close.
fsync on Record A guarantees "if the commit started, Record A is on disk"; fsync on
Record B guarantees "if the SHA was recorded, it survives the crash." Reuses the
existing `durable=True` precedent (`_fab_delta_readmit`).

### 1b. Recovery-aware preflight (the resume entry gate — CR round-2 finding 1)

The marker (§1) is written while the workspace is still dirty — §1 runs
immediately before `publish_fn`, and the commit happens INSIDE `publish_fn`
(`publishing.py:179`). So after a crash the resumed workspace is dirty: fully, for
a crash BEFORE the commit; or with any `run_loop` residue outside `owned_paths`,
for a crash AFTER it. Production `run_train` runs Step-2 preflight
(`train_runner.py:2288-2295`), which calls `_check_repo_clean` — a hard failure on
ANY `git status --short` output (`:181-182`) — and returns `preflight_failed`
(`:2294`) BEFORE it reads the ledger (`:2299`). Preflight failure is a STRUCTURAL
whole-train abort (module docstring `:17-19`): zero PRs, all repos. So without
this change the `committing` marker is never read, Step 4 never runs, and one
crashed marked node blocks the ENTIRE train's resume — the resume mechanism is
dead code on the real path (precisely the `#368` AC-12/13 unreachable-path defect
this plan exists to not repeat).

**The change (a narrow, fail-closed exemption):**

1. **Read the ledger at "Step 1.5", before Step-2 preflight.** `run_train` reads
   the ledger at `:2299`, after preflight; move a read ahead of the preflight call
   (or read once at Step 1.5 and reuse it at `:2299`) so the marker is available
   to the entry gate.
2. **Thread `ledger_state` into `_default_preflight`.** Its signature becomes
   `_default_preflight(nodes, resolve_workspace, ledger_state)`; the injectable
   `_preflight_fn` seam gains the same third parameter.
3. **Exempt ONLY `_check_repo_clean`, ONLY for a node whose folded ledger status
   is `committing`.** Skip the uncommitted-changes check for that node (its
   dirtiness is the legitimate crash residue Step 4 reconciles). EVERY other check
   still runs for it (auth, remote-reachable, base-exists), and every OTHER node —
   including a dirty node with NO `committing` marker — still fails closed exactly
   as today.

**New entry invariant (stated precisely):** *zero PRs are opened unless a node
carries a durable `committing` marker authorizing resume, and that node's publish
is still gated by Step-4 fail-closed reconciliation (§2).* The exemption is not
"skip the clean check when dirty" — it is "a durable marker is the ONLY key that
opens the gate for a dirty tree, and it only DEFERS the decision to Step 4, which
can still block." An unmarked dirty workspace remains a hard preflight failure.

**Why this is in scope, not a separate plan (lead-ratified ONE plan).** This IS a
scope increase over the original marker-plus-Step-4-branch plan, and it is
acknowledged as one — but the lead ratified keeping it in THIS plan, and the
reasoning is the split test: *would either half be independently useful?* Here
neither is. The marker (§1) is inert dead code if the entry gate rejects the
node before the marker is read; the preflight exemption is meaningless without the
marker it keys on. They interlock at a SINGLE entry point and can only land
together — a split would produce two PRs that must merge as one, which is one PR
with extra bookkeeping and two more chances for a stale-branch incident. (Contrast
`#288`, which split cleanly because P2 — the readmit consumer — had standalone
value and the boundary was a real git-merge interlock.) The deeper reason it is
in-scope rather than *adjacent*: it is the SAME defect class this plan exists to
close. `#376` exists because `#368`'s AC-12/13 proved a fix against a path
production cannot enter, and `#376`'s own AC-376-2 was about to repeat exactly that
— not by carelessness, but through an interaction two layers apart, where the
resume mechanism's own precondition (a persistent workspace, so `HEAD` survives the
crash) is PRECISELY what makes the tree dirty, which is PRECISELY what the entry
gate rejects. A resume seam whose entry gate refuses to admit the state the seam
exists to recover is not a resume seam. Closing that is the plan's obligation, not
an adjacent nicety.

**Disposition of the crash-BEFORE-commit dirty tree (the equal-HEAD arm) — PRESERVE,
never destroy (CR round-3 finding 1).** When Step 4 finds `HEAD ==
rec.pre_commit_head` (the commit never landed), the node's own work must be
regenerated from the clean recorded parent — but the dirty tree may ALSO contain
UNRELATED user work (the `committing` marker proves a crash occurred, NOT that every
tracked/untracked change came from this run). The round-2.5 arm's repository-wide
`git reset --hard` + `git clean -fd` would DESTROY that unrelated work, and its
"strictly non-regressive" justification was **FALSE**: the existing preflight BLOCKS
a dirty tree while PRESERVING its bytes on disk (recoverable); reset+clean blocks
work AND deletes bytes (unrecoverable). Parity with the existing REFUSAL is not
parity with the existing OUTCOME. A stranded node is recoverable; deleted
uncommitted work is not.

**The invariant: resume NEVER destroys uncommitted bytes.** The equal-HEAD arm must
durably PRESERVE the FULL dirty tree (tracked *and* untracked) to a recoverable,
named location BEFORE any tree-mutating op, and must **BLOCK if that preservation
cannot be PROVEN** — never run a destructive op on an unverified preservation (that
failure branch is exactly where bytes die). Two mechanisms satisfy "preserve";
**the choice is a lead decision** because it changes AC-376-11's positive control:

- **(P) Quarantine-in-place** (recommended — smaller, one worktree/branch):
  **requirement** — durably capture BOTH tracked AND untracked dirty state to a
  recoverable, GC-safe named ref `refs/fab-quarantine/<node>/<run_id>` and VERIFY it
  resolves to a non-empty object, record it in the block/log, THEN `git reset --hard
  rec.pre_commit_head` + `git clean -fd` and re-run `run_loop`. (Note: bare `git
  stash create` does NOT capture untracked files — the implementation must use a
  mechanism that captures both, e.g. `git stash push --include-untracked` into a
  retained ref, or an explicit index+`write-tree` of tracked-plus-untracked. AC-376-11
  tests an UNTRACKED file's survival precisely so a tracked-only capture cannot pass.)
  Preservation guarantee: **recoverable from a verified named ref** — NOT
  byte-identical in the working tree (the tree is reset). If the quarantine ref-write
  fails or is empty → BLOCK, no reset.
- **(W) Fresh worktree** (satisfies the lead's literal "byte-identical afterwards"):
  regenerate in a NEW `git worktree add` at `rec.pre_commit_head`, leaving the
  original crashed worktree UNTOUCHED — an unrelated file is byte-identical
  afterwards because nothing wrote to it. Cost: worktree lifecycle + the
  two-worktrees-cannot-share-one-branch constraint (the crashed worktree still holds
  the branch), so the regeneration/publish worktree needs its own branch handling.

The plan carries **(P)** as primary with AC-376-11 asserting *recoverable from a
verified ref*, and flags to the lead that their stated control ("byte-identical
afterwards") is satisfiable ONLY by **(W)** — an honest match of criterion to
mechanism, not a silent substitution. Under either, reconciliation is ALWAYS on
`HEAD` (a git-atomic ref), never on working-tree content: the dirty tree is evidence
a crash happened, not a source of truth to publish. (A crash-AFTER-commit node is
identified by its COMMIT — `committed_head_sha`, §2 / `## Commit identity via
post-commit SHA` — where residual dirt is simply ignored by the prebuilt publish,
which reads `git rev-parse HEAD` and never re-stages, so no preservation issue
arises there — only the equal-HEAD regenerate arm mutates the tree.)

### 2. Resume detection + routing (train_runner Step 4)

In Step 4 (`train_runner.py:2440+`), for a node NOT already recovered into
`completed_nodes` (a `committing` node is not `pr_open`/`merged`, so Step 3 at
`:2311` does not recover it), add a branch keyed on the folded status, placed
after `workspace = resolve_workspace(node)` (`:2505`) and BEFORE the `running`
append (`:2509`):

```
rec = ledger_state.get(nid)                 # last-wins fold gives Record B if it exists
if rec is not None and rec.status == "committing":
    head = <git rev-parse HEAD in workspace>
    if rec.committed_head_sha is not None and head == rec.committed_head_sha \
       and <current branch> == rec.branch:
        # EXACT identity (round-3 finding 2): the head IS the object the publisher
        # committed (SHA recorded POST-commit, hook-robust) AND on the recorded
        # branch (the finding's "records `branch` without checking it" clause — the
        # broker's own branch check `credsep.py:210` is tautological, current==request
        # both derived from the current branch, so it cannot catch a wrong-branch
        # resume; this compares against the RECORDED branch). → resume-publish it.
        <upstream-staleness re-check — see §3; block if stale>
        <git fetch origin <base> — see §4; block on fetch failure>
        <route through the prebuilt publish path (prebuilt=True), §4,
         using rec.owned_paths (codex 3), NOT prebuilt_owned_paths_fn;
         the broker re-authorizes owned-scope on publish — credsep :248-253>
        <run the FULL success epilogue below (B1 + B2)>
    elif rec.committed_head_sha is not None:
        # Record B present but head != committed_head_sha (or the branch is not the
        # recorded one) → the head/branch is not the object+ref we committed
        # (foreign/advanced/wrong-branch). Cannot claim it as ours. → fail closed.
        <blocked: "committed_head_moved_on_resume"; fail closed>
    elif head == rec.pre_commit_head:
        # commit never landed → PRESERVE-then-regenerate (§1b, round-3 finding 1).
        <preserve the FULL dirty tree to a verified quarantine ref (or fresh
         worktree); BLOCK if preservation cannot be proven — never destroy>
        <git reset --hard rec.pre_commit_head && git clean -fd>   # only AFTER proven preserve
        pass                      # fall through to the normal execute re-run
    elif <head^ == rec.pre_commit_head>:
        # committed in the tiny commit→append gap; SHA never recorded → identity is
        # UNPROVABLE. Do NOT fall back to authorization (round-3 finding 2). Fail closed.
        <blocked: "committed_head_unrecorded_on_resume"; bounded stated limitation>
    else:
        # head^ != pre_commit_head — foreign commit on a different parent.
        <blocked: "committed_head_ambiguous_on_resume"; fail closed>
```

**Control flow (explicit, to foreclose a double-publish reading).** ONLY the
equal-HEAD (commit-never-landed) arm falls through to the normal execute re-run
(the `pass` above); the exact-identity publish arm (after its publish + epilogue)
and EVERY fail-closed `blocked` arm terminate the node (`continue` to the next topo
node / return the block), NEVER falling through to the normal execute path at
`:2509`. Without that, a resumed node would run `run_loop` and publish a SECOND
time.

**The resume success epilogue is the FULL normal epilogue
(`train_runner.py:2739-2792`), not just the `pr_open` append (B1 + B2).** After a
successful resumed publish, run exactly what the normal execute success path runs,
with one intentional deviation:

1. `_fab_run_id_bind, _fab_block_reason = _resolve_admission_fab_run_id(workspace,
   head_sha, rec.fab_run_id)` — sourcing `_node_fab_run_id` from the MARKER
   (`rec.fab_run_id`, B1), not a live run_loop closeout (there is none on resume).
   The helper re-verifies the plumbed run_id's provenance against the committed
   `head_sha`; a torn/missing/mismatched FAB scope returns a block reason.
2. `if _fab_block_reason is not None:` → append `blocked` and return — a resumed
   FAB node NEVER publishes with a silent `None` fab_run_id (B1 fail-open closed).
3. `completed_nodes[nid] = {branch, head_sha, admitted_head_sha: head_sha, pr_url}`
   and `if _fab_run_id_bind is not None: completed_nodes[nid]["fab_run_id"] = ...`
   — populate `completed_nodes` so downstream nodes and the P4 merge loop /
   promotion gate find this node (B2, multi-node correctness).
4. `append_record(pr_open, ..., fab_run_id=_fab_run_id_bind)` — bind fab_run_id in
   the durable record too (B1), exactly as `:2790`.

**The one intentional deviation from the normal epilogue:** the resumed node is
**not** added to `rebuilt_this_run`. It publishes the same frozen head it
committed pre-crash, so downstream pins built against that head remain valid
(mirrors the Step-3 recovery at `:2417-2432`, which populates `completed_nodes`
without marking a rebuild). This is the ONLY line of `:2739-2792` the resume path
omits; every other line runs.

### 3. Upstream-staleness re-check (a consciously-preserved gate)

A **declared** prebuilt node consumed no upstream, so the prebuilt path does no
stale-upstream check. A resumed **execute** node is different: it injected
upstream refs (`train_runner.py:2573-2603`) into the tree BEFORE its commit, so
those pins are baked into the frozen commit. Routing it through the prebuilt
path would silently inherit "no consumed upstream" and BYPASS the
`upstream_changed_downstream_pr_open` gate (`:2457-2503`).

**Decision: re-check and block (fail closed), not ship-frozen.** Before
publishing the frozen commit, the resumed node re-checks its upstream currency
against the SAME `rebuilt_this_run` and `out_of_band_upstreams` sets the pr_open
gate uses (`:2457-2469`; both are populated by the time topo-order reaches this
node — `out_of_band_upstreams` in Step 3, `rebuilt_this_run` as earlier nodes
process). If any consumed (non-`order-only`) upstream was rebuilt this run or
received an out-of-band push, the frozen commit is stale → block with
`upstream_changed_downstream_committed` (parallel to the pr_open reason),
telling the operator to discard the stale commit and re-run.

*Rejected alternative — ship-frozen-and-defer* (consistent with the
"automatic downstream rebuild deferred" note at `:2449-2450`): silently shipping
a commit built against a now-stale upstream is exactly the class the pr_open gate
exists to prevent. A crash is not a license to weaken a fail-closed invariant.
Named here so it does not fall through unexamined.

### 4. Publish routing reuses the existing prebuilt path (no new publish logic)

The resume branch builds the same `publish_kwargs` the declared-prebuilt path
builds (`train_runner.py:2538-2556`): `prebuilt=True`, `base=_DEFAULT_BASE`,
`broker_client` + `admission=admission_fn(coordinator_runtime, node, workspace,
owned_paths)`. **`owned_paths = rec.owned_paths` — the node's PERSISTED owned
scope from the marker (codex 3), NOT `prebuilt_owned_paths_fn(workspace,
_DEFAULT_BASE)`.** The declared-prebuilt default (whole committed diff vs base)
would broaden a resumed execute node's authorization from what it owned to
everything the branch touched since `origin/<base>`; the persisted set is exactly
the union (`run_loop` snapshot dirty ∪ injected-upstream) the node passed at first
publish, so the broker's owned-scope re-diff (credsep re-diffs
`origin/<base>...head_sha` and requires every changed path covered by
`owned_paths`, `credsep.py:250-257`) reconciles IDENTICALLY to the crashed
first attempt. It then calls `publish_fn(workspace, owned_paths, **publish_kwargs)`.
The broker's replay-before-admit makes the call idempotent for a terminally-observed
head; an un-pushed head is admitted and pushed (the `PROVIDER_CALL_IN_FLIGHT`
sub-window is the corrected exception — see `## Broker in-flight sub-window`).
**No change to `publishing.py`.**

**Fetch `origin/<base>` before reconstructing (correctness, not cosmetics).** A
crash-resume can run long after the crash, when `origin/<base>` has advanced. The
`#368` `merge-base(head, origin/<base>)` `base_sha` AND the broker's own
owned-scope re-diff (`origin/<base>...head_sha`, `credsep.py:250-257`) both read
the LOCAL `origin/<base>` ref; a stale local ref changes the `base_sha` and the
set of paths the broker requires `owned_paths` to cover. The resume branch MUST
`git fetch origin <base>` before publishing so both are computed against the
current base (the repo's "verify against origin, not a stale local ref"
discipline). A failed fetch fails closed (block), never silently uses the stale
ref. (Owned scope itself is now the persisted `rec.owned_paths`, so the fetch no
longer feeds an `owned_paths` RE-derivation — but it still gates the base_sha and
the broker's coverage re-diff, so it remains required.)

## The #368 interlock (verified against source, not inferred from #368's plan)

`_default_build_admission` binds `base_sha = git rev-parse HEAD`
(`train_runner.py:120`) and `lease_epoch=1` (`:138`) **today**. Two consequences:

1. **Today the resumed publish DEDUPS regardless of the admission — and the
   admission's `base_sha` actually DIFFERS across the crash (grok round-2, folded).**
   `_default_build_admission` runs `git rev-parse HEAD` (`:119-120`) at
   `admission_fn(...)` (`:2695`), which is BEFORE `publish_fn`'s commit (`:2698` →
   `publishing.py:179`) — so the FIRST execute admission's `base_sha` is the PARENT
   (`pre_commit_head`), whereas a resume rebuild (post-commit, HEAD = committed
   head) binds `base_sha` to the committed head: the two DIFFER on today's code.
   This does not break resume, because the publish dedup key is
   `publish_committed_branch_idempotency_key(repo, branch, head_sha)` — keyed on
   `(repo, branch, head_sha)`, NOT on `base_sha` or the epoch — so a resumed
   publish dedups a terminally-observed head or admits+pushes at `lease_epoch=1`
   irrespective of the reconstructed admission's `base_sha`/epoch. Core resume
   independence rests on the head_sha-keyed idempotency, NOT on any `base_sha`- or
   epoch-stability (there is none today) — which is exactly why the reachability
   fix is genuinely #368-independent.
2. **Under #368 (on the #288 line) the epoch becomes an allocated value**, the
   `base_sha` binding moves to §5b's `merge-base(head_sha, origin/<base>)`, and
   the `PreAdmissionEnvelope` lets the admission be REBUILT at a freshly-allocated
   epoch on retry, with dedup keyed on `attempt_id`. Only THEN does a resumed
   publish exercise a cross-epoch admission rebuild.

**The core resume fix (AC-376-1/2/3) does NOT depend on #368, and fixes a live
bug on today's code.** The publish dedup key is
`publish_committed_branch_idempotency_key(repo, branch, head_sha)` — keyed on
`(repo, branch, head_sha)`, NOT on the epoch-dependent `fence_token`. So the
resumed publish reaches the broker and either dedups a terminally-observed head or
admits+pushes at `lease_epoch=1` — it PUBLISHES, or (in the narrow
`PROVIDER_CALL_IN_FLIGHT` sub-window, codex 1) BLOCKS with a determinate broker
ambiguity — where today it is permanently stuck at `nothing_staged` with the
commit stranded and no broker record at all. Either resumed outcome is strictly
better than the stuck state and neither loses the commit. AC-376-1 therefore
genuinely fails-then-passes on the pre-#368 code; it is not vacuous today. (The
in-flight sub-window is a corrected scope boundary, not a fail-open — see
`## Broker in-flight sub-window`.)

**Only `AC-376-4` — the cross-epoch identity proof — is #368-gated.** Only #368
makes the epoch move (off `lease_epoch=1`) and changes the `base_sha` binding to
`merge-base`; only then is there a cross-epoch admission rebuild for a resumed
publish to exercise. On the pre-#368 code the epoch never moves, so that aspect
is trivial-until-#368 — written against the OBLIGATION and flagged unsatisfiable
until #368 merges (per the lead's #375 caution: derive the criterion from the
obligation; if it cannot currently be satisfied, say so — which is landing the
core now with AC-4 flagged, not gating the whole plan).

**Two senses of "upstream," reconciled.** The lead's "#376 is upstream" is
CAUSAL: the resume door must open before any identity drift is observable, so the
reachability fix can and should land FIRST, independent of #368. #368 is the
BUILD dependency of `AC-376-4` ONLY: the cross-epoch proof needs #368's allocated
epoch and `merge-base` `base_sha`. These are consistent — the reachability fix is
causally upstream and ships now; `AC-376-4` is the later discharge of #368 AC-13
at the production seam. Landing #376 AFTER #368 buys a single clean story
(AC-1..4 all green at once) and is a **sequencing preference the lead may
choose**, not a hard dependency of the core fix.

**Debt discharged (does-anything-still-promise-it discipline).** When #376
lands, `Consiliency/agent-harness#368` AC-13 becomes promotable from unit-level
to the production seam: #376's resume path is the first production caller that
reconstructs an admission for an already-committed head across a process
boundary — precisely the scenario #368 AC-13 proves only in unit form today
(and records as `#376`-gated at `plans/detailed-fab-288-shared-epoch-allocator-20260728.md:1007-1024`).
#376's `AC-376-4` IS that production-seam proof. Whoever executes #376 owes an
update to #368's AC-13 reachability note pointing at `AC-376-4` as the discharge.

## Changes

### `phase-loop-runtime/src/phase_loop_runtime/train_ledger.py` (modify)
- `VALID_STATUSES` (`:56-58`) — **modify** — add `"committing"` to the frozen
  vocabulary. This is a contract change; see `## Frozen-vocabulary confirmation`
  and `## Status-reader sweep`.
- `LedgerRecord` (`:147-183`) — **modify** — add THREE new optional fields, all
  `committing`-only and omit-from-`to_dict`-when-absent (mirror the `fab_run_id`
  omit-when-`None` pattern at `:175-183`) so every non-`committing` record stays
  byte-for-byte unchanged: `pre_commit_head: Optional[str] = None` (landed-detection
  only), `owned_paths: Optional[tuple[str, ...]] = None` (recovery scope only, codex
  3 — no longer an identity signal after round-3), and `committed_head_sha:
  Optional[str] = None` (EXACT commit identity, round-3 finding 2, set on the
  post-commit Record B). Reuse the EXISTING `fab_run_id` field to carry FAB scope
  (B1) — no new field. Thread all three new fields through the `ts`-reissue copy in
  `append_record` (`:272-283`) and `_dict_to_record` (`:356-367`). `owned_paths`
  serializes as a JSON list; on read, restore as a tuple. (Round-1 `expected_tree_sha`
  dropped in round-2; identity is now the POST-commit `committed_head_sha` — `##
  Commit identity via post-commit SHA`.)
  **BYTE-NEUTRALITY TRAP (verified against source):** `to_dict` (`:175-183`)
  currently hard-codes the omit-when-`None` filter to `fab_run_id` ONLY
  (`if not (k == "fab_run_id" and v is None)`). All THREE new optional fields MUST
  be ADDED to that filter (generalize it to an omit-set
  `{"fab_run_id", "pre_commit_head", "owned_paths", "committed_head_sha"}`), or every
  non-`committing` record gains new `null` keys and byte-neutrality breaks. A
  round-trip test (write both `committing` records → `read_ledger` → all fields
  survive incl. `committed_head_sha`; write a `running`/`pr_open` record → serialized
  JSON byte-identical to pre-#376) is the falsifier for both the propagation and the
  neutrality.

### `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` (modify)
- **Recovery-aware preflight entry gate (§1b — CR round-2 finding 1) — modify.**
  Read the ledger once at "Step 1.5" BEFORE the Step-2 preflight call
  (`:2288-2295`) and pass `ledger_state` into preflight; change
  `_default_preflight` (`:303`) to `_default_preflight(nodes, resolve_workspace,
  ledger_state)` (and the injectable `_preflight_fn` seam, `:2136`/`:2240`, to the
  same arity). Inside, for a node whose folded status is `committing`, SKIP
  `_check_repo_clean` (`:332`) ONLY; every other check, and every unmarked node,
  is unchanged. This is the change that makes the whole resume mechanism reachable
  on the real `run_train` path — WITHOUT it preflight aborts the train
  (`preflight_failed`, `:2294`) before the ledger is read (`:2299`). **(Scope
  increase, lead-RATIFIED as in-scope for this ONE plan — same unreachable-path
  defect class, marker+gate interlock at one entry point; see design §1b, "Why
  this is in scope, not a separate plan".)**
- Execute-path publish block (around `:2684-2702`) — **modify** — (i) immediately
  before `publish_fn(...)`, capture `pre_commit_head = git rev-parse HEAD` and append
  Record A: `LedgerRecord(node_id=nid, status="committing", branch=<branch>,
  pre_commit_head=..., owned_paths=tuple(owned_paths), fab_run_id=_node_fab_run_id)`
  with `durable=True`. (ii) Build the Record-B closure and pass it as the new
  `on_committed=` kwarg to `publish_fn`: `on_committed = lambda sha:
  _append_committing_B(nid, branch, pre_commit_head, owned_paths, _node_fab_run_id,
  committed_head_sha=sha)` — a durable append of a SECOND `committing` record adding
  `committed_head_sha` (the identity signal, round-3 finding 2). All marker inputs
  are the SAME values passed to the `publish_fn` call. Execute path only; the
  declared-prebuilt path (`:2518-2561`) does not commit and passes no `on_committed`.
- Step 4 resume loop (around `:2505-2509`) — **add** — the `committing`
  reconciliation branch (§2), keyed on `rec.committed_head_sha`: (a) present AND
  `HEAD == rec.committed_head_sha` AND `current branch == rec.branch` (finding-2
  branch clause) → EXACT identity → §3 upstream re-check + `git
  fetch origin <base>` + prebuilt publish path (§4) using `rec.owned_paths` (codex 3;
  the broker re-authorizes owned-scope on publish) + FULL success epilogue
  (`_resolve_admission_fab_run_id` block-or-bind, `completed_nodes`, `pr_open` with
  `fab_run_id` — B1 + B2); (b) present AND `HEAD != committed_head_sha` → block
  `committed_head_moved_on_resume`; (c) absent AND `HEAD == pre_commit_head` →
  PRESERVE the full dirty tree to a verified quarantine ref (BLOCK if unproven),
  THEN `git reset --hard` + `git clean -fd`, fall through to the normal re-run (§1b,
  round-3 finding 1); (d) absent AND `HEAD^ == pre_commit_head` → block
  `committed_head_unrecorded_on_resume` (the bounded commit→append gap, round-3
  finding 2 — never authorization-as-identity); (e) else → block
  `committed_head_ambiguous_on_resume`.
- Reuse (no change) — `_default_build_admission` (`:103`), `publish_from_worktree`'s
  `prebuilt=True` path, `_resolve_admission_fab_run_id` (`:618`), and the normal
  success epilogue's shape (`:2739-2792`). **Owned-scope AUTHORIZATION on the resume
  publish is the broker's own re-diff (`credsep.py:248-253`, incl. `--no-renames`),
  not a local check** — round-3 dropped the local `_paths_covered_by_owned` /
  `enumerate_changed_paths` confinement check from the resume path (its identity role
  is gone; authorization is the broker's job). Those helpers remain untouched at
  their live call site (`_fab_delta_readmit`, `:982-986`).
- NOT reused on the resume path — `_prebuilt_owned_paths` / `prebuilt_owned_paths_fn`
  (`:250`): the declared-prebuilt whole-diff-vs-base scope is REPLACED by the
  persisted `rec.owned_paths` (codex 3).

### `phase-loop-runtime/src/phase_loop_runtime/publishing.py` (modify — NEW footprint, named scope increase)

- `publish_from_worktree` (`:81-95`) — **modify** — add a keyword-only
  `on_committed: Callable[[str], None] | None = None`. Right after the existing
  post-commit `head_sha` capture (`:188-190`) and BEFORE `broker_client.execute`
  (`:196`), if `on_committed is not None` call `on_committed(head_sha)` inside a
  guard that SWALLOWS any exception (best-effort: `try/except Exception: log;
  proceed`). A failed durable append MUST NOT fail the publish — it only widens the
  fail-closed commit→append gap on resume, which is safe. This is the ONLY
  `publishing.py` change; it is the seam that lets a durable identity record be
  written from INSIDE the commit's process (a crash mid-`publish_fn` never returns to
  `train_runner`, so option (a) is impossible without it — `## Commit identity via
  post-commit SHA`). **Behaviour/byte-neutral when `on_committed=None`** (the default,
  and what the declared-prebuilt path and every existing caller pass) — assert this
  in a test. **(Scope increase — the plan previously had "no `publishing.py`
  footprint"; named to the lead, `## CR fold — round 3`.)**

### `phase-loop-runtime/tests/…/test_train_runner_crash_resume.py` (create)
- The `run_train`-level crash-resume tests (see `## Verification` / the ACs).

## Documentation impact

- `Consiliency/agent-harness#368` AC-13 reachability note
  (`plans/detailed-fab-288-shared-epoch-allocator-20260728.md:1007-1024`) —
  **modify (at #376 execution, gated on #368 merged)** — point it at `AC-376-4`
  as the production-seam discharge. Recorded here as the promised debt; not
  edited in this plan.
- `train_ledger.py` module docstring record-shape list (`:19-37`, `:56-58`) —
  **modify** — document the `committing` status and its `pre_commit_head`,
  `owned_paths`, `committed_head_sha` fields (and its reuse of `fab_run_id`), noting
  the two-append shape (pre-commit Record A + post-commit Record B).
- No `README`/`CHANGELOG`/`AGENTS.md` footprint: this is internal coordinator
  crash-recovery, no public-surface change.

## Frozen-vocabulary confirmation

`train_ledger.py`'s status vocabulary is a frozen contract
(`VALID_STATUSES`, `:56-58`; enforced in `LedgerRecord.__post_init__`, `:168-173`).
This plan adds exactly one new value, `"committing"`, and THREE new optional
fields — `pre_commit_head`, `owned_paths`, `committed_head_sha` — all populated ONLY
on a `committing` record and omitted from `to_dict` when absent; it also sets the
EXISTING `fab_run_id` field on the `committing` record (no schema change for it).
No other vocabulary is introduced; no existing value or field
changes meaning, and because `committing` is a new status every pre-existing
record serializes byte-for-byte as before. The `CoordinatorEvent` schema
(`:73-117`) is NOT touched.

## Status-reader sweep (contract-change diligence — cross-cutting principle #5)

Adding `"committing"` to `VALID_STATUSES` is a signature-class change; every
reader of ledger `.status` was swept. All readers test SPECIFIC values (none
enumerates the set exhaustively in a way a new value could silently mis-route):

| Reader | Line | Behavior on `committing` | Needs change? |
|---|---|---|---|
| `LedgerRecord.__post_init__` membership | `train_ledger.py:169` | rejects until added to `VALID_STATUSES` | YES — add value |
| `normalize_legacy_ledger_record` | `train_ledger.py:389` | `committing != "blocked"` → `blocker_reason=None` | no (correct) |
| Step 3 recovery `status in ("pr_open","merged")` | `train_runner.py:2311` | not recovered → falls to Step 4 | no (correct — Step 4 handles it) |
| Step 3 `status == "pr_open"` | `train_runner.py:2313` | not entered | no |
| Step 4 merged-skip `status == "merged"` | `train_runner.py:2454` | not entered → new `committing` branch | YES — new branch (§2) |
| Recovery-aware preflight (`_default_preflight`, §1b) | `train_runner.py:303/332` (NEW `ledger_state` param) | reads `ledger_state[nid].status == "committing"` to exempt `_check_repo_clean` ONLY | YES — NEW reader (§1b, CR round-2 finding 1) |
| P4 merged/approved readers | `train_runner.py:2833,2900,…` | a `committing` node never reaches P4 | no |

## Scope & explicitly-deferred variants

- **Graceful post-commit block** (broker returns not-accepted after the commit,
  `:2721`; or a normal `Exception` after commit, `:2707`): leaves the same
  committed-unpublished tree but with last record = `blocked`. Handling it would
  require a full-log scan (the last-wins fold hides an earlier `committing` behind
  the `blocked`) AND would change `blocked`'s meaning from terminal to retryable
  (blast radius into every `blocked` consumer). It is the SAME committed-tree
  state but a materially different detection + semantics problem. **Filed as its
  own issue `Consiliency/agent-harness#380`, not built here** — the ratified target
  is the crash case, where the `committing` marker survives the fold directly and
  detection needs no scan.
- **Declared prebuilt nodes** are already crash-safe (their resume re-runs the
  idempotent prebuilt path); no marker needed.
- **The broker `PROVIDER_CALL_IN_FLIGHT` sub-window** (codex 1) is a pre-existing
  broker recovery gap #376 makes reachable, NOT built here; see
  `## Broker in-flight sub-window`.
- **The resume seam itself** (this plan) is #368-gated for its cross-epoch proof;
  see `## The #368 interlock`.

## Broker in-flight sub-window (CR — codex 1; scope correction, not a fail-open)

#376's crash window (`commit → pr_open`) contains `broker.execute`, and the broker
does NOT recover ONE sub-window of it. `execute` writes `PROVIDER_CALL_IN_FLIGHT`
via `record_intent` (`verbs.py:65`) BEFORE the adapter call (`verbs.py:67`), and
the replay guard (`verbs.py:58`) treats an in-flight record as NON-replayable. So a
crash after credsep's `gh pr create` SUCCEEDS (`credsep.py:283`) but before
`record_terminal` (`verbs.py:72`) leaves the evidence in-flight. On resume the
adapter is RE-INVOKED: `git push` is idempotent, but `gh pr create` hits GitHub's
"a pull request already exists" and returns non-zero, so credsep returns
`_ambiguous("pr-unconfirmed")` (`credsep.py:284`) — **before** the existing-PR
recovery read (`gh pr list --head`, `credsep.py:293`) is reached. The record
becomes `OUTCOME_AMBIGUOUS_BLOCKED`.

**Why this is a scope correction, not a fail-open.** The commit is pushed and the
PR exists; nothing is silently lost; the resumed node BLOCKS with a determinate
broker-ambiguity reason (fail-closed), which an operator resolves against the real
PR. It is strictly better than today's permanent `nothing_staged` stuck-state.
What it is NOT is "publishes" — so the plan's earlier "the broker already recovers
any commit-to-terminal-evidence crash" is corrected here and AC-376-1 is scoped to
"publishes OR blocks determinately, never silent loss," with **AC-376-5** asserting
the in-flight sub-window fails closed rather than fabricating a duplicate PR or
silently dropping the commit.

**The broker-side fix is a SEPARATE follow-up.** credsep should, on a non-zero
`gh pr create`, first `gh pr list --head <branch>` and ADOPT an already-created PR
that matches the pushed head/base (idempotent recovery) before returning ambiguous;
and/or `execute` should make an in-flight replay READ the provider state rather than
blind-re-invoke. That is broker/#337/#288-line machinery, pre-existing and
independent of #376's train-runner seam — filed as its own issue (see
`## Dependencies & order`), not absorbed here.

## Dependencies & order

1. **`Consiliency/agent-harness#368` MERGED gates `AC-376-4` ONLY** (the shared
   allocated epoch + §5b `merge-base` `base_sha` + `PreAdmissionEnvelope`
   rebuild). The core reachability fix — the marker, resume detection, prebuilt
   routing, upstream re-check (AC-376-1/2/3) — is INDEPENDENT of #368 and fixes a
   live permanent-stuck-node bug on today's code (the publish idempotency key is
   epoch-independent; see `## The #368 interlock`). Land the core now with AC-4
   flagged unsatisfiable-until-#368; do not hold the reachability fix for #368.
   Landing #376 after #368 for a single clean AC-1..4 story is a sequencing
   preference for the lead, not a hard dependency. This is a declared external
   dependency of AC-4, not a phase.
2. Within this plan: ledger schema change (new status + fields) before the
   train_runner marker write; marker write before the resume-detection branch can
   be tested end-to-end.
3. **Broker in-flight recovery (codex 1) — a SEPARATE follow-up, not a gate on the
   core.** credsep adopting an already-created PR on a non-zero `gh pr create`
   before returning ambiguous (and/or `execute` reading provider state for an
   in-flight replay) closes the `PROVIDER_CALL_IN_FLIGHT` sub-window so the
   resumed node PUBLISHES instead of blocking-ambiguous. It is pre-existing broker
   machinery (`verbs.py`/`credsep.py`), independent of #376's train-runner seam;
   filed as its own issue. #376 lands WITHOUT it — AC-376-5 asserts the sub-window
   fails closed (the correct, safe behaviour) until that follow-up ships. **File
   this issue at #376 execution** (mirrors the #380 disposition for the graceful
   variant); the fold names it so the obligation is not left as a plan footnote.

## Verification

Run from the runtime package root with `PYTHONPATH=src:tests`:

```
PYTHONPATH=src:tests python -m pytest phase-loop-runtime/tests/…/test_train_runner_crash_resume.py -q
PYTHONPATH=src python -c "from phase_loop_runtime.train_ledger import VALID_STATUSES; assert 'committing' in VALID_STATUSES"
```

**automation.suite_command** (runner-executable; the effective machine-checkable
suite for this plan):

```
automation:
  suite_command: "cd phase-loop-runtime && PYTHONPATH=src:tests python -m pytest tests -q -k 'crash_resume or train_ledger or train_runner'"
```

AC-376-1/2/3 and AC-376-5..11 are machine-checkable by this suite today
(the recovery-aware-preflight, exact-SHA-identity, and preserve-not-destroy arms
exercise the DEFAULT `_default_preflight` and the real `on_committed` callback on a
real dirty workspace — round-2/round-3 findings).
AC-376-4 is NOT machine-checkable until #368 merges (operational precondition: the
epoch allocator + `merge-base` `base_sha` must exist); it is recorded as
`#368`-gated and MUST NOT be reported green by the runner before that — a plan
amendment records its satisfaction once #376 is rebased onto merged #368.

**Test faithfulness (the core of #376).** The crash MUST be produced by the real
`run_train` path, and resume MUST re-enter through the real `run_train` path —
never by hand-constructing the post-crash ledger + tree, and never by injecting a
`_preflight_fn` or cleaning the workspace to sidestep the entry gate.

- **Primary — subprocess + SIGKILL.** Drive `run_train` in a real subprocess on
  a real git repo with a `publish_fn`/broker that performs the real commit then
  blocks on a barrier; the parent `SIGKILL`s the child in the window between
  commit and `pr_open`; then re-invoke `run_train` (resume) and assert publish.
  This is the lead's literal instruction and proves no `finally`/atexit masks
  the state.
- **Resume through the DEFAULT preflight on the REAL dirty workspace (round-2
  finding 1 — the reachability proof).** The resume `run_train` invocation MUST use
  the DEFAULT `_default_preflight` (no `_preflight_fn` injected) on the SAME
  workspace the crash left dirty, and MUST NOT `git checkout`/`reset`/`clean` the
  tree before resuming. A resume that injects a preflight or pre-cleans the tree
  re-proves the fix against a path production cannot enter — the exact `#368`
  AC-12/13 sin. `assert` the resume did not return `preflight_failed`. **This is a
  prohibition on the test's SETUP, not merely an assertion about its outcome.** The
  anticipated failure mode is a future maintainer "simplifying" the fixture — an
  injected `_preflight_fn` or a pre-run `git reset` looks like harmless test
  cleanup but silently relocates the whole proof onto the unreachable path this
  plan exists to fix, and the outcome assertion would still pass. Name the
  prohibition in the test as a comment so the setup cannot be "tidied" into
  vacuity.
- **In-process form (deterministic companion).** Inject a `BaseException`
  (`SystemExit`) at the deepest post-commit point — inside `broker.execute`,
  after `publishing.py:179` — bypassing `except Exception` at `:2704`. First
  confirm no outer `finally`/`BaseException` handler around the node loop or the
  CLI entry writes a terminal record on exit.
- **Ledger-faithfulness assertion (proves the state is REACHABLE, not
  constructed).** After the injected crash, assert the ledger byte-matches a real
  crash: the node's last `committing` record has `pre_commit_head` and `owned_paths`
  set (and `fab_run_id` on a FAB node); for an AFTER-commit crash it ALSO has
  `committed_head_sha` set (Record B, produced by the REAL `on_committed` callback —
  NEVER hand-injected, round-3 finding 2); for a BEFORE-commit crash `committed_head_sha`
  is absent; and there is NO `pr_open` and NO `blocked` record for it. An AC that
  resumes from a hand-built state (or a hand-set `committed_head_sha`) would silently
  reproduce the exact defect #376 closes; this assertion is what forbids it, and it
  proves both markers actually persisted the reconstruction fields the resume epilogue
  depends on. **The commit→append gap** is exercised by crashing BETWEEN the commit
  (`publishing.py:179`) and the `on_committed` append: assert the last record is
  `committing` WITHOUT `committed_head_sha`, and that resume BLOCKS
  `committed_head_unrecorded_on_resume` (AC-376-6 gap-neg).

## Acceptance criteria

Each names the falsifier (the mutation that makes it fail) and the injection
anchor. `AC-376-4` is written against the obligation and flagged
unsatisfiable-until-#368-merged. **AC-376-5..9 are the round-1 CR fold** (codex 1 →
AC-376-5; codex 2 → AC-376-6; B1 → AC-376-7; B2 → AC-376-8; codex 3 → AC-376-9),
**AC-376-10 is the round-2 fold** (recovery-aware preflight — finding 1), and
**AC-376-11 is the round-3 fold** (unrelated-work survival — finding 1). **AC-376-6
was rewritten in round 3** (EXACT post-commit-SHA identity, superseding round-2's
owned-scope confinement — finding 2) and **AC-376-2 in round 3** (preserve-not-destroy
— finding 1). All of AC-376-1/2/3/5..11 are machine-checkable by the suite TODAY
(they do not depend on #368). Every AC's falsifier was written to name an
OBSERVABLE the code can actually produce and a mutation that makes it fire — see
`## AC observable-grounding` for the per-AC audit. **Every crash-resume AC below
drives the crash through the REAL `run_train` path and resumes through the DEFAULT
`_default_preflight` on the REAL post-crash workspace — never an injected preflight
and never a hand-cleaned tree** (that is what makes finding 1's reachability real
and not a re-proof against an unreachable path — the `#368` AC-12/13 sin).

- [ ] **AC-376-1 (crash-resume publishes, OR blocks determinately — never silent
  loss).** After a `run_train`-level crash in the commit→`pr_open` window
  (subprocess+SIGKILL primary; in-process `BaseException` companion) that reached
  the point where `broker.execute` recorded a TERMINAL or NO evidence (i.e. NOT
  the `PROVIDER_CALL_IN_FLIGHT` sub-window — that case is AC-376-5), a second
  `run_train` invocation PUBLISHES the node via the prebuilt path and writes
  `pr_open`.
  *Observable:* the resumed run reaches `broker.execute` and returns
  `{status: "published"}` for the node; `pr_open` appended, carrying `fab_run_id`
  (see AC-376-7).
  *Falsifier:* revert the Step-4 `committing` branch (§2) → resume re-runs the
  execute path → `publish_from_worktree` returns `nothing_staged`
  (`publishing.py:223`) and the node never publishes.
  *Injection anchor:* `assert` the resumed publish call was made with
  `prebuilt=True` (not the execute path), AND the pre-resume ledger's last record
  for the node is `committing` with no `pr_open`/`blocked` (the faithfulness
  assertion above). **Scope note:** "publishes" is the terminal-or-no-evidence
  window; the in-flight sub-window's determinate block is AC-376-5, and neither
  window ever returns to the silent `nothing_staged` stuck-state.

- [ ] **AC-376-2 (crash BEFORE commit re-runs through the DEFAULT preflight,
  preserving-not-destroying, does not mis-route).** A crash with `HEAD ==
  pre_commit_head` (commit never landed) leaves a DIRTY workspace; resume passes the
  DEFAULT `_default_preflight` (the node carries a `committing` marker — §1b), then
  PRESERVES the dirty tree to a verified quarantine (byte-survival is AC-376-11) and
  RE-RUNS the normal execute path (not the prebuilt path).
  *Observable:* with the real dirty post-crash workspace and the DEFAULT preflight,
  `run_train` does NOT return `preflight_failed`; the resumed run preserves the
  dirty tree, resets to `pre_commit_head`, invokes `run_loop`, and stages/commits
  afresh; it does NOT call publish with `prebuilt=True`.
  *Falsifier (any fails the AC):* (a) revert the §1b preflight exemption → the
  dirty workspace makes `run_train` return `preflight_failed` and the node never
  resumes at all (proves the exemption is load-bearing — round-2 finding 1); (b)
  weaken the reconciliation to route on marker-presence alone (drop the `HEAD ==
  pre_commit_head` equal-head arm) → a no-commit crash is mis-routed to
  prebuilt-publish → publishes the stale parent or blocks spuriously; (c) make the
  preservation unverified (skip the "block if quarantine unproven" guard) → a
  quarantine failure would let `reset --hard` run anyway (that regression is what
  AC-376-11 catches).
  *Injection anchor:* drive the crash in the real subprocess BEFORE
  `publishing.py:179` so the workspace is genuinely dirty; `assert` the resume ran
  the DEFAULT preflight (no `_preflight_fn` injected) and did NOT return
  `preflight_failed`, AND `run_loop` was invoked on resume for the no-commit node,
  AND `prebuilt=True` was NOT passed.

- [ ] **AC-376-3 (stale-upstream on a frozen commit fails closed).** A resumed
  committed-unpublished node whose consumed upstream was rebuilt this run (or
  pushed out-of-band) is BLOCKED with `upstream_changed_downstream_committed`
  before any publish, not silently shipped.
  *Observable:* `run_train` returns `{status: "blocked", detail.reason:
  "upstream_changed_downstream_committed"}`; no `broker.execute` for the node.
  *Falsifier:* remove the §3 re-check → the frozen commit ships against a stale
  upstream → the node publishes (no block), reproducing the pr_open-gate bypass.
  *Injection anchor:* `assert` the upstream id is in `rebuilt_this_run` (or
  `out_of_band_upstreams`) at the point the block fires, and `broker.execute` was
  never called for this node (proves the path was ENTERED — principle #3).

- [ ] **AC-376-4 (commit-stable identity across a cross-epoch rebuild) —
  UNSATISFIABLE UNTIL `#368` MERGES; do not claim proven before then.** On
  resume, the reconstructed admission is REBUILT at a freshly-allocated epoch
  (not `lease_epoch=1`) and DEDUPS via `attempt_id`, with
  `base_sha == merge-base(committed_head, origin/<base>)` byte-identical to the
  pre-crash admission — so a faithful retry dedups instead of raising.
  *Observable (post-#368):* the resumed `admit_next`/envelope rebuild records an
  `attempt_id` dedup HIT and, on the DURABLE `AdmissionRecord`, an `.epoch`
  distinct from the pre-crash epoch, with equal `base_sha`. (Read the durable
  record's `.epoch`, NOT a `BrokerExecutionResult.granted_epoch` — that result
  field does not exist; #368's B4 fold resolved `granted_epoch` to
  `record.epoch` / `store.replay()[-1].epoch`, and this AC MUST use that same
  observable or it reintroduces the assertion-cannot-be-expressed vacuity.)
  *Falsifier (post-#368):* pin `base_sha` to a captured pre-crash value / a
  non-`merge-base` head → the rebuilt approval digest diverges → the retry
  RAISES instead of dedup.
  *Current state (verified):* `_default_build_admission` binds `base_sha = rev-parse
  HEAD` (`:120`) and `lease_epoch=1` (`:138`) — the epoch never moves, so there is
  no cross-epoch rebuild to exercise. This AC therefore cannot be satisfied on the
  pre-#368 code and MUST NOT be reported green until #368 is merged and #376 is
  rebased onto it. This AC is the production-seam discharge of `#368` AC-13.

- [ ] **AC-376-5 (broker in-flight sub-window fails closed — codex 1).** A crash
  AFTER credsep's `gh pr create` succeeded but BEFORE `record_terminal`
  (`verbs.py:72`) leaves the evidence `PROVIDER_CALL_IN_FLIGHT`. On resume the node
  BLOCKS with a determinate broker-ambiguity reason — it does NOT fabricate a
  second PR and does NOT silently drop the commit.
  *Observable:* `run_train` returns `{status: "blocked"}` for the node with a
  broker-ambiguity reason (`outcome_ambiguous` / `pr-unconfirmed`); the ledger has
  no `pr_open`; exactly ONE PR exists on the remote for the branch.
  *Falsifier:* seed the evidence store with a `PROVIDER_CALL_IN_FLIGHT` record for
  the node's key and a real already-created PR, then resume; if the resume path
  claimed `published` (masking the ambiguity) or the fake `gh pr create` was
  invoked a second time and SUCCEEDED (duplicate PR), the AC fails. Positive
  control: with a TERMINAL evidence record instead, resume dedups and publishes
  (AC-376-1) — proving the test distinguishes the two evidence states.
  *Injection anchor:* drive the crash through `verbs.py` so the evidence state is
  produced by the real `record_intent`→adapter path, not a hand-built record;
  `assert` the terminal ledger status is `blocked` and the remote PR count is 1.

- [ ] **AC-376-6 (EXACT commit identity via post-commit SHA — the node's OWN commit
  publishes even under hook mutation; a foreign same-parent commit with a DIFFERENT
  SHA blocks — round-3 finding 2).** Obligation: resume must publish *the same
  committed object this run produced* — identified by the SHA recorded POST-commit —
  and must fail closed on any head that is not that exact SHA, including a foreign
  same-parent commit (identity, not authorization). It must NOT false-reject a
  legitimate commit merely because a clean-filter or pre-commit hook mutated its tree.
  *Observable / positive control (this is the fix):* a resume where a pre-commit hook
  (or clean filter) ALTERED the committed tree, but `HEAD == rec.committed_head_sha`
  (the SHA was recorded AFTER the mutation by the real `on_committed` callback),
  PUBLISHES — `run_train` returns `{status:"published"}` and `broker.execute` is
  called. Exact PRE-commit tree (round-1) would have false-blocked this; the
  post-commit SHA does not, because it records the tree the hook actually produced.
  *Observable / negative — identity (the arm that proves identity ≠ authorization):*
  a resume where a FOREIGN commit sits on the exact recorded parent AND is fully
  CONFINED to the node's owned paths (so round-2.5 confinement would have ACCEPTED
  it), but its SHA `!= rec.committed_head_sha`, is BLOCKED — `run_train` returns
  `{status:"blocked", detail.reason: "committed_head_moved_on_resume"}`;
  `broker.execute` is NEVER called. This is the case confinement could not
  distinguish and exact SHA does.
  *Observable / negative — unrecorded gap (fail-closed, not authorization):* a
  crash in the commit→append gap (`HEAD^ == pre_commit_head`, NO `committed_head_sha`
  recorded) BLOCKS with `committed_head_unrecorded_on_resume` — it does NOT fall back
  to a confinement/authorization check to publish.
  *Falsifier (any fails the AC):* (a) restore exact PRE-commit-tree identity → the
  hook-mutated commit blocks (positive control fails); (b) restore owned-scope
  confinement AS identity (accept any same-parent in-scope commit) → the foreign
  different-SHA commit publishes (identity-negative fails — the round-3 defect); (c)
  make the unrecorded-gap arm fall back to confinement-and-publish → the gap arm
  publishes an unidentified head (unrecorded-negative fails).
  *Injection anchor:* run all arms in the same module against a real repo — (positive)
  configure a pre-commit hook that reformats an OWNED file, let the REAL `on_committed`
  fire, resume, assert PUBLISHES with `HEAD == rec.committed_head_sha`; (identity-neg)
  after the real crash, move HEAD to a DIFFERENT foreign commit on the same parent,
  confined to owned paths, and assert the resume BLOCKS `committed_head_moved_on_resume`
  with `broker.execute` not called. **(Faithfulness distinction: the MARKER
  `committed_head_sha` is still produced by the real `on_committed` callback — never
  fabricated; the HEAD-move is the ADVERSARIAL CONDITION under test, i.e. the world
  changed under a genuine marker, not a hand-built ledger state. That is the opposite
  of the forbidden "hand-construct the post-crash ledger" — here the ledger is real
  and the environment is the variable.)** (gap-neg) drive a
  crash in the commit→append window so no `committed_head_sha` is recorded and assert
  BLOCK `committed_head_unrecorded_on_resume`. `committed_head_sha` MUST be produced
  by the real callback, never hand-injected (faithfulness — `## Verification`).

- [ ] **AC-376-7 (resumed FAB node binds its `fab_run_id`, or blocks — never
  silent `None` — B1).** A crash-resumed node that was FAB-scoped (its `committing`
  marker carries `fab_run_id`, `PHASE_LOOP_FAB` on) publishes `pr_open` with the
  SAME `fab_run_id` bound (in both `completed_nodes[nid]` and the ledger record),
  OR blocks when provenance is missing/mismatched — it never writes `pr_open` with
  `fab_run_id=None`.
  *Observable:* `completed_nodes[nid]["fab_run_id"]` and the `pr_open` record's
  `fab_run_id` equal the marker's `fab_run_id`, so `_fab_promotion_gate_before_merge`
  is NOT inert (`train_runner.py:485-496`); with corrupted provenance the node is
  `blocked` instead.
  *Falsifier:* route the resume through the declared-prebuilt path verbatim (as the
  pre-fold plan did) so `_node_fab_run_id` stays `None` (comment
  `train_runner.py:2526-2532`) → `pr_open` written with `fab_run_id=None` → the
  merge-time re-gate is inert → FAB content would merge ungated. The AC fails
  because the resumed `pr_open.fab_run_id` is `None` (or absent).
  *Injection anchor:* `assert` the resumed `pr_open` record's `fab_run_id` equals
  the marker's, AND `assert` a separate arm with tampered provenance yields
  `blocked` — proving the resume runs `_resolve_admission_fab_run_id` (bind-or-block),
  not the prebuilt path's silent `None`.

- [ ] **AC-376-8 (resumed node populates `completed_nodes` — B2).** After a
  resumed publish, downstream nodes and the P4 merge loop find the node in
  `completed_nodes[nid]` with `branch`, `head_sha`, `admitted_head_sha`, and
  `pr_url`, exactly as the normal success epilogue populates them.
  *Observable:* a two-node train where the UPSTREAM node crash-resumes and the
  DOWNSTREAM node consumes it: the downstream node's PR body / pin reads the
  upstream's `completed_nodes[nid]` values; the P4 loop's `--match-head-commit`
  reads `completed_nodes[nid]["admitted_head_sha"]`.
  *Falsifier:* collapse the resume epilogue to the `pr_open` append only (omit the
  `completed_nodes[nid] = {...}` population) → the downstream node raises
  KeyError / mis-pins, or the P4 merge loop cannot resolve the admitted head.
  *Injection anchor:* `assert completed_nodes[nid]["admitted_head_sha"] == head_sha`
  after the resumed publish, AND drive a downstream consumer that reads it.

- [ ] **AC-376-9 (resume publishes at the node's OWNED scope, not the whole branch
  diff — codex 3).** The resumed publish passes `owned_paths == rec.owned_paths`
  (the persisted union of run_loop snapshot dirty ∪ injected-upstream), NOT
  `prebuilt_owned_paths_fn`'s whole committed-diff-vs-base.
  *Observable:* the `broker.execute` / `publish_fn` call on resume receives
  `owned_paths` byte-equal to the marker's `owned_paths`; a path changed on the
  branch since `origin/<base>` but OUTSIDE the node's owned set is NOT in the
  scope passed.
  *Falsifier:* construct a resumed node whose committed diff vs `origin/<base>` is
  broader than its owned scope (e.g. an upstream node's paths are present in the
  branch history vs base but were not this node's owned set); if the resume derives
  `owned_paths` from `prebuilt_owned_paths_fn(workspace, _DEFAULT_BASE)`, the passed
  scope is broader than `rec.owned_paths` and the AC fails.
  *Injection anchor:* `assert` the `owned_paths` argument captured at the resumed
  `publish_fn` call equals `rec.owned_paths` (tuple-equal), and is a STRICT subset
  of `prebuilt_owned_paths_fn(workspace, _DEFAULT_BASE)` in the constructed case —
  proving the persisted scope, not the broadened one, is authoritative.

- [ ] **AC-376-10 (recovery-aware preflight admits a durably-marked node on a real
  dirty workspace, but still fails closed for an unmarked dirty node — round-2
  finding 1).** Obligation: the resume entry gate must let a node carrying a
  durable `committing` marker past the uncommitted-changes check on its real
  post-crash (dirty) workspace, while every unmarked dirty node still aborts the
  train with zero PRs.
  *Observable / positive (reachability):* after a real `run_train` crash that left
  a `committing` marker and a DIRTY workspace, a second `run_train` invocation with
  the DEFAULT `_default_preflight` does NOT return `preflight_failed` — it proceeds
  to read the ledger and reach the Step-4 committing branch (the resumed node then
  publishes or blocks per AC-376-1/5/6, never `preflight_failed`).
  *Observable / negative (fail-closed narrowness):* a node with a DIRTY workspace
  and NO `committing` marker (a stray edit, or a `running`-not-`committing` record)
  still makes `run_train` return `{status:"preflight_failed"}` with zero PRs — the
  exemption is keyed strictly on the marker.
  *Falsifier (either fails the AC):* (a) revert the §1b exemption (or the Step-1.5
  ledger-read reorder, or the `_default_preflight` `ledger_state` param) → the
  marked dirty node returns `preflight_failed` and never resumes (positive fails —
  reproducing finding 1's dead-code mechanism); (b) broaden the exemption to skip
  `_check_repo_clean` for ANY dirty node → the unmarked dirty node is admitted
  (negative fails — the entry invariant is breached).
  *Injection anchor:* assert the resume used the DEFAULT preflight (no
  `_preflight_fn` injected) on the REAL dirty post-crash workspace and did not
  return `preflight_failed`; and in a sibling arm, seed one node dirty WITHOUT a
  `committing` marker and assert `run_train` returns `preflight_failed` with zero
  publish calls. This is the AC that proves finding 1 is closed on the production
  path and the exemption is marker-narrow, not a blanket dirty-skip.

- [ ] **AC-376-11 (a resume NEVER destroys unrelated uncommitted work — round-3
  finding 1).** Obligation: when the equal-HEAD arm regenerates a crash-before-commit
  node, any pre-existing uncommitted change that did NOT come from this run must
  SURVIVE the resume — never silently deleted by `reset --hard`/`clean`. *(The
  positive-control wording depends on the §1b mechanism choice, a lead decision:
  quarantine-in-place → "recoverable from a verified named ref"; fresh-worktree →
  "byte-identical in the original tree afterward." The plan carries quarantine as
  primary; this AC is written for it and flags the alternative.)*
  *Observable / positive control (quarantine):* seed the crashed workspace with an
  unrelated dirty file the run never touched (both a tracked edit and an untracked
  file); after resume, that file's pre-crash bytes are RECOVERABLE from the recorded
  `refs/fab-quarantine/<node>/<run_id>` (the ref resolves to a tree containing the
  exact pre-crash content). *(Fresh-worktree variant: the file is byte-identical in
  the original worktree, untouched.)*
  *Observable / negative (fail-closed on unproven preservation):* if the quarantine
  ref-write fails or resolves empty, `run_train` BLOCKS the node and does NOT run
  `reset --hard`/`clean` — the unrelated bytes remain in the working tree (never
  destroyed on an unverified quarantine).
  *Falsifier (either fails the AC):* (a) restore the unconditional `git reset --hard`
  + `git clean -fd` (the round-2.5 arm) → the unrelated tracked edit is reset and the
  untracked file deleted, unrecoverable → positive control fails (this is the exact
  regression finding 1 names); (b) run the destructive op WITHOUT gating on proven
  quarantine → inject a quarantine failure and observe `reset --hard` still runs and
  eats the bytes → negative fails.
  *Injection anchor:* drive the real crash-before-commit in a subprocess, plant an
  unrelated dirty file, resume through the DEFAULT preflight, and assert the unrelated
  content is recoverable from the quarantine ref (or byte-identical, per mechanism)
  AND that a forced quarantine failure yields a BLOCK with the working tree untouched.
  This is the AC the lead required: "pre-existing unrelated changes survive a resume,
  with a positive control."

## AC observable-grounding (standing rule — every falsifier names an observable the code can produce)

Per the lead's standing rule (#375 had a filler falsifier survive a 98/98 claim;
#368 named a symbol no API produces), each AC's observable was grounded against a
concrete symbol at `file:line`. `x.y ⇒ y exists on type(x)`:

| AC | Asserted observable | Grounded at | Producible today? |
|---|---|---|---|
| 1 | `{status:"published"}`; `pr_open` w/ `fab_run_id` | `publishing.py:199` returns `{"status":"published",...}`; `LedgerRecord.fab_run_id` `train_ledger.py:175-183` | YES |
| 2 | DEFAULT preflight passes (no `preflight_failed`); `run_loop` invoked; `prebuilt=True` NOT passed | `_default_preflight` `train_runner.py:303`; `preflight_failed` return `:2294`; `publish_fn`/`run_loop` seams | YES (seam + §1b) |
| 3 | `{status:"blocked", reason:"upstream_changed_downstream_committed"}`; no `broker.execute` | blocked-return shape `train_runner.py:2733-2737`; reason string DEFINED by §3 | YES (reason introduced by this plan) |
| 4 | durable `AdmissionRecord.epoch` dedup HIT, equal `base_sha` | `AdmissionRecord.epoch` `admission.py:16`; #368 fold resolution | POST-#368 only (flagged); NOT `result.granted_epoch` (no such field) |
| 5 | `{status:"blocked"}` broker-ambiguity reason; remote PR count 1 | `verbs.py:76` `reason="outcome_ambiguous"`; `credsep.py:284` `pr-unconfirmed`; PR count via fake `gh` | YES |
| 6 | positive: hook-mutated commit w/ `HEAD == rec.committed_head_sha` → `{status:"published"}` + `broker.execute` called; identity-neg: foreign same-parent in-scope commit, SHA ≠ recorded → `{status:"blocked", reason:"committed_head_moved_on_resume"}` + no `broker.execute`; gap-neg: `HEAD^==pre_commit_head`, no SHA recorded → `{status:"blocked", reason:"committed_head_unrecorded_on_resume"}` | identity = exact `LedgerRecord.committed_head_sha` (NEW field, `train_ledger.py` §Changes) vs `git rev-parse HEAD`; `on_committed` fired at `publishing.py:188-190`; reasons DEFINED by §2 arms; blocked/published shapes as AC-1/AC-3 | YES |
| 7 | `completed_nodes[nid]["fab_run_id"]` == marker; `pr_open.fab_run_id` == marker; gate not inert | `completed_nodes` dict `:2767-2777`; `pr_open.fab_run_id` `:2790`; `_fab_promotion_gate_before_merge` `:485-496` | YES |
| 8 | `completed_nodes[nid]["admitted_head_sha"]` == `head_sha` | `completed_nodes[nid]["admitted_head_sha"]` `:2773` | YES |
| 9 | captured `owned_paths` arg == `rec.owned_paths`, ⊊ whole-diff | `publish_fn` arg spy; `rec.owned_paths` tuple; `prebuilt_owned_paths_fn` `:2536` | YES |
| 10 | marked dirty node → no `preflight_failed`, reaches Step-4 branch; unmarked dirty node → `{status:"preflight_failed"}`, zero PRs | `_default_preflight` `:303`/`:332` (new `ledger_state` param, §1b); `preflight_failed` return `:2294`; `_check_repo_clean` `:168-183` | YES |
| 11 | unrelated dirty file (tracked AND untracked) recoverable from `refs/fab-quarantine/...` after resume; unproven quarantine → BLOCK, tree untouched | quarantine ref (NEW, §1b — captures tracked+untracked, e.g. `stash push --include-untracked`); `git cat-file`/`rev-parse` verify; block-return shape `:2733-2737` | YES |

Every AC 1/2/3/5/6/7/8/9/10/11 observable is producible on TODAY's code; only AC-4's
is #368-gated and is grounded on the durable record's `.epoch`, not on a result field
that does not exist.

## Execution Policy

- execute: effort=high, reason=crash-consistency + resume reconciliation +
  frozen-vocabulary contract change + persisted-reconstruction marker; subtle
  post-commit window and fail-closed branches, security-adjacent (never publish a
  stale/foreign/unidentified HEAD, never drop FAB scope, never broaden owned scope).
