# Detailed plan: post-commit crash-resume seam for train publish (`Consiliency/agent-harness#376`)

> **PLAN ONLY.** No implementation, no merge. Written 2026-07-29 to be paneled.
> **DEPENDS ON `Consiliency/agent-harness#368` MERGED** — see `## Dependencies & order`.
> Scope: the CRASH case only (last ledger record survives as `committing`). The
> graceful post-commit-block variant is a flagged follow-up, NOT built here (see
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

- **The broker layer is already crash-safe.** `execute`'s replay-before-admit
  sequence (#288/#337) dedups an already-published head via the evidence store;
  the idempotency key is `publish_committed_branch_idempotency_key(repo, branch,
  head_sha)` — stable across resume because `head_sha` is the frozen committed
  SHA. The defect is purely that the normal publisher never REACHES the broker
  on resume: `publish_from_worktree`'s staged-diff audit
  (`publishing.py:207-228`) fires `nothing_staged` at `:223`, before
  `broker_client.execute(...)` at `:196`.
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

## Design

### 1. Durable pre-commit marker (a new `committing` ledger status + `pre_commit_head`)

`train_runner` writes a `committing` record **with `durable=True`**, immediately
before it calls `publish_fn(...)` on the EXECUTE path (around
`train_runner.py:2698`). The record carries `pre_commit_head` = `git rev-parse
HEAD` captured at that point — i.e. the PARENT the commit will be built on.

**Why the marker records the PRE-commit head, and why non-atomicity is fine.**
The lead's caution — "a marker that is itself non-atomic with respect to the
commit just relocates the window" — is answered by making git, not the marker,
the source of truth for "did the commit land." The marker is deliberately not
the post-commit head; it is the pre-image. Resume reconciles the marker against
`git rev-parse HEAD`:

- `HEAD == pre_commit_head` → the commit did not land (crash before or during
  `git commit`) → re-run normally.
- `HEAD^ == pre_commit_head` (HEAD is a direct child) → the commit landed,
  unpublished → route to the prebuilt publish path.
- anything else → ambiguous / foreign HEAD → **fail closed**.

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
    elif <head^ == rec.pre_commit_head>:
        # committed-unpublished → resume-publish the frozen commit
        <upstream-staleness re-check — see §3; block if stale>
        <route through the prebuilt publish path (prebuilt=True), §4>
        <on success: write pr_open exactly as :2780; continue>
    else:
        <blocked: "committed_head_ambiguous_on_resume"; fail closed>
```

A resumed-published node is **not** added to `rebuilt_this_run`: it publishes
the same frozen head it committed pre-crash, so downstream pins built against
that head remain valid (mirrors the Step-3 recovery at `:2417-2432`, which
populates `completed_nodes` without marking a rebuild).

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
owned_paths)`, with `owned_paths = prebuilt_owned_paths_fn(workspace,
_DEFAULT_BASE)` (the committed diff vs base — git is authoritative). It then
calls `publish_fn(workspace, owned_paths, **publish_kwargs)`. The broker's
replay-before-admit makes the call idempotent: an already-pushed head dedups; an
un-pushed head is admitted and pushed. **No change to `publishing.py`.**

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

**Therefore #376 must build on #368 MERGED.** If #376 landed on the
constant-epoch / `base_sha=HEAD` path, its crash-resume test would pass
trivially and would NOT exercise the envelope rebuild at a fresh epoch — a
vacuity relocated from the falsifier to the scenario, the exact failure #376 was
filed to prevent. The AC that asserts the cross-epoch rebuild
(`AC-376-4`) is therefore written against the OBLIGATION and flagged
**unsatisfiable until #368 merges** (per the lead's #375 caution: derive the
criterion from the obligation, not from what the current code can do; if it
cannot currently be satisfied, say so).

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
- `LedgerRecord` (`:147-183`) — **modify** — add optional field `pre_commit_head:
  Optional[str] = None`; omit it from `to_dict` when `None` (mirror the
  `fab_run_id` omit-when-`None` pattern at `:175-183`) so every non-`committing`
  record stays byte-for-byte unchanged. Thread it through the `ts`-reissue copy
  in `append_record` (`:272-283`) and `_dict_to_record` (`:356-367`).

### `phase-loop-runtime/src/phase_loop_runtime/train_runner.py` (modify)
- Execute-path publish block (around `:2684-2702`) — **modify** — capture
  `pre_commit_head = git rev-parse HEAD` and `append_record(..., LedgerRecord(
  node_id=nid, status="committing", branch=<branch>, pre_commit_head=...),
  durable=True)` immediately before `publish_fn(...)`. Execute path only; the
  declared-prebuilt path (`:2518-2561`) does not commit and is already crash-safe.
- Step 4 resume loop (around `:2505-2509`) — **add** — the `committing`
  reconciliation branch (§2): git-reconcile `pre_commit_head`; on committed-child
  run the §3 upstream-staleness re-check then route through the prebuilt publish
  path (§4) and write `pr_open`; on equal-head fall through to normal re-run; on
  ambiguous head fail closed.
- Reuse (no change) — `_default_build_admission` (`:103`), `_prebuilt_owned_paths`
  (`:250`), `publish_from_worktree`'s `prebuilt=True` path, and the `pr_open`
  write (`:2780`).

### `phase-loop-runtime/tests/…/test_train_runner_crash_resume.py` (create)
- The `run_train`-level crash-resume tests (see `## Verification` / the ACs).

## Documentation impact

- `Consiliency/agent-harness#368` AC-13 reachability note
  (`plans/detailed-fab-288-shared-epoch-allocator-20260728.md:1007-1024`) —
  **modify (at #376 execution, gated on #368 merged)** — point it at `AC-376-4`
  as the production-seam discharge. Recorded here as the promised debt; not
  edited in this plan.
- `train_ledger.py` module docstring record-shape list (`:19-37`, `:56-58`) —
  **modify** — document the `committing` status and `pre_commit_head` field.
- No `README`/`CHANGELOG`/`AGENTS.md` footprint: this is internal coordinator
  crash-recovery, no public-surface change.

## Frozen-vocabulary confirmation

`train_ledger.py`'s status vocabulary is a frozen contract
(`VALID_STATUSES`, `:56-58`; enforced in `LedgerRecord.__post_init__`, `:168-173`).
This plan adds exactly one new value, `"committing"`, and one new optional
field, `pre_commit_head`. No other vocabulary is introduced; no existing value
or field changes meaning. The `CoordinatorEvent` schema (`:73-117`) is NOT
touched.

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
  state but a materially different detection + semantics problem. **Flagged
  follow-up, not built here** — the ratified target is the crash case, where the
  `committing` marker survives the fold directly and detection needs no scan.
  Recommend a separate issue if desired.
- **Declared prebuilt nodes** are already crash-safe (their resume re-runs the
  idempotent prebuilt path); no marker needed.
- **The resume seam itself** (this plan) is #368-gated for its cross-epoch proof;
  see `## The #368 interlock`.

## Dependencies & order

1. **`Consiliency/agent-harness#368` MERGED is an upstream dependency** (the
   shared allocated epoch + §5b `merge-base` `base_sha` + `PreAdmissionEnvelope`
   rebuild). Until it merges, `AC-376-4` (cross-epoch rebuild) is unsatisfiable
   — build the marker/detection/routing (AC-1..3) but do not claim AC-4 proven.
   This is a declared external dependency, not a phase.
2. Within this plan: ledger schema change (new status + field) before the
   train_runner marker write; marker write before the resume-detection branch can
   be tested end-to-end.

## Verification

Run from the runtime package root with `PYTHONPATH=src:tests`:

```
PYTHONPATH=src:tests python -m pytest phase-loop-runtime/tests/…/test_train_runner_crash_resume.py -q
PYTHONPATH=src python -c "from phase_loop_runtime.train_ledger import VALID_STATUSES; assert 'committing' in VALID_STATUSES"
```

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
  crash: the node's last record is `committing` with `pre_commit_head` set, and
  there is NO `pr_open` and NO `blocked` record for it. An AC that resumes from a
  hand-built state would silently reproduce the exact defect #376 closes; this
  assertion is what forbids it.

## Acceptance criteria

Each names the falsifier (the mutation that makes it fail) and the injection
anchor. `AC-376-4` is written against the obligation and flagged
unsatisfiable-until-#368-merged.

- [ ] **AC-376-1 (crash-resume publishes).** After a `run_train`-level crash in
  the commit→`pr_open` window (subprocess+SIGKILL primary; in-process
  `BaseException` companion), a second `run_train` invocation PUBLISHES the node
  via the prebuilt path and writes `pr_open`.
  *Observable:* the resumed run reaches `broker.execute` and returns
  `{status: "published"}` for the node; `pr_open` appended.
  *Falsifier:* revert the Step-4 `committing` branch (§2) → resume re-runs the
  execute path → `publish_from_worktree` returns `nothing_staged`
  (`publishing.py:223`) and the node never publishes.
  *Injection anchor:* `assert` the resumed publish call was made with
  `prebuilt=True` (not the execute path), AND the pre-resume ledger's last record
  for the node is `committing` with no `pr_open`/`blocked` (the faithfulness
  assertion above).

- [ ] **AC-376-2 (crash BEFORE commit re-runs, does not mis-route).** A crash
  with `HEAD == pre_commit_head` (commit never landed) resumes by RE-RUNNING the
  normal execute path, not the prebuilt path.
  *Observable:* the resumed run invokes `run_loop` and stages/commits afresh; it
  does NOT call publish with `prebuilt=True`.
  *Falsifier:* weaken the reconciliation to route on marker-presence alone
  (drop the `HEAD^ == pre_commit_head` check) → a no-commit crash is mis-routed to
  prebuilt-publish → `prebuilt_owned_paths_fn` raises "no committed changes vs
  origin/<base>" (`train_runner.py` around `:297`) or publishes the stale parent.
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
  `attempt_id` dedup HIT and a `granted_epoch` distinct from the pre-crash epoch,
  with equal `base_sha`.
  *Falsifier (post-#368):* pin `base_sha` to a captured pre-crash value / a
  non-`merge-base` head → the rebuilt approval digest diverges → the retry
  RAISES instead of dedup.
  *Current state (verified):* `_default_build_admission` binds `base_sha = rev-parse
  HEAD` (`:120`) and `lease_epoch=1` (`:138`) — the epoch never moves, so there is
  no cross-epoch rebuild to exercise. This AC therefore cannot be satisfied on the
  pre-#368 code and MUST NOT be reported green until #368 is merged and #376 is
  rebased onto it. This AC is the production-seam discharge of `#368` AC-13.

## Execution Policy

- execute: effort=high, reason=crash-consistency + resume reconciliation +
  frozen-vocabulary contract change; subtle post-commit window and fail-closed
  branches, security-adjacent (never publish a stale/foreign HEAD).
