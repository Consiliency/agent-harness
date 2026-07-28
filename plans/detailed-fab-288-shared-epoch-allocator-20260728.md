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
  Today (verified on `main`): the delta re-admit does a **direct**
  `append_record(ledger_path, LedgerRecord(...), durable=True)` (the "re-admission COMMIT
  POINT") and takes `ledger_path`, **NOT a `broker_client`**. The call site
  (`train_runner.py:3084`) passes no broker. So the delta re-admit **bypasses broker
  lease/epoch/revocation entirely** — a node whose lease was revoked mid-run can still
  delta-re-admit and merge. Re-landing S4 makes the primitive EXIST; it does not make S8
  CALL it. **Change:** replace the direct `append_record` with a call to
  `broker_client.readmit_advanced_head(...)` (which allocates via `admit_next` and
  fail-closes on `epoch_blocked`), then append the ledger record only on an accepted
  `ReadmitResult`. This requires **threading `broker_client` through the production spawn
  path** — `run_train → merge loop → _fab_delta_readmit` — the multi-site plumbing #288's
  body calls "multi-day protocol integration." Threading anchors: the `CoordinatorRuntime`
  already carries `broker_client` (`train_runner.py:100`); it must reach the merge loop's
  call site (`:3084`) and be added to `_fab_delta_readmit`'s signature. When
  `broker_client is None`, fail CLOSED (fall through to the unchanged `pr-head-advanced`
  guard), never fall back to the direct append.

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
  vacuously blocking everything.

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
  at `:64` — proving `:58` is a terminal-only replay, not a blanket bypass.

- **AC-6b — a revoked resume is refused IN-LOCK (the parked defect, as a live AC).** An
  admission is authorized (dedup-able by `attempt_id`) but its effect is NOT yet observed;
  a revocation lands; the resume is REFUSED — no ledger append, no merge. **Falsifier:**
  return the `attempt_id` dedup hit BEFORE the in-lock `epoch_blocked` check in `admit_next`
  (the un-reordered 288a ordering) → the revoked resume returns ACCEPTED and the caller
  merges. **Injection anchor:** the in-lock order in `admit_next` (S6, §3 reorder).
  **Positive control:** a NON-revoked resume dedups to the SAME `granted_epoch` (idempotency
  preserved) — proving the gate refuses only under revocation, not always.

- **AC-8 — the delta re-admit is subject to revocation (the #288 bug reproducer, readmit
  half).** With the broker lease revoked (`evidence_store.epoch_blocked = True`),
  `_fab_delta_readmit` (S8) fails CLOSED — it does NOT append a re-admission ledger record
  and returns `None` (caller falls through to the `pr-head-advanced` guard, no merge).
  **Falsifier:** leave the current direct `append_record` in place (the bypass) → the
  re-admit succeeds and the advanced head merges despite revocation — the exact #288 defect
  reproduces. **Injection anchor:** the `append_record` → `broker_client.readmit_advanced_head`
  rewrite at `train_runner.py` (S8) + `broker_client` threading through the merge loop
  (`:3084`). **Positive control:** with `epoch_blocked = False` and a valid single-commit
  PASS delta, the re-admit IS admitted at an allocated epoch and the head advances — so the
  test proves the gate fires on revocation, not that the shortcut is dead.

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

## 10. Ordering and what blocks what

1. **Re-land the allocator + readmit primitive** (`admit_next`, `AdmissionPrecondition`,
   `readmit_advanced_head`, `readmit_attempt_id`, `ReadmitResult`, routing) from #337.
   Blocks everything. (#366's shared-lock is already in main under it.)
2. **Migrate publish to the allocator** — S1 + S2 + S3 + §5 epoch-late-binding + §6
   `attempt_id`. Depends on (1). **This is the live-#199 risk; it gets AC-1..AC-3, AC-6a/6b and
   a byte-diff review against a live-broker fixture.**
3. **Docs/CHANGELOG retraction** (§9) — lands WITH (2); AC-7 gates it.
4. **Wire the readmit CONSUMER** (S8) — rewrite `_fab_delta_readmit`'s direct
   `append_record` to `broker_client.readmit_advanced_head`, and thread `broker_client`
   through `run_train → merge loop → _fab_delta_readmit`. Depends on (1). This is the
   "multi-day protocol integration" of #288 and the actual gap the flag guards. AC-8 gates
   it.
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

## 11. Scope statement + what is explicitly NOT in scope (do not over-build)

**In scope (the full #288 arc):** this is the migration plan for #288, so it covers the
allocator foundation (1), the publish migration (2) — the LIVE-#199 risk the ratification
is about — the docs retraction (3), the readmit CONSUMER wiring (4, S8/AC-8) — the seam
#288 exists to fix — and the gated flag flip (5). The flag flip is NOT a safe terminal step
until the consumer is wired; that dependency is fixed in §10. The consumer wiring is
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
