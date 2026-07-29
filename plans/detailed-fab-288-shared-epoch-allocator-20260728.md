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
  computes `epoch = max(existing)+1` INSIDE the flock, then calls
  `make_request(epoch, attempt_id)` to build the request at the allocated epoch, THREADING
  its own `attempt_id` argument into the factory (round-2 CR, grok — see the "attempt_id
  locus" paragraph below; the 288a `make_request(epoch)` signature is a self-contradiction
  that ships broken idempotency). **This is a RE-LAND, not a signature change on a shipped
  API:** `admit_next`/`make_request` do not exist on `main` (they come from `c1da62a`), so
  `make_request(epoch, attempt_id)` costs ZERO migration — there is no caller to update — and
  the same two-arg shape is used by BOTH the publish and readmit builders.
  **RE-LAND WITH A CORRECTED IN-LOCK ORDER — do NOT port unchanged.** The 288a diff
  (@ `c1da62a`) returns the `attempt_id` dedup hit BEFORE its in-lock `epoch_blocked()`
  check — the exact ordering the parked-conflict record flags as a defect ("revocation must
  precede dedup"): a revoked resume returns its prior record as ACCEPTED and the caller
  proceeds to merge. The required in-lock order is:
  **`epoch_blocked` → `attempt_id` dedup (rebuild `make_request(prior.epoch, attempt_id)` +
  conflict-compare on a hit — see below) → `precondition` → allocate `max+1` → build
  `make_request(epoch, attempt_id)` → ENFORCE `request.lease_epoch == epoch` AND
  `request.attempt_id == attempt_id` → `policy` → append.** Rationale: readmit has NO evidence-terminal replay (decoupled admit, no
  provider adapter), so ALL readmit idempotency lives at this admission-dedup layer; gating
  dedup behind `epoch_blocked` refuses a revoked resume (no double-merge — the ledger record
  + `--match-head-commit` pinning already prevent that) while still deduping a NON-revoked
  resume. This also closes the #366 race on the dedup path (a revocation landing after an
  outside-lock entry check but before the in-lock body is only caught if in-lock
  `epoch_blocked` precedes the dedup return).
  **ADDITIONALLY — restore the conflict-compare the 288a `admit_next` DROPPED (round-1 CR,
  grok — verified @ `c1da62a`).** Its `attempt_id` dedup does `return record` with NO rebuild
  and NO compare, whereas legacy `admit()` (`admission.py:47`) raises
  `ValueError("conflicting idempotency key")` when `record.request != request`. Ported
  unchanged, a resume presenting the SAME `attempt_id` but a DIFFERENT
  authority/approval/predicate is returned ACCEPTED — and under S8 "accepted" means
  "authorized to append the ledger and merge." So on the dedup hit, AFTER `epoch_blocked`,
  the re-land MUST rebuild `make_request(prior.epoch, attempt_id)` and require field equality (raising a
  field-wise conflict otherwise), matching `admit()`'s semantics. This guard is reachable
  ONLY under §6's DETERMINISTIC `attempt_id`: with the random `uuid4`, dedup never fires and
  the compare is dead code — so BLOCKING-2 REINFORCES the §6 recommendation. Falsifier + AC:
  AC-9 (§8).
  **ENFORCE THE ALLOCATED EPOCH — `admit_next` must not TRUST the factory (round-2 CR, codex
  — verified).** `admit_next` records `AdmissionRecord(epoch=max+1)` but the epoch inside the
  `request` is whatever `make_request` built. A factory that ignores its `epoch` argument and
  hardcodes `lease_epoch=1` yields a record with `epoch=3` and `request.lease_epoch=1`, and
  NOTHING rejects the divergence: `admit_next` deliberately does NOT carry `admit()`'s
  `lease_epoch < max` fence (sibling-diff table), and that fence would not even catch it (at
  `allocated==2`, `max==1`, so `1 < 1` is false). `AdmissionRequest` is FROZEN
  (`contracts.py:18`) so the epoch cannot be fixed up after building. Therefore, on the
  allocate path, AFTER `request = make_request(epoch, attempt_id)`, `admit_next` MUST assert
  BOTH `request.lease_epoch == epoch` AND `request.attempt_id == attempt_id`, raising
  `ValueError` otherwise; and on the dedup-rebuild path assert `rebuilt.lease_epoch ==
  prior.epoch` AND `rebuilt.attempt_id == attempt_id` before comparing (belt-and-suspenders —
  the conflict-compare already catches a divergent `lease_epoch` because it makes
  `rebuilt != prior.request`, but the explicit check gives a precise error and states the
  invariant). The LOAD-BEARING check is on the allocate path. Without it, "the broker
  allocates the epoch, the caller never chooses it" is UNVERIFIED — and AC-1's naive
  "S1 hardcodes `lease_epoch=1`" falsifier does not fire (silent-accept, not stale-epoch);
  that mutation is relocated to its own AC-10 (§8), and AC-1's falsifier is fixed to the
  `admit()`-revert form that raises via the legacy fence.
  **ENFORCE THE DEDUP IDENTITY TOO — `admit_next` must not TRUST the factory to honor the
  supplied `attempt_id` (round-3 CR, codex+grok — the SAME class as the epoch enforcement
  above, one field over).** The dedup identity is what makes idempotency work, and it is
  currently TRUSTED, not ENFORCED: nothing requires the built `request.attempt_id` to equal the
  `attempt_id` argument `admit_next` dedups on. A factory that ignores the supplied id — e.g.
  the round-2 S1 defect, leaving `factory.lease()` to default `attempt_id` to `uuid4`
  (`fencing.py:54`) — appends a record keyed by a random id NO future retry can reproduce, so
  every in-flight resume re-allocates and AC-9's conflict-compare is dead code again (the exact
  defect the round-2 locus decision was meant to close, resurfacing because that decision had
  not reached S1). Hence the `request.attempt_id == attempt_id` assertion on BOTH paths above,
  parallel to the epoch check. Falsifier + AC: **AC-11** (§8) is the UNIT enforcement (the
  stored id IS the supplied id); it is DISTINCT from AC-9 (a CONFLICTING resume) and from
  **AC-12** (the behavioral in-flight retry driven through the live S1 seam, which AC-3 cannot
  reach — see §8).
  **attempt_id LOCUS — resolve the self-contradiction (round-2 CR, grok — verified).** Three
  requirements could not all hold as first written: (i) S1 returns `make_request(epoch)` and
  must NOT bind the §6 `attempt_id`; (ii) §6/S3 computes `attempt_id =
  sha256(publish‖repo‖branch‖head_sha)` from the POST-COMMIT head, inside `execute`; (iii)
  `admit_next` dedups on `attempt_id` and the rebuild reconstructs the request. If
  `make_request` took epoch ALONE, `fencing.lease()` would fall back to `uuid.uuid4().hex`
  (`fencing.py:54`), so the STORED request carries a random `attempt_id` that never equals the
  deterministic `attempt_id` argument `admit_next` dedups on — **publish idempotency silently
  broken, every resume re-allocates.** **DECISION: `make_request(epoch, attempt_id)`;**
  `execute` computes the deterministic `attempt_id` once (from the post-commit
  `BrokerRequest.head_sha`) and passes it as `admit_next`'s `attempt_id` argument, which
  `admit_next` threads into `make_request` on BOTH the allocate and rebuild calls. S1 still
  does not COMPUTE the `attempt_id` (it runs pre-commit); it RECEIVES it as a parameter — so
  requirement (i) holds as "S1 must not bind it," not "make_request must not see it."
  `attempt_id` folds into `fence_token` and `idempotency_key` (`fencing.py:56/67`), so a
  deterministic input makes the rebuilt request byte-identical to the stored one ON THE
  `attempt_id` AXIS and the AC-9 compare exact — **but byte-identity also requires the
  `approval_digest` axis to be commit-stable; across a crash it is NOT, absent §5b's fix
  (round-4 codex). This clause is necessary but not sufficient on its own; see §5b + AC-13.**
  **Why the alternative (rebuild reads `attempt_id` from the stored prior
  record) is WRONG:** the ALLOCATE path must STORE a request whose `attempt_id` equals the
  deterministic dedup argument, or no future resume ever finds it; `make_request` needs
  `attempt_id` on the allocate path regardless, so reading-from-stored only patches the
  compare and leaves storage carrying `uuid4` — idempotency stays broken. **Head-stability
  assumption (state it, do not leave silent):** `attempt_id` is stable across an in-flight
  retry only because the commit has already happened and HEAD does not move on resume;
  a COMPLETED publish short-circuits earlier at the evidence layer (`execute:58`) and never
  reaches allocation at all.
