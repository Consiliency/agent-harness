# Detailed plan: post-commit crash-resume seam for train publish (`Consiliency/agent-harness#376`)

> **PLAN ONLY.** No implementation, no merge. Written 2026-07-29 to be paneled;
> revised for the round-1 board (grok+codex, five findings — see `## CR fold`).
> **Core (AC-376-1/2/3, and the CR fold AC-376-5..9) is INDEPENDENT of `#368` and
> fixes the reachability + safety defects on today's code** (the publish
> idempotency key is epoch-independent — see `## The #368 interlock`). **Only
> `AC-376-4`** — the cross-epoch identity proof — is `#368`-gated. See
> `## Dependencies & order`.
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
| codex 2 | `HEAD^ == pre_commit_head` proves PARENTAGE, not committed-tree identity | marker records only the pre-commit parent | marker records `expected_tree_sha`; resume requires `HEAD^{tree} == expected_tree_sha`, else fail closed | AC-376-6 |
| grok B1 | routing a resumed FAB node through the prebuilt path drops `fab_run_id` → merge-gate inert → **fail-open** | prebuilt path leaves `_node_fab_run_id=None` (`:2526-2532`) | marker carries `fab_run_id`; resume epilogue runs `_resolve_admission_fab_run_id` → bind or BLOCK | AC-376-7 |
| codex 3 | recovery broadens authorization to whole-branch-diff | prebuilt `owned_paths` = committed diff vs base (`:2536`) | marker persists the node's `owned_paths`; resume publishes at that scope | AC-376-9 |
| grok B2 | resume epilogue omits `completed_nodes` | epilogue collapsed to "write `pr_open`" | resume runs the FULL normal epilogue `:2739-2792` | AC-376-8 |
| codex 1 | crash window not fully covered — `PROVIDER_CALL_IN_FLIGHT` sub-window re-invokes `gh pr create` → ambiguity | broker replay excludes in-flight (`verbs.py:58`); credsep returns ambiguous before adopting an existing PR (`credsep.py:284` vs `:293`) | premise + scope corrected (fails CLOSED, not open); broker recovery filed as a follow-up | AC-376-5 |

