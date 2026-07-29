# Detailed migration plan: FAB ah#288 — P1 of 2: one shared monotonic epoch allocator + publish migration

*Phase alias: FABPUB (specs/phase-plans-v10.md)*

> **⚠️ THIS IS P1 OF A RATIFIED TWO-PLAN SPLIT** (maintainer, `ah#363` follow-up), carved
> along the merge boundary the §11 DAG implies. **P1 (this plan)** = the shared allocator
> (`admit_next`), the re-landed `readmit_advanced_head` primitive, and the live #199 **publish**
> migration — steps (1)(2)(3), AC-1..AC-7 and AC-9..AC-15 — where all the entangled-identity
> density lives (epoch late-binding, the deterministic post-commit `attempt_id`, and §5b
> commit-stable `approval_digest`). **P2** (`plans/detailed-fab-288-p2-readmit-consumer-20260729.md`)
> = the readmit CONSUMER wiring (`_fab_delta_readmit`) + the engage-flag flip — steps (4)(5),
> AC-8a/AC-8b — and **DEPENDS ON P1 BEING MERGED** (the mixed-allocation interlock becomes a git
> merge boundary rather than an in-document promise; see §11). The readmit PRIMITIVE re-landed
> here (step 1) is exercised at the broker level by P1's AC-4 and AC-6b; its PRODUCTION CONSUMER
> is P2.

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
  authority/approval/predicate is returned ACCEPTED — and under the readmit consumer (P2's S8)
  "accepted" means "authorized to append the ledger and merge." So on the dedup hit, AFTER `epoch_blocked`,
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
(the `epoch_blocked` ordering was the first).** RE-DERIVED against `admit()` LINE BY LINE
(round-5 codex F3 — the earlier table extended rows rather than re-deriving, and MISSED that
`admit()`'s opening guard is a COMPOUND `if self.epoch_blocked() or self.policy is None or not
self.policy(request): raise` evaluated BEFORE the dedup loop; the in-lock reorder SPLIT that
compound guard — `epoch_blocked` moved to the front (correct), but POLICY silently moved to the
end, AFTER dedup, so a dedup-hit resume returns a prior admission without ever consulting the
policy: **fail-closed → fail-open, the repo's fifteenth**). A table with a hole in it is worse
than no table — the same reason a deferral that reads as settled is worse than an open question.
Performed here for `admit()` vs `admit_next` (@ `c1da62a`), one row per element of `admit()`:

| Check in `admit()` | In `admit_next`? | Disposition |
|---|---|---|
| conflict-compare on a dedup hit (`record.request != request → ValueError`) | **DROPPED** | **MUST RESTORE** — BLOCKING-2 (round-1); AC-9 |
| explicit fence `lease_epoch < max(epoch)` (`admission.py:49`) | absent | **DELIBERATE NON-PORT for MONOTONICITY** — allocation is `max+1` in-lock, so "strictly above" holds by construction. **But it does NOT bind `record.epoch` to `request.lease_epoch`** — see the ADD below; the `<` fence is also insufficient for that (misses `allocated==2`) |
| `record.epoch == request.lease_epoch` equality (NOT in `admit()` either — a NEW guard) | **ADD** | **NEW, load-bearing** — `admit_next` allocates the epoch but trusts the frozen `request` to carry it; enforce on the allocate path (and rebuild). Beyond a straight port. BLOCKING (round-2, codex); AC-10 |
| `record.request.attempt_id == attempt_id` (the supplied dedup id; NOT in `admit()` — a NEW guard) | **ADD** | **NEW, load-bearing** — `admit_next` dedups on `attempt_id` but trusts the frozen `request` to carry it; a factory defaulting `lease()` to `uuid4` stores an unfindable record → idempotency silently broken, AC-9 compare dead. Enforce on allocate + rebuild, parallel to the epoch guard. BLOCKING (round-3, codex+grok); AC-11 |
| `epoch_blocked()` — first disjunct of `admit()`'s compound guard | reordered to FIRST in-lock | **already fixed** by the §3 in-lock reorder above (it correctly gates BOTH the dedup and allocate paths — it is evaluated before the dedup return) |
| `self.policy is None` — second disjunct (fail-closed store-state) | **DROPPED from the pre-dedup gate** | **MUST RESTORE before the dedup return** — store-state, needs no request; a store with no policy must DENY on a dedup-hit resume, not return the prior admission. BLOCKING (round-5, codex F3); AC-15. (At the LIVE seam `build_github_broker_client` substitutes `_default_admission_policy` for `None` (`live.py:79`), so `policy is None` is reachable only for a store constructed directly — the AC's UNIT arm; the reachable PRODUCTION instance is the next row.) |
| `not self.policy(request)` — third disjunct (a configured policy DENIES) | **DROPPED from the pre-dedup gate** | **MUST RESTORE on the dedup-return path**, evaluated against the rebuilt-at-`prior.epoch` request (the same object the conflict-compare rebuilds; CONFIRMED well-defined — `BrokerAdmissionPolicy = Callable[[AdmissionRequest], bool]` (`admission.py:20`) is a pure, epoch-AGNOSTIC request-predicate, so the prior-epoch rebuild is a valid argument and the dedup-path evaluation is sound) — else a real admission gate is bypassed on every resume. `admission_policy` is a designed, threaded parameter (`_RoutingBrokerService`), so a denying policy is a reachable configuration; today's default admits all, which is exactly why the reorder's fail-open is LATENT. BLOCKING (round-5, codex F3); AC-15 (real-adapter, via `build_github_broker_client(admission_policy=<denying>)`). |

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

- **S8 (the readmit CONSUMER — `_fab_delta_readmit`) is MOVED TO P2.** Re-landing the
  `readmit_advanced_head` primitive here (S4) makes it EXIST; wiring the consumer that CALLS
  it — replacing the two direct `append_record` commit points (`train_runner.py:1016`
  crash-resume + `:1139` normal) with one broker-gated `_commit_readmission` path, and
  threading `broker_client` through `run_train → :3084 → _fab_delta_readmit` — is
  `plans/detailed-fab-288-p2-readmit-consumer-20260729.md` §3 (AC-8a/AC-8b). It depends on
  THIS plan (P1) being merged. The `append_record` enumeration method that finds those two
  commit points moves with it.

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
- **(a) exclude HEAD-derived fields from the compare — WRONG, and not even expressible.**
  `AdmissionRequest` stores only the OPAQUE `approval_digest` (and `idempotency_key`) — its
  components (`roadmap_digest`, `effective_code`, `base_sha`, `verification_*`) live in
  `ApprovalBinding` and are NEVER on the compared object (`fencing.py:27-34, 63-68`). So the
  conflict-compare CANNOT selectively drop `base_sha`; "exclude the HEAD-derived field"
  necessarily means dropping `approval_digest` WHOLESALE. And `attempt_id` pins only
  `(repo, branch, head_sha)`, while `roadmap_digest`, the owned-code subset (`effective_code`),
  and `verification_*` can differ at the SAME head — so dropping `approval_digest` reopens
  exactly the hole AC-9 closed (a resume presenting a DIFFERENT approval at the same
  `attempt_id` would be accepted). The compare must keep the approval.
- **(c) scope the compare to "authority fields only" — WRONG, same reason.** `approval_digest`
  IS an authority field for AC-9's purpose (a different approved base/code is a different
  authorization); narrowing the compare to lease/scope defeats AC-9.
- **(b) build the approval from a COMMIT-STABLE input — CORRECT direction.** The invariant the
  fix must satisfy: **the approval inputs used in the rebuild are byte-identical to those at
  first admission, derived from a source that does not drift across the commit/crash boundary,
  and NOT read back from the stored record (reading from storage makes the AC-9 compare
  trivially true and defeats it).**

**Mechanism — DECIDED (round-5 codex F1; the deferral was itself the defect — an implementer
hits it on day 1, so this plan now names the realization).** Two ingredients, both required:

1. **Derive `base_sha` as `merge-base(head_sha, origin/<request.base>)` — a function of the
   COMMITTED head and the declared base ref, not of live `HEAD`-at-call-time.** This is the same
   base the broker ALREADY three-dot-diffs `owned_paths` against (`BrokerRequest.base`,
   `origin/<base>...head_sha`, `credsep.py`); aligning the approval's `base_sha` with it is the
   "bind base into the approval" step `credsep.py:226` flags as the stronger form. It is
   commit-stable: identical whether computed on the first pass or a crash-resume, because
   `head_sha` and `origin/<base>` are both stable post-commit and the publish commit sits on the
   FEATURE branch, so `origin/<base>` advancing (another train merging) pre-merge does not move
   the fork point. It **unifies the two paths** — the asymmetry that falsified `head_sha^`: on
   the NON-prebuilt path the change is one publish commit so `merge-base(H1, origin/base) = H0`
   (the parent, correct); on the PREBUILT path the change is the whole branch so `merge-base` is
   its fork-point vs base (correct, and a strict improvement over today's degenerate
   `base_sha = head_sha`). `head_sha^` was wrong for prebuilt (strips one commit of a
   multi-commit branch); `merge-base` is right for both because it asks the base-relative
   question directly. It does NOT reopen AC-9's hole: `approval_digest` still folds
   `roadmap_digest`, `effective_code`, `dependency_shas`, and `verification_*`, so a DIFFERENT
   approval at the same head still diverges (AC-13's positive control). And it re-derives from
   stable git state rather than reading the stored record — honoring the invariant above (reading
   from storage would make the AC-9 compare trivially true).
2. **Bind it at the POST-COMMIT seam, not at pre-commit S1.** S1's pre-commit `base_sha`
   (`train_runner.py:119`, a live `rev-parse HEAD`) is **NOT identity-bearing** — it is
   superseded. The commit-stable `base_sha` is computed once, from post-commit git state, at the
   same seam that binds the deterministic `attempt_id` post-commit (round-3/S3b), and threaded
   into `factory.approval(...)` on BOTH the allocate path AND the dedup-rebuild path inside
   `admit_next`'s `make_request(epoch, attempt_id)` — so first-pass and resume compute BYTE-
   IDENTICAL approval inputs by construction. (This is the round-3 propagation discipline: the
   derivation lives at ONE seam and every rebuild routes through it; a second live-`HEAD`
   derivation anywhere reintroduces the drift.)

**Operational precondition (stated, not silent).** `merge-base(head_sha, origin/<base>)` requires
`origin/<base>` to be resolvable at the binding seam — the broker already depends on it (it
three-dot-diffs `origin/<base>...head_sha` in `credsep.execute`), so the reference is available in
the same context. If it is UNRESOLVABLE the derivation must fail CLOSED: no `base_sha` →
`compute_approval_digest` raises `ValueError("approval evidence is incomplete")` (`fencing.py:38`),
never silently substituting a live `HEAD` (which would reintroduce the drift this fix removes).

**Verified safe against the broker's execute path (the F2-class check, done for `base_sha`'s
consumers).** Changing `base_sha`'s derivation cannot spuriously reject a publish: the broker's
`credsep.execute` owned-scope reconciliation diffs against `request.base` (the ref NAME), which
it explicitly notes is "*not the digest-bound base_sha*" (`credsep.py:226`); nothing in the
execute path compares the approval's `base_sha`. `InvalidationTrigger.BASE_SHA_CHANGED` is
confined to the downstream-merge invalidation model (`reconcile.py:66`), a separate consumer that
detects a legitimately-moved base across a MERGE, not a publish crash-retry. `base_sha` is
therefore consumed ONLY by `compute_approval_digest`; re-deriving it is self-contained.

### 5c. `execute` finalizes the frozen `BrokerRequest` from the allocated record (round-5 codex F2)

**The construction seam the plan's audit had not specified — Fixes 1 and 2 are ONE seam.**
`admit_next` allocates the epoch in-lock and BUILDS the finalized `AdmissionRequest` via
`make_request(epoch, attempt_id)` (carrying the allocated epoch, the deterministic `attempt_id`,
and the merge-base `base_sha` above), returning it as `record.request`. But `BrokerRequest` is
`@dataclass(frozen=True)` with `admission: AdmissionRequest` — a CONCRETE field, not a callable;
**a factory cannot cross that boundary, so `execute` must reconstruct the frozen request** with
the finalized admission — `dataclasses.replace(request, admission=record.request)` — and pass
THAT to `self.adapter.execute(...)`, so every downstream consumer of `request.admission` sees the
finalized object, not the pre-allocation S1 admission. **The class is ONE producer + SIX consumers,
and it took TWO enumeration passes to see the whole of it — because the type is changing,
construction sites are a SEPARATE enumeration pass from read sites.** Three successive
`.admission`-READ sweeps (codex 3, lead 4, this plan's re-enumeration 6) each found more consumers
and none grepped for the CONSTRUCTOR — the same shape as the round-3 propagation defect (thorough
within the frame, and the frame was wrong). **PRODUCER (1) — `publishing.py:196`** builds the ENTRY
`BrokerRequest(BrokerVerb.PUBLISH_COMMITTED_BRANCH, admission, …)` from the caller-supplied
`admission` param (`:93`, guarded `is None` at `:194`). That entry admission is S1's STALE,
non-identity-bearing one (`base_sha=H0`); **`:196` is NOT where the correctly-keyed admission is
produced** — `admit_next` is (post-commit, in-lock, carrying epoch E + deterministic `attempt_id` +
merge-base `base_sha`), and §5c's `dataclasses.replace(request, admission=record.request)` is the
stale→finalized SWAP. The type change lands at `:196` (the frozen constructor must be satisfied)
even though the correct VALUE is admit_next's — which is exactly why AC-14 asserts the adapter sees
the RECONSTRUCTED admission, not the one `:196` threaded in. **CONSUMERS (6) across three modules —**
the sites that then READ `request.admission` and require it to be the concrete, correctly-keyed
object: `verbs.py:65` `admit(request.admission)` (the whole-object handoff — a mis-built admission
surfaces here FIRST, caught by AC-10/AC-11's enforcement), `verbs.py:40` `.admission.idempotency_key`,
`credsep.py:123/:131/:315` `.admission.idempotency_key` (terminal evidence), and
`adapters/base.py:29` (`AdapterExecutionRequest.__post_init__` hard-RAISES unless
`admission.attempt_id == attempt_id`). **Honest stakes — verified, do not overstate:** on the
PUBLISH path the `credsep` terminal-evidence `idempotency_key` is INFORMATIONAL — `verbs.execute`
persists the evidence keyed by the `_dedup_key` (`publish_committed_branch_idempotency_key`, the
`(repo, branch, head)` triple) via `record_terminal(EvidenceRecord(key, …))` and DISCARDS the
adapter evidence's key field (`verbs.py:66-73`). So reconstruction is an OBJECT-GRAPH-CONSISTENCY
requirement (the frozen request the adapter/consumers see must carry the finalized admission), and
it is FUNCTIONAL for the CLASS members reached by OTHER verbs — `verbs.py:40` (the non-publish
dedup key) and `adapters/base.py:29` (the attempt_id invariant) — not a live publish mis-label. **Of the six, the PUBLISH hot path reaches four**
(`verbs.py:65` and the three `credsep` terminal-evidence sites); `verbs.py:40` is the NON-publish
dedup branch (publish keys on `publish_committed_branch_idempotency_key(repo, branch, head)`,
`verbs.py:35-39`) and `adapters/base.py:29` is the bounded-adapter path for other verbs — its only
consumer `run_bounded` is wired to the `claude`/`codex`/`outside_agent` execution adapters (NEVER
the publish adapter `credsep`), and `AdapterExecutionRequest` has ZERO src construction sites
(built only in `test_convergence_adapters.py`), so `base.py:29` is CATEGORICALLY
non-publish-reachable. Both are the SAME class but reached by other verbs, so the finalized
construction must satisfy them structurally even though AC-14 exercises the four publish-reachable
ones — and a test that makes `base.py:29` itself FIRE needs an agent-execution verb, out of P1's
publish scope (a publish-driven assertion that it raises would be vacuous).

**This plan now pins the DEFECT, the INVARIANT, the rejected alternatives, the DECIDED mechanism
(merge-base + post-commit binding + `execute` reconstruction), and AC-13 + AC-14.** Scope note:
this is PUBLISH-SPECIFIC — `readmit_advanced_head` takes `approval` as a caller-supplied parameter
(`c1da62a` `verbs.py:87`) and keys on an already-advanced, stable `new_head_sha`; it does not
re-derive `base_sha` from a drifting `rev-parse HEAD`. `refresh_downstream_after_merge` likewise
takes `base_sha` as a supplied field (`refresh.py:31,60`), not a live read, so it does not drift.

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
  **Discriminating observable for the in-lock test (round-4 self-review — "refused" alone is
  vacuous):** a plain "refused" can be satisfied by the `execute:64` PRE-check WITHOUT ever
  entering the in-lock body — the same seed-vacuity class. The in-lock test MUST arrange the
  revocation to land AFTER the pre-check passes but BEFORE the in-lock body (the #366 race:
  seed `epoch_blocked = False` at entry, flip it `True` at a barrier between the outside-lock
  entry check and the in-lock re-check), and its FALSIFIER must be **removing the in-lock
  `epoch_blocked()` re-check specifically** (not the `:64` pre-check) → the race-revoked publish
  is ACCEPTED. If the refusal came from `:64`, removing the in-lock check would not change the
  outcome and the test would not be red — so red-on-removal-of-the-in-lock-check is exactly the
  observable that proves the in-lock path was entered.

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
  resume is returned ACCEPTED (and under the readmit consumer (P2's S8) that is "authorized to
  append the ledger and merge"). **Injection anchor:** the `attempt_id` dedup return inside `admit_next` (S6, §3) —
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
  anchor:** the `base_sha` derivation feeding `factory.approval(...)` — under §5b's DECIDED
  mechanism this is `merge-base(head_sha, origin/<base>)` computed at the post-commit binding
  seam (NOT S1's pre-commit `train_runner.py:119` read, which §5b makes non-identity-bearing);
  assert the merge-base derivation is present in `src` (and that no live-`HEAD` `base_sha` feeds
  the rebuild) before mutating. **Sharpened falsifier (mechanism now chosen):** the rebuild
  derives `base_sha` from a reconstruction-time `rev-parse HEAD` instead of
  `merge-base(head_sha, origin/<base>)` → drift → the conflict-compare raises. **Positive
  observable:** the merge-base rebuild → dedup HIT with `granted_epoch == E`. **Wave:** rides with
  the publish-migration tests (step 2); not wave-0.

- **AC-14 — `execute` hands the FINALIZED admission (the allocated record) to the adapter, not
  S1's pre-allocation one (round-5 codex F2 — the construction seam the audit had not specified;
  §5c).** Drive the publish through `publish_committed_branch` (the `publishing.py:196` PRODUCER
  path that constructs the entry `BrokerRequest`), NOT a hand-built `BrokerRequest` handed to
  `execute` directly — a test that starts at `execute`/`admit()` with a hand-built admission PASSES
  while the real `:196`→`execute` seam stays broken (the reachability trap, the 7th-site lesson: the
  entry constructor was missed by every `.admission`-read sweep). Install a SPY adapter that
  CAPTURES the `BrokerRequest` `execute` calls it with. `admit_next` allocates epoch E and builds the
  finalized `AdmissionRequest` (`record.request`, carrying epoch E, the deterministic `attempt_id`,
  and the merge-base `base_sha`). **Assert the request handed to `adapter.execute(...)` carries the
  FINALIZED admission** — `captured.admission == record.request` (in particular
  `captured.admission.lease_epoch == E` AND `captured.admission.attempt_id == <the deterministic
  attempt_id>` — the attempt_id-preservation PROPERTY that `base.py:29` enforces for agent-execution
  verbs, asserted here on the reachable publish spy since `base.py:29` itself never fires on the
  publish path, §5c), NOT S1's admission at `lease_epoch=1`. **Falsifier:**
  have `execute` pass the pre-allocation `request` to `self.adapter.execute(...)` instead of
  `dataclasses.replace(request, admission=record.request)` → the spy captures `request.admission`
  still at `lease_epoch=1`, diverging from the allocated record. **Observable:** FIELD DIVERGENCE
  read off the CAPTURED request — `captured.admission.lease_epoch != E` — NOT a raise, and NOT the
  terminal-evidence key (on the publish path `verbs.execute` re-keys the persisted evidence by the
  `_dedup_key` and discards the adapter evidence's key, so that field is informational — asserting
  on it would be vacuous; see §5c "honest stakes"). **Injection anchor:** the `execute` line
  constructing the request handed to the adapter — assert `admission=record.request` is threaded
  in `src` before mutating. **Positive control / path-entered:** the spy adapter is actually
  INVOKED (proves the seam was entered, so the captured admission is a real handoff, not an
  unreached path); the whole-object handoff `admit_next(...)` (`verbs.py:65`) is where a mis-built
  admission surfaces FIRST via AC-10/AC-11, and AC-14 is its COMPLEMENT — the admission flowing
  OUT of the allocator into the consumers. **Stakes (§5c):** on the publish path this is an
  OBJECT-GRAPH-CONSISTENCY requirement (informational for `credsep`); it is FUNCTIONAL for the
  class members reached by OTHER verbs — `verbs.py:40` (non-publish dedup) and `adapters/base.py:29`
  (the attempt_id invariant) — which the finalized construction must also satisfy. **Wave:** rides
  with the publish-migration tests (step 2) — needs migrated `execute` + `admit_next`; not wave-0.

- **AC-15 — a DENYING admission policy is enforced on a dedup-hit resume, not bypassed
  (round-5 codex F3 — the fail-closed→fail-open the in-lock reorder INTRODUCED; §3 table).** Seed
  an admission through the migrated publish `execute` → `admit_next` at `attempt_id = X` (epoch
  E) under a PERMITTING policy. Then install a DENYING policy on that repo's store
  (`build_github_broker_client(admission_policy=<denies this request>)`) and re-drive the SAME
  publish (same `attempt_id = X` — a genuine dedup-able resume). It is REFUSED
  (`PermissionError("broker admission denied")`); no record returned, no ledger append.
  **Falsifier:** the ratified in-lock order evaluates the `attempt_id` dedup and RETURNS the prior
  record BEFORE the `not policy(request)` check → the resume returns the prior ACCEPTED record
  despite the denying policy (fail-open). **Observable:** ACCEPTANCE (a deduped record returned)
  where refusal is expected — the falsifier accepts; the fix refuses. **Path-entered precondition
  (this AC's own vacuity trap — the F3(b) sweep):** assert BOTH (a) the resume DEDUP-HITS — the
  prior record at `attempt_id = X` is present and found — AND (b) `policy(request)` is
  independently `False` for the installed policy; a permissive policy never denies and an
  unreached dedup never exercises the gate, so without both the test passes vacuously. **Use a
  DENYING policy, NOT `policy=None`:** the live factory substitutes `_default_admission_policy`
  for `None` (`live.py:79`), so a `policy=None` reopen is reachable only at the store-UNIT level
  (a legitimate second arm for the fail-closed `policy is None` disjunct), while the reachable
  PRODUCTION instance is a configured denying policy. **Injection anchor:** the position of the
  `not policy(request)` gate relative to the dedup return in `admit_next` (S6) — assert the policy
  gate PRECEDES the dedup return in `src` before mutating. **Positive control:** with a PERMITTING
  policy the identical resume dedups to the SAME `granted_epoch == E` — proving the gate refuses
  only under denial, not always. **Wave:** the real-adapter form rides step-2 (needs migrated
  publish `execute`); the `admit_next` unit form (inject the policy directly) is step-1.

> **AC-8a / AC-8b (the two S8 readmit-consumer commit points) are MOVED TO P2**
> (`plans/detailed-fab-288-p2-readmit-consumer-20260729.md` §5). They are P2's wave-0, red
> against P1-MERGED `main` — P1 does not touch the consumer, so the bypass they target
> persists until P2 wires it. AC-7 below stays in P1 (the docs retraction lands with the
> publish migration).

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
| AC-9 | conflicting resume accepted / same record for a different request | ✅ | dead code under `uuid4` ⇒ requires the §6 deterministic `attempt_id` |
| AC-10 | record appended with `epoch != request.lease_epoch` (no raise) | ✅ | NEW; guards the allocated-epoch enforcement |
| AC-11 | record appended with `request.attempt_id != attempt_id` (no raise) | ✅ | NEW; guards the dedup-identity enforcement — mirrors AC-10, one field over |
| AC-12 | admission record COUNT +1 / new epoch on an IN-FLIGHT retry | ✅ | NEW; falsifier is vacuous UNLESS the seed is `PROVIDER_CALL_IN_FLIGHT` (else short-circuits at `:59` before `admit` at `:65`) — the trap this AC itself guards; AC-3 (completed replay) cannot reach the admission path |
| AC-13 | `ValueError` on a faithful retry (drift) vs `granted_epoch == E` (fixed) | ✅ | NEW; falsifier requires (a) the crash modelled by re-running S1 on post-commit git state, NOT a captured closure, and (b) the `attempt_id` dedup HIT asserted — else vacuous in both arms |
| AC-14 | CAPTURED (spy) request's `admission.lease_epoch != E` / `admission.attempt_id` mismatch (FIELD DIVERGENCE, no raise) | ✅ | NEW (round-5 F2); §5c construction seam — driven through the `publishing.py:196` PRODUCER path (not a hand-built request), asserts the admission HANDED TO THE ADAPTER (epoch E + deterministic attempt_id, the property `base.py:29` enforces — which never fires on the publish path), NOT the terminal-evidence key (informational: `verbs` re-keys the persisted evidence by the `_dedup_key`); path-entered = the spy adapter is invoked |
| AC-15 | acceptance (deduped record) where refusal expected under a DENYING policy | ✅ | NEW (round-5 F3); falsifier vacuous unless the resume DEDUP-HITS **and** `policy(request)` is `False` (both asserted); a denying policy — `policy=None` is unreachable at the live seam (`live.py:79`) |

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
AC-13's falsifier is the current drift. **§5b's mechanism is now DECIDED (round-5), not deferred
(`merge-base` + post-commit binding + `execute` reconstruction), adding two round-5 clusters:
CONSTRUCTION-SEAM (§5c) gates AC-14 — the finalized admission must reach the consumers, its
falsifier the un-reconstructed `request` (the class is 1 PRODUCER at `publishing.py:196` + 6
consumers; the type change lands at the constructor, the finalized VALUE at `admit_next`, and
construction sites are a separate enumeration pass from read sites); and POLICY-ON-DEDUP (§3 table) gates AC-15 — a denying
policy must survive a dedup-hit resume, its falsifier the dedup-before-policy order.** A reviewer
can check this table against the tests: any AC
whose "fires?" is ✅ must have an assertion reading the named observable, not a `pytest.raises`
where the audit says "values" or "count."

### Path-entered re-audit — if the scenario silently never reaches the seam, does the assertion still pass? (round-4, per grok B1 "sweep ALL")

Grok named AC-8a/8b (now owned by P2); the discipline is general and applied to every P1 AC below. For every AC, name the SPECIFIC proof that the
seam was ENTERED — a positive observable that cannot occur on an unreached path, or an explicit
positive control. An AC whose core assertion is a NEGATIVE ("X did not happen") is vacuous on any
scenario that silently never reaches the seam, unless a positive control proves reachability.

| AC | Core assertion shape | Path-entered proof |
|---|---|---|
| AC-1 | POSITIVE — `accepted=True`, `granted_epoch == 3` | the accept/epoch value cannot be read on an unreached publish |
| AC-2 | negative (refused) | positive control: `epoch_blocked=False` → the SAME publish is accepted (proves entry); the in-lock red-first test's discriminator is red-ON-REMOVAL-OF-THE-IN-LOCK-CHECK under the #366 race (a `:64` pre-check refusal would NOT go red when only the in-lock check is removed) — so it proves the in-lock body was entered, not just "refused" |
| AC-3 | negative (no new record) | positive control: DIFFERENT `head_sha` → a record IS appended (proves `execute`+admit reachable) |
| AC-4 | POSITIVE — epoch sequence `[1,2,3,4]` | all four accepts are positive reads |
| AC-5 | POSITIVE — epochs `1..N` present | value read over N appends |
| AC-6a | negative (not blocked) | positive control: DIFFERENT `head_sha` IS refused at `:64` (proves `:58` reached) |
| AC-6b | negative (refused, no append) | positive control: non-revoked resume dedups to the SAME `granted_epoch` (proves the resume path is entered) |
| AC-7 | doc grep | N/A (static check, no seam) |
| AC-9 | POSITIVE — a `ValueError` raise | the raise cannot occur on an unreached compare; positive control: genuine resume dedups (no false conflict) |
| AC-10 | POSITIVE — field divergence value / raise | the divergent record / raise is a positive read |
| AC-11 | POSITIVE — field divergence value / raise | mirrors AC-10 |
| AC-12 | negative (no 2nd record) | round-3 FIX: asserts the `PROVIDER_CALL_IN_FLIGHT` seed (path-entered) + positive control (different head → new record) |
| AC-13 | mixed (raise vs dedup) | round-4: asserts the `attempt_id` dedup HIT (prior record found) as the path-entered precondition BEFORE the compare outcome |
| AC-14 | POSITIVE — captured admission carries epoch E + deterministic attempt_id, gated on the spy being invoked | round-5 F2: driven through `publish_committed_branch` (`publishing.py:196`), so the real entry-constructor→`execute` seam is exercised (not a hand-built request); asserts the spy adapter was INVOKED (seam entered) before reading the captured request's `admission` fields — those cannot be read on an unreached adapter call |
| AC-15 | negative (refused under a denying policy) | round-5 F3: asserts the dedup HIT **and** `policy(request)==False` as path-entered preconditions before the refusal; positive control: a PERMITTING policy → the same resume dedups to `granted_epoch == E` (proves entry, and that the gate refuses only under denial) |

The two ACs that needed the fix this round (AC-8a/8b) are now in P2; each P1 AC above carries a
positive observable or a reachability control, shown so the sweep is checkable rather than
declared. AC-13 was built with its path-entered precondition from the start.

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
- **`plans/manifest.json`** — this plan (P1, slug `fab-288-shared-epoch-allocator`, 13 ACs) is
  registered on THIS branch via `phase_loop_runtime.plan_manifest.append_entry` (the typed
  `DotfilesPlanEntry`, `status: committed`) — the deferral to avoid the #365 conflict is lifted
  now that #365 has merged. **Registered via `append_entry`, never hand-edited** (a single bad
  entry has silently disabled all plan discovery before); lifecycle transitions (`executing` →
  `completed`) are driven later by the execute-detailed runner. P2 registers its own entry
  (`fab-288-p2-readmit-consumer`, 2 ACs) on its own branch, reconciled against P1-merged `main`.
  The amendment-2 plan was never manifested on `main`, so there is no stale entry to retire.
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
scaffolding. P1's wave-0 items (AC-8a/8b having moved to P2):

- **AC-8a + AC-8b (readmit-consumer bypass) are MOVED TO P2** — they are P2's wave-0, red
  against P1-MERGED `main` (P1 does not touch `_fab_delta_readmit`, so both direct-append
  commit points `:1016`/`:1139` persist as the bypass on P1-merged `main`). See
  `plans/detailed-fab-288-p2-readmit-consumer-20260729.md` §6. They are NOT part of P1's
  wave-0.
- **AC-1 (round-4 stale-epoch incident) — red on arrival, but VIA A SEEDED RECORD, not the
  literal sequence.** ⚠️ The reproduction "publish A → readmit A → publish B" is NOT
  buildable on `main`: `readmit_advanced_head` is re-landed by step (1) and is absent, and
  the on-`main` `_fab_delta_readmit` appends to the ledger — not the broker admission store
  (that is the readmit-consumer bypass P2 fixes) — so **nothing on `main` advances the broker admission epoch via
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
seam. Neither AC-11 nor AC-12 is wave-0 (both need `admit_next`, absent on `main`). **AC-14 and
AC-15 (round-5) ride step-2's real-adapter tests** — AC-14 needs the migrated `execute` that
reconstructs the frozen `BrokerRequest` from the allocated record (§5c), and AC-15's real-adapter
form needs the migrated publish `execute`; AC-15 additionally has an `admit_next` unit form
(inject a denying policy directly) that can land in the step-1 wave. Neither is wave-0. This is
still test-first — it is the primitive's own red→green —
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

Everything else in §8 fails on arrival for its named reason (AC-1/AC-7 against `main`
per wave-0 above; AC-3/AC-4/AC-5/AC-6b/AC-9/AC-10 against the step-1 skeleton) and satisfies the
contract.

---

## 11. Ordering and what blocks what

1. **Re-land the allocator + readmit primitive** (`admit_next` with the `(epoch, attempt_id)`
   signature + `request.lease_epoch == epoch` AND `request.attempt_id == attempt_id`
   enforcement + the conflict-compare on dedup, `AdmissionPrecondition`, `readmit_advanced_head`,
   `readmit_attempt_id`, `ReadmitResult`, routing) from #337. Blocks everything. **The
   primitive-level ACs gate it: AC-4, AC-5, AC-6b, AC-9, AC-10, AC-11, and AC-15's `admit_next`
   unit form** (all mutate `admit_next`/routing; step-1 test wave). (#366's shared-lock is already
   in main under it.)
2. **Migrate publish to the allocator** — S1 + S2 + S3 + §5 epoch-late-binding + §6
   `attempt_id` (S1's `make_request` threads the received `attempt_id` into
   `factory.lease(..., attempt_id=…)` — round-3) + §5b commit-stable approval identity (round-4,
   DECIDED round-5) + §5c `execute` reconstruction of the frozen `BrokerRequest` (round-5).
   Depends on (1). **This is the live-#199 risk; it gets AC-1, AC-2, AC-3, AC-6a, AC-12 (the
   in-flight retry through the live S1 seam), AC-13 (the faithful post-crash retry — §5b), AC-14
   (the §5c construction seam), AC-15 real-adapter form (the policy gate on a dedup-hit resume)
   and a byte-diff review against a live-broker fixture. §5b's commit-stable mechanism is now
   DECIDED (round-5): `merge-base(head_sha, origin/<base>)` bound post-commit, threaded through
   every rebuild, plus §5c's `execute` reconstruction — no longer a deferred pass.**
3. **Docs/CHANGELOG retraction** (§9) — lands WITH (2); AC-7 gates it.

**Steps (4) and (5) are P2** (`plans/detailed-fab-288-p2-readmit-consumer-20260729.md`): (4)
wire the readmit CONSUMER (`_fab_delta_readmit` → `_commit_readmission → readmit_advanced_head`,
both commit points, `broker_client` threaded through `:3084`); (5) flip
`_FAB_DELTA_BROKER_READMIT_READY = True`. **P2 depends on THIS plan (P1) being MERGED** — which
makes the flag-flip interlock SAFER, not riskier: the flip must not activate while publish is
still on `admit(lease_epoch=1)` (mode (b), the mixed-allocation brick that killed #337 round 4),
and P1-migrated-publish-on-`main` satisfies that predecessor as a **merge boundary** rather than
an in-document ordering promise a reader could miss. P2 §7 owns the full interlock.

Blocks (within P1): (2)→(1); (3) lands with (2). The publish migration (2) builds on the
re-landed primitive (1). The cross-plan edge (P2 step 5)→(P1 step 2) is discharged by the P1
merge boundary.

---

## 12. Scope statement + what is explicitly NOT in scope (do not over-build)

**In scope (P1 — the allocator + publish half of the #288 arc):** the allocator foundation (1)
— the re-landed `admit_next` + `readmit_advanced_head` primitive — the publish migration (2),
the LIVE-#199 risk the ratification is about, and the docs retraction (3). The readmit CONSUMER
wiring and the gated flag flip are **P2** (steps 4/5, AC-8a/AC-8b;
`plans/detailed-fab-288-p2-readmit-consumer-20260729.md`), which depends on this plan merged.

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

### 12b. Split status (RATIFIED) — this is P1 of 2

The combined plan converged on the DESIGN over five adversarial rounds (fourteen blocking
findings, all verified real, each round a genuinely different invariant — round 5 being codex's
F1/F2/F3: the §5b deferral was not executable, the `execute` construction seam was unspecified,
and the in-lock reorder introduced a policy fail-open), but its density is
concentrated — and entangled — in the publish-migration half: publish's IDENTITY under a commit
that moves `HEAD` mid-operation (epoch late-binding, the deterministic post-commit `attempt_id`,
and §5b commit-stable `approval_digest`). The readmit-CONSUMER half does NOT share that
entanglement — `readmit_advanced_head` takes `approval` as a caller-supplied parameter
(`c1da62a` `verbs.py:87`) and keys on an already-advanced, stable `new_head_sha`. **The
maintainer ratified splitting along the §11 merge boundary:** this plan is **P1** (steps 1/2/3,
AC-1..AC-7 and AC-9..AC-15 — all the density, incl. the §5b DECIDED mechanism + §5c construction
seam); **P2**
(`plans/detailed-fab-288-p2-readmit-consumer-20260729.md`) is the readmit consumer + flag flip
(steps 4/5, AC-8a/AC-8b) and **depends on P1 merged**. Making P2 depend on P1-merged makes the
mixed-allocation interlock SAFER — publish is already migrated on `main` before P2 begins, so the
(P2 step 5)→(P1 step 2) edge is satisfied by a merge boundary rather than an in-plan promise.