- `AdmissionPrecondition = Callable[[tuple[AdmissionRecord, ...]], str | None]` — an
  in-lock gate over the durable log (used by readmit's baseline check; publish supplies
  none).
- `readmit_advanced_head(...) -> ReadmitResult`, `readmit_attempt_id(node_id, new_head_sha)`
  — the FAB readmit half (already uses `admit_next`).
- `_RoutingBrokerService.readmit_advanced_head` — routes on the SAME per-repo key as
  `execute`.

Do NOT re-invent these; port them from `origin/feat/288a-broker-readmit-primitive`
(@ `c1da62a`) unchanged except where §4/§5 below extend them to publish.

### Sibling-diff discipline (re-landing a function that has an existing sibling)

**Rule (generalizes past this plan): when re-landing a function that is a SIBLING of an
existing one, DIFF the two for DROPPED checks and ENUMERATE what you deliberately did NOT
port — a silent omission is the second guard-drop this one plan would otherwise have shipped
(the `epoch_blocked` ordering was the first).** Performed here for `admit()` vs `admit_next`
(@ `c1da62a`):

| Check in `admit()` | In `admit_next`? | Disposition |
|---|---|---|
| conflict-compare on a dedup hit (`record.request != request → ValueError`) | **DROPPED** | **MUST RESTORE** — BLOCKING-2 (round-1); AC-9 |
| explicit fence `lease_epoch < max(epoch)` (`admission.py:49`) | absent | **DELIBERATE NON-PORT for MONOTONICITY** — allocation is `max+1` in-lock, so "strictly above" holds by construction. **But it does NOT bind `record.epoch` to `request.lease_epoch`** — see the ADD below; the `<` fence is also insufficient for that (misses `allocated==2`) |
| `record.epoch == request.lease_epoch` equality (NOT in `admit()` either — a NEW guard) | **ADD** | **NEW, load-bearing** — `admit_next` allocates the epoch but trusts the frozen `request` to carry it; enforce on the allocate path (and rebuild). Beyond a straight port. BLOCKING (round-2, codex); AC-10 |
| `record.request.attempt_id == attempt_id` (the supplied dedup id; NOT in `admit()` — a NEW guard) | **ADD** | **NEW, load-bearing** — `admit_next` dedups on `attempt_id` but trusts the frozen `request` to carry it; a factory defaulting `lease()` to `uuid4` stores an unfindable record → idempotency silently broken, AC-9 compare dead. Enforce on allocate + rebuild, parallel to the epoch guard. BLOCKING (round-3, codex+grok); AC-11 |
| `epoch_blocked` position (FIRST in `admit`, LAST in `admit_next`) | reordered | **already fixed** by the §3 in-lock reorder above |

Applied to the OTHER re-land, `readmit_advanced_head`: it and `execute`'s publish admit both
now route through the SAME `admit_next` body (one dedup/compare/fence path), so there is no
sibling-specific guard for it to drop — **checked, nothing dropped.** (The "assume a third
until you have enumerated exhaustively" directive applies to the guard-drop class too, not
only to the append-site class of §4.)

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
  `make_request(epoch: int, attempt_id: str) -> AdmissionRequest` closure that rebuilds the
  lease + request at the epoch the broker allocates AND the `attempt_id` the broker threads in
  (see §5; the two-arg form is FORCED by the §3 round-2 locus resolution — the one-arg
  `make_request(epoch)` is the self-contradiction that ships broken idempotency). Nothing here
  may hardcode `1`. **The `attempt_id` is a PARAMETER this closure RECEIVES; it must NOT COMPUTE
  it from a HEAD.** S1 runs PRE-commit on the non-prebuilt path (the commit is in
  `publishing.py`, S3b), so a pre-commit HEAD could not yield the right id anyway — `execute`
  computes the deterministic `attempt_id` downstream from the post-commit `BrokerRequest.head_sha`
  (§6) and `admit_next` forwards it in as this closure's `attempt_id` argument. **MECHANISM (the
  actual fix, of which the signature is only the shape):** the closure threads its received
  `attempt_id` into `factory.lease(..., attempt_id=attempt_id)` so `lease()` never defaults it to
  `uuid4` (`fencing.py:54`); a closure that takes epoch ALONE leaves the stored request carrying a
  random id that never equals the deterministic dedup key `admit_next` matches on — publish
  idempotency silently broken (round-3 CR, codex+grok: the round-2 two-arg decision had been
  applied to §3/§5/§6/S3 but NOT to this normative S1 text an implementer follows).

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
  attempt_id=<publish attempt_id, §6>)` where `make_request` has signature
  `make_request(epoch, attempt_id)` (§3 round-2 locus resolution). `execute` computes the
  deterministic `attempt_id` ONCE and passes it as `admit_next`'s `attempt_id` argument;
  `admit_next` threads it into `make_request` on the allocate and rebuild calls. The
  `BrokerRequest`/`execute` contract must carry a `make_request` factory (or the fields to
  build one) instead of a pre-epoched `AdmissionRequest`. The in-lock `epoch_blocked` re-check
  inside `admit_next` preserves the #366 revocation guarantee; keep the pre-check at
  `verbs.py:64` too (fail-fast). `admit_next` ENFORCES `request.lease_epoch == epoch` AND
  `request.attempt_id == attempt_id` (§3), so a `make_request` that ignores EITHER supplied
  argument fails loud rather than storing a divergent record.
  **attempt_id LOCUS (round-1 + round-2 CR, grok — verified):** the §6 `publish_attempt_id =
  sha256(publish‖repo‖branch‖head_sha)` is computed HERE, inside `execute`, from
  `BrokerRequest.head_sha` — the POST-COMMIT head — NOT baked in S1, which runs BEFORE the
  commit on the non-prebuilt path (S1 at `train_runner.py:2696`, commit at `publishing.py:179`,
  head captured `:188`, `execute` at `:196`). Binding `attempt_id` from a pre-commit HEAD
  would key a resume off a head that changes after commit, so dedup would never fire (and the
  §3 / AC-9 conflict-compare would be dead code). Because `make_request` now RECEIVES the
  `attempt_id` (round-2), the built request carries the deterministic value rather than
  `fencing.lease()`'s `uuid4` default — this is what actually makes dedup fire; the round-1
  wording "computed HERE" is necessary but was NOT sufficient without threading it into the
  factory.

- **S3b — `publishing.py:196`, `publish_committed_branch` → `broker_client.execute(...)`**
  *(the live #199 CALL site of S3 — previously unlisted, round-1 CR, grok).* This is where
  the `BrokerRequest` is constructed with the POST-COMMIT `head_sha` (captured at
  `publishing.py:188`, "immediately after commit") and `execute` is invoked. It stamps no
  epoch (S3 allocates), but it is the seam that SUPPLIES the post-commit `head_sha` the §6
  `attempt_id` binds to — enumerated so a reviewer sees the pre-commit (S1) vs post-commit
  (here) boundary. The prebuilt path (`publishing.py:157`) already has HEAD = the prebuilt
  commit, so its head_sha is stable across S1.

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
  (max(r.epoch) if records else 0) + 1`, computed under the flock; builds via
  `make_request(epoch, attempt_id)` and ENFORCES BOTH `request.lease_epoch == epoch` AND
  `request.attempt_id == attempt_id` before append (§3, codex round-2 + round-3).