codex 2, B1, B2, codex 3 are ONE class (the resumed-execute-node needs persisted
state — next section). codex 1 is a distinct pre-existing broker gap #376 makes
reachable. Priority the lead set — codex 2 and grok B1 first (the two that make
the fix worse than the bug) — is reflected in the marker-identity and FAB-scope
work being the load-bearing changes.

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
| **codex 2** | landed-check is parentage only (`HEAD^ == parent`) — any child of the parent passes, incl. an amended/foreign commit | `expected_tree_sha` (the tree the node stages) | require committed-tree IDENTITY, not parentage; fail closed on a foreign/amended tree |
| **B1** | `_node_fab_run_id` stays `None` (comment `train_runner.py:2526-2532`) → merge-time re-gate inert → FAB content merges ungated | `fab_run_id` (the run_loop-plumbed value) | re-resolve provenance against the committed head; bind or BLOCK — never silent `None` |
| **codex 3** | `owned_paths = prebuilt_owned_paths_fn(...)` = whole committed diff vs base | `owned_paths` (the node's actual owned scope: run_loop snapshot dirty ∪ injected-upstream union) | publish scoped to what the node OWNED, not everything the branch touched |
| **B2** | success epilogue collapsed to "write `pr_open`" | (nothing new — code, not marker) | run the FULL normal epilogue `train_runner.py:2739-2792`: `completed_nodes[nid]` population incl. `admitted_head_sha` |

All three new marker fields are `committing`-only and omit-when-absent (mirror the
`fab_run_id` omit-when-`None` pattern, `train_ledger.py:175-183`); `committing` is
a brand-new status, so no EXISTING record ever sets them. Byte-neutrality of every
non-`committing` record is preserved as long as `to_dict`'s omit filter is
GENERALIZED from the current `fab_run_id`-only hard-code to include the new fields
— a required, verified code change, not automatic (see the BYTE-NEUTRALITY TRAP
in `## Changes`).

**Why `expected_tree_sha` is the RIGHT identity (codex 2).** The plan's literal
obligation is "publish the **same committed tree**." The execute path stages
EXACTLY `owned_paths` by name (`git add -- <owned_paths>`, never `-A`,
`publishing.py:164`) then commits (`publishing.py:179`), so the committed tree is
a deterministic function of (parent tree, owned_paths, worktree content) — all
known at marker time, one line before `publish_fn`. The marker computes it in a
TEMP index without disturbing the live one (`GIT_INDEX_FILE=<tmp> git read-tree
HEAD && git add -- <owned_paths> && git write-tree`), records the resulting tree
SHA, and `publish_fn`'s own `git add -- owned_paths` + commit reproduces that
exact tree. Resume then checks `HEAD^ == pre_commit_head` **AND**
`HEAD^{tree} == expected_tree_sha`. Tree-equality is not a proxy for identity —
it IS the obligation: a commit reproducing the exact tree publishes byte-identical
content, and any foreign/amended tree differs in the tree SHA and fails closed.
(A pre-commit marker structurally cannot record the post-commit COMMIT sha; it CAN
pin the tree it is about to commit, which is the object the obligation is about.)

*Rejected alternative — a second, post-commit `committed`-SHA marker.* Recording
the exact commit sha after `publishing.py:188` would need a `publish_fn` seam
(the plan otherwise touches no `publishing.py`) and reintroduces a
commit→marker atomicity window whose absent-marker case must ALSO fail closed —
so it is strictly more machinery for the same fail-closed guarantee the
tree-in-marker gives with one durable write. Named so it is not silently skipped.

## Design

### 1. Durable pre-commit marker (a new `committing` ledger status + `pre_commit_head` + `expected_tree_sha` + `fab_run_id` + `owned_paths`)

`train_runner` writes a `committing` record **with `durable=True`**, immediately
before it calls `publish_fn(...)` on the EXECUTE path (around
`train_runner.py:2698`). At that point `owned_paths` and `_node_fab_run_id` are
already computed (both are inputs to the very `publish_fn` call that follows), so
the record captures, all at marker time:

- `pre_commit_head` = `git rev-parse HEAD` — the PARENT the commit will be built
  on (landed-detection; unchanged).
- `expected_tree_sha` = the tree that staging `owned_paths` onto `pre_commit_head`
  produces, computed in a TEMP index so the live index is untouched
  (`GIT_INDEX_FILE=<tmp> git read-tree HEAD && git add -- <owned_paths> && git
  write-tree`) — committed-tree IDENTITY (codex 2). This mirrors `publish_fn`'s
  exact staging (`git add -- owned_paths`, `publishing.py:164`), so the tree it
  records equals the tree `publish_fn` commits.
- `owned_paths` = the node's actual owned scope passed to `publish_fn` (run_loop
  snapshot dirty paths ∪ injected-upstream union) — recovery scope (codex 3).
- `fab_run_id` = `_node_fab_run_id` (the run_loop-plumbed value, `None` on non-FAB
  or flag-off) — FAB scope carrier (B1). Omit-when-`None`, byte-neutral.

A failure to compute `expected_tree_sha` (temp-index git error) fails closed
BEFORE `publish_fn` — the node is not left half-marked.

