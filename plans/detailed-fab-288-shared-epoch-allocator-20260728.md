# Detailed migration plan: FAB ah#288 — one shared monotonic epoch allocator across all admission kinds

> **Status: RATIFIED input (Option B, maintainer, 2026-07-28). Decision is SETTLED — do
> not relitigate.** Decision record: `gh issue view 363 --comments`. This plan is written
> FROM that decision; the implementation PR rewrites the killed design (the amendment-2
> plan PR, Consiliency/agent-harness#339), it does not revise it. This plan SUPERSEDES the
> stop-signed `plans/detailed-288-fab-broker-readmission-20260726.md` (killed
> caller-supplied-`lease_epoch` / `node_id`-lineage / `sequence >= 2` mechanism, 4 failed
> CR rounds).

Issues: Consiliency/agent-harness#288 (the FAB re-admission piece this unblocks),
Consiliency/agent-harness#363 (the ratification record).

---

## 1. The ratified decision, stated as the constraint this plan obeys

**All admission kinds — including publish — draw from ONE shared, per-repo, monotonic epoch
allocator. The broker allocates the epoch inside its lock; the caller never chooses it.**

Corollaries that are SETTLED, not open:

- **Publish byte-neutrality is RETRACTED.** Publish stops writing the literal constant
  `lease_epoch=1`. Its durable broker `AdmissionRecord.epoch` becomes an allocated value
  (`2`, `3`, …). **Any text in this plan or its PR that claims publish byte-neutrality
  alongside renumbering is repeating agent-harness#339 round 5 and must be rejected on
  sight.** The retraction is NOT gated by `PHASE_LOOP_FAB`: the publish admission is on the
  live merged `publish_committed_branch` path (#199), so the record-shape change applies
  wherever a live broker records, FAB flag on or off.
- **Publish stays SUBJECT to the fence and to revocation.** Option A (exempt publish from
  the epoch comparison) is dead: exempting publish from the comparison also exempts it from
  revocation — it would keep publishing after its lease was revoked. Do not reintroduce any
  variant of "publish opts out of the check." Publish is a participant *as a subject*.

### What the decision FORCES (not a design choice — state it and move on)

"Draw from one shared monotonic allocator" has exactly one sound realization:
**in-lock allocation.** Reading `max(epoch)+1` outside the advisory lock and then admitting
is the TOCTOU the allocator exists to kill; letting publish "join at the current max"
without an in-lock re-check is the revocation-exempt family the maintainer killed.
Therefore **publish routes through the same in-lock allocation entrypoint the readmit
primitive uses (`LinearizableAdmissionStore.admit_next`)** — or `execute` inlines the
identical in-lock logic. This is forced by soundness; it is not presented as a fork below.

---

## 2. Scope boundary — the two-namespace distinction (READ BEFORE TOUCHING ANY `epoch`)

This repo has **three distinct `epoch` namespaces**. Option B touches exactly ONE. A
mis-scoped edit into either of the others is a defect, and a sweep that "fixes" `epoch=1`
across the FAB tests is the wrong sweep.

| Namespace | Where | Touched by Option B? |
|---|---|---|
| **Broker admission epoch** — `AdmissionRecord.epoch`, `AdmissionRequest.lease_epoch`, the fence `request.lease_epoch < max(r.epoch)` | `convergence/broker/admission.py`, `convergence/fencing.py`, `convergence/refresh.py`, `train_runner.py:_default_build_admission` | **YES — this is the whole change** |
| **FAB review-round epoch** — `FAB_CANDIDATE_EPOCH`, `DeltaReviewRecord.epoch`, `SeatOutcomeRecord.epoch` (candidate=1, delta rounds 2,3…) | `fab_gate.py`, `fab_producer.py`, `fab_provenance.py`, `panel_invoker.py:540`, `train_runner.py:795/1037` | **NO — leave untouched** |
| **Runtime fencing event-log epoch** — `CoordinatorEvent.epoch`, `event_log.py` monotonic check | `convergence/event_log.py` | **NO by default** — see reader-audit RA-1 |

**Verified consequence:** the ONLY consumer of the broker `AdmissionRecord.epoch` is the
fence at `admission.py:49` (`max(r.epoch for r in records)`). The `epoch=1` assertions
across `tests/test_fab_*.py` and `panel_invoker.py:540` are the FAB review-round /
seat-outcome namespace and are **out of scope** — do not renumber them, and do not cite
them as falsifiers for this change. The in-scope test that stamps a broker admission epoch
is `tests/test_convergence_refresh.py:12` (`lease_epoch=1`).

---

## 3. Prior art to RE-LAND (not depend on)

The readmit / allocator primitive was built on branch `feat/288a-broker-readmit-primitive`
and shipped as PR Consiliency/agent-harness#337 — now **CLOSED**. Its blocker was the
publish-side epoch-domain decision (now ratified as B), **not an implementation defect**, so
the primitive itself carries forward. Its shared-lock revocation fix was already extracted
and MERGED as Consiliency/agent-harness#366 (both admission and evidence stores share one
`admissions.lock`, so `epoch_blocked` is now evaluated in-lock and actually fires). This
plan RE-LANDS the rest of #337 as prior art:

- `LinearizableAdmissionStore.admit_next(make_request, *, attempt_id, precondition)` —
  computes `epoch = max(existing)+1` INSIDE the flock, then calls `make_request(epoch)` to
  build the request at the allocated epoch.
  **RE-LAND WITH A CORRECTED IN-LOCK ORDER — do NOT port unchanged.** The 288a diff
  (@ `c1da62a`) returns the `attempt_id` dedup hit BEFORE its in-lock `epoch_blocked()`
  check — the exact ordering the parked-conflict record flags as a defect ("revocation must
  precede dedup"): a revoked resume returns its prior record as ACCEPTED and the caller
  proceeds to merge. The required in-lock order is:
  **`epoch_blocked` → `attempt_id` dedup → `precondition` → allocate `max+1` → `policy` →
  append.** Rationale: readmit has NO evidence-terminal replay (decoupled admit, no provider
  adapter), so ALL readmit idempotency lives at this admission-dedup layer; gating dedup
  behind `epoch_blocked` refuses a revoked resume (no double-merge — the ledger record +
  `--match-head-commit` pinning already prevent that) while still deduping a NON-revoked
  resume. This also closes the #366 race on the dedup path (a revocation landing after an
  outside-lock entry check but before the in-lock body is only caught if in-lock
  `epoch_blocked` precedes the dedup return).
- `AdmissionPrecondition = Callable[[tuple[AdmissionRecord, ...]], str | None]` — an
  in-lock gate over the durable log (used by readmit's baseline check; publish supplies
  none).
- `readmit_advanced_head(...) -> ReadmitResult`, `readmit_attempt_id(node_id, new_head_sha)`
  — the FAB readmit half (already uses `admit_next`).
- `_RoutingBrokerService.readmit_advanced_head` — routes on the SAME per-repo key as
  `execute`.

Do NOT re-invent these; port them from `origin/feat/288a-broker-readmit-primitive`
(@ `c1da62a`) unchanged except where §4/§5 below extend them to publish.

Also confirmed already shipped — **do NOT re-invent**: `RatificationPolicy`
(`ratification_policy.py`) exists and is unrelated to this change.

---

## 4. Enumerated seams (every site that CONSTRUCTS, ADMITS, or READS a broker epoch)

The principal danger of Option B is that it touches the LIVE MERGED publish path (#199).
The recurring failure in this repo is editing a helper while never threading the production
construction seam (`epoch_blocked` itself did this once: guard correct, never wired, suite
green). So the seams are enumerated exhaustively, each with the exact change.

### CONSTRUCTOR seams (build an `AdmissionRequest` carrying an epoch)

- **S1 — `train_runner.py:138`, `_default_build_admission`** *(THE live #199 publish
  builder — highest risk).* Today: `factory.lease(..., action="publish", lease_epoch=1)`
  then `factory.create(...)`, returning a fully-built `AdmissionRequest` with epoch `1`
  baked into `fence_token` and the fencing `idempotency_key`.
  **Change:** stop returning a finished request at a fixed epoch. Return instead a
  `make_request(epoch: int) -> AdmissionRequest` closure that rebuilds the lease + request
  at the epoch the broker allocates (see §5). Nothing here may hardcode `1`.

- **S2 — `convergence/refresh.py:61`, `refresh_downstream_after_merge`.** Today: takes a
  caller `lease_epoch: int` param and builds `factory.lease(..., lease_epoch=lease_epoch)`.
  **Change:** same epoch-late-binding — the function must obtain the epoch from the broker
  allocator, not a caller int; drop the `lease_epoch` parameter. **This has NO production
  caller** (only the def + `tests/test_convergence_refresh.py`); migrate it for consistency
  and to keep S1/S2 from drifting (S1's docstring says it "mirrors" S2), but it is not the
  live risk.

### ADMIT seams (where an epoch hits the fence and is recorded)

- **S3 — `verbs.py:65`, `BrokerService.execute`** *(the publish admit).* Today:
  `self.admission_store.admit(request.admission)` — admits the caller-stamped epoch.
  **Change:** switch publish to `self.admission_store.admit_next(make_request,
  attempt_id=<publish attempt_id, §6>)`. The `BrokerRequest`/`execute` contract must carry
  a `make_request` factory (or the fields needed to build one) instead of a pre-epoched
  `AdmissionRequest`. The in-lock `epoch_blocked` re-check inside `admit_next` preserves the
  #366 revocation guarantee; keep the pre-check at `verbs.py:64` too (fail-fast).

- **S4 — `verbs.py`, `readmit_advanced_head`** *(re-landed from #337).* Already uses
  `admit_next`. No change beyond re-landing.

- **S8 — `train_runner.py:892`, `_fab_delta_readmit` (THE readmit CONSUMER — the seam
  #288 exists to fix; "guard correct, never wired" applied to the readmit half).**
  Today (verified on `main` @ `b581fcd`): `_fab_delta_readmit` takes `ledger_path`, **NOT a
  `broker_client`**, and the call site (`train_runner.py:3084`) passes no broker. So the
  delta re-admit **bypasses broker lease/epoch/revocation entirely** — a node whose lease
  was revoked mid-run can still delta-re-admit and merge.
  **⚠️ There are TWO re-admission COMMIT POINTs in this one function, not one** (round-1 CR,
  codex — verified):
  - **`train_runner.py:1016`** — the idempotent CRASH-RESUME early append (comment: "a prior
    attempt already extended the chain to the live head AND it passes the gate — only the
    ledger append was pending"). Fires when `resolved_final == live_head_sha and
    _gate_passes()`.
  - **`train_runner.py:1139`** — the NORMAL path append ("7. COMMIT POINT"), after
    capture+build+re-gate.

  Both build the **identical** `LedgerRecord(status="pr_open", head_sha=live_head_sha,
  fab_run_id=run_id, …)` and both `append_record(..., durable=True)` directly. A rewrite
  that only touches `:1139` (the seam a reader lands on) leaves `:1016` as a live bypass: a
  crash that leaves gate-passing extended provenance lets a **revoked resume take the early
  `:1016` append and merge with no broker admission** — the exact #288 defect, on the path
  nobody reads. This is the dominant failure class in this line of work (guard added at one
  seam; a second seam completes the same operation unguarded).
  **Change — ONE shared broker-gated commit path covering BOTH appends (directive #1):**
  introduce a single inner `_commit_readmission(*, broker_client, ledger_path, node_id,
  branch, pr_url, merge_order, run_id, new_head_sha) -> str | None` that (a) fails CLOSED and
  returns `None` when `broker_client is None` (NO direct-append fallback — caller falls
  through to the unchanged `pr-head-advanced` guard); (b) otherwise calls
  `broker_client.readmit_advanced_head(...)`, which allocates via `admit_next` and
  fail-closes on `epoch_blocked`; (c) `append_record(..., durable=True)` the ledger record
  ONLY on an accepted `ReadmitResult`, then returns `new_head_sha`. **BOTH `:1016` and
  `:1139` call this one function instead of their inline `append_record`.** Two call sites
  converging on one admission-gated function — not two parallel rewrites that can drift.
  **Normative: any future site that advances the admitted head MUST route through
  `_commit_readmission`; a new direct `append_record` of an advanced head is a defect.**
  - **Commit-ordering / crash-consistency (state it so the shifted COMMIT POINT is not
    misread as a regression):** the broker admission becomes the authority; the ledger append
    is downstream of an accepted `ReadmitResult`. A crash BETWEEN the broker admit and the
    ledger append still fails CLOSED — the ledger stays at the OLD admitted head, so
    `_live_merge_pr` pins `--match-head-commit` to it and the guard fires; on resume the
    `:1016` branch re-enters `_commit_readmission`, and `admit_next` **dedups on the
    deterministic `readmit_attempt_id(node_id, new_head_sha)`** → same epoch if not revoked
    (idempotent, ledger append completes), refused if revoked (§6 two-layer / AC-6b).
  - **Threading (the load-bearing plumbing #288's body calls "multi-day protocol
    integration"):** `broker_client` must reach `_fab_delta_readmit` through the PRODUCTION
    path `run_train → merge loop (`:3084`) → _fab_delta_readmit → _commit_readmission`. The
    `CoordinatorRuntime` already carries `broker_client` (`train_runner.py:100`); it must be
    added to the `:3084` call and to `_fab_delta_readmit`'s signature. **Re-landing S4 makes
    the primitive EXIST; it does not make S8 CALL it — the test that proves the wiring is a
    seam-level test (AC-8a/8b, §8), NOT a direct helper call.**

**Enumeration method (so a reviewer can check COMPLETENESS, not just the result) —
repo-wide, per directive #3:**
1. `grep -rn "append_record(" phase-loop-runtime/src/` → **21 call sites in 3 files**
   (`train_ledger.py`, `train_runner.py`, `advisor_board/observability.py`). The durable
   ledger `append_record` is the SOLE commit surface that admits/advances a node's admitted
   head — the merge pins `--match-head-commit` to the ledger's admitted head, so a
   head-advancing re-admission MUST write a ledger record carrying the new head.
2. Discriminant for a HEAD-ADVANCING re-admission commit: the appended `LedgerRecord` sets
   `head_sha=live_head_sha` (the advanced head). `grep -rn "head_sha=live_head_sha"
   phase-loop-runtime/src/` — then EXCLUDE the read-side `final_pr_head_sha=live_head_sha` /
   `live_head_sha=` params in `fab_gate.py` and `fab_canonical.py` (gate-compose inputs, not
   ledger writes). **Result: exactly `train_runner.py:1020` and `:1143` — i.e. the `:1016`
   and `:1139` appends, both inside `_fab_delta_readmit`.** The `observability.py` and
   `train_ledger.py` appends are non-head-advancing (metrics / the `append_record` def).
3. Completeness is re-checkable by re-running both greps: any NEW head-advancing append
   surfaces as a third `head_sha=<advanced head>` hit and MUST route through
   `_commit_readmission` (step (1) normative rule).

### ALLOCATOR / FENCE seams

- **S5 — `admission.py:37`, `admit()`** *(legacy caller-epoch admit)*. Retained for
  back-compat, but **no publish/readmit caller uses it after this change.** Its fence at
  `admission.py:49` (`request.lease_epoch < max(r.epoch)`) becomes reachable only by legacy
  callers; the allocator guarantees monotonicity for allocated admits by construction.
  Decision: keep `admit()` (a public method with independent tests) but assert in the plan
  that S1/S3 no longer route through it.
- **S6 — `admission.py:admit_next()`** — THE shared allocator (re-landed). `epoch =
  (max(r.epoch) if records else 0) + 1`, computed under the flock.
- **S7 — `fencing.py:63`, `create()` / `fencing.py:54`, `lease()`** — bind `fence_token`
  and the fencing `idempotency_key` to `lease_epoch`. Under allocation these are invoked
  by `make_request(epoch)` with the ALLOCATED epoch (§5). No signature change required;
  the change is that the CALLER now calls them late, at the allocated epoch.

### READER seams

- **R1 — `admission.py:49`** — the fence. Sole consumer of `AdmissionRecord.epoch`.
  Unchanged in code; its behavior is what the falsifiers exercise.
- See §7 reader-audit for the two readers ruled OUT (`panel_invoker.py:540` = SeatOutcome;
  `event_log.py` = CoordinatorEvent) and the one to verify (RA-1).

---

## 5. Epoch-late-binding specification (the central, precise change)

`execute` today receives a fully-built `AdmissionRequest` with the epoch already baked in;
`admit_next` needs a `make_request(epoch)` that builds it AT the allocated epoch. Spell out
exactly which fields rebuild and which stay stable — this is the seam whose mis-threading
sinks the change.

**REBUILD at the allocated epoch** (these digests include `lease_epoch`):
- `fence_token` — `_digest((train_id, node_id, action, attempt_id, lease_epoch))`
  (`fencing.py:56`).
- fencing `AdmissionRequest.idempotency_key` — `_digest((attempt_id, lease_epoch,
  fence_token, approval_digest, expected_version_predicate, authority_domain_scope))`
  (`fencing.py:67`). It transitively depends on `fence_token`, so it moves with it.
- `AdmissionRecord.epoch` and `AdmissionRequest.lease_epoch` — the allocated value.

**STABLE across allocation** (must NOT depend on the epoch):
- `attempt_id` — deterministic, epoch-free (§6). `admit_next` dedups on it *before*
  allocation; if it encoded the epoch, a resume would be handed a fresh number every time
  and never de-dup.
- `approval_digest` — bound to roadmap/code/base/verification, not the epoch.
- **`publish_committed_branch_idempotency_key(repo, branch, head_sha)`** (`verbs.py:25`) —
  the EVIDENCE-layer key that preserves publish de-duplication. It is
  `sha256(f"{repo}\0{branch}\0{head_sha}")`, **epoch-independent**, and `execute` short-
  circuits on it at the evidence-replay layer (`verbs.py:57`) BEFORE any allocation.
  Renumbering does not break publish idempotency. **Do not touch this key.**

**Three seams must change together** or the edit is the helper-edited-but-seam-unthreaded
defect: the `execute`/`BrokerRequest` contract (S3), `_default_build_admission` (S1), and
`refresh_downstream_after_merge` (S2). Editing `admit_next` while leaving S1 stamping `1`
ships a green suite and a broken live path.

---

## 6. The one genuinely OPEN fork the ratification does NOT settle: publish `attempt_id`

`admit_next` dedups on `attempt_id`, requiring it be deterministic and epoch-free so a
resume finds its record before allocation. Publish's current `attempt_id` is
`uuid.uuid4().hex` (`fencing.py:55` default) — **random per call.** `execute` short-circuits
publish idempotency at the evidence layer (`verbs.py:57`) for COMPLETED publishes, so a
random `attempt_id` is harmless for a fresh publish. But `verbs.py:58` lets a
`PROVIDER_CALL_IN_FLIGHT` record fall THROUGH to re-admit — and with a random `attempt_id`
that retry allocates a SECOND epoch and appends a SECOND admission record for one publish,
bloating the allocator and racing a concurrent readmit.

- **Fork:** does publish adopt a deterministic epoch-free `attempt_id`, or keep the random
  one and accept duplicate admission records under in-flight retry?
- **Recommendation (adopt):** derive `publish_attempt_id =
  sha256(f"publish\0{repo}\0{branch}\0{head_sha}")`, mirroring `readmit_attempt_id`. This
  makes `admit_next` idempotent under in-flight retry: the resume finds its prior record
  before allocating.
- **Two idempotency layers the plan MUST keep distinct** (conflating them silently inverts
  the revocation semantics — see AC-6a/6b):
  - **Completed-EFFECT idempotency = evidence-replay (`execute:58`).** Fires only for a
    TERMINAL state (the branch was actually pushed). It correctly SKIPS the revocation check
    — you are reporting an accomplished external fact, not authorizing new work; you cannot
    un-push, and re-checking `epoch_blocked` here would make a resume of an already-succeeded
    publish falsely report "blocked."
  - **Admission DEDUP = `admit_next` `attempt_id` hit.** Means "authorized, effect NOT yet
    observed." It MUST be gated by revocation (the §3 reorder) — a dedup hit authorizes the
    caller to proceed, so a revoked epoch must refuse it.
  Concretely: a fresh/in-flight publish under revocation is refused at the service entry
  (`execute:64`) AND in-lock in `admit_next`; the ONLY thing that survives revocation is a
  TERMINAL replay at `:58`. Do NOT write "in-flight publish completes despite revocation" —
  that is false against this code and re-ships the parked defect.

---

## 7. Reader-audit checklist (the "who reads the shape" the retraction depends on)

- **RA-0 (ruled OUT):** `panel_invoker.py:540` `record.epoch` is a `SeatOutcomeRecord`
  (FAB namespace); `test_cli_train_status_45.py:96` / `event_log.py` `CoordinatorEvent.epoch`
  is the runtime fencing log. Neither is `AdmissionRecord.epoch`.
- **RA-1 (VERIFY during implementation, do not assume):** confirm the publish admission's
  `lease_epoch` does NOT flow into a `CoordinatorEvent(epoch=…)` that then hits the
  runtime event-log monotonic check (`event_log.py:123`, `event.epoch < latest_epoch`). If
  a live-broker publish DOES emit such an event, that check must tolerate allocated epochs
  (it already enforces monotonic-nondecreasing, so allocated `2,3,…` is fine — but a test
  pinning a publish event to `epoch==1` would break and is the falsifier anchor). Grep
  anchor: `record_intent(` / `CoordinatorEvent(` on the publish path in `train_runner.py`.

---

## 8. Acceptance criteria — each names its FALSIFIER (the mutation that makes it fail), the
injection anchor, and a positive control

> A criterion that cannot fire is the defect class this repo keeps shipping. Every AC below
> names the exact mutation that breaks it AND asserts a positive control so it is not
> vacuously green.

- **AC-1 — publish-after-readmit no longer stale-epoch-rejects (the exact round-4
  incident).** In ONE per-repo store: readmit advances the epoch to 2, then a publish
  succeeds and records epoch 3 (strictly above). **Falsifier:** revert S3 to
  `admit(request.admission)` (or S1 to `lease_epoch=1`) → the post-readmit publish raises
  `PermissionError("stale epoch")` at `admission.py:49`. **Injection anchor:** `execute`'s
  admit call (`verbs.py:65`) / `_default_build_admission` epoch. **Positive control:**
  assert the publish returns `accepted=True` with `granted_epoch == 3` — not merely "did
  not raise."

- **AC-2 — publish stays subject to revocation (the safety property Option A would have
  lost).** With `evidence_store.epoch_blocked = True`, a fresh publish (no prior in-flight
  record) is REFUSED. **Falsifier:** exempt publish from the `epoch_blocked` check (the dead
  Option-A variant) → publish is accepted after revocation. **Injection anchor:** the
  in-lock `epoch_blocked()` inside `admit_next` (S6) + `execute:64`. **Positive control:**
  with `epoch_blocked = False`, the identical publish is accepted — so the test is not
  vacuously blocking everything. **⚠️ §10 ratified SPLIT:** the simple form here PASSES on
  current `main` (`execute:64` already refuses under #366), so it is relabeled a `REGRESSION
  GUARD` (rule 7); a SEPARATE red-first test asserts the genuinely new guarantee — in-lock
  refusal inside `admit_next` under a concurrent revocation race (step-1 wave). Both.

- **AC-3 — publish idempotency survives renumbering (epoch-independent key).** Publish
  `(repo, branch, head)`; it records some epoch E. Replay the SAME publish → returns the
  SAME `PublishCommittedBranchResult` and appends NO new admission record (record count
  unchanged, no new epoch allocated). **Falsifier:** make the publish `attempt_id` or the
  evidence dedup key encode the epoch → the replay allocates E+1 and a second record
  appears. **Injection anchor:** evidence replay (`verbs.py:57`) + the §6 deterministic
  `attempt_id`. **Positive control:** a publish of a DIFFERENT `head_sha` DOES allocate a
  new epoch and append a record — so the test proves dedup, not universal no-op.

- **AC-4 — monotonic across MIXED kinds, WITHIN one repo store.** publish → readmit →
  publish → readmit against ONE per-repo store record strictly increasing epochs
  `[1,2,3,4]`. **Falsifier:** give readmit its own separate store/allocator (the "separate
  epoch domains" alternative the maintainer rejected) → the two sequences each restart at 1
  and the fence trips. **Injection anchor:** `_RoutingBrokerService._service_for` routing —
  both `execute` and `readmit_advanced_head` must resolve the SAME per-repo root
  (`live.py`). **Positive control:** all four accepted. **Scope guard:** the store is
  per-repo (see #208 global-poison memory); a SECOND repo's first admission independently
  starts at 1 — assert that too, so the plan is not mis-read as one GLOBAL allocator.

- **AC-5 — allocation is atomic (no TOCTOU).** After N appends via `admit_next` on one
  store, epochs are distinct and contiguous `1..N`; the `max+1` is computed from
  `_records()` read INSIDE the held flock. **Falsifier:** move the `max(r.epoch)+1`
  computation (or the `_records()` read) OUTSIDE the `fcntl.flock` in `admit_next` → under a
  serialized two-writer harness (patch a barrier between read and append) two admissions
  collide on one epoch. **Injection anchor:** the `flock` scope in `admit_next` (S6).
  **Positive control:** the un-mutated allocator yields `1..N` with no gap or dup.

- **AC-6a — a COMPLETED publish replays idempotently even after revocation (evidence
  layer).** A publish reaches a TERMINAL effect-observed state; a revocation then lands;
  replaying the SAME publish returns the prior `PublishCommittedBranchResult` (does NOT
  report blocked, does NOT re-push). **Falsifier:** make `_replay`/`execute:58` re-check
  `epoch_blocked` → a succeeded publish wrongly reports blocked on resume. **Injection
  anchor:** the terminal short-circuit at `execute:58` (before the `:64` revocation gate).
  **Positive control:** a DIFFERENT `head_sha` publish under the same revocation IS refused
  at `:64` — proving `:58` is a terminal-only replay, not a blanket bypass. **⚠️ §10 ratified
  REGRESSION GUARD:** this PASSES on current `main` (`:58` already precedes `:64` under #366);
  no new guarantee hides here, so it is labeled a `REGRESSION GUARD` (rule 7) naming the
  `:58`-before-`:64` ordering, not presented as a red-first test.

- **AC-6b — a revoked resume is refused IN-LOCK (the parked defect, as a live AC).** An
  admission is authorized (dedup-able by `attempt_id`) but its effect is NOT yet observed;
  a revocation lands; the resume is REFUSED — no ledger append, no merge. **Falsifier:**
  return the `attempt_id` dedup hit BEFORE the in-lock `epoch_blocked` check in `admit_next`
  (the un-reordered 288a ordering) → the revoked resume returns ACCEPTED and the caller
  merges. **Injection anchor:** the in-lock order in `admit_next` (S6, §3 reorder).
  **Positive control:** a NON-revoked resume dedups to the SAME `granted_epoch` (idempotency
  preserved) — proving the gate refuses only under revocation, not always.

> **AC-8 is split into AC-8a (normal path) and AC-8b (crash-resume path) — the two S8
> commit points. BOTH bind to the PRODUCTION SEAM, not to a direct helper call.** Driving
> `_fab_delta_readmit(broker_client=<fake>, …)` directly would test the helper in isolation
> and CANNOT catch the actual #288 defect — `broker_client` never threaded through the
> `:3084` production path (the "guard correct, never wired, suite green" class). It also
> breaks the §10 contract: a test naming the new `broker_client` param dies on `main` with a
> `TypeError` (rule-2 wrong-reason red) and must be edited by the impl PR (rule-5 violation).
> So each test sets up a revoked per-repo broker store and drives the merge-loop seam
> (`run_train` / the `:3084` caller — at minimum `_live_merge_pr`); it NEVER hands
> `broker_client` to the helper. The wiring supplies it, so an unwired path stays red.

- **AC-8a — the NORMAL-path delta re-admit is subject to revocation.** Drive the merge-loop
  seam with a valid single-commit PASS delta (so `:1139` is the append reached) against a
  revoked per-repo broker store (`evidence_store.epoch_blocked = True`): the node does NOT
  re-admit — no new admitted head, no `:1139` ledger append, the merge falls through to the
  `pr-head-advanced` guard (no merge). **Falsifier:** restore the direct `append_record` at
  `train_runner.py:1139` (the current bypass) → the seam re-admits and the advanced head
  merges despite revocation. **Injection anchor:** the `:1139` append rewrite +
  `broker_client` threading at the `:3084` call. **Wave-0 red on `main`** (the seam reaches
  `:1139`, appends, merges despite the revoked store). **Positive control (POST-IMPL,
  green-time — NOT wave-0):** with `epoch_blocked = False`, the identical seam re-admits at an
  allocated epoch and the head advances.

- **AC-8b — the CRASH-RESUME delta re-admit is subject to revocation (the second bypass
  codex found).** Pre-extend the durable provenance to the live head so it passes the gate
  (`resolved_final == live_head_sha and _gate_passes()` → the `:1016` crash-resume branch
  fires), then drive the SAME merge-loop seam against a revoked store: the node does NOT
  re-admit — no `:1016` ledger append, falls through to the guard. **Falsifier:** restore the
  direct `append_record` at `train_runner.py:1016` (the crash-resume bypass) → a revoked
  resume takes the early append and merges. **Injection anchor:** the `:1016` append
  specifically (assert `head_sha=live_head_sha` at that append in `src` before mutating, so
  the mutation cannot be a silent no-op against a moved anchor). **Wave-0 red on `main`** (the
  crash-resume path appends unconditionally today). **Positive control (POST-IMPL,
  green-time — NOT wave-0):** with `epoch_blocked = False`, the crash-resume DEDUPS to the
  SAME `granted_epoch` (idempotent resume, per §6/AC-6b) and the head advances — proving the
  gate refuses only under revocation, not that the crash-resume path is dead.

- **AC-7 — CHANGELOG/doc retraction present and self-consistent.** A repo check (grep-level
  is sufficient) asserts (a) `CHANGELOG.md` contains the byte-neutrality RETRACTION entry
  for publish, and (b) NO tracked doc asserts publish byte-neutrality *alongside*
  renumbering. **Falsifier:** leave `design-fab-integration-milestone.md` item 4 or any doc
  claiming "publish remains byte-neutral" once renumbering ships → the check fails.
  **Injection anchor:** `CHANGELOG.md` + `design-fab-integration-milestone.md`. **Positive
  control:** the check PASSES on the amended tree (so it is not an unconditional failer).

---

## 9. Documentation impact

- **`CHANGELOG.md`** — REQUIRED retraction entry: publish admission records are renumbered;
  publish no longer writes `lease_epoch=1`; byte-neutrality of the publish durable record is
  retracted and NOT gated by `PHASE_LOOP_FAB`. (Public-surface change ⇒ CI docs-freshness
  gate requires a committed CHANGELOG entry — see repo docs-audit gate.)
- **`plans/detailed-288-fab-broker-readmission-20260726.md`** — already stop-signed; add a
  one-line pointer that the replacement is THIS plan + Option B (do not resurrect it).
- **`plans/design-fab-integration-milestone.md`** — item 4 ("byte-neutral default") must be
  amended to carve out the broker publish admission epoch: FAB-OFF byte-neutrality still
  holds for FAB machinery, but the #199 publish admission record shape changes
  unconditionally. Item 3.1/3.2 (broker-admitted head bound at admission time) is satisfied
  by the allocated epoch.
- **`plans/manifest.json`** — tooling-owned (lifecycle-driven by the execute-detailed
  runner); the execution PR's runner registers this plan on `executing`. Do NOT hand-edit
  it here (a single bad entry has silently disabled all plan discovery before). The
  amendment-2 plan was never manifested on `main`, so there is no stale entry to retire.
- **The re-landed `admit_next` / readmit docstrings** carry forward from #337.

---

## 10. Test-first execution contract — NORMATIVE, not advisory

This plan is not implementable in one PR. Its acceptance criteria (§8) LAND AS FAILING
TESTS BEFORE any production change here, so the criteria are stipulated while it is still
cheap to argue their shape — not reverse-engineered to fit whatever got built. This section
is normative: an execution that writes code first violates the plan.

**No harness gate enforces this.** The falsifier-gate that would
(Consiliency/agent-harness#362) is not built. This is a PLAN-LEVEL commitment; the reviewer
is asked to enforce it at review time. Do not assume a CI check will catch a violation —
there is none.

### The contract (each rule is a review gate)

1. **Tests land FIRST, in their own PR**, before any production change in this plan. That PR
   contains ONLY test files plus the minimal scaffolding they need to import (fixtures, a
   conftest, import shims for symbols step (1) will create — nothing that implements
   behavior).
2. **Every test FAILS when it lands, for its named reason.** The test PR records, per test:
   the AC it proves, the observed failure output, and why that failure is the RIGHT failure
   — the asserted behavior is wrong, NOT an import error, a typo, or a missing fixture. A
   test that passes on arrival proves nothing about work not yet done and is rejected.
3. **Each falsifier from §8 is RUN, with its injection anchor asserted.** Not "a mutation
   was identified" — the mutation is applied to the tree, `assert <anchor> in <source>`
   confirms the anchor matched (a mutation against a moved/renamed anchor is a silent no-op
   — the defect class this repo has already shipped), the test is observed to die, and the
   source is restored. An unapplied mutation is indistinguishable from a passing one.
4. **The test PR is REVIEWED BY THE PANEL BEFORE implementation begins.** The review
   question is "are these the right tests and the right falsifiers," decided while argument
   is cheap — not "does this code work," discovered after the code exists. This is the whole
   point of the exercise.
5. **The implementation PR MUST NOT modify the landed tests.** Any diff touching a landed
   test file is a BLOCKING review item requiring explicit written justification. If a test
   was wrong, that is a finding against the test PR and its review — reopened there, not
   quietly patched to green. Without this rule TDD is theatre.
6. **`pytest -k <new tests>` goes red→green across exactly TWO commits** per lane: the test
   commit (red) and the implementation commit (green). The execution PR states which two.
7. **Rule 2 governs tests for NEW behavior. A test that proves EXISTING behavior stays fixed
   is a different, legitimate category: a REGRESSION GUARD — green on arrival, rule-2 exempt
   BY LABEL.** The exemption is by explicit labelling, NEVER by silence: a regression guard
   must carry the `REGRESSION GUARD` label and name exactly what existing behavior it guards
   (e.g. #366's `execute:64` fresh-publish refusal, or the `execute:58`-before-`:64`
   terminal-replay ordering). **An unlabelled green-on-arrival test remains a rule-2
   violation** — the failure mode rule 2 prevents is a test shaped to fit code that already
   exists, and a regression guard is openly that by design, which is fine only because it is
   declared. When existing behavior is being guarded AND the same AC also asserts a genuinely
   NEW guarantee, the new guarantee gets its OWN red-first test ALONGSIDE the regression guard
   — both, not either.

### The general rule (generalizes past this plan)

**Test-first is per implementation STEP, not per plan.** A step's tests land and go red
before that step's code; a falsifier that mutates a not-yet-existing symbol belongs to that
symbol's step, not to an earlier wave. Rules 2 (red on arrival) and 3 (falsifier = applied
mutation) are different lifecycle moments and coincide only where the current tree already
embodies the mutation.

### Pilot status (why this section exists as prose, not a gate)

This contract is a **PILOT**: no harness gate enforces it yet (Consiliency/agent-harness#362
is the falsifier-gate that would). It is here because the discipline has just paid off
elsewhere — the ratification review of `Consiliency/spec` PR #102 found that the conformance
validator REJECTS the canonical corpus, a defect invisible for as long as it was because
every test ran against fixtures we authored ourselves rather than the corpus
(Consiliency/agent-harness#371). Self-authored fixtures that never exercise the real artifact
are the same vacuity rule 3 targets.

### Applied to THIS plan's step ordering (§11)

Test-first is applied PER STEP, because §11 carries an internal dependency: the falsifiers
for the allocator primitive MUTATE code (`admit_next`, `readmit_advanced_head`, routing)
that step (1) creates, and a falsifier cannot be RUN against code that does not yet exist.
Rules 2 (red on arrival) and 3 (falsifier = applied mutation) are different lifecycle
moments: they coincide only where `main` already embodies the mutation. So the tests split
into two waves.

**Wave-0 test PR — red against current `main`, no new production code required.** The
falsifier here IS the status quo, so the test is red on arrival with zero behavior
scaffolding. The two the directive prioritizes both live here:

- **AC-8a + AC-8b (readmit-consumer bypass, BOTH commit points) — highest-value test-first
  items, wave-0.** Current `_fab_delta_readmit` appends directly at `:1139` (normal) AND
  `:1016` (crash-resume), ignoring the broker; driven at the merge-loop seam against a
  revoked per-repo store it STILL appends and the advanced head merges. Each test reproduces
  the #288 defect on its path and is RED on `main`. They MUST exist and fail before any
  allocator or publish work, so neither bypass can be introduced by ordering accident
  (flipping `_FAB_DELTA_BROKER_READMIT_READY` while either append is still direct). Falsifier
  = the current direct append at that specific line = the tree as it stands. **Bound at the
  PRODUCTION SEAM, never a direct helper call (§8 preamble); the POSITIVE controls
  (non-revoked advances; 8b dedups to the same epoch) are POST-IMPL green-time, not wave-0
  red.**
- **AC-1 (round-4 stale-epoch incident) — red on arrival, but VIA A SEEDED RECORD, not the
  literal sequence.** ⚠️ The reproduction "publish A → readmit A → publish B" is NOT
  buildable on `main`: `readmit_advanced_head` is re-landed by step (1) and is absent, and
  the on-`main` `_fab_delta_readmit` appends to the ledger — not the broker admission store
  (that is the S8 bypass) — so **nothing on `main` advances the broker admission epoch via
  readmit**, and the literal sequence cannot trip the fence pre-allocator. The wave-0 test
  instead SEEDS a broker record at epoch 2 directly via `admit()` (legal on an empty store —
  the fence is `if records and …`), then drives the live publish path (S1/S3) at
  `lease_epoch=1` → `admission.py:49` raises `1 < 2`. Red on `main`; post-fix, publish
  allocates epoch 3 and succeeds. Falsifier = the status quo (`lease_epoch=1` at S1).
  (agent-harness#363 is NOT wrong — it records the round-4 reproduction as it occurred on
  #337's branch, where `readmit_advanced_head` existed; only the mapping onto `main` needs
  this seed.)
- **AC-7 (doc retraction) — red on arrival.** The byte-neutrality claim is still in the
  tree and the CHANGELOG retraction is absent, so the grep-level check fails today.

**Step-1 test PR — red against the step-1 skeleton.** AC-3, AC-4, AC-5, AC-6b (and the
in-lock half of AC-2) mutate `admit_next` / `readmit_advanced_head` / routing, which step
(1) re-lands. Their falsifiers can only be RUN once those symbols exist, so these tests land
red against a step-1 skeleton (symbols present, bodies unimplemented or deliberately wrong)
— NOT against empty `main`. This is still test-first — it is the primitive's own red→green —
but it is a SEPARATE wave. The plan must not pretend AC-5's "move `max+1` outside the flock"
mutation, or AC-6b's "return the dedup hit before `epoch_blocked`," can run before
`admit_next` exists.

### Criteria in §8 that need rework or relabeling under this contract

Applying rule 2 surfaces two that do NOT fail on arrival, because #366 already shipped the
behavior they assert. **Resolution RATIFIED (team-lead): relabel per rule 7, do NOT exempt
silently** — and where a new guarantee hides inside the same AC, add its own red-first test
alongside the guard.

- **AC-2 (fresh publish refused under revocation) — PASSES on arrival → split.** `execute:64`
  already raises under `epoch_blocked` (merged #366), so a fresh publish is already refused
  today. Resolution: **(a)** relabel the on-arrival assertion a `REGRESSION GUARD` naming
  #366's `execute:64` refusal (rule-7 exempt), AND **(b)** add a SEPARATE red-first test for
  the genuinely new guarantee — refusal IN-LOCK inside `admit_next` under a concurrent
  revocation race — which is absent today and lands in the step-1 wave. Both, not either.
- **AC-6a (completed publish replays after revocation) — PASSES on arrival → REGRESSION
  GUARD.** `execute:58` terminal replay already precedes the `:64` revocation gate (#366
  ordering), so a completed publish already replays without reporting blocked. There is no
  new guarantee hiding here; relabel it a `REGRESSION GUARD` naming the `:58`-before-`:64`
  ordering. It is legitimately green from the start.

Everything else in §8 fails on arrival for its named reason (AC-1/AC-7/AC-8a/AC-8b against `main`
per wave-0 above; AC-3/AC-4/AC-5/AC-6b against the step-1 skeleton) and satisfies the
contract.

---

## 11. Ordering and what blocks what

1. **Re-land the allocator + readmit primitive** (`admit_next`, `AdmissionPrecondition`,
   `readmit_advanced_head`, `readmit_attempt_id`, `ReadmitResult`, routing) from #337.
   Blocks everything. (#366's shared-lock is already in main under it.)
2. **Migrate publish to the allocator** — S1 + S2 + S3 + §5 epoch-late-binding + §6
   `attempt_id`. Depends on (1). **This is the live-#199 risk; it gets AC-1..AC-3, AC-6a/6b and
   a byte-diff review against a live-broker fixture.**
3. **Docs/CHANGELOG retraction** (§9) — lands WITH (2); AC-7 gates it.
4. **Wire the readmit CONSUMER** (S8) — replace BOTH direct `append_record` sites
   (`:1016` crash-resume + `:1139` normal) with the single `_commit_readmission` →
   `broker_client.readmit_advanced_head` path, and thread `broker_client` through
   `run_train → merge loop (`:3084`) → _fab_delta_readmit`. Depends on (1). This is the
   "multi-day protocol integration" of #288 and the actual gap the flag guards. **AC-8a AND
   AC-8b gate it** (one per commit point).
5. **Flip `_FAB_DELTA_BROKER_READMIT_READY = True`** in `governed_premerge.py:76` — LAST,
   as its own gated step per the #288 landing-checklist interlock. **Depends on (4)** — NOT
   on (1)+(2) — because the gap the flag guards is closed by the CONSUMER wiring, not by
   re-landing the primitive. Flipping the flag while `_fab_delta_readmit` still appends
   directly would ACTIVATE the exact bypass #288 exists to fix. Until this flip, the
   delta-shortcut ENGAGE path is fenced OFF by construction and the gap is unreachable.

Blocks: (2)→(1); (4)→(1); (5)→(4). Publish migration (2) and consumer wiring (4) both
sequence before the flip (5) so no ENGAGE path can reach a half-migrated allocator or a
still-bypassing consumer. (2) and (4) are independent and may land in either order; both
build on the re-landed primitive (1).

---

## 12. Scope statement + what is explicitly NOT in scope (do not over-build)

**In scope (the full #288 arc):** this is the migration plan for #288, so it covers the
allocator foundation (1), the publish migration (2) — the LIVE-#199 risk the ratification
is about — the docs retraction (3), the readmit CONSUMER wiring (4, S8/AC-8a/AC-8b — BOTH
commit points `:1016`+`:1139` via one gated path) — the seam #288 exists to fix — and the
gated flag flip (5). The flag flip is NOT a safe terminal step
until the consumer is wired; that dependency is fixed in §11. The consumer wiring is
"multi-day protocol integration" per #288's body — specified here at the seam/falsifier
level, implemented by the execution PR.

**Explicitly NOT in scope:**

- **No data migration.** Maintainer confirmed (issue #363) a whole-machine search found
  broker state only as ephemeral `/tmp` scratch (3 files, 1 record each, from a test run);
  this is the primary dev machine and other losses are trivial. Old records carry epoch 1
  and sit below a new counter without conflicting. One sentence, no migration section, no
  backfill tooling.
- **No `refresh_downstream_after_merge` production wiring.** It has no production caller;
  migrate its signature for consistency (S2) but do not invent a call site.
- **No new `RatificationPolicy`** — it already ships.
- **No touching the FAB review-round epoch or the seat-outcome epoch** (§2). A sweep that
  renumbers `epoch=1` in `tests/test_fab_*.py` is the wrong sweep.