- **S7 — `fencing.py:63`, `create()` / `fencing.py:54`, `lease()`** — bind `fence_token`
  and the fencing `idempotency_key` to `lease_epoch` AND `attempt_id`. Under allocation these
  are invoked by `make_request(epoch, attempt_id)` with the ALLOCATED epoch and the
  DETERMINISTIC `attempt_id` (§5/§6). `lease()`'s `attempt_id` arg MUST be supplied (never
  defaulted to `uuid4`, `fencing.py:54`). No `fencing` signature change — `lease()` already
  accepts `attempt_id`; the change is that the CALLER now calls late, at the allocated epoch,
  passing the deterministic id.

### READER seams

- **R1 — `admission.py:49`** — the fence. Sole consumer of `AdmissionRecord.epoch`.
  Unchanged in code; its behavior is what the falsifiers exercise.
- See §7 reader-audit for the two readers ruled OUT (`panel_invoker.py:540` = SeatOutcome;
  `event_log.py` = CoordinatorEvent) and the one to verify (RA-1).

---

## 5. Epoch-late-binding specification (the central, precise change)

`execute` today receives a fully-built `AdmissionRequest` with the epoch already baked in;
`admit_next` needs a `make_request(epoch, attempt_id)` that builds it AT the allocated epoch
(the two-arg signature is forced by the round-2 locus resolution in §3 — `attempt_id` is an
INPUT so the stored request and the rebuild both carry the deterministic value). Spell out
exactly which fields rebuild and which stay stable — this is the seam whose mis-threading
sinks the change. `admit_next` additionally ENFORCES `request.lease_epoch == epoch` after the
build (§3, codex round-2 + round-3), so a factory that ignores its epoch OR its supplied
`attempt_id` cannot silently store a divergent record.

**REBUILD at the allocated epoch** (these digests include `lease_epoch`):
- `fence_token` — `_digest((train_id, node_id, action, attempt_id, lease_epoch))`
  (`fencing.py:56`).
- fencing `AdmissionRequest.idempotency_key` — `_digest((attempt_id, lease_epoch,
  fence_token, approval_digest, expected_version_predicate, authority_domain_scope))`
  (`fencing.py:67`). It transitively depends on `fence_token`, so it moves with it.
- `AdmissionRecord.epoch` and `AdmissionRequest.lease_epoch` — the allocated value.

**STABLE across allocation** (must NOT depend on the epoch):
- `attempt_id` — deterministic, epoch-free (§6), computed once in `execute` and passed AS AN
  ARGUMENT to `make_request(epoch, attempt_id)` (not recomputed per call). `admit_next` dedups
  on it *before* allocation; if it encoded the epoch, a resume would be handed a fresh number
  every time and never de-dup. Because it is an argument (not defaulted inside
  `fencing.lease()` to `uuid4`), the rebuilt request is byte-identical to the stored one on the
  `attempt_id` axis and the AC-9 conflict-compare is exact **on that axis — the `approval_digest`
  axis additionally requires §5b's commit-stable identity (round-4), else a post-crash rebuild
  diverges and AC-9 wrongly rejects a faithful retry (AC-13).**
- `approval_digest` — epoch-INDEPENDENT (does not move with allocation). **⚠️ But NOT
  automatically retry-STABLE — see the commit-stability requirement below (round-4 codex,
  verified). It is stable across the *epoch* axis, which is all §5's rebuild/stable split
  concerns; retry-stability is a SEPARATE axis the round-2 conflict-compare made load-bearing.**
- **`publish_committed_branch_idempotency_key(repo, branch, head_sha)`** (`verbs.py:25`) —
  the EVIDENCE-layer key that preserves publish de-duplication. It is
  `sha256(f"{repo}\0{branch}\0{head_sha}")`, **epoch-independent**, and `execute` short-
  circuits on it at the evidence-replay layer (`verbs.py:57`) BEFORE any allocation.
  Renumbering does not break publish idempotency. **Do not touch this key.**

**Three seams must change together** or the edit is the helper-edited-but-seam-unthreaded
defect: the `execute`/`BrokerRequest` contract (S3), `_default_build_admission` (S1), and
`refresh_downstream_after_merge` (S2). Editing `admit_next` while leaving S1 stamping `1`
ships a green suite and a broken live path.

### 5b. Commit-stable approval identity — the round-2 conflict-compare needs it (round-4 codex, verified)

**The defect (verified in source).** `approval_digest = compute_approval_digest(…, base_sha, …)`
digests over `base_sha` (`fencing.py:37-40`), and `create()` folds `approval_digest` into the
frozen `AdmissionRequest.idempotency_key` (`fencing.py:67-68`). S1 sets `base_sha` from
`rev-parse HEAD` at S1-build time (`train_runner.py:119`). On the non-prebuilt path S1 runs
PRE-commit, so `base_sha = H0` (the base). **On a CRASH retry the runtime re-runs S1 from
scratch, but the publish commit already landed, so `rev-parse HEAD = H1` and `base_sha = H1 ≠
H0`.** The `attempt_id` still matches (deterministic on the post-commit `head_sha`), so the
resume DEDUP-HITS — and then the round-2 conflict-compare rebuilds a request carrying
`approval_digest(H1)`, compares it to the stored `approval_digest(H0)`, finds them different,
and **RAISES `ValueError("conflicting idempotency key")` on a LEGITIMATE retry.** The round-2
fix (AC-9) created this round-4 failure. The plan's earlier "byte-identical rebuild" claim
(§3/§6) does NOT hold for publish across the crash boundary.