**Why the marker records the PRE-commit head AND the expected tree, and why
non-atomicity is fine.** The lead's caution — "a marker that is itself non-atomic
with respect to the commit just relocates the window" — is answered by making git,
not the marker, the source of truth for "did the commit land." `pre_commit_head`
answers LANDED-DETECTION (a pre-image the marker can record before the commit
exists); `expected_tree_sha` answers IDENTITY (codex 2 — the object the commit
will produce, also known pre-commit because staging is deterministic, §"Why
`expected_tree_sha` is the RIGHT identity"). Resume reconciles both against
`git rev-parse HEAD`:

- `HEAD == pre_commit_head` → the commit did not land (crash before or during
  `git commit`) → re-run normally.
- `HEAD^ == pre_commit_head` AND `HEAD^{tree} == expected_tree_sha` → the commit
  landed AND its TREE is the one the node staged (positive identity, not mere
  parentage) → route to the prebuilt publish path.
- anything else — `HEAD^ != pre_commit_head`, OR a child whose
  `HEAD^{tree} != expected_tree_sha` (an amended/foreign commit on the recorded
  parent, codex 2) → cannot positively identify the committed object → **fail
  closed**.

The two durable facts (marker append, git commit) need not be simultaneous
because resume COMPARES them; atomicity is never assumed. The ordering
(marker strictly before commit) plus append-atomicity gives the guarantee:
a durable marker ⟹ the commit may or may not have landed (reconcile via git);
a torn/absent marker ⟹ the commit definitely had not started (safe to re-run,
because the tolerant reader (`train_ledger.py:311-345`) drops a torn trailing
line and resume sees the prior `running`). `git`'s own ref update is atomic
(rename), so HEAD is never observed half-moved — there is no torn-commit state
that yields a wrong decision.

**Why `durable=True` (fsync) on the marker.** Without fsync, a crash right after
the marker append but after the commit could lose the marker while keeping the
commit — reproducing the exact undetectable state #376 exists to close. fsync
before the commit guarantees: if the commit started, the marker is on disk.
This reuses the existing `durable=True` precedent (`_fab_delta_readmit`).

### 2. Resume detection + routing (train_runner Step 4)

In Step 4 (`train_runner.py:2440+`), for a node NOT already recovered into
`completed_nodes` (a `committing` node is not `pr_open`/`merged`, so Step 3 at
`:2311` does not recover it), add a branch keyed on the folded status, placed
after `workspace = resolve_workspace(node)` (`:2505`) and BEFORE the `running`
append (`:2509`):

```
rec = ledger_state.get(nid)
if rec is not None and rec.status == "committing":
    head = <git rev-parse HEAD in workspace>
    if head == rec.pre_commit_head:
        pass                      # commit never landed → fall through to normal re-run
    elif <head^ == rec.pre_commit_head> and <head^{tree} == rec.expected_tree_sha>:
        # committed-unpublished AND the committed TREE is the one the node staged
        # (codex 2 — identity, not parentage) → resume-publish the frozen commit
        <upstream-staleness re-check — see §3; block if stale>
        <route through the prebuilt publish path (prebuilt=True), §4,
         using rec.owned_paths (codex 3), NOT prebuilt_owned_paths_fn>
        <run the FULL success epilogue below (B1 + B2)>
    else:
        # head^ != parent (foreign commit on a different parent) OR
        # head^{tree} != expected_tree_sha (amended/foreign tree on the recorded
        # parent — codex 2). Cannot positively identify the committed object.
        <blocked: "committed_head_ambiguous_on_resume"; fail closed>
```

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

1. **Today the resumed identity is already stable — but for the wrong reason.**
   `base_sha` is the frozen committed HEAD, so reconstructing the admission on
   resume yields the same `base_sha`; and `lease_epoch=1` is constant, so the
   epoch-dependent `fence_token` is stable too. Identity is stable because the
   epoch never moves — i.e. via exactly the constant-epoch publish `#288` exists
   to remove.
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
- `LedgerRecord` (`:147-183`) — **modify** — add FOUR optional fields, all
  `committing`-only and omit-from-`to_dict`-when-absent (mirror the `fab_run_id`
  omit-when-`None` pattern at `:175-183`) so every non-`committing` record stays
  byte-for-byte unchanged: `pre_commit_head: Optional[str] = None` (landed check),
  `expected_tree_sha: Optional[str] = None` (committed-tree identity, codex 2),
  `owned_paths: Optional[tuple[str, ...]] = None` (recovery scope, codex 3), and
  reuse the EXISTING `fab_run_id` field (already on the record, `:175-183`) to
  carry FAB scope on the `committing` record (B1) — no new field for it. `LedgerRecord`
  already carries `fab_run_id`, so only three fields are genuinely new. Thread all
  new fields through the `ts`-reissue copy in `append_record` (`:272-283`) and
  `_dict_to_record` (`:356-367`). `owned_paths` serializes as a JSON list; on
  read, restore as a tuple.
  **BYTE-NEUTRALITY TRAP (verified against source):** `to_dict` (`:175-183`)
  currently hard-codes the omit-when-`None` filter to `fab_run_id` ONLY
  (`if not (k == "fab_run_id" and v is None)`). The three new optional fields MUST
  be ADDED to that filter (generalize it to an omit-set
  `{"fab_run_id", "pre_commit_head", "expected_tree_sha", "owned_paths"}`), or
  every non-`committing` record gains new `null` keys and byte-neutrality breaks.
  A round-trip test (write a `committing` record with all fields → `read_ledger`
  → fields survive; write a `running`/`pr_open` record → serialized JSON is
  byte-identical to pre-#376) is the falsifier for both the propagation and the
  neutrality.

### `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` (modify)
- Execute-path publish block (around `:2684-2702`) — **modify** — immediately
  before `publish_fn(...)`, capture `pre_commit_head = git rev-parse HEAD`,
  `expected_tree_sha` (temp-index `read-tree HEAD` + `add -- owned_paths` +
  `write-tree`, §1), and append `LedgerRecord(node_id=nid, status="committing",
  branch=<branch>, pre_commit_head=..., expected_tree_sha=..., owned_paths=tuple(
  owned_paths), fab_run_id=_node_fab_run_id)` with `durable=True`. All marker
  inputs (`owned_paths`, `_node_fab_run_id`) are the SAME values passed to the
  `publish_fn` call that follows. Execute path only; the declared-prebuilt path
  (`:2518-2561`) does not commit and is already crash-safe.
- Step 4 resume loop (around `:2505-2509`) — **add** — the `committing`
  reconciliation branch (§2): reconcile `pre_commit_head` AND
  `expected_tree_sha` (identity, not parentage — codex 2); on a positively-identified
  committed child run the §3 upstream-staleness re-check, `git fetch origin
  <base>`, then route through the prebuilt publish path (§4) using
  `rec.owned_paths` (codex 3), then run the FULL success epilogue
  (`_resolve_admission_fab_run_id` + block-or-bind, `completed_nodes` population,
  `pr_open` with `fab_run_id` — B1 + B2); on equal-head fall through to normal
  re-run; on any unidentified head fail closed.
- Reuse (no change) — `_default_build_admission` (`:103`),
  `publish_from_worktree`'s `prebuilt=True` path, `_resolve_admission_fab_run_id`
  (`:618`), and the normal success epilogue's shape (`:2739-2792`).
- NOT reused on the resume path — `_prebuilt_owned_paths` / `prebuilt_owned_paths_fn`
  (`:250`): the declared-prebuilt whole-diff-vs-base scope is REPLACED by the
  persisted `rec.owned_paths` (codex 3).

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
  `expected_tree_sha`, `owned_paths` fields (and its reuse of `fab_run_id`).
- No `README`/`CHANGELOG`/`AGENTS.md` footprint: this is internal coordinator
  crash-recovery, no public-surface change.

## Frozen-vocabulary confirmation

`train_ledger.py`'s status vocabulary is a frozen contract
(`VALID_STATUSES`, `:56-58`; enforced in `LedgerRecord.__post_init__`, `:168-173`).
This plan adds exactly one new value, `"committing"`, and three new optional
fields — `pre_commit_head`, `expected_tree_sha`, `owned_paths` — all populated
ONLY on a `committing` record and omitted from `to_dict` when absent; it also
sets the EXISTING `fab_run_id` field on the `committing` record (no schema
change for it). No other vocabulary is introduced; no existing value or field
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

AC-376-1/2/3 are machine-checkable by this suite today. AC-376-4 is NOT
machine-checkable until #368 merges (operational precondition: the epoch
allocator + `merge-base` `base_sha` must exist); it is recorded as
`#368`-gated and MUST NOT be reported green by the runner before that — a plan
amendment records its satisfaction once #376 is rebased onto merged #368.

**Test faithfulness (the core of #376).** The crash MUST be produced by the real
`run_train` path, never by hand-constructing the post-crash ledger + tree.

- **Primary — subprocess + SIGKILL.** Drive `run_train` in a real subprocess on
  a real git repo with a `publish_fn`/broker that performs the real commit then
  blocks on a barrier; the parent `SIGKILL`s the child in the window between
  commit and `pr_open`; then re-invoke `run_train` (resume) and assert publish.
  This is the lead's literal instruction and proves no `finally`/atexit masks
  the state.
- **In-process form (deterministic companion).** Inject a `BaseException`
  (`SystemExit`) at the deepest post-commit point — inside `broker.execute`,
  after `publishing.py:179` — bypassing `except Exception` at `:2704`. First
  confirm no outer `finally`/`BaseException` handler around the node loop or the
  CLI entry writes a terminal record on exit.
- **Ledger-faithfulness assertion (proves the state is REACHABLE, not
  constructed).** After the injected crash, assert the ledger byte-matches a real
  crash: the node's last record is `committing` with `pre_commit_head`,
  `expected_tree_sha`, and `owned_paths` set (and `fab_run_id` set on a FAB node),
  and there is NO `pr_open` and NO `blocked` record for it. An AC that resumes from
  a hand-built state would silently reproduce the exact defect #376 closes; this
  assertion is what forbids it, and it also proves the marker actually persisted
  the reconstruction fields the resume epilogue depends on.

## Acceptance criteria

Each names the falsifier (the mutation that makes it fail) and the injection
anchor. `AC-376-4` is written against the obligation and flagged
unsatisfiable-until-#368-merged. **AC-376-5..9 are the CR fold** (codex 1 →
AC-376-5; codex 2 → AC-376-6; B1 → AC-376-7; B2 → AC-376-8; codex 3 → AC-376-9);
all five are machine-checkable by the suite TODAY (they do not depend on #368).
Every AC's falsifier was written to name an OBSERVABLE the code can actually
produce and a mutation that makes it fire — see `## AC observable-grounding` for
the per-AC audit.

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

- [ ] **AC-376-2 (crash BEFORE commit re-runs, does not mis-route).** A crash
  with `HEAD == pre_commit_head` (commit never landed) resumes by RE-RUNNING the
  normal execute path, not the prebuilt path.
  *Observable:* the resumed run invokes `run_loop` and stages/commits afresh; it
  does NOT call publish with `prebuilt=True`.
  *Falsifier:* weaken the reconciliation to route on marker-presence alone
  (drop the `HEAD == pre_commit_head` equal-head arm, or the identity conjunction)
  → a no-commit crash is mis-routed to prebuilt-publish → publishes the stale
  parent or blocks spuriously.
  *Injection anchor:* `assert` `run_loop` was invoked on resume for the
  no-commit node AND `prebuilt=True` was NOT passed.

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

- [ ] **AC-376-6 (committed-tree IDENTITY, not parentage — codex 2).** A resume
  where HEAD is a child of `pre_commit_head` but its TREE differs from
  `expected_tree_sha` (an amended or foreign commit built on the recorded parent)
  is BLOCKED, not published.
  *Observable:* `run_train` returns `{status: "blocked", detail.reason:
  "committed_head_ambiguous_on_resume"}`; `broker.execute` is NEVER called for the
  node.
  *Falsifier:* between the crash and the resume, replace the committed HEAD with a
  different commit on the SAME parent (e.g. `git commit --amend` altering a byte,
  or a foreign commit whose parent is `pre_commit_head`) so `HEAD^ ==
  pre_commit_head` still holds but `HEAD^{tree} != expected_tree_sha`; if the
  reconciliation checks parentage ONLY (drops the `expected_tree_sha` conjunction),
  the foreign tree publishes. Positive control: the UNMODIFIED committed HEAD
  (tree matches) publishes (AC-376-1) — proving the identity check is not
  vacuously blocking everything.
  *Injection anchor:* `assert` the block fires with `broker.execute` not called,
  AND assert the positive-control (untouched tree) publishes in the same test
  module — the two arms together prove the check discriminates tree identity, not
  merely presence of a child.

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

## AC observable-grounding (standing rule — every falsifier names an observable the code can produce)

Per the lead's standing rule (#375 had a filler falsifier survive a 98/98 claim;
#368 named a symbol no API produces), each AC's observable was grounded against a
concrete symbol at `file:line`. `x.y ⇒ y exists on type(x)`:

| AC | Asserted observable | Grounded at | Producible today? |
|---|---|---|---|
| 1 | `{status:"published"}`; `pr_open` w/ `fab_run_id` | `publishing.py:199` returns `{"status":"published",...}`; `LedgerRecord.fab_run_id` `train_ledger.py:175-183` | YES |
| 2 | `run_loop` invoked; `prebuilt=True` NOT passed | test spies on the `publish_fn`/`run_loop` seams | YES (seam) |
| 3 | `{status:"blocked", reason:"upstream_changed_downstream_committed"}`; no `broker.execute` | blocked-return shape `train_runner.py:2733-2737`; reason string DEFINED by §3 | YES (reason introduced by this plan) |
| 4 | durable `AdmissionRecord.epoch` dedup HIT, equal `base_sha` | `AdmissionRecord.epoch` `admission.py:16`; #368 fold resolution | POST-#368 only (flagged); NOT `result.granted_epoch` (no such field) |
| 5 | `{status:"blocked"}` broker-ambiguity reason; remote PR count 1 | `verbs.py:76` `reason="outcome_ambiguous"`; `credsep.py:284` `pr-unconfirmed`; PR count via fake `gh` | YES |
| 6 | `{status:"blocked", reason:"committed_head_ambiguous_on_resume"}`; no `broker.execute` | reason DEFINED by §2 else-arm; blocked-return shape as AC-3 | YES |
| 7 | `completed_nodes[nid]["fab_run_id"]` == marker; `pr_open.fab_run_id` == marker; gate not inert | `completed_nodes` dict `:2767-2777`; `pr_open.fab_run_id` `:2790`; `_fab_promotion_gate_before_merge` `:485-496` | YES |
| 8 | `completed_nodes[nid]["admitted_head_sha"]` == `head_sha` | `completed_nodes[nid]["admitted_head_sha"]` `:2773` | YES |
| 9 | captured `owned_paths` arg == `rec.owned_paths`, ⊊ whole-diff | `publish_fn` arg spy; `rec.owned_paths` tuple; `prebuilt_owned_paths_fn` `:2536` | YES |

Every AC 1/2/3/5/6/7/8/9 observable is producible on TODAY's code; only AC-4's is
#368-gated and is grounded on the durable record's `.epoch`, not on a result field
that does not exist.

## Execution Policy

- execute: effort=high, reason=crash-consistency + resume reconciliation +
  frozen-vocabulary contract change + persisted-reconstruction marker; subtle
  post-commit window and fail-closed branches, security-adjacent (never publish a
  stale/foreign/unidentified HEAD, never drop FAB scope, never broaden owned scope).