**Resolution — (b) the approval identity must be COMMIT-STABLE. State the invariant, not a
one-line mechanism.** The rejected alternatives and why:
- **(a) exclude HEAD-derived fields from the compare — WRONG.** `attempt_id` pins
  `(repo, branch, head_sha)`, but `roadmap_digest`, the owned-code subset (`effective_code`),
  and `verification_*` can differ at the SAME head; dropping `approval_digest` from the compare
  reopens exactly the hole AC-9 closed (a resume presenting a DIFFERENT approval at the same
  `attempt_id` would be accepted). The compare must keep the approval.
- **(c) scope the compare to "authority fields only" — WRONG, same reason.** `approval_digest`
  IS an authority field for AC-9's purpose (a different approved base/code is a different
  authorization); narrowing the compare to lease/scope defeats AC-9.
- **(b) build the approval from a COMMIT-STABLE input — CORRECT direction.** The invariant the
  fix must satisfy: **the approval inputs used in the rebuild are byte-identical to those at
  first admission, derived from a source that does not drift across the commit/crash boundary,
  and NOT read back from the stored record (reading from storage makes the AC-9 compare
  trivially true and defeats it).**

**Mechanism is DEFERRED to a focused design pass — do NOT hardcode one here, because the
obvious candidate is already falsified.** `base_sha = head_sha^` (parent of the committed head)
gives `H0` on the non-prebuilt path — but the PREBUILT path (`publishing.py:157`) has
`HEAD = the prebuilt commit` when S1 runs, so today `base_sha = head_sha` (the commit ITSELF,
not its parent). So `base_sha` already means DIFFERENT things on the two paths, and `head_sha^`
is wrong for prebuilt. Nor is `base_sha` redundant-given-`head_sha` (that would tempt "just drop
it") while it still carries this prebuilt-vs-not distinction. The realization must reconcile
both paths — likely by binding the approval to a commit-stable value captured from the SAME
post-commit git state on every attempt (mirroring how `attempt_id` is computed post-commit and
threaded), reconciled with the prebuilt path — and is the kind of entangled-identity sub-problem
that motivates the split recommendation in §12. **This plan pins the DEFECT, the INVARIANT, the
rejected alternatives, and AC-13; the exact realization is called out as needing its own design
pass.** Scope note: this is PUBLISH-SPECIFIC — `readmit_advanced_head` takes `approval` as a
caller-supplied parameter (`c1da62a` `verbs.py:87`) and keys on an already-advanced, stable
`new_head_sha`; it does not re-derive `base_sha` from a drifting `rev-parse HEAD`.

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
  before allocating. **The `head_sha` here is the POST-COMMIT head, bound inside `execute`
  from `BrokerRequest.head_sha` (S3/S3b) — NOT a pre-commit HEAD captured in S1 (round-1 CR,
  grok — verified). On the non-prebuilt path the commit happens in `publishing.py` AFTER S1
  builds the admission (`publishing.py:188` captures the head, `:196` calls `execute`), so a
  pre-commit binding would key the resume off a head that changes and dedup would never
  fire.** This also settles the fork TOWARD deterministic: BLOCKING-2's restored
  conflict-compare (§3, AC-9) is reachable ONLY under a deterministic `attempt_id` — with
  `uuid4`, dedup never fires and the compare is dead code.
  **ROUND-2 correction (grok): "compute it in `execute`" is necessary but NOT sufficient — it
  must also be THREADED into the factory.** `make_request` takes `(epoch, attempt_id)` (§3),
  and `execute` passes the deterministic id as `admit_next`'s `attempt_id` argument, which is
  forwarded into `make_request` on the allocate AND rebuild calls. If `make_request` took
  epoch alone, `fencing.lease()` would default `attempt_id` to `uuid4` (`fencing.py:54`) and
  the STORED request would carry a random id ≠ the deterministic dedup argument — idempotency
  silently broken. The rejected alternative (rebuild reads `attempt_id` from the stored
  record) does not help: the allocate path must STORE the deterministic id or no resume ever
  dedups. Head-stability holds because a completed publish short-circuits at `execute:58`
  before allocation, so allocation is only reached post-commit with a fixed HEAD.
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
  succeeds and records epoch 3 (strictly above). **Falsifier (CORRECTED, round-2 codex):**
  revert S3 to `admit(request.admission)` — i.e. route publish back through the LEGACY
  caller-epoch admit with `lease_epoch=1` — → the post-readmit publish raises
  `PermissionError("stale epoch")` at `admission.py:49` (`1 < 2`). **Observable:** a
  `PermissionError`. **Do NOT use "S1 hardcodes `lease_epoch=1` while S3 stays on
  `admit_next`" as this AC's falsifier — it does NOT raise stale epoch:** `admit_next` has no
  `lease_epoch < max` fence, so it would record `epoch=3` with a divergent
  `request.lease_epoch=1` and (absent the §3 enforcement) SILENTLY accept. That mutation — and
  the enforcement that catches it — is AC-10, not this AC. **Injection anchor:** `execute`'s
  admit call (`verbs.py:65`). **Positive control:** assert the publish returns
  `accepted=True` with `granted_epoch == 3` — not merely "did not raise."

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
  epoch domains" alternative the maintainer rejected) → the two sequences each restart at 1.
  **Observable (CORRECTED, round-2 audit): the recorded epoch VALUES become `[1,1,2,2]`, NOT
  a raised exception.** Separate stores are each independently monotonic, so NOTHING trips a
  fence — the assertion must read the recorded epoch SEQUENCE (`[r.epoch for r in
  store.replay()]`), not expect a `PermissionError`. (Naming "the fence trips" was itself an
  imprecise falsifier — the exact class codex told us to assume another of; the test asserts
  on values, and would have PASSED under the mutation had it only caught a raise.)
  **Injection anchor:** `_RoutingBrokerService._service_for` routing — both `execute` and
  `readmit_advanced_head` must resolve the SAME per-repo root (`live.py`). **Positive
  control:** all four accepted AND the sequence is exactly `[1,2,3,4]`. **Scope guard:** the
  store is per-repo (see #208 global-poison memory); a SECOND repo's first admission
  independently starts at 1 — assert that too, so the plan is not mis-read as one GLOBAL
  allocator.

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

- **AC-9 — a CONFLICTING resume (same `attempt_id`, different request) is REFUSED, not
  silently accepted (grok round-1 blocking — the guard the 288a `admit_next` dropped).** Seed
  an admission via `admit_next` at `attempt_id=X`. Re-drive `admit_next` with the SAME
  `attempt_id=X` but a `make_request` that rebuilds to DIFFERENT authority/approval/predicate
  fields: it RAISES (conflicting idempotency), appends NO second record. **Falsifier:**
  restore the 288a dedup that does `return record` with no rebuild/compare → the conflicting
  resume is returned ACCEPTED (and under S8 that is "authorized to append the ledger and
  merge"). **Injection anchor:** the `attempt_id` dedup return inside `admit_next` (S6, §3) —
  assert the rebuild `make_request(prior.epoch, attempt_id)` + compare is present in `src` before
  mutating (a mutation against a moved anchor is a silent no-op). **Positive control
  (load-bearing):** a GENUINE resume — same `attempt_id`, a request that rebuilds to the
  IDENTICAL fields at `prior.epoch` — dedups to the SAME record with NO false conflict,
  proving the compare is not over-strict and that idempotency (the whole point of
  `admit_next`) is preserved. **Reachability:** meaningful ONLY under §6's deterministic
  `attempt_id`; with `uuid4` the dedup never fires. **Wave:** step-1 (it mutates `admit_next`,
  which step (1) re-lands), not wave-0.

- **AC-10 — the broker's allocated epoch is ENFORCED, not merely recorded (round-2 codex
  blocking — the falsifier that could not fire).** Call `admit_next` with a `make_request`
  that IGNORES its `epoch` argument and builds a request at `lease_epoch=1` (a mis-built
  factory), against a store whose `max` epoch is ≥ 2 (seed one readmit first). `admit_next`
  RAISES `ValueError` (allocated epoch not honored) and appends NO record. **Falsifier:**
  remove the `request.lease_epoch == epoch` enforcement from `admit_next` → the divergent
  request is SILENTLY appended as `AdmissionRecord(epoch=max+1, request.lease_epoch=1)`.
  **Observable:** the un-enforced build does NOT raise and the store grows by one record whose
  `epoch != request.lease_epoch` — the assertion reads that field divergence, not just a
  raise. **Injection anchor:** the `assert request.lease_epoch == epoch` line in `admit_next`
  (S6) — assert it is present in `src` before mutating. **Positive control:** a CORRECT
  `make_request` that honors its `epoch` argument is ACCEPTED and records
  `epoch == request.lease_epoch == max+1` — proving the check gates only divergence, not every
  admit. **Why this AC exists:** without it, "the broker allocates the epoch, the caller never
  chooses it" (§1's ratified constraint) is UNVERIFIED — `admit_next` records `max+1` but
  trusts the frozen request to carry it, and neither request validation nor the default policy
  rejects a divergence (the `lease_epoch < max` fence would miss `allocated==2`). **Wave:**
  step-1 (it mutates `admit_next`), not wave-0.

- **AC-11 — the broker's dedup identity is ENFORCED, not merely trusted (round-3 codex+grok
  blocking — the round-2 `attempt_id` decision had not reached S1, so a factory could store an
  unfindable record; mirrors AC-10, one field over).** Call `admit_next(make_request,
  attempt_id=X, …)` with a `make_request` that IGNORES its `attempt_id` argument and lets
  `factory.lease()` default it to `uuid4` (`fencing.py:54`) — the mis-built factory — against a
  fresh store. `admit_next` RAISES `ValueError` (supplied dedup id not honored) and appends NO
  record. **Falsifier:** remove the `request.attempt_id == attempt_id` enforcement from
  `admit_next` AND keep the id-ignoring factory → the divergent request is SILENTLY appended as a
  record whose `request.attempt_id` is a random `uuid4`, keyed off a value no future retry can
  reproduce. **Observable:** the un-enforced build does NOT raise and the store grows by one
  record whose `request.attempt_id != attempt_id` — the assertion reads that FIELD DIVERGENCE
  (assert the stored record's `attempt_id` against the supplied `X`), NOT a bare `pytest.raises`
  (an unrelated raise would satisfy that). **Injection anchor:** the `assert request.attempt_id
  == attempt_id` line in `admit_next` (S6) — assert it is present in `src` before mutating.
  **Positive control:** a CORRECT `make_request` that threads its `attempt_id` argument into
  `factory.lease(..., attempt_id=attempt_id)` is ACCEPTED and records `request.attempt_id == X`
  — proving the check gates only divergence, not every admit. **Why this AC exists:** the dedup
  identity is what makes `admit_next` idempotent; if the stored id is trusted rather than
  enforced, a factory bug (the round-2 defect: S1 defaulting to `uuid4`) silently kills
  idempotency and AC-9's compare becomes dead code with NO test dying. This is the UNIT
  enforcement; AC-12 is its end-to-end behavioral counterpart through the live S1 seam. **Wave:**
  step-1 (it mutates `admit_next`), not wave-0.

- **AC-12 — an IN-FLIGHT publish retry REUSES its admission (same epoch, no second record),
  driven through the LIVE S1 boundary (round-3 codex blocking — the behavioral guard AC-3
  structurally CANNOT provide).** Seed the evidence store with a `PROVIDER_CALL_IN_FLIGHT`
  record for the publish `(repo, branch, head_sha)` — NOT a terminal state — and **assert that
  precondition holds before retrying** (`current.state is PROVIDER_CALL_IN_FLIGHT`): without this
  guard the test silently degrades into a completed-replay that short-circuits at
  `verbs.py:58`→`:59` (`_replay`) BEFORE admission, and the falsifier goes vacuous in BOTH arms
  (this is the exact "assert the injection landed" discipline — the seed IS the injection).
  Then re-drive the publish through the LIVE S1 seam (`_default_build_admission` → `execute`),
  reconstructing the `make_request` closure: because the record is IN-FLIGHT it FALLS THROUGH the
  `:58` terminal short-circuit to `admit` at `verbs.py:65`, so `admit_next` dedups on the
  deterministic `attempt_id` and returns the SAME record — NO new epoch allocated, admission
  record COUNT unchanged. **Falsifier:** have S1 bind a fresh `uuid4` `attempt_id` (the
  pre-round-3 one-arg `make_request(epoch)` behavior, `fencing.py:54` default) → the retry's
  dedup key differs, `admit_next` allocates a SECOND epoch and appends a SECOND admission record
  for one publish. **Observable:** admission record COUNT +1 and a new epoch — read the
  count/epoch sequence, NOT a raise. **Why AC-3 cannot cover this:** AC-3 replays a COMPLETED
  publish, which returns at `verbs.py:59` (`_replay`) BEFORE `admit` at `:65` is ever reached —
  so AC-3 never exercises the admission-dedup path and cannot see whether S1 bound a random id.
  ONLY an IN-FLIGHT record falls through to admission. AC-12 is the test that would have caught
  THIS round's defect (S1 shipping the one-arg signature). **Injection anchor:** S1's
  `make_request` closure (`train_runner.py:138`) — assert it threads the supplied `attempt_id`
  into `factory.lease(..., attempt_id=…)` in `src` before mutating. **Positive control:** a retry
  at a DIFFERENT `head_sha` (→ a different deterministic `attempt_id`) DOES allocate a new epoch
  and append a record — proving dedup, not a universal no-op. **Wave:** rides with the
  publish-migration tests (step 2) — it needs the migrated live S1 seam AND `admit_next`, neither
  on `main`; not wave-0.

- **AC-13 — a LEGITIMATE post-crash publish retry DEDUPS, it is not rejected by the
  conflict-compare (round-4 codex blocking — the failure the round-2 fix INTRODUCED; guards §5b's
  commit-stable invariant).** A publish records an admission (epoch E, `attempt_id` from the
  post-commit `head_sha`, `approval_digest(H0)`); the publish then CRASHES post-commit; the
  retry reconstructs the admission from POST-COMMIT git state (a fresh S1 run, NOT a captured
  closure — see below) and re-drives `execute`. The retry MUST dedup to the SAME record — same
  epoch E, NO new allocation, NO `ValueError`. **Falsifier:** build `base_sha` from a
  reconstruction-time `rev-parse HEAD` (the current `train_runner.py:119` behavior) → on the
  retry `base_sha = H1 ≠ H0`, `approval_digest` diverges, the round-2 conflict-compare finds
  `rebuilt != prior.request` and RAISES `ValueError("conflicting idempotency key")` on the
  legitimate retry. **Observable:** a `ValueError` (the retry is WRONGLY rejected) under the
  drift; under the §5b fix the retry returns the prior record with `granted_epoch == E`. **Model
  the CRASH faithfully (this AC's own vacuity trap):** the retry MUST reconstruct the admission
  by re-running S1 against post-commit git state — reusing an in-memory captured closure would
  carry `base_sha=H0` forward and MASK the drift, so the falsifier would pass vacuously against
  the real bug. **Path-entered precondition (assert it, per AC-12's discipline):** assert the
  retry's `attempt_id` dedup HITS — the prior record is present and found — BEFORE asserting the
  compare outcome; if the dedup misses, the retry allocates fresh, nothing compares, and both
  arms pass vacuously. **Positive control (proves the fix does NOT gut AC-9):** a retry at the
  same `head_sha`/`attempt_id` but a genuinely DIFFERENT approval (e.g. a different owned-code
  subset → different `effective_code` → different `approval_digest`) STILL RAISES — the
  commit-stable fix must reject a real conflict while accepting a faithful retry. **Injection
  anchor:** the `base_sha` derivation feeding `factory.approval(...)` (`train_runner.py:119`) —
  assert the commit-stable derivation is present in `src` before mutating. **Wave:** rides with
  the publish-migration tests (step 2); not wave-0. **Note:** the exact commit-stable mechanism
  is §5b's deferred design pass — this AC pins the BEHAVIOR (faithful retry dedups, real conflict
  rejects) independent of which realization §5b lands.

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
  `broker_client` threading at the `:3084` call. **Wave-0 red on `main` — the assertion MUST be
  POSITIVE, not "no append" (round-4 grok B1).** Assert `result["status"] == "merged"` AND that
  the `:1139` ledger record for the advanced head was written — the BUG is that the seam merged
  despite revocation. Phrasing the wave-0 assertion as a POSITIVE outcome is load-bearing: a
  scenario that silently never reaches `:1139` (multi-commit / non-PASS / gate-fail delta)
  yields `status != "merged"`, which FAILS the wave-0 test LOUDLY on `main` rather than passing
  it green — so the wave-0 red cannot be vacuous. A negative "no `:1139` append" assertion would
  PASS on `main` whenever the seam is unreached, collapsing the wave-0 claim for the plan's
  strongest test. **Path-entered control (both waves):** assert the delta actually reaches the
  append site — the same "assert the seed/path landed" discipline as AC-12's IN-FLIGHT check.
  **Positive control (POST-IMPL, green-time — NOT wave-0):** with `epoch_blocked = False`, the
  IDENTICAL seam re-admits at an allocated epoch and the head advances — this proves the seam is
  reachable with this exact setup, so the revoked run's "no advance" isolates revocation as the
  cause, not an unreached path.

- **AC-8b — the CRASH-RESUME delta re-admit is subject to revocation (the second bypass
  codex found).** Pre-extend the durable provenance to the live head so it passes the gate
  (`resolved_final == live_head_sha and _gate_passes()` → the `:1016` crash-resume branch
  fires), then drive the SAME merge-loop seam against a revoked store: the node does NOT
  re-admit — no `:1016` ledger append, falls through to the guard. **Falsifier:** restore the
  direct `append_record` at `train_runner.py:1016` (the crash-resume bypass) → a revoked
  resume takes the early append and merges. **Injection anchor:** the `:1016` append
  specifically (assert `head_sha=live_head_sha` at that append in `src` before mutating, so
  the mutation cannot be a silent no-op against a moved anchor). **Wave-0 red on `main` — POSITIVE
  assertion, not "no append" (round-4 grok B1).** Assert `result["status"] == "merged"` AND the
  `:1016` ledger record was written — the BUG is that a revoked crash-resume merged. If the
  pre-extended provenance does NOT actually route to the `:1016` branch (the gate
  `resolved_final == live_head_sha and _gate_passes()` not satisfied), `status != "merged"` and
  the test FAILS LOUDLY on `main` instead of passing green. **Path-entered control (both
  waves):** assert the run entered the `:1016` crash-resume branch specifically (e.g. the
  crash-resume provenance was consumed / the early-append site was reached), not merely that no
  bad merge occurred — the seed-precondition discipline of AC-12 applied to a code branch.
  **Positive control (POST-IMPL, green-time — NOT wave-0):** with `epoch_blocked = False`, the
  crash-resume DEDUPS to the SAME `granted_epoch` (idempotent resume, per §6/AC-6b) and the head
  advances — proving the gate refuses only under revocation, not that the crash-resume path is
  dead (which would make the revoked assertion vacuous).

- **AC-7 — CHANGELOG/doc retraction present and self-consistent.** A repo check (grep-level
  is sufficient) asserts (a) `CHANGELOG.md` contains the byte-neutrality RETRACTION entry
  for publish, and (b) NO tracked doc asserts publish byte-neutrality *alongside*
  renumbering. **Falsifier:** leave `design-fab-integration-milestone.md` item 4 or any doc
  claiming "publish remains byte-neutral" once renumbering ships → the check fails.
  **Injection anchor:** `CHANGELOG.md` + `design-fab-integration-milestone.md`. **Positive
  control:** the check PASSES on the amended tree (so it is not an unconditional failer).

### Falsifier re-audit — does each mutation actually reach an assertion, and via WHAT observable? (round-2, per codex directive "assume another")

Codex named AC-1; the audit found a SECOND imprecise falsifier (AC-4) and mapped the
reachability dependencies. The question asked of every AC is not "does it fail" but "what
does the assertion SEE" — an AC whose stated mechanism is a raise that never happens is
vacuous even if a different assertion would catch it.

| AC | Observable the assertion reads | Fires? | Notes / dependency |
|---|---|---|---|
| AC-1 | `PermissionError` (stale epoch) | ✅ after fix | falsifier CORRECTED to the `admit()`-revert (raises via legacy fence); the silent-accept variant moved to AC-10 |
| AC-2 | acceptance where refusal expected | ✅ | regression-guard + in-lock split |
| AC-3 | admission record COUNT +1 / new epoch | ✅ | positive control (replay ⇒ no new record) fails on a correct impl UNLESS the §6 locus is fixed — this AC guards the locus |
| AC-4 | epoch VALUES `[1,1,2,2]` vs `[1,2,3,4]` | ✅ after fix | falsifier CORRECTED: separate stores are independently monotonic, NOTHING raises — assert the sequence, not a raise |
| AC-5 | duplicate/non-contiguous epoch under a 2-writer barrier | ✅ | value-based |
| AC-6a | "blocked" where prior result expected | ✅ | regression-guard |
| AC-6b | acceptance (ledger append) where refusal expected | ✅ | scenario needs a dedup-able resume ⇒ requires the §6 deterministic `attempt_id` |
| AC-7 | grep check failure | ✅ | doc-level |
| AC-8a / AC-8b | `status == "merged"` + the `:1139`/`:1016` ledger record written despite revoked store | ✅ (wave-0 red) | production-seam bound; wave-0 assertion is POSITIVE (round-4 grok B1) so an unreached seam FAILS loud on `main`, not vacuously green |
| AC-9 | conflicting resume accepted / same record for a different request | ✅ | dead code under `uuid4` ⇒ requires the §6 deterministic `attempt_id` |
| AC-10 | record appended with `epoch != request.lease_epoch` (no raise) | ✅ | NEW; guards the allocated-epoch enforcement |
| AC-11 | record appended with `request.attempt_id != attempt_id` (no raise) | ✅ | NEW; guards the dedup-identity enforcement — mirrors AC-10, one field over |
| AC-12 | admission record COUNT +1 / new epoch on an IN-FLIGHT retry | ✅ | NEW; falsifier is vacuous UNLESS the seed is `PROVIDER_CALL_IN_FLIGHT` (else short-circuits at `:59` before `admit` at `:65`) — the trap this AC itself guards; AC-3 (completed replay) cannot reach the admission path |
| AC-13 | `ValueError` on a faithful retry (drift) vs `granted_epoch == E` (fixed) | ✅ | NEW; falsifier requires (a) the crash modelled by re-running S1 on post-commit git state, NOT a captured closure, and (b) the `attempt_id` dedup HIT asserted — else vacuous in both arms |

**Three dependency clusters the audit makes explicit** (the round-2 AND round-3 fixes, so the
ACs that ride on them are now live): the EPOCH-ENFORCEMENT (§3, codex round-2) makes AC-1's
real distinction and AC-10 fire; the ATTEMPT_ID-ENFORCEMENT (§3, round-3) makes AC-11 fire and,
propagated to S1, makes AC-12's mutation observable; the DETERMINISTIC-`attempt_id` LOCUS
(§3/§6, grok, propagated to S1 in round-3) is a precondition for AC-3's positive control,
AC-6b's scenario, AC-9's compare, and AC-12's dedup to be anything but dead code. AC-12 carries
its OWN reachability precondition beyond the cluster: the seeded evidence record must be
`PROVIDER_CALL_IN_FLIGHT`, or admission is never reached and the falsifier is vacuous in both
arms. **Fourth cluster (round-4): APPROVAL-COMMIT-STABILITY (§5b) gates AC-13** — the faithful
retry can only dedup (rather than be wrongly rejected) once `approval_digest` is commit-stable;
AC-13's falsifier is the current drift. A reviewer can check this table against the tests: any AC
whose "fires?" is ✅ must have an assertion reading the named observable, not a `pytest.raises`
where the audit says "values" or "count."

### Path-entered re-audit — if the scenario silently never reaches the seam, does the assertion still pass? (round-4, per grok B1 "sweep ALL fourteen")

Grok named AC-8a/8b; the discipline is general. For every AC, name the SPECIFIC proof that the
seam was ENTERED — a positive observable that cannot occur on an unreached path, or an explicit
positive control. An AC whose core assertion is a NEGATIVE ("X did not happen") is vacuous on any
scenario that silently never reaches the seam, unless a positive control proves reachability.

| AC | Core assertion shape | Path-entered proof |
|---|---|---|
| AC-1 | POSITIVE — `accepted=True`, `granted_epoch == 3` | the accept/epoch value cannot be read on an unreached publish |
| AC-2 | negative (refused) | positive control: `epoch_blocked=False` → the SAME publish is accepted (proves entry); in-lock red-first test asserts the admit was reached |
| AC-3 | negative (no new record) | positive control: DIFFERENT `head_sha` → a record IS appended (proves `execute`+admit reachable) |
| AC-4 | POSITIVE — epoch sequence `[1,2,3,4]` | all four accepts are positive reads |
| AC-5 | POSITIVE — epochs `1..N` present | value read over N appends |
| AC-6a | negative (not blocked) | positive control: DIFFERENT `head_sha` IS refused at `:64` (proves `:58` reached) |
| AC-6b | negative (refused, no append) | positive control: non-revoked resume dedups to the SAME `granted_epoch` (proves the resume path is entered) |
| AC-7 | doc grep | N/A (static check, no seam) |
| **AC-8a / AC-8b** | **negative (no re-admit/merge)** | **round-4 FIX: wave-0 assertion made POSITIVE (`status=="merged"` + the specific ledger record) so an unreached seam FAILS loud; green-time positive control (`epoch_blocked=False` advances) proves reachability** |
| AC-9 | POSITIVE — a `ValueError` raise | the raise cannot occur on an unreached compare; positive control: genuine resume dedups (no false conflict) |
| AC-10 | POSITIVE — field divergence value / raise | the divergent record / raise is a positive read |
| AC-11 | POSITIVE — field divergence value / raise | mirrors AC-10 |
| AC-12 | negative (no 2nd record) | round-3 FIX: asserts the `PROVIDER_CALL_IN_FLIGHT` seed (path-entered) + positive control (different head → new record) |
| AC-13 | mixed (raise vs dedup) | round-4: asserts the `attempt_id` dedup HIT (prior record found) as the path-entered precondition BEFORE the compare outcome |

Two ACs needed the fix this round (AC-8a/8b); the rest already carried a positive observable or a
reachability control, shown above so the sweep is checkable rather than declared. AC-13 was built
with its path-entered precondition from the start.

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

**Step-1 test PR — red against the step-1 skeleton.** AC-3, AC-4, AC-5, AC-6b, AC-9, AC-10,
AC-11 (and the in-lock half of AC-2) mutate `admit_next` / `readmit_advanced_head` / routing,
which step (1) re-lands. Their falsifiers can only be RUN once those symbols exist, so these
tests land red against a step-1 skeleton (symbols present, bodies unimplemented or deliberately
wrong) — NOT against empty `main`. **AC-12 is red-first too but rides with the step-2
publish-migration tests, not step-1:** its falsifier mutates the LIVE S1 `make_request` closure
(step 2), which does not exist on the step-1 skeleton — so it lands red against the migrated S1
seam. Neither AC-11 nor AC-12 is wave-0 (both need `admit_next`, absent on `main`). This is still test-first — it is the primitive's own red→green —
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
per wave-0 above; AC-3/AC-4/AC-5/AC-6b/AC-9/AC-10 against the step-1 skeleton) and satisfies the
contract.

---

## 11. Ordering and what blocks what

1. **Re-land the allocator + readmit primitive** (`admit_next` with the `(epoch, attempt_id)`
   signature + `request.lease_epoch == epoch` AND `request.attempt_id == attempt_id`
   enforcement + the conflict-compare on dedup, `AdmissionPrecondition`, `readmit_advanced_head`,
   `readmit_attempt_id`, `ReadmitResult`, routing) from #337. Blocks everything. **The
   primitive-level ACs gate it: AC-4, AC-5, AC-6b, AC-9, AC-10, AC-11** (all mutate
   `admit_next`/routing; step-1 test wave). (#366's shared-lock is already in main under it.)
2. **Migrate publish to the allocator** — S1 + S2 + S3 + §5 epoch-late-binding + §6
   `attempt_id` (S1's `make_request` threads the received `attempt_id` into
   `factory.lease(..., attempt_id=…)` — round-3) + §5b commit-stable approval identity (round-4).
   Depends on (1). **This is the live-#199 risk; it gets AC-1, AC-2, AC-3, AC-6a, AC-12 (the
   in-flight retry through the live S1 seam), AC-13 (the faithful post-crash retry — §5b) and a
   byte-diff review against a live-broker fixture. §5b's commit-stable mechanism is a DEFERRED
   design pass INSIDE this step — its density is the core of the split recommendation (§12).**
3. **Docs/CHANGELOG retraction** (§9) — lands WITH (2); AC-7 gates it.
4. **Wire the readmit CONSUMER** (S8) — replace BOTH direct `append_record` sites
   (`:1016` crash-resume + `:1139` normal) with the single `_commit_readmission` →
   `broker_client.readmit_advanced_head` path, and thread `broker_client` through
   `run_train → merge loop (`:3084`) → _fab_delta_readmit`. Depends on (1). This is the
   "multi-day protocol integration" of #288 and the actual gap the flag guards. **AC-8a AND
   AC-8b gate it** (one per commit point).
5. **Flip `_FAB_DELTA_BROKER_READMIT_READY = True`** in `governed_premerge.py:76` — LAST,
   as its own gated step per the #288 landing-checklist interlock. **Depends on BOTH (4)
   consumer wiring AND (2) publish migration** (round-1 CR, grok — verified). Two failure
   modes it must not activate: **(a)** flipping while `_fab_delta_readmit` still appends
   directly ACTIVATES the exact bypass #288 exists to fix (needs (4)); **(b)** flipping while
   publish is still on `admit(lease_epoch=1)` creates MIXED ALLOCATION — the first delta
   readmit allocates epoch 2 into the shared per-repo store via `admit_next`, then the next
   live #199 publish still presents epoch 1 and the fence at `admission.py:49` raises
   `PermissionError("stale epoch")` (`1 < 2`), BRICKING every multi-node train after the
   first readmit (needs (2)). Mode (b) is the identical mixed-allocation hazard that killed
   #337 round 4 — reintroduced through the dependency graph rather than the code; an earlier
   draft over-corrected "the flag must not depend only on the primitive" into "depends on (4)
   NOT (2)," which is exactly this bug. Until this flip, the delta-shortcut ENGAGE path is
   fenced OFF by construction and the gap is unreachable.

Blocks: (2)→(1); (4)→(1); (5)→(2); (5)→(4). Publish migration (2) and consumer wiring (4)
both sequence before the flip (5) so no ENGAGE path can reach a half-migrated allocator
(mode b) or a still-bypassing consumer (mode a) — the flip requires BOTH, never "(4) alone /
the flag ignores publish." (2) and (4) are independent of EACH OTHER and may land in either
order, but both are predecessors of (5); all build on the re-landed primitive (1).

---

## 12. Scope statement + what is explicitly NOT in scope (do not over-build)

**In scope (the full #288 arc):** this is the migration plan for #288, so it covers the
allocator foundation (1), the publish migration (2) — the LIVE-#199 risk the ratification
is about — the docs retraction (3), the readmit CONSUMER wiring (4, S8/AC-8a/AC-8b — BOTH
commit points `:1016`+`:1139` via one gated path) — the seam #288 exists to fix — and the
gated flag flip (5). The flag flip is NOT a safe terminal step
until the consumer is wired AND publish is migrated (the mixed-allocation brick, grok
round-1); that dependency is fixed in §11 — the flip depends on BOTH (2) and (4). The consumer wiring is
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

### 12b. Convergence assessment + split recommendation (round-4, requested by the team-lead)

**Is this converging or churning?** Converging on the DESIGN — four rounds, eleven blocking
findings, every one verified real, and each round nailed a genuinely DIFFERENT invariant (round-1
the DAG mixed-allocation + dropped conflict-compare; round-2 epoch enforcement + attempt_id
locus; round-3 the two-arg propagation to S1; round-4 commit-stable approval identity + the
path-entered vacuity). Several were introduced by the prior round's fix — that is the signature
of a genuinely entangled sub-system, not of a wandering plan.

**But the density is NOT uniform — it is concentrated in the publish-migration half, and it is
ISOLABLE.** Discriminant checked in source: the recurring hard core is publish's IDENTITY under a
commit that moves HEAD mid-operation (epoch late-binding, deterministic `attempt_id` from the
post-commit head, and now commit-stable `approval_digest`). **`readmit_advanced_head` does NOT
share it** — it takes `approval` as a caller-supplied parameter (`c1da62a` `verbs.py:87`) and
keys on an already-advanced, stable `new_head_sha`; it never re-derives `base_sha` from a drifting
`rev-parse HEAD`. So the entangled-identity work is publish-specific, and the readmit-CONSUMER
half (S8/AC-8a/AC-8b — wire `_fab_delta_readmit` through the broker) is comparatively self-
contained (one finding cluster: the two commit points, plus the round-4 path-entered hardening).

**Recommendation (for the team-lead to ratify — NOT self-executed):** carve this into two plans
along the merge boundary the §11 DAG already implies:
- **P1 — allocator + publish migration** = steps (1)(2)(3): the re-landed primitive, the publish
  migration, and the §5b commit-stable-approval-identity design pass. This is where all the
  density lives; it gets AC-1..AC-7, AC-9, AC-10, AC-11, AC-12, AC-13.
- **P2 — readmit consumer + flag flip** = steps (4)(5), DEPENDS ON P1 merged. It gets AC-8a/AC-8b
  and owns the flag-flip interlock. Making P2 depend on P1-merged makes the mixed-allocation
  interlock (§11: flip requires BOTH publish migrated AND consumer wired) SAFER, not riskier —
  publish is already migrated on `main` before P2 begins, so the (5)→(2) edge is satisfied by a
  merge boundary rather than an in-plan ordering promise.

This is the honest "this is too big" the team-lead invited: the §5b identity sub-design deserves
focused treatment and should not gate the (simpler, ready) consumer-wiring work. **If the
team-lead prefers to keep one plan, it stands as written — the split is a delivery-sequencing
recommendation, not a correctness gap.**
